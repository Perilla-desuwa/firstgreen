import asyncio
import json
import subprocess
import sys
from pathlib import Path

import yaml

from firstgreen.config import load_manifest
from firstgreen.db.repository import SQLiteRepository
from firstgreen.service import SchedulerService


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_critical_path_policy_selects_and_logs_bottom_level_rank(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "base.txt").write_text("base", encoding="utf-8")
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    manifest_path = tmp_path / "manifest.yaml"
    common = {
        "prompt": "fake",
        "replay_safe": False,
        "verify": {"commands": [{"argv": [sys.executable, "-c", "print('ok')"]}]},
    }
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "project": {"repo": str(repo), "base_ref": "main"},
                "scheduler": {
                    "ready_queue_policy": "critical_path",
                    "concurrency": {
                        "max_root": 1,
                        "initial_root": 1,
                        "total_agent_thread_budget": 1,
                    },
                },
                "agent_defaults": {"adapter": "fake"},
                "verification_defaults": {},
                "workspace": {},
                "tasks": [
                    {**common, "id": "short", "estimated_duration_seconds": 1},
                    {**common, "id": "critical", "estimated_duration_seconds": 2},
                    {
                        **common,
                        "id": "tail",
                        "dependencies": ["critical"],
                        "estimated_duration_seconds": 10,
                    },
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
    assert outcome.failed == 0

    with SQLiteRepository(state / "state.db").connect() as connection:
        row = connection.execute(
            "SELECT signals,policy_snapshot FROM scheduler_decisions "
            "WHERE decision_type='ready_queue_select' ORDER BY rowid LIMIT 1"
        ).fetchone()
    assert row is not None
    signals = json.loads(row["signals"])
    snapshot = json.loads(row["policy_snapshot"])
    assert signals["task_key"] == "critical"
    assert signals["bottom_level_seconds"] == 12
    assert snapshot["policy"] == "critical_path"
    assert snapshot["stable_fallback"] == "stable"
