"""Authentication domain services."""

from dataclasses import dataclass

from app.models import User, UserStore


@dataclass(frozen=True)
class AuthenticationResult:
    accepted: bool
    user: User | None
    reason: str


def authenticate(store: UserStore, email: str, password: str) -> AuthenticationResult:
    normalized = email.strip().lower()
    if not normalized or not password:
        return AuthenticationResult(False, None, "credentials required")
    user = store.find_by_email(normalized)
    if user is None or not user.password_matches(password):
        return AuthenticationResult(False, None, "invalid credentials")
    return AuthenticationResult(True, user, "accepted")


def public_user(user: User) -> dict[str, str]:
    return {"id": user.id, "email": user.email}
