"""Strict fixture and result models for the synthetic testbed."""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from firstgreen.planning.models import ProposedTask


class TestbedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IntegerRange(TestbedModel):
    min: int = Field(ge=0)
    max: int = Field(ge=0)


class GoldenExpectation(TestbedModel):
    scenario: str
    decision: str | None = None
    acceptable_decisions: list[str] = Field(default_factory=list)
    recommended_parallelism: IntegerRange | None = None
    task_count: IntegerRange | None = None
    risk_level: Literal["low", "medium", "high"] | None = None
    required_paths: list[str] = Field(default_factory=list)
    forbidden_patterns: list[str] = Field(default_factory=list)
    required_semantic_tasks: list[str] = Field(default_factory=list)
    forbidden_edges: list[tuple[str, str]] = Field(default_factory=list)
    required_final_barrier: bool = False
    required_artifacts: list[str] = Field(default_factory=list)
    required_relationships: list[tuple[str, str]] = Field(default_factory=list)
    requires_parallel_branch: bool = False
    requires_join: bool = False
    execution_allowed: bool
    required_conflict_resource: list[str] = Field(default_factory=list)
    forbid_concurrent_writes: bool = False
    required_risk_tags: list[str] = Field(default_factory=list)
    requires_human_approval: bool = False
    auto_approval: bool | None = None
    expected_state: str | None = None


class CandidateFixture(TestbedModel):
    decision: Literal["single_task", "decompose"]
    recommended_parallelism: int = Field(ge=1, le=8)
    reason: str = "deterministic test fixture"
    tasks: list[ProposedTask] = Field(min_length=1, max_length=5)


class HedgeAttemptFixture(TestbedModel):
    id: str
    start_at: int | Literal["hedge_threshold"] = Field(union_mode="left_to_right")
    duration_seconds: int = Field(gt=0)
    verification: Literal["pass", "fail"]


class HedgeScenarioFixture(TestbedModel):
    id: str
    hedge_after_seconds: int = Field(gt=0)
    attempts: list[HedgeAttemptFixture] = Field(min_length=2, max_length=2)
    expected_winner: str
    expected_cancelled: list[str]


class HedgeFixtures(TestbedModel):
    scenarios: list[HedgeScenarioFixture]


class ScenarioMetadata(TestbedModel):
    id: str
    issue_file: Path | None
    golden_file: Path | None
    planning_only: bool
    fake_execution: bool
    destructive: bool = False


class PlanningResult(TestbedModel):
    decision: str
    candidate_task_count: int = Field(ge=0)
    approved_task_count: int = Field(ge=0)
    recommended_parallelism: int = Field(ge=1)
    validation_passed: bool
    human_approval_required: bool


class ExecutionResult(TestbedModel):
    attempt_count: int = Field(ge=0)
    verified: bool
    wall_seconds: float = Field(ge=0)
    maximum_observed_parallelism: int = Field(ge=0)
    hedges_launched: int = Field(ge=0)
    winner: str | None = None
    cancelled: list[str] = Field(default_factory=list)


class GoldenCheck(TestbedModel):
    passed: bool
    violations: list[str]


class ScenarioResult(TestbedModel):
    scenario: str
    planning: PlanningResult
    execution: ExecutionResult | None
    golden_check: GoldenCheck
    live_planner: Literal["not_requested", "skipped", "ran"] = "not_requested"
    live_coding: Literal["not_requested", "skipped", "ran"] = "not_requested"
    plan: dict[str, Any] = Field(default_factory=dict)
    timeline: list[dict[str, Any]] = Field(default_factory=list)
