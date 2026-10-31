"""HTTP & API server instance for a selected WiGi ServerProfile."""

from __future__ import annotations

from collections import deque
from datetime import datetime
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import html
import json
from pathlib import Path
import platform
import secrets
import socket
import sys
import threading
import time
from typing import Any
from urllib.parse import urlparse

from wigi.network import get_lan_ip
from wigi.storage import ServerProfile


class WiGiHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        profile: ServerProfile,
        workspace_dir: Path,
        quiet: bool = False,
    ) -> None:
        self.profile = profile
        self.workspace_dir = workspace_dir
        self.quiet = quiet
        self.started_at = time.time()
        self.started_at_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.lan_ip = get_lan_ip()
        self.hostname = socket.gethostname()
        self._lock = threading.Lock()
        self._sessions: dict[str, float] = {}  # token -> created_at
        self._events: deque[dict[str, str]] = deque(maxlen=50)
        self.record_event("SYSTEM", f"Сервер '{profile.name}' запущено на порту {server_address[1]}")
        super().__init__(server_address, WiGiRequestHandler)

    def record_event(self, kind: str, message: str) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            self._events.appendleft({"time": now, "kind": kind, "message": message})
        if not self.quiet:
            print(f"  [{now}] [{kind}] {message}", flush=True)

    def create_session(self) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[token] = time.time()
        return token

    def validate_session(self, token: str | None) -> bool:
        if not token:
            return False
        with self._lock:
            created = self._sessions.get(token)
            if created is None:
                return False
            # 24h session TTL
            if time.time() - created > 86400:
                self._sessions.pop(token, None)
                return False
            return True

    def revoke_session(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)

    def list_events(self) -> list[dict[str, str]]:
        with self._lock:
            return list(self._events)


class WiGiRequestHandler(BaseHTTPRequestHandler):
    server: WiGiHTTPServer  # type narrowing

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress default noisy BaseHTTPRequestHandler stderr logging;
        # structured events are logged via server.record_event().
        return

    def _client_ip(self) -> str:
        forwarded = self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        return forwarded or self.client_address[0]

    def _extract_token(self) -> str | None:
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            if token:
                return token

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
        self.wfile.write(body)

    def _send_html(self, status: int, content: str) -> None:
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        length_str = self.headers.get("Content-Length", "0")
        try:
            length = min(int(length_str), 1024 * 64)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
            return parsed if isinstance(parsed, dict) else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"

        if route == "/":
            self._send_html(200, _render_index_html(self.server))
            return

        if route == "/api/info":
            self._send_json(
                200,
                {
                    "online": True,
                    "id": self.server.profile.id,
                    "name": self.server.profile.name,
                    "hostname": self.server.hostname,
                    "authenticated": self._is_authenticated(),
                },
            )
            return

        if route == "/api/status":
            if not self._is_authenticated():
                self._send_json(401, {"ok": False, "error": "Потрібна авторизація паролем сервера."})
                return

            uptime_sec = int(max(0.0, time.time() - self.server.started_at))
            files = []
            if self.server.workspace_dir.exists():
                for p in sorted(self.server.workspace_dir.iterdir(), key=lambda x: x.name):
                    files.append(
                        {
                            "name": p.name,
                            "type": "dir" if p.is_dir() else "file",
                            "size": p.stat().st_size if p.is_file() else None,
                        }
                    )

            port = self.server.server_address[1]
            self._send_json(
                200,
                {
                    "ok": True,
                    "server": {
                        "id": self.server.profile.id,
                        "name": self.server.profile.name,
                        "slug": self.server.profile.slug,
                        "port": port,
                        "created_at": self.server.profile.created_at,
                        "started_at": self.server.started_at_str,
                        "uptime_seconds": uptime_sec,
                    },
                    "host": {
                        "hostname": self.server.hostname,
                        "os": f"{platform.system()} {platform.release()}",
                        "python": sys.version.split()[0],
                        "local_url": f"http://127.0.0.1:{port}",
                        "lan_url": f"http://{self.server.lan_ip}:{port}",
                        "workspace_dir": str(self.server.workspace_dir),
                    },
                    "workspace_files": files,
                    "events": self.server.list_events(),
                },
            )
            return

        self._send_json(404, {"ok": False, "error": "Маршрут не знайдено."})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"

        if route == "/api/login":
            data = self._read_json_body()
            password = str(data.get("password", ""))
            client_ip = self._client_ip()

            if not self.server.profile.verify_password(password):
                time.sleep(0.25)
                self.server.record_event("AUTH", f"Невдала спроба входу з {client_ip}")
                self._send_json(401, {"ok": False, "error": "Невірний пароль сервера."})
                return

            token = self.server.create_session()
            self.server.record_event("AUTH", f"Успішний вхід на сервер з {client_ip}")
            cookie_val = f"wigi_session={token}; HttpOnly; Path=/; Max-Age=86400; SameSite=Lax"
            self._send_json(
                200,
                {"ok": True, "token": token, "name": self.server.profile.name},
                extra_headers=[("Set-Cookie", cookie_val)],
            )
            return

        if route == "/api/logout":
            token = self._extract_token()
            self.server.revoke_session(token)
            cookie_val = "wigi_session=; HttpOnly; Path=/; Max-Age=0; SameSite=Lax"
            self._send_json(
                200,
                {"ok": True},
                extra_headers=[("Set-Cookie", cookie_val)],
            )
            return

        self._send_json(404, {"ok": False, "error": "Маршрут не знайдено."})


