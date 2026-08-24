import asyncio
import json
import sys
from pathlib import Path

import pytest

from firstgreen.testbed.execution import execute_scenario, scenario_manifest
from firstgreen.testbed.repository import create_tinyshop_repository
from firstgreen.testbed.scenarios import compile_scenario


@pytest.mark.parametrize(("scenario", "parallelism"), [("S1", 1), ("S2", 2), ("S3", 2)])
def test_scenarios_execute_with_fake_workers_and_real_verifiers(
    tmp_path: Path, scenario: str, parallelism: int
) -> None:
    repo = create_tinyshop_repository(tmp_path, scenario)
    plan = compile_scenario(scenario, repo)
    outcome = asyncio.run(execute_scenario(scenario, plan, repo, tmp_path / f"state-{scenario}"))
    assert outcome.result.verified
    assert outcome.result.maximum_observed_parallelism == parallelism
    assert outcome.winner_count == len(plan.tasks)
    assert outcome.result.attempt_count == len(plan.tasks)
    assert outcome.main_worktree_unchanged
    assert all(path.is_dir() for path in outcome.winner_workspaces.values())
    if len(plan.tasks) > 1:
        assert outcome.delivery_workspace is not None and outcome.delivery_workspace.is_dir()
    else:
        assert outcome.delivery_workspace is None


def test_s2_independent_tasks_start_together_before_final_barrier(tmp_path: Path) -> None:
    repo = create_tinyshop_repository(tmp_path, "S2")
    plan = compile_scenario("S2", repo)
    outcome = asyncio.run(execute_scenario("S2", plan, repo, tmp_path / "state"))
    starts = {
        entry["task"]: entry["time"] for entry in outcome.timeline if entry["event"] == "started"
    }
    completed = {
        entry["task"]: entry["time"] for entry in outcome.timeline if entry["event"] == "completed"
    }
    assert max(starts["cli_version"], starts["health_commit"]) < min(
        completed["cli_version"], completed["health_commit"]
    )
    assert starts["repository_verification"] > starts["cli_version"]
    assert starts["repository_verification"] >= completed["cli_version"]
    assert starts["repository_verification"] >= completed["health_commit"]
    final = outcome.winner_workspaces["repository_verification"]
    assert "--version" in (final / "app/cli.py").read_text(encoding="utf-8")
    assert "TINYSHOP_COMMIT" in (final / "app/main.py").read_text(encoding="utf-8")


def test_s3_dependency_release_and_join(tmp_path: Path) -> None:
    repo = create_tinyshop_repository(tmp_path, "S3")
    plan = compile_scenario("S3", repo)
    outcome = asyncio.run(execute_scenario("S3", plan, repo, tmp_path / "state"))
    starts = {
        entry["task"]: entry["time"] for entry in outcome.timeline if entry["event"] == "started"
    }
    completed = {
        entry["task"]: entry["time"] for entry in outcome.timeline if entry["event"] == "completed"
    }
    assert max(starts["reset_token_model"], starts["reset_email"]) < min(
        completed["reset_token_model"], completed["reset_email"]
    )
    assert starts["reset_service"] >= completed["reset_token_model"]
    assert starts["reset_integration"] >= completed["reset_service"]
    assert starts["reset_integration"] >= completed["reset_email"]
    final = outcome.winner_workspaces["reset_integration"]
    assert "class ResetToken" in (final / "app/models.py").read_text(encoding="utf-8")
    assert "send_password_reset" in (final / "app/mailer.py").read_text(encoding="utf-8")
    assert (final / "tests/test_password_reset.py").is_file()


def test_production_manifest_allows_only_task_and_verified_ancestor_paths(
    tmp_path: Path,
) -> None:
    repo = create_tinyshop_repository(tmp_path, "S3-manifest")
    plan = compile_scenario("S3", repo)
    manifest = scenario_manifest("S3", plan)
    integration = next(task for task in manifest.tasks if task.id == "reset_integration")
    assert set(integration.verify.allowed_changed_paths) == {
        "app/auth/routes.py",
        "app/auth/service.py",
        "app/mailer.py",
        "app/models.py",
        "tests/test_password_reset.py",
    }


def test_live_manifest_snapshots_bounded_worker_configuration(tmp_path: Path) -> None:
    repo = create_tinyshop_repository(tmp_path, "S2-live-manifest")
    plan = compile_scenario("S2", repo)
    manifest = scenario_manifest(
        "S2",
        plan,
        adapter="codex_exec",
        codex_binary="C:/tools/codex.exe",
        worker_model="test-model",
        worker_reasoning="low",
        timeout_seconds=600,
    )
    assert manifest.agent_defaults.codex_binary == "C:/tools/codex.exe"
    assert manifest.agent_defaults.sandbox == "workspace-write"
    assert manifest.agent_defaults.timeout_seconds == 600
    assert manifest.agent_defaults.max_subagent_threads == 1
    assert manifest.agent_defaults.config == {
        "model": "test-model",
        "model_reasoning_effort": "low",
    }
    assert not manifest.scheduler.hedge.enabled
    assert all(not task.replay_safe for task in manifest.tasks)
    assert all(task.limits.max_attempts == 1 for task in manifest.tasks)
    for task in manifest.tasks:
        context = json.loads(task.prompt.split("Approved execution context:\n", 1)[1])
        rendered_commands = context["approved_task"]["scheduler_verifier_commands"]
        actual_commands = [command.argv for command in task.verify.commands]
        assert rendered_commands == actual_commands
        assert rendered_commands[0][:4] == [sys.executable, "-m", "pytest", "-q"]


def test_live_manifest_rejects_unbounded_or_implicit_configuration(tmp_path: Path) -> None:
    repo = create_tinyshop_repository(tmp_path, "S1-live-guard")
    plan = compile_scenario("S1", repo)
    with pytest.raises(ValueError, match="explicit worker model"):
        scenario_manifest("S1", plan, adapter="codex_exec")
    with pytest.raises(ValueError, match="bounded reasoning"):
        scenario_manifest(
            "S1", plan, adapter="codex_exec", worker_model="test-model", worker_reasoning="turbo"
        )
    with pytest.raises(ValueError, match="timeout"):
        scenario_manifest(
            "S1",
            plan,
            adapter="codex_exec",
            worker_model="test-model",
            worker_reasoning="low",
            timeout_seconds=3600,
        )


def test_s4_exclusive_write_resource_serializes_without_dependency(tmp_path: Path) -> None:
    repo = create_tinyshop_repository(tmp_path, "S4")
    plan = compile_scenario("S4", repo)
    assert plan.conflicts
    assert all(not task.dependencies for task in plan.tasks)
    outcome = asyncio.run(execute_scenario("S4", plan, repo, tmp_path / "state"))
    assert outcome.result.maximum_observed_parallelism == 1
    starts = sorted(
        float(entry["time"]) for entry in outcome.timeline if entry["event"] == "started"
    )
    completed = sorted(
        float(entry["time"]) for entry in outcome.timeline if entry["event"] == "completed"
    )
    assert len(starts) == 2
    assert starts[1] >= completed[0]
    assert outcome.delivery_workspace is not None and outcome.delivery_workspace.is_dir()
