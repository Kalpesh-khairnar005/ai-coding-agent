"""Data models and input validation for the users API."""
from dataclasses import asdict, dataclass


class ValidationError(ValueError):
    """Raised when client input is invalid."""


@dataclass
class UserCreate:
    """Payload accepted when creating a user."""

    name: str
    email: str
    age: int

    def __post_init__(self):
        if not self.name.strip():
            raise ValidationError("name must not be empty")
        if "@" not in self.email:
            raise ValidationError("email must contain '@'")


@dataclass
class User:
    """A stored user."""

    id: int
    name: str
    email: str
    age: int

    def to_dict(self) -> dict:
        return asdict(self)
