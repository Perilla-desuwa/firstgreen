"""Deterministic adapters that exercise FirstGreen's production execution path."""

import asyncio
import os
import sqlite3
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

import yaml

from firstgreen.adapters.base import (
    AttemptHandle,
    AttemptInspection,
    CancelResult,
    DoctorResult,
    StartAttemptRequest,
    WorkerAdapter,
    WorkerEvent,
)
from firstgreen.adapters.codex_exec import CodexExecAdapter
from firstgreen.config import CommandConfig, Manifest, TaskConfig, VerifyConfig
from firstgreen.planning.models import ApprovedPlan, CandidatePlan
from firstgreen.planning.workflow import plan_to_manifest, render_worker_prompt
from firstgreen.service import SchedulerService, WorkerAdapterFactory
from firstgreen.testbed.models import ExecutionResult

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LIVE_REASONING_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh"}
MIN_LIVE_TIMEOUT_SECONDS = 60
MAX_LIVE_TIMEOUT_SECONDS = 1800


class ScenarioExecutionError(RuntimeError):
    """A fake worker or deterministic repository verifier failed."""


class TimelineEntry(TypedDict):
    time: float
    event: str
    task: str
    role: str
    attempt_id: str


@dataclass(frozen=True)
class ExecutionOutcome:
    result: ExecutionResult
    timeline: list[TimelineEntry]
    run_id: str
    state_dir: Path
    winner_workspaces: dict[str, Path]
    loser_workspaces: dict[str, Path]
    winner_count: int
    main_worktree_unchanged: bool
    delivery_workspace: Path | None
    delivery_verified: bool | None


