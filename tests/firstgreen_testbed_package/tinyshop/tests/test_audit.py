from datetime import UTC, datetime

from app.audit import AUDIT_LOG, events_for, record_event


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


def test_record_event_uses_injected_clock() -> None:
    record = record_event("user-1", "login", FixedClock())
    assert record == {
        "user_id": "user-1",
        "event_type": "login",
        "timestamp": "2026-07-14T12:00:00+00:00",
    }
    assert [record] == AUDIT_LOG


def test_events_are_filtered() -> None:
    record_event("user-1", "login", FixedClock())
    record_event("user-2", "login", FixedClock())
    assert len(events_for("user-1")) == 1


def test_empty_audit_fields_are_rejected() -> None:
    try:
        record_event("", "login", FixedClock())
    except ValueError as error:
        assert "require" in str(error)
    else:
        raise AssertionError("invalid audit event accepted")
