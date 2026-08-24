"""Order route-like functions."""

from app.models import Order
from app.orders.service import paginate_orders


def list_orders(orders: list[Order], page: int = 1, page_size: int = 10) -> dict[str, object]:
    result = paginate_orders(orders, page, page_size)
    return {
        "items": [
            {
                "id": order.id,
                "status": order.status,
                "user_id": order.user_id,
                "total_cents": order.total_cents,
            }
            for order in result.items
        ],
        "page": result.page,
        "page_size": result.page_size,
        "total_items": result.total_items,
        "total_pages": result.total_pages,
    }
