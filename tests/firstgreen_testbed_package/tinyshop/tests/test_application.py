from app.main import TinyShopApplication
from app.models import Order


def test_application_dispatches_login() -> None:
    response = TinyShopApplication().dispatch(
        "/login",
        {"email": "buyer@example.test", "password": "correct-horse"},
    )
    assert response == {
        "ok": True,
        "user": {"id": "user-1", "email": "buyer@example.test"},
    }


def test_application_dispatches_orders() -> None:
    response = TinyShopApplication().dispatch(
        "/orders",
        {"orders": [Order("order-1", "pending", "user-1", 500)], "page_size": 10},
    )
    assert isinstance(response, dict)
    assert response["total_items"] == 1
    assert response["items"] == [
        {"id": "order-1", "status": "pending", "user_id": "user-1", "total_cents": 500}
    ]
