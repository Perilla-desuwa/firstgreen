from decimal import Decimal

from app.catalog import Catalog, Product


def test_default_catalog_is_deterministic() -> None:
    catalog = Catalog.with_defaults()
    assert [product.sku for product in catalog.search("")] == ["mug", "shirt"]
    assert catalog.get("mug").price == Decimal("12.50")


def test_search_matches_name_sku_and_tag() -> None:
    catalog = Catalog.with_defaults()
    assert [item.sku for item in catalog.search("green")] == ["mug"]
    assert [item.sku for item in catalog.search("shirt")] == ["shirt"]
    assert [item.sku for item in catalog.search("kitchen")] == ["mug"]


def test_total_price_preserves_decimal_accuracy() -> None:
    assert Catalog.with_defaults().total_price(["mug", "shirt"]) == Decimal("37.50")


def test_product_validation() -> None:
    invalid = [
        ("", "Name", Decimal("1")),
        ("sku", "", Decimal("1")),
        ("sku", "Name", Decimal("-1")),
    ]
    for sku, name, price in invalid:
        try:
            Product(sku, name, price)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid product accepted")


def test_duplicate_product_is_rejected() -> None:
    catalog = Catalog.with_defaults()
    try:
        catalog.add(Product("mug", "Another", Decimal("1")))
    except ValueError as error:
        assert "duplicate" in str(error)
    else:
        raise AssertionError("duplicate product accepted")


def test_unknown_product_is_rejected() -> None:
    try:
        Catalog.with_defaults().get("missing")
    except LookupError as error:
        assert "unknown product" in str(error)
    else:
        raise AssertionError("unknown product accepted")


def test_add_product_is_searchable() -> None:
    catalog = Catalog()
    catalog.add(Product("book", "Green Book", Decimal("5.00"), frozenset({"reading"})))
    assert catalog.search("reading") == [catalog.get("book")]
