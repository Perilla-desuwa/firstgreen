import asyncio
import json
import subprocess
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
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
from firstgreen.config import Manifest, load_manifest
from firstgreen.service import SchedulerService, WorkerAdapterFactory


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "firstgreen@example.invalid")
    git(repo, "config", "user.name", "FirstGreen Test")
    (repo / "result.txt").write_text("base\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    return repo


class RepairFactory(WorkerAdapterFactory):
    def __init__(self) -> None:
        self.roles: list[str] = []
        self.repair_prompts: list[str] = []
        self.repair_inherited: list[str] = []

    def create(self, manifest: Manifest, attempt_id: str, role: str) -> WorkerAdapter:
        del manifest
        self.roles.append(role)
        return RepairAdapter(self, attempt_id, role)


class RepairAdapter:
    def __init__(self, factory: RepairFactory, attempt_id: str, role: str) -> None:
        self.factory = factory
        self.attempt_id = attempt_id
        self.role = role
        self.request: StartAttemptRequest | None = None

    async def doctor(self) -> DoctorResult:
        return DoctorResult(True, "ready")

    async def start(self, request: StartAttemptRequest) -> AttemptHandle:
        self.request = request
        if self.role == "repair":
            self.factory.repair_prompts.append(request.prompt)
            self.factory.repair_inherited.append(
                (request.worktree / "result.txt").read_text(encoding="utf-8")
            )
        return AttemptHandle("repair-fake", self.attempt_id, None)

    async def events(self, handle: AttemptHandle) -> AsyncIterator[WorkerEvent]:
        del handle
        assert self.request is not None
        content = "good\n" if self.role == "repair" else "bad\n"
        (self.request.worktree / "result.txt").write_text(content, encoding="utf-8")
        yield WorkerEvent("worker.completed", datetime.now(UTC), {"status": "completed"})

    async def cancel(self, handle: AttemptHandle, reason: str) -> CancelResult:
        del handle, reason
        return CancelResult(True, "cancelled")

    async def inspect(self, handle: AttemptHandle) -> AttemptInspection:
        del handle
        return AttemptInspection("completed", 0)


def manifest_path(tmp_path: Path, repo: Path, *, max_attempts: int) -> Path:
    verifier = (
        "import os; from pathlib import Path; "
        "print('expected good; token=' + os.environ['FIRSTGREEN_REPAIR_SECRET']); "
        "raise SystemExit(0 if Path('result.txt').read_text(encoding='utf-8') == 'good\\n' else 3)"
    )
    path = tmp_path / "fleet.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "project": {"repo": str(repo), "base_ref": "main"},
                "scheduler": {"concurrency": {}},
                "agent_defaults": {"adapter": "fake"},
                "verification_defaults": {},
                "workspace": {},
                "tasks": [
                    {
                        "id": "repairable",
                        "prompt": "make result.txt contain good",
                        "limits": {"max_attempts": max_attempts},
                        "verify": {
                            "commands": [{"argv": [sys.executable, "-c", verifier]}],
                            "allowed_changed_paths": ["result.txt"],
                        },
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def test_failed_verification_launches_bounded_repair_with_filtered_feedback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "sk-repair-secret-123456"
    monkeypatch.setenv("FIRSTGREEN_REPAIR_SECRET", secret)
    repo = repository(tmp_path)
    manifest = manifest_path(tmp_path, repo, max_attempts=2)
    factory = RepairFactory()
    service = SchedulerService(tmp_path / "state", worker_factory=factory)

    outcome = asyncio.run(service.run(load_manifest(manifest), manifest, "single"))

    assert (outcome.verified, outcome.failed) == (1, 0)
    assert factory.roles == ["primary", "repair"]
    assert factory.repair_inherited == ["bad\n"]
    assert len(factory.repair_prompts) == 1
    assert "expected good" in factory.repair_prompts[0]
    assert "[REDACTED]" in factory.repair_prompts[0]
    assert secret not in factory.repair_prompts[0]
    assert (repo / "result.txt").read_text(encoding="utf-8") == "base\n"
    with service.repository.connect() as connection:
        attempts = connection.execute(
            "SELECT ordinal,role,status,workspace_path FROM attempts ORDER BY ordinal"
        ).fetchall()
        decisions = connection.execute(
            "SELECT decision_type,signals,policy_snapshot FROM scheduler_decisions "
            "ORDER BY timestamp"
        ).fetchall()
        persisted_payloads = [
            str(row[0]) for row in connection.execute("SELECT payload FROM events").fetchall()
        ]
    assert [(row["ordinal"], row["role"], row["status"]) for row in attempts] == [
        (1, "primary", "failed"),
        (2, "repair", "winner"),
    ]
    assert Path(str(attempts[0]["workspace_path"])).is_dir()
    assert Path(str(attempts[1]["workspace_path"])).is_dir()
    assert [row["decision_type"] for row in decisions] == [
        "ready_queue_select",
        "attempt_policy",
        "launch_repair",
    ]
    assert json.loads(decisions[2]["signals"])["source_attempt_id"]
    assert json.loads(decisions[2]["policy_snapshot"])["filtered_feedback_only"] is True
    assert all(secret not in payload for payload in persisted_payloads)


def test_max_attempts_one_prevents_repair(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    manifest = manifest_path(tmp_path, repo, max_attempts=1)
    factory = RepairFactory()
    service = SchedulerService(tmp_path / "state", worker_factory=factory)

    outcome = asyncio.run(service.run(load_manifest(manifest), manifest, "single"))

    assert (outcome.verified, outcome.failed) == (0, 1)
    assert factory.roles == ["primary"]
    with service.repository.connect() as connection:
        attempts = connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
        decision_types = [
            str(row[0])
            for row in connection.execute(
                "SELECT decision_type FROM scheduler_decisions ORDER BY timestamp"
            ).fetchall()
        ]
    assert attempts == 1
    assert decision_types == ["ready_queue_select", "attempt_policy", "repair_limit_reached"]
