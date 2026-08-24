from pathlib import Path

import pytest

from firstgreen.planning.compiler import can_auto_approve
from firstgreen.planning.workflow import default_planning_config
from firstgreen.testbed.golden import compare_golden
from firstgreen.testbed.loaders import load_golden
from firstgreen.testbed.repository import create_tinyshop_repository
from firstgreen.testbed.scenarios import compile_scenario


@pytest.mark.parametrize("scenario", ["S1", "S2", "S3", "S4", "S5", "S6"])
def test_scenario_plan_matches_semantic_golden(tmp_path: Path, scenario: str) -> None:
    repo = create_tinyshop_repository(tmp_path, scenario)
    plan = compile_scenario(scenario, repo)
    check = compare_golden(plan, load_golden(scenario))
    assert check.passed, check.violations


def test_f1_cycle_is_repaired_and_never_executable_as_cycle(tmp_path: Path) -> None:
    plan = compile_scenario("F1", create_tinyshop_repository(tmp_path, "F1"))
    assert plan.validation.valid
    assert len(plan.tasks) == 1
    assert plan.validation.repairs
    assert not plan.tasks[0].dependencies


def test_f2_coordination_only_plan_falls_back_to_concrete_task(tmp_path: Path) -> None:
    plan = compile_scenario("F2", create_tinyshop_repository(tmp_path, "F2"))
    assert plan.validation.valid
    assert [task.id for task in plan.tasks] == ["request"]
    assert "coordination-only" in " ".join(plan.validation.repairs)


def test_s6_cannot_be_policy_auto_approved_or_executed(tmp_path: Path) -> None:
    plan = compile_scenario("S6", create_tinyshop_repository(tmp_path, "S6"))
    assert plan.risk_level == "high"
    assert not can_auto_approve(plan, default_planning_config().risk, allow=True)
