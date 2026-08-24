"""Domain records; persistence models are deliberately separate."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class RunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class TaskStatus(StrEnum):
    QUEUED = "queued"
    READY = "ready"
    RUNNING = "running"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class AttemptStatus(StrEnum):
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    AGENT_COMPLETED = "agent_completed"
    VERIFYING = "verifying"
    PASSED = "passed"
    WINNER = "winner"
    SUPERSEDED = "superseded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ORPHANED = "orphaned"


class VerificationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class Run:
    id: str
    manifest_hash: str
    repo_path: str
    base_sha: str
    policy_snapshot: dict[str, Any]
    status: RunStatus
    created_at: datetime


@dataclass(frozen=True)
class Task:
    id: str
    run_id: str
    task_key: str
    prompt: str
    replay_safe: bool
    status: TaskStatus
    winner_attempt_id: str | None = None


@dataclass(frozen=True)
class Attempt:
    id: str
    task_id: str
    ordinal: int
    role: str
    status: AttemptStatus
    base_sha: str
    config_snapshot: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Verification:
    id: str
    attempt_id: str
    command_index: int
    status: VerificationStatus


@dataclass(frozen=True)
class Event:
    id: str
    type: str
    timestamp: datetime
    payload: dict[str, Any]


@dataclass(frozen=True)
class Decision:
    id: str
    run_id: str
    decision_type: str
    signals: dict[str, Any]
    policy_version: str
    timestamp: datetime


@dataclass(frozen=True)
class Lease:
    id: str
    resource_key: str
    owner_id: str
    acquired_at: datetime
    expires_at: datetime | None
