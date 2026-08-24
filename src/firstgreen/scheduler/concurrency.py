"""Explainable AIMD root concurrency and nested-thread admission."""

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import psutil


@dataclass(frozen=True)
class PressureSnapshot:
    backlog: int
    completed_samples: int = 0
    rate_limit_errors: int = 0
    spawn_errors: int = 0
    verifier_queue_wait_seconds: float = 0
    memory_percent: float = 0
    normalized_load: float = 0
    cancellation_backlog: int = 0

    def pressure_reasons(
        self,
        *,
        max_verifier_wait: float = 30,
        max_memory_percent: float = 90,
        max_normalized_load: float = 1.5,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if self.rate_limit_errors:
            reasons.append("provider_rate_limit")
        if self.spawn_errors:
            reasons.append("spawn_errors")
        if self.verifier_queue_wait_seconds > max_verifier_wait:
            reasons.append("verifier_queue_pressure")
        if self.memory_percent > max_memory_percent:
            reasons.append("memory_pressure")
        if self.normalized_load > max_normalized_load:
            reasons.append("host_load_pressure")
        if self.cancellation_backlog:
            reasons.append("cancellation_backlog")
        return tuple(reasons)


class PressureSignal(Protocol):
    def sample(self) -> PressureSnapshot: ...


class HostPressureSignal:
    def sample(self) -> PressureSnapshot:
        cpu_count = psutil.cpu_count() or 1
        try:
            load = psutil.getloadavg()[0] / cpu_count
        except (AttributeError, OSError):
            load = psutil.cpu_percent(interval=None) / 100
        return PressureSnapshot(
            backlog=0, memory_percent=psutil.virtual_memory().percent, normalized_load=load
        )


@dataclass(frozen=True)
class ConcurrencyState:
    current_root: int
    min_root: int
    max_root: int
    last_change_at: datetime
    pressure_windows: int = 0
    healthy_windows: int = 0

    def __post_init__(self) -> None:
        if not 1 <= self.min_root <= self.current_root <= self.max_root:
            raise ValueError("concurrency must satisfy 1 <= min <= current <= max")


@dataclass(frozen=True)
class ConcurrencyDecision:
    old_root: int
    new_root: int
    action: str
    reason: str
    signals: dict[str, object]
    policy_version: str = "aimd-v1"


class AIMDController:
    version = "aimd-v1"

    def __init__(self, *, cooldown_seconds: float, min_completed_samples: int = 1) -> None:
        self.cooldown_seconds = cooldown_seconds
        self.min_completed_samples = min_completed_samples

    def decide(
        self,
        state: ConcurrencyState,
        snapshot: PressureSnapshot,
        now: datetime,
        *,
        mode: str = "auto",
    ) -> tuple[ConcurrencyState, ConcurrencyDecision]:
        signals: dict[str, object] = {
            "backlog": snapshot.backlog,
            "completed_samples": snapshot.completed_samples,
            "rate_limit_errors": snapshot.rate_limit_errors,
            "spawn_errors": snapshot.spawn_errors,
            "verifier_queue_wait_seconds": snapshot.verifier_queue_wait_seconds,
            "memory_percent": snapshot.memory_percent,
            "normalized_load": snapshot.normalized_load,
            "cancellation_backlog": snapshot.cancellation_backlog,
            "min_root": state.min_root,
            "max_root": state.max_root,
        }
        if mode != "auto":
            return state, ConcurrencyDecision(
                state.current_root, state.current_root, "hold", "static_mode", signals
            )
        elapsed = (now - state.last_change_at).total_seconds()
        if elapsed < self.cooldown_seconds:
            return state, ConcurrencyDecision(
                state.current_root, state.current_root, "hold", "cooldown", signals
            )
        reasons = snapshot.pressure_reasons()
        if reasons:
            new_root = max(state.min_root, math.floor(state.current_root / 2))
            new_state = ConcurrencyState(
                new_root,
                state.min_root,
                state.max_root,
                now,
                state.pressure_windows + 1,
                0,
            )
            return new_state, ConcurrencyDecision(
                state.current_root, new_root, "decrease", ",".join(reasons), signals
            )
        healthy = (
            snapshot.backlog > 0
            and snapshot.completed_samples >= self.min_completed_samples
            and state.current_root < state.max_root
        )
        if healthy:
            new_root = min(state.max_root, state.current_root + 1)
            new_state = ConcurrencyState(
                new_root,
                state.min_root,
                state.max_root,
                now,
                0,
                state.healthy_windows + 1,
            )
            return new_state, ConcurrencyDecision(
                state.current_root, new_root, "increase", "healthy_backlog", signals
            )
        return state, ConcurrencyDecision(
            state.current_root, state.current_root, "hold", "insufficient_signal", signals
        )


@dataclass(frozen=True)
class ThreadAdmission:
    allowed: bool
    granted_threads: int
    reason: str


def subagent_threads_per_root(
    *, total_agent_threads: int, max_root: int, configured_max_subagents: int
) -> int:
    """Conservatively reserve one primary thread for every possible root worker."""
    if total_agent_threads < max_root or max_root < 1 or configured_max_subagents < 0:
        raise ValueError("invalid root or agent thread budget")
    available_subagents = total_agent_threads - max_root
    return min(configured_max_subagents, available_subagents // max_root)


def admit_nested_threads(
    *,
    active_thread_caps: int,
    requested_threads: int,
    total_budget: int,
    allow_reduction: bool = True,
) -> ThreadAdmission:
    if min(requested_threads, total_budget) < 1 or active_thread_caps < 0:
        raise ValueError("thread budgets must be positive")
    available = total_budget - active_thread_caps
    if available >= requested_threads:
        return ThreadAdmission(True, requested_threads, "within_budget")
    if allow_reduction and available >= 1:
        return ThreadAdmission(True, available, "reduced_to_budget")
    return ThreadAdmission(False, 0, "nested_thread_budget_exhausted")
