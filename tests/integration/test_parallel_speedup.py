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


def run_with_slots(tmp_path: Path, repo: Path, slots: int) -> float:
    manifest_path = tmp_path / f"manifest-{slots}.yaml"
    common = {
        "prompt": "fake",
        "replay_safe": False,
        "estimated_duration_seconds": 1,
        "verify": {"commands": [{"argv": [sys.executable, "-c", "pass"]}]},
    }
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "project": {"repo": str(repo), "base_ref": "main"},
                "scheduler": {
                    "ready_queue_policy": "critical_path",
                    "concurrency": {
                        "max_root": slots,
                        "initial_root": slots,
                        "total_agent_thread_budget": slots,
                        "verifier_slots": slots,
                    },
                },
                "agent_defaults": {
                    "adapter": "fake",
                    "config": {"fake_latency_seconds": 0.3},
                },
                "verification_defaults": {
                    "delivery_commands": [{"argv": [sys.executable, "-c", "pass"]}]
                },
                "workspace": {},
                "tasks": [
                    {**common, "id": "left"},
                    {**common, "id": "right"},
                    {**common, "id": "join", "dependencies": ["left", "right"]},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    state = tmp_path / f"state-{slots}"
    outcome = asyncio.run(
        SchedulerService(state).run(load_manifest(manifest_path), manifest_path, "single")
    )
    assert outcome.failed == 0
    assert outcome.delivery_workspace is not None
    with SQLiteRepository(state / "state.db").connect() as connection:
        rows = connection.execute("SELECT started_at,finished_at FROM attempts").fetchall()
    started = min(datetime.fromisoformat(row["started_at"]) for row in rows)
    finished = max(datetime.fromisoformat(row["finished_at"]) for row in rows)
    return (finished - started).total_seconds()


def test_branch_join_dag_is_faster_with_two_root_slots(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "base.txt").write_text("base", encoding="utf-8")
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")

    serial = run_with_slots(tmp_path, repo, 1)
    parallel = run_with_slots(tmp_path, repo, 2)

    assert parallel + 0.15 < serial
