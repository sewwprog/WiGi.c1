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

                # HEAD / healthcheck
                head_req = urllib.request.Request(f"{base_url}/", method="HEAD")
                with urllib.request.urlopen(head_req) as resp:
                    self.assertEqual(resp.status, 200)

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

                # Shell exec via API
                sh_res = post_json("/api/exec", {"command": "echo wigi-ok"})
                self.assertEqual(sh_res["stdout"].strip(), "wigi-ok")

                # Git init via API
                git_res = post_json("/api/git/init", {"folder": "demo-repo"})
                self.assertTrue(git_res["ok"])
                repos_res = get_json("/api/git/repos")
                self.assertEqual(len(repos_res["repos"]), 1)

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
