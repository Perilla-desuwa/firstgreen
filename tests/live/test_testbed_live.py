import asyncio
import os
from pathlib import Path

import pytest

from firstgreen.config import load_manifest
from firstgreen.planning.compiler import can_auto_approve
from firstgreen.planning.planner import CodexPlannerAdapter, PlannerCache
from firstgreen.planning.workflow import default_planning_config
from firstgreen.testbed.execution import execute_scenario
from firstgreen.testbed.golden import compare_golden
from firstgreen.testbed.loaders import load_golden
from firstgreen.testbed.repository import create_tinyshop_repository
from firstgreen.testbed.scenarios import compile_scenario


def _require_selected_live_scenario(scenario: str) -> None:
    selected = os.getenv("FIRSTGREEN_LIVE_TESTBED_SCENARIO")
    if selected != scenario:
        pytest.skip(
            "set FIRSTGREEN_LIVE_TESTBED_SCENARIO to this exact scenario to permit one live case"
        )


def _required_live_model() -> str:
    model = os.getenv("FIRSTGREEN_LIVE_MODEL")
    if not model:
        pytest.skip("set FIRSTGREEN_LIVE_MODEL explicitly before a paid live test")
    return model


@pytest.mark.live
@pytest.mark.parametrize("scenario", ["S1", "S2", "S3", "S4", "S5", "S6"])
@pytest.mark.skipif(
    os.getenv("FIRSTGREEN_RUN_LIVE_TESTBED_PLANNER") != "1",
    reason="set FIRSTGREEN_RUN_LIVE_TESTBED_PLANNER=1 to permit paid planner calls",
)
def test_live_testbed_planning_semantics(tmp_path: Path, scenario: str) -> None:
    _require_selected_live_scenario(scenario)
    repo = create_tinyshop_repository(tmp_path, f"live-plan-{scenario}")
    plan = compile_scenario(
        scenario,
        repo,
        CodexPlannerAdapter(
            tmp_path / "planner",
            binary=os.getenv("FIRSTGREEN_CODEX_BINARY", "codex"),
            model=_required_live_model(),
            reasoning_effort=os.getenv("FIRSTGREEN_LIVE_REASONING", "low"),
            timeout_seconds=int(os.getenv("FIRSTGREEN_LIVE_TIMEOUT_SECONDS", "900")),
        ),
        PlannerCache(tmp_path / "cache"),
    )
    check = compare_golden(plan, load_golden(scenario))
    assert check.passed, check.violations
    if scenario == "S6":
        assert not can_auto_approve(plan, default_planning_config().risk, allow=True)


@pytest.mark.live
@pytest.mark.parametrize("scenario", ["S1", "S2", "S3"])
@pytest.mark.skipif(
    os.getenv("FIRSTGREEN_RUN_LIVE_TESTBED_CODING") != "1",
    reason="set FIRSTGREEN_RUN_LIVE_TESTBED_CODING=1 to permit authenticated coding usage",
)
def test_live_testbed_coding_uses_production_scheduler(tmp_path: Path, scenario: str) -> None:
    _require_selected_live_scenario(scenario)
    repo = create_tinyshop_repository(tmp_path, f"live-code-{scenario}")
    plan = compile_scenario(scenario, repo)
    max_tasks = int(os.getenv("FIRSTGREEN_MAX_LIVE_TASKS", "0"))
    if max_tasks < len(plan.tasks):
        pytest.skip(f"set FIRSTGREEN_MAX_LIVE_TASKS to at least {len(plan.tasks)} for {scenario}")
    model = _required_live_model()
    reasoning = os.getenv("FIRSTGREEN_LIVE_REASONING", "low")
    timeout_seconds = int(os.getenv("FIRSTGREEN_LIVE_TIMEOUT_SECONDS", "900"))
    binary = os.getenv("FIRSTGREEN_CODEX_BINARY", "codex")
    outcome = asyncio.run(
        execute_scenario(
            scenario,
            plan,
            repo,
            tmp_path / "state",
            adapter="codex_exec",
            use_fake_worker=False,
            codex_binary=binary,
            worker_model=model,
            worker_reasoning=reasoning,
            timeout_seconds=timeout_seconds,
        )
    )
    assert outcome.result.verified
    assert outcome.winner_count == len(plan.tasks)
    assert outcome.main_worktree_unchanged
    manifest = load_manifest(outcome.state_dir / "manifest.yaml")
    assert all(task.limits.max_attempts == 1 for task in manifest.tasks)
    assert manifest.agent_defaults.config["model"] == model
    assert manifest.agent_defaults.config["model_reasoning_effort"] == reasoning
    if len(plan.tasks) > 1:
        assert outcome.delivery_workspace is not None
        assert outcome.delivery_verified is True
