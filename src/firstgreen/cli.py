"""FirstGreen command-line interface."""

import asyncio
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import webbrowser
from contextlib import suppress
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path

import typer
import yaml
from pydantic import ValidationError

from firstgreen.adapters.codex_exec import CodexExecAdapter
from firstgreen.benchmark import run_scaling_matrix, write_scaling_svg
from firstgreen.config import Manifest, PlanningConfig, RepositoryViewConfig, load_manifest
from firstgreen.db.repository import SQLiteRepository
from firstgreen.errors import FirstGreenError
from firstgreen.ids import new_id
from firstgreen.planning.compiler import can_auto_approve
from firstgreen.planning.compiler import validate_plan as validate_candidate_tasks
from firstgreen.planning.models import ApprovedPlan, CandidatePlan
from firstgreen.planning.planner import CodexPlannerAdapter
from firstgreen.planning.scanner import HeuristicRepositoryScanner
from firstgreen.planning.workflow import (
    PlanningEngine,
    PlanningOutcome,
    default_planning_config,
    load_plan,
    plan_to_manifest,
    save_plan,
)
from firstgreen.reporting.export import event_data, export_csv, export_json, report_html, run_data
from firstgreen.reporting.trace import export_trace
from firstgreen.service import SchedulerService, default_state_dir
from firstgreen.simulator import simulation_dict
from firstgreen.tui import (
    ask_plan_action,
    default_console,
    events_renderable,
    load_run_renderable,
    print_plan,
    print_result,
    read_multiline_request,
    run_with_tui,
)
from firstgreen.user_config import (
    UserConfig,
    UserConfigError,
    codex_binary_candidates,
    load_user_config,
    remember_repository,
    save_user_config,
    user_config_path,
)
from firstgreen.verifier.environment import (
    DetectedVerifierEnvironment,
    detect_verifier_environment,
)
from firstgreen.work_requests import (
    ClipboardUnavailable,
    WorkRequest,
    clipboard_request,
    request_from_token,
)
from firstgreen.workspace.repository_view import RepositoryView, prepare_repository_view

app = typer.Typer(help="FirstGreen: verified coding-agent fleet scheduler", no_args_is_help=True)
benchmark_app = typer.Typer(help="Reproducible policy benchmarks")
app.add_typer(benchmark_app, name="benchmark")

COMMANDS = {
    "benchmark",
    "cancel",
    "clip",
    "configure",
    "doctor",
    "export",
    "init",
    "logs",
    "plan",
    "report",
    "request",
    "reverify",
    "run",
    "scan",
    "status",
    "validate",
    "validate-plan",
    "version",
}

WORKER_REASONING_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}

_CODEX_PREFLIGHT_CACHE: dict[str, bool] = {}


def _user_config() -> UserConfig:
    try:
        return load_user_config()
    except UserConfigError as error:
        raise typer.BadParameter(str(error)) from error


def _preflight_codex_binary(
    *, explicit: str | None, configured: str | None, announce: bool = False
) -> str:
    failures: list[str] = []
    for candidate in codex_binary_candidates(explicit=explicit, configured=configured):
        if _CODEX_PREFLIGHT_CACHE.get(candidate):
            return candidate
        result = asyncio.run(CodexExecAdapter(candidate).doctor())
        if result.ok:
            _CODEX_PREFLIGHT_CACHE[candidate] = True
            if announce:
                typer.echo(f"Codex preflight: OK - {candidate}")
            return candidate
        failures.append(f"{candidate}: {result.message}")
    typer.echo("Codex preflight blocked; no usable local CLI was found:", err=True)
    for failure in failures:
        typer.echo(f"- {failure}", err=True)
    typer.echo(
        "Run 'fg configure --codex-binary PATH' after selecting an authenticated Codex CLI.",
        err=True,
    )
    raise typer.Exit(3)


def _state(path: Path | None) -> Path:
    return (path or default_state_dir()).expanduser().resolve()


def _repository_view(
    repository: Path,
    *,
    state: Path,
    dirty_mode: str,
    base_ref: str = "HEAD",
) -> RepositoryView:
    if dirty_mode not in {"block", "head", "snapshot"}:
        raise typer.BadParameter("--dirty-mode must be block, head, or snapshot")
    try:
        view = prepare_repository_view(
            repository,
            state,
            dirty_mode=dirty_mode,  # type: ignore[arg-type]
            base_ref=base_ref,
        )
    except (OSError, ValueError, FirstGreenError) as error:
        raise typer.BadParameter(str(error)) from error
    if view.mode != "clean":
        typer.echo(f"Repository mode: {view.mode}")
        typer.echo(f"Source repository: {view.source_repo}")
        typer.echo(f"Execution repository: {view.execution_repo}")
        typer.echo(f"Pinned base: {view.base_sha}")
    return view


def _request_with_repository_view(request: WorkRequest, view: RepositoryView) -> WorkRequest:
    return request.model_copy(
        update={
            "repository": view.execution_repo,
            "source_repository": view.source_repo,
            "repository_mode": view.mode,
            "dirty_entries": list(view.dirty_entries),
        }
    )


def _manifest_with_repository_view(manifest: Manifest, view: RepositoryView) -> Manifest:
    project = manifest.project.model_copy(
        update={"repo": view.execution_repo, "base_ref": view.base_sha}
    )
    record = RepositoryViewConfig(
        source_repo=view.source_repo,
        execution_repo=view.execution_repo,
        base_sha=view.base_sha,
        mode=view.mode,
        dirty_entries=list(view.dirty_entries),
    )
    return manifest.model_copy(update={"project": project, "repository_view": record})


def _apply_worker_overrides(
    manifest: Manifest,
    *,
    worker_model: str | None,
    worker_reasoning: str | None,
    codex_binary: str | None,
) -> Manifest:
    requested = any(value is not None for value in (worker_model, worker_reasoning, codex_binary))
    if requested and manifest.agent_defaults.adapter != "codex_exec":
        raise typer.BadParameter("worker model/reasoning/binary options require codex_exec")
    if worker_reasoning is not None and worker_reasoning not in WORKER_REASONING_EFFORTS:
        allowed = ", ".join(sorted(WORKER_REASONING_EFFORTS))
        raise typer.BadParameter(f"--worker-reasoning must be one of: {allowed}")
    config = dict(manifest.agent_defaults.config)
    if worker_model is not None:
        if not worker_model.strip():
            raise typer.BadParameter("--worker-model cannot be empty")
        config["model"] = worker_model.strip()
    if worker_reasoning is not None:
        config["model_reasoning_effort"] = worker_reasoning
    updates: dict[str, object] = {"config": config}
    if codex_binary is not None:
        if not codex_binary.strip():
            raise typer.BadParameter("--codex-binary cannot be empty")
        updates["codex_binary"] = codex_binary.strip()
    defaults = manifest.agent_defaults.model_copy(update=updates)
    return manifest.model_copy(update={"agent_defaults": defaults})


