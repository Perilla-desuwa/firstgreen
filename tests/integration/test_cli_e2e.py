import json
import os
import subprocess
import sys
from pathlib import Path

import yaml
from typer.testing import CliRunner

from firstgreen.cli import app
from firstgreen.db.repository import SQLiteRepository


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_fake_run_report_and_exports(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "firstgreen@example.invalid")
    git(repo, "config", "user.name", "FirstGreen Test")
    (repo / "base.txt").write_text("base", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    manifest = tmp_path / "fleet.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "project": {"repo": str(repo), "base_ref": "main"},
                "scheduler": {
                    "concurrency": {
                        "mode": "static",
                        "min_root": 1,
                        "max_root": 1,
                        "initial_root": 1,
                        "total_agent_thread_budget": 1,
                        "verifier_slots": 1,
                    }
                },
                "agent_defaults": {"adapter": "fake"},
                "verification_defaults": {},
                "workspace": {},
                "tasks": [
                    {
                        "id": "smoke",
                        "prompt": "fake",
                        "replay_safe": True,
                        "verify": {
                            "commands": [{"argv": [sys.executable, "-c", "print('green')"]}]
                        },
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    state = tmp_path / "state"
    runner = CliRunner()
    result = runner.invoke(app, ["run", str(manifest), "--state-dir", str(state)])
    assert result.exit_code == 0, result.output
    run_id = json.loads(result.output)["run_id"]
    automatic_report = state / "reports" / run_id / "report.html"
    assert automatic_report.is_file()
    report_text = automatic_report.read_text(encoding="utf-8")
    assert "Worker usage" in report_text
    assert "Verification" in report_text
    status = runner.invoke(app, ["status", run_id, "--state-dir", str(state)])
    assert status.exit_code == 0
    assert json.loads(status.output)["run"]["id"] == run_id
    logs = runner.invoke(app, ["logs", run_id, "--json", "--state-dir", str(state)])
    assert logs.exit_code == 0
    assert any(event["type"] == "worker.completed" for event in json.loads(logs.output))
    assert runner.invoke(app, ["report", run_id, "--state-dir", str(state)]).exit_code == 0
    assert (
        runner.invoke(
            app,
            ["export", run_id, "--format", "json", "--state-dir", str(state)],
        ).exit_code
        == 0
    )
    assert automatic_report.is_file()
    assert (state / "exports" / f"{run_id}.json").is_file()
    assert (repo / "base.txt").read_text(encoding="utf-8") == "base"


def test_cli_returns_verified_delivery_for_multi_task_manifest(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "firstgreen@example.invalid")
    git(repo, "config", "user.name", "FirstGreen Test")
    (repo / "base.txt").write_text("base", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    manifest = tmp_path / "fleet.yaml"
    manifest.write_text(
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
                "tasks": [
                    {
                        "id": task,
                        "prompt": "fake",
                        "verify": {
                            "commands": [{"argv": [sys.executable, "-c", "print('green')"]}]
                        },
                    }
                    for task in ("a", "b")
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    state = tmp_path / "state"

    result = CliRunner().invoke(app, ["run", str(manifest), "--state-dir", str(state)])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    delivery = Path(payload["delivery_workspace"])
    assert delivery.is_dir()
    status = CliRunner().invoke(
        app, ["status", payload["run_id"], "--json", "--state-dir", str(state)]
    )
    assert status.exit_code == 0, status.output
    assert json.loads(status.output)["delivery"]["status"] == "verified"


def test_one_shot_delayed_hedge_backup_wins_and_loser_is_cleaned(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "firstgreen@example.invalid")
    git(repo, "config", "user.name", "FirstGreen Test")
    (repo / "base.txt").write_text("base", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    manifest = tmp_path / "fleet.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "project": {"repo": str(repo), "base_ref": "main"},
                "scheduler": {
                    "concurrency": {
                        "mode": "static",
                        "min_root": 1,
                        "max_root": 2,
                        "initial_root": 1,
                        "total_agent_thread_budget": 2,
                        "verifier_slots": 2,
                    },
                    "hedge": {"enabled": True, "fallback_after_seconds": 0.02},
                },
                "agent_defaults": {
                    "adapter": "fake",
                    "config": {
                        "fake_latency_seconds": 2.0,
                        "fake_backup_latency_seconds": 0.01,
                    },
                },
                "verification_defaults": {},
                "workspace": {},
                "tasks": [
                    {
                        "id": "smoke",
                        "prompt": "fake",
                        "replay_safe": True,
                        "verify": {
                            "commands": [{"argv": [sys.executable, "-c", "print('green')"]}]
                        },
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    state = tmp_path / "state"
    result = CliRunner().invoke(
        app,
        [
            "run",
            str(manifest),
            "--policy",
            "delayed-hedge",
            "--state-dir",
            str(state),
        ],
    )
    assert result.exit_code == 0, result.output
    with SQLiteRepository(state / "state.db").connect() as connection:
        attempts = connection.execute(
            "SELECT role,status,workspace_path FROM attempts ORDER BY ordinal"
        ).fetchall()
    assert [(row["role"], row["status"]) for row in attempts] == [
        ("primary", "cancelled"),
        ("hedge", "winner"),
    ]
    assert not Path(attempts[0]["workspace_path"]).exists()
    assert Path(attempts[1]["workspace_path"]).exists()


def test_dry_run_resolves_explicit_codex_worker_options(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "firstgreen@example.invalid")
    git(repo, "config", "user.name", "FirstGreen Test")
    (repo / "base.txt").write_text("base", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    manifest = tmp_path / "fleet.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "project": {"repo": str(repo), "base_ref": "main"},
                "scheduler": {"concurrency": {}},
                "agent_defaults": {"adapter": "codex_exec"},
                "verification_defaults": {},
                "workspace": {},
                "tasks": [
                    {
                        "id": "smoke",
                        "prompt": "fix",
                        "verify": {"commands": [{"argv": [sys.executable, "-c", "print('ok')"]}]},
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    state = tmp_path / "state"
    result = CliRunner().invoke(
        app,
        [
            "run",
            str(manifest),
            "--model",
            "gpt-5.6-luna",
            "--reasoning",
            "low",
            "--codex-binary",
            "C:/tools/codex.exe",
            "--verifier-python",
            sys.executable,
            "--dry-run",
            "--state-dir",
            str(state),
        ],
    )
    assert result.exit_code == 0, result.output
    compiled = Path(json.loads(result.output)["compiled_manifest"])
    loaded = yaml.safe_load(compiled.read_text(encoding="utf-8"))
    assert loaded["agent_defaults"]["codex_binary"] == "C:/tools/codex.exe"
    assert loaded["agent_defaults"]["config"] == {
        "model": "gpt-5.6-luna",
        "model_reasoning_effort": "low",
    }
    assert loaded["agent_defaults"]["disabled_features"] == [
        "code_mode",
        "code_mode_host",
    ]
    assert loaded["verification_defaults"]["executable_overrides"] == {
        "python": os.path.abspath(sys.executable),
        "python3": os.path.abspath(sys.executable),
    }
