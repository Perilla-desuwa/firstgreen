"""Order querying and pagination services."""

from dataclasses import dataclass

from app.models import Order


@dataclass(frozen=True)
class Page[T]:
    items: list[T]
    page: int
    page_size: int
    total_items: int
    total_pages: int

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @property
    def has_previous(self) -> bool:
        return self.page > 1


def paginate_orders[T](items: list[T], page: int, page_size: int) -> Page[T]:
    """Return one page; page_size validation is intentionally missing for scenario S1."""
    if page < 1:
        raise ValueError("page must be at least 1")
    total_pages = (len(items) + page_size - 1) // page_size
    start = (page - 1) * page_size
    return Page(items[start : start + page_size], page, page_size, len(items), total_pages)


def orders_for_user(orders: list[Order], user_id: str) -> list[Order]:
    return [order for order in orders if order.user_id == user_id]


def completed_orders(orders: list[Order]) -> list[Order]:
    return [order for order in orders if order.status == "completed"]


def order_total(orders: list[Order]) -> int:
    return sum(order.total_cents for order in orders)
