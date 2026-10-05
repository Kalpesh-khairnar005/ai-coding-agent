import unittest

from app.main import UserAPI

VALID = {"name": "Ada", "email": "ada@example.com", "age": 36}


class UserApiTests(unittest.TestCase):
    def setUp(self):
        self.api = UserAPI()

    def test_create_user_returns_201(self):
        response = self.api.handle("POST", "/users", VALID)
        self.assertEqual(response.status, 201)
        self.assertEqual(response.body["id"], 1)

    def test_list_users_returns_created_users(self):
        self.api.handle("POST", "/users", VALID)
        response = self.api.handle("GET", "/users")
        self.assertEqual(response.status, 200)
        self.assertEqual(len(response.body), 1)

    def test_create_user_rejects_empty_name(self):
        response = self.api.handle("POST", "/users", {**VALID, "name": "  "})
        self.assertEqual(response.status, 422)

    def test_create_user_rejects_invalid_email(self):
        response = self.api.handle("POST", "/users", {**VALID, "email": "nope"})
        self.assertEqual(response.status, 422)

    def test_get_unknown_user_returns_404(self):
        self.assertEqual(self.api.handle("GET", "/users/99").status, 404)
