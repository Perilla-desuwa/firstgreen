"""TinyShop application entry points."""

from dataclasses import dataclass, field
from typing import Any

from app.auth.routes import login
from app.models import UserStore
from app.orders.routes import list_orders


def health() -> dict[str, str]:
    """Return deterministic process health information."""
    return {"status": "ok"}


@dataclass
class TinyShopApplication:
    """Small dependency container used by tests without a web framework."""

    users: UserStore = field(default_factory=UserStore.with_defaults)

    def dispatch(self, path: str, payload: dict[str, Any] | None = None) -> object:
        body = payload or {}
        if path == "/health":
            return health()
        if path == "/login":
            return login(self.users, str(body.get("email", "")), str(body.get("password", "")))
        if path == "/orders":
            return list_orders(
                list(body.get("orders", [])),
                int(body.get("page", 1)),
                int(body.get("page_size", 10)),
            )
        raise LookupError(f"unknown route: {path}")
