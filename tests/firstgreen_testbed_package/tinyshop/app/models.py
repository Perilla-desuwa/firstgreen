"""In-memory domain models for the fixture."""

from dataclasses import dataclass, field
from typing import Literal

OrderStatus = Literal["pending", "completed"]


@dataclass
class User:
    id: str
    email: str
    password: str
    legacy_token: str | None = None

    def password_matches(self, candidate: str) -> bool:
        return self.password == candidate

    def replace_password(self, value: str) -> None:
        if len(value) < 8:
            raise ValueError("password must contain at least eight characters")
        self.password = value


@dataclass
class Order:
    id: str
    status: OrderStatus
    user_id: str
    total_cents: int = 0

    def __post_init__(self) -> None:
        if self.total_cents < 0:
            raise ValueError("order total cannot be negative")

    @property
    def is_open(self) -> bool:
        return self.status == "pending"


@dataclass
class UserStore:
    users: dict[str, User] = field(default_factory=dict)

    @classmethod
    def with_defaults(cls) -> "UserStore":
        user = User(
            id="user-1",
            email="buyer@example.test",
            password="correct-horse",
            legacy_token="legacy-user-1",
        )
        return cls({user.id: user})

    def get(self, user_id: str) -> User:
        try:
            return self.users[user_id]
        except KeyError as error:
            raise LookupError(f"unknown user: {user_id}") from error

    def find_by_email(self, email: str) -> User | None:
        normalized = email.strip().lower()
        return next((user for user in self.users.values() if user.email == normalized), None)

    def save(self, user: User) -> None:
        if user.id in self.users and self.users[user.id] is not user:
            raise ValueError(f"duplicate user id: {user.id}")
        self.users[user.id] = user

    def snapshot(self) -> list[dict[str, str | None]]:
        return [
            {
                "id": user.id,
                "email": user.email,
                "password": user.password,
                "legacy_token": user.legacy_token,
            }
            for user in sorted(self.users.values(), key=lambda item: item.id)
        ]
