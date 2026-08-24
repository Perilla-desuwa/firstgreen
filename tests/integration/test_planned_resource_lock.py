import asyncio
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

from firstgreen.config import load_manifest
from firstgreen.db.repository import SQLiteRepository
from firstgreen.service import SchedulerService


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_exclusive_write_resource_serializes_tasks(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "base.txt").write_text("base")
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    manifest_path = tmp_path / "fleet.yaml"
    base_task = {
        "task_class": "planned",
        "prompt": "fake",
        "replay_safe": False,
        "dependencies": [],
        "resources": [{"key": "write:src/auth", "capacity": 1}],
        "verify": {"commands": [{"argv": [sys.executable, "-c", "print('ok')"]}]},
    }
    manifest_path.write_text(
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
                "agent_defaults": {
                    "adapter": "fake",
                    "config": {"fake_latency_seconds": 0.25},
                },
                "verification_defaults": {},
                "workspace": {},
                "tasks": [
                    {**base_task, "id": "a"},
                    {**base_task, "id": "b"},
                    {**base_task, "id": "c", "resources": []},
                ],
            },
            sort_keys=False,
        )
    )
    state = tmp_path / "state"
    asyncio.run(SchedulerService(state).run(load_manifest(manifest_path), manifest_path, "single"))
    with SQLiteRepository(state / "state.db").connect() as connection:
        rows = connection.execute(
            "SELECT task.task_key,attempt.started_at FROM attempts attempt "
            "JOIN tasks task ON task.id=attempt.task_id ORDER BY attempt.started_at"
        ).fetchall()
        holds = connection.execute(
            "SELECT signals FROM scheduler_decisions WHERE decision_type='admission_hold'"
        ).fetchall()
    starts = {str(row["task_key"]): datetime.fromisoformat(row["started_at"]) for row in rows}
    assert abs((starts["c"] - starts["a"]).total_seconds()) < 0.2
    assert (starts["b"] - starts["a"]).total_seconds() >= 0.2
    assert holds
