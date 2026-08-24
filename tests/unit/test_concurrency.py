from datetime import UTC, datetime, timedelta

from firstgreen.scheduler.concurrency import (
    AIMDController,
    ConcurrencyState,
    PressureSnapshot,
    admit_nested_threads,
    subagent_threads_per_root,
)


def state(current: int = 6) -> ConcurrencyState:
    return ConcurrencyState(current, 1, 8, datetime(2026, 1, 1, tzinfo=UTC))


def test_pressure_halves_and_never_breaks_hard_minimum() -> None:
    controller = AIMDController(cooldown_seconds=10)
    now = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=11)
    updated, decision = controller.decide(
        state(), PressureSnapshot(backlog=10, rate_limit_errors=1), now
    )
    assert updated.current_root == 3
    assert decision.action == "decrease"
    minimum, _ = controller.decide(state(1), PressureSnapshot(backlog=10, rate_limit_errors=1), now)
    assert minimum.current_root == 1


def test_healthy_backlog_adds_one_and_cooldown_prevents_oscillation() -> None:
    controller = AIMDController(cooldown_seconds=10)
    later = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=11)
    updated, decision = controller.decide(
        state(), PressureSnapshot(backlog=10, completed_samples=2), later
    )
    assert updated.current_root == 7
    assert decision.reason == "healthy_backlog"
    held, held_decision = controller.decide(
        updated, PressureSnapshot(backlog=10, rate_limit_errors=1), later + timedelta(seconds=1)
    )
    assert held.current_root == 7
    assert held_decision.reason == "cooldown"


def test_static_fallback_and_nested_budget_snapshot() -> None:
    controller = AIMDController(cooldown_seconds=0)
    current, decision = controller.decide(
        state(),
        PressureSnapshot(backlog=10, completed_samples=10),
        datetime(2026, 1, 2, tzinfo=UTC),
        mode="static",
    )
    assert current.current_root == 6
    assert decision.reason == "static_mode"
    admission = admit_nested_threads(active_thread_caps=7, requested_threads=3, total_budget=9)
    assert admission.allowed
    assert admission.granted_threads == 2


def test_root_threads_are_reserved_before_subagents() -> None:
    assert (
        subagent_threads_per_root(total_agent_threads=1, max_root=1, configured_max_subagents=32)
        == 0
    )
    assert (
        subagent_threads_per_root(total_agent_threads=32, max_root=1, configured_max_subagents=31)
        == 31
    )
    assert (
        subagent_threads_per_root(total_agent_threads=12, max_root=6, configured_max_subagents=2)
        == 1
    )
