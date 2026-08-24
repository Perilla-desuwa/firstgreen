"""Strict manifest schema and DAG validation."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectConfig(StrictModel):
    repo: Path
    base_ref: str = "HEAD"


class CommandConfig(StrictModel):
    argv: list[str] | None = Field(None, min_length=1)
    command: str | None = None
    shell: bool = False

    @model_validator(mode="after")
    def exactly_one_command(self) -> "CommandConfig":
        if (self.argv is None) == (self.command is None):
            raise ValueError("provide exactly one of argv or command")
        if self.command is not None and not self.shell:
            raise ValueError("string command requires shell: true")
        return self


class VerifyConfig(StrictModel):
    commands: list[CommandConfig] = Field(min_length=1)
    allowed_changed_paths: list[str] = Field(default_factory=list)


class TaskLimits(StrictModel):
    max_attempts: int = Field(2, ge=1)
    max_estimated_usd: float | None = Field(None, ge=0)


class ResourceConfig(StrictModel):
    key: str
    capacity: int = Field(1, ge=1)


class TaskConfig(StrictModel):
    id: str
    task_class: str = "general"
    priority: int = 0
    estimated_duration_seconds: float = Field(default=1.0, gt=0)
    estimate_source: str = "unit"
    prompt: str
    replay_safe: bool = False
    dependencies: list[str] = Field(default_factory=list)
    resources: list[ResourceConfig] = Field(default_factory=list)
    limits: TaskLimits = TaskLimits(max_attempts=2, max_estimated_usd=None)
    verify: VerifyConfig


class ConcurrencyConfig(StrictModel):
    mode: Literal["static", "auto"] = "static"
    min_root: int = Field(1, ge=1)
    max_root: int = Field(1, ge=1)
    initial_root: int = Field(1, ge=1)
    total_agent_thread_budget: int = Field(1, ge=1)
    verifier_slots: int = Field(1, ge=1)
    control_window_seconds: int = Field(60, ge=1)
    cooldown_seconds: int = Field(120, ge=0)

    @model_validator(mode="after")
    def valid_limits(self) -> "ConcurrencyConfig":
        if not self.min_root <= self.initial_root <= self.max_root:
            raise ValueError("concurrency requires min_root <= initial_root <= max_root")
        if self.total_agent_thread_budget < self.max_root:
            raise ValueError("thread budget cannot be smaller than max_root")
        return self


class HedgeConfig(StrictModel):
    enabled: bool = False
    quantile: float = Field(0.9, gt=0, le=1)
    min_samples: int = Field(10, ge=1)
    fallback_after_seconds: float | None = Field(None, gt=0)
    max_replicas: int = Field(1, ge=0, le=1)
    cancel_loser: bool = True


class BudgetConfig(StrictModel):
    max_run_estimated_usd: float | None = Field(None, ge=0)
    max_hedge_estimated_usd: float | None = Field(None, ge=0)


class SchedulerConfig(StrictModel):
    objective: Literal["p95_time_to_verified"] = "p95_time_to_verified"
    ready_queue_policy: Literal["stable", "critical_path"] = "stable"
    concurrency: ConcurrencyConfig
    hedge: HedgeConfig = HedgeConfig(
        enabled=False,
        quantile=0.9,
        min_samples=10,
        fallback_after_seconds=None,
        max_replicas=1,
        cancel_loser=True,
    )
    budgets: BudgetConfig = BudgetConfig(max_run_estimated_usd=None, max_hedge_estimated_usd=None)


class AgentDefaults(StrictModel):
    adapter: Literal["fake", "codex_exec"] = "fake"
    codex_binary: str = Field("codex", min_length=1)
    sandbox: Literal["read-only", "workspace-write", "danger-full-access"] = "workspace-write"
    network_access: bool = False
    capture_sensitive_events: bool = False
    timeout_seconds: int = Field(3600, ge=1)
    max_subagent_threads: int = Field(1, ge=0)
    disabled_features: list[str] = Field(default_factory=lambda: ["code_mode", "code_mode_host"])
    config: dict[str, object] = Field(default_factory=dict)


class VerificationDefaults(StrictModel):
    all_must_pass: bool = True
    command_timeout_seconds: int = Field(900, ge=1)
    max_output_bytes: int = Field(2_000_000, ge=1)
    delivery_commands: list[CommandConfig] = Field(default_factory=list)
    executable_overrides: dict[str, str] = Field(default_factory=dict)
    environment_snapshot: dict[str, object] | None = None

    @model_validator(mode="after")
    def absolute_executable_overrides(self) -> "VerificationDefaults":
        for alias, target in self.executable_overrides.items():
            if not alias.strip() or Path(alias).name != alias:
                raise ValueError("verifier executable override keys must be bare command names")
            if not Path(target).expanduser().is_absolute():
                raise ValueError("verifier executable override paths must be absolute")
        return self


class WorkspaceConfig(StrictModel):
    root: Path = Path(".firstgreen/worktrees")
    keep_winner: bool = True
    keep_failed_seconds: int = Field(86400, ge=0)
    keep_cancelled_seconds: int = Field(3600, ge=0)


class RepositoryViewConfig(StrictModel):
    source_repo: Path
    execution_repo: Path
    base_sha: str
    mode: Literal["clean", "head", "snapshot"]
    dirty_entries: list[str] = Field(default_factory=list, max_length=20)


def _default_language_profiles() -> list[Literal["python", "generic"]]:
    return ["python", "generic"]


class RepositoryScanConfig(StrictModel):
    language_profiles: list[Literal["python", "generic"]] = Field(
        default_factory=_default_language_profiles
    )
    include_git_history: bool = True
    max_history_commits: int = Field(500, ge=0, le=5000)
    max_repo_map_tokens: int = Field(20_000, ge=1000)
    max_files: int = Field(2000, ge=10, le=100_000)


class DecompositionConfig(StrictModel):
    max_depth: Literal[1] = 1
    max_tasks: int = Field(5, ge=1, le=5)
    minimum_expected_task_seconds: int = Field(180, ge=0)
    maximum_write_overlap: float = Field(0.35, ge=0, le=1)
    allow_single_task_fallback: bool = True


class PlannerLLMConfig(StrictModel):
    enabled: bool = True
    provider: Literal["codex", "fake"] = "codex"
    model: str = "auto"
    maximum_calls_per_issue: Literal[1] = 1
    maximum_repair_calls: Literal[0, 1] = 0
    cache: bool = True
    planner_budget: float | None = Field(None, ge=0)


class PlanApprovalConfig(StrictModel):
    require_human: bool = True
    allow_low_risk_auto_approval: bool = False


class PlanningRiskConfig(StrictModel):
    require_manual_approval: list[str] = Field(
        default_factory=lambda: [
            "database-migration",
            "deployment",
            "security-policy",
            "external-side-effect",
        ]
    )


class PlanningConfig(StrictModel):
    mode: Literal["none", "auto", "existing"] = "auto"
    repository_scan: RepositoryScanConfig = RepositoryScanConfig(
        language_profiles=["python", "generic"],
        include_git_history=True,
        max_history_commits=500,
        max_repo_map_tokens=20_000,
        max_files=2000,
    )
    decomposition: DecompositionConfig = DecompositionConfig(
        max_depth=1,
        max_tasks=5,
        minimum_expected_task_seconds=180,
        maximum_write_overlap=0.35,
        allow_single_task_fallback=True,
    )
    llm: PlannerLLMConfig = PlannerLLMConfig(
        enabled=True,
        provider="codex",
        model="auto",
        maximum_calls_per_issue=1,
        maximum_repair_calls=0,
        cache=True,
        planner_budget=None,
    )
    approval: PlanApprovalConfig = PlanApprovalConfig(
        require_human=True, allow_low_risk_auto_approval=False
    )
    risk: PlanningRiskConfig = PlanningRiskConfig(
        require_manual_approval=[
            "database-migration",
            "deployment",
            "security-policy",
            "external-side-effect",
        ]
    )


class Manifest(StrictModel):
    version: Literal[1]
    project: ProjectConfig
    scheduler: SchedulerConfig
    agent_defaults: AgentDefaults
    verification_defaults: VerificationDefaults
    workspace: WorkspaceConfig
    repository_view: RepositoryViewConfig | None = None
    planning: PlanningConfig | None = None
    planning_record: dict[str, object] | None = None
    tasks: list[TaskConfig]

    @model_validator(mode="after")
    def valid_dag(self) -> "Manifest":
        ids = [task.id for task in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("task ids must be unique")
        graph = {task.id: task.dependencies for task in self.tasks}
        unknown = {dep for deps in graph.values() for dep in deps if dep not in graph}
        if unknown:
            raise ValueError(f"unknown dependencies: {sorted(unknown)}")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise ValueError(f"dependency cycle contains {node}")
            if node in visited:
                return
            visiting.add(node)
            for dependency in graph[node]:
                visit(dependency)
            visiting.remove(node)
            visited.add(node)

        for task_id in graph:
            visit(task_id)
        return self


def load_manifest(path: Path) -> Manifest:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Manifest.model_validate(data)
