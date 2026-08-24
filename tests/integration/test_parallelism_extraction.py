import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from firstgreen.config import CommandConfig, VerifyConfig
from firstgreen.planning.workflow import PlanningEngine, default_planning_config, plan_to_manifest
from firstgreen.service import SchedulerService


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def initialize(repo: Path) -> Path:
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    return repo


def python_repository(root: Path) -> Path:
    repo = root / "python-repo"
    for relative in (
        "src/models/user.py",
        "src/services/auth.py",
        "src/mail/reset.py",
        "src/routes/reset.py",
        "tests/test_reset.py",
        "docs/reset.md",
    ):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        content = (
            "def test_fixture():\n    assert True\n" if "tests/" in relative else "# fixture\n"
        )
        path.write_text(content, encoding="utf-8")
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    return initialize(repo)


def javascript_repository(root: Path) -> Path:
    repo = root / "javascript-repo"
    for relative in (
        "src/models/user.js",
        "src/services/auth.js",
        "src/mail/reset.js",
        "src/routes/reset.js",
        "docs/reset.md",
    ):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("// fixture\n", encoding="utf-8")
    (repo / "package.json").write_text(
        json.dumps({"scripts": {"test": "node --test"}}), encoding="utf-8"
    )
    return initialize(repo)


@pytest.mark.parametrize("repository", [python_repository, javascript_repository])
def test_repo_goal_freezes_parallelism_analysis_and_compiles_manifest(
    tmp_path: Path, repository: object
) -> None:
    repo = repository(tmp_path)  # type: ignore[operator]
    engine = PlanningEngine(tmp_path / f"state-{repo.name}")
    config = default_planning_config()
    outcome = engine.plan_issue(
        "Add a user model, reset service, email notification, API route, tests, and docs",
        repo,
        config,
    )

    assert outcome.plan.validation.valid
    analysis = outcome.plan.parallelism_analysis
    assert analysis is not None
    assert analysis.ready_width >= 2
    assert analysis.recommended_root_slots >= 2
    assert analysis.estimated_work_seconds > analysis.estimated_span_seconds
    assert analysis.critical_path

    approved = engine.approve(outcome, config)
    manifest = plan_to_manifest(approved, adapter="fake", replay_safe=False)
    assert manifest.scheduler.ready_queue_policy == "critical_path"
    assert manifest.scheduler.concurrency.max_root == analysis.recommended_root_slots
    assert manifest.planning_record is not None
    persisted_analysis = manifest.planning_record["parallelism_analysis"]
    assert isinstance(persisted_analysis, dict)
    assert persisted_analysis["estimate_hash"] == analysis.estimate_hash
    assert all(task.estimated_duration_seconds > 0 for task in manifest.tasks)


def test_sequential_goal_reports_insufficient_parallelism(tmp_path: Path) -> None:
    repo = python_repository(tmp_path)
    engine = PlanningEngine(tmp_path / "state-sequential")
    outcome = engine.plan_issue("Fix a typo in one file", repo, default_planning_config())

    analysis = outcome.plan.parallelism_analysis
    assert analysis is not None
    assert outcome.plan.decision.decision == "single_task"
    assert analysis.ready_width == 1
    assert analysis.recommended_root_slots == 1
    assert analysis.exposed_parallelism == 1
    assert "No dependency" in analysis.recommendation_reason


def test_approved_extracted_plan_runs_to_verified_delivery(tmp_path: Path) -> None:
    repo = python_repository(tmp_path)
    state = tmp_path / "state-execute"
    engine = PlanningEngine(state)
    config = default_planning_config()
    outcome = engine.plan_issue(
        "Add a user model, reset service, email notification, API route, tests, and docs",
        repo,
        config,
    )
    approved = engine.approve(outcome, config)
    manifest = plan_to_manifest(approved, adapter="fake", replay_safe=False)
    manifest = manifest.model_copy(
        update={
            "tasks": [
                task.model_copy(
                    update={
                        "verify": VerifyConfig(
                            commands=[CommandConfig(argv=[sys.executable, "-c", "pass"])],
                            allowed_changed_paths=task.verify.allowed_changed_paths,
                        )
                    }
                )
                for task in manifest.tasks
            ],
            "agent_defaults": manifest.agent_defaults.model_copy(
                update={"config": {"fake_latency_seconds": 0.01}}
            ),
            "verification_defaults": manifest.verification_defaults.model_copy(
                update={"delivery_commands": [CommandConfig(argv=[sys.executable, "-c", "pass"])]}
            ),
        }
    )
    manifest_path = tmp_path / "approved-manifest.yaml"
    manifest_path.write_text(
        yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )

    run = asyncio.run(SchedulerService(state).run(manifest, manifest_path, "single"))

    assert run.failed == 0
    assert run.verified == len(approved.tasks)
    assert run.delivery_workspace is not None and run.delivery_workspace.is_dir()
