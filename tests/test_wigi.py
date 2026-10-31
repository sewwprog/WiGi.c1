from __future__ import annotations

import base64
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from wigi import workspace as ws_ops
from wigi.cli import run_interactive_menu
from wigi.server import WiGiHTTPServer
from wigi.storage import ServerStore, make_slug


class TestServerStorage(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.store = ServerStore(
            servers_file=base / "data" / "servers.json",
            workspaces_dir=base / "servers",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_create_manage_clone_and_delete(self) -> None:
        srv = self.store.create_server("Мій Ноут Сервер", "пароль123!", port=8123)
        self.assertEqual(srv.name, "Мій Ноут Сервер")
        self.assertEqual(srv.slug, make_slug("Мій Ноут Сервер", srv.id))
        ws_dir = Path(self.tmp.name) / "servers" / srv.slug
        self.assertTrue((ws_dir / "server.json").exists())
        self.assertTrue((ws_dir / "hello.py").exists())

        self.assertTrue(srv.verify_password("пароль123!"))
        self.assertFalse(srv.verify_password("wrong"))

        # Rename & change port & change password
        renamed = self.store.rename_server(srv.id, "Оновлений Сервер", description="Мій бекенд")
        self.assertEqual(renamed.name, "Оновлений Сервер")
        self.assertEqual(renamed.description, "Мій бекенд")

        re_ported = self.store.change_port(srv.id, 8500)
        self.assertEqual(re_ported.port, 8500)

        re_pw = self.store.change_password(srv.id, "новийПароль")
        self.assertTrue(re_pw.verify_password("новийПароль"))
        self.assertFalse(re_pw.verify_password("пароль123!"))

        # Clone server workspace
        (ws_dir / "custom.txt").write_text("hello clone", encoding="utf-8")
        cloned = self.store.clone_server(srv.id, "Клон Сервера", "clonepw", port=8501)
        clone_ws = Path(self.tmp.name) / "servers" / cloned.slug
        self.assertEqual((clone_ws / "custom.txt").read_text(encoding="utf-8"), "hello clone")

        # Duplicate name should fail
        with self.assertRaises(ValueError):
            self.store.create_server("оновлений сервер", "other", port=8124)

        self.assertTrue(self.store.delete_server(srv.id, remove_workspace=True))
        self.assertFalse(ws_dir.exists())


class TestWorkspaceOperations(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name) / "srv"
        self.ws.mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_path_traversal_blocked(self) -> None:
        with self.assertRaises(ValueError):
            ws_ops.resolve_safe_path(self.ws, "../../etc/passwd")

    def test_files_env_python_and_git(self) -> None:
        ws_ops.make_directory(self.ws, "src")
        ws_ops.write_text_file(self.ws, "src/app.py", "import os\nprint(os.environ.get('MY_TOKEN', ''))\n")
        read_back = ws_ops.read_text_file(self.ws, "src/app.py")
        self.assertIn("MY_TOKEN", read_back["content"])

        ws_ops.save_env_vars(self.ws, {"MY_TOKEN": "secret-xyz"})
        py_res = ws_ops.run_python_code(self.ws, rel_file="src/app.py")
        self.assertEqual(py_res["exit_code"], 0)
        self.assertEqual(py_res["stdout"].strip(), "secret-xyz")

        # Upload & rename & delete
        raw_b64 = base64.b64encode(b"binary-payload").decode("ascii")
        ws_ops.upload_base64_file(self.ws, "data.bin", raw_b64)
        ws_ops.rename_entry(self.ws, "data.bin", "renamed.bin")
        fname, content = ws_ops.read_binary_file(self.ws, "renamed.bin")
        self.assertEqual(fname, "renamed.bin")
        self.assertEqual(content, b"binary-payload")
        self.assertTrue(ws_ops.delete_entry(self.ws, "renamed.bin"))

        # Git init, commit, branch switch
        ws_ops.git_init(self.ws, "my-repo")
        ws_ops.write_text_file(self.ws, "my-repo/main.py", "print(1)\n")
        commit_res = ws_ops.git_action(self.ws, "my-repo", "commit", message="Initial commit")
        self.assertEqual(commit_res["exit_code"], 0)

        checkout_res = ws_ops.git_action(self.ws, "my-repo", "checkout", branch="feature-x")
        self.assertEqual(checkout_res["exit_code"], 0)

        repos = ws_ops.list_git_repos(self.ws)
        self.assertEqual(len(repos), 1)
        self.assertEqual(repos[0]["branch"], "feature-x")
        self.assertEqual(len(repos[0]["commits"]), 1)


class TestInteractiveCLI(unittest.TestCase):
    def test_create_server_without_immediate_start_then_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            store = ServerStore(
                servers_file=base / "data" / "servers.json",
                workspaces_dir=base / "servers",
            )
            fake_stdin = io.StringIO("1\nAlpha\nsecret\n8099\nn\n0\n")
            fake_stdout = io.StringIO()
            with patch("sys.stdin", fake_stdin), patch("sys.stdout", fake_stdout):
                rc = run_interactive_menu(store)

            self.assertEqual(rc, 0)
            created = store.get_by_name("Alpha")
            self.assertIsNotNone(created)
            assert created is not None
            self.assertEqual(created.port, 8099)
            self.assertTrue(created.verify_password("secret"))

    def test_select_existing_server_checks_password_and_starts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            store = ServerStore(
                servers_file=base / "data" / "servers.json",
                workspaces_dir=base / "servers",
            )
            store.create_server("MyLaptop", "pass42", port=8055)

            started_names: list[str] = []

            def fake_run_blocking(_store: ServerStore, profile: object, **_kwargs: object) -> None:
                started_names.append(getattr(profile, "name"))

            fake_stdin = io.StringIO("2\n1\nwrong\npass42\n0\n")
            fake_stdout = io.StringIO()
            with (
                patch("sys.stdin", fake_stdin),
                patch("sys.stdout", fake_stdout),
                patch("wigi.cli.run_server_blocking", side_effect=fake_run_blocking),
            ):
                rc = run_interactive_menu(store)

            self.assertEqual(rc, 0)
            self.assertEqual(started_names, ["MyLaptop"])
            out = fake_stdout.getvalue()
            self.assertIn("Невірний пароль", out)
            self.assertIn("Пароль підтверджено", out)


class TestHTTPServerFullAPI(unittest.TestCase):
    def test_http_login_files_exec_git_and_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            store = ServerStore(
                servers_file=base / "data" / "servers.json",
                workspaces_dir=base / "servers",
            )
            profile = store.create_server("TestEnv", "s3cr3t", port=8000)
            ws = store.ensure_workspace(profile)

            httpd = WiGiHTTPServer(("127.0.0.1", 0), profile, ws, quiet=True, store=store)
            port = httpd.server_address[1]
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                base_url = f"http://127.0.0.1:{port}"

                # HEAD / and GET /os healthcheck
                head_req = urllib.request.Request(f"{base_url}/", method="HEAD")
                with urllib.request.urlopen(head_req) as resp:
                    self.assertEqual(resp.status, 200)

                with urllib.request.urlopen(f"{base_url}/os") as os_resp:
                    os_html = os_resp.read().decode("utf-8")
                    self.assertEqual(os_resp.status, 200)
                    self.assertIn("WiGi OS", os_html)
                    self.assertIn("Code Studio", os_html)

                # Unauthenticated /api/files -> 401
                with self.assertRaises(urllib.error.HTTPError) as unauth_ctx:
                    urllib.request.urlopen(f"{base_url}/api/files")
                self.assertEqual(unauth_ctx.exception.code, 401)
                unauth_ctx.exception.close()

                # Login
                ok_req = urllib.request.Request(
                    f"{base_url}/api/login",
                    data=json.dumps({"password": "s3cr3t"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(ok_req) as resp:
                    token = json.loads(resp.read().decode("utf-8"))["token"]

                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }

                def post_json(path: str, payload: dict) -> dict:
                    req = urllib.request.Request(
                        f"{base_url}{path}",
                        data=json.dumps(payload).encode("utf-8"),
                        headers=headers,
                        method="POST",
                    )
                    with urllib.request.urlopen(req) as r:
                        return json.loads(r.read().decode("utf-8"))

                def get_json(path: str) -> dict:
                    req = urllib.request.Request(f"{base_url}{path}", headers=headers)
                    with urllib.request.urlopen(req) as r:
                        return json.loads(r.read().decode("utf-8"))

                # Write & run Python script via API
                w_res = post_json("/api/files/write", {"path": "calc.py", "content": "print(6 * 7)\n"})
                self.assertTrue(w_res["ok"])

                py_res = post_json("/api/python/run", {"file": "calc.py"})
                self.assertTrue(py_res["ok"])
                self.assertEqual(py_res["stdout"].strip(), "42")

                # Shell exec via API + stateful cd inside workspace
                sh_res = post_json("/api/exec", {"command": "echo wigi-ok"})
                self.assertEqual(sh_res["stdout"].strip(), "wigi-ok")

                # Git init via API
                git_res = post_json("/api/git/init", {"folder": "demo-repo"})
                self.assertTrue(git_res["ok"])
                repos_res = get_json("/api/git/repos")
                self.assertEqual(len(repos_res["repos"]), 1)

                cd_res = post_json("/api/exec", {"command": "cd demo-repo"})
                self.assertEqual(cd_res["cwd"], "demo-repo")

                # WiGi OS state, templates, search, processes, and /workspace/ static serving
                os_st = post_json(
                    "/api/os/state",
                    {
                        "theme": "nebula",
                        "sticky_note": "My OS note",
                        "tasks": [{"id": "1", "title": "Ship OS", "col": "doing", "priority": "high"}],
                    },
                )
                self.assertTrue(os_st["ok"])
                self.assertEqual(os_st["state"]["theme"], "nebula")

                tpl = post_json("/api/os/template", {"kind": "html-app", "name": "live-ui"})
                self.assertTrue(tpl["ok"])
                self.assertEqual(tpl["entry"], "live-ui/index.html")

                with urllib.request.urlopen(f"{base_url}/workspace/live-ui/index.html?token={token}") as w_resp:
                    self.assertEqual(w_resp.status, 200)
                    self.assertIn("live-ui", w_resp.read().decode("utf-8"))

                procs = get_json("/api/os/processes")
                self.assertTrue(procs["ok"])
                search_res = get_json("/api/os/search")
                self.assertTrue(any(f["path"] == "live-ui/index.html" for f in search_res["files"]))

                # Update server settings via API & check persistence
                cfg_res = post_json(
                    "/api/server/settings",
                    {"name": "ProServer", "description": "Upgraded", "port": 8088},
                )
                self.assertTrue(cfg_res["ok"])
                reloaded = store.get_by_id(profile.id)
                assert reloaded is not None
                self.assertEqual(reloaded.name, "ProServer")
                self.assertEqual(reloaded.port, 8088)

                # Logout revokes token
                post_json("/api/logout", {})
                with self.assertRaises(urllib.error.HTTPError) as after_logout:
                    get_json("/api/status")
                self.assertEqual(after_logout.exception.code, 401)
                after_logout.exception.close()
            finally:
                httpd.shutdown()
                httpd.server_close()


if __name__ == "__main__":
    unittest.main()

class TestSiteHosting(unittest.TestCase):
    def test_custom_domains_gateway_host_header_and_auth(self) -> None:
        from wigi import sites as sites_ops
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = ServerStore(servers_file=root / 'data/servers.json', workspaces_dir=root / 'servers')
            profile = store.create_server('Sites Test', 'secret', port=8000)
            ws = store.ensure_workspace(profile)
            self.assertTrue((ws / '.wigi_sites.json').exists())
            httpd = WiGiHTTPServer(('127.0.0.1', 0), profile, ws, quiet=True, store=store)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{httpd.server_address[1]}'
            def request(path: str, host: str | None = None, token: str = '', payload: dict | None = None):
                headers = {'Content-Type': 'application/json'}
                if host: headers['Host'] = host
                if token: headers['Authorization'] = 'Bearer ' + token
                req = urllib.request.Request(base + path, headers=headers,
                    data=json.dumps(payload).encode() if payload is not None else None,
                    method='POST' if payload is not None else 'GET')
                try:
                    with urllib.request.urlopen(req) as response:
                        return response.status, response.read(), dict(response.headers)
                except urllib.error.HTTPError as exc:
                    with exc:
                        return exc.code, exc.read(), dict(exc.headers)
            try:
                status, data, _ = request('/api/sites')
                self.assertEqual(status, 401)
                status, data, _ = request('/api/login', payload={'password':'secret'})
                token = json.loads(data)['token']
                status, data, _ = request('/api/sites/create', token=token, payload={
                    'domain': 'myshop.ua', 'title':'My Shop', 'template':'store'})
                self.assertEqual(status, 200)
                site = json.loads(data)['site']
                self.assertTrue((ws / site['folder'] / 'style.css').exists())
                status, body, _ = request('/s/myshop.ua/')
                self.assertEqual(status, 200)
                self.assertIn(b'My Shop', body)
                status, css, h = request('/s/myshop.ua/style.css')
                self.assertEqual(status, 200)
                self.assertIn('text/css', h['Content-Type'])
                self.assertTrue(css)
                for host in ('myshop.ua', 'www.myshop.ua', 'myshop-ua.localhost', 'myshop-ua.127.0.0.1.nip.io'):
                    self.assertEqual(request('/', host=host)[0], 200, host)
                self.assertEqual(request('/.wigi_sites.json', host='myshop.ua')[0], 404)
                self.assertEqual(request('/%2e%2e/%2e%2e/server.json', host='myshop.ua')[0], 404)
                self.assertGreater(sites_ops.get_site_by_domain(ws,'myshop.ua')['visits'], 0)
                status, data, _ = request('/api/sites/update', token=token, payload={'id': site['id'], 'enabled':False})
                self.assertEqual(status, 200)
                self.assertEqual(request('/s/myshop.ua/')[0], 503)
                self.assertEqual(request('/', host='myshop.ua')[0], 503)
                status, data, _ = request('/api/sites/delete', token=token, payload={'id':site['id']})
                self.assertEqual(status, 200)
                self.assertTrue((ws / site['folder'] / 'index.html').exists())
                self.assertEqual(request('/s/myshop.ua/')[0], 404)
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=3)

    def test_os_and_panel_scripts_parse(self) -> None:
        import re
        import shutil
        import subprocess
        from wigi.webos import render_webos_html
        from wigi.server import _render_index_html
        if shutil.which('node') is None:
            self.skipTest('node not installed')
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = ServerStore(servers_file=root / 'data/s.json', workspaces_dir=root / 'servers')
            profile = store.create_server('Scripts', 'secret')
            srv = WiGiHTTPServer(('127.0.0.1', 0), profile, store.ensure_workspace(profile), quiet=True)
            try:
                for i, html in enumerate((_render_index_html(srv), render_webos_html(srv))):
                    script = re.findall(r'<script[^>]*>(.*?)</script>', html, flags=re.S)[0]
                    path = root / f'script-{i}.js'
                    path.write_text(script, encoding='utf-8')
                    result = subprocess.run(['node', '--check', str(path)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
            finally:
                srv.server_close()

    def test_all_website_templates_emit_valid_javascript(self) -> None:
        import shutil
        import subprocess
        from wigi.sites import TEMPLATE_CHOICES, create_site
        if shutil.which('node') is None:
            self.skipTest('node not installed')
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for index, template in enumerate(TEMPLATE_CHOICES):
                site = create_site(root, f'template{index}.wigi', template=template)
                folder = root / site['folder']
                self.assertTrue((folder / 'index.html').exists())
                for script in folder.glob('*.js'):
                    result = subprocess.run(['node', '--check', str(script)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, f'{template}: {result.stderr}')
