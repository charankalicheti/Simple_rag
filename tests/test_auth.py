import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import main


class AuthenticationFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(cls.temp_dir.name) / "test.db"
        main.engine = create_engine(f"sqlite:///{database_path}", connect_args={"check_same_thread": False})
        main.SessionLocal = sessionmaker(bind=main.engine, expire_on_commit=False)
        main.AI_API_KEY = ""

    @classmethod
    def tearDownClass(cls):
        main.engine.dispose()
        cls.temp_dir.cleanup()

    def setUp(self):
        main.Base.metadata.drop_all(main.engine)
        main.Base.metadata.create_all(main.engine)
        self.client = TestClient(main.app, follow_redirects=False)

    def tearDown(self):
        self.client.close()

    def test_register_login_protected_home_and_logout(self):
        self.assertEqual(self.client.get("/").status_code, 303)

        register_page = self.client.get("/register")
        token = self.csrf_token(register_page.text)
        response = self.client.post(
            "/register",
            data={
                "name": "Taylor",
                "email": "TAYLOR@example.com",
                "password": "correct-horse-7",
                "csrf_token": token,
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Ideas for your day", response.text)
        with main.SessionLocal() as db:
            user = db.scalar(select(main.User).where(main.User.email == "taylor@example.com"))
            self.assertIsNotNone(user)
            self.assertNotEqual(user.password_hash, "correct-horse-7")
            self.assertTrue(user.password_hash.startswith("$2b$"))

        home_token = self.csrf_token(response.text)
        ideas_response = self.client.post("/api/ideas", data={"csrf_token": home_token})
        self.assertEqual(ideas_response.status_code, 200)
        self.assertIn("starting collection is ready", ideas_response.text)

        logout_token = self.csrf_token(response.text)
        logout_response = self.client.post("/logout", data={"csrf_token": logout_token})
        self.assertEqual(logout_response.status_code, 303)
        self.assertEqual(self.client.get("/").status_code, 303)

        login_page = self.client.get("/login")
        login_response = self.client.post(
            "/login",
            data={
                "email": "taylor@example.com",
                "password": "correct-horse-7",
                "csrf_token": self.csrf_token(login_page.text),
            },
            follow_redirects=True,
        )
        self.assertIn("Ideas for your day", login_response.text)

    def test_rejects_invalid_csrf_token(self):
        response = self.client.post(
            "/register",
            data={
                "name": "Taylor",
                "email": "taylor@example.com",
                "password": "correct-horse-7",
                "csrf_token": "not-the-session-token",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("session expired", response.text)

    @staticmethod
    def csrf_token(html):
        marker = 'name="csrf_token" value="'
        return html.split(marker, 1)[1].split('"', 1)[0]


if __name__ == "__main__":
    unittest.main()