def _verifier_python_mapping(verifier_python: Path | None) -> dict[str, str]:
    if verifier_python is None:
        return {}
    resolved = Path(os.path.abspath(verifier_python.expanduser()))
    if not resolved.is_file():
        raise typer.BadParameter(f"--verifier-python is not a file: {resolved}")
    return {"python": str(resolved), "python3": str(resolved)}


def _manifest_verifier_commands(manifest: Manifest) -> tuple[tuple[str, ...] | None, ...]:
    return tuple(
        tuple(command.argv) if command.argv is not None and not command.shell else None
        for task in manifest.tasks
        for command in task.verify.commands
    )


def _show_verifier_environment(environment: DetectedVerifierEnvironment) -> None:
    if environment.mode == "not-required":
        return
    typer.echo(f"Verifier environment: {environment.mode}")
    if environment.environment_root is not None:
        typer.echo(f"Project environment: {environment.environment_root}")
    for name, executable in sorted(environment.resolved_executables.items()):
        typer.echo(f"Verifier executable: {name} -> {executable}")
    for warning in environment.warnings:
        typer.echo(f"Verifier warning: {warning}", err=True)


def _apply_verifier_environment(manifest: Manifest, verifier_python: Path | None) -> Manifest:
    explicit = dict(manifest.verification_defaults.executable_overrides)
    explicit.update(_verifier_python_mapping(verifier_python))
    source_repo = (
        manifest.repository_view.source_repo
        if manifest.repository_view is not None
        else manifest.project.repo
    )
    try:
        environment = detect_verifier_environment(
            source_repo,
            _manifest_verifier_commands(manifest),
            explicit_overrides=explicit,
        )
    except FirstGreenError as error:
        raise typer.BadParameter(str(error)) from error
    overrides = dict(explicit)
    overrides.update(environment.resolved_executables)
    snapshot = {
        "mode": environment.mode,
        "repository": str(environment.repository),
        "environment_root": (
            str(environment.environment_root) if environment.environment_root is not None else None
        ),
        "resolved_executables": environment.resolved_executables,
        "warnings": list(environment.warnings),
    }
    defaults = manifest.verification_defaults.model_copy(
        update={"executable_overrides": overrides, "environment_snapshot": snapshot}
    )
    _show_verifier_environment(environment)
    return manifest.model_copy(update={"verification_defaults": defaults})


def _write_resolved_manifest(state: Path, manifest: Manifest) -> Path:
    content = yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False)
    digest = hashlib.sha256(content.encode()).hexdigest()
    path = state / "plans" / f"resolved-{digest}.manifest.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _planning_config(
    *,
    planner_provider: str,
    planner_model: str,
    planner_budget: float | None,
    max_plan_tasks: int,
    no_history: bool,
) -> PlanningConfig:
    if planner_provider not in {"fake", "codex"}:
        raise typer.BadParameter("--planner-provider must be fake or codex")
    config = default_planning_config(fake=planner_provider == "fake")
    return config.model_copy(
        update={
            "repository_scan": config.repository_scan.model_copy(
                update={"include_git_history": not no_history}
            ),
            "decomposition": config.decomposition.model_copy(update={"max_tasks": max_plan_tasks}),
            "llm": config.llm.model_copy(
                update={"model": planner_model, "planner_budget": planner_budget}
            ),
        }
    )


def _show_plan(plan: CandidatePlan) -> None:
    console = default_console()
    if console.is_terminal:
        print_plan(plan, console)
        return
    typer.echo(f"Planning result: {plan.decision.decision}")
    typer.echo(f"Source repository: {plan.source_repo or plan.repo}")
    if (plan.source_repo or plan.repo).resolve() != plan.repo.resolve():
        typer.echo(f"Execution repository: {plan.repo}")
    typer.echo(f"Repository mode: {plan.repository_mode}")
    typer.echo(f"Recommended root slots: {plan.decision.recommended_parallelism}")
    if plan.parallelism_analysis is not None:
        analysis = plan.parallelism_analysis
        typer.echo(
            "Estimated work/span: "
            f"{analysis.estimated_work_seconds:.1f}s / {analysis.estimated_span_seconds:.1f}s"
        )
        typer.echo(f"Exposed parallelism W/L: {analysis.exposed_parallelism:.3f}")
        typer.echo(f"Ready width: {analysis.ready_width}")
        typer.echo(f"Critical path: {' -> '.join(analysis.critical_path)}")
        typer.echo(f"Slot recommendation: {analysis.recommendation_reason}")
    typer.echo(f"Risk level: {plan.risk_level}")
    typer.echo(f"Reason: {plan.decision.reason}\n")
    typer.echo("Tasks:")
    for index, task in enumerate(plan.tasks, start=1):
        typer.echo(f"[{index}] {task.id}")
        typer.echo(f"    Objective: {task.objective}")
        typer.echo(
            f"    Duration estimate: {task.estimated_duration_seconds:.1f}s "
            f"({task.estimate_source})"
        )
        if task.dependencies:
            typer.echo(f"    Depends on: {', '.join(task.dependencies)}")
        if task.produces:
            typer.echo(f"    Produces: {', '.join(task.produces)}")
        if task.likely_paths:
            typer.echo(f"    Likely paths: {', '.join(task.likely_paths)}")
        typer.echo("    Scheduler-owned verification:")
        for command in task.verifier:
            typer.echo(f"      - {shlex.join(command)}")
    typer.echo("\nExecution DAG:")
    for task in plan.tasks:
        dependencies = ", ".join(task.dependencies) or "start"
        locks = ", ".join(task.resources) or "none"
        typer.echo(f"- {task.id}: starts after {dependencies}; conflict locks: {locks}")
    if plan.conflicts:
        typer.echo("\nConflicts:")
        for conflict in plan.conflicts:
            typer.echo(
                f"- {conflict.task_a} / {conflict.task_b}: "
                f"{conflict.constraint} on {conflict.resource}"
            )
    if plan.validation.repairs:
        typer.echo("\nDeterministic repairs:")
        for repair in plan.validation.repairs:
            typer.echo(f"- {repair}")
    typer.echo(
        f"\nValidation: {'valid' if plan.validation.valid else 'invalid'}; "
        f"planning time: {plan.planning_latency_seconds:.3f}s"
    )
    typer.echo("Approval: required before any worker starts")


