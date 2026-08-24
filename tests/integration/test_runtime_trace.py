import asyncio
import json
import subprocess
import sys
from pathlib import Path

import yaml

from firstgreen.config import load_manifest
from firstgreen.db.repository import SQLiteRepository
from firstgreen.reporting.trace import export_trace, runtime_observability
from firstgreen.service import SchedulerService


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_trace_is_sanitized_and_summary_is_rebuildable(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "base.txt").write_text("base", encoding="utf-8")
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "project": {"repo": str(repo), "base_ref": "main"},
                "scheduler": {
                    "concurrency": {
                        "max_root": 1,
                        "initial_root": 1,
                        "total_agent_thread_budget": 1,
                    }
                },
                "agent_defaults": {
                    "adapter": "fake",
                    "config": {"fake_latency_seconds": 0.02},
                },
                "verification_defaults": {},
                "workspace": {},
                "tasks": [
                    {
                        "id": "task",
                        "prompt": "SECRET PROMPT MUST NOT APPEAR",
                        "verify": {"commands": [{"argv": [sys.executable, "-c", "pass"]}]},
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    state = tmp_path / "state"
    outcome = asyncio.run(
        SchedulerService(state).run(load_manifest(manifest_path), manifest_path, "single")
    )
    repository = SQLiteRepository(state / "state.db")
    summary = runtime_observability(repository, outcome.run_id)
    output = export_trace(repository, outcome.run_id, tmp_path / "trace.json")
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert summary["makespan_seconds"] > 0
    assert summary["agent_seconds"] > 0
    assert 0 < summary["root_slot_utilization"] <= 1
    assert summary["idle_root_slot_seconds"] >= 0
    assert "resource_locked" in summary["idle_reason_observations"]
    assert summary["attempt_count"] == 1
    assert {event["cat"] for event in payload["traceEvents"]} == {"agent", "verifier"}
    assert "SECRET PROMPT" not in output.read_text(encoding="utf-8")
    assert str(repo) not in output.read_text(encoding="utf-8")
    with repository.connect() as connection:
        lifecycle = {
            str(row[0])
            for row in connection.execute(
                "SELECT type FROM events WHERE run_id=?", (outcome.run_id,)
            ).fetchall()
        }
    assert {
        "scheduler.ready_set",
        "scheduler.task_admitted",
        "scheduler.task_finished",
        "verifier.admitted",
    } <= lifecycle
