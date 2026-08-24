"""Normalized worker contract."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class StartAttemptRequest:
    run_id: str
    task_id: str
    attempt_id: str
    prompt: str
    worktree: Path
    timeout_seconds: int
    adapter_config: dict[str, Any]


@dataclass(frozen=True)
class AttemptHandle:
    adapter: str
    external_id: str
    pid: int | None


@dataclass(frozen=True)
class WorkerEvent:
    type: str
    timestamp: datetime
    payload: dict[str, Any]
    raw: str | None = None


@dataclass(frozen=True)
class DoctorResult:
    ok: bool
    message: str
    version: str | None = None


@dataclass(frozen=True)
class CancelResult:
    cancelled: bool
    message: str


@dataclass(frozen=True)
class AttemptInspection:
    status: str
    exit_code: int | None = None


class WorkerAdapter(Protocol):
    async def doctor(self) -> DoctorResult: ...
    async def start(self, request: StartAttemptRequest) -> AttemptHandle: ...
    def events(self, handle: AttemptHandle) -> AsyncIterator[WorkerEvent]: ...
    async def cancel(self, handle: AttemptHandle, reason: str) -> CancelResult: ...
    async def inspect(self, handle: AttemptHandle) -> AttemptInspection: ...
