"""HTTP & REST API server + Web Control Panel for a selected WiGi ServerProfile."""

from __future__ import annotations

from collections import deque
from datetime import datetime
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import html
import json
import mimetypes
from pathlib import Path
import secrets
import socket
import threading
import time
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from wigi.network import get_lan_ip, get_system_metrics
from wigi.storage import ServerProfile, ServerStore
from wigi.webos import render_webos_html
from wigi import workspace as ws_ops

MAX_JSON_BODY = 36 * 1024 * 1024  # 36 MB (supports base64 uploads up to 25 MB)


class WiGiHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        profile: ServerProfile,
        workspace_dir: Path,
        quiet: bool = False,
        store: ServerStore | None = None,
    ) -> None:
        self.profile = profile
        self.workspace_dir = workspace_dir
        self.quiet = quiet
        self.store = store
        self.started_at = time.time()
        self.started_at_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.lan_ip = get_lan_ip()
        self.hostname = socket.gethostname()
        self._lock = threading.Lock()
        self._sessions: dict[str, dict[str, Any]] = {}
        self._events: deque[dict[str, str]] = deque(maxlen=100)
        super().__init__(server_address, WiGiRequestHandler)
        actual_port = self.server_address[1]
        self.record_event("SYSTEM", f"Сервер '{profile.name}' запущено на порту {actual_port}")

    def record_event(self, kind: str, message: str) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            self._events.appendleft({"time": now, "kind": kind, "message": message})
        if not self.quiet:
            print(f"  [{now}] [{kind}] {message}", flush=True)

    def create_session(self, client_ip: str = "") -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self._sessions[token] = {
                "ip": client_ip or "unknown",
                "created_at": now,
                "last_seen": now,
            }
        return token

    def validate_session(self, token: str | None) -> bool:
        if not token:
            return False
        now = time.time()
        with self._lock:
            sess = self._sessions.get(token)
            if sess is None:
                return False
            if now - float(sess["created_at"]) > 86400:
                self._sessions.pop(token, None)
                return False
            sess["last_seen"] = now
            return True

    def revoke_session(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)

    def revoke_other_sessions(self, keep_token: str | None) -> int:
        removed = 0
        with self._lock:
            for tok in list(self._sessions.keys()):
                if tok != keep_token:
                    self._sessions.pop(tok, None)
                    removed += 1
        return removed

    def list_sessions_public(self, current_token: str | None) -> list[dict[str, Any]]:
        now = time.time()
        out: list[dict[str, Any]] = []
        with self._lock:
            for tok, info in list(self._sessions.items()):
                if now - float(info["created_at"]) > 86400:
                    self._sessions.pop(tok, None)
                    continue
                out.append(
                    {
                        "id": tok[:8],
                        "ip": info["ip"],
                        "age_seconds": int(max(0.0, now - float(info["created_at"]))),
                        "idle_seconds": int(max(0.0, now - float(info["last_seen"]))),
                        "current": tok == current_token,
                    }
                )
        return out

    def list_events(self) -> list[dict[str, str]]:
        with self._lock:
            return list(self._events)


