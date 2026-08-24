"""Scheduler-level deterministic delayed-hedge scenarios for the testbed."""

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from firstgreen.adapters.base import (
    AttemptHandle,
    AttemptInspection,
    CancelResult,
    DoctorResult,
    StartAttemptRequest,
    WorkerAdapter,
    WorkerEvent,
)
from firstgreen.config import Manifest
from firstgreen.service import SchedulerService, WorkerAdapterFactory
from firstgreen.workspace.git_worktree import Workspace


@dataclass(frozen=True)
class HedgeAttemptProfile:
    duration_seconds: float
    verification_passes: bool


@dataclass(frozen=True)
class HedgeAttemptRecord:
    attempt_id: str
    role: str
    status: str
    workspace: Workspace


@dataclass(frozen=True)
class HedgeExecutionOutcome:
    run_id: str
    winner_attempt_id: str | None
    winner_role: str | None
    winner_count: int
    attempts: tuple[HedgeAttemptRecord, ...]
    factory: "HedgeWorkerFactory"
    state_dir: Path


class HedgeWorkerFactory(WorkerAdapterFactory):
    def __init__(self, profiles: dict[str, HedgeAttemptProfile]) -> None:
        self.profiles = profiles
        self.adapters: dict[str, HedgeWorkerAdapter] = {}
        self.started_at = time.monotonic()
        self.timeline: list[dict[str, object]] = []

    def create(self, manifest: Manifest, attempt_id: str, role: str) -> WorkerAdapter:
        del manifest
        try:
            profile = self.profiles[role]
        except KeyError as error:
            raise ValueError(f"missing deterministic hedge profile for role: {role}") from error
        adapter = HedgeWorkerAdapter(self, attempt_id, role, profile)
        self.adapters[attempt_id] = adapter
        return adapter

    def record(self, event: str, request: StartAttemptRequest, role: str) -> None:
        self.timeline.append(
            {
                "time": time.monotonic() - self.started_at,
                "event": event,
                "task": request.task_id,
                "attempt_id": request.attempt_id,
                "role": role,
            }
        )


class HedgeWorkerAdapter:
    def __init__(
        self,
        factory: HedgeWorkerFactory,
        attempt_id: str,
        role: str,
        profile: HedgeAttemptProfile,
    ) -> None:
        self.factory = factory
        self.attempt_id = attempt_id
        self.role = role
        self.profile = profile
        self.request: StartAttemptRequest | None = None
        self.cancel_calls = 0
        self.status = "created"

    async def doctor(self) -> DoctorResult:
        return DoctorResult(True, "deterministic hedge worker ready", "hedge-fake-v1")

    async def start(self, request: StartAttemptRequest) -> AttemptHandle:
        if request.attempt_id != self.attempt_id:
            raise RuntimeError("hedge worker attempt identity mismatch")
        self.request = request
        self.status = "running"
        self.factory.record("started", request, self.role)
        return AttemptHandle("hedge-fake", request.attempt_id, None)

    async def events(self, handle: AttemptHandle) -> AsyncIterator[WorkerEvent]:
        del handle
        if self.request is None:
            raise RuntimeError("hedge worker was not started")
        await asyncio.sleep(self.profile.duration_seconds)
        value = "valid" if self.profile.verification_passes else "invalid"
        (self.request.worktree / "result.txt").write_text(value, encoding="utf-8")
        self.status = "completed"
        self.factory.record("completed", self.request, self.role)
        yield WorkerEvent(
            "worker.completed",
            datetime.now(UTC),
            {"status": "completed", "worker": "hedge-fake"},
        )

    async def cancel(self, handle: AttemptHandle, reason: str) -> CancelResult:
        del handle, reason
        self.cancel_calls += 1
        already_cancelled = self.status == "cancelled"
        self.status = "cancelled"
        return CancelResult(True, "already cancelled" if already_cancelled else "cancelled")

    async def inspect(self, handle: AttemptHandle) -> AttemptInspection:
        del handle
        return AttemptInspection(self.status, 0 if self.status == "completed" else None)


def hedge_manifest(repo: Path, *, delay_seconds: float, replay_safe: bool) -> Manifest:
    python = __import__("sys").executable
    return Manifest.model_validate(
        {
            "version": 1,
            "project": {"repo": str(repo), "base_ref": "HEAD"},
            "scheduler": {
                "concurrency": {
                    "mode": "static",
                    "min_root": 1,
                    "max_root": 2,
                    "initial_root": 1,
                    "total_agent_thread_budget": 2,
                    "verifier_slots": 2,
                },
                "hedge": {
                    "enabled": True,
                    "fallback_after_seconds": delay_seconds,
                    "max_replicas": 1,
                    "cancel_loser": True,
                },
                "budgets": {
                    "max_run_estimated_usd": None,
                    "max_hedge_estimated_usd": None,
                },
            },
            "agent_defaults": {"adapter": "fake"},
            "verification_defaults": {"command_timeout_seconds": 30},
            "workspace": {"keep_winner": True},
            "tasks": [
                {
                    "id": "hedged-result",
                    "prompt": "Produce a deterministic verified result.",
                    "replay_safe": replay_safe,
                    "verify": {
                        "commands": [
                            {
                                "argv": [
                                    python,
                                    "-c",
                                    "from pathlib import Path; "
                                    "raise SystemExit(0 if "
                                    "Path('result.txt').read_text(encoding='utf-8') "
                                    "== 'valid' else 1)",
                                ]
                            }
                        ],
                        "allowed_changed_paths": ["result.txt"],
                    },
                }
            ],
        }
    )


async def execute_hedge_scenario(
    repo: Path,
    state_dir: Path,
    profiles: dict[str, HedgeAttemptProfile],
    *,
    policy: str = "delayed-hedge",
    delay_seconds: float = 0.05,
    replay_safe: bool = True,
) -> HedgeExecutionOutcome:
    manifest = hedge_manifest(repo, delay_seconds=delay_seconds, replay_safe=replay_safe)
    state_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = state_dir / "hedge-manifest.yaml"
    manifest_path.write_text(
        yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    factory = HedgeWorkerFactory(profiles)
    service = SchedulerService(state_dir, worker_factory=factory)
    result = await service.run(manifest, manifest_path, policy)
    with service.repository.connect() as connection:
        rows = connection.execute(
            "SELECT attempt.id,attempt.role,attempt.status,attempt.workspace_path,attempt.branch,"
            "attempt.base_sha,task.task_key,task.winner_attempt_id "
            "FROM attempts attempt JOIN tasks task ON task.id=attempt.task_id "
            "WHERE task.run_id=? ORDER BY attempt.ordinal",
            (result.run_id,),
        ).fetchall()
        winner_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM task_winners winner "
                "JOIN tasks task ON task.id=winner.task_id WHERE task.run_id=?",
                (result.run_id,),
            ).fetchone()[0]
        )
    records = tuple(
        HedgeAttemptRecord(
            attempt_id=str(row["id"]),
            role=str(row["role"]),
            status=str(row["status"]),
            workspace=Workspace(
                str(row["id"]),
                Path(str(row["workspace_path"])),
                str(row["branch"]),
                repo.resolve(),
                str(row["base_sha"]),
                result.run_id,
                str(row["task_key"]),
                str(row["id"]),
            ),
        )
        for row in rows
    )
    winner = next((record for record in records if record.status == "winner"), None)
    return HedgeExecutionOutcome(
        result.run_id,
        winner.attempt_id if winner else None,
        winner.role if winner else None,
        winner_count,
        records,
        factory,
        state_dir,
    )
