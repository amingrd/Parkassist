import tempfile
import unittest
from pathlib import Path

from parking_app.repository import Repository


class RepositorySSOTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Repository(Path(self.temp_dir.name) / "test.db", seed_demo_data=False)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_find_or_create_sso_user_creates_new_user(self) -> None:
        user = self.repo.find_or_create_sso_user(
            name="Sam Example",
            email="sam@example.com",
            auth_provider="okta",
            external_subject="okta|123",
        )
        self.assertEqual(user["auth_provider"], "okta")
        self.assertEqual(user["external_subject"], "okta|123")
        self.assertEqual(user["password_hash"], None)

    def test_find_or_create_sso_user_reuses_email_match(self) -> None:
        self.repo.create_user("Jamie", "jamie@example.com", "password123")
        user = self.repo.find_or_create_sso_user(
            name="Jamie Updated",
            email="jamie@example.com",
            auth_provider="okta",
            external_subject="okta|456",
        )
        self.assertEqual(user["name"], "Jamie Updated")
        self.assertEqual(user["auth_provider"], "okta")
        self.assertEqual(user["external_subject"], "okta|456")


if __name__ == "__main__":
    unittest.main()
