"""Planning orchestration, persistence, approval and compilation to scheduler manifests."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from firstgreen.clock import Clock, SystemClock
from firstgreen.config import (
    AgentDefaults,
    BudgetConfig,
    CommandConfig,
    ConcurrencyConfig,
    HedgeConfig,
    Manifest,
    PlanningConfig,
    ProjectConfig,
    RepositoryViewConfig,
    ResourceConfig,
    SchedulerConfig,
    TaskConfig,
    TaskLimits,
    VerificationDefaults,
    VerifyConfig,
    WorkspaceConfig,
)
from firstgreen.db.repository import SQLiteRepository
from firstgreen.ids import new_id
from firstgreen.planning.compiler import can_auto_approve, compile_plan, validate_plan
from firstgreen.planning.decomposition import decide_decomposition
from firstgreen.planning.models import (
    ApprovedPlan,
    CandidatePlan,
    DecompositionDecision,
    IssueState,
    PlannerProposal,
    PlanTask,
    ProposedTask,
)
from firstgreen.planning.parallelism import analyze_parallelism
from firstgreen.planning.planner import FakePlanner, PlannerAdapter, PlannerCache, planner_cache_key
from firstgreen.planning.scanner import HeuristicRepositoryScanner, RepositoryScanner
from firstgreen.planning.state_machine import require_planning_transition
from firstgreen.work_requests import WorkRequest


@dataclass(frozen=True)
class PlanningOutcome:
    request_id: str
    plan_id: str
    plan: CandidatePlan
    cache_hit: bool


class PlanningEngine:
    def __init__(
        self,
        state_dir: Path,
        *,
        scanner: RepositoryScanner | None = None,
        planner: PlannerAdapter | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.state_dir = state_dir.resolve()
        self.repository = SQLiteRepository(self.state_dir / "state.db")
        self.repository.initialize()
        self.scanner = scanner or HeuristicRepositoryScanner()
        self.planner = planner or FakePlanner()
        self.clock = clock or SystemClock()

    def _transition(self, request_id: str, current: IssueState, new: IssueState) -> IssueState:
        require_planning_transition(current, new)
        timestamp = self.clock.now().isoformat()
        with self.repository.transaction() as connection:
            cursor = connection.execute(
                "UPDATE planning_requests SET state=?,updated_at=? WHERE id=? AND state=?",
                (new.value, timestamp, request_id, current.value),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("planning state compare-and-set failed")
        self.repository.append_event(
            new_id("event"),
            "planning.state_changed",
            timestamp,
            {"planning_request_id": request_id, "from": current.value, "to": new.value},
        )
        return new

    def plan_request(
        self,
        request: WorkRequest,
        config: PlanningConfig,
        *,
        mode: str = "auto",
        allow_paths: tuple[str, ...] = (),
        deny_paths: tuple[str, ...] = (),
    ) -> PlanningOutcome:
        """Plan a normalized request without coupling the engine to an issue tracker."""

        outcome = self.plan_issue(
            request.content,
            request.repository,
            config,
            mode=mode,
            allow_paths=allow_paths,
            deny_paths=deny_paths,
            request_source=request.source.model_dump(mode="json"),
        )
        source_repo = request.source_repository or request.repository
        plan = outcome.plan.model_copy(
            update={
                "source_repo": source_repo,
                "repository_mode": request.repository_mode,
                "dirty_entries": request.dirty_entries,
            }
        )
        with self.repository.transaction() as connection:
            connection.execute(
                "UPDATE candidate_plans SET plan_json=? WHERE id=?",
                (plan.model_dump_json(), outcome.plan_id),
            )
        return PlanningOutcome(outcome.request_id, outcome.plan_id, plan, outcome.cache_hit)

    def plan_issue(
        self,
        issue: str,
        repo: Path,
        config: PlanningConfig,
        *,
        mode: str = "auto",
        allow_paths: tuple[str, ...] = (),
        deny_paths: tuple[str, ...] = (),
        request_source: dict[str, object] | None = None,
    ) -> PlanningOutcome:
        started = self.clock.now()
        request_id = new_id("planning")
        issue_hash = hashlib.sha256(issue.encode()).hexdigest()
        snapshot = config.model_dump(mode="json")
        if request_source is not None:
            snapshot["work_request_source"] = request_source
        now = started.isoformat()
        with self.repository.transaction() as connection:
            connection.execute(
                "INSERT INTO planning_requests(id,issue_hash,issue_text,repo_path,commit_sha,state,"
                "config_snapshot,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    request_id,
                    issue_hash,
                    issue,
                    str(repo.resolve()),
                    "",
                    IssueState.RECEIVED.value,
                    json.dumps(snapshot, sort_keys=True),
                    now,
                    now,
                ),
            )
        state = self._transition(request_id, IssueState.RECEIVED, IssueState.REPO_SCANNING)
        repo_map = self.scanner.scan(repo, config.repository_scan)
        with self.repository.transaction() as connection:
            connection.execute(
                "UPDATE planning_requests SET repo_path=?,commit_sha=?,updated_at=? WHERE id=?",
                (
                    str(repo_map.repo),
                    repo_map.commit_sha,
                    self.clock.now().isoformat(),
                    request_id,
                ),
            )
            connection.execute(
                "INSERT INTO repository_maps(id,planning_request_id,map_version,map_json,"
                "created_at) "
                "VALUES(?,?,?,?,?)",
                (
                    new_id("repo_map"),
                    request_id,
                    repo_map.version,
                    repo_map.model_dump_json(),
                    now,
                ),
            )
        state = self._transition(request_id, state, IssueState.PLANNING)
        decision = (
            DecompositionDecision(
                recommended_parallelism=1,
                decision="single_task",
                reason="Planning mode none preserves the issue as one execution task.",
            )
            if mode == "none"
            else decide_decomposition(issue, repo_map)
        )
        key = planner_cache_key(
            issue,
            repo_map.commit_sha,
            self.planner.version,
            {
                "max_tasks": config.decomposition.max_tasks,
                "mode": mode,
                "allow_paths": allow_paths,
                "deny_paths": deny_paths,
                "model": config.llm.model,
                "input_model": "work-request-v1",
            },
        )
        cache = PlannerCache(self.state_dir / "planner-cache")
        proposal = cache.load(key) if config.llm.cache else None
        cache_hit = proposal is not None
        if proposal is None and (
            not config.llm.enabled
            or (decision.decision == "single_task" and config.llm.provider == "fake")
        ):
            proposal = PlannerProposal(
                planner_version="small-task-bypass-v1",
                decision=decision,
                tasks=[
                    ProposedTask(
                        id="request",
                        objective=issue,
                        likely_paths=decision.relevant_paths,
                        verification_hints=["run repository verifier"],
                    )
                ],
                call_count=0,
                input_tokens=None,
                output_tokens=None,
                estimated_cost=0,
                latency_seconds=0,
            )
        if proposal is None and config.llm.planner_budget == 0:
            safe_decision = decision.model_copy(
                update={
                    "decision": "single_task",
                    "recommended_parallelism": 1,
                    "reason": "Planner budget is zero; using deterministic single-task bypass.",
                }
            )
            proposal = PlannerProposal(
                planner_version="budget-bypass-v1",
                decision=safe_decision,
                tasks=[
                    ProposedTask(
                        id="request",
                        objective=issue,
                        likely_paths=safe_decision.relevant_paths,
                        verification_hints=["run repository verifier"],
                    )
                ],
                call_count=0,
                input_tokens=None,
                output_tokens=None,
                estimated_cost=0,
                latency_seconds=0,
            )
        planner_failed = False
        if proposal is None:
            try:
                proposal = self.planner.propose(
                    issue,
                    repo_map,
                    decision,
                    max_tasks=config.decomposition.max_tasks,
                )
            except (ValueError, RuntimeError) as error:
                planner_failed = True
                error_type = type(error).__name__
                self.repository.append_event(
                    new_id("event"),
                    "planning.planner_failed",
                    self.clock.now().isoformat(),
                    {
                        "planning_request_id": request_id,
                        "planner_version": self.planner.version,
                        "error_type": error_type,
                        "fallback": "single_task",
                    },
                )
                safe_decision = decision.model_copy(
                    update={
                        "decision": "single_task",
                        "recommended_parallelism": 1,
                        "reason": (
                            f"Planner failed ({error_type}); using deterministic single-task "
                            "fallback. No planner error was treated as an approved plan."
                        ),
                    }
                )
                proposal = PlannerProposal(
                    planner_version="deterministic-fallback-v1",
                    decision=safe_decision,
                    tasks=[
                        ProposedTask(
                            id="request",
                            objective=issue,
                            likely_paths=safe_decision.relevant_paths,
                            verification_hints=["run repository verifier"],
                            uncertainty=(
                                f"Planner unavailable ({error_type}); review the fallback boundary "
                                "before approval."
                            ),
                        )
                    ],
                    call_count=0,
                    input_tokens=None,
                    output_tokens=None,
                    estimated_cost=None,
                    latency_seconds=0,
                )
            if config.llm.cache and not planner_failed:
                cache.save(key, proposal)
        state = self._transition(request_id, state, IssueState.PLAN_VALIDATION)
        plan = compile_plan(
            issue,
            proposal,
            repo_map,
            config.decomposition,
            key,
            allow_paths=allow_paths,
            deny_paths=deny_paths,
        )
        elapsed = (self.clock.now() - started).total_seconds()
        plan = plan.model_copy(update={"planning_latency_seconds": elapsed})
        plan_id = new_id("plan")
        with self.repository.transaction() as connection:
            connection.execute(
                "INSERT INTO candidate_plans(id,planning_request_id,planner_version,cache_key,"
                "plan_json,approved,user_edited,planning_latency_seconds,input_tokens,output_tokens,"
                "estimated_cost,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    plan_id,
                    request_id,
                    plan.planner_version,
                    key,
                    plan.model_dump_json(),
                    0,
                    0,
                    plan.planning_latency_seconds,
                    plan.planning_input_tokens,
                    plan.planning_output_tokens,
                    plan.planning_estimated_cost,
                    self.clock.now().isoformat(),
                ),
            )
            connection.execute(
                "INSERT INTO plan_validation_results(id,candidate_plan_id,valid,result_json,"
                "created_at) VALUES(?,?,?,?,?)",
                (
                    new_id("validation"),
                    plan_id,
                    int(plan.validation.valid),
                    plan.validation.model_dump_json(),
                    self.clock.now().isoformat(),
                ),
            )
        self._transition(request_id, state, IssueState.AWAITING_PLAN_APPROVAL)
        return PlanningOutcome(request_id, plan_id, plan, cache_hit)

    def approve(
        self,
        outcome: PlanningOutcome,
        config: PlanningConfig,
        *,
        policy_auto_approval: bool = False,
    ) -> ApprovedPlan:
        if policy_auto_approval and not can_auto_approve(outcome.plan, config.risk, allow=True):
            raise ValueError("plan is not eligible for low-risk auto-approval")
        if not outcome.plan.validation.valid:
            raise ValueError("invalid plan cannot be approved")
        approved = ApprovedPlan.model_validate(
            outcome.plan.model_copy(update={"approved": True}).model_dump(mode="json")
        )
        with self.repository.transaction() as connection:
            connection.execute(
                "UPDATE candidate_plans SET approved=1,plan_json=? WHERE id=?",
                (approved.model_dump_json(), outcome.plan_id),
            )
        self._transition(
            outcome.request_id,
            IssueState.AWAITING_PLAN_APPROVAL,
            IssueState.PLAN_APPROVED,
        )
        return approved

    def replace_candidate(
        self,
        outcome: PlanningOutcome,
        candidate: CandidatePlan,
        config: PlanningConfig,
        *,
        allow_paths: tuple[str, ...] = (),
        deny_paths: tuple[str, ...] = (),
    ) -> PlanningOutcome:
        """Revalidate and persist a user-edited candidate without changing planning state."""

        if candidate.repo.resolve() != outcome.plan.repo.resolve():
            raise ValueError("edited plan cannot change the target repository")
        if candidate.commit_sha != outcome.plan.commit_sha:
            raise ValueError("edited plan cannot change the approved base commit")
        repo_map = self.scanner.scan(candidate.repo, config.repository_scan)
        if repo_map.commit_sha != candidate.commit_sha:
            raise ValueError("repository HEAD changed while the plan was being edited")
        validation = validate_plan(
            candidate.tasks,
            candidate.conflicts,
            repo_map,
            candidate.external_artifacts,
            max_tasks=config.decomposition.max_tasks,
            allow_paths=allow_paths,
            deny_paths=deny_paths,
        ).model_copy(update={"repairs": candidate.validation.repairs})
        analysis = analyze_parallelism(candidate.tasks) if validation.valid else None
        decision = candidate.decision
        if analysis is not None:
            decision = decision.model_copy(
                update={"recommended_parallelism": analysis.recommended_root_slots}
            )
        edited = candidate.model_copy(
            update={
                "approved": False,
                "user_edited": True,
                "validation": validation,
                "parallelism_analysis": analysis,
                "decision": decision,
            }
        )
        timestamp = self.clock.now().isoformat()
        with self.repository.transaction() as connection:
            connection.execute(
                "UPDATE candidate_plans SET plan_json=?,user_edited=1 WHERE id=?",
                (edited.model_dump_json(), outcome.plan_id),
            )
            connection.execute(
                "INSERT INTO plan_validation_results(id,candidate_plan_id,valid,result_json,"
                "created_at) VALUES(?,?,?,?,?)",
                (
                    new_id("validation"),
                    outcome.plan_id,
                    int(validation.valid),
                    validation.model_dump_json(),
                    timestamp,
                ),
            )
        return PlanningOutcome(outcome.request_id, outcome.plan_id, edited, outcome.cache_hit)


def save_plan(plan: CandidatePlan, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(plan.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
    return path


def load_plan(path: Path) -> CandidatePlan:
    return CandidatePlan.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def validate_loaded_plan(plan: CandidatePlan, repo_map: object | None = None) -> bool:
    del repo_map
    return plan.validation.valid and bool(plan.tasks)


def _path_patterns(paths: list[str]) -> list[str]:
    patterns: list[str] = []
    for value in paths:
        normalized = value.replace("\\", "/").rstrip("/")
        patterns.append(normalized)
        if "." not in Path(normalized).name:
            patterns.append(f"{normalized}/**")
    return sorted(set(patterns))


def _transitive_task_paths(plan: ApprovedPlan, task_id: str) -> list[str]:
    """Allow a downstream verifier to see only its own and verified ancestor changes."""
    task_by_id = {task.id: task for task in plan.tasks}
    paths: set[str] = set()
    visited: set[str] = set()

    def collect(current: str) -> None:
        if current in visited:
            return
        visited.add(current)
        task = task_by_id[current]
        paths.update(task.likely_paths)
        for dependency in task.dependencies:
            collect(dependency)

    collect(task_id)
    return sorted(paths)


def render_worker_prompt(
    plan: ApprovedPlan,
    task: PlanTask,
    allowed_changed_paths: list[str],
    *,
    verifier_commands: list[list[str]] | None = None,
) -> str:
    peer_boundaries = [
        {
            "id": peer.id,
            "objective": peer.objective,
            "produces_exact_artifacts": peer.produces,
            "planned_writable_paths": peer.likely_paths,
        }
        for peer in plan.tasks
        if peer.id != task.id
    ]
    context = {
        "original_request": plan.request,
        "approved_task": {
            "id": task.id,
            "objective": task.objective,
            "produces_exact_artifacts": task.produces,
            "requires_exact_artifacts": task.requires,
            "dependencies": task.dependencies,
            "planned_writable_paths": task.likely_paths,
            "verification_allowed_changed_paths": allowed_changed_paths,
            "verification_hints": task.verification_hints,
            "scheduler_verifier_commands": verifier_commands or task.verifier,
            "risks": task.risk_tags,
            "uncertainty": task.uncertainty,
        },
        "peer_task_boundaries": peer_boundaries,
    }
    return (
        "Implement exactly one approved FirstGreen task in this isolated worktree. Preserve "
        "verified dependency changes already present. Peer task objectives and writable paths "
        "are explicit ownership boundaries: do not implement their deliverables in this task. "
        "Do not broaden the task, alter unrelated files, weaken tests, push, deploy, or perform "
        "irreversible external actions. The scheduler—not the worker—decides success by running "
        "the listed verifier commands.\n\n"
        f"Approved execution context:\n{json.dumps(context, indent=2, ensure_ascii=False)}"
    )


def plan_to_manifest(
    plan: ApprovedPlan,
    *,
    adapter: str,
    replay_safe: bool,
    policy: str = "auto",
) -> Manifest:
    current_analysis = analyze_parallelism(plan.tasks)
    if (
        plan.parallelism_analysis is not None
        and plan.parallelism_analysis.estimate_hash != current_analysis.estimate_hash
    ):
        raise ValueError("approved plan parallelism analysis is stale")
    recommended_parallelism = max(
        1,
        min(
            current_analysis.recommended_root_slots,
            len(plan.tasks),
        ),
    )
    parallelism = 1 if policy == "single" else recommended_parallelism
    tasks: list[TaskConfig] = []
    for task in plan.tasks:
        allowed_changed_paths = _path_patterns(_transitive_task_paths(plan, task.id))
        tasks.append(
            TaskConfig(
                id=task.id,
                task_class="planned",
                priority=0,
                estimated_duration_seconds=task.estimated_duration_seconds,
                estimate_source=task.estimate_source,
                prompt=render_worker_prompt(plan, task, allowed_changed_paths),
                replay_safe=replay_safe,
                dependencies=task.dependencies,
                resources=[ResourceConfig(key=value, capacity=1) for value in task.resources],
                limits=TaskLimits(max_attempts=3, max_estimated_usd=None),
                verify=VerifyConfig(
                    commands=[CommandConfig(argv=command) for command in task.verifier],
                    allowed_changed_paths=allowed_changed_paths,
                ),
            )
        )
    return Manifest(
        version=1,
        project=ProjectConfig(repo=plan.repo, base_ref=plan.commit_sha),
        scheduler=SchedulerConfig(
            objective="p95_time_to_verified",
            ready_queue_policy="critical_path",
            concurrency=ConcurrencyConfig(
                mode="auto" if policy == "auto" else "static",
                min_root=1,
                max_root=parallelism,
                initial_root=1 if policy == "auto" else parallelism,
                total_agent_thread_budget=max(1, parallelism),
                verifier_slots=max(1, min(2, parallelism)),
                control_window_seconds=60,
                cooldown_seconds=120,
            ),
            hedge=HedgeConfig(
                enabled=replay_safe,
                quantile=0.9,
                min_samples=10,
                fallback_after_seconds=900,
                max_replicas=1,
                cancel_loser=True,
            ),
            budgets=BudgetConfig(max_run_estimated_usd=None, max_hedge_estimated_usd=None),
        ),
        agent_defaults=AgentDefaults(
            adapter=adapter,  # type: ignore[arg-type]
            codex_binary="codex",
            sandbox="workspace-write",
            network_access=False,
            capture_sensitive_events=False,
            timeout_seconds=900,
            max_subagent_threads=1,
            disabled_features=["code_mode", "code_mode_host"],
            config={},
        ),
        verification_defaults=VerificationDefaults(
            all_must_pass=True,
            command_timeout_seconds=900,
            max_output_bytes=2_000_000,
            delivery_commands=[CommandConfig(argv=command) for command in plan.delivery_verifier],
        ),
        workspace=WorkspaceConfig(
            root=Path(".firstgreen/worktrees"),
            keep_winner=True,
            keep_failed_seconds=86400,
            keep_cancelled_seconds=3600,
        ),
        repository_view=RepositoryViewConfig(
            source_repo=plan.source_repo or plan.repo,
            execution_repo=plan.repo,
            base_sha=plan.commit_sha,
            mode=plan.repository_mode,
            dirty_entries=plan.dirty_entries,
        ),
        planning=None,
        planning_record={
            "planner_version": plan.planner_version,
            "cache_key": plan.cache_key,
            "decision": plan.decision.decision,
            "recommended_parallelism": plan.decision.recommended_parallelism,
            "parallelism_analysis": (current_analysis.model_dump(mode="json")),
            "risk_level": plan.risk_level,
            "task_count": len(plan.tasks),
            "planning_latency_seconds": plan.planning_latency_seconds,
            "planning_input_tokens": plan.planning_input_tokens,
            "planning_output_tokens": plan.planning_output_tokens,
            "planning_estimated_cost": plan.planning_estimated_cost,
            "source_repo": str(plan.source_repo or plan.repo),
            "execution_repo": str(plan.repo),
            "repository_mode": plan.repository_mode,
            "dirty_entries": plan.dirty_entries,
        },
        tasks=tasks,
    )


def default_planning_config(*, fake: bool = True) -> PlanningConfig:
    return PlanningConfig.model_validate(
        {
            "mode": "auto",
            "repository_scan": {},
            "decomposition": {},
            "llm": {"provider": "fake" if fake else "codex"},
            "approval": {"require_human": True},
            "risk": {},
        }
    )
