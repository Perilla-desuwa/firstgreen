from app.models import Order, User, UserStore


def test_default_user_store_contains_legacy_data() -> None:
    store = UserStore.with_defaults()
    assert store.get("user-1").legacy_token == "legacy-user-1"
    assert store.find_by_email("BUYER@example.test") is store.get("user-1")


def test_password_replacement_validates_length() -> None:
    user = User("u", "u@example.test", "old-password")
    try:
        user.replace_password("short")
    except ValueError as error:
        assert "eight" in str(error)
    else:
        raise AssertionError("short password accepted")
    user.replace_password("new-password")
    assert user.password_matches("new-password")


def test_negative_order_total_is_rejected() -> None:
    try:
        Order("order", "pending", "user", -1)
    except ValueError as error:
        assert "negative" in str(error)
    else:
        raise AssertionError("negative total accepted")
