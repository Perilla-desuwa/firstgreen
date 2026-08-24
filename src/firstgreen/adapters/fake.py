"""Deterministic, cost-free worker used by scheduler and simulator tests."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

from firstgreen.adapters.base import (
    AttemptHandle,
    AttemptInspection,
    CancelResult,
    DoctorResult,
    StartAttemptRequest,
    WorkerEvent,
)


@dataclass(frozen=True)
class FakePlan:
    latency_seconds: float = 0
    exit_code: int = 0
    usage_tokens: int = 100
    events: tuple[dict[str, object], ...] = ()


@dataclass
class FakeWorkerAdapter:
    plans: dict[str, FakePlan] = field(default_factory=dict)
    _cancelled: set[str] = field(default_factory=set)

    async def doctor(self) -> DoctorResult:
        return DoctorResult(True, "fake worker ready", "fake-v1")

    async def start(self, request: StartAttemptRequest) -> AttemptHandle:
        return AttemptHandle("fake", request.attempt_id, None)

    async def events(self, handle: AttemptHandle) -> AsyncIterator[WorkerEvent]:
        plan = self.plans.get(handle.external_id, FakePlan())
        yield WorkerEvent("worker.started", datetime.now(UTC), {})
        for payload in plan.events:
            yield WorkerEvent("worker.activity", datetime.now(UTC), dict(payload))
        await asyncio.sleep(plan.latency_seconds)
        if handle.external_id in self._cancelled:
            yield WorkerEvent("worker.cancelled", datetime.now(UTC), {})
        elif plan.exit_code == 0:
            yield WorkerEvent("worker.usage", datetime.now(UTC), {"tokens": plan.usage_tokens})
            yield WorkerEvent("worker.completed", datetime.now(UTC), {})
        else:
            yield WorkerEvent("worker.failed", datetime.now(UTC), {"exit_code": plan.exit_code})

    async def cancel(self, handle: AttemptHandle, reason: str) -> CancelResult:
        self._cancelled.add(handle.external_id)
        return CancelResult(True, reason)

    async def inspect(self, handle: AttemptHandle) -> AttemptInspection:
        status = "cancelled" if handle.external_id in self._cancelled else "running"
        return AttemptInspection(status)
