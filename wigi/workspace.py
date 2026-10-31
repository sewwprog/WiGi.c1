"""Sandboxed workspace operations for a running WiGi server:
files, code editor, terminal/Python execution, env vars, and Git/GitHub repos.
"""

from __future__ import annotations

import base64
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

ENV_FILENAME = ".wigi_env.json"
OS_STATE_FILENAME = ".wigi_os.json"
HIDDEN_SYSTEM_FILES = {ENV_FILENAME, OS_STATE_FILENAME}
MAX_TEXT_BYTES = 2 * 1024 * 1024     # 2 MB text editor cap
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB upload cap
MAX_OUTPUT_CHARS = 120_000


def resolve_safe_path(workspace_dir: Path, rel_path: str = "") -> Path:
    """Resolve `rel_path` strictly inside `workspace_dir` (prevents `..` traversal)."""
    base = workspace_dir.resolve()
    cleaned = (rel_path or "").strip().lstrip("/\\")
    if cleaned in ("", "."):
        return base
    target = (base / cleaned).resolve()
    if target != base and base not in target.parents:
        raise ValueError("Вихід за межі робочої папки сервера заборонено.")
    return target


def to_rel_posix(workspace_dir: Path, path: Path) -> str:
    base = workspace_dir.resolve()
    resolved = path.resolve()
    if resolved == base:
        return ""
    return resolved.relative_to(base).as_posix()


# ---------------------------------------------------------------------------
# Environment Variables (.wigi_env.json)
# ---------------------------------------------------------------------------

