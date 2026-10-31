from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

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

    def test_create_list_verify_and_delete(self) -> None:
        srv = self.store.create_server("Мій Ноут Сервер", "пароль123!", port=8123)
        self.assertEqual(srv.name, "Мій Ноут Сервер")
        self.assertEqual(srv.slug, make_slug("Мій Ноут Сервер", srv.id))
        self.assertTrue((Path(self.tmp.name) / "servers" / srv.slug / "server.json").exists())

        self.assertTrue(srv.verify_password("пароль123!"))
        self.assertFalse(srv.verify_password("wrong"))

        # Duplicate name should fail
        with self.assertRaises(ValueError):
            self.store.create_server("мій ноут сервер", "other", port=8124)

        listed = self.store.list_servers()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].id, srv.id)

        self.assertTrue(self.store.delete_server(srv.id, remove_workspace=True))
        self.assertEqual(self.store.list_servers(), [])
        self.assertFalse((Path(self.tmp.name) / "servers" / srv.slug).exists())


class TestInteractiveCLI(unittest.TestCase):
    def test_create_server_without_immediate_start_then_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            store = ServerStore(
                servers_file=base / "data" / "servers.json",
                workspaces_dir=base / "servers",
            )
            # 1 -> create, name="Alpha", password="secret", port="8099", start now="n", 0 -> exit
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

            # 2 -> select existing, 1 -> pick #1, "wrong" -> fail, "pass42" -> ok, 0 -> exit
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


class TestHTTPServerAuth(unittest.TestCase):
    def test_http_login_status_and_logout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            store = ServerStore(
                servers_file=base / "data" / "servers.json",
                workspaces_dir=base / "servers",
            )
            profile = store.create_server("TestEnv", "s3cr3t", port=8000)
            ws = store.ensure_workspace(profile)

            httpd = WiGiHTTPServer(("127.0.0.1", 0), profile, ws, quiet=True)
            port = httpd.server_address[1]
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                base_url = f"http://127.0.0.1:{port}"

                # 1. Public info
                with urllib.request.urlopen(f"{base_url}/api/info") as resp:
                    info = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(info["online"])
                    self.assertEqual(info["name"], "TestEnv")
                    self.assertFalse(info["authenticated"])

                # 2. Protected status without token -> 401
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(f"{base_url}/api/status")
                self.assertEqual(ctx.exception.code, 401)
                ctx.exception.close()

                # 3. Wrong password -> 401
                bad_req = urllib.request.Request(
                    f"{base_url}/api/login",
                    data=json.dumps({"password": "wrong"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx2:
                    urllib.request.urlopen(bad_req)
                self.assertEqual(ctx2.exception.code, 401)
                ctx2.exception.close()

                # 4. Correct password -> 200 + token
                ok_req = urllib.request.Request(
                    f"{base_url}/api/login",
                    data=json.dumps({"password": "s3cr3t"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(ok_req) as resp:
                    login_data = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(login_data["ok"])
                    token = login_data["token"]

                # 5. Authenticated /api/status -> 200
                status_req = urllib.request.Request(
                    f"{base_url}/api/status",
                    headers={"Authorization": f"Bearer {token}"},
                )
                with urllib.request.urlopen(status_req) as resp:
                    st = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(st["ok"])
                    self.assertEqual(st["server"]["name"], "TestEnv")

                # 6. Logout revokes token
                logout_req = urllib.request.Request(
                    f"{base_url}/api/logout",
                    headers={"Authorization": f"Bearer {token}"},
                    method="POST",
                )
                with urllib.request.urlopen(logout_req) as resp:
                    self.assertEqual(resp.status, 200)

                with self.assertRaises(urllib.error.HTTPError) as ctx3:
                    urllib.request.urlopen(status_req)
                self.assertEqual(ctx3.exception.code, 401)
                ctx3.exception.close()
            finally:
                httpd.shutdown()
                httpd.server_close()


if __name__ == "__main__":
    unittest.main()
