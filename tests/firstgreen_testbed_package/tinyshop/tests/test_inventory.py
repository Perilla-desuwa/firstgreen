from app.inventory import Inventory, StockItem


def inventory() -> Inventory:
    result = Inventory()
    result.add(StockItem("mug", 5))
    result.add(StockItem("shirt", 2))
    return result


def test_reserve_moves_available_stock() -> None:
    item = inventory().reserve("mug", 2)
    assert item.available == 3
    assert item.reserved == 2
    assert item.on_hand == 5


def test_release_restores_available_stock() -> None:
    item = inventory().reserve("mug", 3)
    item.release(1)
    assert item.available == 3
    assert item.reserved == 2


def test_insufficient_stock_is_rejected() -> None:
    try:
        inventory().reserve("shirt", 3)
    except ValueError as error:
        assert "insufficient" in str(error)
    else:
        raise AssertionError("over-reservation accepted")


def test_invalid_quantities_are_rejected() -> None:
    item = StockItem("mug", 1)
    for quantity in (0, -1):
        try:
            item.reserve(quantity)
        except ValueError as error:
            assert "positive" in str(error)
        else:
            raise AssertionError("invalid reservation accepted")


def test_low_stock_is_sorted() -> None:
    assert [item.sku for item in inventory().low_stock(2)] == ["shirt"]


def test_duplicate_and_unknown_skus_are_rejected() -> None:
    items = inventory()
    try:
        items.add(StockItem("mug", 1))
    except ValueError as error:
        assert "duplicate" in str(error)
    else:
        raise AssertionError("duplicate sku accepted")
    try:
        items.get("missing")
    except LookupError as error:
        assert "unknown sku" in str(error)
    else:
        raise AssertionError("unknown sku accepted")
