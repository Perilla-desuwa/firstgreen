"""Injectable UTC clocks."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass
class FakeClock:
    current: datetime

    def now(self) -> datetime:
        if self.current.tzinfo is None:
            raise ValueError("FakeClock requires a timezone-aware datetime")
        return self.current.astimezone(UTC)

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)