class WiGiRequestHandler(BaseHTTPRequestHandler):
    server: WiGiHTTPServer

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _client_ip(self) -> str:
        forwarded = self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        return forwarded or self.client_address[0]

    def _cookie_flags(self) -> str:
        proto = self.headers.get("X-Forwarded-Proto", "").lower()
        if proto == "https":
            return "HttpOnly; Path=/; SameSite=None; Secure"
        return "HttpOnly; Path=/; SameSite=Lax"

    def _extract_token(self) -> str | None:
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            if token:
                return token

        parsed = urlparse(self.path)
        if parsed.query:
            qs = parse_qs(parsed.query)
            q_tok = (qs.get("token", [""])[0] or "").strip()
            if q_tok:
                return q_tok

        raw_cookie = self.headers.get("Cookie")
        if raw_cookie:
            jar = cookies.SimpleCookie()
            try:
                jar.load(raw_cookie)
                morsel = jar.get("wigi_session")
                if morsel and morsel.value:
                    return morsel.value
            except cookies.CookieError:
                pass
        return None

    def _is_authenticated(self) -> bool:
        return self.server.validate_session(self._extract_token())

    def _require_auth(self) -> bool:
        if not self._is_authenticated():
            self._send_json(401, {"ok": False, "error": "Потрібна авторизація паролем сервера."})
            return False
        return True

    def _send_json(
        self,
        status: int,
        payload: dict[str, Any],
        extra_headers: list[tuple[str, str]] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for k, v in extra_headers:
                self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_html(self, status: int, content: str) -> None:
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_download(self, filename: str, raw: bytes) -> None:
        mime, _ = mimetypes.guess_type(filename)
        content_type = mime or "application/octet-stream"
        encoded_name = quote(filename)
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header(
            "Content-Disposition",
            f"attachment; filename*=UTF-8''{encoded_name}",
        )
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def _send_inline_file(self, filename: str, raw: bytes, set_token_cookie: str | None = None) -> None:
        mime, _ = mimetypes.guess_type(filename)
        content_type = mime or "application/octet-stream"
        if content_type.startswith("text/") and "charset=" not in content_type:
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        if set_token_cookie:
            self.send_header(
                "Set-Cookie",
                f"wigi_session={set_token_cookie}; Max-Age=86400; {self._cookie_flags()}",
            )
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def _read_json_body(self) -> dict[str, Any] | None:
        length_str = self.headers.get("Content-Length", "0")
        try:
            length = int(length_str)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        if length > MAX_JSON_BODY:
            self._send_json(413, {"ok": False, "error": "Запит перевищує ліміт розміру."})
            return None
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
            return parsed if isinstance(parsed, dict) else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        if route == "/favicon.ico":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if route == "/":
            self._send_html(200, _render_index_html(self.server))
            return

        if route == "/os":
            self._send_html(200, render_webos_html(self.server))
            return

        if route == "/api/info":
            self._send_json(
                200,
                {
                    "online": True,
                    "id": self.server.profile.id,
                    "name": self.server.profile.name,
                    "description": self.server.profile.description,
                    "hostname": self.server.hostname,
                    "authenticated": self._is_authenticated(),
                },
            )
            return

        # Protected GET routes below
        if not self._require_auth():
            return

        if route == "/api/status":
            uptime_sec = int(max(0.0, time.time() - self.server.started_at))
            port = self.server.server_address[1]
            metrics = get_system_metrics(self.server.workspace_dir)
            cur_tok = self._extract_token()
            listing = ws_ops.list_directory(self.server.workspace_dir, "")
            self._send_json(
                200,
                {
                    "ok": True,
                    "server": {
                        "id": self.server.profile.id,
                        "name": self.server.profile.name,
                        "description": self.server.profile.description,
                        "slug": self.server.profile.slug,
                        "port": port,
                        "saved_port": self.server.profile.port,
                        "created_at": self.server.profile.created_at,
                        "started_at": self.server.started_at_str,
                        "uptime_seconds": uptime_sec,
                    },
                    "host": {
                        "hostname": self.server.hostname,
                        "os": metrics["os"],
                        "python": metrics["python"],
                        "cpu_cores": metrics["cpu_cores"],
                        "load_avg": metrics["load_avg"],
                        "memory": metrics["memory"],
                        "disk": metrics["disk"],
                        "local_url": f"http://localhost:{port}",
                        "lan_url": f"http://{self.server.lan_ip}:{port}",
                        "workspace_dir": str(self.server.workspace_dir),
                    },
                    "workspace_files": listing["items"],
                    "sessions": self.server.list_sessions_public(cur_tok),
                    "events": self.server.list_events(),
                },
            )
            return

        if route == "/api/files":
            rel_path = (qs.get("path", [""])[0] or "").strip()
            try:
                data = ws_ops.list_directory(self.server.workspace_dir, rel_path)
                self._send_json(200, {"ok": True, **data})
            except ValueError as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
            return

        if route == "/api/files/read":
            rel_path = (qs.get("path", [""])[0] or "").strip()
            try:
                data = ws_ops.read_text_file(self.server.workspace_dir, rel_path)
                self._send_json(200, {"ok": True, **data})
            except ValueError as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
            return

        if route == "/api/files/download":
            rel_path = (qs.get("path", [""])[0] or "").strip()
            try:
                filename, raw = ws_ops.read_binary_file(self.server.workspace_dir, rel_path)
                self._send_download(filename, raw)
            except ValueError as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
            return

        if route == "/api/git/repos":
            repos = ws_ops.list_git_repos(self.server.workspace_dir)
            self._send_json(200, {"ok": True, "repos": repos})
            return

        if route == "/api/env":
            env_vars = ws_ops.load_env_vars(self.server.workspace_dir)
            self._send_json(200, {"ok": True, "env": env_vars})
            return

        if route == "/api/os/state":
            state = ws_ops.load_os_state(self.server.workspace_dir)
            self._send_json(200, {"ok": True, "state": state})
            return

        if route == "/api/os/processes":
            procs = ws_ops.list_host_processes()
            self._send_json(200, {"ok": True, "processes": procs})
            return

        if route == "/api/os/search":
            files = ws_ops.list_all_files_flat(self.server.workspace_dir)
            self._send_json(200, {"ok": True, "files": files})
            return

        if route.startswith("/workspace/"):
            rel_path = parsed.path[len("/workspace/") :].strip("/")
            try:
                target = ws_ops.resolve_safe_path(self.server.workspace_dir, rel_path)
                if target.is_dir():
                    target = target / "index.html"
                filename, raw = ws_ops.read_binary_file(
                    self.server.workspace_dir,
                    ws_ops.to_rel_posix(self.server.workspace_dir, target),
                )
                q_tok = (qs.get("token", [""])[0] or "").strip() or None
                self._send_inline_file(filename, raw, set_token_cookie=q_tok)
            except ValueError as exc:
                self._send_json(404, {"ok": False, "error": str(exc)})
            return

        self._send_json(404, {"ok": False, "error": "Маршрут не знайдено."})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        data = self._read_json_body()
        if data is None:
            return

        if route == "/api/login":
            password = str(data.get("password", ""))
            client_ip = self._client_ip()

            if not self.server.profile.verify_password(password):
                time.sleep(0.25)
                self.server.record_event("AUTH", f"Невдала спроба входу з {client_ip}")
                self._send_json(401, {"ok": False, "error": "Невірний пароль сервера."})
                return

            token = self.server.create_session(client_ip=client_ip)
            self.server.record_event("AUTH", f"Успішний вхід на сервер з {client_ip}")
            cookie_val = f"wigi_session={token}; Max-Age=86400; {self._cookie_flags()}"
            self._send_json(
                200,
                {"ok": True, "token": token, "name": self.server.profile.name},
                extra_headers=[("Set-Cookie", cookie_val)],
            )
            return

        if route == "/api/logout":
            token = self._extract_token()
            self.server.revoke_session(token)
            cookie_val = f"wigi_session=; Max-Age=0; {self._cookie_flags()}"
            self._send_json(
                200,
                {"ok": True},
                extra_headers=[("Set-Cookie", cookie_val)],
            )
            return

        # All POST routes below require authentication
        if not self._require_auth():
            return

        try:
            if route == "/api/files/write":
                rel_path = str(data.get("path", ""))
                content = str(data.get("content", ""))
                saved = ws_ops.write_text_file(self.server.workspace_dir, rel_path, content)
                self.server.record_event("FILES", f"Збережено файл '{saved['path']}' ({saved['size']} B)")
                self._send_json(200, {"ok": True, **saved})
                return

            if route == "/api/files/upload":
                rel_path = str(data.get("path", ""))
                data_b64 = str(data.get("data_b64", ""))
                uploaded = ws_ops.upload_base64_file(self.server.workspace_dir, rel_path, data_b64)
                self.server.record_event("FILES", f"Завантажено файл '{uploaded['path']}' ({uploaded['size']} B)")
                self._send_json(200, {"ok": True, **uploaded})
                return

            if route == "/api/files/mkdir":
                rel_path = str(data.get("path", ""))
                created = ws_ops.make_directory(self.server.workspace_dir, rel_path)
                self.server.record_event("FILES", f"Створено папку '{created['path']}'")
                self._send_json(200, {"ok": True, **created})
                return

            if route == "/api/files/rename":
                old_rel = str(data.get("path", ""))
                new_name = str(data.get("new_name", ""))
                renamed = ws_ops.rename_entry(self.server.workspace_dir, old_rel, new_name)
                self.server.record_event("FILES", f"Перейменовано '{old_rel}' -> '{renamed['path']}'")
                self._send_json(200, {"ok": True, **renamed})
                return

            if route == "/api/files/delete":
                rel_path = str(data.get("path", ""))
                deleted = ws_ops.delete_entry(self.server.workspace_dir, rel_path)
                if deleted:
                    self.server.record_event("FILES", f"Видалено '{rel_path}'")
                self._send_json(200, {"ok": True, "deleted": deleted})
                return

            if route == "/api/exec":
                command = str(data.get("command", ""))
                rel_cwd = str(data.get("cwd", ""))
                timeout_sec = int(data.get("timeout", 30) or 30)
                short_cmd = command.strip().splitlines()[0][:64]
                self.server.record_event("EXEC", f"$ {short_cmd}")
                res = ws_ops.run_shell_command(
                    self.server.workspace_dir,
                    command=command,
                    rel_cwd=rel_cwd,
                    timeout_sec=timeout_sec,
                )
                self._send_json(200, {"ok": True, **res})
                return

            if route == "/api/python/run":
                rel_file = str(data.get("file", ""))
                code = str(data.get("code", ""))
                timeout_sec = int(data.get("timeout", 30) or 30)
                label = rel_file if rel_file.strip() else "inline snippet"
                self.server.record_event("PYTHON", f"Запуск Python ({label})")
                res = ws_ops.run_python_code(
                    self.server.workspace_dir,
                    rel_file=rel_file,
                    code=code,
                    timeout_sec=timeout_sec,
                )
                self._send_json(200, {"ok": True, **res})
                return

            if route == "/api/git/clone":
                repo = str(data.get("repo", ""))
                folder = str(data.get("folder", ""))
                cloned = ws_ops.git_clone(self.server.workspace_dir, repo_input=repo, folder_name=folder)
                self.server.record_event("GIT", f"Клоновано репозиторій '{cloned['url']}' -> {cloned['path']}")
                self._send_json(200, {"ok": True, **cloned})
                return

            if route == "/api/git/init":
                folder = str(data.get("folder", ""))
                inited = ws_ops.git_init(self.server.workspace_dir, folder_name=folder)
                self.server.record_event("GIT", f"Ініціалізовано Git-репозиторій '{inited['path']}'")
                self._send_json(200, {"ok": True, **inited})
                return

            if route == "/api/git/action":
                rel_repo = str(data.get("path", ""))
                action = str(data.get("action", ""))
                message = str(data.get("message", ""))
                branch = str(data.get("branch", ""))
                remote_url = str(data.get("remote_url", ""))
                res = ws_ops.git_action(
                    self.server.workspace_dir,
                    rel_repo_path=rel_repo,
                    action=action,
                    message=message,
                    branch=branch,
                    remote_url=remote_url,
                )
                self.server.record_event("GIT", f"git {action} у '{rel_repo or '.'}' (код {res['exit_code']})")
                self._send_json(200, {"ok": True, **res})
                return

            if route == "/api/env":
                raw_env = data.get("env", {})
                if not isinstance(raw_env, dict):
                    raise ValueError("Поле 'env' має бути словником {KEY: VALUE}.")
                saved_env = ws_ops.save_env_vars(self.server.workspace_dir, raw_env)
                self.server.record_event("CONFIG", f"Оновлено змінні середовища ({len(saved_env)} шт.)")
                self._send_json(200, {"ok": True, "env": saved_env})
                return

            if route == "/api/os/state":
                saved_state = ws_ops.save_os_state(self.server.workspace_dir, data)
                self._send_json(200, {"ok": True, "state": saved_state})
                return

            if route == "/api/os/template":
                kind = str(data.get("kind", "python-app"))
                name = str(data.get("name", ""))
                created = ws_ops.create_project_template(self.server.workspace_dir, kind=kind, name=name)
                self.server.record_event("OS", f"Створено проєкт '{created['name']}' ({kind})")
                self._send_json(200, {"ok": True, **created})
                return

            if route == "/api/sessions/revoke-others":
                cur_tok = self._extract_token()
                removed = self.server.revoke_other_sessions(cur_tok)
                self.server.record_event("AUTH", f"Завершено інші активні сесії ({removed} шт.)")
                self._send_json(200, {"ok": True, "removed": removed})
                return

            if route == "/api/server/settings":
                new_name = str(data.get("name", self.server.profile.name)).strip()
                new_desc = str(data.get("description", self.server.profile.description)).strip()
                new_port = int(data.get("port", self.server.profile.port) or self.server.profile.port)
                if not new_name:
                    raise ValueError("Назва сервера не може бути порожньою.")
                if not (1 <= new_port <= 65535):
                    raise ValueError("Порт має бути в діапазоні 1..65535.")

                if self.server.store is not None:
                    updated = self.server.store.rename_server(self.server.profile.id, new_name, description=new_desc)
                    if new_port != updated.port:
                        updated = self.server.store.change_port(self.server.profile.id, new_port)
                    self.server.profile = updated
                else:
                    self.server.profile.name = new_name
                    self.server.profile.description = new_desc
                    self.server.profile.port = new_port

                self.server.record_event("CONFIG", f"Оновлено налаштування сервера '{self.server.profile.name}'")
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "name": self.server.profile.name,
                        "description": self.server.profile.description,
                        "saved_port": self.server.profile.port,
                    },
                )
                return

            if route == "/api/server/password":
                current_pw = str(data.get("current_password", ""))
                new_pw = str(data.get("new_password", ""))
                if not self.server.profile.verify_password(current_pw):
                    self._send_json(403, {"ok": False, "error": "Поточний пароль вказано невірно."})
                    return
                if not new_pw:
                    raise ValueError("Новий пароль не може бути порожнім.")

                if self.server.store is not None:
                    self.server.profile = self.server.store.change_password(self.server.profile.id, new_pw)
                else:
                    from wigi.storage import hash_password

                    salt_hex, hash_hex = hash_password(new_pw)
                    self.server.profile.password_salt = salt_hex
                    self.server.profile.password_hash = hash_hex

                cur_tok = self._extract_token()
                self.server.revoke_other_sessions(cur_tok)
                self.server.record_event("AUTH", "Пароль сервера змінено")
                self._send_json(200, {"ok": True})
                return

            if route == "/api/server/stop":
                self.server.record_event("SYSTEM", f"Запит на зупинку сервера з {self._client_ip()}")
                self._send_json(200, {"ok": True, "message": "Сервер зупиняється..."})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return

        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return

        self._send_json(404, {"ok": False, "error": "Маршрут не знайдено."})


