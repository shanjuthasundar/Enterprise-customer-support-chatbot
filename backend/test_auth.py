import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


class AuthenticationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory(prefix="kindred-auth-test-")
        self.database_patcher = patch.object(
            main,
            "ACCOUNT_DATABASE",
            Path(self.temp_directory.name) / "accounts.sqlite3",
        )
        self.database_patcher.start()
        main.COOKIE_SECURE = False
        main._initialize_auth_database()
        self.client = TestClient(main.app)
        self.client.__enter__()
        self.origin = {"Origin": "http://localhost:5173"}

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.database_patcher.stop()
        self.temp_directory.cleanup()

    def signup(self) -> dict[str, object]:
        response = self.client.post(
            "/api/auth/signup",
            headers=self.origin,
            json={
                "display_name": "Taylor Reed",
                "email": "Taylor@example.com",
                "password": "correct horse battery",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertIn("httponly", response.headers.get("set-cookie", "").lower())
        self.assertIn("samesite=lax", response.headers.get("set-cookie", "").lower())
        return response.json()

    def test_profile_and_http_only_session_survive_a_new_client(self) -> None:
        result = self.signup()
        self.assertEqual(result["user"]["display_name"], "Taylor Reed")
        self.assertEqual(result["user"]["email"], "taylor@example.com")
        cookie = self.client.cookies.get(main.SESSION_COOKIE)
        self.assertTrue(cookie)

        connection = sqlite3.connect(main.ACCOUNT_DATABASE)
        try:
            password_hash = connection.execute(
                "SELECT password_hash FROM users WHERE email = ?",
                ("taylor@example.com",),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertTrue(password_hash.startswith("scrypt$"))
        self.assertNotEqual(password_hash, "correct horse battery")

        self.client.__exit__(None, None, None)
        with TestClient(main.app) as reloaded_client:
            reloaded_client.cookies.set(main.SESSION_COOKIE, cookie, path="/api")
            profile = reloaded_client.get("/api/auth/me")
            self.assertEqual(profile.status_code, 200, profile.text)
            self.assertEqual(profile.json()["user"]["display_name"], "Taylor Reed")
            self.assertEqual(profile.json()["user"]["email"], "taylor@example.com")
        self.client = TestClient(main.app)
        self.client.__enter__()

    def test_login_logout_duplicate_signup_and_rate_limit(self) -> None:
        self.signup()
        duplicate = self.client.post(
            "/api/auth/signup",
            headers=self.origin,
            json={
                "display_name": "Taylor Reed",
                "email": "taylor@example.com",
                "password": "correct horse battery",
            },
        )
        self.assertEqual(duplicate.status_code, 409)

        logout = self.client.post("/api/auth/logout", headers=self.origin)
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

        for attempt in range(10):
            response = self.client.post(
                "/api/auth/login",
                headers=self.origin,
                json={"email": "taylor@example.com", "password": f"incorrect password {attempt}"},
            )
            self.assertEqual(response.status_code, 401, response.text)
        blocked = self.client.post(
            "/api/auth/login",
            headers=self.origin,
            json={"email": "taylor@example.com", "password": "correct horse battery"},
        )
        self.assertEqual(blocked.status_code, 429)

    def test_signup_validates_passwords_and_rejects_untrusted_origins(self) -> None:
        weak_password = self.client.post(
            "/api/auth/signup",
            headers=self.origin,
            json={"display_name": "Taylor Reed", "email": "taylor@example.com", "password": "short"},
        )
        self.assertEqual(weak_password.status_code, 422)

        untrusted_origin = self.client.post(
            "/api/auth/login",
            headers={"Origin": "https://attacker.example"},
            json={"email": "taylor@example.com", "password": "irrelevant"},
        )
        self.assertEqual(untrusted_origin.status_code, 403)

        missing_origin = self.client.post(
            "/api/auth/login",
            json={"email": "taylor@example.com", "password": "irrelevant"},
        )
        self.assertEqual(missing_origin.status_code, 403)

    def test_workspace_endpoints_require_a_session(self) -> None:
        self.assertEqual(self.client.get("/api/documents").status_code, 401)
        chat = self.client.post(
            "/api/chat",
            headers=self.origin,
            json={"message": "How can I return my order?"},
        )
        self.assertEqual(chat.status_code, 401)


if __name__ == "__main__":
    unittest.main()
