import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

import firstgreen.cli as cli_module
from firstgreen.benchmark import run_scaling_matrix, write_scaling_svg
from firstgreen.cli import app
from firstgreen.config import load_manifest


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_scaling_driver_replays_frozen_manifest_and_appends_raw_cells(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "base.txt").write_text("base", encoding="utf-8")
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    manifest_path = tmp_path / "frozen.yaml"
    command = {"argv": [sys.executable, "-c", "pass"]}
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "project": {"repo": str(repo), "base_ref": "main"},
                "scheduler": {"concurrency": {}},
                "agent_defaults": {
                    "adapter": "fake",
                    "config": {"fake_latency_seconds": 0.08},
                },
                "verification_defaults": {"delivery_commands": [command]},
                "workspace": {},
                "tasks": [
                    {"id": "left", "prompt": "left", "verify": {"commands": [command]}},
                    {"id": "right", "prompt": "right", "verify": {"commands": [command]}},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    before = manifest_path.read_bytes()
    branches_before = subprocess.run(
        ["git", "-C", str(repo), "branch", "--format=%(refname:short)"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    journal = tmp_path / "results" / "raw.jsonl"
    results = asyncio.run(
        run_scaling_matrix(
            load_manifest(manifest_path),
            frozen_manifest_path=manifest_path,
            state_root=tmp_path / "results" / "runs",
            journal_path=journal,
            slots=(1, 2, 4, 8, 16),
        )
    )

    assert manifest_path.read_bytes() == before
    branches_after = subprocess.run(
        ["git", "-C", str(repo), "branch", "--format=%(refname:short)"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert branches_after == branches_before
    assert [result["slots"] for result in results] == [1, 2, 4, 8, 16]
    assert all(result["failed"] == 0 for result in results)
    assert results[1]["speedup_vs_first_one_slot"] > 1
    rows = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 5
    assert len({row["frozen_manifest_sha256"] for row in rows}) == 1
    figure = write_scaling_svg(results, tmp_path / "results" / "scaling.svg")
    assert "FirstGreen scripted strong scaling" in figure.read_text(encoding="utf-8")

    preserved_state = tmp_path / "preserved" / "runs"
    asyncio.run(
        run_scaling_matrix(
            load_manifest(manifest_path),
            frozen_manifest_path=manifest_path,
            state_root=preserved_state,
            journal_path=tmp_path / "preserved" / "raw.jsonl",
            slots=(2,),
            scale_verifier_slots=False,
        )
    )
    replayed = load_manifest(preserved_state / "slots-2" / "repeat-1" / "manifest.yaml")
    assert replayed.scheduler.concurrency.max_root == 2
    assert replayed.scheduler.concurrency.verifier_slots == 1


def test_scaling_cli_can_skip_figure_without_a_one_slot_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = tmp_path / "fixed-capacity.yaml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "project": {"repo": str(tmp_path), "base_ref": "HEAD"},
                "scheduler": {"concurrency": {}},
                "agent_defaults": {"adapter": "fake"},
                "verification_defaults": {},
                "workspace": {},
                "tasks": [
                    {
                        "id": "only",
                        "prompt": "only",
                        "verify": {"commands": [{"argv": [sys.executable, "-c", "pass"]}]},
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    matrix_options: dict[str, object] = {}

    async def fake_matrix(*args: object, **kwargs: object) -> list[dict[str, Any]]:
        matrix_options.update(kwargs)
        return [
            {
                "slots": 2,
                "repetition": repetition,
                "failed": 0,
                "speedup_vs_first_one_slot": None,
            }
            for repetition in (1, 2, 3)
        ]

    def unexpected_figure(*args: object, **kwargs: object) -> Path:
        raise AssertionError("figure writer must not run without an explicit baseline")

    monkeypatch.setattr(cli_module, "run_scaling_matrix", fake_matrix)
    monkeypatch.setattr(cli_module, "write_scaling_svg", unexpected_figure)
    output_dir = tmp_path / "results"

    result = CliRunner().invoke(
        app,
        [
            "benchmark",
            "scaling",
            str(manifest_path),
            "--slots",
            "2",
            "--repetitions",
            "3",
            "--output-dir",
            str(output_dir),
            "--no-write-figure",
            "--preserve-verifier-slots",
        ],
    )

    assert result.exit_code == 0, result.output
    assert matrix_options["scale_verifier_slots"] is False
    assert (output_dir / "summary.json").exists()
    assert not (output_dir / "scaling.svg").exists()