def _replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise ScenarioExecutionError(f"expected mutation anchor not found in {path}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _append(path: Path, text: str, marker: str) -> None:
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    if marker in current:
        raise ScenarioExecutionError(f"mutation marker already present in {path}: {marker}")
    separator = "" if not current or current.endswith("\n") else "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(current + separator + text.lstrip("\n"), encoding="utf-8")


def _s1(repo: Path, task_id: str) -> None:
    if task_id != "pagination_fix":
        return
    _replace(
        repo / "app/orders/service.py",
        '    if page < 1:\n        raise ValueError("page must be at least 1")\n',
        '    if page < 1:\n        raise ValueError("page must be at least 1")\n'
        '    if page_size < 1:\n        raise ValueError("page_size must be at least 1")\n',
    )
    _append(
        repo / "tests/test_orders.py",
        """

def test_page_size_must_be_positive() -> None:
    for invalid in (0, -1):
        try:
            paginate_orders(orders(), page=1, page_size=invalid)
        except ValueError as error:
            assert "page_size must be" in str(error)
        else:
            raise AssertionError("invalid page size accepted")
""",
        "test_page_size_must_be_positive",
    )


def _s2(repo: Path, task_id: str) -> None:
    if task_id == "cli_version":
        _replace(
            repo / "app/cli.py",
            "from app.main import health\n",
            "from app import __version__\nfrom app.main import health\n",
        )
        _replace(
            repo / "app/cli.py",
            "def run(argv: Sequence[str] | None = None) -> tuple[int, str]:\n"
            "    parser = build_parser()\n",
            "def run(argv: Sequence[str] | None = None) -> tuple[int, str]:\n"
            '    if argv is not None and "--version" in argv:\n'
            "        return 0, __version__\n"
            "    parser = build_parser()\n",
        )
        _append(
            repo / "tests/test_cli.py",
            """

def test_version_option() -> None:
    assert run(["--version"]) == (0, "0.1.0")
""",
            "test_version_option",
        )
    elif task_id == "health_commit":
        _replace(
            repo / "app/main.py",
            "from dataclasses import dataclass, field\n",
            "import os\nfrom dataclasses import dataclass, field\n",
        )
        _replace(
            repo / "app/main.py",
            '    return {"status": "ok"}\n',
            '    return {"status": "ok", "commit": os.getenv("TINYSHOP_COMMIT", "unknown")}\n',
        )
        _replace(
            repo / "tests/test_health.py",
            "from app.main import TinyShopApplication, health\n",
            "import os\n\nfrom app.main import TinyShopApplication, health\n",
        )
        _replace(
            repo / "tests/test_health.py",
            '    assert health() == {"status": "ok"}\n',
            '    os.environ["TINYSHOP_COMMIT"] = "abc123"\n'
            '    assert health() == {"status": "ok", "commit": "abc123"}\n',
        )
        _replace(
            repo / "tests/test_health.py",
            '    assert TinyShopApplication().dispatch("/health") == {"status": "ok"}\n',
            '    os.environ["TINYSHOP_COMMIT"] = "abc123"\n'
            '    assert TinyShopApplication().dispatch("/health") == {\n'
            '        "status": "ok", "commit": "abc123"\n'
            "    }\n",
        )


def _s3_model(repo: Path) -> None:
    _replace(
        repo / "app/models.py",
        "from dataclasses import dataclass, field\n",
        "from dataclasses import dataclass, field\nfrom datetime import datetime\n",
    )
    _append(
        repo / "app/models.py",
        """

@dataclass
class ResetToken:
    value: str
    user_id: str
    expires_at: datetime
    used: bool = False

    def is_valid(self, now: datetime) -> bool:
        return not self.used and now < self.expires_at
""",
        "class ResetToken",
    )


def _s3_email(repo: Path) -> None:
    _append(
        repo / "app/mailer.py",
        """

def send_password_reset(recipient: str, token: str) -> dict[str, str]:
    return send_email(recipient, "Password reset", f"Reset token: {token}")
""",
        "send_password_reset",
    )


def _s3_service(repo: Path) -> None:
    _replace(
        repo / "app/auth/service.py",
        "from dataclasses import dataclass\n",
        "from dataclasses import dataclass\nfrom datetime import datetime, timedelta\n",
    )
    _replace(
        repo / "app/auth/service.py",
        "from app.models import User, UserStore\n",
        "from app.models import ResetToken, User, UserStore\n",
    )
    _append(
        repo / "app/auth/service.py",
        """

def request_reset(store: UserStore, email: str, now: datetime) -> ResetToken:
    user = store.find_by_email(email)
    if user is None:
        raise LookupError("unknown reset user")
    value = f"reset-{user.id}-{int(now.timestamp())}"
    token = ResetToken(value, user.id, now + timedelta(hours=1))
    return token


def confirm_reset(
    store: UserStore, token: ResetToken, value: str, password: str, now: datetime
) -> None:
    if token.value != value or not token.is_valid(now):
        raise ValueError("invalid or expired reset token")
    store.get(token.user_id).replace_password(password)
    token.used = True
""",
        "def request_reset",
    )


def _s3_integration(repo: Path) -> None:
    _replace(
        repo / "app/auth/routes.py",
        "from app.auth.service import authenticate, public_user\n"
        "from app.models import UserStore\n",
        "from datetime import datetime\n\n"
        "from app.auth.service import (\n"
        "    authenticate,\n"
        "    confirm_reset,\n"
        "    public_user,\n"
        "    request_reset,\n"
        ")\n"
        "from app.mailer import send_password_reset\n"
        "from app.models import ResetToken, UserStore\n",
    )
    _append(
        repo / "app/auth/routes.py",
        """

def request_password_reset(store: UserStore, email: str, now: datetime) -> ResetToken:
    token = request_reset(store, email, now)
    send_password_reset(email, token.value)
    return token


def confirm_password_reset(
    store: UserStore, token: ResetToken, value: str, password: str, now: datetime
) -> dict[str, bool]:
    confirm_reset(store, token, value, password, now)
    return {"ok": True}
""",
        "def request_password_reset",
    )
    (repo / "tests/test_password_reset.py").write_text(
        """from datetime import UTC, datetime, timedelta

from app.auth.routes import confirm_password_reset, request_password_reset
from app.mailer import OUTBOX
from app.models import UserStore


NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


def test_password_reset_sends_token_and_updates_password() -> None:
    store = UserStore.with_defaults()
    token = request_password_reset(store, "buyer@example.test", NOW)
    assert token.value in OUTBOX[-1]["body"]
    assert token.expires_at == NOW + timedelta(hours=1)
    assert confirm_password_reset(store, token, token.value, "new-password", NOW) == {"ok": True}
    assert store.get("user-1").password == "new-password"


def test_expired_and_invalid_tokens_are_rejected() -> None:
    store = UserStore.with_defaults()
    token = request_password_reset(store, "buyer@example.test", NOW)
    for value, moment in (("wrong", NOW), (token.value, NOW + timedelta(hours=1))):
        try:
            confirm_password_reset(store, token, value, "new-password", moment)
        except ValueError as error:
            assert "invalid or expired" in str(error)
        else:
            raise AssertionError("invalid reset token accepted")


def test_reset_token_cannot_be_reused() -> None:
    store = UserStore.with_defaults()
    token = request_password_reset(store, "buyer@example.test", NOW)
    confirm_password_reset(store, token, token.value, "new-password", NOW)
    try:
        confirm_password_reset(store, token, token.value, "again-password", NOW)
    except ValueError as error:
        assert "invalid or expired" in str(error)
    else:
        raise AssertionError("used token accepted")
""",
        encoding="utf-8",
    )


def _s3(repo: Path, task_id: str) -> None:
    actions = {
        "reset_token_model": _s3_model,
        "reset_email": _s3_email,
        "reset_service": _s3_service,
        "reset_integration": _s3_integration,
    }
    if task_id in actions:
        actions[task_id](repo)


MUTATIONS = {"S1": _s1, "S2": _s2, "S3": _s3}

DURATIONS = {
    "S1": {"pagination_fix": 0.01},
    "S2": {"cli_version": 0.08, "health_commit": 0.08, "repository_verification": 0.01},
    "S3": {
        "reset_token_model": 0.03,
        "reset_email": 3.0,
        "reset_service": 0.04,
        "reset_integration": 0.01,
    },
    "S4": {"login_audit": 0.05, "reset_audit": 0.05},
}

MARKERS = {
    "S1": {"pagination_fix": ("app/orders/service.py", "page_size must be at least 1")},
    "S2": {
        "cli_version": ("app/cli.py", "--version"),
        "health_commit": ("app/main.py", "TINYSHOP_COMMIT"),
    },
    "S3": {
        "reset_token_model": ("app/models.py", "class ResetToken"),
        "reset_email": ("app/mailer.py", "send_password_reset"),
        "reset_service": ("app/auth/service.py", "def request_reset"),
        "reset_integration": ("tests/test_password_reset.py", "test_reset_token_cannot_be_reused"),
    },
}


class ScenarioWorkerFactory(WorkerAdapterFactory):
    """Create deterministic workers while recording scheduler-observed concurrency."""

    def __init__(self, scenario: str) -> None:
        if scenario not in DURATIONS:
            raise ValueError(f"scenario has no fake execution profile: {scenario}")
        self.scenario = scenario
        self.started_at = time.monotonic()
        self.active = 0
        self.maximum_active = 0
        self.timeline: list[TimelineEntry] = []
        self.adapters: dict[str, ScenarioWorkerAdapter] = {}

    def create(self, manifest: Manifest, attempt_id: str, role: str) -> WorkerAdapter:
        del manifest
        adapter = ScenarioWorkerAdapter(self, attempt_id, role)
        self.adapters[attempt_id] = adapter
        return adapter

    def record(self, event: str, request: StartAttemptRequest, role: str) -> None:
        self.timeline.append(
            {
                "time": time.monotonic() - self.started_at,
                "event": event,
                "task": request.task_id,
                "role": role,
                "attempt_id": request.attempt_id,
            }
        )


class ScenarioWorkerAdapter:
    """Worker contract implementation; the scheduler still owns all verification."""

    def __init__(self, factory: ScenarioWorkerFactory, attempt_id: str, role: str) -> None:
        self.factory = factory
        self.attempt_id = attempt_id
        self.role = role
        self.request: StartAttemptRequest | None = None
        self.cancel_calls = 0
        self.status = "created"

    async def doctor(self) -> DoctorResult:
        return DoctorResult(True, "deterministic TinyShop worker ready", "tinyshop-fake-v1")

    async def start(self, request: StartAttemptRequest) -> AttemptHandle:
        if request.attempt_id != self.attempt_id:
            raise ScenarioExecutionError("worker factory attempt identity mismatch")
        self.request = request
        self.status = "running"
        return AttemptHandle("tinyshop-fake", request.attempt_id, None)

    async def events(self, handle: AttemptHandle) -> AsyncIterator[WorkerEvent]:
        del handle
        if self.request is None:
            raise ScenarioExecutionError("worker was not started")
        request = self.request
        self.factory.active += 1
        self.factory.maximum_active = max(self.factory.maximum_active, self.factory.active)
        self.factory.record("started", request, self.role)
        try:
            await asyncio.sleep(DURATIONS[self.factory.scenario].get(request.task_id, 0.01))
            mutation = MUTATIONS.get(self.factory.scenario)
            if mutation is not None:
                mutation(request.worktree, request.task_id)
            await _normalize_worker_output(request.worktree)
            marker = MARKERS.get(self.factory.scenario, {}).get(request.task_id)
            if marker is not None:
                path, expected = marker
                if expected not in (request.worktree / path).read_text(encoding="utf-8"):
                    raise ScenarioExecutionError(
                        f"fake worker did not produce {self.factory.scenario}/{request.task_id}"
                    )
            self.status = "completed"
            self.factory.record("completed", request, self.role)
            yield WorkerEvent(
                "worker.completed",
                datetime.now(UTC),
                {"status": "completed", "worker": "tinyshop-fake"},
            )
        finally:
            self.factory.active -= 1

    async def cancel(self, handle: AttemptHandle, reason: str) -> CancelResult:
        del handle, reason
        self.cancel_calls += 1
        already_cancelled = self.status == "cancelled"
        self.status = "cancelled"
        return CancelResult(True, "already cancelled" if already_cancelled else "cancelled")

    async def inspect(self, handle: AttemptHandle) -> AttemptInspection:
        del handle
        return AttemptInspection(self.status, 0 if self.status == "completed" else None)


async def _normalize_worker_output(worktree: Path) -> None:
    commands = (
        (sys.executable, "-m", "ruff", "check", "--fix", "--select", "I", "."),
        (sys.executable, "-m", "ruff", "format", "."),
    )
    for command in commands:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=worktree,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode:
            raise ScenarioExecutionError(
                f"fake worker formatter failed: {command!r}\n"
                f"{stdout.decode(errors='replace')}\n{stderr.decode(errors='replace')}"
            )


def _portable_verifier(scenario: str, task: TaskConfig) -> list[CommandConfig]:
    pytest_target: list[str] = []
    ruff_target: list[str] = ["."]
    if scenario == "S1":
        pytest_target = ["tests/test_orders.py"]
        ruff_target = ["app/orders/service.py", "tests/test_orders.py"]
    elif scenario == "S2" and task.id == "cli_version":
        pytest_target = ["tests/test_cli.py"]
        ruff_target = ["app/cli.py", "tests/test_cli.py"]
    elif scenario == "S2" and task.id == "health_commit":
        pytest_target = ["tests/test_health.py"]
        ruff_target = ["app/main.py", "tests/test_health.py"]
    return [
        CommandConfig(argv=[sys.executable, "-m", "pytest", "-q", *pytest_target]),
        CommandConfig(argv=[sys.executable, "-m", "ruff", "check", *ruff_target]),
    ]


def scenario_manifest(
    scenario: str,
    plan: CandidatePlan,
    *,
    adapter: str = "fake",
    replay_safe: bool = False,
    policy: str = "single",
    codex_binary: str = "codex",
    worker_model: str | None = None,
    worker_reasoning: str | None = None,
    timeout_seconds: int = 900,
) -> Manifest:
    """Compile the approved plan through FirstGreen's production manifest compiler."""
    if adapter == "codex_exec":
        if not worker_model:
            raise ValueError("live Codex testbed manifests require an explicit worker model")
        if worker_reasoning not in LIVE_REASONING_EFFORTS:
            raise ValueError("live Codex testbed manifests require a bounded reasoning effort")
        if not MIN_LIVE_TIMEOUT_SECONDS <= timeout_seconds <= MAX_LIVE_TIMEOUT_SECONDS:
            raise ValueError(
                "live Codex timeout must be between "
                f"{MIN_LIVE_TIMEOUT_SECONDS} and {MAX_LIVE_TIMEOUT_SECONDS} seconds"
            )
    approved = ApprovedPlan.model_validate(
        plan.model_copy(update={"approved": True}).model_dump(mode="json")
    )
    manifest = plan_to_manifest(
        approved,
        adapter=adapter,
        replay_safe=replay_safe,
        policy=policy,
    )
    tasks: list[TaskConfig] = []
    for task in manifest.tasks:
        verifier_commands = _portable_verifier(scenario, task)
        plan_task = next(item for item in approved.tasks if item.id == task.id)
        tasks.append(
            task.model_copy(
                update={
                    "prompt": render_worker_prompt(
                        approved,
                        plan_task,
                        task.verify.allowed_changed_paths,
                        verifier_commands=[
                            list(command.argv or []) for command in verifier_commands
                        ],
                    ),
                    "verify": VerifyConfig(
                        commands=verifier_commands,
                        allowed_changed_paths=task.verify.allowed_changed_paths,
                    ),
                    "limits": task.limits.model_copy(update={"max_attempts": 1}),
                }
            )
        )
    adapter_config = dict(manifest.agent_defaults.config)
    if worker_model is not None:
        adapter_config["model"] = worker_model
    if worker_reasoning is not None:
        adapter_config["model_reasoning_effort"] = worker_reasoning
    agent_defaults = manifest.agent_defaults.model_copy(
        update={
            "codex_binary": codex_binary,
            "timeout_seconds": timeout_seconds,
            "max_subagent_threads": 1,
            "config": adapter_config,
        }
    )
    delivery_commands = []
    for command in manifest.verification_defaults.delivery_commands:
        argv = list(command.argv or [])
        if argv and argv[0] == "python":
            argv[0] = sys.executable
        delivery_commands.append(command.model_copy(update={"argv": argv}))
    verification_defaults = manifest.verification_defaults.model_copy(
        update={"delivery_commands": delivery_commands}
    )
    return manifest.model_copy(
        update={
            "tasks": tasks,
            "agent_defaults": agent_defaults,
            "verification_defaults": verification_defaults,
        }
    )


def _git_status(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain=v1"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _maximum_attempt_parallelism(rows: list[sqlite3.Row]) -> int:
    events: list[tuple[datetime, int]] = []
    for row in rows:
        started_at = row["started_at"]
        finished_at = row["finished_at"]
        if started_at is None or finished_at is None:
            continue
        events.append((datetime.fromisoformat(str(started_at)), 1))
        events.append((datetime.fromisoformat(str(finished_at)), -1))
    active = 0
    maximum = 0
    for _, delta in sorted(events, key=lambda event: (event[0], event[1])):
        active += delta
        maximum = max(maximum, active)
    return maximum


async def execute_scenario(
    scenario: str,
    plan: CandidatePlan,
    repo: Path,
    state_dir: Path,
    *,
    worker_factory: WorkerAdapterFactory | None = None,
    adapter: str = "fake",
    use_fake_worker: bool = True,
    codex_binary: str = "codex",
    worker_model: str | None = None,
    worker_reasoning: str | None = None,
    timeout_seconds: int = 900,
    policy: str = "always-race",
) -> ExecutionOutcome:
    """Execute through SchedulerService, real worktrees, verifier and winner transaction."""
    if scenario not in DURATIONS:
        raise ValueError(f"scenario has no fake execution profile: {scenario}")
    before = _git_status(repo)
    manifest = scenario_manifest(
        scenario,
        plan,
        adapter=adapter,
        codex_binary=codex_binary,
        worker_model=worker_model,
        worker_reasoning=worker_reasoning,
        timeout_seconds=timeout_seconds,
        policy=policy,
    )
    if adapter == "codex_exec" and not use_fake_worker and worker_factory is None:
        doctor = await CodexExecAdapter(codex_binary).doctor()
        if not doctor.ok:
            raise ScenarioExecutionError(f"Codex preflight failed: {doctor.message}")
    state_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = state_dir / "manifest.yaml"
    manifest_path.write_text(
        yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    factory = worker_factory
    if factory is None and use_fake_worker:
        factory = ScenarioWorkerFactory(scenario)
    service = SchedulerService(state_dir, worker_factory=factory)
    started = time.monotonic()
    previous_pythonpath = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = os.pathsep.join(
        [str(PROJECT_ROOT / ".deps"), str(PROJECT_ROOT / "src")]
    )
    try:
        outcome = await service.run(manifest, manifest_path, policy)
    finally:
        if previous_pythonpath is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = previous_pythonpath
    elapsed = time.monotonic() - started
    with service.repository.connect() as connection:
        winner_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM task_winners winner "
                "JOIN tasks task ON task.id=winner.task_id WHERE task.run_id=?",
                (outcome.run_id,),
            ).fetchone()[0]
        )
        rows = connection.execute(
            "SELECT task.task_key,attempt.workspace_path,"
            "attempt.started_at,attempt.finished_at,"
            "CASE WHEN task.winner_attempt_id=attempt.id THEN 1 ELSE 0 END AS is_winner "
            "FROM attempts attempt JOIN tasks task ON task.id=attempt.task_id "
            "WHERE task.run_id=?",
            (outcome.run_id,),
        ).fetchall()
        attempt_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM attempts attempt JOIN tasks task ON task.id=attempt.task_id "
                "WHERE task.run_id=?",
                (outcome.run_id,),
            ).fetchone()[0]
        )
        delivery_row = connection.execute(
            "SELECT status FROM deliveries WHERE run_id=?", (outcome.run_id,)
        ).fetchone()
    winners = {
        str(row["task_key"]): Path(str(row["workspace_path"]))
        for row in rows
        if int(row["is_winner"])
    }
    losers = {
        str(row["task_key"]): Path(str(row["workspace_path"]))
        for row in rows
        if not int(row["is_winner"])
    }
    recorded_timeline = list(factory.timeline) if isinstance(factory, ScenarioWorkerFactory) else []
    maximum = _maximum_attempt_parallelism(list(rows))
    return ExecutionOutcome(
        result=ExecutionResult(
            attempt_count=attempt_count,
            verified=outcome.failed == 0 and outcome.verified == len(plan.tasks),
            wall_seconds=elapsed,
            maximum_observed_parallelism=maximum,
            hedges_launched=0,
            winner=None,
            cancelled=[],
        ),
        timeline=recorded_timeline,
        run_id=outcome.run_id,
        state_dir=state_dir,
        winner_workspaces=winners,
        loser_workspaces=losers,
        winner_count=winner_count,
        main_worktree_unchanged=_git_status(repo) == before,
        delivery_workspace=outcome.delivery_workspace,
        delivery_verified=(
            str(delivery_row["status"]) == "verified" if delivery_row is not None else None
        ),
    )
