import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from firstgreen.config import load_manifest
from firstgreen.db.repository import SQLiteRepository
from firstgreen.errors import WorkspaceSafetyError
from firstgreen.reporting.export import report_html, run_data
from firstgreen.service import SchedulerService
from firstgreen.workspace.dependency_overlay import DependencySnapshot
from firstgreen.workspace.git_worktree import Workspace


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "firstgreen@example.invalid")
    git(repo, "config", "user.name", "FirstGreen Test")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    return repo


def manifest_path(
    tmp_path: Path,
    repo: Path,
    *,
    verifier: list[str],
    fake_latency_seconds: float = 0,
) -> Path:
    path = tmp_path / "fleet.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "project": {"repo": str(repo), "base_ref": "main"},
                "scheduler": {"concurrency": {}},
                "agent_defaults": {
                    "adapter": "fake",
                    "config": {"fake_latency_seconds": fake_latency_seconds},
                },
                "verification_defaults": {},
                "workspace": {},
                "tasks": [
                    {
                        "id": "task",
                        "prompt": "fake",
                        "verify": {"commands": [{"argv": verifier}]},
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def test_failed_verifier_is_persisted_and_attempt_is_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = repository(tmp_path)
    monkeypatch.setenv("FIRSTGREEN_TEST_SECRET", "sk-secret-never-persist")
    verifier = [
        sys.executable,
        "-c",
        "import os; print(os.environ['FIRSTGREEN_TEST_SECRET']); raise SystemExit(1)",
    ]
    manifest = manifest_path(tmp_path, repo, verifier=verifier)
    state = tmp_path / "state"
    outcome = asyncio.run(SchedulerService(state).run(load_manifest(manifest), manifest, "single"))

    assert outcome.failed == 1
    repository_db = SQLiteRepository(state / "state.db")
    with repository_db.connect() as connection:
        attempt = connection.execute("SELECT status,finished_at FROM attempts").fetchone()
        verification = connection.execute(
            "SELECT status,exit_code,started_at,finished_at,output_path FROM verification_runs"
        ).fetchone()
    assert attempt is not None
    assert (attempt["status"], bool(attempt["finished_at"])) == ("failed", True)
    assert verification is not None
    assert verification["status"] == "failed"
    assert verification["exit_code"] == 1
    assert verification["started_at"] and verification["finished_at"]
    output_path = Path(str(verification["output_path"]))
    metadata = json.loads(output_path.read_text(encoding="utf-8"))
    assert metadata["captured_stdout_bytes"] > 0
    assert "sk-secret-never-persist" not in output_path.read_text(encoding="utf-8")
    data = run_data(repository_db, outcome.run_id)
    assert data["verifications"][0]["status"] == "failed"
    assert any(
        event["type"] == "verifier.completed"
        for event in connectionless_events(repository_db, outcome.run_id)
    )


def connectionless_events(repository_db: SQLiteRepository, run_id: str) -> list[dict[str, str]]:
    with repository_db.connect() as connection:
        return [
            {"type": str(row[0])}
            for row in connection.execute(
                "SELECT type FROM events WHERE run_id=? ORDER BY sequence", (run_id,)
            ).fetchall()
        ]


def test_workspace_prepare_failure_is_a_clean_failed_run(tmp_path: Path) -> None:
    class RaisingPreparer:
        async def prepare(
            self, workspace: Workspace, dependencies: tuple[DependencySnapshot, ...]
        ) -> None:
            del workspace, dependencies
            raise WorkspaceSafetyError("dependency collision")

    repo = repository(tmp_path)
    manifest = manifest_path(tmp_path, repo, verifier=[sys.executable, "-c", "pass"])
    state = tmp_path / "state"
    outcome = asyncio.run(
        SchedulerService(state, workspace_preparer=RaisingPreparer()).run(
            load_manifest(manifest), manifest, "single"
        )
    )

    assert outcome.failed == 1
    repository_db = SQLiteRepository(state / "state.db")
    with repository_db.connect() as connection:
        run = connection.execute("SELECT status,finished_at FROM runs").fetchone()
        task = connection.execute("SELECT status FROM tasks").fetchone()
        decision = connection.execute(
            "SELECT decision_type FROM scheduler_decisions "
            "WHERE decision_type='dependency_prepare_failed'"
        ).fetchone()
    assert run is not None and (run["status"], bool(run["finished_at"])) == (
        "failed",
        True,
    )
    assert task is not None and task["status"] == "failed"
    assert decision is not None and decision["decision_type"] == "dependency_prepare_failed"


def test_run_report_aggregates_filtered_usage_and_latest_verifier_evidence(
    tmp_path: Path,
) -> None:
    repository_db = SQLiteRepository(tmp_path / "state.db")
    repository_db.initialize()
    with repository_db.transaction() as connection:
        connection.execute(
            "INSERT INTO runs(id,manifest_hash,repo_path,base_sha,policy_snapshot,status,"
            "created_at,started_at,finished_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "run-report",
                "manifest",
                "C:/repo",
                "base",
                "{}",
                "completed",
                "2026-07-17T00:00:00+00:00",
                "2026-07-17T00:00:00+00:00",
                "2026-07-17T00:00:01+00:00",
            ),
        )
        connection.execute(
            "INSERT INTO tasks(id,run_id,task_key,prompt,status,winner_attempt_id,verified_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                "task-report",
                "run-report",
                "task",
                "filtered",
                "verified",
                "attempt-report",
                "2026-07-17T00:00:01+00:00",
            ),
        )
        connection.execute(
            "INSERT INTO attempts(id,task_id,ordinal,role,status,base_sha,config_snapshot,"
            "workspace_path,branch,started_at,finished_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                "attempt-report",
                "task-report",
                1,
                "primary",
                "winner",
                "base",
                "{}",
                "C:/workspace",
                "fg/run-report/task/1",
                "2026-07-17T00:00:00+00:00",
                "2026-07-17T00:00:01+00:00",
            ),
        )
        connection.execute(
            "INSERT INTO verification_runs(id,attempt_id,command_index,verification_round,"
            "command_json,status,exit_code) VALUES(?,?,?,?,?,?,?)",
            (
                "verification-report",
                "attempt-report",
                0,
                2,
                '{"argv":["python","-m","pytest"]}',
                "passed",
                0,
            ),
        )
    repository_db.append_event(
        "worker-usage-report",
        "worker.completed",
        "2026-07-17T00:00:00+00:00",
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 10,
                "cached_input_tokens": 4,
                "output_tokens": 2,
                "reasoning_output_tokens": 1,
            },
        },
        run_id="run-report",
        task_id="task-report",
        attempt_id="attempt-report",
    )
    repository_db.append_event(
        "latest-verifier-evidence",
        "verifier.completed",
        "2026-07-17T00:00:00+00:00",
        {
            "passed": False,
            "changed_paths": ["src/feature.py", "tests/test_feature.py"],
            "disallowed_paths": ["secrets.txt"],
            "diff_hash": "abc",
            "verification_round": 2,
        },
        run_id="run-report",
        task_id="task-report",
        attempt_id="attempt-report",
    )

    data = run_data(repository_db, "run-report")

    assert data["usage"] == {
        "reported": True,
        "attempts_reported": 1,
        "input_tokens": 10,
        "cached_input_tokens": 4,
        "output_tokens": 2,
        "reasoning_output_tokens": 1,
        "total_tokens": 12,
        "raw_totals": {
            "input_tokens": 10,
            "cached_input_tokens": 4,
            "output_tokens": 2,
            "reasoning_output_tokens": 1,
        },
    }
    assert data["changes"]["changed_paths"] == ["src/feature.py", "tests/test_feature.py"]
    assert data["changes"]["disallowed_paths"] == ["secrets.txt"]
    assert data["changes"]["latest_by_attempt"][0]["verification_round"] == 2
    report = report_html(repository_db, "run-report", tmp_path / "report.html")
    html = report.read_text(encoding="utf-8")
    assert "Worker usage" in html
    assert "src/feature.py" in html
    assert "Disallowed paths detected" in html


