"""Credential-free semantic planner fixtures for S1-S6, F1 and F2."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from firstgreen.planning.compiler import compile_plan
from firstgreen.planning.decomposition import decide_decomposition
from firstgreen.planning.models import (
    CandidatePlan,
    DecompositionDecision,
    PlannerProposal,
    ProposedTask,
    RepositoryMap,
)
from firstgreen.planning.planner import PlannerAdapter, PlannerCache, planner_cache_key
from firstgreen.planning.scanner import HeuristicRepositoryScanner
from firstgreen.planning.workflow import default_planning_config
from firstgreen.testbed.loaders import load_candidate_fixture, load_issue


def _task(
    task_id: str,
    objective: str,
    paths: list[str],
    *,
    produces: list[str],
    requires: list[str] | None = None,
    risks: list[str] | None = None,
    read_only: bool = False,
) -> ProposedTask:
    return ProposedTask(
        id=task_id,
        objective=objective,
        produces=produces,
        requires=requires or [],
        likely_paths=paths,
        verification_hints=["run deterministic TinyShop tests"],
        risk_tags=risks or [],
        read_only=read_only,
    )


def _proposal(
    decision: str,
    parallelism: int,
    reason: str,
    tasks: list[ProposedTask],
    relevant_paths: list[str] | None = None,
) -> PlannerProposal:
    return PlannerProposal(
        planner_version="tinyshop-fake-v1",
        decision=DecompositionDecision(
            decision=decision,  # type: ignore[arg-type]
            recommended_parallelism=parallelism,
            reason=reason,
            relevant_paths=relevant_paths
            or sorted({path for task in tasks for path in task.likely_paths}),
        ),
        tasks=tasks,
        call_count=0,
        input_tokens=None,
        output_tokens=None,
        estimated_cost=None,
        latency_seconds=0,
    )


def _s1() -> PlannerProposal:
    paths = ["app/orders/service.py", "tests/test_orders.py"]
    return _proposal(
        "single_task",
        1,
        "The implementation and regression tests are tightly coupled.",
        [
            _task(
                "pagination_fix",
                "Validate page size and add regression tests.",
                paths,
                produces=["pagination-fix"],
            )
        ],
        paths,
    )


def _s2() -> PlannerProposal:
    return _proposal(
        "decompose",
        2,
        "CLI and health changes have disjoint writes and a final verification barrier.",
        [
            _task(
                "cli_version",
                "Add the CLI version option.",
                ["app/cli.py", "tests/test_cli.py"],
                produces=["cli-version"],
            ),
            _task(
                "health_commit",
                "Add commit metadata to health.",
                ["app/main.py", "tests/test_health.py"],
                produces=["health-commit"],
            ),
            _task(
                "repository_verification",
                "Run final repository verification.",
                ["tests/test_cli.py", "tests/test_health.py"],
                produces=["verified-repository"],
                requires=["cli-version", "health-commit"],
                read_only=True,
            ),
        ],
    )


def _s3() -> PlannerProposal:
    risk = ["authentication-change"]
    return _proposal(
        "decompose",
        2,
        "Model/service and email form parallel branches before integration.",
        [
            _task(
                "reset_token_model",
                "Add reset token model.",
                ["app/models.py"],
                produces=["reset-token-schema"],
                risks=risk,
            ),
            _task(
                "reset_service",
                "Implement password reset service.",
                ["app/auth/service.py"],
                produces=["password-reset-service"],
                requires=["reset-token-schema"],
                risks=risk,
            ),
            _task(
                "reset_email",
                "Add reset email content.",
                ["app/mailer.py"],
                produces=["password-reset-email"],
                risks=risk,
            ),
            _task(
                "reset_integration",
                "Integrate reset routes and tests.",
                ["app/auth/routes.py", "tests/test_password_reset.py"],
                produces=["reset-integration"],
                requires=["password-reset-service", "password-reset-email"],
                risks=risk,
            ),
        ],
    )


def _s4() -> PlannerProposal:
    paths = ["app/auth/routes.py", "tests/test_auth.py"]
    return _proposal(
        "decompose",
        1,
        "Semantic units share an exclusive app/auth write resource.",
        [
            _task("login_audit", "Audit successful login.", paths, produces=["login-audit"]),
            _task(
                "reset_audit", "Audit successful password reset.", paths, produces=["reset-audit"]
            ),
        ],
    )


def _s5() -> PlannerProposal:
    return _proposal(
        "decompose",
        2,
        "Status and email can start independently before integration.",
        [
            _task(
                "cancelled_status",
                "Add cancelled order state.",
                ["app/models.py"],
                produces=["cancelled-order-state"],
            ),
            _task(
                "cancellation_service",
                "Implement cancellation rules.",
                ["app/orders/service.py"],
                produces=["order-cancellation-service"],
                requires=["cancelled-order-state"],
            ),
            _task(
                "cancellation_email",
                "Add cancellation email.",
                ["app/mailer.py"],
                produces=["cancellation-email"],
            ),
            _task(
                "cancellation_integration",
                "Integrate cancellation route and tests.",
                ["app/orders/routes.py", "tests/test_orders.py"],
                produces=["cancellation-integration"],
                requires=["order-cancellation-service", "cancellation-email"],
            ),
        ],
    )


def _s6() -> PlannerProposal:
    risks = ["database-migration", "destructive-schema-change"]
    return _proposal(
        "decompose",
        1,
        "Destructive schema work is bounded but always requires human approval.",
        [
            _task(
                "legacy_schema_migration",
                "Remove the persisted legacy token with a reversible migration.",
                ["app/models.py", "migrations/001_remove_legacy_token.py"],
                produces=["user-schema-v2"],
                risks=risks,
            ),
            _task(
                "legacy_reference_cleanup",
                "Remove application references and verify existing users.",
                ["app/auth/service.py", "tests/test_models.py"],
                produces=["legacy-token-removed"],
                requires=["user-schema-v2"],
                risks=risks,
            ),
        ],
    )


SCENARIO_PROPOSALS: dict[str, Callable[[], PlannerProposal]] = {
    "S1": _s1,
    "S2": _s2,
    "S3": _s3,
    "S4": _s4,
    "S5": _s5,
    "S6": _s6,
}


def fake_proposal(scenario: str) -> PlannerProposal:
    try:
        return SCENARIO_PROPOSALS[scenario]()
    except KeyError as error:
        if scenario not in {"F1", "F2"}:
            raise ValueError(f"unknown planning scenario: {scenario}") from error
    fixture_name = (
        "cyclic_candidate_plan.json"
        if scenario == "F1"
        else "coordination_only_candidate_plan.json"
    )
    fixture = load_candidate_fixture(fixture_name)
    return _proposal(
        fixture.decision,
        min(5, fixture.recommended_parallelism),
        fixture.reason,
        fixture.tasks,
        ["app/main.py", "tests/test_health.py"],
    )


@dataclass
class ScenarioPlannerAdapter:
    """Bounded planner adapter used through the same contract as a live planner."""

    scenario: str
    version: str = "tinyshop-fake-v1"
    calls: int = 0

    def propose(
        self,
        issue: str,
        repo_map: RepositoryMap,
        decision: DecompositionDecision,
        *,
        max_tasks: int,
    ) -> PlannerProposal:
        del issue, repo_map, decision
        if self.calls >= 1:
            raise RuntimeError("testbed planner call budget exhausted")
        self.calls += 1
        proposal = fake_proposal(self.scenario)
        if len(proposal.tasks) > max_tasks:
            raise ValueError("testbed planner exceeded maximum task count")
        return proposal.model_copy(update={"call_count": 1})


def compile_scenario(
    scenario: str,
    repo: Path,
    planner: PlannerAdapter | None = None,
    planner_cache: PlannerCache | None = None,
) -> CandidatePlan:
    config = default_planning_config()
    scan_config = config.repository_scan.model_copy(update={"include_git_history": False})
    repo_map = HeuristicRepositoryScanner().scan(repo, scan_config)
    issue = (
        load_issue(scenario)
        if scenario.startswith("S")
        else f"Reject and safely repair fake scenario {scenario}."
    )
    selected_planner = planner or ScenarioPlannerAdapter(scenario)
    decision = decide_decomposition(issue, repo_map)
    cache_key = planner_cache_key(
        issue,
        repo_map.commit_sha,
        selected_planner.version,
        {
            "scenario": scenario,
            "max_tasks": config.decomposition.max_tasks,
            "decomposition": config.decomposition.model_dump(mode="json"),
            "planner_model": getattr(selected_planner, "model", None),
            "planner_reasoning_effort": getattr(selected_planner, "reasoning_effort", None),
            "planner_binary": getattr(selected_planner, "binary", None),
        },
    )
    proposal = planner_cache.load(cache_key) if planner_cache is not None else None
    if proposal is None:
        proposal = selected_planner.propose(
            issue,
            repo_map,
            decision,
            max_tasks=config.decomposition.max_tasks,
        )
        if planner_cache is not None:
            planner_cache.save(cache_key, proposal)
    return compile_plan(
        issue,
        proposal,
        repo_map,
        config.decomposition,
        cache_key,
    )
