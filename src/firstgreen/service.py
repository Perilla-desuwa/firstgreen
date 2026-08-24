"""One-shot scheduler service used by the CLI and future daemon."""

import asyncio
import hashlib
import json
import subprocess
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from firstgreen.adapters.base import AttemptHandle, StartAttemptRequest, WorkerAdapter
from firstgreen.adapters.codex_exec import CodexExecAdapter
from firstgreen.adapters.fake import FakePlan, FakeWorkerAdapter
from firstgreen.config import CommandConfig, Manifest, TaskConfig, VerifyConfig
from firstgreen.db.repository import SQLiteRepository
from firstgreen.domain.models import AttemptStatus, RunStatus, TaskStatus
from firstgreen.domain.state_machine import (
    ATTEMPT_TRANSITIONS,
    RUN_TRANSITIONS,
    TASK_TRANSITIONS,
    require_transition,
)
from firstgreen.errors import FirstGreenError, WorkspaceSafetyError
from firstgreen.ids import new_id
from firstgreen.scheduler.concurrency import (
    AIMDController,
    ConcurrencyState,
    HostPressureSignal,
    PressureSignal,
    PressureSnapshot,
    subagent_threads_per_root,
)
from firstgreen.scheduler.queue import ranked_ready_tasks
from firstgreen.scheduler.racing import AttemptOutcome, first_verified_wins
from firstgreen.verifier.feedback import build_repair_prompt, build_verification_feedback
from firstgreen.verifier.runner import (
    CommandVerifier,
    VerificationCommand,
    VerificationRequest,
    VerificationResult,
)
from firstgreen.workspace.dependency_overlay import (
    DependencySnapshot,
    FailedAttemptOverlay,
    RepairWorkspacePreparer,
    VerifiedDependencyOverlay,
    WorkspacePreparer,
)
from firstgreen.workspace.git_worktree import GitWorktreeManager, Workspace, WorkspaceSpec


def default_state_dir() -> Path:
    return Path.home() / ".firstgreen"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@dataclass(frozen=True)
class RunOutcome:
    run_id: str
    verified: int
    failed: int
    delivery_workspace: Path | None = None


@dataclass(frozen=True)
class ReverificationOutcome:
    run_id: str
    attempt_id: str
    verification_round: int
    verified: bool
    winner_claimed: bool


MAX_VERIFICATION_ROUNDS = 3


class WorkerAdapterFactory(Protocol):
    def create(self, manifest: Manifest, attempt_id: str, role: str) -> WorkerAdapter: ...


