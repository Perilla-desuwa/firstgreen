from pathlib import Path

import pytest
from pydantic import ValidationError

from firstgreen.config import PlanningConfig
from firstgreen.planning.models import (
    CandidatePlan,
    DecompositionDecision,
    PlanTask,
    PlanValidationResult,
    ProposedTask,
)


def test_planning_defaults_are_bounded() -> None:
    config = PlanningConfig()
    assert config.decomposition.max_depth == 1
    assert config.decomposition.max_tasks == 5
    assert config.llm.maximum_calls_per_issue == 1
    assert config.llm.maximum_repair_calls == 0


def test_proposal_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ProposedTask.model_validate({"id": "x", "objective": "x", "invented": True})


def test_invalid_plan_cannot_be_approved() -> None:
    with pytest.raises(ValidationError, match="invalid plan"):
        CandidatePlan(
            planner_version="fake-v1",
            request="fix",
            request_hash="hash",
            repo=Path("."),
            commit_sha="sha",
            repository_map_version="repo-map-v1",
            decision=DecompositionDecision(
                recommended_parallelism=1,
                decision="single_task",
                reason="local change",
            ),
            tasks=[PlanTask(id="x", objective="x")],
            risk_level="low",
            validation=PlanValidationResult(valid=False, errors=["bad"]),
            approved=True,
            cache_key="key",
            planning_latency_seconds=0,
            planning_input_tokens=None,
            planning_output_tokens=None,
            planning_estimated_cost=None,
        )


def test_v01_issue_fields_load_but_new_plans_serialize_as_work_requests() -> None:
    plan = CandidatePlan.model_validate(
        {
            "planner_version": "fake-v1",
            "issue": "fix",
            "issue_hash": "hash",
            "repo": ".",
            "commit_sha": "sha",
            "repository_map_version": "repo-map-v1",
            "decision": {
                "recommended_parallelism": 1,
                "decision": "single_task",
                "reason": "local change",
            },
            "tasks": [{"id": "x", "objective": "x"}],
            "risk_level": "low",
            "validation": {"valid": True},
            "cache_key": "key",
        }
    )

    serialized = plan.model_dump(mode="json")
    assert plan.issue == "fix"
    assert plan.issue_hash == "hash"
    assert serialized["request"] == "fix"
    assert serialized["request_hash"] == "hash"
    assert "issue" not in serialized
