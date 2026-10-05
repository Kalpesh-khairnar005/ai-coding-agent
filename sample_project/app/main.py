"""A tiny HTTP-style API layer (framework-free so the sample runs with zero dependencies)."""
from dataclasses import dataclass
from typing import Any, Optional

from app.models import UserCreate, ValidationError
from app.services import UserService


@dataclass
class Response:
    status: int
    body: Any


class UserAPI:
    """Routes: POST /users, GET /users, GET /users/{id}."""

    def __init__(self, service: Optional[UserService] = None):
        self.service = service or UserService()

    def handle(self, method: str, path: str, body: Optional[dict] = None) -> Response:
        if path == "/users" and method == "POST":
            return self._create_user(body or {})
        if path == "/users" and method == "GET":
            return Response(200, [u.to_dict() for u in self.service.list_users()])
        if path.startswith("/users/") and method == "GET":
            return self._get_user(path.rsplit("/", 1)[-1])
        return Response(404, {"error": "route not found"})

    def _create_user(self, payload: dict) -> Response:
        try:
            data = UserCreate(**payload)
        except TypeError as exc:
            return Response(400, {"error": f"invalid payload: {exc}"})
        except ValidationError as exc:
            return Response(422, {"error": str(exc)})
        return Response(201, self.service.create_user(data).to_dict())

    def _get_user(self, raw_id: str) -> Response:
        if not raw_id.isdigit():
            return Response(400, {"error": "user id must be an integer"})
        user = self.service.get_user(int(raw_id))
        if user is None:
            return Response(404, {"error": "user not found"})
        return Response(200, user.to_dict())

