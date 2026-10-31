"""Persistent storage and password hashing for created server profiles."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shutil

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SERVERS_FILE = DATA_DIR / "servers.json"
WORKSPACES_DIR = BASE_DIR / "servers"

PBKDF2_ITERATIONS = 200_000

_UA_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e",
    "є": "ye", "ж": "zh", "з": "z", "и": "y", "і": "i", "ї": "yi", "й": "y",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "shch", "ь": "", "ю": "yu", "я": "ya", "ы": "y", "э": "e",
    "ё": "yo", "ъ": "",
}


def make_slug(name: str, fallback_id: str) -> str:
    """Convert any server name (including Ukrainian) into a clean folder slug."""
    lowered = name.strip().lower()
    transliterated = "".join(_UA_TRANSLIT.get(ch, ch) for ch in lowered)
    slug = re.sub(r"[^a-z0-9]+", "-", transliterated).strip("-")
    if not slug:
        slug = f"server-{fallback_id}"
    return slug[:48]


def hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    """Return `(salt_hex, hash_hex)` using PBKDF2-HMAC-SHA256."""
    if salt_hex is None:
        salt_bytes = secrets.token_bytes(16)
        salt_hex = salt_bytes.hex()
    else:
        salt_bytes = bytes.fromhex(salt_hex)

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_bytes,
        PBKDF2_ITERATIONS,
    )
    return salt_hex, digest.hex()


@dataclass
class ServerProfile:
    id: str
    name: str
    slug: str
    port: int
    password_salt: str
    password_hash: str
    created_at: str
    last_started_at: str | None = None
    description: str = ""

    def verify_password(self, password: str) -> bool:
        _, candidate_hash = hash_password(password, self.password_salt)
        return hmac.compare_digest(self.password_hash, candidate_hash)

    @property
    def workspace_dir(self) -> Path:
        return WORKSPACES_DIR / self.slug


class ServerStore:
    """Manages server profiles stored in `data/servers.json` and workspaces in `servers/`."""

    def __init__(
        self,
        servers_file: Path = SERVERS_FILE,
        workspaces_dir: Path = WORKSPACES_DIR,
    ) -> None:
        self.servers_file = servers_file
        self.workspaces_dir = workspaces_dir

    def _load_raw(self) -> list[dict]:
        if not self.servers_file.exists():
            return []
        try:
            data = json.loads(self.servers_file.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("servers"), list):
                return data["servers"]
            if isinstance(data, list):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return []

    def _save_raw(self, records: list[dict]) -> None:
        self.servers_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.servers_file.with_suffix(".tmp")
        payload = json.dumps({"servers": records}, ensure_ascii=False, indent=2)
        tmp_path.write_text(payload, encoding="utf-8")
        if os.name != "nt":
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                pass
        tmp_path.replace(self.servers_file)

    def list_servers(self) -> list[ServerProfile]:
        profiles: list[ServerProfile] = []
        for item in self._load_raw():
            try:
                allowed = {
                    k: v
                    for k, v in item.items()
                    if k
                    in {
                        "id",
                        "name",
                        "slug",
                        "port",
                        "password_salt",
                        "password_hash",
                        "created_at",
                        "last_started_at",
                        "description",
                    }
                }
                profiles.append(ServerProfile(**allowed))
            except TypeError:
                continue
        return profiles

    def get_by_id(self, server_id: str) -> ServerProfile | None:
        for profile in self.list_servers():
            if profile.id == server_id:
                return profile
        return None

    def get_by_name(self, name: str) -> ServerProfile | None:
        normalized = name.strip().lower()
        for profile in self.list_servers():
            if profile.name.strip().lower() == normalized:
                return profile
        return None

    def ensure_workspace(self, profile: ServerProfile) -> Path:
        ws = self.workspaces_dir / profile.slug
        is_new = not ws.exists()
        ws.mkdir(parents=True, exist_ok=True)
        meta_file = ws / "server.json"
        meta = {
            "id": profile.id,
            "name": profile.name,
            "slug": profile.slug,
            "created_at": profile.created_at,
            "description": profile.description,
        }
        if not meta_file.exists():
            meta_file.write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        if is_new:
            starter_py = ws / "hello.py"
            if not starter_py.exists():
                starter_py.write_text(
                    'import platform\nimport datetime\n\n'
                    f'print("Привіт із сервера {profile.name}!")\n'
                    'print("Система:", platform.system(), platform.release())\n'
                    'print("Час:", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))\n',
                    encoding="utf-8",
                )
            notes_md = ws / "notes.md"
            if not notes_md.exists():
                notes_md.write_text(
                    f"# {profile.name}\n\nРобоче середовище сервера `{profile.slug}`.\n\n"
                    "- Python-скрипт: `hello.py`\n"
                    "- Веб-додаток HTML: `web_demo/index.html`\n",
                    encoding="utf-8",
                )
            try:
                from wigi.workspace import create_project_template
                from wigi.sites import create_site

                if not (ws / "web_demo").exists():
                    create_project_template(ws, "html-app", "web_demo")
                if not (ws / ".wigi_sites.json").exists():
                    create_site(ws, domain="nexus.wigi", title="Nexus Studio", template="landing")
            except Exception:
                pass
        return ws

    def create_server(
        self,
        name: str,
        password: str,
        port: int = 8000,
        description: str = "",
    ) -> ServerProfile:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Назва сервера не може бути порожньою.")
        if not password:
            raise ValueError("Пароль не може бути порожнім.")
        if self.get_by_name(clean_name) is not None:
            raise ValueError(f"Сервер з назвою '{clean_name}' вже існує.")
        if not (1 <= port <= 65535):
            raise ValueError("Порт має бути в діапазоні 1..65535.")

        existing = self.list_servers()
        existing_slugs = {s.slug for s in existing}

        server_id = secrets.token_hex(4)
        base_slug = make_slug(clean_name, server_id)
        slug = base_slug
        if slug in existing_slugs:
            slug = f"{base_slug}-{server_id[:4]}"

        salt_hex, hash_hex = hash_password(password)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        profile = ServerProfile(
            id=server_id,
            name=clean_name,
            slug=slug,
            port=port,
            password_salt=salt_hex,
            password_hash=hash_hex,
            created_at=now_str,
            last_started_at=None,
            description=description.strip(),
        )

        records = [asdict(s) for s in existing]
        records.append(asdict(profile))
        self._save_raw(records)
        self.ensure_workspace(profile)
        return profile

    def mark_started(self, server_id: str, port: int | None = None) -> ServerProfile | None:
        profiles = self.list_servers()
        updated: ServerProfile | None = None
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for profile in profiles:
            if profile.id == server_id:
                profile.last_started_at = now_str
                if port is not None:
                    profile.port = port
                updated = profile
                break

        if updated is not None:
            self._save_raw([asdict(p) for p in profiles])
            self.ensure_workspace(updated)
        return updated

    def rename_server(self, server_id: str, new_name: str, description: str | None = None) -> ServerProfile:
        clean_name = new_name.strip()
        if not clean_name:
            raise ValueError("Нова назва не може бути порожньою.")

        profiles = self.list_servers()
        for p in profiles:
            if p.id != server_id and p.name.strip().lower() == clean_name.lower():
                raise ValueError(f"Сервер з назвою '{clean_name}' вже існує.")

        target: ServerProfile | None = None
        for p in profiles:
            if p.id == server_id:
                p.name = clean_name
                if description is not None:
                    p.description = description.strip()
                target = p
                break

        if target is None:
            raise ValueError("Сервер не знайдено.")

        self._save_raw([asdict(p) for p in profiles])
        return target

    def change_password(self, server_id: str, new_password: str) -> ServerProfile:
        if not new_password:
            raise ValueError("Новий пароль не може бути порожнім.")

        profiles = self.list_servers()
        target: ServerProfile | None = None
        for p in profiles:
            if p.id == server_id:
                salt_hex, hash_hex = hash_password(new_password)
                p.password_salt = salt_hex
                p.password_hash = hash_hex
                target = p
                break

        if target is None:
            raise ValueError("Сервер не знайдено.")

        self._save_raw([asdict(p) for p in profiles])
        return target

    def change_port(self, server_id: str, new_port: int) -> ServerProfile:
        if not (1 <= new_port <= 65535):
            raise ValueError("Порт має бути в діапазоні 1..65535.")

        profiles = self.list_servers()
        target: ServerProfile | None = None
        for p in profiles:
            if p.id == server_id:
                p.port = new_port
                target = p
                break

        if target is None:
            raise ValueError("Сервер не знайдено.")

        self._save_raw([asdict(p) for p in profiles])
        return target

    def clone_server(
        self,
        source_id: str,
        new_name: str,
        new_password: str,
        port: int = 8000,
    ) -> ServerProfile:
        src = self.get_by_id(source_id)
        if src is None:
            raise ValueError("Вихідний сервер не знайдено.")

        cloned = self.create_server(
            name=new_name,
            password=new_password,
            port=port,
            description=src.description,
        )
        src_ws = self.workspaces_dir / src.slug
        dst_ws = self.workspaces_dir / cloned.slug
        if src_ws.exists():
            for item in src_ws.iterdir():
                if item.name == "server.json":
                    continue
                target_item = dst_ws / item.name
                if item.is_dir():
                    shutil.copytree(item, target_item, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, target_item)
        return cloned

    def delete_server(self, server_id: str, remove_workspace: bool = True) -> bool:
        profiles = self.list_servers()
        target: ServerProfile | None = None
        remaining: list[ServerProfile] = []

        for profile in profiles:
            if profile.id == server_id:
                target = profile
            else:
                remaining.append(profile)

        if target is None:
            return False

        self._save_raw([asdict(p) for p in remaining])
        if remove_workspace:
            ws = self.workspaces_dir / target.slug
            if ws.exists():
                shutil.rmtree(ws, ignore_errors=True)
        return True
