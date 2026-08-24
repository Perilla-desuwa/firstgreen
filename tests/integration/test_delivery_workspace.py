import asyncio
import subprocess
import sys
from collections.abc import AsyncIterator
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
from firstgreen.config import Manifest, load_manifest
from firstgreen.reporting.export import report_html, run_data
from firstgreen.service import SchedulerService, WorkerAdapterFactory


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


class EditingFactory(WorkerAdapterFactory):
    def __init__(self, edits: dict[str, tuple[str, str]]) -> None:
        self.edits = edits

    def create(self, manifest: Manifest, attempt_id: str, role: str) -> WorkerAdapter:
        del manifest, role
        return EditingAdapter(attempt_id, self.edits)


class EditingAdapter:
    def __init__(self, attempt_id: str, edits: dict[str, tuple[str, str]]) -> None:
        self.attempt_id = attempt_id
        self.edits = edits
        self.request: StartAttemptRequest | None = None

    async def doctor(self) -> DoctorResult:
        return DoctorResult(True, "ready")

    async def start(self, request: StartAttemptRequest) -> AttemptHandle:
        self.request = request
        return AttemptHandle("editing-fake", self.attempt_id, None)

    async def events(self, handle: AttemptHandle) -> AsyncIterator[WorkerEvent]:
        del handle
        assert self.request is not None
        relative, content = self.edits[self.request.task_id]
        (self.request.worktree / relative).write_text(content, encoding="utf-8")
        yield WorkerEvent("worker.completed", datetime.now(UTC), {"status": "completed"})

    async def cancel(self, handle: AttemptHandle, reason: str) -> CancelResult:
        del handle, reason
        return CancelResult(True, "cancelled")

    async def inspect(self, handle: AttemptHandle) -> AttemptInspection:
        del handle
        return AttemptInspection("completed", 0)


