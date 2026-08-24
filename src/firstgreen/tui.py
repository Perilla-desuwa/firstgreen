"""Foreground terminal UI built on scheduler-owned persisted state."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from firstgreen.config import Manifest
from firstgreen.db.repository import SQLiteRepository
from firstgreen.planning.models import CandidatePlan
from firstgreen.reporting.export import run_data
from firstgreen.service import RunOutcome, SchedulerService

PlanAction = Literal["approve", "edit", "single", "cancel"]

STATUS_MARKS = {
    "verified": ("OK", "green"),
    "winner": ("OK", "green"),
    "completed": ("OK", "green"),
    "passed": ("OK", "green"),
    "running": (">>", "cyan"),
    "verifying": (">>", "yellow"),
    "starting": (">>", "cyan"),
    "ready": ("..", "blue"),
    "queued": ("..", "dim"),
    "blocked": ("!!", "red"),
    "failed": ("!!", "red"),
    "timed_out": ("!!", "red"),
    "cancelled": ("--", "dim"),
    "superseded": ("--", "dim"),
    "skipped": ("--", "dim"),
}


def default_console() -> Console:
    return Console(highlight=False)


def read_multiline_request(
    console: Console | None = None,
    *,
    reader: Callable[[str], str] | None = None,
) -> str:
    """Read a pasted request; a blank line or EOF submits it."""

    target = console or default_console()
    target.print("[bold green]Describe the change you want FirstGreen to make[/bold green]")
    target.print(
        "Paste one or more lines. A blank line submits the request. "
        "The repository is only scanned until you approve a plan.\n"
    )
    lines: list[str] = []
    read = reader or target.input
    while True:
        try:
            line = read("[green]>[/green] " if not lines else "[dim]...[/dim] ")
        except EOFError:
            break
        if not line.strip() and lines:
            break
        if line or lines:
            lines.append(line)
    return "\n".join(lines).strip()


def _command_text(command: list[str]) -> str:
    if not command:
        return "-"
    if os.name == "nt":
        return subprocess.list2cmdline(command)
    return shlex.join(command)


def _lines(values: list[str], *, empty: str = "-") -> str:
    return "\n".join(values) if values else empty


def plan_renderable(plan: CandidatePlan) -> RenderableType:
    """Render an approval-oriented plan with its executable DAG and safety bounds."""

    summary = Table.grid(expand=True)
    summary.add_column(style="bold", width=24)
    summary.add_column()
    summary.add_row("Source repository", str(plan.source_repo or plan.repo))
    if (plan.source_repo or plan.repo).resolve() != plan.repo.resolve():
        summary.add_row("Execution repository", str(plan.repo))
    summary.add_row("Repository mode", plan.repository_mode)
    summary.add_row("Base commit", plan.commit_sha[:12])
    summary.add_row("Decision", plan.decision.decision)
    summary.add_row("Tasks", str(len(plan.tasks)))
    summary.add_row("Recommended root slots", str(plan.decision.recommended_parallelism))
    if plan.parallelism_analysis is not None:
        analysis = plan.parallelism_analysis
        summary.add_row(
            "Estimated work / span",
            f"{analysis.estimated_work_seconds:.1f}s / {analysis.estimated_span_seconds:.1f}s",
        )
        summary.add_row("Exposed parallelism W/L", f"{analysis.exposed_parallelism:.3f}")
        summary.add_row("Ready width", str(analysis.ready_width))
        summary.add_row("Critical path", " → ".join(analysis.critical_path))
        summary.add_row("Slot recommendation", analysis.recommendation_reason)
    summary.add_row("Risk", plan.risk_level)
    summary.add_row("Reason", plan.decision.reason)

    tasks = Table(expand=True, box=None, padding=(0, 1))
    tasks.add_column("#", style="dim", width=3)
    tasks.add_column("Task", style="bold", ratio=1)
    tasks.add_column("Objective", ratio=3)
    tasks.add_column("Allowed write paths", ratio=2)
    tasks.add_column("Duration estimate", ratio=1)
    tasks.add_column("Risk / uncertainty", ratio=2)
    for index, task in enumerate(plan.tasks, start=1):
        risk = _lines(task.risk_tags)
        if task.uncertainty:
            risk = f"{risk}\n{task.uncertainty}" if task.risk_tags else task.uncertainty
        tasks.add_row(
            str(index),
            task.id,
            task.objective,
            "read-only" if task.read_only else _lines(task.likely_paths),
            f"{task.estimated_duration_seconds:.1f}s\n{task.estimate_source}",
            risk,
        )

    unlocks: dict[str, list[str]] = {task.id: [] for task in plan.tasks}
    for task in plan.tasks:
        for dependency in task.dependencies:
            unlocks.setdefault(dependency, []).append(task.id)
    dag = Table(expand=True, box=None, padding=(0, 1))
    dag.add_column("Task", style="bold")
    dag.add_column("Starts after")
    dag.add_column("Unlocks")
    dag.add_column("Conflict locks")
    for task in plan.tasks:
        dag.add_row(
            task.id,
            ", ".join(task.dependencies) or "start",
            ", ".join(unlocks.get(task.id, [])) or "end",
            _lines(task.resources),
        )

    verification = Table(expand=True, box=None, padding=(0, 1))
    verification.add_column("Task", style="bold")
    verification.add_column("Scheduler-owned verification")
    for task in plan.tasks:
        verification.add_row(task.id, _lines([_command_text(command) for command in task.verifier]))

    validation = Table.grid(expand=True)
    validation.add_column(style="bold", width=24)
    validation.add_column()
    validation.add_row(
        "Deterministic validation",
        Text(
            "VALID" if plan.validation.valid else "INVALID",
            style="green" if plan.validation.valid else "red",
        ),
    )
    validation.add_row("Approval", "Required before any worker starts")
    validation.add_row("Planner", plan.planner_version)
    validation.add_row("Planning time", f"{plan.planning_latency_seconds:.3f}s")
    if plan.conflicts:
        validation.add_row(
            "Conflicts",
            _lines(
                [
                    f"{item.task_a} / {item.task_b}: {item.constraint} on {item.resource}"
                    for item in plan.conflicts
                ]
            ),
        )
    if plan.validation.repairs:
        validation.add_row("Deterministic repairs", _lines(plan.validation.repairs))
    if plan.validation.warnings:
        validation.add_row("Warnings", _lines(plan.validation.warnings))
    if plan.validation.errors:
        validation.add_row("Errors", Text(_lines(plan.validation.errors), style="red"))

    return Panel(
        Group(
            Text(plan.request, style="bold"),
            Text(""),
            summary,
            Text("\nWork units", style="bold cyan"),
            tasks,
            Text("\nExecution DAG", style="bold cyan"),
            dag,
            Text("\nVerification gates", style="bold cyan"),
            verification,
            Text("\nSafety and approval", style="bold cyan"),
            validation,
        ),
        title="FirstGreen plan review",
        subtitle="Nothing has been executed yet",
    )


def print_plan(plan: CandidatePlan, console: Console | None = None) -> None:
    (console or default_console()).print(plan_renderable(plan))


def ask_plan_action(
    console: Console | None = None,
    *,
    reader: Callable[[str], str] | None = None,
) -> PlanAction:
    target = console or default_console()
    read = reader or target.input
    choices: dict[str, PlanAction] = {
        "a": "approve",
        "approve": "approve",
        "e": "edit",
        "edit": "edit",
        "s": "single",
        "single": "single",
        "c": "cancel",
        "cancel": "cancel",
    }
    target.print("Review the validated plan above. No worker has started yet.", style="bold")
    while True:
        answer = (
            read(
                "[a] approve and execute  [e] edit YAML and review again  "
                "[s] replace with one task  [c] cancel: "
            )
            .strip()
            .lower()
        )
        action = choices.get(answer)
        if action is not None:
            return action
        target.print("Choose a, e, s, or c. Execution requires an explicit choice.", style="yellow")


def _elapsed_seconds(run: dict[str, object], now: datetime) -> float:
    started = run.get("started_at") or run.get("created_at")
    if not isinstance(started, str):
        return 0.0
    try:
        parsed = datetime.fromisoformat(started)
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max(0.0, (now - parsed).total_seconds())


def _duration(value: float) -> str:
    total = int(value)
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _finished_elapsed(run: dict[str, object]) -> float:
    started = run.get("started_at") or run.get("created_at")
    finished = run.get("finished_at")
    if not isinstance(started, str) or not isinstance(finished, str):
        return 0.0
    try:
        start_time = datetime.fromisoformat(started)
        finish_time = datetime.fromisoformat(finished)
    except ValueError:
        return 0.0
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=UTC)
    if finish_time.tzinfo is None:
        finish_time = finish_time.replace(tzinfo=UTC)
    return max(0.0, (finish_time - start_time).total_seconds())


def _verification_command(raw: object) -> str:
    try:
        command = json.loads(str(raw))
    except (TypeError, ValueError):
        return str(raw)
    if not isinstance(command, dict):
        return str(raw)
    argv = command.get("argv")
    if isinstance(argv, list) and all(isinstance(item, str) for item in argv):
        return _command_text(argv)
    shell_command = command.get("command")
    return str(shell_command or "-")


def result_renderable(
    data: dict[str, Any],
    *,
    report_path: Path,
    manifest_path: Path,
    state_dir: Path,
) -> RenderableType:
    """Render scheduler-owned final evidence and actionable next steps."""

    run = dict(data["run"])
    tasks = [dict(item) for item in data["tasks"]]
    attempts = [dict(item) for item in data["attempts"]]
    verifications = [dict(item) for item in data["verifications"]]
    summary = dict(data["summary"])
    usage = dict(data.get("usage") or {})
    changes = dict(data.get("changes") or {})
    raw_delivery = data.get("delivery")
    delivery = dict(raw_delivery) if isinstance(raw_delivery, dict) else None
    delivery_verified = delivery is None or delivery.get("status") == "verified"
    verified = (
        run.get("status") == "completed"
        and summary.get("verified", 0) == len(tasks)
        and not summary.get("failed", 0)
        and delivery_verified
    )
    result_text = "VERIFIED" if verified else "NOT VERIFIED"
    result_style = "bold green" if verified else "bold red"

    overview = Table.grid(expand=True)
    overview.add_column(style="bold", width=22)
    overview.add_column()
    overview.add_row("Result", Text(result_text, style=result_style))
    overview.add_row("Run", str(run.get("id", "")))
    overview.add_row("Repository", str(run.get("repo_path", "")))
    overview.add_row("Base commit", str(run.get("base_sha", ""))[:12])
    if delivery is not None:
        overview.add_row(
            "Final delivery",
            f"{delivery.get('status', '')}: {delivery.get('workspace_path') or 'unavailable'}",
        )
    overview.add_row(
        "Tasks",
        f"{summary.get('verified', 0)}/{len(tasks)} verified; "
        f"{summary.get('failed', 0)} failed/blocked",
    )
    overview.add_row(
        "Attempts",
        f"{len(attempts)} total; {summary.get('hedges', 0)} hedge attempts",
    )
    overview.add_row("Elapsed", _duration(_finished_elapsed(run)))
    if usage.get("reported"):
        overview.add_row(
            "Worker usage",
            f"input {usage.get('input_tokens', 0):,}; "
            f"cached {usage.get('cached_input_tokens', 0):,}; "
            f"output {usage.get('output_tokens', 0):,}; "
            f"reasoning {usage.get('reasoning_output_tokens', 0):,}; "
            f"reported total {usage.get('total_tokens', 0):,}",
        )
    else:
        overview.add_row("Worker usage", "not reported by this adapter")

    attempt_table = Table(expand=True, box=None, padding=(0, 1))
    attempt_table.add_column("Task", style="bold")
    attempt_table.add_column("Role")
    attempt_table.add_column("Status")
    attempt_table.add_column("Attempt")
    attempt_table.add_column("Workspace")
    for attempt in attempts:
        status = str(attempt.get("status", ""))
        _mark, style = STATUS_MARKS.get(status, ("?", "white"))
        attempt_id = str(attempt.get("id", ""))
        attempt_table.add_row(
            str(attempt.get("task_key", "")),
            str(attempt.get("role", "")),
            Text(status, style=style),
            attempt_id,
            str(attempt.get("workspace_path", "")),
        )

    verification_table = Table(expand=True, box=None, padding=(0, 1))
    verification_table.add_column("Task", style="bold")
    verification_table.add_column("Round")
    verification_table.add_column("Command", ratio=4)
    verification_table.add_column("Status")
    verification_table.add_column("Exit")
    for verification in verifications:
        status = str(verification.get("status", ""))
        _mark, style = STATUS_MARKS.get(status, ("?", "white"))
        verification_table.add_row(
            str(verification.get("task_key", "")),
            str(verification.get("verification_round", "")),
            _verification_command(verification.get("command_json")),
            Text(status, style=style),
            "-" if verification.get("exit_code") is None else str(verification["exit_code"]),
        )

    changed_paths = [str(item) for item in changes.get("changed_paths", [])]
    disallowed_paths = [str(item) for item in changes.get("disallowed_paths", [])]
    evidence = Table.grid(expand=True)
    evidence.add_column(style="bold", width=22)
    evidence.add_column()
    evidence.add_row("Changed files", _lines(changed_paths, empty="none reported"))
    if disallowed_paths:
        evidence.add_row("Disallowed paths", Text(_lines(disallowed_paths), style="bold red"))
    evidence.add_row("HTML report", str(report_path))
    evidence.add_row("Main working tree", "unchanged; FirstGreen did not merge")
    if delivery is not None and delivery.get("workspace_path"):
        evidence.add_row("Delivery worktree", str(delivery["workspace_path"]))

    run_id = str(run.get("id", ""))
    next_steps = [
        f"fg report {run_id} --open --state-dir {shlex.quote(str(state_dir))}",
        f"fg status {run_id} --json --state-dir {shlex.quote(str(state_dir))}",
        f"fg logs {run_id} --json --state-dir {shlex.quote(str(state_dir))}",
    ]
    if not verified:
        failed_attempts = [item for item in attempts if item.get("status") == "failed"]
        if failed_attempts:
            attempt_id = str(failed_attempts[-1].get("id", ""))
            next_steps.insert(
                0,
                f"fg reverify {run_id} --attempt {attempt_id} "
                f"--manifest {shlex.quote(str(manifest_path))} "
                f"--state-dir {shlex.quote(str(state_dir))}",
            )

    return Panel(
        Group(
            overview,
            Text("\nAttempts and preserved workspaces", style="bold cyan"),
            attempt_table,
            Text("\nDeterministic verification", style="bold cyan"),
            verification_table,
            Text("\nEvidence", style="bold cyan"),
            evidence,
            Text("\nNext steps", style="bold cyan"),
            Text("\n".join(next_steps)),
        ),
        title=f"FirstGreen result: {result_text}",
        border_style="green" if verified else "red",
    )


def print_result(
    data: dict[str, Any],
    *,
    report_path: Path,
    manifest_path: Path,
    state_dir: Path,
    console: Console | None = None,
) -> None:
    (console or default_console()).print(
        result_renderable(
            data,
            report_path=report_path,
            manifest_path=manifest_path,
            state_dir=state_dir,
        )
    )


def run_renderable(data: dict[str, Any], *, now: datetime | None = None) -> RenderableType:
    current = now or datetime.now(UTC)
    run = dict(data["run"])
    tasks = list(data["tasks"])
    attempts = list(data["attempts"])
    summary = dict(data["summary"])
    raw_delivery = data.get("delivery")
    delivery = dict(raw_delivery) if isinstance(raw_delivery, dict) else None

    table = Table(expand=True, box=None)
    table.add_column("", width=3)
    table.add_column("Task", style="bold")
    table.add_column("Status")
    table.add_column("Attempt")
    for raw_task in tasks:
        task = dict(raw_task)
        status = str(task["status"])
        mark, style = STATUS_MARKS.get(status, ("?", "white"))
        task_attempts = [
            dict(item) for item in attempts if dict(item).get("task_key") == task.get("task_key")
        ]
        role = (
            ", ".join(f"{item.get('role')}:{item.get('status')}" for item in task_attempts) or "-"
        )
        table.add_row(
            Text(mark, style=style), str(task["task_key"]), Text(status, style=style), role
        )

    active = sum(
        str(dict(item).get("status")) in {"starting", "running", "verifying"} for item in attempts
    )
    planning = data.get("planning")
    estimated_cost: float | int | str | None = None
    if isinstance(planning, dict):
        raw_cost = planning.get("planning_estimated_cost")
        if isinstance(raw_cost, float | int | str):
            estimated_cost = raw_cost
    cost_text = (
        "unavailable" if estimated_cost is None else f"${float(estimated_cost):.4f} planner est."
    )
    footer = Text(
        f"Agents: {active} active   Verified: {summary['verified']}   "
        f"Failed: {summary['failed']}   Cost: {cost_text}   "
        f"Elapsed: {_duration(_elapsed_seconds(run, current))}"
    )
    if delivery is not None:
        footer.append(f"   Delivery: {delivery.get('status', '-')}")
    title = f"FirstGreen | {run['id']} | {run['status']}"
    return Panel(Group(table, Text(""), footer), title=title)


def load_run_renderable(repository: SQLiteRepository, run_id: str) -> RenderableType:
    try:
        return run_renderable(run_data(repository, run_id))
    except ValueError:
        return Panel("Preparing scheduler state...", title=f"FirstGreen | {run_id}")


async def run_with_tui(
    service: SchedulerService,
    manifest: Manifest,
    manifest_path: object,
    policy: str,
    run_id: str,
    *,
    console: Console | None = None,
    refresh_seconds: float = 0.15,
) -> RunOutcome:
    """Run the production scheduler while polling its persisted state for display."""

    target = console or default_console()
    path = manifest_path if isinstance(manifest_path, Path) else Path(str(manifest_path))
    future = asyncio.create_task(
        service.run(manifest, path, policy, run_id=run_id), name=f"firstgreen-ui:{run_id}"
    )
    with Live(
        load_run_renderable(service.repository, run_id),
        console=target,
        refresh_per_second=8,
        transient=False,
    ) as live:
        while not future.done():
            live.update(load_run_renderable(service.repository, run_id))
            await asyncio.sleep(refresh_seconds)
        outcome = await future
        live.update(load_run_renderable(service.repository, run_id), refresh=True)
    return outcome


def events_renderable(events: list[dict[str, object]]) -> RenderableType:
    table = Table(expand=True, box=None)
    table.add_column("Time")
    table.add_column("Task")
    table.add_column("Event", style="bold")
    table.add_column("Details")
    for event in events:
        payload = event.get("payload")
        details = json.dumps(payload, ensure_ascii=False) if payload else ""
        table.add_row(
            str(event.get("timestamp", "")),
            str(event.get("task_key") or "-"),
            str(event.get("type", "")),
            details,
        )
    return Panel(table, title="FirstGreen events")
