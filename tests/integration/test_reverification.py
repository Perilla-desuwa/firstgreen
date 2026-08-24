import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from firstgreen.cli import app
from firstgreen.config import load_manifest
from firstgreen.errors import WorkspaceSafetyError
from firstgreen.service import SchedulerService


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


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


def manifest_path(tmp_path: Path, repo: Path) -> Path:
    path = tmp_path / "fleet.yaml"
    verifier = (
        "import os; raise SystemExit(0 if os.environ.get('FIRSTGREEN_REVERIFY_PASS') == '1' else 7)"
    )
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
                        "id": "task",
                        "prompt": "fake",
                        "limits": {"max_attempts": 1},
                        "verify": {"commands": [{"argv": ["python", "-c", verifier]}]},
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def failed_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, SchedulerService, str, str, Path]:
    repo = repository(tmp_path)
    manifest = manifest_path(tmp_path, repo)
    state = tmp_path / "state"
    monkeypatch.delenv("FIRSTGREEN_REVERIFY_PASS", raising=False)
    service = SchedulerService(state)
    outcome = asyncio.run(service.run(load_manifest(manifest), manifest, "single"))
    assert outcome.failed == 1
    with service.repository.connect() as connection:
        attempt = connection.execute("SELECT id,workspace_path FROM attempts").fetchone()
    assert attempt is not None
    return (
        repo,
        manifest,
        service,
        outcome.run_id,
        str(attempt["id"]),
        Path(str(attempt["workspace_path"])),
    )


def test_cli_reverifies_preserved_attempt_without_restarting_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, manifest, service, run_id, attempt_id, workspace = failed_run(tmp_path, monkeypatch)
    monkeypatch.setenv("FIRSTGREEN_REVERIFY_PASS", "1")

    result = CliRunner().invoke(
        app,
        [
            "reverify",
            run_id,
            "--attempt",
            attempt_id,
            "--manifest",
            str(manifest),
            "--verifier-python",
            sys.executable,
            "--state-dir",
            str(tmp_path / "state"),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {
        "run_id": run_id,
        "attempt_id": attempt_id,
        "verification_round": 2,
        "verified": True,
        "winner_claimed": True,
        "worker_restarted": False,
    }
    with service.repository.connect() as connection:
        run = connection.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
        task = connection.execute(
            "SELECT status,winner_attempt_id FROM tasks WHERE run_id=?", (run_id,)
        ).fetchone()
        attempt = connection.execute(
            "SELECT status FROM attempts WHERE id=?", (attempt_id,)
        ).fetchone()
        rounds = connection.execute(
            "SELECT verification_round,status,output_path FROM verification_runs "
            "WHERE attempt_id=? ORDER BY verification_round",
            (attempt_id,),
        ).fetchall()
        attempts = connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
        decisions = connection.execute(
            "SELECT decision_type FROM scheduler_decisions WHERE run_id=?", (run_id,)
        ).fetchall()
    assert run is not None and run["status"] == "completed"
    assert task is not None and tuple(task) == ("verified", attempt_id)
    assert attempt is not None and attempt["status"] == "winner"
    assert [(row["verification_round"], row["status"]) for row in rounds] == [
        (1, "failed"),
        (2, "passed"),
    ]
    metadata = json.loads(Path(str(rounds[1]["output_path"])).read_text(encoding="utf-8"))
    assert Path(metadata["resolved_executable"]).resolve() == Path(sys.executable).resolve()
    assert metadata["launch_error_kind"] is None
    assert attempts == 1
    assert [row["decision_type"] for row in decisions] == [
        "ready_queue_select",
        "attempt_policy",
        "repair_limit_reached",
        "manual_reverification",
    ]
    assert workspace.exists()
    assert git(repo, "status", "--porcelain") == ""

    repeated = CliRunner().invoke(
        app,
        [
            "reverify",
            run_id,
            "--attempt",
            attempt_id,
            "--manifest",
            str(manifest),
            "--state-dir",
            str(tmp_path / "state"),
        ],
    )
    assert repeated.exit_code == 2
    assert "no winner" in repeated.output


def test_cli_recovers_attempt_that_has_no_verification_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, manifest, service, run_id, attempt_id, workspace = failed_run(tmp_path, monkeypatch)
    with service.repository.transaction() as connection:
        connection.execute("DELETE FROM verification_runs WHERE attempt_id=?", (attempt_id,))
    monkeypatch.setenv("FIRSTGREEN_REVERIFY_PASS", "1")

    result = CliRunner().invoke(
        app,
        [
            "reverify",
            run_id,
            "--attempt",
            attempt_id,
            "--manifest",
            str(manifest),
            "--verifier-python",
            sys.executable,
            "--state-dir",
            str(tmp_path / "state"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "run_id": run_id,
        "attempt_id": attempt_id,
        "verification_round": 1,
        "verified": True,
        "winner_claimed": True,
        "worker_restarted": False,
    }
    with service.repository.connect() as connection:
        statuses = connection.execute(
            "SELECT r.status,t.status,a.status,t.winner_attempt_id "
            "FROM runs r JOIN tasks t ON t.run_id=r.id "
            "JOIN attempts a ON a.task_id=t.id WHERE r.id=?",
            (run_id,),
        ).fetchone()
        decision = connection.execute(
            "SELECT signals FROM scheduler_decisions WHERE run_id=? "
            "AND decision_type='manual_reverification'",
            (run_id,),
        ).fetchone()
    assert statuses is not None and tuple(statuses) == (
        "completed",
        "verified",
        "winner",
        attempt_id,
    )
    assert decision is not None
    assert json.loads(decision["signals"])["initial_verification_recovery"] is True
    assert workspace.exists()


def test_reverify_rejects_changed_manifest_without_reopening_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, manifest, service, run_id, attempt_id, _ = failed_run(tmp_path, monkeypatch)
    changed = tmp_path / "changed.yaml"
    changed.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="manifest bytes"):
        asyncio.run(service.reverify(load_manifest(changed), changed, run_id, attempt_id))

    with service.repository.connect() as connection:
        statuses = connection.execute(
            "SELECT r.status,t.status,a.status FROM runs r JOIN tasks t ON t.run_id=r.id "
            "JOIN attempts a ON a.task_id=t.id WHERE r.id=?",
            (run_id,),
        ).fetchone()
        rounds = connection.execute(
            "SELECT COUNT(*) FROM verification_runs WHERE attempt_id=?", (attempt_id,)
        ).fetchone()[0]
    assert statuses is not None and tuple(statuses) == ("failed", "failed", "failed")
    assert rounds == 1


def test_reverify_refuses_tampered_workspace_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, manifest, service, run_id, attempt_id, workspace = failed_run(tmp_path, monkeypatch)
    (workspace / ".firstgreen-attempt.json").write_text("{}", encoding="utf-8")

    with pytest.raises(WorkspaceSafetyError, match="matching marker"):
        asyncio.run(service.reverify(load_manifest(manifest), manifest, run_id, attempt_id))

    with service.repository.connect() as connection:
        statuses = connection.execute(
            "SELECT r.status,t.status,a.status FROM runs r JOIN tasks t ON t.run_id=r.id "
            "JOIN attempts a ON a.task_id=t.id WHERE r.id=?",
            (run_id,),
        ).fetchone()
    assert statuses is not None and tuple(statuses) == ("failed", "failed", "failed")