def _render_index_html(srv: WiGiHTTPServer) -> str:
    safe_name = html.escape(srv.profile.name)
    safe_host = html.escape(srv.hostname)
    safe_desc = html.escape(srv.profile.description or "Персональне Python-середовище сервера")
    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{safe_name} — WiGi Server</title>
  <style>
    :root {{
      --bg: #090d16;
      --panel: #111827;
      --panel-2: #172135;
      --panel-3: #0d1320;
      --border: #25334d;
      --text: #e6edf7;
      --muted: #8ea0bd;
      --accent: #38bdf8;
      --accent-hover: #0ea5e9;
      --green: #22c55e;
      --amber: #f59e0b;
      --red: #ef4444;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      background: radial-gradient(circle at top, #132038 0%, var(--bg) 60%);
      color: var(--text);
      min-height: 100vh;
      padding: 20px 16px 48px;
    }}
    .wrap {{ width: 100%; max-width: 1120px; margin: 0 auto; }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 22px;
      box-shadow: 0 20px 45px rgba(0, 0, 0, 0.42);
    }}
    .top {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      flex-wrap: wrap;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--border);
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: 12px;
      font-weight: 600;
      padding: 5px 11px;
      border-radius: 999px;
      background: rgba(34, 197, 94, 0.14);
      color: #86efac;
      border: 1px solid rgba(34, 197, 94, 0.3);
    }}
    .dot {{
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--green);
      box-shadow: 0 0 8px var(--green);
    }}
    h1 {{ font-size: 22px; font-weight: 700; letter-spacing: -0.01em; }}
    .sub {{ color: var(--muted); font-size: 13px; margin-top: 3px; }}
    .tabs {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin: 16px 0 20px;
    }}
    .tab-btn {{
      background: var(--panel-2);
      color: var(--muted);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 9px 15px;
      font-size: 13.5px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s;
    }}
    .tab-btn:hover {{ color: var(--text); border-color: #36496e; }}
    .tab-btn.active {{
      background: rgba(56, 189, 248, 0.15);
      color: var(--accent);
      border-color: rgba(56, 189, 248, 0.5);
    }}
    .login-box {{ max-width: 420px; margin: 34px auto 12px; }}
    label {{ display: block; font-size: 13px; color: var(--muted); margin-bottom: 6px; }}
    input[type="text"], input[type="password"], input[type="number"], textarea, select {{
      width: 100%;
      background: var(--panel-3);
      border: 1px solid var(--border);
      color: var(--text);
      border-radius: 9px;
      padding: 10px 12px;
      font-size: 14px;
      outline: none;
      transition: border-color 0.15s;
    }}
    input:focus, textarea:focus, select:focus {{ border-color: var(--accent); }}
    textarea.mono, input.mono {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 13px;
      line-height: 1.48;
    }}
    .btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      border: 1px solid transparent;
      border-radius: 9px;
      padding: 9px 15px;
      font-size: 13.5px;
      font-weight: 600;
      cursor: pointer;
      background: var(--accent);
      color: #05131f;
      transition: opacity 0.15s, border-color 0.15s;
      white-space: nowrap;
    }}
    .btn:hover {{ opacity: 0.92; }}
    .btn-sm {{ padding: 6px 11px; font-size: 12.5px; border-radius: 7px; }}
    .btn-full {{ width: 100%; margin-top: 12px; padding: 11px 16px; }}
    .btn-ghost {{
      background: var(--panel-2);
      color: var(--text);
      border-color: var(--border);
    }}
    .btn-ghost:hover {{ border-color: var(--muted); }}
    .btn-green {{ background: var(--green); color: #052010; }}
    .btn-danger {{
      background: rgba(239, 68, 68, 0.14);
      color: #fca5a5;
      border-color: rgba(239, 68, 68, 0.35);
    }}
    .err {{ margin-top: 10px; color: #fca5a5; font-size: 13px; min-height: 18px; }}
    .toast {{
      position: fixed;
      bottom: 20px;
      right: 20px;
      background: #17253d;
      border: 1px solid var(--accent);
      color: var(--text);
      padding: 10px 16px;
      border-radius: 10px;
      font-size: 13.5px;
      box-shadow: 0 12px 30px rgba(0,0,0,0.45);
      z-index: 999;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(235px, 1fr));
      gap: 12px;
    }}
    .stat {{
      background: var(--panel-2);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 13px 15px;
    }}
    .stat-k {{ font-size: 12px; color: var(--muted); margin-bottom: 5px; }}
    .stat-v {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 13.5px;
      word-break: break-all;
    }}
    .bar {{
      height: 6px;
      background: #0c1220;
      border-radius: 999px;
      overflow: hidden;
      margin-top: 8px;
    }}
    .bar > span {{
      display: block;
      height: 100%;
      background: linear-gradient(90deg, var(--accent), var(--green));
    }}
    .section-title {{
      font-size: 12.5px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--muted);
      margin: 20px 0 10px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }}
    .box-list {{
      background: var(--panel-3);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px 14px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12.5px;
      max-height: 240px;
      overflow-y: auto;
    }}
    .row-item {{
      padding: 6px 0;
      border-bottom: 1px solid rgba(37, 51, 77, 0.5);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }}
    .row-item:last-child {{ border-bottom: none; }}
    .split {{
      display: grid;
      grid-template-columns: 340px 1fr;
      gap: 16px;
      align-items: start;
    }}
    @media (max-width: 860px) {{
      .split {{ grid-template-columns: 1fr; }}
    }}
    .toolbar {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 10px; }}
    .file-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 7px 9px;
      border-radius: 8px;
      cursor: pointer;
      font-size: 13px;
    }}
    .file-row:hover {{ background: rgba(56, 189, 248, 0.08); }}
    .file-name {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .term-out {{
      background: #060910;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 14px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12.8px;
      line-height: 1.5;
      color: #d1fae5;
      min-height: 240px;
      max-height: 400px;
      overflow-y: auto;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .chip {{
      background: var(--panel-2);
      border: 1px solid var(--border);
      color: var(--muted);
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      cursor: pointer;
    }}
    .chip:hover {{ color: var(--text); border-color: var(--accent); }}
    .repo-card {{
      background: var(--panel-2);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px;
      margin-bottom: 14px;
    }}
    .muted {{ color: var(--muted); }}
    .hidden {{ display: none !important; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <div class="top">
        <div>
          <h1 id="hdrTitle">{safe_name}</h1>
          <div class="sub" id="hdrSub">{safe_desc} &bull; Хост: {safe_host}</div>
        </div>
        <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
          <a id="launchOsTopBtn" href="os" class="btn btn-sm hidden" style="text-decoration:none; background:linear-gradient(135deg,#38bdf8,#a855f7); color:#05101e;">🖥 Запустити WiGi OS</a>
          <span class="badge"><span class="dot"></span> <span id="hdrStatus">ONLINE</span></span>
          <button id="logoutBtn" class="btn btn-ghost btn-sm hidden" type="button">Вийти</button>
        </div>
      </div>

      <!-- LOGIN -->
      <div id="loginView" class="login-box hidden">
        <form id="loginForm">
          <label for="pwInput">Сервер захищено паролем. Введіть пароль для входу в середовище:</label>
          <input id="pwInput" type="password" placeholder="Пароль сервера..." autocomplete="current-password" required />
          <button class="btn btn-full" type="submit">Увійти на сервер</button>
          <div id="loginErr" class="err"></div>
        </form>
      </div>

      <!-- AUTHENTICATED WORKSPACE -->
      <div id="appView" class="hidden">
        <div class="tabs">
          <button class="tab-btn active" data-tab="overview" type="button">Огляд системи</button>
          <button class="tab-btn" data-tab="files" type="button">Файли та Код</button>
          <button class="tab-btn" data-tab="terminal" type="button">Термінал / Python</button>
          <button class="tab-btn" data-tab="git" type="button">Git / GitHub</button>
          <button class="tab-btn" data-tab="settings" type="button">Налаштування</button>
        </div>

        <!-- TAB 1: OVERVIEW -->
        <div id="tab-overview" class="tab-pane">
          <div style="background:linear-gradient(135deg,rgba(56,189,248,0.14),rgba(168,85,247,0.16)); border:1px solid rgba(56,189,248,0.4); border-radius:12px; padding:16px 18px; margin-bottom:16px; display:flex; align-items:center; justify-content:space-between; gap:14px; flex-wrap:wrap;">
            <div>
              <div style="font-size:16px; font-weight:800; margin-bottom:4px;">🖥 Розширення WiGi OS — Веб-Операційна Система</div>
              <div class="muted" style="font-size:13px;">Повноцінний робочий стіл у браузері: Code Studio IDE, Термінал, Провідник, GitHub Studio, Kanban-дошка, Нотатки та Веб-Ранер HTML-додатків.</div>
            </div>
            <a href="os" class="btn" style="text-decoration:none; background:linear-gradient(135deg,#38bdf8,#a855f7); color:#05101e; padding:10px 18px;">🚀 Відкрити WiGi OS</a>
          </div>

          <div class="grid">
            <div class="stat">
              <div class="stat-k">Сервер / ID</div>
              <div class="stat-v" id="stName">—</div>
            </div>
            <div class="stat">
              <div class="stat-k">Час роботи (Uptime)</div>
              <div class="stat-v" id="stUptime">—</div>
            </div>
            <div class="stat">
              <div class="stat-k">Браузер (цей ноут)</div>
              <div class="stat-v" id="stLocal">—</div>
            </div>
            <div class="stat">
              <div class="stat-k">Адреса в мережі (LAN)</div>
              <div class="stat-v" id="stLan">—</div>
            </div>
            <div class="stat">
              <div class="stat-k">Система / CPU / Python</div>
              <div class="stat-v" id="stSys">—</div>
            </div>
            <div class="stat">
              <div class="stat-k">Оперативна пам'ять (RAM)</div>
              <div class="stat-v" id="stRam">—</div>
              <div class="bar"><span id="barRam" style="width:0%"></span></div>
            </div>
            <div class="stat">
              <div class="stat-k">Диск середовища</div>
              <div class="stat-v" id="stDisk">—</div>
              <div class="bar"><span id="barDisk" style="width:0%"></span></div>
            </div>
            <div class="stat">
              <div class="stat-k">Папка середовища</div>
              <div class="stat-v" id="stDir">—</div>
            </div>
          </div>

          <div class="section-title">
            <span>Активні сесії підключення</span>
            <button id="revokeOthersBtn" class="btn btn-ghost btn-sm" type="button">Завершити інші сесії</button>
          </div>
          <div class="box-list" id="sessionsList"></div>

          <div class="section-title"><span>Журнал подій сервера</span></div>
          <div class="box-list" id="eventsList"></div>
        </div>

        <!-- TAB 2: FILES & CODE EDITOR -->
        <div id="tab-files" class="tab-pane hidden">
          <div class="split">
            <div class="stat" style="padding:14px;">
              <div class="toolbar">
                <button id="upDirBtn" class="btn btn-ghost btn-sm" type="button">↑ Вгору</button>
                <button id="newFileBtn" class="btn btn-ghost btn-sm" type="button">+ Файл</button>
                <button id="newDirBtn" class="btn btn-ghost btn-sm" type="button">+ Папка</button>
                <label class="btn btn-ghost btn-sm" style="margin:0; cursor:pointer;">
                  Завантажити
                  <input id="uploadInput" type="file" style="display:none;" />
                </label>
              </div>
              <div class="muted" style="font-size:12px; margin-bottom:8px;">
                Шлях: <code id="curDirLabel">/</code>
              </div>
              <div id="fileTree" class="box-list" style="max-height:430px; padding:6px;"></div>
            </div>

            <div class="stat" style="padding:14px;">
              <div class="toolbar" style="justify-content:space-between;">
                <div style="font-size:13px;">
                  Файл: <strong id="editorPathLabel" class="mono">не вибрано</strong>
                </div>
                <div style="display:flex; gap:8px; flex-wrap:wrap;">
                  <button id="runPyFileBtn" class="btn btn-green btn-sm hidden" type="button">▶ Запустити .py</button>
                  <button id="saveFileBtn" class="btn btn-sm" type="button" disabled>Зберегти (Ctrl+S)</button>
                </div>
              </div>
              <textarea id="codeEditor" class="mono" rows="16" placeholder="Вибери файл зліва для перегляду/редагування або натисни «+ Файл»..." disabled></textarea>
              <div id="pyRunOutWrap" class="hidden" style="margin-top:12px;">
                <div class="muted" style="font-size:12px; margin-bottom:4px;">Результат виконання:</div>
                <div id="pyRunOut" class="term-out" style="min-height:110px; max-height:200px;"></div>
              </div>
            </div>
          </div>
        </div>

        <!-- TAB 3: TERMINAL & PYTHON -->
        <div id="tab-terminal" class="tab-pane hidden">
          <div class="toolbar">
            <span class="muted" style="font-size:12.5px;">Швидкі команди:</span>
            <button class="chip" data-cmd="ls -la" type="button">ls -la</button>
            <button class="chip" data-cmd="python3 --version" type="button">python3 --version</button>
            <button class="chip" data-cmd="python3 hello.py" type="button">python3 hello.py</button>
            <button class="chip" data-cmd="git status" type="button">git status</button>
            <button class="chip" data-cmd="uname -a" type="button">uname -a</button>
            <button id="clearTermBtn" class="btn btn-ghost btn-sm" style="margin-left:auto;" type="button">Очистити</button>
          </div>

          <div id="termOutput" class="term-out">Готово. Команди виконуються в робочій папці цього сервера.\n</div>

          <form id="termForm" style="display:flex; gap:8px; margin-top:10px;">
            <input id="termCwd" class="mono" type="text" style="max-width:170px;" placeholder="підпапка (опц.)" title="Відносна робоча папка" />
            <input id="termInput" class="mono" type="text" placeholder="Введи команду (напр. python3 hello.py або ls -la)..." autocomplete="off" />
            <button class="btn" type="submit">Виконати</button>
          </form>

          <div class="section-title"><span>Швидкий запуск Python-коду на сервері</span></div>
          <textarea id="pySnippet" class="mono" rows="5" placeholder="import os&#10;print('Файли сервера:', os.listdir('.'))"></textarea>
          <div style="margin-top:8px; display:flex; justify-content:flex-end;">
            <button id="runSnippetBtn" class="btn btn-green" type="button">▶ Виконати Python-код</button>
          </div>
        </div>

        <!-- TAB 4: GIT / GITHUB -->
        <div id="tab-git" class="tab-pane hidden">
          <div class="grid" style="margin-bottom:18px;">
            <form id="cloneRepoForm" class="stat">
              <div class="stat-k" style="font-weight:600; color:var(--text); margin-bottom:8px;">Клонувати репозиторій з GitHub</div>
              <input id="cloneUrlInput" type="text" placeholder="owner/repo або https://github.com/..." required style="margin-bottom:8px;" />
              <div style="display:flex; gap:8px;">
                <input id="cloneDirInput" type="text" placeholder="Назва папки (авто)" />
                <button class="btn" type="submit">Клонувати</button>
              </div>
            </form>

            <form id="initRepoForm" class="stat">
              <div class="stat-k" style="font-weight:600; color:var(--text); margin-bottom:8px;">Створити новий Git-репозиторій</div>
              <input id="initDirInput" type="text" placeholder="Назва папки проєкту (напр. my-bot)" required style="margin-bottom:8px;" />
              <button class="btn btn-ghost" type="submit" style="width:100%;">git init у середовищі</button>
            </form>
          </div>

          <div class="section-title">
            <span>Репозиторії в середовищі сервера</span>
            <button id="refreshReposBtn" class="btn btn-ghost btn-sm" type="button">Оновити список</button>
          </div>
          <div id="reposContainer"></div>
          <div id="gitOutputWrap" class="hidden" style="margin-top:12px;">
            <div class="muted" style="font-size:12px; margin-bottom:4px;">Вивід Git:</div>
            <div id="gitOutput" class="term-out" style="min-height:90px; max-height:200px;"></div>
          </div>
        </div>

        <!-- TAB 5: SETTINGS & ENV -->
        <div id="tab-settings" class="tab-pane hidden">
          <div class="grid">
            <form id="settingsForm" class="stat">
              <div class="stat-k" style="font-weight:600; color:var(--text); margin-bottom:10px;">Профіль сервера</div>
              <label>Назва сервера</label>
              <input id="cfgName" type="text" required style="margin-bottom:10px;" />
              <label>Опис середовища</label>
              <input id="cfgDesc" type="text" placeholder="Напр. Бекенд для ботів та GitHub" style="margin-bottom:10px;" />
              <label>Базовий порт (для наступних запусків)</label>
              <input id="cfgPort" type="number" min="1" max="65535" required style="margin-bottom:12px;" />
              <button class="btn" type="submit">Зберегти налаштування</button>
            </form>

            <form id="pwForm" class="stat">
              <div class="stat-k" style="font-weight:600; color:var(--text); margin-bottom:10px;">Зміна пароля сервера</div>
              <label>Поточний пароль</label>
              <input id="curPw" type="password" required style="margin-bottom:10px;" />
              <label>Новий пароль</label>
              <input id="newPw" type="password" required style="margin-bottom:12px;" />
              <button class="btn btn-ghost" type="submit">Оновити пароль</button>
            </form>
          </div>

          <div class="section-title"><span>Змінні середовища сервера (ENV — доступні в Python, Терміналі та Git)</span></div>
          <div class="stat">
            <div class="muted" style="font-size:12.5px; margin-bottom:8px;">
              Формат <code>KEY=VALUE</code> (по одній на рядок, напр. <code>GITHUB_TOKEN=...</code> або <code>APP_MODE=dev</code>):
            </div>
            <textarea id="envEditor" class="mono" rows="6" placeholder="APP_ENV=development&#10;MY_SECRET=12345"></textarea>
            <div style="margin-top:10px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
              <button id="saveEnvBtn" class="btn" type="button">Зберегти ENV змінні</button>
              <button id="stopServerBtn" class="btn btn-danger" type="button">Зупинити сервер віддалено</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div id="toast" class="toast hidden"></div>

  <script>
    const TOKEN_KEY = "wigi_auth_token";
    function getToken() {{
      try {{ return sessionStorage.getItem(TOKEN_KEY) || ""; }} catch (_) {{ return window.__wigiToken || ""; }}
    }}
    function setToken(t) {{
      window.__wigiToken = t;
      try {{
        if (t) sessionStorage.setItem(TOKEN_KEY, t);
        else sessionStorage.removeItem(TOKEN_KEY);
      }} catch (_) {{}}
    }}
    function authHeaders(extra) {{
      const h = Object.assign({{ "Content-Type": "application/json" }}, extra || {{}});
      const t = getToken();
      if (t) h["Authorization"] = "Bearer " + t;
      return h;
    }}
    async function api(url, opts) {{
      const options = opts || {{}};
      options.headers = authHeaders(options.headers);
      const res = await fetch(url, options);
      if (res.status === 401 && url !== "api/login") {{
        showLogin();
        throw new Error("Unauthorized");
      }}
      const data = await res.json();
      return {{ res, data }};
    }}
    function notify(msg, isErr) {{
      const el = document.getElementById("toast");
      el.textContent = msg;
      el.style.borderColor = isErr ? "var(--red)" : "var(--accent)";
      el.classList.remove("hidden");
      clearTimeout(window.__toastT);
      window.__toastT = setTimeout(() => el.classList.add("hidden"), 3000);
    }}
    function fmtUptime(sec) {{
      const h = Math.floor(sec / 3600);
      const m = Math.floor((sec % 3600) / 60);
      const s = sec % 60;
      return `${{String(h).padStart(2,"0")}}:${{String(m).padStart(2,"0")}}:${{String(s).padStart(2,"0")}}`;
    }}
    function fmtBytes(b) {{
      if (b == null) return "";
      if (b < 1024) return b + " B";
      if (b < 1024 * 1024) return (b / 1024).toFixed(1) + " KB";
      return (b / (1024 * 1024)).toFixed(2) + " MB";
    }}

    const loginView = document.getElementById("loginView");
    const appView = document.getElementById("appView");
    const logoutBtn = document.getElementById("logoutBtn");
    const loginErr = document.getElementById("loginErr");
    let pollTimer = null;
    let activeTab = "overview";
    let currentDir = "";
    let currentParentDir = "";
    let currentEditingPath = "";
    const cmdHistory = [];
    let cmdIdx = -1;

    // Tabs switching
    document.querySelectorAll(".tab-btn").forEach(btn => {{
      btn.addEventListener("click", () => switchTab(btn.dataset.tab));
    }});
    function switchTab(tab) {{
      activeTab = tab;
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.toggle("active", b.dataset.tab === tab));
      document.querySelectorAll(".tab-pane").forEach(p => p.classList.toggle("hidden", p.id !== "tab-" + tab));
      if (tab === "overview") loadOverview();
      if (tab === "files") loadFiles(currentDir);
      if (tab === "git") loadRepos();
      if (tab === "settings") loadSettingsTab();
    }}

    // Overview
    async function loadOverview() {{
      try {{
        const {{ data }} = await api("api/status");
        if (!data.ok) return;
        loginView.classList.add("hidden");
        appView.classList.remove("hidden");
        logoutBtn.classList.remove("hidden");
        document.getElementById("launchOsTopBtn").classList.remove("hidden");

        document.getElementById("hdrTitle").textContent = data.server.name;
        document.getElementById("hdrSub").textContent = `${{data.server.description || "Персональне Python-середовище сервера"}} • Хост: ${{data.host.hostname}}`;
        document.getElementById("stName").textContent = `${{data.server.name}} (#${{data.server.id}})`;
        document.getElementById("stUptime").textContent = fmtUptime(data.server.uptime_seconds);
        document.getElementById("stLocal").textContent = data.host.local_url;
        document.getElementById("stLan").textContent = data.host.lan_url;
        const loadTxt = data.host.load_avg ? ` • Load ${{data.host.load_avg[0]}}` : "";
        document.getElementById("stSys").textContent = `${{data.host.os}} • ${{data.host.cpu_cores}} CPU${{loadTxt}} • Py ${{data.host.python}}`;
        document.getElementById("stDir").textContent = data.host.workspace_dir;

        if (data.host.memory) {{
          const m = data.host.memory;
          document.getElementById("stRam").textContent = `${{m.used_mb}} / ${{m.total_mb}} МБ (${{m.percent}}%)`;
          document.getElementById("barRam").style.width = Math.min(100, m.percent) + "%";
        }} else {{
          document.getElementById("stRam").textContent = "Н/Д";
        }}

        if (data.host.disk) {{
          const d = data.host.disk;
          document.getElementById("stDisk").textContent = `${{d.used_gb}} / ${{d.total_gb}} ГБ (вільно ${{d.free_gb}} ГБ)`;
          document.getElementById("barDisk").style.width = Math.min(100, d.percent) + "%";
        }}

        window.__lastStatus = data;

        const sessEl = document.getElementById("sessionsList");
        sessEl.innerHTML = "";
        (data.sessions || []).forEach(s => {{
          const row = document.createElement("div");
          row.className = "row-item";
          row.textContent = `${{s.current ? "● Поточна сесія" : "○ Сесія #" + s.id}} — IP: ${{s.ip}} (активна ${{fmtUptime(s.age_seconds)}})`;
          sessEl.appendChild(row);
        }});

        const evEl = document.getElementById("eventsList");
        evEl.innerHTML = "";
        (data.events || []).forEach(ev => {{
          const row = document.createElement("div");
          row.className = "row-item";
          row.textContent = `[${{ev.time}}] [${{ev.kind}}] ${{ev.message}}`;
          evEl.appendChild(row);
        }});
      }} catch (_) {{}}
    }}

    document.getElementById("revokeOthersBtn").addEventListener("click", async () => {{
      const {{ data }} = await api("api/sessions/revoke-others", {{ method: "POST", body: "{{}}" }});
      if (data.ok) {{
        notify(`Завершено інших сесій: ${{data.removed}}`);
        loadOverview();
      }}
    }});

    // File Manager & Editor
    async function loadFiles(dirPath) {{
      const {{ data }} = await api("api/files?path=" + encodeURIComponent(dirPath || ""));
      if (!data.ok) {{ notify(data.error || "Помилка", true); return; }}
      currentDir = data.cwd || "";
      currentParentDir = data.parent || "";
      document.getElementById("curDirLabel").textContent = "/" + currentDir;
      document.getElementById("upDirBtn").disabled = !currentDir;

      const tree = document.getElementById("fileTree");
      tree.innerHTML = "";
      if (!data.items.length) {{
        tree.innerHTML = '<div class="muted" style="padding:10px;">Папка порожня</div>';
        return;
      }}
      data.items.forEach(item => {{
        const row = document.createElement("div");
        row.className = "file-row";
        const left = document.createElement("div");
        left.className = "file-name";
        const icon = item.type === "dir" ? (item.is_git ? "📦 " : "📁 ") : (item.name.endsWith(".py") ? "🐍 " : "📄 ");
        left.textContent = icon + item.name + (item.size != null ? ` (${{fmtBytes(item.size)}})` : "");
        left.addEventListener("click", () => {{
          if (item.type === "dir") loadFiles(item.path);
          else openFileInEditor(item.path);
        }});

        const actions = document.createElement("div");
        actions.style.display = "flex";
        actions.style.gap = "4px";

        if (item.type === "file") {{
          const dlBtn = document.createElement("button");
          dlBtn.className = "btn btn-ghost btn-sm";
          dlBtn.style.padding = "2px 7px";
          dlBtn.textContent = "↓";
          dlBtn.title = "Скачати";
          dlBtn.addEventListener("click", (e) => {{
            e.stopPropagation();
            downloadFile(item.path, item.name);
          }});
          actions.appendChild(dlBtn);
        }}

        const renBtn = document.createElement("button");
        renBtn.className = "btn btn-ghost btn-sm";
        renBtn.style.padding = "2px 7px";
        renBtn.textContent = "✎";
        renBtn.title = "Перейменувати";
        renBtn.addEventListener("click", async (e) => {{
          e.stopPropagation();
          const nn = prompt("Нова назва:", item.name);
          if (!nn || nn === item.name) return;
          const r = await api("api/files/rename", {{
            method: "POST",
            body: JSON.stringify({{ path: item.path, new_name: nn }})
          }});
          if (!r.data.ok) return notify(r.data.error, true);
          notify("Перейменовано");
          loadFiles(currentDir);
        }});
        actions.appendChild(renBtn);

        if (item.path !== "server.json") {{
          const delBtn = document.createElement("button");
          delBtn.className = "btn btn-danger btn-sm";
          delBtn.style.padding = "2px 7px";
          delBtn.textContent = "×";
          delBtn.title = "Видалити";
          delBtn.addEventListener("click", async (e) => {{
            e.stopPropagation();
            if (!confirm(`Видалити '${{item.name}}'?`)) return;
            const r = await api("api/files/delete", {{
              method: "POST",
              body: JSON.stringify({{ path: item.path }})
            }});
            if (!r.data.ok) return notify(r.data.error, true);
            if (currentEditingPath === item.path) {{
              currentEditingPath = "";
              document.getElementById("editorPathLabel").textContent = "не вибрано";
              document.getElementById("codeEditor").value = "";
              document.getElementById("codeEditor").disabled = true;
              document.getElementById("saveFileBtn").disabled = true;
            }}
            notify("Видалено");
            loadFiles(currentDir);
          }});
          actions.appendChild(delBtn);
        }}

        row.appendChild(left);
        row.appendChild(actions);
        tree.appendChild(row);
      }});
    }}

    async function downloadFile(relPath, fileName) {{
      const res = await fetch("api/files/download?path=" + encodeURIComponent(relPath), {{
        headers: getToken() ? {{ "Authorization": "Bearer " + getToken() }} : {{}}
      }});
      if (!res.ok) return notify("Помилка скачування", true);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = fileName;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    }}

    async function openFileInEditor(relPath) {{
      const {{ data }} = await api("api/files/read?path=" + encodeURIComponent(relPath));
      if (!data.ok) return notify(data.error, true);
      currentEditingPath = data.path;
      document.getElementById("editorPathLabel").textContent = data.path;
      const ed = document.getElementById("codeEditor");
      ed.disabled = false;
      ed.value = data.content;
      document.getElementById("saveFileBtn").disabled = false;
      document.getElementById("runPyFileBtn").classList.toggle("hidden", !data.path.endsWith(".py"));
    }}

    async function saveCurrentFile() {{
      if (!currentEditingPath) return;
      const content = document.getElementById("codeEditor").value;
      const {{ data }} = await api("api/files/write", {{
        method: "POST",
        body: JSON.stringify({{ path: currentEditingPath, content }})
      }});
      if (!data.ok) return notify(data.error, true);
      notify(`Збережено ${{data.path}}`);
      loadFiles(currentDir);
    }}

    document.getElementById("saveFileBtn").addEventListener("click", saveCurrentFile);
    document.getElementById("codeEditor").addEventListener("keydown", (e) => {{
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {{
        e.preventDefault();
        saveCurrentFile();
      }}
    }});

    document.getElementById("runPyFileBtn").addEventListener("click", async () => {{
      if (!currentEditingPath) return;
      await saveCurrentFile();
      const wrap = document.getElementById("pyRunOutWrap");
      const outEl = document.getElementById("pyRunOut");
      wrap.classList.remove("hidden");
      outEl.textContent = "Виконується...";
      const {{ data }} = await api("api/python/run", {{
        method: "POST",
        body: JSON.stringify({{ file: currentEditingPath }})
      }});
      if (!data.ok) {{ outEl.textContent = "Помилка: " + data.error; return; }}
      outEl.textContent = (data.stdout || "") + (data.stderr ? "\\n" + data.stderr : "") + `\\n[код виходу: ${{data.exit_code}}, ${{data.duration_ms}} мс]`;
    }});

    document.getElementById("upDirBtn").addEventListener("click", () => loadFiles(currentParentDir));
    document.getElementById("newFileBtn").addEventListener("click", async () => {{
      const name = prompt("Назва нового файлу (напр. script.py):");
      if (!name) return;
      const rel = currentDir ? (currentDir + "/" + name) : name;
      const {{ data }} = await api("api/files/write", {{
        method: "POST",
        body: JSON.stringify({{ path: rel, content: "" }})
      }});
      if (!data.ok) return notify(data.error, true);
      await loadFiles(currentDir);
      openFileInEditor(data.path);
    }});

    document.getElementById("newDirBtn").addEventListener("click", async () => {{
      const name = prompt("Назва нової папки:");
      if (!name) return;
      const rel = currentDir ? (currentDir + "/" + name) : name;
      const {{ data }} = await api("api/files/mkdir", {{
        method: "POST",
        body: JSON.stringify({{ path: rel }})
      }});
      if (!data.ok) return notify(data.error, true);
      loadFiles(currentDir);
    }});

    document.getElementById("uploadInput").addEventListener("change", (e) => {{
      const file = e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = async () => {{
        const b64 = String(reader.result).split(",")[1] || "";
        const rel = currentDir ? (currentDir + "/" + file.name) : file.name;
        const {{ data }} = await api("api/files/upload", {{
          method: "POST",
          body: JSON.stringify({{ path: rel, data_b64: b64 }})
        }});
        e.target.value = "";
        if (!data.ok) return notify(data.error, true);
        notify(`Завантажено ${{data.name}}`);
        loadFiles(currentDir);
      }};
      reader.readAsDataURL(file);
    }});

    // Terminal & Python Scratchpad
    const termOutput = document.getElementById("termOutput");
    const termInput = document.getElementById("termInput");

    function appendTerm(text) {{
      termOutput.textContent += text;
      termOutput.scrollTop = termOutput.scrollHeight;
    }}

    async function execShell(cmd) {{
      const cwd = document.getElementById("termCwd").value.trim();
      appendTerm(`\\n${{cwd ? "[" + cwd + "] " : ""}}$ ${{cmd}}\\n`);
      const {{ data }} = await api("api/exec", {{
        method: "POST",
        body: JSON.stringify({{ command: cmd, cwd }})
      }});
      if (!data.ok) {{
        appendTerm(`Помилка: ${{data.error}}\\n`);
        return;
      }}
      if (data.stdout) appendTerm(data.stdout.endsWith("\\n") ? data.stdout : data.stdout + "\\n");
      if (data.stderr) appendTerm(data.stderr.endsWith("\\n") ? data.stderr : data.stderr + "\\n");
      appendTerm(`[exit=${{data.exit_code}} • ${{data.duration_ms}} ms]\\n`);
    }}

    document.getElementById("termForm").addEventListener("submit", async (e) => {{
      e.preventDefault();
      const cmd = termInput.value.trim();
      if (!cmd) return;
      cmdHistory.unshift(cmd);
      cmdIdx = -1;
      termInput.value = "";
      await execShell(cmd);
    }});

    termInput.addEventListener("keydown", (e) => {{
      if (e.key === "ArrowUp" && cmdHistory.length) {{
        e.preventDefault();
        cmdIdx = Math.min(cmdHistory.length - 1, cmdIdx + 1);
        termInput.value = cmdHistory[cmdIdx];
      }} else if (e.key === "ArrowDown") {{
        e.preventDefault();
        cmdIdx = Math.max(-1, cmdIdx - 1);
        termInput.value = cmdIdx >= 0 ? cmdHistory[cmdIdx] : "";
      }}
    }});

    document.querySelectorAll(".chip[data-cmd]").forEach(ch => {{
      ch.addEventListener("click", () => execShell(ch.dataset.cmd));
    }});
    document.getElementById("clearTermBtn").addEventListener("click", () => {{ termOutput.textContent = ""; }});

    document.getElementById("runSnippetBtn").addEventListener("click", async () => {{
      const code = document.getElementById("pySnippet").value;
      if (!code.trim()) return notify("Введи Python-код", true);
      appendTerm("\\n>>> [Виконання Python-фрагмента]\\n");
      const {{ data }} = await api("api/python/run", {{
        method: "POST",
        body: JSON.stringify({{ code }})
      }});
      if (!data.ok) return appendTerm(`Помилка: ${{data.error}}\\n`);
      if (data.stdout) appendTerm(data.stdout.endsWith("\\n") ? data.stdout : data.stdout + "\\n");
      if (data.stderr) appendTerm(data.stderr.endsWith("\\n") ? data.stderr : data.stderr + "\\n");
      appendTerm(`[exit=${{data.exit_code}} • ${{data.duration_ms}} ms]\\n`);
    }});

    // Git / GitHub Manager
    function showGitOutput(txt) {{
      document.getElementById("gitOutputWrap").classList.remove("hidden");
      document.getElementById("gitOutput").textContent = txt;
    }}

    async function loadRepos() {{
      const {{ data }} = await api("api/git/repos");
      if (!data.ok) return;
      const box = document.getElementById("reposContainer");
      box.innerHTML = "";
      if (!data.repos.length) {{
        box.innerHTML = '<div class="stat muted">У середовищі сервера ще немає Git-репозиторіїв. Клонуй з GitHub вище або створи новий через git init!</div>';
        return;
      }}
      data.repos.forEach(repo => {{
        const card = document.createElement("div");
        card.className = "repo-card";

        const top = document.createElement("div");
        top.style.cssText = "display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:10px;";
        const title = document.createElement("div");
        title.innerHTML = `<strong style="font-size:16px;">📦 ${{repo.name}}</strong> <span class="badge" style="margin-left:8px;">гілка: ${{repo.branch}}</span>`;
        const sub = document.createElement("div");
        sub.className = "muted mono";
        sub.style.fontSize = "12px";
        sub.textContent = repo.remote_url || "локальний репозиторій (без origin)";
        title.appendChild(sub);

        const btnRow = document.createElement("div");
        btnRow.style.cssText = "display:flex; gap:6px; flex-wrap:wrap;";

        const mkActionBtn = (label, act, extraFn) => {{
          const b = document.createElement("button");
          b.className = "btn btn-ghost btn-sm";
          b.type = "button";
          b.textContent = label;
          b.addEventListener("click", async () => {{
            let payload = {{ path: repo.path, action: act }};
            if (extraFn) {{
              const extra = extraFn();
              if (!extra) return;
              Object.assign(payload, extra);
            }}
            const r = await api("api/git/action", {{ method: "POST", body: JSON.stringify(payload) }});
            if (!r.data.ok) return notify(r.data.error, true);
            showGitOutput(r.data.output);
            loadRepos();
          }});
          return b;
        }};

        btnRow.appendChild(mkActionBtn("Status", "status"));
        btnRow.appendChild(mkActionBtn("Pull", "pull"));
        btnRow.appendChild(mkActionBtn("Commit", "commit", () => {{
          const m = prompt("Текст коміту (git add -A && git commit -m):");
          return m ? {{ message: m }} : null;
        }}));
        btnRow.appendChild(mkActionBtn("Push", "push"));
        btnRow.appendChild(mkActionBtn("Гілка", "checkout", () => {{
          const br = prompt("Назва гілки (перемкнути або створити):", repo.branch);
          return br ? {{ branch: br }} : null;
        }}));

        const openFilesBtn = document.createElement("button");
        openFilesBtn.className = "btn btn-sm";
        openFilesBtn.type = "button";
        openFilesBtn.textContent = "Відкрити файли";
        openFilesBtn.addEventListener("click", () => {{
          currentDir = repo.path;
          switchTab("files");
        }});
        btnRow.appendChild(openFilesBtn);

        top.appendChild(title);
        top.appendChild(btnRow);
        card.appendChild(top);

        const info = document.createElement("div");
        info.className = "box-list";
        info.style.maxHeight = "130px";
        const lines = [];
        lines.push(`Змінених файлів: ${{repo.changed_count}}`);
        (repo.status || []).slice(0, 6).forEach(s => lines.push("  " + s));
        if ((repo.commits || []).length) {{
          lines.push("Останні коміти:");
          repo.commits.slice(0, 4).forEach(c => lines.push(`  ${{c.hash}} • ${{c.subject}} (${{c.when}})`));
        }}
        info.textContent = lines.join("\\n");
        info.style.whiteSpace = "pre-wrap";
        card.appendChild(info);
        box.appendChild(card);
      }});
    }}

    document.getElementById("refreshReposBtn").addEventListener("click", loadRepos);
    document.getElementById("cloneRepoForm").addEventListener("submit", async (e) => {{
      e.preventDefault();
      const repo = document.getElementById("cloneUrlInput").value.trim();
      const folder = document.getElementById("cloneDirInput").value.trim();
      showGitOutput("Клонування репозиторію...");
      const {{ data }} = await api("api/git/clone", {{
        method: "POST",
        body: JSON.stringify({{ repo, folder }})
      }});
      if (!data.ok) {{
        showGitOutput("Помилка: " + data.error);
        return notify(data.error, true);
      }}
      document.getElementById("cloneUrlInput").value = "";
      document.getElementById("cloneDirInput").value = "";
      showGitOutput(data.output || `Клоновано у /${{data.path}}`);
      notify(`Клоновано ${{data.name}}`);
      loadRepos();
    }});

    document.getElementById("initRepoForm").addEventListener("submit", async (e) => {{
      e.preventDefault();
      const folder = document.getElementById("initDirInput").value.trim();
      const {{ data }} = await api("api/git/init", {{
        method: "POST",
        body: JSON.stringify({{ folder }})
      }});
      if (!data.ok) return notify(data.error, true);
      document.getElementById("initDirInput").value = "";
      showGitOutput(data.output || `Створено репозиторій ${{data.path}}`);
      notify(`Ініціалізовано ${{data.name}}`);
      loadRepos();
    }});

    // Settings & ENV
    async function loadSettingsTab() {{
      if (!window.__lastStatus) await loadOverview();
      if (window.__lastStatus) {{
        const s = window.__lastStatus.server;
        document.getElementById("cfgName").value = s.name;
        document.getElementById("cfgDesc").value = s.description || "";
        document.getElementById("cfgPort").value = s.saved_port || s.port;
      }}
      const {{ data }} = await api("api/env");
      if (data.ok) {{
        const lines = Object.entries(data.env || {{}}).map(([k, v]) => `${{k}}=${{v}}`);
        document.getElementById("envEditor").value = lines.join("\\n");
      }}
    }}

    document.getElementById("settingsForm").addEventListener("submit", async (e) => {{
      e.preventDefault();
      const name = document.getElementById("cfgName").value.trim();
      const description = document.getElementById("cfgDesc").value.trim();
      const port = Number(document.getElementById("cfgPort").value);
      const {{ data }} = await api("api/server/settings", {{
        method: "POST",
        body: JSON.stringify({{ name, description, port }})
      }});
      if (!data.ok) return notify(data.error, true);
      notify("Налаштування збережено");
      loadOverview();
    }});

    document.getElementById("pwForm").addEventListener("submit", async (e) => {{
      e.preventDefault();
      const current_password = document.getElementById("curPw").value;
      const new_password = document.getElementById("newPw").value;
      const {{ data }} = await api("api/server/password", {{
        method: "POST",
        body: JSON.stringify({{ current_password, new_password }})
      }});
      if (!data.ok) return notify(data.error, true);
      document.getElementById("curPw").value = "";
      document.getElementById("newPw").value = "";
      notify("Пароль сервера успішно змінено!");
    }});

    document.getElementById("saveEnvBtn").addEventListener("click", async () => {{
      const raw = document.getElementById("envEditor").value.split("\\n");
      const env = {{}};
      for (const line of raw) {{
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith("#")) continue;
        const eq = trimmed.indexOf("=");
        if (eq === -1) return notify(`Невірний рядок ENV: ${{trimmed}}`, true);
        env[trimmed.slice(0, eq).trim()] = trimmed.slice(eq + 1);
      }}
      const {{ data }} = await api("api/env", {{
        method: "POST",
        body: JSON.stringify({{ env }})
      }});
      if (!data.ok) return notify(data.error, true);
      notify("Змінні ENV збережено");
    }});

    document.getElementById("stopServerBtn").addEventListener("click", async () => {{
      if (!confirm("Точно зупинити цей сервер?")) return;
      const {{ data }} = await api("api/server/stop", {{ method: "POST", body: "{{}}" }});
      if (data.ok) {{
        document.getElementById("hdrStatus").textContent = "STOPPED";
        notify("Сервер зупинено");
      }}
    }});

    // Auth lifecycle
    function showLogin() {{
      if (pollTimer) {{ clearInterval(pollTimer); pollTimer = null; }}
      appView.classList.add("hidden");
      logoutBtn.classList.add("hidden");
      document.getElementById("launchOsTopBtn").classList.add("hidden");
      loginView.classList.remove("hidden");
      document.getElementById("pwInput").focus();
    }}

    function startPolling() {{
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(() => {{
        if (activeTab === "overview") loadOverview();
      }}, 4000);
    }}

    document.getElementById("loginForm").addEventListener("submit", async (e) => {{
      e.preventDefault();
      loginErr.textContent = "";
      const password = document.getElementById("pwInput").value;
      const res = await fetch("api/login", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ password }})
      }});
      const data = await res.json();
      if (!res.ok || !data.ok) {{
        loginErr.textContent = data.error || "Помилка входу";
        return;
      }}
      setToken(data.token || "");
      document.getElementById("pwInput").value = "";
      await loadOverview();
      startPolling();
    }});

    logoutBtn.addEventListener("click", async () => {{
      try {{ await api("api/logout", {{ method: "POST", body: "{{}}" }}); }} catch (_) {{}}
      setToken("");
      showLogin();
    }});

    (async () => {{
      const res = await fetch("api/info", {{ headers: authHeaders() }});
      const info = await res.json();
      if (info.authenticated) {{
        await loadOverview();
        startPolling();
      }} else {{
        showLogin();
      }}
    }})();
  </script>
</body>
</html>
"""