class SchedulerService:
    def __init__(
        self,
        state_dir: Path,
        pressure_signal: PressureSignal | None = None,
        *,
        worker_factory: WorkerAdapterFactory | None = None,
        workspace_preparer: WorkspacePreparer | None = None,
        repair_workspace_preparer: RepairWorkspacePreparer | None = None,
    ) -> None:
        self.state_dir = state_dir.resolve()
        self.repository = SQLiteRepository(self.state_dir / "state.db")
        self.repository.initialize()
        self.pressure_signal = pressure_signal or HostPressureSignal()
        self.worker_factory = worker_factory
        self.workspace_preparer = workspace_preparer or VerifiedDependencyOverlay()
        self.repair_workspace_preparer = repair_workspace_preparer or FailedAttemptOverlay()
        self._root_semaphore = asyncio.Semaphore(1)
        self._verifier_semaphore = asyncio.Semaphore(1)
        self._resource_semaphores: dict[str, asyncio.Semaphore] = {}
        self._active_task_futures: set[asyncio.Task[bool]] = set()
        self._ready_work_count = 0

    @asynccontextmanager
    async def _task_resources(self, task: TaskConfig) -> AsyncIterator[None]:
        semaphores = [
            self._resource_semaphores.setdefault(resource.key, asyncio.Semaphore(resource.capacity))
            for resource in sorted(task.resources, key=lambda item: item.key)
        ]
        for semaphore in semaphores:
            await semaphore.acquire()
        try:
            yield
        finally:
            for semaphore in reversed(semaphores):
                semaphore.release()

    async def run(
        self,
        manifest: Manifest,
        manifest_path: Path,
        policy: str,
        *,
        run_id: str | None = None,
    ) -> RunOutcome:
        run_id = run_id or new_id("run")
        self._verifier_semaphore = asyncio.Semaphore(manifest.scheduler.concurrency.verifier_slots)
        try:
            return await self._run_started(manifest, manifest_path, policy, run_id)
        except asyncio.CancelledError:
            active = tuple(self._active_task_futures)
            for future in active:
                future.cancel()
            if active:
                await asyncio.gather(*active, return_exceptions=True)
                self._active_task_futures.difference_update(active)
            finished = datetime.now(UTC).isoformat()
            with self.repository.transaction() as connection:
                connection.execute(
                    "UPDATE attempts SET status='cancelled',finished_at=COALESCE(finished_at,?) "
                    "WHERE task_id IN (SELECT id FROM tasks WHERE run_id=?) "
                    "AND status IN ('starting','running','verifying','agent_completed')",
                    (finished, run_id),
                )
                connection.execute(
                    "UPDATE tasks SET status='cancelled' WHERE run_id=? "
                    "AND winner_attempt_id IS NULL "
                    "AND status NOT IN ('failed','blocked','cancelled')",
                    (run_id,),
                )
                connection.execute(
                    "UPDATE runs SET status='cancelled',finished_at=? "
                    "WHERE id=? AND status='running'",
                    (finished, run_id),
                )
            self.repository.append_event(
                new_id("event"),
                "scheduler.run_cancelled",
                finished,
                {"reason": "scheduler coroutine cancelled"},
                run_id=run_id,
            )
            raise

    async def reverify(
        self,
        manifest: Manifest,
        manifest_path: Path,
        run_id: str,
        attempt_id: str,
        *,
        executable_overrides: dict[str, str] | None = None,
    ) -> ReverificationOutcome:
        """Run deterministic verification for one preserved failed attempt.

        This path never starts a worker. It deliberately supports only a terminal
        single-task run until scheduler resume semantics exist for a partial DAG. It
        also recovers an attempt that failed after its worker exited but before the
        first scheduler-owned verification could start.
        """

        self._verifier_semaphore = asyncio.Semaphore(manifest.scheduler.concurrency.verifier_slots)
        manifest_path = manifest_path.expanduser().resolve()
        manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT r.manifest_hash,r.repo_path,r.base_sha,r.status AS run_status,"
                "t.id AS task_id,t.task_key,t.status AS task_status,t.winner_attempt_id,"
                "a.status AS attempt_status,a.workspace_path,a.branch,"
                "a.base_sha AS attempt_base_sha,"
                "(SELECT COUNT(*) FROM tasks rt WHERE rt.run_id=r.id) AS task_count,"
                "COALESCE((SELECT MAX(v.verification_round) FROM verification_runs v "
                "WHERE v.attempt_id=a.id),0) AS previous_rounds "
                "FROM runs r JOIN tasks t ON t.run_id=r.id JOIN attempts a ON a.task_id=t.id "
                "WHERE r.id=? AND a.id=?",
                (run_id, attempt_id),
            ).fetchone()
        if row is None:
            raise ValueError("run/attempt pair not found")
        if str(row["manifest_hash"]) != manifest_hash:
            raise ValueError("manifest bytes do not match the original run")
        if int(row["task_count"]) != 1 or len(manifest.tasks) != 1:
            raise ValueError("reverify currently supports terminal single-task runs only")
        if int(row["previous_rounds"]) >= MAX_VERIFICATION_ROUNDS:
            raise ValueError(f"verification hard limit reached: {MAX_VERIFICATION_ROUNDS} rounds")
        repo = Path(str(row["repo_path"])).expanduser().resolve()
        if manifest.project.repo.expanduser().resolve() != repo:
            raise ValueError("manifest repository does not match the original run")
        if _git(repo, "rev-parse", f"{manifest.project.base_ref}^{{commit}}") != str(
            row["base_sha"]
        ):
            raise ValueError("manifest base ref no longer resolves to the original run SHA")
        task = manifest.tasks[0]
        if task.id != str(row["task_key"]):
            raise ValueError("manifest task does not match the persisted attempt")
        if str(row["attempt_base_sha"]) != str(row["base_sha"]):
            raise ValueError("attempt base SHA does not match the original run")
        if row["workspace_path"] is None or row["branch"] is None:
            raise WorkspaceSafetyError("attempt has no persisted workspace identity")

        task_id = str(row["task_id"])
        with self.repository.transaction() as connection:
            current = connection.execute(
                "SELECT r.status,t.status,a.status,t.winner_attempt_id "
                "FROM runs r JOIN tasks t ON t.run_id=r.id JOIN attempts a ON a.task_id=t.id "
                "WHERE r.id=? AND t.id=? AND a.id=?",
                (run_id, task_id, attempt_id),
            ).fetchone()
            if current is None or tuple(current) != ("failed", "failed", "failed", None):
                raise ValueError("only a failed run/task/attempt with no winner can be reverified")
            require_transition(RunStatus.FAILED, RunStatus.RUNNING, RUN_TRANSITIONS)
            require_transition(TaskStatus.FAILED, TaskStatus.VERIFYING, TASK_TRANSITIONS)
            require_transition(AttemptStatus.FAILED, AttemptStatus.VERIFYING, ATTEMPT_TRANSITIONS)
            connection.execute(
                "UPDATE runs SET status='running',finished_at=NULL WHERE id=?", (run_id,)
            )
            connection.execute("UPDATE tasks SET status='verifying' WHERE id=?", (task_id,))
            connection.execute(
                "UPDATE attempts SET status='verifying',finished_at=NULL WHERE id=?",
                (attempt_id,),
            )

        previous_rounds = int(row["previous_rounds"])
        self.repository.record_decision(
            decision_id=new_id("decision"),
            run_id=run_id,
            task_id=task_id,
            attempt_id=attempt_id,
            decision_type="manual_reverification",
            signals={
                "reason": "explicit_user_request",
                "previous_rounds": previous_rounds,
                "initial_verification_recovery": previous_rounds == 0,
                "worker_restarted": False,
            },
            policy_version="reverify-v1",
            policy_snapshot={
                "maximum_rounds": MAX_VERIFICATION_ROUNDS,
                "single_task_only": True,
                "manifest_hash_required": True,
                "workspace_identity_required": True,
                "initial_verification_recovery": previous_rounds == 0,
            },
            timestamp=datetime.now(UTC).isoformat(),
        )
        self.repository.append_event(
            new_id("event"),
            "verifier.reverification_started",
            datetime.now(UTC).isoformat(),
            {"previous_rounds": previous_rounds, "worker_restarted": False},
            run_id=run_id,
            task_id=task_id,
            attempt_id=attempt_id,
        )

        workspace = Workspace(
            attempt_id,
            Path(str(row["workspace_path"])).resolve(),
            str(row["branch"]),
            repo,
            str(row["base_sha"]),
            run_id,
            task.id,
            attempt_id,
        )
        manager = GitWorktreeManager(self.state_dir / "worktrees", keep_winner=True)
        try:
            if not self.repository.workspace_identity_matches(
                attempt_id=attempt_id,
                path=str(workspace.path),
                branch=workspace.branch,
                base_sha=workspace.base_sha,
            ):
                raise WorkspaceSafetyError("database workspace identity mismatch")
            workspace_status = await manager.inspect(workspace)
            if not (
                workspace_status.exists
                and workspace_status.marker_valid
                and workspace_status.registered
            ):
                raise WorkspaceSafetyError(
                    "reverify requires an existing registered worktree with a matching marker"
                )
            commands = self._verification_commands(task, manifest)
            verification = await self._verify_workspace(
                manifest,
                task,
                workspace,
                commands,
                executable_overrides=executable_overrides,
                run_id=run_id,
                task_id=task_id,
            )
            verification_round = self._persist_verification(
                run_id, task_id, attempt_id, commands, verification
            )
        except asyncio.CancelledError:
            self._finish_reverification_failure(run_id, task_id, attempt_id)
            self._append_reverification_failure_event(run_id, task_id, attempt_id, "CancelledError")
            raise
        except Exception as error:
            self._finish_reverification_failure(run_id, task_id, attempt_id)
            self._append_reverification_failure_event(
                run_id, task_id, attempt_id, type(error).__name__
            )
            raise

        finished = datetime.now(UTC).isoformat()
        if not verification.passed:
            self._finish_reverification_failure(run_id, task_id, attempt_id, finished=finished)
            self.repository.append_event(
                new_id("event"),
                "verifier.reverification_completed",
                finished,
                {"passed": False, "verification_round": verification_round},
                run_id=run_id,
                task_id=task_id,
                attempt_id=attempt_id,
            )
            return ReverificationOutcome(run_id, attempt_id, verification_round, False, False)

        require_transition(AttemptStatus.VERIFYING, AttemptStatus.PASSED, ATTEMPT_TRANSITIONS)
        require_transition(TaskStatus.VERIFYING, TaskStatus.VERIFIED, TASK_TRANSITIONS)
        require_transition(RunStatus.RUNNING, RunStatus.COMPLETED, RUN_TRANSITIONS)
        with self.repository.transaction() as connection:
            connection.execute(
                "UPDATE attempts SET status='passed',finished_at=? WHERE id=?",
                (finished, attempt_id),
            )
        winner_claimed = self.repository.claim_winner(task_id, attempt_id, finished)
        with self.repository.transaction() as connection:
            connection.execute(
                "UPDATE runs SET status=?,finished_at=? WHERE id=?",
                ("completed" if winner_claimed else "failed", finished, run_id),
            )
            if not winner_claimed:
                connection.execute(
                    "UPDATE attempts SET status='superseded' WHERE id=? AND status='passed'",
                    (attempt_id,),
                )
        self.repository.append_event(
            new_id("event"),
            "verifier.reverification_completed",
            finished,
            {
                "passed": True,
                "verification_round": verification_round,
                "winner_claimed": winner_claimed,
            },
            run_id=run_id,
            task_id=task_id,
            attempt_id=attempt_id,
        )
        return ReverificationOutcome(run_id, attempt_id, verification_round, True, winner_claimed)

    def _finish_reverification_failure(
        self,
        run_id: str,
        task_id: str,
        attempt_id: str,
        *,
        finished: str | None = None,
    ) -> None:
        timestamp = finished or datetime.now(UTC).isoformat()
        with self.repository.transaction() as connection:
            connection.execute(
                "UPDATE attempts SET status='failed',finished_at=? "
                "WHERE id=? AND status='verifying'",
                (timestamp, attempt_id),
            )
            connection.execute(
                "UPDATE tasks SET status='failed' WHERE id=? AND status='verifying' "
                "AND winner_attempt_id IS NULL",
                (task_id,),
            )
            connection.execute(
                "UPDATE runs SET status='failed',finished_at=? WHERE id=? AND status='running'",
                (timestamp, run_id),
            )

    def _append_reverification_failure_event(
        self, run_id: str, task_id: str, attempt_id: str, error_kind: str
    ) -> None:
        self.repository.append_event(
            new_id("event"),
            "verifier.reverification_failed",
            datetime.now(UTC).isoformat(),
            {"error_kind": error_kind},
            run_id=run_id,
            task_id=task_id,
            attempt_id=attempt_id,
        )

    async def _run_started(
        self,
        manifest: Manifest,
        manifest_path: Path,
        policy: str,
        run_id: str,
    ) -> RunOutcome:
        repo = manifest.project.repo.expanduser().resolve()
        base_sha = _git(repo, "rev-parse", f"{manifest.project.base_ref}^{{commit}}")
        manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        now = datetime.now(UTC).isoformat()
        policy_snapshot = {
            "selected": policy,
            "concurrency": manifest.scheduler.concurrency.model_dump(mode="json"),
            "hedge": manifest.scheduler.hedge.model_dump(mode="json"),
            "planning": manifest.planning_record,
            "repository_view": (
                manifest.repository_view.model_dump(mode="json")
                if manifest.repository_view is not None
                else None
            ),
            "verification_environment": manifest.verification_defaults.environment_snapshot,
        }
        task_ids = {task.id: new_id("task") for task in manifest.tasks}
        with self.repository.transaction() as connection:
            connection.execute(
                "INSERT INTO runs(id,manifest_hash,repo_path,base_sha,policy_snapshot,status,"
                "created_at,started_at) VALUES(?,?,?,?,?,'running',?,?)",
                (run_id, manifest_hash, str(repo), base_sha, json.dumps(policy_snapshot), now, now),
            )
            for task in manifest.tasks:
                status = "ready" if not task.dependencies else "queued"
                connection.execute(
                    "INSERT INTO tasks(id,run_id,task_key,prompt,replay_safe,status) "
                    "VALUES(?,?,?,?,?,?)",
                    (
                        task_ids[task.id],
                        run_id,
                        task.id,
                        task.prompt,
                        int(task.replay_safe),
                        status,
                    ),
                )
            for task in manifest.tasks:
                connection.executemany(
                    "INSERT INTO task_dependencies(task_id,dependency_id) VALUES(?,?)",
                    [(task_ids[task.id], task_ids[dependency]) for dependency in task.dependencies],
                )
        pending = {task.id: task for task in manifest.tasks}
        verified_keys: set[str] = set()
        failed = 0
        concurrency_config = manifest.scheduler.concurrency
        self._root_semaphore = asyncio.Semaphore(concurrency_config.max_root)
        controller = AIMDController(cooldown_seconds=concurrency_config.cooldown_seconds)
        concurrency_state = ConcurrencyState(
            concurrency_config.initial_root,
            concurrency_config.min_root,
            concurrency_config.max_root,
            datetime.now(UTC) - timedelta(seconds=concurrency_config.cooldown_seconds),
        )
        running: dict[asyncio.Task[bool], TaskConfig] = {}
        while pending or running:
            ranked_ready = ranked_ready_tasks(
                list(pending.values()),
                verified_keys,
                policy=manifest.scheduler.ready_queue_policy,
                all_tasks=manifest.tasks,
            )
            ready = [item.task for item in ranked_ready]
            self._ready_work_count = len(ready)
            self.repository.append_event(
                new_id("event"),
                "scheduler.ready_set",
                datetime.now(UTC).isoformat(),
                {
                    "ready_task_keys": [task.id for task in ready],
                    "pending_count": len(pending),
                    "running_count": len(running),
                },
                run_id=run_id,
            )
            if not ready and not running:
                with self.repository.transaction() as connection:
                    for task in pending.values():
                        connection.execute(
                            "UPDATE tasks SET status='blocked' WHERE id=?", (task_ids[task.id],)
                        )
                failed += len(pending)
                break
            if concurrency_config.mode == "auto":
                host = self.pressure_signal.sample()
                snapshot = PressureSnapshot(
                    backlog=len(pending),
                    completed_samples=len(verified_keys) + failed,
                    rate_limit_errors=host.rate_limit_errors,
                    spawn_errors=host.spawn_errors,
                    verifier_queue_wait_seconds=host.verifier_queue_wait_seconds,
                    memory_percent=host.memory_percent,
                    normalized_load=host.normalized_load,
                    cancellation_backlog=host.cancellation_backlog,
                )
                concurrency_state, decision = controller.decide(
                    concurrency_state, snapshot, datetime.now(UTC), mode="auto"
                )
                self.repository.record_decision(
                    decision_id=new_id("decision"),
                    run_id=run_id,
                    decision_type="root_concurrency",
                    signals={
                        **decision.signals,
                        "reason": decision.reason,
                        "old_root": decision.old_root,
                        "new_root": decision.new_root,
                    },
                    policy_version=decision.policy_version,
                    policy_snapshot=concurrency_config.model_dump(mode="json"),
                    timestamp=datetime.now(UTC).isoformat(),
                )
            limit = concurrency_state.current_root
            capacity = max(0, limit - len(running))
            granted_threads = subagent_threads_per_root(
                total_agent_threads=concurrency_config.total_agent_thread_budget,
                max_root=concurrency_config.max_root,
                configured_max_subagents=manifest.agent_defaults.max_subagent_threads,
            )
            active_resources = {
                resource.key for task in running.values() for resource in task.resources
            }
            selected = []
            selected_resources: set[str] = set()
            for ranked in ranked_ready:
                resources = {resource.key for resource in ranked.task.resources}
                conflicts = resources & (active_resources | selected_resources)
                if conflicts:
                    self.repository.record_decision(
                        decision_id=new_id("decision"),
                        run_id=run_id,
                        task_id=task_ids[ranked.task.id],
                        decision_type="admission_hold",
                        signals={
                            "task_key": ranked.task.id,
                            "reason": "resource_conflict",
                            "resources": sorted(conflicts),
                            "ready_count": len(ranked_ready),
                        },
                        policy_version="admission-v1",
                        policy_snapshot={
                            "root_limit": limit,
                            "thread_budget": concurrency_config.total_agent_thread_budget,
                        },
                        timestamp=datetime.now(UTC).isoformat(),
                    )
                    continue
                selected.append(ranked)
                selected_resources.update(resources)
                if len(selected) >= capacity:
                    break
            for position, ranked in enumerate(selected, start=1):
                task = ranked.task
                pending.pop(task.id)
                self.repository.record_decision(
                    decision_id=new_id("decision"),
                    run_id=run_id,
                    task_id=task_ids[task.id],
                    decision_type="ready_queue_select",
                    signals={
                        "task_key": task.id,
                        "position": position,
                        "ready_count": len(ranked_ready),
                        "bottom_level_seconds": ranked.bottom_level_seconds,
                        "manifest_priority": task.priority,
                    },
                    policy_version="ready-queue-v1",
                    policy_snapshot={
                        "policy": manifest.scheduler.ready_queue_policy,
                        "stable_fallback": "stable",
                        "estimate_source": task.estimate_source,
                    },
                    timestamp=datetime.now(UTC).isoformat(),
                )
                self.repository.append_event(
                    new_id("event"),
                    "scheduler.task_admitted",
                    datetime.now(UTC).isoformat(),
                    {
                        "task_key": task.id,
                        "bottom_level_seconds": ranked.bottom_level_seconds,
                        "root_limit": limit,
                    },
                    run_id=run_id,
                    task_id=task_ids[task.id],
                )
                future = asyncio.create_task(
                    self._run_task(
                        run_id,
                        task_ids[task.id],
                        task,
                        manifest,
                        repo,
                        base_sha,
                        policy,
                        granted_threads,
                    ),
                    name=f"firstgreen-task:{task.id}",
                )
                running[future] = task
                self._active_task_futures.add(future)
            if not running:
                continue
            done, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            for future in done:
                task = running.pop(future)
                self._active_task_futures.discard(future)
                if future.result():
                    verified_keys.add(task.id)
                    result = "verified"
                else:
                    failed += 1
                    result = "failed"
                self.repository.append_event(
                    new_id("event"),
                    "scheduler.task_finished",
                    datetime.now(UTC).isoformat(),
                    {"task_key": task.id, "result": result},
                    run_id=run_id,
                    task_id=task_ids[task.id],
                )
        delivery_workspace: Path | None = None
        if failed == 0 and len(manifest.tasks) > 1:
            delivery_workspace, delivery_verified = await self._finalize_delivery(
                run_id,
                manifest,
                repo,
                base_sha,
            )
            if not delivery_verified:
                failed += 1
        finished = datetime.now(UTC).isoformat()
        with self.repository.transaction() as connection:
            connection.execute(
                "UPDATE runs SET status=?,finished_at=? WHERE id=?",
                ("completed" if failed == 0 else "failed", finished, run_id),
            )
        return RunOutcome(run_id, len(verified_keys), failed, delivery_workspace)

    def _delivery_snapshots(
        self, run_id: str, manifest: Manifest
    ) -> tuple[DependencySnapshot, ...]:
        dependency_keys = {
            dependency for task in manifest.tasks for dependency in task.dependencies
        }
        sink_keys = sorted(task.id for task in manifest.tasks if task.id not in dependency_keys)
        task_by_key = {task.id: task for task in manifest.tasks}
        placeholders = ",".join("?" for _ in sink_keys)
        with self.repository.connect() as connection:
            rows = connection.execute(
                "SELECT task.task_key,attempt.workspace_path,attempt.base_sha "
                "FROM tasks task JOIN attempts attempt ON attempt.id=task.winner_attempt_id "
                f"WHERE task.run_id=? AND task.task_key IN ({placeholders}) "
                "ORDER BY task.task_key",
                (run_id, *sink_keys),
            ).fetchall()
        if len(rows) != len(sink_keys):
            raise WorkspaceSafetyError("delivery requires one verified winner for every DAG sink")
        return tuple(
            DependencySnapshot(
                task_by_key[str(row["task_key"])],
                Path(str(row["workspace_path"])).resolve(),
                str(row["base_sha"]),
            )
            for row in rows
        )

    @staticmethod
    def _delivery_task(manifest: Manifest) -> TaskConfig:
        commands: list[CommandConfig] = []
        seen: set[str] = set()
        command_groups = (
            [manifest.verification_defaults.delivery_commands]
            if manifest.verification_defaults.delivery_commands
            else [task.verify.commands for task in manifest.tasks]
        )
        for group in command_groups:
            for command in group:
                key = command.model_dump_json()
                if key not in seen:
                    seen.add(key)
                    commands.append(command)
        path_sets = [task.verify.allowed_changed_paths for task in manifest.tasks]
        allowed_paths = (
            []
            if any(not paths for paths in path_sets)
            else sorted({path for paths in path_sets for path in paths})
        )
        return TaskConfig(
            id="__firstgreen_delivery__",
            prompt="Scheduler-owned final delivery composition",
            replay_safe=False,
            verify=VerifyConfig(
                commands=commands,
                allowed_changed_paths=allowed_paths,
            ),
        )

    async def _finalize_delivery(
        self,
        run_id: str,
        manifest: Manifest,
        repo: Path,
        base_sha: str,
    ) -> tuple[Path | None, bool]:
        delivery_id = new_id("delivery")
        created_at = datetime.now(UTC).isoformat()
        with self.repository.transaction() as connection:
            connection.execute(
                "INSERT INTO deliveries(id,run_id,status,base_sha,created_at) "
                "VALUES(?,?,'assembling',?,?)",
                (delivery_id, run_id, base_sha, created_at),
            )
        self.repository.append_event(
            new_id("event"),
            "delivery.assembling",
            created_at,
            {"delivery_id": delivery_id},
            run_id=run_id,
        )
        manager = GitWorktreeManager(self.state_dir / "worktrees", keep_winner=True)
        workspace: Workspace | None = None
        try:
            workspace = await manager.create_attempt_workspace(
                WorkspaceSpec(run_id, "__delivery__", delivery_id, repo, base_sha)
            )
            with self.repository.transaction() as connection:
                connection.execute(
                    "UPDATE deliveries SET workspace_path=?,branch=? WHERE id=?",
                    (str(workspace.path), workspace.branch, delivery_id),
                )
            snapshots = self._delivery_snapshots(run_id, manifest)
            if any(snapshot.base_sha != workspace.base_sha for snapshot in snapshots):
                raise WorkspaceSafetyError("delivery sinks do not share the run base SHA")
            await self.workspace_preparer.prepare(workspace, snapshots)
            task = self._delivery_task(manifest)
            commands = self._verification_commands(task, manifest)
            with self.repository.transaction() as connection:
                connection.execute(
                    "UPDATE deliveries SET status='verifying' WHERE id=?", (delivery_id,)
                )
            verification = await self._verify_workspace(
                manifest, task, workspace, commands, run_id=run_id
            )
            self._persist_delivery_verification(
                run_id,
                delivery_id,
                commands,
                verification,
            )
            verified_at = datetime.now(UTC).isoformat() if verification.passed else None
            with self.repository.transaction() as connection:
                connection.execute(
                    "UPDATE deliveries SET status=?,diff_hash=?,verified_at=? WHERE id=?",
                    (
                        "verified" if verification.passed else "failed",
                        verification.diff_hash,
                        verified_at,
                        delivery_id,
                    ),
                )
            self.repository.append_event(
                new_id("event"),
                "delivery.finished",
                datetime.now(UTC).isoformat(),
                {"delivery_id": delivery_id, "verified": verification.passed},
                run_id=run_id,
            )
            return workspace.path, verification.passed
        except asyncio.CancelledError:
            with self.repository.transaction() as connection:
                connection.execute(
                    "UPDATE deliveries SET status='cancelled',error_kind='CancelledError' "
                    "WHERE id=?",
                    (delivery_id,),
                )
            if workspace is not None:
                await manager.cleanup(workspace)
            raise
        except (OSError, ValueError, FirstGreenError) as error:
            with self.repository.transaction() as connection:
                connection.execute(
                    "UPDATE deliveries SET status='failed',error_kind=? WHERE id=?",
                    (type(error).__name__, delivery_id),
                )
            self.repository.append_event(
                new_id("event"),
                "delivery.failed",
                datetime.now(UTC).isoformat(),
                {"error_kind": type(error).__name__},
                run_id=run_id,
            )
            return workspace.path if workspace is not None else None, False

    async def _run_task(
        self,
        run_id: str,
        task_id: str,
        task: TaskConfig,
        manifest: Manifest,
        repo: Path,
        base_sha: str,
        policy: str,
        granted_threads: int,
    ) -> bool:
        async with self._task_resources(task):
            return await self._run_task_with_resources(
                run_id,
                task_id,
                task,
                manifest,
                repo,
                base_sha,
                policy,
                granted_threads,
            )

    async def _run_task_with_resources(
        self,
        run_id: str,
        task_id: str,
        task: TaskConfig,
        manifest: Manifest,
        repo: Path,
        base_sha: str,
        policy: str,
        granted_threads: int,
    ) -> bool:
        manager = GitWorktreeManager(self.state_dir / "worktrees", keep_winner=True)
        primary_id = new_id("attempt")
        primary_workspace = None
        try:
            primary_workspace = await manager.create_attempt_workspace(
                WorkspaceSpec(run_id, task.id, primary_id, repo, base_sha)
            )
            dependencies = self._dependency_winners(task_id, manifest)
            await self.workspace_preparer.prepare(primary_workspace, dependencies)
        except (OSError, ValueError, FirstGreenError) as error:
            if primary_workspace is not None:
                await manager.cleanup(primary_workspace)
            with self.repository.transaction() as connection:
                connection.execute("UPDATE tasks SET status='failed' WHERE id=?", (task_id,))
            self.repository.record_decision(
                decision_id=new_id("decision"),
                run_id=run_id,
                task_id=task_id,
                decision_type="dependency_prepare_failed",
                signals={"error_kind": type(error).__name__},
                policy_version="workspace-safety-v1",
                policy_snapshot={"path_bounded": True},
                timestamp=datetime.now(UTC).isoformat(),
            )
            return False
        assert primary_workspace is not None
        with self.repository.transaction() as connection:
            connection.execute("UPDATE tasks SET status='running' WHERE id=?", (task_id,))

        effective_policy = policy
        policy_reason = "requested_policy"
        if policy in {"delayed-hedge", "auto"} and not manifest.scheduler.hedge.enabled:
            effective_policy = "single"
            policy_reason = "hedging_disabled"
        elif policy in {"delayed-hedge", "auto"} and manifest.scheduler.hedge.max_replicas < 1:
            effective_policy = "single"
            policy_reason = "max_replicas_reached"
        elif policy in {"delayed-hedge", "auto"} and (
            manifest.scheduler.budgets.max_hedge_estimated_usd == 0
        ):
            effective_policy = "single"
            policy_reason = "hedge_budget_exhausted"
        elif policy in {"delayed-hedge", "auto", "always-race"} and (task.limits.max_attempts < 2):
            effective_policy = "single"
            policy_reason = "attempt_limit_reached"
        elif policy in {"delayed-hedge", "auto", "always-race"} and not task.replay_safe:
            effective_policy = "single"
            policy_reason = "task_not_replay_safe"
        self.repository.record_decision(
            decision_id=new_id("decision"),
            run_id=run_id,
            task_id=task_id,
            decision_type="attempt_policy",
            signals={
                "requested_policy": policy,
                "effective_policy": effective_policy,
                "replay_safe": task.replay_safe,
                "hedge_enabled": manifest.scheduler.hedge.enabled,
                "max_replicas": manifest.scheduler.hedge.max_replicas,
            },
            policy_version="hedge-v1",
            policy_snapshot=manifest.scheduler.hedge.model_dump(mode="json"),
            timestamp=datetime.now(UTC).isoformat(),
        )

        async def primary() -> AttemptOutcome:
            async with self._root_semaphore:
                return await self._execute_attempt(
                    run_id,
                    task_id,
                    task,
                    manifest,
                    manager,
                    primary_workspace,
                    ordinal=1,
                    role="primary",
                    granted_threads=granted_threads,
                )

        async def backup() -> AttemptOutcome:
            backup_id = new_id("attempt")
            workspace = await manager.create_backup_workspace(
                primary_workspace, attempt_id=backup_id
            )
            await self.workspace_preparer.prepare(workspace, dependencies)
            async with self._root_semaphore:
                return await self._execute_attempt(
                    run_id,
                    task_id,
                    task,
                    manifest,
                    manager,
                    workspace,
                    ordinal=2,
                    role="hedge",
                    granted_threads=granted_threads,
                )

        hedge_delay = manifest.scheduler.hedge.fallback_after_seconds
        result = await first_verified_wins(
            primary,
            backup,
            lambda attempt_id: self.repository.claim_winner(
                task_id, attempt_id, datetime.now(UTC).isoformat()
            ),
            policy=effective_policy,
            replay_safe=task.replay_safe,
            hedge_delay_seconds=hedge_delay if hedge_delay is not None else float("inf"),
        )
        if result.launched_backup:
            self.repository.record_decision(
                decision_id=new_id("decision"),
                run_id=run_id,
                task_id=task_id,
                attempt_id=result.winner_attempt_id,
                decision_type="launch_hedge",
                signals={
                    "threshold_seconds": hedge_delay,
                    "reason": policy_reason,
                    "ready_work_pending": self._ready_work_count,
                    "slot_competition": "shared_root_semaphore",
                },
                policy_version="hedge-v1",
                policy_snapshot=manifest.scheduler.hedge.model_dump(mode="json"),
                timestamp=datetime.now(UTC).isoformat(),
            )
        if result.winner_attempt_id is not None:
            return True
        attempts_used = 1 + int(result.launched_backup)
        attempt_workspaces = {primary_workspace.attempt_id: primary_workspace}
        if result.launched_backup:
            with self.repository.connect() as connection:
                row = connection.execute(
                    "SELECT id,workspace_path,branch,base_sha FROM attempts "
                    "WHERE task_id=? AND ordinal=2",
                    (task_id,),
                ).fetchone()
            if row is not None and row["workspace_path"] is not None and row["branch"] is not None:
                attempt_workspaces[str(row["id"])] = Workspace(
                    str(row["id"]),
                    Path(str(row["workspace_path"])).resolve(),
                    str(row["branch"]),
                    repo,
                    str(row["base_sha"]),
                    run_id,
                    task.id,
                    str(row["id"]),
                )
        source = max(
            (outcome for outcome in result.outcomes if outcome.verification_feedback is not None),
            key=lambda outcome: outcome.ordinal,
            default=None,
        )
        while source is not None and attempts_used < task.limits.max_attempts:
            source_workspace = attempt_workspaces.get(source.attempt_id)
            if source_workspace is None:
                break
            repair_ordinal = attempts_used + 1
            repair_id = new_id("attempt")
            repair_workspace = await manager.create_backup_workspace(
                primary_workspace, attempt_id=repair_id
            )
            try:
                await self.workspace_preparer.prepare(repair_workspace, dependencies)
                await self.repair_workspace_preparer.prepare(repair_workspace, source_workspace)
            except WorkspaceSafetyError as error:
                await manager.cleanup(repair_workspace)
                self.repository.record_decision(
                    decision_id=new_id("decision"),
                    run_id=run_id,
                    task_id=task_id,
                    attempt_id=source.attempt_id,
                    decision_type="repair_skipped",
                    signals={
                        "reason": "workspace_overlay_rejected",
                        "error_kind": type(error).__name__,
                        "attempts_used": attempts_used,
                    },
                    policy_version="repair-v1",
                    policy_snapshot={"max_attempts": task.limits.max_attempts},
                    timestamp=datetime.now(UTC).isoformat(),
                )
                break
            attempt_workspaces[repair_id] = repair_workspace
            with self.repository.transaction() as connection:
                current_status = str(
                    connection.execute(
                        "SELECT status FROM tasks WHERE id=?", (task_id,)
                    ).fetchone()[0]
                )
                require_transition(TaskStatus(current_status), TaskStatus.RUNNING, TASK_TRANSITIONS)
                connection.execute("UPDATE tasks SET status='running' WHERE id=?", (task_id,))
            assert source.verification_feedback is not None
            repair_prompt = build_repair_prompt(
                task.prompt,
                source.verification_feedback,
                attempt_number=repair_ordinal,
                max_attempts=task.limits.max_attempts,
                allowed_changed_paths=tuple(task.verify.allowed_changed_paths),
            )
            self.repository.record_decision(
                decision_id=new_id("decision"),
                run_id=run_id,
                task_id=task_id,
                attempt_id=repair_id,
                decision_type="launch_repair",
                signals={
                    "reason": "verification_failed",
                    "source_attempt_id": source.attempt_id,
                    "repair_ordinal": repair_ordinal,
                    "max_attempts": task.limits.max_attempts,
                },
                policy_version="repair-v1",
                policy_snapshot={
                    "max_attempts": task.limits.max_attempts,
                    "reuse_approved_plan": True,
                    "carry_forward_isolated_changes": True,
                    "filtered_feedback_only": True,
                },
                timestamp=datetime.now(UTC).isoformat(),
            )
            async with self._root_semaphore:
                repair_outcome = await self._execute_attempt(
                    run_id,
                    task_id,
                    task,
                    manifest,
                    manager,
                    repair_workspace,
                    ordinal=repair_ordinal,
                    role="repair",
                    granted_threads=granted_threads,
                    prompt=repair_prompt,
                )
            attempts_used += 1
            if repair_outcome.verified:
                return self.repository.claim_winner(
                    task_id, repair_outcome.attempt_id, datetime.now(UTC).isoformat()
                )
            source = repair_outcome if repair_outcome.verification_feedback is not None else None
        if source is not None and attempts_used >= task.limits.max_attempts:
            self.repository.record_decision(
                decision_id=new_id("decision"),
                run_id=run_id,
                task_id=task_id,
                attempt_id=source.attempt_id,
                decision_type="repair_limit_reached",
                signals={
                    "reason": "max_attempts_exhausted",
                    "attempts_used": attempts_used,
                },
                policy_version="repair-v1",
                policy_snapshot={"max_attempts": task.limits.max_attempts},
                timestamp=datetime.now(UTC).isoformat(),
            )
        with self.repository.transaction() as connection:
            connection.execute(
                "UPDATE tasks SET status='failed' WHERE id=? AND winner_attempt_id IS NULL",
                (task_id,),
            )
        return False

    def _dependency_winners(
        self, task_id: str, manifest: Manifest
    ) -> tuple[DependencySnapshot, ...]:
        task_by_key = {task.id: task for task in manifest.tasks}
        with self.repository.transaction() as connection:
            rows = connection.execute(
                "SELECT parent.task_key,attempt.workspace_path,attempt.base_sha "
                "FROM task_dependencies dependency "
                "JOIN tasks parent ON parent.id=dependency.dependency_id "
                "JOIN attempts attempt ON attempt.id=parent.winner_attempt_id "
                "WHERE dependency.task_id=? ORDER BY parent.task_key",
                (task_id,),
            ).fetchall()
        return tuple(
            DependencySnapshot(
                task_by_key[str(row[0])],
                Path(str(row[1])).resolve(),
                str(row[2]),
            )
            for row in rows
            if row[1] is not None
        )

    async def _execute_attempt(
        self,
        run_id: str,
        task_id: str,
        task: TaskConfig,
        manifest: Manifest,
        manager: GitWorktreeManager,
        workspace: Workspace,
        *,
        ordinal: int,
        role: str,
        granted_threads: int,
        prompt: str | None = None,
    ) -> AttemptOutcome:
        attempt_id = workspace.attempt_id
        config = manifest.agent_defaults.model_dump(mode="json")
        config["max_subagent_threads"] = granted_threads
        config["artifact_dir"] = str(self.state_dir / "runs" / run_id / attempt_id)
        with self.repository.transaction() as connection:
            connection.execute(
                "INSERT INTO attempts(id,task_id,ordinal,role,status,base_sha,config_snapshot,"
                "workspace_path,branch,started_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    attempt_id,
                    task_id,
                    ordinal,
                    role,
                    "starting",
                    workspace.base_sha,
                    json.dumps(config),
                    str(workspace.path),
                    workspace.branch,
                    datetime.now(UTC).isoformat(),
                ),
            )
            connection.execute("UPDATE attempts SET status='running' WHERE id=?", (attempt_id,))
        adapter: WorkerAdapter
        if self.worker_factory is not None:
            adapter = self.worker_factory.create(manifest, attempt_id, role)
        elif manifest.agent_defaults.adapter == "fake":
            raw_latency = manifest.agent_defaults.config.get("fake_latency_seconds", 0)
            latency = float(raw_latency) if isinstance(raw_latency, int | float | str) else 0
            if role == "hedge":
                raw_backup_latency = manifest.agent_defaults.config.get(
                    "fake_backup_latency_seconds", latency
                )
                latency = (
                    float(raw_backup_latency)
                    if isinstance(raw_backup_latency, int | float | str)
                    else latency
                )
            adapter = FakeWorkerAdapter({attempt_id: FakePlan(latency_seconds=latency)})
        else:
            adapter = CodexExecAdapter(manifest.agent_defaults.codex_binary)
        handle = await adapter.start(
            StartAttemptRequest(
                run_id,
                task.id,
                attempt_id,
                prompt or task.prompt,
                workspace.path,
                manifest.agent_defaults.timeout_seconds,
                config,
            )
        )
        completed = False
        try:
            async for event in adapter.events(handle):
                self.repository.append_event(
                    new_id("event"),
                    event.type,
                    event.timestamp.isoformat(),
                    event.payload,
                    run_id=run_id,
                    task_id=task_id,
                    attempt_id=attempt_id,
                )
                if event.type == "worker.completed":
                    completed = True
        except asyncio.CancelledError:
            await self._cancel_attempt(adapter, handle, manager, workspace)
            raise
        if not completed:
            finished = datetime.now(UTC).isoformat()
            with self.repository.transaction() as connection:
                connection.execute(
                    "UPDATE attempts SET status='failed',finished_at=? WHERE id=?",
                    (finished, attempt_id),
                )
            return AttemptOutcome(attempt_id, False, ordinal)
        with self.repository.transaction() as connection:
            connection.execute("UPDATE attempts SET status='verifying' WHERE id=?", (attempt_id,))
            connection.execute("UPDATE tasks SET status='verifying' WHERE id=?", (task_id,))
        commands = self._verification_commands(task, manifest)
        try:
            verification = await self._verify_workspace(
                manifest,
                task,
                workspace,
                commands,
                run_id=run_id,
                task_id=task_id,
            )
        except asyncio.CancelledError:
            await self._cancel_attempt(adapter, handle, manager, workspace)
            raise
        self._persist_verification(run_id, task_id, attempt_id, commands, verification)
        finished = datetime.now(UTC).isoformat()
        if not verification.passed:
            with self.repository.transaction() as connection:
                connection.execute(
                    "UPDATE attempts SET status='failed',finished_at=? WHERE id=?",
                    (finished, attempt_id),
                )
            return AttemptOutcome(
                attempt_id,
                False,
                ordinal,
                build_verification_feedback(verification),
            )
        with self.repository.transaction() as connection:
            connection.execute(
                "UPDATE attempts SET status='passed',finished_at=? WHERE id=?",
                (finished, attempt_id),
            )
        return AttemptOutcome(attempt_id, True, ordinal)

    @staticmethod
    def _verification_commands(
        task: TaskConfig, manifest: Manifest
    ) -> tuple[VerificationCommand, ...]:
        return tuple(
            VerificationCommand(
                argv=tuple(command.argv) if command.argv is not None else None,
                command=command.command,
                shell=command.shell,
                timeout_seconds=manifest.verification_defaults.command_timeout_seconds,
            )
            for command in task.verify.commands
        )

    async def _verify_workspace(
        self,
        manifest: Manifest,
        task: TaskConfig,
        workspace: Workspace,
        commands: tuple[VerificationCommand, ...],
        *,
        executable_overrides: dict[str, str] | None = None,
        run_id: str | None = None,
        task_id: str | None = None,
    ) -> VerificationResult:
        overrides = dict(manifest.verification_defaults.executable_overrides)
        overrides.update(executable_overrides or {})
        queued_at = time.monotonic()
        async with self._verifier_semaphore:
            wait_seconds = time.monotonic() - queued_at
            self.repository.append_event(
                new_id("event"),
                "verifier.admitted",
                datetime.now(UTC).isoformat(),
                {
                    "queue_wait_seconds": wait_seconds,
                    "configured_slots": manifest.scheduler.concurrency.verifier_slots,
                },
                run_id=run_id,
                task_id=task_id,
                attempt_id=workspace.attempt_id,
            )
            return await CommandVerifier(1, executable_overrides=overrides).verify(
                VerificationRequest(
                    workspace.attempt_id,
                    workspace.path,
                    workspace.base_sha,
                    commands,
                    tuple(task.verify.allowed_changed_paths),
                    manifest.verification_defaults.max_output_bytes,
                )
            )

    def _persist_verification(
        self,
        run_id: str,
        task_id: str,
        attempt_id: str,
        commands: tuple[VerificationCommand, ...],
        verification: VerificationResult,
    ) -> int:
        with self.repository.transaction() as connection:
            verification_round = int(
                connection.execute(
                    "SELECT COALESCE(MAX(verification_round),0)+1 FROM verification_runs "
                    "WHERE attempt_id=?",
                    (attempt_id,),
                ).fetchone()[0]
            )
        root = (
            self.state_dir
            / "runs"
            / run_id
            / attempt_id
            / "verification"
            / f"round-{verification_round:03d}"
        )
        root.mkdir(parents=True, exist_ok=True)
        rows: list[tuple[object, ...]] = []
        for index, command in enumerate(commands):
            command_payload = {
                "argv": list(command.argv) if command.argv is not None else None,
                "command": command.command,
                "shell": command.shell,
                "timeout_seconds": command.timeout_seconds,
            }
            if index < len(verification.commands):
                result = verification.commands[index]
                status = (
                    "timed_out"
                    if result.timed_out
                    else "passed"
                    if result.exit_code == 0
                    else "failed"
                )
                metadata = {
                    "captured_stdout_bytes": len(result.stdout.encode()),
                    "captured_stderr_bytes": len(result.stderr.encode()),
                    "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
                    "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest(),
                    "output_truncated": result.output_truncated,
                    "resolved_executable": result.resolved_executable,
                    "launch_error_kind": result.launch_error_kind,
                }
                output_path = root / f"command-{index:03d}.json"
                output_path.write_text(
                    json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
                )
                exit_code = result.exit_code
                started_at = result.started_at
                finished_at = result.finished_at
            else:
                status = "skipped"
                exit_code = None
                started_at = None
                finished_at = None
                output_path = None
            rows.append(
                (
                    new_id("verification"),
                    attempt_id,
                    index,
                    verification_round,
                    json.dumps(command_payload, sort_keys=True),
                    status,
                    exit_code,
                    started_at,
                    finished_at,
                    str(output_path) if output_path is not None else None,
                )
            )
        with self.repository.transaction() as connection:
            connection.executemany(
                "INSERT INTO verification_runs(id,attempt_id,command_index,verification_round,"
                "command_json,status,exit_code,started_at,finished_at,output_path) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
        self.repository.append_event(
            new_id("event"),
            "verifier.completed",
            datetime.now(UTC).isoformat(),
            {
                "passed": verification.passed,
                "changed_paths": list(verification.changed_paths),
                "disallowed_paths": list(verification.disallowed_paths),
                "diff_hash": verification.diff_hash,
                "executed_commands": len(verification.commands),
                "planned_commands": len(commands),
                "verification_round": verification_round,
            },
            run_id=run_id,
            task_id=task_id,
            attempt_id=attempt_id,
        )
        return verification_round

    def _persist_delivery_verification(
        self,
        run_id: str,
        delivery_id: str,
        commands: tuple[VerificationCommand, ...],
        verification: VerificationResult,
    ) -> None:
        root = self.state_dir / "runs" / run_id / "delivery" / "verification"
        root.mkdir(parents=True, exist_ok=True)
        rows: list[tuple[object, ...]] = []
        for index, command in enumerate(commands):
            command_payload = {
                "argv": list(command.argv) if command.argv is not None else None,
                "command": command.command,
                "shell": command.shell,
                "timeout_seconds": command.timeout_seconds,
            }
            if index < len(verification.commands):
                result = verification.commands[index]
                status = (
                    "timed_out"
                    if result.timed_out
                    else "passed"
                    if result.exit_code == 0
                    else "failed"
                )
                metadata = {
                    "captured_stdout_bytes": len(result.stdout.encode()),
                    "captured_stderr_bytes": len(result.stderr.encode()),
                    "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
                    "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest(),
                    "output_truncated": result.output_truncated,
                    "resolved_executable": result.resolved_executable,
                    "launch_error_kind": result.launch_error_kind,
                }
                output_path = root / f"command-{index:03d}.json"
                output_path.write_text(
                    json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
                )
                exit_code = result.exit_code
                started_at = result.started_at
                finished_at = result.finished_at
            else:
                status = "skipped"
                exit_code = None
                started_at = None
                finished_at = None
                output_path = None
            rows.append(
                (
                    new_id("delivery_verification"),
                    delivery_id,
                    index,
                    json.dumps(command_payload, sort_keys=True),
                    status,
                    exit_code,
                    started_at,
                    finished_at,
                    str(output_path) if output_path is not None else None,
                )
            )
        with self.repository.transaction() as connection:
            connection.executemany(
                "INSERT INTO delivery_verification_runs("
                "id,delivery_id,command_index,command_json,status,exit_code,started_at,"
                "finished_at,output_path) VALUES(?,?,?,?,?,?,?,?,?)",
                rows,
            )
        self.repository.append_event(
            new_id("event"),
            "delivery.verifier_completed",
            datetime.now(UTC).isoformat(),
            {
                "passed": verification.passed,
                "changed_paths": list(verification.changed_paths),
                "disallowed_paths": list(verification.disallowed_paths),
                "diff_hash": verification.diff_hash,
                "executed_commands": len(verification.commands),
                "planned_commands": len(commands),
            },
            run_id=run_id,
        )

    async def _cancel_attempt(
        self,
        adapter: WorkerAdapter,
        handle: AttemptHandle,
        manager: GitWorktreeManager,
        workspace: Workspace,
    ) -> None:
        await adapter.cancel(handle, "scheduler cancelled attempt")
        with self.repository.transaction() as connection:
            connection.execute(
                "UPDATE attempts SET status='cancelled',finished_at=? WHERE id=?",
                (datetime.now(UTC).isoformat(), workspace.attempt_id),
            )
        if not self.repository.workspace_identity_matches(
            attempt_id=workspace.attempt_id,
            path=str(workspace.path),
            branch=workspace.branch,
            base_sha=workspace.base_sha,
        ):
            raise RuntimeError("database workspace identity mismatch; cleanup refused")
        await manager.cleanup(workspace)
