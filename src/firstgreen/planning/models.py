"""Strict planning records. LLM proposals are never executable by themselves."""

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class PlanningModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IssueState(StrEnum):
    RECEIVED = "received"
    REPO_SCANNING = "repo_scanning"
    PLANNING = "planning"
    PLAN_VALIDATION = "plan_validation"
    AWAITING_PLAN_APPROVAL = "awaiting_plan_approval"
    PLAN_APPROVED = "plan_approved"
    EXECUTION_READY = "execution_ready"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RepositoryModule(PlanningModel):
    name: str
    paths: list[str]
    depends_on: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)


class RepositoryFile(PlanningModel):
    path: str
    kind: Literal["source", "test", "migration", "config", "docs", "other"]
    symbols: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    tested_by: list[str] = Field(default_factory=list)
    api_routes: list[str] = Field(default_factory=list)


class RepositoryMap(PlanningModel):
    version: str = "repo-map-v2"
    repo: Path
    commit_sha: str
    modules: list[RepositoryModule] = Field(default_factory=list)
    files: list[RepositoryFile] = Field(default_factory=list)
    commands: dict[str, list[list[str]]] = Field(default_factory=dict)
    codeowners: dict[str, list[str]] = Field(default_factory=dict)
    cochange_groups: list[list[str]] = Field(default_factory=list)
    shared_resources: list[str] = Field(default_factory=list)
    truncated: bool = False


class DecompositionDecision(PlanningModel):
    recommended_parallelism: int = Field(ge=1, le=5)
    decision: Literal["single_task", "decompose"]
    reason: str
    relevant_paths: list[str] = Field(default_factory=list)


class ProposedTask(PlanningModel):
    id: str
    objective: str
    produces: list[str] = Field(default_factory=list)
    requires: list[str] = Field(default_factory=list)
    likely_paths: list[str] = Field(default_factory=list)
    verification_hints: list[str] = Field(default_factory=list)
    risk_tags: list[str] = Field(default_factory=list)
    uncertainty: str | None = None
    read_only: bool = False


class PlannerProposal(PlanningModel):
    planner_version: str
    decision: DecompositionDecision
    tasks: list[ProposedTask] = Field(min_length=1, max_length=5)
    external_artifacts: list[str] = Field(default_factory=list)
    call_count: int = Field(ge=0, le=1)
    input_tokens: int | None = Field(None, ge=0)
    output_tokens: int | None = Field(None, ge=0)
    estimated_cost: float | None = Field(None, ge=0)
    latency_seconds: float = Field(0, ge=0)


class ConflictConstraint(PlanningModel):
    task_a: str
    task_b: str
    constraint: Literal["exclusive_write", "shared_resource"]
    resource: str


class PlanTask(ProposedTask):
    dependencies: list[str] = Field(default_factory=list)
    verifier: list[list[str]] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    estimated_duration_seconds: float = Field(default=1.0, gt=0)
    estimate_source: Literal["unit", "deterministic_heuristic_v1", "merged"] = "unit"


class ParallelismAnalysis(PlanningModel):
    analysis_version: Literal["dag-performance-v1"] = "dag-performance-v1"
    estimated_work_seconds: float = Field(gt=0)
    estimated_span_seconds: float = Field(gt=0)
    critical_path: list[str] = Field(min_length=1)
    ready_width: int = Field(ge=1)
    exposed_parallelism: float = Field(ge=1)
    recommended_root_slots: int = Field(ge=1, le=5)
    recommendation_reason: str
    estimate_hash: str


class PlanValidationResult(PlanningModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    repairs: list[str] = Field(default_factory=list)


class CandidatePlan(PlanningModel):
    plan_version: Literal[1] = 1
    planner_version: str
    request: str = Field(validation_alias=AliasChoices("request", "issue"))
    request_hash: str = Field(validation_alias=AliasChoices("request_hash", "issue_hash"))
    repo: Path
    source_repo: Path | None = None
    repository_mode: Literal["clean", "head", "snapshot"] = "clean"
    dirty_entries: list[str] = Field(default_factory=list, max_length=20)
    commit_sha: str
    repository_map_version: str
    decision: DecompositionDecision
    tasks: list[PlanTask] = Field(min_length=1, max_length=5)
    parallelism_analysis: ParallelismAnalysis | None = None
    delivery_verifier: list[list[str]] = Field(default_factory=list)
    conflicts: list[ConflictConstraint] = Field(default_factory=list)
    external_artifacts: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"]
    validation: PlanValidationResult
    approved: bool = False
    user_edited: bool = False
    cache_key: str
    planning_latency_seconds: float = Field(0, ge=0)
    planning_input_tokens: int | None = Field(None, ge=0)
    planning_output_tokens: int | None = Field(None, ge=0)
    planning_estimated_cost: float | None = Field(None, ge=0)

    @property
    def issue(self) -> str:
        """Compatibility accessor for v0.1 plan consumers."""

        return self.request

    @property
    def issue_hash(self) -> str:
        """Compatibility accessor for v0.1 plan consumers."""

        return self.request_hash

    @model_validator(mode="after")
    def approval_requires_validity(self) -> "CandidatePlan":
        if self.approved and not self.validation.valid:
            raise ValueError("an invalid plan cannot be approved")
        return self


class ApprovedPlan(CandidatePlan):
    approved: Literal[True] = True
