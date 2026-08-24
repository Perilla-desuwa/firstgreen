"""Credential-free testbed runner with explicit opt-in live modes."""

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import yaml

from firstgreen.db.repository import SQLiteRepository
from firstgreen.errors import FirstGreenError
from firstgreen.planning.compiler import can_auto_approve
from firstgreen.planning.models import CandidatePlan
from firstgreen.planning.planner import CodexPlannerAdapter, PlannerCache
from firstgreen.planning.workflow import default_planning_config
from firstgreen.testbed.execution import execute_scenario
from firstgreen.testbed.golden import compare_golden
from firstgreen.testbed.hedge import HedgeAttemptProfile, execute_hedge_scenario
from firstgreen.testbed.loaders import (
    TESTBED_REPORTS_ROOT,
    TESTBED_RUNTIME_ROOT,
    load_golden,
    load_hedge_fixtures,
    load_json_schema,
    validate_json_schema,
)
from firstgreen.testbed.models import (
    ExecutionResult,
    GoldenCheck,
    PlanningResult,
    ScenarioResult,
)
from firstgreen.testbed.repository import create_tinyshop_repository
from firstgreen.testbed.scenarios import compile_scenario

PLANNING_SCENARIOS = ("S1", "S2", "S3", "S4", "S5", "S6", "F1", "F2")
EXECUTION_SCENARIOS = {"S1", "S2", "S3"}
LIVE_PLANNING_SCENARIOS = {"S1", "S2", "S3", "S4", "S5", "S6"}
ALL_SCENARIOS = (*PLANNING_SCENARIOS, "H1")
LIVE_REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh")
MAX_LIVE_TASKS = 5
MIN_LIVE_TIMEOUT_SECONDS = 60
MAX_LIVE_TIMEOUT_SECONDS = 1800


def _planning_result(plan: CandidatePlan) -> PlanningResult:
    requires_human = (
        plan.risk_level == "high"
        or not can_auto_approve(plan, default_planning_config().risk, allow=True)
        and any(
            tag in default_planning_config().risk.require_manual_approval
            for task in plan.tasks
            for tag in task.risk_tags
        )
    )
    return PlanningResult(
        decision=plan.decision.decision,
        candidate_task_count=len(plan.tasks),
        approved_task_count=0 if requires_human else len(plan.tasks),
        recommended_parallelism=plan.decision.recommended_parallelism,
        validation_passed=plan.validation.valid,
        human_approval_required=requires_human,
    )


def _fallback_check(plan: CandidatePlan) -> GoldenCheck:
    violations: list[str] = []
    if not plan.validation.valid:
        violations.append("fallback plan is invalid")
    if len(plan.tasks) != 1 or plan.tasks[0].dependencies:
        violations.append("unsafe planner output did not collapse to one acyclic task")
    if not plan.validation.repairs:
        violations.append("planner repair was not recorded")
    return GoldenCheck(passed=not violations, violations=violations)


def _usage_metrics(state_dir: Path, run_id: str) -> dict[str, int | float | None]:
    tokens = 0
    usage_reported = False
    estimated_cost = 0.0
    cost_reported = False
    repository = SQLiteRepository(state_dir / "state.db")
    with repository.connect() as connection:
        payloads = connection.execute(
            "SELECT payload FROM events WHERE run_id=?", (run_id,)
        ).fetchall()
    for row in payloads:
        value = json.loads(str(row[0]))
        if not isinstance(value, dict):
            continue
        usage = value.get("usage")
        if isinstance(usage, dict):
            usage_reported = True
            total = usage.get("total_tokens")
            if isinstance(total, int):
                tokens += total
            else:
                tokens += sum(
                    int(item)
                    for key, item in usage.items()
                    if isinstance(item, int)
                    and str(key).lower() in {"input_tokens", "output_tokens"}
                )
        elif isinstance(value.get("tokens"), int):
            usage_reported = True
            tokens += int(value["tokens"])
        for key in ("estimated_cost_usd", "cost_usd"):
            if isinstance(value.get(key), int | float):
                cost_reported = True
                estimated_cost += float(value[key])
    return {
        "reported_tokens": tokens if usage_reported else None,
        "reported_cost_usd": estimated_cost if cost_reported else None,
    }


def _write_plan(plan: CandidatePlan, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(plan.model_dump(mode="json"), sort_keys=False), encoding="utf-8")


