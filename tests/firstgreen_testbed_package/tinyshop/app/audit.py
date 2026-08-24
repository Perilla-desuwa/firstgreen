"""Deterministic in-memory audit logging."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

AUDIT_LOG: list[dict[str, str]] = []


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True)
class AuditRecord:
    user_id: str
    event_type: str
    timestamp: datetime

    def as_record(self) -> dict[str, str]:
        return {
            "user_id": self.user_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp.astimezone(UTC).isoformat(),
        }


def record_event(user_id: str, event_type: str, clock: Clock | None = None) -> dict[str, str]:
    if not user_id or not event_type:
        raise ValueError("audit events require user_id and event_type")
    entry = AuditRecord(user_id, event_type, (clock or SystemClock()).now()).as_record()
    AUDIT_LOG.append(entry)
    return dict(entry)


def events_for(user_id: str) -> list[dict[str, str]]:
    return [dict(entry) for entry in AUDIT_LOG if entry["user_id"] == user_id]


def clear_audit_log() -> None:
    AUDIT_LOG.clear()
