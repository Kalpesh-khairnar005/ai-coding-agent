"""Business logic: an in-memory user store."""
from typing import Optional

from app.models import User, UserCreate


class UserService:
    def __init__(self):
        self._users: dict[int, User] = {}
        self._next_id = 1

    def create_user(self, data: UserCreate) -> User:
        user = User(id=self._next_id, name=data.name.strip(), email=data.email, age=data.age)
        self._users[user.id] = user
        self._next_id += 1
        return user

    def get_user(self, user_id: int) -> Optional[User]:
        return self._users.get(user_id)

    def list_users(self) -> list[User]:
        return list(self._users.values())