def _write_reports(results: list[ScenarioResult], reports_dir: Path) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "plans").mkdir(exist_ok=True)
    (reports_dir / "timelines").mkdir(exist_ok=True)
    schema = load_json_schema("result_record.schema.json")
    lines: list[str] = []
    for result in results:
        raw = result.model_dump(mode="json")
        validate_json_schema(raw, schema, f"result[{result.scenario}]")
        lines.append(json.dumps(raw, sort_keys=True))
        (reports_dir / "timelines" / f"{result.scenario}.json").write_text(
            json.dumps(result.timeline, indent=2, sort_keys=True), encoding="utf-8"
        )
    (reports_dir / "results.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    rows = [
        "# FirstGreen testbed summary",
        "",
        "| Scenario | Planning | Execution | Golden | Live planner | Live coding |",
        "|---|---|---|---|---|---|",
    ]
    for result in results:
        execution = (
            "not run"
            if result.execution is None
            else "passed"
            if result.execution.verified
            else "failed"
        )
        rows.append(
            f"| {result.scenario} | "
            f"{'passed' if result.planning.validation_passed else 'failed'} | "
            f"{execution} | {'passed' if result.golden_check.passed else 'failed'} | "
            f"{result.live_planner} | {result.live_coding} |"
        )
    rows.extend(
        [
            "",
            "Default results are credential-free. Live modes require both an explicit CLI flag",
            "and their documented environment variable; skipped live runs are never reported "
            "as passed.",
            "S6 is planning-only and is never executed by this runner.",
        ]
    )
    (reports_dir / "summary.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _profiles_for_fixture(case_id: str) -> dict[str, HedgeAttemptProfile]:
    if case_id == "fast_verified_hedge":
        return {
            "primary": HedgeAttemptProfile(2.0, True),
            "hedge": HedgeAttemptProfile(0.01, True),
        }
    return {
        "primary": HedgeAttemptProfile(1.5, True),
        "hedge": HedgeAttemptProfile(0.01, False),
    }


def _run_h1(runtime_dir: Path) -> ScenarioResult:
    attempts = 0
    wall = 0.0
    launched = 0
    winners: list[str] = []
    cancelled: list[str] = []
    timeline: list[dict[str, Any]] = []
    violations: list[str] = []
    for fixture in load_hedge_fixtures().scenarios:
        case_root = runtime_dir / fixture.id
        repo = create_tinyshop_repository(case_root, fixture.id)
        started = time.monotonic()
        outcome = asyncio.run(
            execute_hedge_scenario(
                repo,
                case_root / "state",
                _profiles_for_fixture(fixture.id),
            )
        )
        wall += time.monotonic() - started
        attempts += len(outcome.attempts)
        launched += int(len(outcome.attempts) > 1)
        winner = outcome.winner_role or "none"
        winners.append(winner)
        cancelled.extend(record.role for record in outcome.attempts if record.status == "cancelled")
        timeline.extend({"case": fixture.id, **entry} for entry in outcome.factory.timeline)
        if winner != fixture.expected_winner:
            violations.append(f"{fixture.id}: winner {winner!r} != {fixture.expected_winner!r}")
        if outcome.winner_count != 1:
            violations.append(f"{fixture.id}: expected exactly one transactional winner")
    return ScenarioResult(
        scenario="H1",
        planning=PlanningResult(
            decision="not_applicable",
            candidate_task_count=0,
            approved_task_count=0,
            recommended_parallelism=1,
            validation_passed=True,
            human_approval_required=False,
        ),
        execution=ExecutionResult(
            attempt_count=attempts,
            verified=not violations,
            wall_seconds=wall,
            maximum_observed_parallelism=2,
            hedges_launched=launched,
            winner=",".join(winners),
            cancelled=cancelled,
        ),
        golden_check=GoldenCheck(passed=not violations, violations=violations),
        timeline=timeline,
    )


def _run_planning_scenario(
    scenario: str,
    runtime_dir: Path,
    *,
    live_planner: bool,
    live_coding: bool,
    codex_binary: str,
    model: str | None,
    reasoning: str,
    live_timeout_seconds: int,
    max_live_tasks: int | None,
) -> ScenarioResult:
    repo = create_tinyshop_repository(runtime_dir, scenario)
    planner_status: Literal["not_requested", "skipped", "ran"] = "not_requested"
    planner = None
    cache = None
    if live_planner and scenario.startswith("S"):
        if os.getenv("FIRSTGREEN_RUN_LIVE_TESTBED_PLANNER") == "1":
            planner = CodexPlannerAdapter(
                runtime_dir / "planner-live",
                binary=codex_binary,
                model=model or "auto",
                reasoning_effort=reasoning,
                timeout_seconds=live_timeout_seconds,
            )
            cache = PlannerCache(runtime_dir / "planner-cache")
            planner_status = "ran"
        else:
            planner_status = "skipped"
    planner_failure: str | None = None
    try:
        plan = compile_scenario(scenario, repo, planner, cache)
    except (OSError, RuntimeError, ValueError) as error:
        if planner is None:
            raise
        planner_failure = type(error).__name__
        plan = compile_scenario(scenario, repo)
    _write_plan(plan, runtime_dir.parent.parent / "reports" / "plans" / f"{scenario}.yaml")
    check = (
        compare_golden(plan, load_golden(scenario))
        if scenario.startswith("S")
        else _fallback_check(plan)
    )
    if planner_failure is not None:
        check = check.model_copy(
            update={
                "passed": False,
                "violations": [
                    *check.violations,
                    f"live planner failed with {planner_failure}; fake fallback was not accepted",
                ],
            }
        )
    execution = None
    timeline: list[dict[str, Any]] = []
    coding_status: Literal["not_requested", "skipped", "ran"] = "not_requested"
    metrics: dict[str, Any] = {}
    if scenario in EXECUTION_SCENARIOS:
        use_live = live_coding and os.getenv("FIRSTGREEN_RUN_LIVE_TESTBED_CODING") == "1"
        if live_coding and not use_live:
            coding_status = "skipped"
        else:
            coding_status = "ran" if use_live else "not_requested"
            if use_live:
                metrics = {
                    "reported_tokens": None,
                    "reported_cost_usd": None,
                    "model": model,
                    "reasoning_effort": reasoning,
                    "task_limit": max_live_tasks,
                    "task_count": len(plan.tasks),
                    "attempt_limit_per_task": 1,
                    "timeout_seconds_per_attempt": live_timeout_seconds,
                    "hedging_enabled": False,
                    "delivery_verified": None,
                }
            started = time.monotonic()
            try:
                if use_live and (max_live_tasks is None or len(plan.tasks) > max_live_tasks):
                    raise ValueError(
                        f"live plan has {len(plan.tasks)} tasks but --max-live-tasks is "
                        f"{max_live_tasks!r}"
                    )
                outcome = asyncio.run(
                    execute_scenario(
                        scenario,
                        plan,
                        repo,
                        runtime_dir / "state",
                        adapter="codex_exec" if use_live else "fake",
                        use_fake_worker=not use_live,
                        codex_binary=codex_binary,
                        worker_model=model if use_live else None,
                        worker_reasoning=reasoning if use_live else None,
                        timeout_seconds=live_timeout_seconds if use_live else 900,
                    )
                )
                execution = outcome.result
                timeline = [dict(entry) for entry in outcome.timeline]
                metrics.update(_usage_metrics(outcome.state_dir, outcome.run_id))
                metrics.update(
                    {
                        "model": model if use_live else None,
                        "reasoning_effort": reasoning if use_live else None,
                        "task_limit": max_live_tasks if use_live else None,
                        "task_count": len(plan.tasks),
                        "attempt_limit_per_task": 1,
                        "timeout_seconds_per_attempt": (live_timeout_seconds if use_live else None),
                        "hedging_enabled": False,
                        "delivery_verified": outcome.delivery_verified,
                    }
                )
                main_unchanged = outcome.main_worktree_unchanged
            except (FirstGreenError, OSError, RuntimeError, ValueError) as error:
                execution = ExecutionResult(
                    attempt_count=0,
                    verified=False,
                    wall_seconds=time.monotonic() - started,
                    maximum_observed_parallelism=0,
                    hedges_launched=0,
                    winner=None,
                    cancelled=[],
                )
                check = check.model_copy(
                    update={
                        "passed": False,
                        "violations": [
                            *check.violations,
                            f"worker execution failed with {type(error).__name__}",
                        ],
                    }
                )
                main_unchanged = True
            if not main_unchanged:
                check = check.model_copy(
                    update={
                        "passed": False,
                        "violations": [*check.violations, "main worktree was modified"],
                    }
                )
    return ScenarioResult(
        scenario=scenario,
        planning=_planning_result(plan),
        execution=execution,
        golden_check=check,
        live_planner=planner_status,
        live_coding=coding_status,
        plan={**plan.model_dump(mode="json"), "execution_usage": metrics},
        timeline=timeline,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the FirstGreen synthetic testbed")
    parser.add_argument("--scenario", choices=("all", *ALL_SCENARIOS), default="all")
    parser.add_argument("--fake-planner", action="store_true")
    parser.add_argument("--fake-worker", action="store_true")
    parser.add_argument("--live-planner", action="store_true")
    parser.add_argument("--live-coding", action="store_true")
    parser.add_argument("--codex-binary", default=os.getenv("FIRSTGREEN_CODEX_BINARY", "codex"))
    parser.add_argument("--model", default=os.getenv("FIRSTGREEN_LIVE_MODEL"))
    parser.add_argument(
        "--reasoning",
        choices=LIVE_REASONING_EFFORTS,
        default=os.getenv("FIRSTGREEN_LIVE_REASONING", "low"),
    )
    parser.add_argument("--max-live-tasks", type=int)
    parser.add_argument("--live-timeout-seconds", type=int, default=900)
    parser.add_argument("--reports-dir", type=Path, default=TESTBED_REPORTS_ROOT)
    parser.add_argument("--runtime-dir", type=Path, default=TESTBED_RUNTIME_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.live_planner and args.fake_planner:
        raise SystemExit("choose either --live-planner or --fake-planner")
    if args.live_coding and args.fake_worker:
        raise SystemExit("choose either --live-coding or --fake-worker")
    if (args.live_planner or args.live_coding) and args.scenario == "all":
        raise SystemExit("live modes require exactly one explicit --scenario")
    if args.live_planner and args.scenario not in LIVE_PLANNING_SCENARIOS:
        raise SystemExit("live planning is limited to S1-S6")
    if args.live_coding and args.scenario not in EXECUTION_SCENARIOS:
        raise SystemExit("live coding is limited to S1, S2, or S3")
    if args.max_live_tasks is not None and not 1 <= args.max_live_tasks <= MAX_LIVE_TASKS:
        raise SystemExit(f"--max-live-tasks must be between 1 and {MAX_LIVE_TASKS}")
    if not MIN_LIVE_TIMEOUT_SECONDS <= args.live_timeout_seconds <= MAX_LIVE_TIMEOUT_SECONDS:
        raise SystemExit(
            "--live-timeout-seconds must be between "
            f"{MIN_LIVE_TIMEOUT_SECONDS} and {MAX_LIVE_TIMEOUT_SECONDS}"
        )
    live_planner_enabled = (
        args.live_planner and os.getenv("FIRSTGREEN_RUN_LIVE_TESTBED_PLANNER") == "1"
    )
    live_coding_enabled = (
        args.live_coding and os.getenv("FIRSTGREEN_RUN_LIVE_TESTBED_CODING") == "1"
    )
    if (live_planner_enabled or live_coding_enabled) and not args.model:
        raise SystemExit("an explicit --model is required before a paid live test")
    if live_coding_enabled and args.max_live_tasks is None:
        raise SystemExit("--max-live-tasks is required before a paid live coding test")
    reports_dir = args.reports_dir.resolve()
    run_root = (args.runtime_dir / f"run-{uuid4().hex[:8]}").resolve()
    run_root.mkdir(parents=True, exist_ok=False)
    selected = ALL_SCENARIOS if args.scenario == "all" else (args.scenario,)
    results: list[ScenarioResult] = []
    for scenario in selected:
        if scenario == "H1":
            result = _run_h1(run_root / scenario)
        else:
            result = _run_planning_scenario(
                scenario,
                run_root / scenario,
                live_planner=args.live_planner,
                live_coding=args.live_coding,
                codex_binary=args.codex_binary,
                model=args.model,
                reasoning=args.reasoning,
                live_timeout_seconds=args.live_timeout_seconds,
                max_live_tasks=args.max_live_tasks,
            )
        results.append(result)
    # Plans are initially staged beside the runtime to keep scenario helpers simple.
    staged_plans = run_root.parent / "reports" / "plans"
    (reports_dir / "plans").mkdir(parents=True, exist_ok=True)
    if staged_plans.exists():
        for plan in staged_plans.glob("*.yaml"):
            (reports_dir / "plans" / plan.name).write_text(
                plan.read_text(encoding="utf-8"), encoding="utf-8"
            )
    _write_reports(results, reports_dir)
    failures = [
        result.scenario
        for result in results
        if not result.planning.validation_passed
        or not result.golden_check.passed
        or (result.execution is not None and not result.execution.verified)
    ]
    print(f"reports: {reports_dir}")
    print(f"scenarios: {len(results) - len(failures)} passed, {len(failures)} failed")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
