"""Small in-memory inventory model used by the synthetic shop."""

from dataclasses import dataclass, field


@dataclass
class StockItem:
    sku: str
    available: int
    reserved: int = 0

    def __post_init__(self) -> None:
        if not self.sku.strip():
            raise ValueError("sku cannot be empty")
        if self.available < 0 or self.reserved < 0:
            raise ValueError("stock quantities cannot be negative")

    @property
    def on_hand(self) -> int:
        return self.available + self.reserved

    def reserve(self, quantity: int) -> None:
        if quantity < 1:
            raise ValueError("reservation quantity must be positive")
        if quantity > self.available:
            raise ValueError("insufficient stock")
        self.available -= quantity
        self.reserved += quantity

    def release(self, quantity: int) -> None:
        if quantity < 1:
            raise ValueError("release quantity must be positive")
        if quantity > self.reserved:
            raise ValueError("cannot release more than reserved")
        self.reserved -= quantity
        self.available += quantity


@dataclass
class Inventory:
    items: dict[str, StockItem] = field(default_factory=dict)

    def add(self, item: StockItem) -> None:
        if item.sku in self.items:
            raise ValueError(f"duplicate sku: {item.sku}")
        self.items[item.sku] = item

    def get(self, sku: str) -> StockItem:
        try:
            return self.items[sku]
        except KeyError as error:
            raise LookupError(f"unknown sku: {sku}") from error

    def reserve(self, sku: str, quantity: int) -> StockItem:
        item = self.get(sku)
        item.reserve(quantity)
        return item

    def low_stock(self, threshold: int) -> list[StockItem]:
        if threshold < 0:
            raise ValueError("threshold cannot be negative")
        return sorted(
            (item for item in self.items.values() if item.available <= threshold),
            key=lambda item: item.sku,
        )
