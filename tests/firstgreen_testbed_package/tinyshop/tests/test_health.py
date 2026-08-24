from app.main import TinyShopApplication, health


def test_health_is_minimal_and_deterministic() -> None:
    assert health() == {"status": "ok"}


def test_application_dispatches_health() -> None:
    assert TinyShopApplication().dispatch("/health") == {"status": "ok"}


def test_unknown_route_is_rejected() -> None:
    try:
        TinyShopApplication().dispatch("/missing")
    except LookupError as error:
        assert "unknown route" in str(error)
    else:
        raise AssertionError("unknown route was accepted")