def repository(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    for relative, content in files.items():
        (repo / relative).write_text(content, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    return repo


def manifest_file(
    tmp_path: Path,
    repo: Path,
    edits: dict[str, tuple[str, str]],
) -> Path:
    tasks: list[dict[str, object]] = []
    for task_id, (relative, content) in edits.items():
        verifier = (
            "from pathlib import Path; "
            f"assert Path({relative!r}).read_text(encoding='utf-8') == {content!r}"
        )
        tasks.append(
            {
                "id": task_id,
                "prompt": f"edit {relative}",
                "verify": {
                    "commands": [{"argv": [sys.executable, "-c", verifier]}],
                    "allowed_changed_paths": [relative],
                },
            }
        )
    path = tmp_path / "fleet.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "project": {"repo": str(repo), "base_ref": "main"},
                "scheduler": {
                    "concurrency": {
                        "mode": "static",
                        "min_root": 1,
                        "max_root": 2,
                        "initial_root": 2,
                        "total_agent_thread_budget": 2,
                        "verifier_slots": 2,
                    }
                },
                "agent_defaults": {"adapter": "fake"},
                "verification_defaults": {},
                "workspace": {},
                "tasks": tasks,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def test_independent_sinks_produce_one_verified_delivery_workspace(tmp_path: Path) -> None:
    repo = repository(tmp_path, {"a.txt": "base-a\n", "b.txt": "base-b\n"})
    edits = {"task-a": ("a.txt", "A\n"), "task-b": ("b.txt", "B\n")}
    manifest_path = manifest_file(tmp_path, repo, edits)
    state = tmp_path / "state"
    service = SchedulerService(state, worker_factory=EditingFactory(edits))

    outcome = asyncio.run(service.run(load_manifest(manifest_path), manifest_path, "single"))

    assert outcome.failed == 0
    assert outcome.verified == 2
    assert outcome.delivery_workspace is not None
    assert (outcome.delivery_workspace / "a.txt").read_text(encoding="utf-8") == "A\n"
    assert (outcome.delivery_workspace / "b.txt").read_text(encoding="utf-8") == "B\n"
    assert (repo / "a.txt").read_text(encoding="utf-8") == "base-a\n"
    data = run_data(service.repository, outcome.run_id)
    assert data["run"]["status"] == "completed"
    assert data["delivery"]["status"] == "verified"
    assert len(data["delivery"]["verifications"]) == 2
    assert all(item["status"] == "passed" for item in data["delivery"]["verifications"])
    report = report_html(service.repository, outcome.run_id, tmp_path / "report.html")
    html = report.read_text(encoding="utf-8")
    assert "Final delivery" in html
    assert str(outcome.delivery_workspace) in html


def test_conflicting_verified_sinks_fail_delivery_without_deleting_workspace(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path, {"shared.txt": "base\n"})
    edits = {"task-a": ("shared.txt", "A\n"), "task-b": ("shared.txt", "B\n")}
    manifest_path = manifest_file(tmp_path, repo, edits)
    state = tmp_path / "state"
    service = SchedulerService(state, worker_factory=EditingFactory(edits))

    outcome = asyncio.run(service.run(load_manifest(manifest_path), manifest_path, "single"))

    assert outcome.verified == 2
    assert outcome.failed == 1
    assert outcome.delivery_workspace is not None and outcome.delivery_workspace.is_dir()
    data = run_data(service.repository, outcome.run_id)
    assert data["run"]["status"] == "failed"
    assert data["delivery"]["status"] == "failed"
    assert data["delivery"]["error_kind"] == "WorkspaceSafetyError"
    assert data["delivery"]["verifications"] == []
    assert (repo / "shared.txt").read_text(encoding="utf-8") == "base\n"


def test_composed_delivery_must_pass_aggregate_verifiers(tmp_path: Path) -> None:
    repo = repository(tmp_path, {"a.txt": "base-a\n", "b.txt": "base-b\n"})
    edits = {"task-a": ("a.txt", "A\n"), "task-b": ("b.txt", "B\n")}
    manifest_path = manifest_file(tmp_path, repo, edits)
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    raw["tasks"][0]["verify"]["commands"][0]["argv"][-1] += (
        "; assert Path('b.txt').read_text(encoding='utf-8') == 'base-b\\n'"
    )
    manifest_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    state = tmp_path / "state"
    service = SchedulerService(state, worker_factory=EditingFactory(edits))

    outcome = asyncio.run(service.run(load_manifest(manifest_path), manifest_path, "single"))

    assert outcome.verified == 2
    assert outcome.failed == 1
    assert outcome.delivery_workspace is not None and outcome.delivery_workspace.is_dir()
    assert (outcome.delivery_workspace / "a.txt").read_text(encoding="utf-8") == "A\n"
    assert (outcome.delivery_workspace / "b.txt").read_text(encoding="utf-8") == "B\n"
    data = run_data(service.repository, outcome.run_id)
    assert data["delivery"]["status"] == "failed"
    assert [item["status"] for item in data["delivery"]["verifications"]] == [
        "failed",
        "skipped",
    ]


def test_delivery_cancellation_cleans_only_delivery_and_keeps_task_winners(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path, {"a.txt": "base-a\n", "b.txt": "base-b\n"})
    edits = {"task-a": ("a.txt", "A\n"), "task-b": ("b.txt", "B\n")}
    manifest_path = manifest_file(tmp_path, repo, edits)
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    raw["tasks"][0]["verify"]["commands"][0]["argv"][-1] += (
        "; import time; "
        "time.sleep(30) if Path('b.txt').read_text(encoding='utf-8') == 'B\\n' else None"
    )
    manifest_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    state = tmp_path / "state"
    service = SchedulerService(state, worker_factory=EditingFactory(edits))

    async def scenario() -> Path:
        running = asyncio.create_task(
            service.run(
                load_manifest(manifest_path), manifest_path, "single", run_id="cancel-delivery"
            )
        )
        for _ in range(300):
            with service.repository.connect() as connection:
                delivery = connection.execute(
                    "SELECT status,workspace_path FROM deliveries WHERE run_id='cancel-delivery'"
                ).fetchone()
            if delivery is not None and delivery["status"] == "verifying":
                delivery_path = Path(str(delivery["workspace_path"]))
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("delivery verification did not start")
        running.cancel()
        try:
            await running
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("cancelled delivery run returned normally")
        return delivery_path

    delivery_path = asyncio.run(scenario())

    with service.repository.connect() as connection:
        run = connection.execute("SELECT status FROM runs WHERE id='cancel-delivery'").fetchone()
        delivery = connection.execute(
            "SELECT status FROM deliveries WHERE run_id='cancel-delivery'"
        ).fetchone()
        winner_paths = [
            Path(str(row[0]))
            for row in connection.execute(
                "SELECT attempt.workspace_path FROM attempts attempt "
                "JOIN tasks task ON task.winner_attempt_id=attempt.id "
                "WHERE task.run_id='cancel-delivery'"
            ).fetchall()
        ]
    assert run is not None and run["status"] == "cancelled"
    assert delivery is not None and delivery["status"] == "cancelled"
    assert not delivery_path.exists()
    assert len(winner_paths) == 2 and all(path.is_dir() for path in winner_paths)