@app.command()
def scan(
    repo: Path = typer.Option(Path("."), "--repo"),
    output: Path | None = typer.Option(None, "--output"),
    no_history_analysis: bool = typer.Option(False, "--no-history-analysis"),
    dirty_mode: str | None = typer.Option(None, "--dirty-mode"),
    state_dir: Path | None = typer.Option(None),
) -> None:
    """Build a bounded, read-only repository map."""
    settings = _user_config()
    configured_state = Path(settings.state_dir) if settings.state_dir else None
    state = _state(state_dir or configured_state)
    view = _repository_view(repo, state=state, dirty_mode=dirty_mode or settings.dirty_mode)
    config = default_planning_config().repository_scan.model_copy(
        update={"include_git_history": not no_history_analysis}
    )
    repo_map = HeuristicRepositoryScanner().scan(view.execution_repo, config)
    rendered = repo_map.model_dump_json(indent=2)
    if output is None:
        typer.echo(rendered)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        typer.echo(str(output))


@app.command("plan")
def plan_command(
    request: str,
    repo: Path = typer.Option(Path("."), "--repo"),
    output: Path | None = typer.Option(None, "--output"),
    planner_provider: str | None = typer.Option(None, "--planner-provider"),
    planner_model: str | None = typer.Option(None, "--planner-model"),
    codex_binary: str | None = typer.Option(None, "--codex-binary"),
    planner_budget: float | None = typer.Option(None, "--planner-budget"),
    max_plan_tasks: int = typer.Option(5, "--max-plan-tasks", min=1, max=5),
    allow_path: list[str] | None = typer.Option(None, "--allow-path"),
    deny_path: list[str] | None = typer.Option(None, "--deny-path"),
    repo_map_cache: Path | None = typer.Option(None, "--repo-map-cache"),
    no_history_analysis: bool = typer.Option(False, "--no-history-analysis"),
    dirty_mode: str | None = typer.Option(None, "--dirty-mode"),
    state_dir: Path | None = typer.Option(None),
) -> None:
    """Convert inline text, a file, or stdin into a validated candidate plan."""
    del repo_map_cache  # Reserved for an external shared repo-map cache in a later batch.
    settings = _user_config()
    planner_provider = planner_provider or settings.planner_provider
    planner_model = planner_model or settings.planner_model
    configured_state = Path(settings.state_dir) if settings.state_dir else None
    state = _state(state_dir or configured_state)
    view = _repository_view(repo, state=state, dirty_mode=dirty_mode or settings.dirty_mode)
    try:
        work_request = _request_with_repository_view(
            request_from_token(request, view.execution_repo), view
        )
    except (OSError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error
    config = _planning_config(
        planner_provider=planner_provider,
        planner_model=planner_model,
        planner_budget=planner_budget,
        max_plan_tasks=max_plan_tasks,
        no_history=no_history_analysis,
    )
    planner_binary = codex_binary or settings.codex_binary
    if planner_provider == "codex":
        planner_binary = _preflight_codex_binary(
            explicit=codex_binary,
            configured=settings.codex_binary,
            announce=True,
        )
    planner = (
        CodexPlannerAdapter(
            state / "planner-live", binary=planner_binary or "codex", model=planner_model
        )
        if planner_provider == "codex"
        else None
    )
    outcome = PlanningEngine(state, planner=planner).plan_request(
        work_request,
        config,
        allow_paths=tuple(allow_path or ()),
        deny_paths=tuple(deny_path or ()),
    )
    _show_plan(outcome.plan)
    if output is not None:
        save_plan(outcome.plan, output)
        typer.echo(f"Plan YAML: {output}")


@app.command("validate-plan")
def validate_plan_command(
    plan_file: Path,
    allow_path: list[str] | None = typer.Option(None, "--allow-path"),
    deny_path: list[str] | None = typer.Option(None, "--deny-path"),
    dirty_mode: str | None = typer.Option(None, "--dirty-mode"),
    state_dir: Path | None = typer.Option(None),
) -> None:
    """Re-scan and deterministically validate an edited plan YAML."""
    plan = load_plan(plan_file)
    settings = _user_config()
    configured_state = Path(settings.state_dir) if settings.state_dir else None
    state = _state(state_dir or configured_state)
    view = _repository_view(
        plan.repo,
        state=state,
        dirty_mode=dirty_mode or settings.dirty_mode,
    )
    if view.base_sha != plan.commit_sha:
        raise typer.BadParameter(
            "repository snapshot no longer matches the plan base; create a new plan"
        )
    plan = plan.model_copy(update={"repo": view.execution_repo})
    config = default_planning_config()
    repo_map = HeuristicRepositoryScanner().scan(plan.repo, config.repository_scan)
    validation = validate_candidate_tasks(
        plan.tasks,
        plan.conflicts,
        repo_map,
        plan.external_artifacts,
        max_tasks=config.decomposition.max_tasks,
        allow_paths=tuple(allow_path or ()),
        deny_paths=tuple(deny_path or ()),
    )
    validation = validation.model_copy(update={"repairs": plan.validation.repairs})
    typer.echo(validation.model_dump_json(indent=2))
    if not validation.valid:
        raise typer.Exit(2)


@app.command()
def doctor(
    repo: Path = typer.Option(Path("."), "--repo"),
    codex_binary: str = typer.Option("codex", "--codex-binary"),
) -> None:
    """Check Python, Git, repository, state storage, and Codex availability."""
    state = default_state_dir()
    state.mkdir(parents=True, exist_ok=True)
    codex = asyncio.run(CodexExecAdapter(codex_binary).doctor())
    repository = repo.expanduser().resolve()
    is_repo = (repository / ".git").exists()
    clean = False
    worktree = False
    if is_repo and shutil.which("git"):
        status_result = subprocess.run(
            ["git", "-C", str(repository), "status", "--porcelain"],
            check=False,
            capture_output=True,
            text=True,
        )
        worktree_result = subprocess.run(
            ["git", "-C", str(repository), "worktree", "list", "--porcelain"],
            check=False,
            capture_output=True,
            text=True,
        )
        clean = status_result.returncode == 0 and not status_result.stdout.strip()
        worktree = worktree_result.returncode == 0
    typer.echo(
        f"Python: {sys.version.split()[0]} {'OK' if sys.version_info >= (3, 12) else 'ERROR'}"
    )
    typer.echo(f"Git: {'OK' if shutil.which('git') else 'ERROR'}")
    typer.echo(f"Repository: {'OK' if is_repo else 'ERROR'} - {repository}")
    typer.echo(f"Main worktree: {'clean' if clean else 'dirty or unavailable'}")
    typer.echo(f"Git worktree support: {'OK' if worktree else 'ERROR'}")
    typer.echo(f"State: {state} OK")
    typer.echo(f"Codex: {'OK' if codex.ok else 'BLOCKED'} - {codex.message}")


@app.command()
def configure(
    codex_binary: str | None = typer.Option(None, "--codex-binary"),
    auto_codex: bool = typer.Option(False, "--auto-codex"),
    adapter: str | None = typer.Option(None, "--adapter"),
    worker_model: str | None = typer.Option(None, "--model", "--worker-model"),
    worker_reasoning: str | None = typer.Option(None, "--reasoning", "--worker-reasoning"),
    planner_provider: str | None = typer.Option(None, "--planner-provider"),
    planner_model: str | None = typer.Option(None, "--planner-model"),
    dirty_mode: str | None = typer.Option(None, "--dirty-mode"),
    state_dir: Path | None = typer.Option(None, "--state-dir"),
    show: bool = typer.Option(False, "--show"),
) -> None:
    """Persist non-secret local defaults used by future fg sessions."""

    current = _user_config()
    updates: dict[str, object] = {}
    if adapter is not None:
        updates["adapter"] = adapter
    if worker_model is not None:
        updates["worker_model"] = worker_model
    if worker_reasoning is not None:
        if worker_reasoning not in WORKER_REASONING_EFFORTS:
            allowed = ", ".join(sorted(WORKER_REASONING_EFFORTS))
            raise typer.BadParameter(f"--worker-reasoning must be one of: {allowed}")
        updates["worker_reasoning"] = worker_reasoning
    if planner_provider is not None:
        updates["planner_provider"] = planner_provider
    if planner_model is not None:
        updates["planner_model"] = planner_model
    if dirty_mode is not None:
        updates["dirty_mode"] = dirty_mode
    if state_dir is not None:
        updates["state_dir"] = str(state_dir.expanduser().resolve())
    if codex_binary is not None or auto_codex:
        updates["codex_binary"] = _preflight_codex_binary(
            explicit=codex_binary,
            configured=None if auto_codex else current.codex_binary,
            announce=True,
        )
    try:
        configured = current.model_copy(update=updates)
        configured = UserConfig.model_validate(configured.model_dump(mode="json"))
    except ValidationError as error:
        raise typer.BadParameter(f"invalid FirstGreen configuration: {error}") from error
    if updates:
        path = save_user_config(configured)
        typer.echo(f"Saved FirstGreen configuration: {path}")
    if show or not updates:
        typer.echo(f"Configuration: {user_config_path()}")
        typer.echo(configured.model_dump_json(indent=2))


@app.command()
def version() -> None:
    """Print the FirstGreen package version."""

    try:
        value = package_version("firstgreen")
    except PackageNotFoundError:
        value = "0.1.0rc1+source"
    typer.echo(value)


@app.command("init")
def init_command(path: Path = Path("fleet.yaml")) -> None:
    """Write a safe starter manifest without overwriting existing files."""
    if path.exists():
        raise typer.BadParameter(f"refusing to overwrite {path}")
    template = {
        "version": 1,
        "project": {"repo": str(Path.cwd()), "base_ref": "HEAD"},
        "scheduler": {
            "concurrency": {
                "mode": "static",
                "min_root": 1,
                "max_root": 1,
                "initial_root": 1,
                "total_agent_thread_budget": 1,
                "verifier_slots": 1,
            }
        },
        "agent_defaults": {"adapter": "fake"},
        "verification_defaults": {},
        "workspace": {},
        "tasks": [
            {
                "id": "smoke",
                "prompt": "Fake smoke task",
                "replay_safe": True,
                "verify": {"commands": [{"argv": [sys.executable, "-c", "print('green')"]}]},
            }
        ],
    }
    path.write_text(yaml.safe_dump(template, sort_keys=False), encoding="utf-8")
    typer.echo(str(path))


@app.command()
def validate(manifest: Path) -> None:
    """Validate strict schema, DAG, repository, and base ref."""
    try:
        loaded = load_manifest(manifest)
    except (OSError, ValidationError, ValueError) as error:
        typer.echo(f"invalid: {error}", err=True)
        raise typer.Exit(2) from error
    if not (loaded.project.repo / ".git").exists():
        typer.echo("invalid: project.repo is not a Git repository", err=True)
        raise typer.Exit(2)
    typer.echo(f"valid: {len(loaded.tasks)} task(s)")


def _write_compiled_manifest(state: Path, approved: ApprovedPlan, manifest: Manifest) -> Path:
    path = state / "plans" / f"{approved.cache_key}.manifest.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    return path


def _edit_plan_in_local_editor(path: Path) -> bool:
    configured = os.environ.get("FIRSTGREEN_EDITOR") or os.environ.get("EDITOR")
    if configured:
        argv = [*shlex.split(configured, posix=os.name != "nt"), str(path)]
    elif os.name == "nt":
        argv = ["notepad.exe", str(path)]
    else:
        editor = shutil.which("nano") or shutil.which("vi")
        if editor is None:
            return False
        argv = [editor, str(path)]
    try:
        completed = subprocess.run(argv, check=False)
    except OSError as error:
        typer.echo(f"Could not open plan editor: {type(error).__name__}", err=True)
        return False
    return completed.returncode == 0


def _approve_request_plan(
    *,
    engine: PlanningEngine,
    outcome: PlanningOutcome,
    request: WorkRequest,
    config: PlanningConfig,
    plan_mode: str,
    approve_plan: bool,
    require_plan_approval: bool,
    use_tui: bool,
    state: Path,
    allow_paths: tuple[str, ...],
    deny_paths: tuple[str, ...],
) -> ApprovedPlan:
    current = outcome
    _show_plan(current.plan)
    if plan_mode == "none":
        return engine.approve(outcome, config)
    if approve_plan and not require_plan_approval:
        try:
            return engine.approve(outcome, config, policy_auto_approval=True)
        except ValueError as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(2) from error

    console = default_console()
    if use_tui and console.is_terminal:
        while True:
            action = ask_plan_action(console)
            if action == "cancel":
                raise typer.Exit(2)
            if action == "approve":
                return engine.approve(current, config)
            if action == "edit":
                path = state / "plans" / f"{current.plan.cache_key}.editable.yaml"
                save_plan(current.plan, path)
                typer.echo(f"Editable plan: {path}")
                if not _edit_plan_in_local_editor(path):
                    typer.echo(f"After editing: fg run {path} --plan existing")
                    raise typer.Exit(2)
                try:
                    current = engine.replace_candidate(
                        current,
                        load_plan(path),
                        config,
                        allow_paths=allow_paths,
                        deny_paths=deny_paths,
                    )
                except (OSError, ValidationError, ValueError, yaml.YAMLError) as error:
                    typer.echo(f"Edited plan is invalid: {error}", err=True)
                    continue
                _show_plan(current.plan)
                continue
            if action == "single":
                current = engine.plan_request(
                    request,
                    config,
                    mode="none",
                    allow_paths=allow_paths,
                    deny_paths=deny_paths,
                )
                _show_plan(current.plan)
                continue
    elif not typer.confirm("Approve this validated plan for execution?"):
        raise typer.Exit(2)
    return engine.approve(current, config)


def _execute_manifest(
    manifest: Manifest,
    compiled_path: Path,
    *,
    state: Path,
    policy: str,
    use_tui: bool,
) -> tuple[str, int, int, bool, Path | None]:
    if manifest.agent_defaults.adapter == "codex_exec":
        doctor_result = asyncio.run(CodexExecAdapter(manifest.agent_defaults.codex_binary).doctor())
        if not doctor_result.ok:
            typer.echo(f"Codex preflight blocked: {doctor_result.message}", err=True)
            raise typer.Exit(3)
    service = SchedulerService(state)
    run_id = new_id("run")
    console = default_console()
    if use_tui and console.is_terminal:
        outcome = asyncio.run(
            run_with_tui(service, manifest, compiled_path, policy, run_id, console=console)
        )
    else:
        outcome = asyncio.run(service.run(manifest, compiled_path, policy, run_id=run_id))
    report_path = report_html(
        service.repository,
        outcome.run_id,
        state / "reports" / outcome.run_id / "report.html",
    )
    human_result = use_tui and console.is_terminal
    if human_result:
        print_result(
            run_data(service.repository, outcome.run_id),
            report_path=report_path,
            manifest_path=compiled_path,
            state_dir=state,
            console=console,
        )
    return (
        outcome.run_id,
        outcome.verified,
        outcome.failed,
        human_result,
        outcome.delivery_workspace,
    )


def _prepare_work_request(
    request: WorkRequest,
    *,
    state: Path,
    config: PlanningConfig,
    policy: str,
    plan_mode: str,
    approve_plan: bool,
    require_plan_approval: bool,
    adapter: str,
    replay_safe: bool,
    planner_provider: str,
    planner_model: str,
    codex_binary: str | None,
    allow_paths: tuple[str, ...],
    deny_paths: tuple[str, ...],
    use_tui: bool,
) -> tuple[Manifest, Path]:
    planner = (
        CodexPlannerAdapter(
            state / "planner-live", binary=codex_binary or "codex", model=planner_model
        )
        if planner_provider == "codex"
        else None
    )
    engine = PlanningEngine(state, planner=planner)
    outcome = engine.plan_request(
        request,
        config,
        mode=plan_mode,
        allow_paths=allow_paths,
        deny_paths=deny_paths,
    )
    approved = _approve_request_plan(
        engine=engine,
        outcome=outcome,
        request=request,
        config=config,
        plan_mode=plan_mode,
        approve_plan=approve_plan,
        require_plan_approval=require_plan_approval,
        use_tui=use_tui,
        state=state,
        allow_paths=allow_paths,
        deny_paths=deny_paths,
    )
    manifest = plan_to_manifest(approved, adapter=adapter, replay_safe=replay_safe, policy=policy)
    return manifest, _write_compiled_manifest(state, approved, manifest)


@app.command()
def run(
    input_value: str,
    policy: str = typer.Option("single", help="single|always-race|delayed-hedge|auto"),
    plan_mode: str = typer.Option("auto", "--plan", help="none|auto|existing"),
    approve_plan: bool = typer.Option(False, "--approve-plan", "--yes"),
    require_plan_approval: bool = typer.Option(False, "--require-plan-approval"),
    repo: Path = typer.Option(Path("."), "--repo"),
    adapter: str | None = typer.Option(None, "--adapter"),
    worker_model: str | None = typer.Option(None, "--model", "--worker-model"),
    worker_reasoning: str | None = typer.Option(None, "--reasoning", "--worker-reasoning"),
    codex_binary: str | None = typer.Option(None, "--codex-binary"),
    verifier_python: Path | None = typer.Option(None, "--verifier-python"),
    replay_safe: bool = typer.Option(False, "--replay-safe"),
    planner_provider: str | None = typer.Option(None, "--planner-provider"),
    planner_model: str | None = typer.Option(None, "--planner-model"),
    planner_budget: float | None = typer.Option(None, "--planner-budget"),
    max_plan_tasks: int = typer.Option(5, "--max-plan-tasks", min=1, max=5),
    allow_path: list[str] | None = typer.Option(None, "--allow-path"),
    deny_path: list[str] | None = typer.Option(None, "--deny-path"),
    no_history_analysis: bool = typer.Option(False, "--no-history-analysis"),
    dirty_mode: str | None = typer.Option(None, "--dirty-mode"),
    dry_run: bool = False,
    tui: bool = typer.Option(True, "--tui/--no-tui"),
    state_dir: Path | None = typer.Option(None),
) -> None:
    """Run inline text, a request file/stdin, an approved plan, or a manifest."""

    settings = _user_config()
    explicit_worker_model = worker_model
    explicit_worker_reasoning = worker_reasoning
    explicit_codex_binary = codex_binary
    adapter = adapter or settings.adapter
    planner_provider = planner_provider or settings.planner_provider
    planner_model = planner_model or settings.planner_model
    worker_model = worker_model or settings.worker_model
    worker_reasoning = worker_reasoning or settings.worker_reasoning
    codex_binary = codex_binary or settings.codex_binary
    dirty_mode = dirty_mode or settings.dirty_mode
    if policy not in {"single", "always-race", "delayed-hedge", "auto"}:
        raise typer.BadParameter("unknown policy")
    if plan_mode not in {"none", "auto", "existing"}:
        raise typer.BadParameter("--plan must be none, auto, or existing")
    if adapter not in {"fake", "codex_exec"}:
        raise typer.BadParameter("--adapter must be fake or codex_exec")
    configured_state = Path(settings.state_dir) if settings.state_dir else None
    state = _state(state_dir or configured_state)
    planning_config = _planning_config(
        planner_provider=planner_provider,
        planner_model=planner_model,
        planner_budget=planner_budget,
        max_plan_tasks=max_plan_tasks,
        no_history=no_history_analysis,
    )
    input_path = Path(input_value).expanduser()
    input_is_file = False
    with suppress(OSError):
        input_is_file = input_path.is_file()
    raw: object | None = None
    if input_is_file and input_path.suffix.lower() in {".yaml", ".yml"}:
        try:
            raw = yaml.safe_load(input_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise typer.BadParameter(f"cannot read input: {error}") from error
    is_plan_file = isinstance(raw, dict) and raw.get("plan_version") == 1
    is_manifest_file = (
        isinstance(raw, dict) and raw.get("version") == 1 and "project" in raw and "tasks" in raw
    )
    compiled_path = input_path
    loaded: Manifest
    source_repository: Path
    if not is_plan_file and not is_manifest_file:
        if plan_mode == "existing":
            raise typer.BadParameter("natural-language input requires --plan none or --plan auto")
        view = _repository_view(repo, state=state, dirty_mode=dirty_mode)
        source_repository = view.source_repo
        try:
            work_request = _request_with_repository_view(
                request_from_token(input_value, view.execution_repo), view
            )
        except (OSError, ValueError) as error:
            raise typer.BadParameter(str(error)) from error
        allow_paths = tuple(allow_path or ())
        deny_paths = tuple(deny_path or ())
        if planner_provider == "codex":
            codex_binary = _preflight_codex_binary(
                explicit=explicit_codex_binary,
                configured=codex_binary,
                announce=True,
            )
        loaded, compiled_path = _prepare_work_request(
            work_request,
            state=state,
            config=planning_config,
            policy=policy,
            plan_mode=plan_mode,
            approve_plan=approve_plan,
            require_plan_approval=require_plan_approval,
            adapter=adapter,
            replay_safe=replay_safe,
            planner_provider=planner_provider,
            planner_model=planner_model,
            codex_binary=codex_binary,
            allow_paths=allow_paths,
            deny_paths=deny_paths,
            use_tui=tui,
        )
    elif is_plan_file:
        candidate = load_plan(input_path)
        view = _repository_view(candidate.repo, state=state, dirty_mode=dirty_mode)
        source_repository = candidate.source_repo or view.source_repo
        if view.base_sha != candidate.commit_sha:
            raise typer.BadParameter(
                "repository snapshot no longer matches the saved plan base; create a new plan"
            )
        candidate = candidate.model_copy(
            update={
                "repo": view.execution_repo,
                "source_repo": source_repository,
                "repository_mode": view.mode,
                "dirty_entries": list(view.dirty_entries),
            }
        )
        repo_map = HeuristicRepositoryScanner().scan(
            candidate.repo, planning_config.repository_scan
        )
        validation = validate_candidate_tasks(
            candidate.tasks,
            candidate.conflicts,
            repo_map,
            candidate.external_artifacts,
            max_tasks=planning_config.decomposition.max_tasks,
            allow_paths=tuple(allow_path or ()),
            deny_paths=tuple(deny_path or ()),
        )
        validation = validation.model_copy(update={"repairs": candidate.validation.repairs})
        candidate = candidate.model_copy(
            update={"validation": validation, "approved": False, "user_edited": True}
        )
        _show_plan(candidate)
        if not validation.valid:
            typer.echo("edited plan failed deterministic validation", err=True)
            raise typer.Exit(2)
        if approve_plan and not require_plan_approval:
            if not can_auto_approve(candidate, planning_config.risk, allow=True):
                typer.echo("plan is not eligible for low-risk auto-approval", err=True)
                raise typer.Exit(2)
        elif not typer.confirm("Approve this validated plan for execution?"):
            raise typer.Exit(2)
        approved = ApprovedPlan.model_validate(
            candidate.model_copy(update={"approved": True}).model_dump(mode="json")
        )
        loaded = plan_to_manifest(approved, adapter=adapter, replay_safe=replay_safe, policy=policy)
        compiled_path = _write_compiled_manifest(state, approved, loaded)
    else:
        try:
            loaded = load_manifest(input_path)
        except (OSError, ValidationError, ValueError) as error:
            typer.echo(f"invalid: {error}", err=True)
            raise typer.Exit(2) from error
        view = _repository_view(
            loaded.project.repo,
            state=state,
            dirty_mode=dirty_mode,
            base_ref=loaded.project.base_ref,
        )
        source_repository = view.source_repo
        loaded = _manifest_with_repository_view(loaded, view)
        compiled_path = _write_resolved_manifest(state, loaded)
    settings_apply_to_worker = loaded.agent_defaults.adapter == "codex_exec"
    resolved = _apply_worker_overrides(
        loaded,
        worker_model=worker_model if settings_apply_to_worker else explicit_worker_model,
        worker_reasoning=(
            worker_reasoning if settings_apply_to_worker else explicit_worker_reasoning
        ),
        codex_binary=codex_binary if settings_apply_to_worker else explicit_codex_binary,
    )
    resolved = _apply_verifier_environment(resolved, verifier_python)
    if resolved != loaded:
        loaded = resolved
        compiled_path = _write_resolved_manifest(state, loaded)
    config_path = user_config_path()
    if config_path.exists():
        save_user_config(remember_repository(settings, source_repository), config_path)
    if dry_run:
        typer.echo(
            json.dumps(
                {
                    "tasks": [task.id for task in loaded.tasks],
                    "policy": policy,
                    "compiled_manifest": str(compiled_path),
                }
            )
        )
        return
    run_id, verified, failed, human_result, delivery_workspace = _execute_manifest(
        loaded, compiled_path, state=state, policy=policy, use_tui=tui
    )
    if not human_result:
        typer.echo(
            json.dumps(
                {
                    "run_id": run_id,
                    "verified": verified,
                    "failed": failed,
                    "delivery_workspace": (
                        str(delivery_workspace) if delivery_workspace is not None else None
                    ),
                }
            )
        )
    if failed:
        raise typer.Exit(4)


@app.command("request")
def request_command(
    request: str | None = typer.Argument(None),
    policy: str = typer.Option("single", help="single|always-race|delayed-hedge|auto"),
    plan_mode: str = typer.Option("auto", "--plan", help="none|auto"),
    approve_plan: bool = typer.Option(False, "--yes", "--approve-plan"),
    repo: Path = typer.Option(Path("."), "--repo"),
    adapter: str | None = typer.Option(None, "--adapter"),
    worker_model: str | None = typer.Option(None, "--model", "--worker-model"),
    worker_reasoning: str | None = typer.Option(None, "--reasoning", "--worker-reasoning"),
    codex_binary: str | None = typer.Option(None, "--codex-binary"),
    verifier_python: Path | None = typer.Option(None, "--verifier-python"),
    replay_safe: bool = typer.Option(False, "--replay-safe"),
    planner_provider: str | None = typer.Option(None, "--planner-provider"),
    planner_model: str | None = typer.Option(None, "--planner-model"),
    planner_budget: float | None = typer.Option(None, "--planner-budget"),
    max_plan_tasks: int = typer.Option(5, "--max-plan-tasks", min=1, max=5),
    allow_path: list[str] | None = typer.Option(None, "--allow-path"),
    deny_path: list[str] | None = typer.Option(None, "--deny-path"),
    no_history_analysis: bool = typer.Option(False, "--no-history-analysis"),
    dirty_mode: str | None = typer.Option(None, "--dirty-mode"),
    dry_run: bool = False,
    tui: bool = typer.Option(True, "--tui/--no-tui"),
    state_dir: Path | None = typer.Option(None),
) -> None:
    """Interactive default entry: describe work, review the plan, then execute."""

    settings = _user_config()
    value = request
    if value is None:
        effective_adapter = adapter or settings.adapter
        effective_planner = planner_provider or settings.planner_provider
        if effective_adapter == "codex_exec" or effective_planner == "codex":
            codex_binary = _preflight_codex_binary(
                explicit=codex_binary,
                configured=settings.codex_binary,
                announce=True,
            )
        value = "-" if not sys.stdin.isatty() else read_multiline_request()
    if not value.strip():
        raise typer.BadParameter("work request content cannot be empty")
    run(
        input_value=value,
        policy=policy,
        plan_mode=plan_mode,
        approve_plan=approve_plan,
        require_plan_approval=False,
        repo=repo,
        adapter=adapter,
        worker_model=worker_model,
        worker_reasoning=worker_reasoning,
        codex_binary=codex_binary,
        verifier_python=verifier_python,
        replay_safe=replay_safe,
        planner_provider=planner_provider,
        planner_model=planner_model,
        planner_budget=planner_budget,
        max_plan_tasks=max_plan_tasks,
        allow_path=allow_path,
        deny_path=deny_path,
        no_history_analysis=no_history_analysis,
        dirty_mode=dirty_mode,
        dry_run=dry_run,
        tui=tui,
        state_dir=state_dir,
    )


@app.command()
def clip(
    plan_only: bool = typer.Option(False, "--plan-only"),
    repo: Path = typer.Option(Path("."), "--repo"),
    planner_provider: str | None = typer.Option(None, "--planner-provider"),
    planner_model: str | None = typer.Option(None, "--planner-model"),
    codex_binary: str | None = typer.Option(None, "--codex-binary"),
    adapter: str | None = typer.Option(None, "--adapter"),
    approve_plan: bool = typer.Option(False, "--yes", "--approve-plan"),
    dirty_mode: str | None = typer.Option(None, "--dirty-mode"),
    dry_run: bool = False,
    state_dir: Path | None = typer.Option(None),
) -> None:
    """Read a work request from the local clipboard."""

    settings = _user_config()
    planner_provider = planner_provider or settings.planner_provider
    planner_model = planner_model or settings.planner_model
    adapter = adapter or settings.adapter
    codex_binary = codex_binary or settings.codex_binary
    dirty_mode = dirty_mode or settings.dirty_mode
    configured_state = Path(settings.state_dir) if settings.state_dir else None
    state = _state(state_dir or configured_state)
    view = _repository_view(repo, state=state, dirty_mode=dirty_mode)
    try:
        request = _request_with_repository_view(clipboard_request(view.execution_repo), view)
    except ClipboardUnavailable as error:
        typer.echo(f"clipboard unavailable: {error}", err=True)
        raise typer.Exit(2) from error
    config = _planning_config(
        planner_provider=planner_provider,
        planner_model=planner_model,
        planner_budget=None,
        max_plan_tasks=5,
        no_history=False,
    )
    if planner_provider == "codex":
        codex_binary = _preflight_codex_binary(
            explicit=None,
            configured=codex_binary,
            announce=True,
        )
    if plan_only:
        planner = (
            CodexPlannerAdapter(
                state / "planner-live", binary=codex_binary or "codex", model=planner_model
            )
            if planner_provider == "codex"
            else None
        )
        outcome = PlanningEngine(state, planner=planner).plan_request(request, config)
        _show_plan(outcome.plan)
        return
    manifest, compiled_path = _prepare_work_request(
        request,
        state=state,
        config=config,
        policy="single",
        plan_mode="auto",
        approve_plan=approve_plan,
        require_plan_approval=False,
        adapter=adapter,
        replay_safe=False,
        planner_provider=planner_provider,
        planner_model=planner_model,
        codex_binary=codex_binary,
        allow_paths=(),
        deny_paths=(),
        use_tui=True,
    )
    if dry_run:
        typer.echo(
            json.dumps(
                {
                    "tasks": [task.id for task in manifest.tasks],
                    "policy": "single",
                    "compiled_manifest": str(compiled_path),
                }
            )
        )
        return
    run_id, verified, failed, human_result, delivery_workspace = _execute_manifest(
        manifest, compiled_path, state=state, policy="single", use_tui=True
    )
    if not human_result:
        typer.echo(
            json.dumps(
                {
                    "run_id": run_id,
                    "verified": verified,
                    "failed": failed,
                    "delivery_workspace": (
                        str(delivery_workspace) if delivery_workspace is not None else None
                    ),
                }
            )
        )
    if failed:
        raise typer.Exit(4)


@app.command()
def reverify(
    run_id: str,
    attempt_id: str = typer.Option(..., "--attempt"),
    manifest_file: Path = typer.Option(..., "--manifest"),
    verifier_python: Path | None = typer.Option(None, "--verifier-python"),
    state_dir: Path | None = typer.Option(None),
) -> None:
    """Run only deterministic verification for one preserved failed attempt."""

    state = _state(state_dir)
    try:
        manifest = load_manifest(manifest_file)
        outcome = asyncio.run(
            SchedulerService(state).reverify(
                manifest,
                manifest_file,
                run_id,
                attempt_id,
                executable_overrides=_verifier_python_mapping(verifier_python),
            )
        )
    except (OSError, ValidationError, ValueError, FirstGreenError) as error:
        typer.echo(f"reverify blocked: {error}", err=True)
        raise typer.Exit(2) from error
    typer.echo(
        json.dumps(
            {
                "run_id": outcome.run_id,
                "attempt_id": outcome.attempt_id,
                "verification_round": outcome.verification_round,
                "verified": outcome.verified,
                "winner_claimed": outcome.winner_claimed,
                "worker_restarted": False,
            }
        )
    )
    if not outcome.verified or not outcome.winner_claimed:
        raise typer.Exit(4)


@app.command()
def status(
    run_id: str = typer.Argument(""),
    json_output: bool = typer.Option(False, "--json"),
    state_dir: Path | None = typer.Option(None),
) -> None:
    """Show one run or the most recent run."""
    repository = SQLiteRepository(_state(state_dir) / "state.db")
    repository.initialize()
    if not run_id:
        with repository.connect() as connection:
            row = connection.execute(
                "SELECT id FROM runs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            typer.echo("no runs")
            return
        run_id = str(row[0])
    if json_output or not default_console().is_terminal:
        typer.echo(json.dumps(run_data(repository, run_id), indent=2))
    else:
        default_console().print(load_run_renderable(repository, run_id))


@app.command()
def logs(
    run_id: str = typer.Argument(""),
    limit: int = typer.Option(200, min=1, max=2000),
    json_output: bool = typer.Option(False, "--json"),
    state_dir: Path | None = typer.Option(None),
) -> None:
    """Show persisted, filtered worker events for one run."""

    repository = SQLiteRepository(_state(state_dir) / "state.db")
    repository.initialize()
    if not run_id:
        with repository.connect() as connection:
            row = connection.execute(
                "SELECT id FROM runs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            typer.echo("no runs")
            return
        run_id = str(row[0])
    events = event_data(repository, run_id, limit=limit)
    if json_output or not default_console().is_terminal:
        typer.echo(json.dumps(events, indent=2))
    else:
        default_console().print(events_renderable(events))


@app.command()
def cancel(
    run_id: str,
    task: str | None = typer.Option(None),
    state_dir: Path | None = typer.Option(None),
) -> None:
    """Persist a conservative cancellation request for a run or task."""
    repository = SQLiteRepository(_state(state_dir) / "state.db")
    repository.initialize()
    with repository.transaction() as connection:
        if task is None:
            cursor = connection.execute(
                "UPDATE runs SET status='cancelled' WHERE id=? AND status='running'", (run_id,)
            )
            connection.execute(
                "UPDATE tasks SET status='cancelled' WHERE run_id=? "
                "AND status NOT IN ('verified','failed','blocked','cancelled')",
                (run_id,),
            )
        else:
            cursor = connection.execute(
                "UPDATE tasks SET status='cancelled' WHERE run_id=? AND task_key=? "
                "AND status NOT IN ('verified','failed','blocked','cancelled')",
                (run_id, task),
            )
    typer.echo(f"cancelled records: {cursor.rowcount}")


@app.command()
def report(
    run_id: str,
    open_report: bool = typer.Option(False, "--open"),
    state_dir: Path | None = typer.Option(None),
) -> None:
    """Generate a standalone static HTML report."""
    state = _state(state_dir)
    path = report_html(
        SQLiteRepository(state / "state.db"), run_id, state / "reports" / run_id / "report.html"
    )
    typer.echo(str(path))
    if open_report:
        webbrowser.open(path.as_uri())


@app.command("export")
def export_command(
    run_id: str,
    format: str = typer.Option(..., "--format"),
    output: Path | None = typer.Option(None),
    state_dir: Path | None = typer.Option(None),
) -> None:
    """Export run evidence as JSON, CSV, or sanitized Chrome trace."""
    state = _state(state_dir)
    repository = SQLiteRepository(state / "state.db")
    if format == "json":
        path = export_json(repository, run_id, output or state / "exports" / f"{run_id}.json")
    elif format == "csv":
        path = export_csv(repository, run_id, output or state / "exports" / f"{run_id}.csv")
    elif format == "trace":
        path = export_trace(
            repository, run_id, output or state / "exports" / f"{run_id}.trace.json"
        )
    else:
        raise typer.BadParameter("format must be json, csv, or trace")
    typer.echo(str(path))


@benchmark_app.command("simulate")
def benchmark_simulate(
    config: Path | None = typer.Argument(None), seed: int = 7, tasks: int = 1000
) -> None:
    """Compare single, always-race, delayed-hedge, and auto on a seeded workload."""
    if config is not None:
        values = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
        seed = int(values.get("seed", seed))
        tasks = int(values.get("tasks", tasks))
    results = [
        simulation_dict(policy=policy, seed=seed, tasks=tasks)
        for policy in ("single", "always-race", "delayed-hedge", "auto")
    ]
    typer.echo(
        json.dumps({"kind": "simulation_not_real_world_claim", "results": results}, indent=2)
    )


@benchmark_app.command("scaling")
def benchmark_scaling(
    manifest_file: Path,
    slots: str = typer.Option("1,2,4", help="Comma-separated root-slot capacities."),
    repetitions: int = typer.Option(1, min=1, max=20),
    output_dir: Path = typer.Option(Path("benchmark-results")),
    write_figure: bool = typer.Option(
        True,
        "--write-figure/--no-write-figure",
        help="Write a speedup figure; requires a valid one-slot baseline.",
    ),
    scale_verifier_slots: bool = typer.Option(
        True,
        "--scale-verifier-slots/--preserve-verifier-slots",
        help="Scale verifier capacity with root slots or preserve the frozen Manifest value.",
    ),
) -> None:
    """Replay one frozen production manifest across root-slot capacities."""

    capacities = tuple(int(value.strip()) for value in slots.split(",") if value.strip())
    manifest = load_manifest(manifest_file)
    results = asyncio.run(
        run_scaling_matrix(
            manifest,
            frozen_manifest_path=manifest_file,
            state_root=output_dir / "runs",
            journal_path=output_dir / "raw.jsonl",
            slots=capacities,
            repetitions=repetitions,
            scale_verifier_slots=scale_verifier_slots,
        )
    )
    summary = output_dir / "summary.json"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(json.dumps(results, indent=2), encoding="utf-8")
    if write_figure:
        write_scaling_svg(results, output_dir / "scaling.svg")
    typer.echo(str(summary))


def normalize_cli_args(arguments: list[str]) -> list[str]:
    """Route the installed ``fg`` shorthand to the interactive request command."""

    if not arguments:
        return ["request"]
    if arguments == ["--version"]:
        return ["version"]
    first = arguments[0]
    if first in COMMANDS or first.startswith("-"):
        return arguments
    return ["request", *arguments]


def main() -> None:
    app(args=normalize_cli_args(sys.argv[1:]), prog_name=Path(sys.argv[0]).name)


if __name__ == "__main__":
    main()