def _render_index_html(srv: WiGiHTTPServer) -> str:
    safe_name = html.escape(srv.profile.name)
    safe_host = html.escape(srv.hostname)
    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{safe_name} — WiGi Server</title>
  <style>
    :root {{
      --bg: #0b0f17;
      --panel: #121826;
      --panel-2: #182032;
      --border: #253047;
      --text: #e6edf7;
      --muted: #8fa0bc;
      --accent: #38bdf8;
      --green: #22c55e;
      --red: #ef4444;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      background: radial-gradient(circle at top, #131c2e 0%, var(--bg) 65%);
      color: var(--text);
      min-height: 100vh;
      padding: 24px 16px;
      display: flex;
      justify-content: center;
      align-items: flex-start;
    }}
    .wrap {{ width: 100%; max-width: 820px; margin-top: 24px; }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 24px;
      box-shadow: 0 18px 40px rgba(0, 0, 0, 0.4);
    }}
    .top {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 20px;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: 12px;
      font-weight: 600;
      padding: 5px 10px;
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
    .sub {{ color: var(--muted); font-size: 13px; margin-top: 4px; }}
    .login-box {{ max-width: 420px; margin: 28px auto 8px; }}
    label {{ display: block; font-size: 13px; color: var(--muted); margin-bottom: 8px; }}
    input[type="password"] {{
      width: 100%;
      background: var(--panel-2);
      border: 1px solid var(--border);
      color: var(--text);
      border-radius: 10px;
      padding: 12px 14px;
      font-size: 15px;
      outline: none;
      transition: border-color 0.15s;
    }}
    input[type="password"]:focus {{ border-color: var(--accent); }}
    .btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: none;
      border-radius: 10px;
      padding: 11px 18px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      background: var(--accent);
      color: #06131f;
      transition: opacity 0.15s;
    }}
    .btn:hover {{ opacity: 0.9; }}
    .btn-full {{ width: 100%; margin-top: 12px; }}
    .btn-ghost {{
      background: transparent;
      color: var(--muted);
      border: 1px solid var(--border);
      padding: 7px 13px;
      font-size: 13px;
    }}
    .btn-ghost:hover {{ color: var(--text); border-color: var(--muted); }}
    .err {{
      margin-top: 10px;
      color: #fca5a5;
      font-size: 13px;
      min-height: 18px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
      gap: 12px;
      margin-top: 16px;
    }}
    .stat {{
      background: var(--panel-2);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 13px 15px;
    }}
    .stat-k {{ font-size: 12px; color: var(--muted); margin-bottom: 4px; }}
    .stat-v {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 13.5px;
      word-break: break-all;
    }}
    .section-title {{
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--muted);
      margin: 22px 0 10px;
    }}
    .box-list {{
      background: #0c111b;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px 14px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12.5px;
      max-height: 220px;
      overflow-y: auto;
    }}
    .row-item {{ padding: 4px 0; border-bottom: 1px solid rgba(37, 48, 71, 0.45); }}
    .row-item:last-child {{ border-bottom: none; }}
    .muted {{ color: var(--muted); }}
    .hidden {{ display: none !important; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <div class="top">
        <div>
          <h1>{safe_name}</h1>
          <div class="sub">Хост: {safe_host} &bull; WiGi Python Environment</div>
        </div>
        <div style="display:flex; align-items:center; gap:10px;">
          <span class="badge"><span class="dot"></span> ONLINE</span>
          <button id="logoutBtn" class="btn btn-ghost hidden" type="button">Вийти</button>
        </div>
      </div>

      <div id="loginView" class="login-box hidden">
        <form id="loginForm">
          <label for="pwInput">Сервер захищено паролем. Введіть пароль для доступу:</label>
          <input id="pwInput" type="password" placeholder="Пароль сервера..." autocomplete="current-password" required />
          <button class="btn btn-full" type="submit">Увійти на сервер</button>
          <div id="loginErr" class="err"></div>
        </form>
      </div>

      <div id="dashView" class="hidden">
        <div class="grid">
          <div class="stat">
            <div class="stat-k">Назва / ID</div>
            <div class="stat-v" id="stName">—</div>
          </div>
          <div class="stat">
            <div class="stat-k">Час роботи (Uptime)</div>
            <div class="stat-v" id="stUptime">—</div>
          </div>
          <div class="stat">
            <div class="stat-k">Локальна адреса</div>
            <div class="stat-v" id="stLocal">—</div>
          </div>
          <div class="stat">
            <div class="stat-k">Адреса в мережі (LAN)</div>
            <div class="stat-v" id="stLan">—</div>
          </div>
          <div class="stat">
            <div class="stat-k">Система / Python</div>
            <div class="stat-v" id="stSys">—</div>
          </div>
          <div class="stat">
            <div class="stat-k">Робоча папка середовища</div>
            <div class="stat-v" id="stDir">—</div>
          </div>
        </div>

        <div class="section-title">Файли середовища сервера</div>
        <div class="box-list" id="filesList"></div>

        <div class="section-title">Журнал подій</div>
        <div class="box-list" id="eventsList"></div>
      </div>
    </div>
  </div>

  <script>
    const TOKEN_KEY = "wigi_token_" + location.pathname;
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
    function authHeaders() {{
      const h = {{ "Content-Type": "application/json" }};
      const t = getToken();
      if (t) h["Authorization"] = "Bearer " + t;
      return h;
    }}
    function fmtUptime(sec) {{
      const h = Math.floor(sec / 3600);
      const m = Math.floor((sec % 3600) / 60);
      const s = sec % 60;
      return `${{String(h).padStart(2,"0")}}:${{String(m).padStart(2,"0")}}:${{String(s).padStart(2,"0")}}`;
    }}

    const loginView = document.getElementById("loginView");
    const dashView = document.getElementById("dashView");
    const logoutBtn = document.getElementById("logoutBtn");
    const loginErr = document.getElementById("loginErr");
    let pollTimer = null;

    async function loadDashboard() {{
      const res = await fetch("api/status", {{ headers: authHeaders() }});
      if (res.status === 401) {{
        showLogin();
        return;
      }}
      const data = await res.json();
      if (!data.ok) return;

      loginView.classList.add("hidden");
      dashView.classList.remove("hidden");
      logoutBtn.classList.remove("hidden");

      document.getElementById("stName").textContent = `${{data.server.name}} (#${{data.server.id}})`;
      document.getElementById("stUptime").textContent = fmtUptime(data.server.uptime_seconds);
      document.getElementById("stLocal").textContent = data.host.local_url;
      document.getElementById("stLan").textContent = data.host.lan_url;
      document.getElementById("stSys").textContent = `${{data.host.os}} • Python ${{data.host.python}}`;
      document.getElementById("stDir").textContent = data.host.workspace_dir;

      const filesEl = document.getElementById("filesList");
      filesEl.innerHTML = "";
      (data.workspace_files || []).forEach(f => {{
        const row = document.createElement("div");
        row.className = "row-item";
        row.textContent = (f.type === "dir" ? "[DIR]  " : "[FILE] ") + f.name + (f.size != null ? ` (${{f.size}} B)` : "");
        filesEl.appendChild(row);
      }});

      const evEl = document.getElementById("eventsList");
      evEl.innerHTML = "";
      (data.events || []).forEach(ev => {{
        const row = document.createElement("div");
        row.className = "row-item";
        row.textContent = `[${{ev.time}}] [${{ev.kind}}] ${{ev.message}}`;
        evEl.appendChild(row);
      }});
    }}

    function showLogin() {{
      if (pollTimer) {{ clearInterval(pollTimer); pollTimer = null; }}
      dashView.classList.add("hidden");
      logoutBtn.classList.add("hidden");
      loginView.classList.remove("hidden");
      document.getElementById("pwInput").focus();
    }}

    function startPolling() {{
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(loadDashboard, 3000);
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
      await loadDashboard();
      startPolling();
    }});

    logoutBtn.addEventListener("click", async () => {{
      await fetch("api/logout", {{ method: "POST", headers: authHeaders() }});
      setToken("");
      showLogin();
    }});

    (async () => {{
      const infoRes = await fetch("api/info", {{ headers: authHeaders() }});
      const info = await infoRes.json();
      if (info.authenticated) {{
        await loadDashboard();
        startPolling();
      }} else {{
        showLogin();
      }}
    }})();
  </script>
</body>
</html>
"""
