"""Deterministic product catalog queries."""

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    price: Decimal
    tags: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.sku.strip() or not self.name.strip():
            raise ValueError("products require sku and name")
        if self.price < 0:
            raise ValueError("product price cannot be negative")

    def matches(self, query: str) -> bool:
        needle = query.strip().lower()
        if not needle:
            return True
        return needle in self.name.lower() or needle in self.sku.lower() or needle in self.tags


@dataclass
class Catalog:
    products: dict[str, Product] = field(default_factory=dict)

    @classmethod
    def with_defaults(cls) -> "Catalog":
        return cls(
            {
                "mug": Product("mug", "Green Mug", Decimal("12.50"), frozenset({"kitchen"})),
                "shirt": Product(
                    "shirt", "TinyShop Shirt", Decimal("25.00"), frozenset({"clothing"})
                ),
            }
        )

    def add(self, product: Product) -> None:
        if product.sku in self.products:
            raise ValueError(f"duplicate product: {product.sku}")
        self.products[product.sku] = product

    def get(self, sku: str) -> Product:
        try:
            return self.products[sku]
        except KeyError as error:
            raise LookupError(f"unknown product: {sku}") from error

    def search(self, query: str) -> list[Product]:
        return sorted(
            (product for product in self.products.values() if product.matches(query)),
            key=lambda product: product.sku,
        )

    def total_price(self, skus: list[str]) -> Decimal:
        return sum((self.get(sku).price for sku in skus), start=Decimal())
