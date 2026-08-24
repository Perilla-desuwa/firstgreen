from app.models import Order
from app.orders.routes import list_orders
from app.orders.service import completed_orders, order_total, orders_for_user, paginate_orders


def orders() -> list[Order]:
    return [
        Order("order-1", "pending", "user-1", 1000),
        Order("order-2", "completed", "user-1", 2500),
        Order("order-3", "pending", "user-2", 400),
    ]


def test_normal_pagination() -> None:
    page = paginate_orders(orders(), page=1, page_size=2)
    assert [order.id for order in page.items] == ["order-1", "order-2"]
    assert page.total_pages == 2
    assert page.has_next


def test_page_number_must_be_positive() -> None:
    try:
        paginate_orders(orders(), page=0, page_size=2)
    except ValueError as error:
        assert "page must be" in str(error)
    else:
        raise AssertionError("invalid page accepted")


def test_order_filters_and_total() -> None:
    assert [item.id for item in orders_for_user(orders(), "user-1")] == ["order-1", "order-2"]
    assert [item.id for item in completed_orders(orders())] == ["order-2"]
    assert order_total(orders()) == 3900


def test_order_route_serializes_page() -> None:
    response = list_orders(orders(), page=2, page_size=2)
    assert response["total_items"] == 3
    assert response["items"] == [
        {"id": "order-3", "status": "pending", "user_id": "user-2", "total_cents": 400}
    ]