def load_env_vars(workspace_dir: Path) -> dict[str, str]:
    env_file = workspace_dir / ENV_FILENAME
    if not env_file.exists():
        return {}
    try:
        raw = json.loads(env_file.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return {str(k): str(v) for k, v in raw.items() if str(k).strip()}
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_env_vars(workspace_dir: Path, env_vars: dict[str, Any]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for k, v in env_vars.items():
        key = str(k).strip()
        if not key:
            continue
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            raise ValueError(f"Некоректна назва змінної середовища: '{key}'.")
        cleaned[key] = str(v)

    env_file = workspace_dir / ENV_FILENAME
    env_file.write_text(
        json.dumps(cleaned, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if os.name != "nt":
        try:
            os.chmod(env_file, 0o600)
        except OSError:
            pass
    return cleaned


def _build_process_env(workspace_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update(load_env_vars(workspace_dir))
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    return env


# ---------------------------------------------------------------------------
# File Manager & Code Editor
# ---------------------------------------------------------------------------

def list_directory(workspace_dir: Path, rel_path: str = "") -> dict[str, Any]:
    target = resolve_safe_path(workspace_dir, rel_path)
    if not target.exists():
        raise ValueError("Папку не знайдено.")
    if not target.is_dir():
        raise ValueError("Вказаний шлях не є папкою.")

    items: list[dict[str, Any]] = []
    for entry in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if entry.name in HIDDEN_SYSTEM_FILES or entry.name.startswith(".wigi_run_"):
            continue
        try:
            st = entry.stat()
            mtime = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            size = st.st_size if entry.is_file() else None
        except OSError:
            mtime = ""
            size = None

        items.append(
            {
                "name": entry.name,
                "path": to_rel_posix(workspace_dir, entry),
                "type": "dir" if entry.is_dir() else "file",
                "size": size,
                "modified_at": mtime,
                "is_git": entry.is_dir() and (entry / ".git").exists(),
            }
        )

    parent_rel = ""
    if target.resolve() != workspace_dir.resolve():
        parent_rel = to_rel_posix(workspace_dir, target.parent)

    return {
        "cwd": to_rel_posix(workspace_dir, target),
        "parent": parent_rel,
        "items": items,
    }


def read_text_file(workspace_dir: Path, rel_path: str) -> dict[str, Any]:
    target = resolve_safe_path(workspace_dir, rel_path)
    if not target.exists() or not target.is_file():
        raise ValueError("Файл не знайдено.")
    size = target.stat().st_size
    if size > MAX_TEXT_BYTES:
        raise ValueError("Файл занадто великий для текстового редактора (> 2 МБ).")

    raw = target.read_bytes()
    if b"\x00" in raw[:4096]:
        raise ValueError("Це бінарний файл — його можна скачати, але не редагувати як текст.")

    content = raw.decode("utf-8", errors="replace")
    return {
        "path": to_rel_posix(workspace_dir, target),
        "name": target.name,
        "size": size,
        "content": content,
    }


def write_text_file(workspace_dir: Path, rel_path: str, content: str) -> dict[str, Any]:
    if not rel_path or not rel_path.strip():
        raise ValueError("Вкажи шлях до файлу.")
    target = resolve_safe_path(workspace_dir, rel_path)
    if target == workspace_dir.resolve():
        raise ValueError("Некоректне ім'я файлу.")
    if target.exists() and target.is_dir():
        raise ValueError("За цим шляхом вже існує папка.")

    encoded = content.encode("utf-8")
    if len(encoded) > MAX_TEXT_BYTES:
        raise ValueError("Вміст перевищує ліміт 2 МБ.")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(encoded)
    return {
        "path": to_rel_posix(workspace_dir, target),
        "name": target.name,
        "size": len(encoded),
    }


def upload_base64_file(workspace_dir: Path, rel_path: str, data_b64: str) -> dict[str, Any]:
    if not rel_path or not rel_path.strip():
        raise ValueError("Вкажи ім'я файлу для завантаження.")
    target = resolve_safe_path(workspace_dir, rel_path)
    if target == workspace_dir.resolve() or (target.exists() and target.is_dir()):
        raise ValueError("Некоректний шлях для файлу.")

    try:
        raw = base64.b64decode(data_b64, validate=False)
    except Exception as exc:
        raise ValueError("Некоректні base64-дані файлу.") from exc

    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("Файл перевищує максимальний розмір 25 МБ.")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return {
        "path": to_rel_posix(workspace_dir, target),
        "name": target.name,
        "size": len(raw),
    }


def read_binary_file(workspace_dir: Path, rel_path: str) -> tuple[str, bytes]:
    target = resolve_safe_path(workspace_dir, rel_path)
    if not target.exists() or not target.is_file():
        raise ValueError("Файл не знайдено.")
    return target.name, target.read_bytes()


def make_directory(workspace_dir: Path, rel_path: str) -> dict[str, Any]:
    if not rel_path or not rel_path.strip():
        raise ValueError("Вкажи назву папки.")
    target = resolve_safe_path(workspace_dir, rel_path)
    if target == workspace_dir.resolve():
        raise ValueError("Некоректна назва папки.")
    target.mkdir(parents=True, exist_ok=True)
    return {"path": to_rel_posix(workspace_dir, target), "name": target.name}


def rename_entry(workspace_dir: Path, old_rel: str, new_name: str) -> dict[str, Any]:
    src = resolve_safe_path(workspace_dir, old_rel)
    if src == workspace_dir.resolve() or not src.exists():
        raise ValueError("Об'єкт для перейменування не знайдено.")
    clean_new = new_name.strip().strip("/\\")
    if not clean_new or "/" in clean_new or "\\" in clean_new:
        raise ValueError("Вкажи коректну нову назву без слешів.")
    dst = resolve_safe_path(workspace_dir, to_rel_posix(workspace_dir, src.parent / clean_new))
    if dst.exists():
        raise ValueError(f"'{clean_new}' вже існує.")
    src.rename(dst)
    return {"path": to_rel_posix(workspace_dir, dst), "name": dst.name}


def delete_entry(workspace_dir: Path, rel_path: str) -> bool:
    target = resolve_safe_path(workspace_dir, rel_path)
    if target == workspace_dir.resolve():
        raise ValueError("Не можна видалити кореневу папку середовища.")
    if target.name == "server.json" and target.parent == workspace_dir.resolve():
        raise ValueError("Системний файл server.json не можна видаляти.")
    if not target.exists():
        return False
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return True


# ---------------------------------------------------------------------------
# Shell Command & Python Script Execution
# ---------------------------------------------------------------------------

def _truncate_output(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + "\n... [вивід скорочено]"


def run_shell_command(
    workspace_dir: Path,
    command: str,
    rel_cwd: str = "",
    timeout_sec: int = 30,
) -> dict[str, Any]:
    cmd = command.strip()
    if not cmd:
        raise ValueError("Команда порожня.")
    base = workspace_dir.resolve()
    cwd = resolve_safe_path(workspace_dir, rel_cwd)
    if not cwd.exists() or not cwd.is_dir():
        cwd = base

    wrapped_cmd = cmd
    marker = "__WIGI_CWD__="
    if os.name != "nt":
        wrapped_cmd = f"{cmd}\n__wigi_ec=$?\nprintf '\\n{marker}%s\\n' \"$PWD\"\nexit $__wigi_ec"

    timeout_clamped = max(1, min(int(timeout_sec), 120))
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            wrapped_cmd,
            shell=True,
            cwd=str(cwd),
            env=_build_process_env(workspace_dir),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_clamped,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        stdout_txt = completed.stdout
        resulting_cwd = cwd

        if os.name != "nt" and marker in stdout_txt:
            idx = stdout_txt.rfind(marker)
            prefix = stdout_txt[:idx]
            if prefix.endswith("\n"):
                prefix = prefix[:-1]
            tail = stdout_txt[idx + len(marker) :].splitlines()
            if tail:
                cand = Path(tail[0].strip()).resolve()
                if cand == base or base in cand.parents:
                    resulting_cwd = cand
            stdout_txt = prefix

        return {
            "exit_code": completed.returncode,
            "stdout": _truncate_output(stdout_txt),
            "stderr": _truncate_output(completed.stderr),
            "duration_ms": duration_ms,
            "timed_out": False,
            "cwd": to_rel_posix(workspace_dir, resulting_cwd),
        }
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        out = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return {
            "exit_code": -1,
            "stdout": _truncate_output(out),
            "stderr": _truncate_output(err + f"\n[Перевищено ліміт часу {timeout_clamped} с]"),
            "duration_ms": duration_ms,
            "timed_out": True,
            "cwd": to_rel_posix(workspace_dir, cwd),
        }


def run_python_code(
    workspace_dir: Path,
    rel_file: str = "",
    code: str = "",
    timeout_sec: int = 30,
) -> dict[str, Any]:
    timeout_clamped = max(1, min(int(timeout_sec), 120))
    env = _build_process_env(workspace_dir)
    started = time.perf_counter()

    if rel_file.strip():
        script_path = resolve_safe_path(workspace_dir, rel_file)
        if not script_path.exists() or not script_path.is_file():
            raise ValueError(f"Python-файл '{rel_file}' не знайдено.")
        cwd = script_path.parent
        cmd_list = [sys.executable, str(script_path)]
        return _exec_argv(cmd_list, cwd, env, timeout_clamped, started, workspace_dir)

    if not code.strip():
        raise ValueError("Передай Python-код або шлях до .py файлу.")

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        dir=str(workspace_dir),
        prefix=".wigi_run_",
        encoding="utf-8",
        delete=False,
    ) as tmp:
        tmp.write(code)
        tmp_path = Path(tmp.name)

    try:
        cmd_list = [sys.executable, str(tmp_path)]
        return _exec_argv(cmd_list, workspace_dir.resolve(), env, timeout_clamped, started, workspace_dir)
    finally:
        tmp_path.unlink(missing_ok=True)


def _exec_argv(
    argv: list[str],
    cwd: Path,
    env: dict[str, str],
    timeout_sec: int,
    started: float,
    workspace_dir: Path,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        return {
            "exit_code": completed.returncode,
            "stdout": _truncate_output(completed.stdout),
            "stderr": _truncate_output(completed.stderr),
            "duration_ms": duration_ms,
            "timed_out": False,
            "cwd": to_rel_posix(workspace_dir, cwd),
        }
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        out = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return {
            "exit_code": -1,
            "stdout": _truncate_output(out),
            "stderr": _truncate_output(err + f"\n[Перевищено ліміт часу {timeout_sec} с]"),
            "duration_ms": duration_ms,
            "timed_out": True,
            "cwd": to_rel_posix(workspace_dir, cwd),
        }


# ---------------------------------------------------------------------------
# Git / GitHub Repository Management
# ---------------------------------------------------------------------------

def _normalize_repo_url(repo_input: str) -> tuple[str, str]:
    """Accept full git URL or GitHub shorthand `owner/repo` -> `(clone_url, default_dir)`."""
    cleaned = repo_input.strip()
    if not cleaned:
        raise ValueError("Вкажи посилання на GitHub репозиторій або owner/repo.")

    if re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", cleaned):
        repo_name = cleaned.split("/", 1)[1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]
        return f"https://github.com/{cleaned}.git", repo_name

    if cleaned.startswith(("https://", "http://", "git@", "ssh://")):
        tail = cleaned.rstrip("/").rsplit("/", 1)[-1]
        if tail.endswith(".git"):
            tail = tail[:-4]
        folder = re.sub(r"[^A-Za-z0-9_.-]+", "-", tail).strip("-") or "repo"
        return cleaned, folder

    raise ValueError("Підтримується формат 'owner/repo' або повний URL (https://github.com/...).")


def _run_git(cwd: Path, args: list[str], workspace_dir: Path, timeout_sec: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=_build_process_env(workspace_dir),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_sec,
    )


def git_clone(workspace_dir: Path, repo_input: str, folder_name: str = "") -> dict[str, Any]:
    url, default_folder = _normalize_repo_url(repo_input)
    folder = folder_name.strip() or default_folder
    if "/" in folder or "\\" in folder or folder in (".", ".."):
        raise ValueError("Некоректна назва цільової папки.")

    dest = resolve_safe_path(workspace_dir, folder)
    if dest.exists():
        raise ValueError(f"Папка '{folder}' вже існує в середовищі сервера.")

    res = _run_git(workspace_dir.resolve(), ["clone", url, str(dest)], workspace_dir, timeout_sec=90)
    if res.returncode != 0:
        raise ValueError((res.stderr or res.stdout or "Помилка git clone").strip())

    return {
        "name": dest.name,
        "path": to_rel_posix(workspace_dir, dest),
        "url": url,
        "output": (res.stdout + "\n" + res.stderr).strip(),
    }


def git_init(workspace_dir: Path, folder_name: str) -> dict[str, Any]:
    clean = folder_name.strip().strip("/\\")
    if not clean or "/" in clean or "\\" in clean:
        raise ValueError("Вкажи коректну назву папки для нового репозиторію.")

    dest = resolve_safe_path(workspace_dir, clean)
    dest.mkdir(parents=True, exist_ok=True)
    res = _run_git(dest, ["init", "-b", "main"], workspace_dir)
    if res.returncode != 0:
        res = _run_git(dest, ["init"], workspace_dir)
    if res.returncode != 0:
        raise ValueError((res.stderr or res.stdout or "Помилка git init").strip())

    readme = dest / "README.md"
    if not readme.exists():
        readme.write_text(f"# {clean}\n", encoding="utf-8")

    return {
        "name": dest.name,
        "path": to_rel_posix(workspace_dir, dest),
        "output": (res.stdout + "\n" + res.stderr).strip(),
    }


def _inspect_single_repo(workspace_dir: Path, repo_dir: Path) -> dict[str, Any]:
    branch_res = _run_git(repo_dir, ["rev-parse", "--abbrev-ref", "HEAD"], workspace_dir, timeout_sec=10)
    branch = branch_res.stdout.strip() if branch_res.returncode == 0 else "main"

    remote_res = _run_git(repo_dir, ["remote", "get-url", "origin"], workspace_dir, timeout_sec=10)
    remote_url = remote_res.stdout.strip() if remote_res.returncode == 0 else ""

    status_res = _run_git(repo_dir, ["status", "--short"], workspace_dir, timeout_sec=10)
    status_lines = [ln for ln in status_res.stdout.splitlines() if ln.strip()]

    log_res = _run_git(
        repo_dir,
        ["log", "-n", "8", "--pretty=format:%h|%an|%ar|%s"],
        workspace_dir,
        timeout_sec=10,
    )
    commits: list[dict[str, str]] = []
    if log_res.returncode == 0 and log_res.stdout.strip():
        for ln in log_res.stdout.splitlines():
            parts = ln.split("|", 3)
            if len(parts) == 4:
                commits.append(
                    {
                        "hash": parts[0],
                        "author": parts[1],
                        "when": parts[2],
                        "subject": parts[3],
                    }
                )

    rel = to_rel_posix(workspace_dir, repo_dir)
    return {
        "name": repo_dir.name if rel else "(root)",
        "path": rel,
        "branch": branch,
        "remote_url": remote_url,
        "changed_count": len(status_lines),
        "status": status_lines[:40],
        "commits": commits,
    }


def list_git_repos(workspace_dir: Path) -> list[dict[str, Any]]:
    repos: list[dict[str, Any]] = []
    if not workspace_dir.exists():
        return repos

    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=5, check=True)
    except Exception:
        return repos

    if (workspace_dir / ".git").exists():
        repos.append(_inspect_single_repo(workspace_dir, workspace_dir))

    for child in sorted(workspace_dir.iterdir(), key=lambda p: p.name.lower()):
        if child.is_dir() and not child.name.startswith(".") and (child / ".git").exists():
            repos.append(_inspect_single_repo(workspace_dir, child))

    return repos


def git_action(
    workspace_dir: Path,
    rel_repo_path: str,
    action: str,
    message: str = "",
    branch: str = "",
    remote_url: str = "",
) -> dict[str, Any]:
    repo_dir = resolve_safe_path(workspace_dir, rel_repo_path)
    if not (repo_dir / ".git").exists():
        raise ValueError("Вибрана папка не є Git-репозиторієм.")

    act = action.strip().lower()
    if act == "status":
        res = _run_git(repo_dir, ["status"], workspace_dir)
    elif act == "pull":
        res = _run_git(repo_dir, ["pull", "--ff-only"], workspace_dir, timeout_sec=60)
    elif act == "push":
        br_res = _run_git(repo_dir, ["rev-parse", "--abbrev-ref", "HEAD"], workspace_dir)
        cur_branch = br_res.stdout.strip() or "main"
        res = _run_git(repo_dir, ["push", "-u", "origin", cur_branch], workspace_dir, timeout_sec=60)
    elif act == "commit":
        msg = message.strip()
        if not msg:
            raise ValueError("Вкажи текст коміту (commit message).")
        add_res = _run_git(repo_dir, ["add", "-A"], workspace_dir)
        if add_res.returncode != 0:
            raise ValueError((add_res.stderr or add_res.stdout).strip())

        email_chk = _run_git(repo_dir, ["config", "user.email"], workspace_dir)
        commit_cmd = ["commit", "-m", msg]
        if not email_chk.stdout.strip():
            commit_cmd = ["-c", "user.name=WiGi Server", "-c", "user.email=wigi@localhost", *commit_cmd]
        res = _run_git(repo_dir, commit_cmd, workspace_dir)
    elif act == "checkout":
        br = branch.strip()
        if not br or not re.match(r"^[A-Za-z0-9._/-]+$", br):
            raise ValueError("Вкажи коректну назву гілки.")
        res = _run_git(repo_dir, ["checkout", br], workspace_dir)
        if res.returncode != 0:
            res = _run_git(repo_dir, ["checkout", "-b", br], workspace_dir)
    elif act == "set-remote":
        clean_remote = remote_url.strip()
        if not clean_remote:
            raise ValueError("Вкажи URL віддаленого репозиторію.")
        chk = _run_git(repo_dir, ["remote", "get-url", "origin"], workspace_dir)
        if chk.returncode == 0:
            res = _run_git(repo_dir, ["remote", "set-url", "origin", clean_remote], workspace_dir)
        else:
            res = _run_git(repo_dir, ["remote", "add", "origin", clean_remote], workspace_dir)
    else:
        raise ValueError(f"Невідома Git-дія: '{action}'.")

    output = ((res.stdout or "") + ("\n" + res.stderr if res.stderr else "")).strip()
    return {
        "exit_code": res.returncode,
        "output": output or "(виконано без виводу)",
        "repo": _inspect_single_repo(workspace_dir, repo_dir),
    }


# ---------------------------------------------------------------------------
# WiGi OS Extension State, Flat Search, Process Monitor & Project Templates
# ---------------------------------------------------------------------------

def _default_os_state() -> dict[str, Any]:
    return {
        "theme": "cyber",
        "sticky_note": "Швидкі нотатки сервера...\n• Ctrl+K — швидкий пошук\n• Ctrl+S — зберегти код",
        "tasks": [
            {"id": "t1", "title": "Клонувати або створити Git-репозиторій", "col": "todo", "priority": "high"},
            {"id": "t2", "title": "Написати та запустити Python-скрипт у Code Studio", "col": "doing", "priority": "normal"},
            {"id": "t3", "title": "Підняти власне серверне середовище WiGi", "col": "done", "priority": "normal"},
        ],
    }


def load_os_state(workspace_dir: Path) -> dict[str, Any]:
    state = _default_os_state()
    state_file = workspace_dir / OS_STATE_FILENAME
    if state_file.exists():
        try:
            saved = json.loads(state_file.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                if isinstance(saved.get("theme"), str):
                    state["theme"] = saved["theme"]
                if isinstance(saved.get("sticky_note"), str):
                    state["sticky_note"] = saved["sticky_note"][:20_000]
                if isinstance(saved.get("tasks"), list):
                    clean_tasks = []
                    for item in saved["tasks"][:200]:
                        if isinstance(item, dict) and str(item.get("title", "")).strip():
                            col = str(item.get("col", "todo"))
                            if col not in ("todo", "doing", "done"):
                                col = "todo"
                            prio = str(item.get("priority", "normal"))
                            if prio not in ("normal", "high"):
                                prio = "normal"
                            clean_tasks.append(
                                {
                                    "id": str(item.get("id") or int(time.time() * 1000)),
                                    "title": str(item["title"]).strip()[:240],
                                    "col": col,
                                    "priority": prio,
                                }
                            )
                    state["tasks"] = clean_tasks
        except (OSError, json.JSONDecodeError):
            pass
    return state


def save_os_state(workspace_dir: Path, patch_data: dict[str, Any]) -> dict[str, Any]:
    current = load_os_state(workspace_dir)
    if "theme" in patch_data and isinstance(patch_data["theme"], str):
        allowed_themes = {"cyber", "nebula", "matrix", "sunset", "slate"}
        if patch_data["theme"] in allowed_themes:
            current["theme"] = patch_data["theme"]
    if "sticky_note" in patch_data and isinstance(patch_data["sticky_note"], str):
        current["sticky_note"] = patch_data["sticky_note"][:20_000]
    if "tasks" in patch_data and isinstance(patch_data["tasks"], list):
        clean_tasks = []
        for idx, item in enumerate(patch_data["tasks"][:200]):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            col = str(item.get("col", "todo"))
            if col not in ("todo", "doing", "done"):
                col = "todo"
            prio = str(item.get("priority", "normal"))
            if prio not in ("normal", "high"):
                prio = "normal"
            clean_tasks.append(
                {
                    "id": str(item.get("id") or f"t_{int(time.time()*1000)}_{idx}"),
                    "title": title[:240],
                    "col": col,
                    "priority": prio,
                }
            )
        current["tasks"] = clean_tasks

    state_file = workspace_dir / OS_STATE_FILENAME
    state_file.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return current


def list_all_files_flat(workspace_dir: Path, max_items: int = 250) -> list[dict[str, Any]]:
    """Return a flat list of workspace files for quick Ctrl+K search in WiGi OS."""
    results: list[dict[str, Any]] = []
    base = workspace_dir.resolve()
    if not base.exists():
        return results

    skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv"}
    for root, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if d not in skip_dirs and not d.startswith(".wigi"))
        for fname in sorted(files):
            if fname in HIDDEN_SYSTEM_FILES or fname.startswith(".wigi_run_"):
                continue
            fpath = Path(root) / fname
            rel = to_rel_posix(workspace_dir, fpath)
            results.append({"name": fname, "path": rel})
            if len(results) >= max_items:
                return results
    return results


def list_host_processes(limit: int = 18) -> list[dict[str, str]]:
    """Return top running processes on the host machine for the OS System Monitor."""
    procs: list[dict[str, str]] = []
    try:
        if os.name == "nt":
            res = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            for ln in res.stdout.splitlines()[:limit]:
                parts = [p.strip('"') for p in ln.split('","')]
                if len(parts) >= 5:
                    procs.append({"pid": parts[1], "cpu": "—", "mem": parts[4], "command": parts[0]})
        else:
            res = subprocess.run(
                ["ps", "-eo", "pid,pcpu,pmem,comm", "--sort=-pcpu"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            lines = res.stdout.splitlines()
            for ln in lines[1 : limit + 1]:
                cols = ln.strip().split(None, 3)
                if len(cols) == 4:
                    procs.append({"pid": cols[0], "cpu": cols[1] + "%", "mem": cols[2] + "%", "command": cols[3]})
    except Exception:
        pass
    return procs


def create_project_template(workspace_dir: Path, kind: str, name: str) -> dict[str, Any]:
    """Scaffold a ready-to-work project inside the server workspace."""
    clean_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", name.strip()).strip("-")
    if not clean_name:
        raise ValueError("Вкажи коректну назву проєкту.")
    proj_dir = resolve_safe_path(workspace_dir, clean_name)
    if proj_dir.exists():
        raise ValueError(f"Папка '{clean_name}' вже існує.")
    proj_dir.mkdir(parents=True, exist_ok=True)

    if kind == "html-app":
        (proj_dir / "index.html").write_text(
            f"""<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="utf-8" />
  <title>{clean_name}</title>
  <link rel="stylesheet" href="style.css" />
</head>
<body>
  <div class="box">
    <h1>⚡ {clean_name}</h1>
    <p>Живий HTML/JS додаток, запущений прямо із середовища сервера WiGi OS.</p>
    <button id="actBtn">Натисни для тесту</button>
    <div id="out"></div>
  </div>
  <script src="app.js"></script>
</body>
</html>
""",
            encoding="utf-8",
        )
        (proj_dir / "style.css").write_text(
            """body { font-family: system-ui, sans-serif; background: #0b1220; color: #e2e8f0; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; }
.box { background: #131e33; border: 1px solid #283a5e; border-radius: 14px; padding: 28px; max-width: 440px; text-align: center; }
button { background: #38bdf8; color: #041321; border: none; padding: 10px 18px; border-radius: 9px; font-weight: 700; cursor: pointer; margin-top: 12px; }
#out { margin-top: 14px; color: #86efac; font-family: monospace; }
""",
            encoding="utf-8",
        )
        (proj_dir / "app.js").write_text(
            """let clicks = 0;
document.getElementById("actBtn").addEventListener("click", () => {
  clicks += 1;
  document.getElementById("out").textContent = `Кліків: ${clicks} • Час: ${new Date().toLocaleTimeString()}`;
});
""",
            encoding="utf-8",
        )
        entry = f"{clean_name}/index.html"
    else:
        (proj_dir / "main.py").write_text(
            f"""#!/usr/bin/env python3
\"\"\"Робочий Python-проєкт: {clean_name}\"\"\"

from datetime import datetime
from pathlib import Path
import json


def run() -> None:
    report = {{
        "project": "{clean_name}",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "cwd": str(Path.cwd()),
    }}
    print("=== Звіт виконання проєкту ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
""",
            encoding="utf-8",
        )
        (proj_dir / "README.md").write_text(
            f"# {clean_name}\n\nPython-проєкт створено у середовищі **WiGi OS**.\n",
            encoding="utf-8",
        )
        entry = f"{clean_name}/main.py"

    return {
        "name": clean_name,
        "path": to_rel_posix(workspace_dir, proj_dir),
        "entry": entry,
        "kind": kind,
    }