def test_scheduler_cancellation_terminalizes_run_task_attempt_and_cleans_workspace(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)
    manifest = manifest_path(
        tmp_path,
        repo,
        verifier=[sys.executable, "-c", "print('ok')"],
        fake_latency_seconds=30,
    )
    state = tmp_path / "state"
    service = SchedulerService(state)

    async def scenario() -> None:
        running = asyncio.create_task(
            service.run(load_manifest(manifest), manifest, "single", run_id="cancelled-run")
        )
        for _ in range(200):
            with service.repository.connect() as connection:
                attempt = connection.execute(
                    "SELECT status FROM attempts WHERE status='running'"
                ).fetchone()
            if attempt is not None:
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("attempt did not start")
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running

    asyncio.run(scenario())

    with service.repository.connect() as connection:
        run = connection.execute(
            "SELECT status,finished_at FROM runs WHERE id='cancelled-run'"
        ).fetchone()
        task = connection.execute("SELECT status FROM tasks").fetchone()
        attempt = connection.execute(
            "SELECT status,finished_at,workspace_path FROM attempts"
        ).fetchone()
    assert run is not None and (run["status"], bool(run["finished_at"])) == (
        "cancelled",
        True,
    )
    assert task is not None and task["status"] == "cancelled"
    assert attempt is not None and (attempt["status"], bool(attempt["finished_at"])) == (
        "cancelled",
        True,
    )
    assert not Path(str(attempt["workspace_path"])).exists()
    git(repo, "worktree", "prune")
    worktrees = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert worktrees.count("worktree ") == 1
