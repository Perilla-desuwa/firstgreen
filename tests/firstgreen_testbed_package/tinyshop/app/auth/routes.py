"""Authentication route-like functions."""

from app.auth.service import authenticate, public_user
from app.models import UserStore


def login(store: UserStore, email: str, password: str) -> dict[str, object]:
    result = authenticate(store, email, password)
    if not result.accepted or result.user is None:
        return {"ok": False, "error": result.reason}
    return {"ok": True, "user": public_user(result.user)}


def session_status(user_id: str | None) -> dict[str, object]:
    if user_id is None:
        return {"authenticated": False}
    return {"authenticated": True, "user_id": user_id}
