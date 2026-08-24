from app.auth.routes import login, session_status
from app.auth.service import authenticate
from app.models import UserStore


def test_valid_login_returns_public_user() -> None:
    store = UserStore.with_defaults()
    response = login(store, "buyer@example.test", "correct-horse")
    assert response == {
        "ok": True,
        "user": {"id": "user-1", "email": "buyer@example.test"},
    }


def test_invalid_login_is_rejected() -> None:
    result = authenticate(UserStore.with_defaults(), "buyer@example.test", "wrong")
    assert not result.accepted
    assert result.user is None


def test_session_status() -> None:
    assert session_status(None) == {"authenticated": False}
    assert session_status("user-1") == {"authenticated": True, "user_id": "user-1"}
