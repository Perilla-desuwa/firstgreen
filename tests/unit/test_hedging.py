import pytest

from firstgreen.scheduler.hedging import (
    HedgeInputs,
    HedgePolicy,
    RuntimeBucket,
    Threshold,
    choose_threshold,
    empirical_quantile,
)
from firstgreen.simulator import simulate


def inputs(**overrides: object) -> HedgeInputs:
    values: dict[str, object] = {
        "replay_safe": True,
        "enabled": True,
        "winner_absent": True,
        "primary_active": True,
        "replicas": 0,
        "max_replicas": 1,
        "budget_available": True,
        "slots_available": True,
        "resources_available": True,
        "controller_backoff": False,
        "elapsed_seconds": 11.0,
        "threshold": Threshold(10.0, "configured_fallback", 0),
    }
    values.update(overrides)
    return HedgeInputs(**values)  # type: ignore[arg-type]


def test_replay_unsafe_never_hedges_even_after_threshold() -> None:
    decision = HedgePolicy().evaluate(inputs(replay_safe=False, elapsed_seconds=1000.0))
    assert not decision.launch
    assert decision.reason == "task_not_replay_safe"


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"enabled": False}, "hedging_disabled"),
        ({"winner_absent": False}, "winner_exists"),
        ({"budget_available": False}, "hedge_budget_exhausted"),
        ({"slots_available": False}, "no_root_slot"),
        ({"controller_backoff": True}, "controller_backoff"),
        ({"elapsed_seconds": 9.0}, "threshold_not_reached"),
    ],
)
def test_gates_are_explainable(override: dict[str, object], reason: str) -> None:
    assert HedgePolicy().evaluate(inputs(**override)).reason == reason


def test_nearest_rank_and_bucket_fallback() -> None:
    assert empirical_quantile([1, 2, 3, 4], 0.75) == 3
    bucket = RuntimeBucket("repo", "bug", "codex", "model", "verify")
    threshold = choose_threshold(
        {("codex", "model"): [1, 2, 3]},
        bucket,
        quantile=1,
        min_samples=3,
        fallback_seconds=99,
    )
    assert threshold.seconds == 3
    assert threshold.source == "historical_level_3"


def test_simulator_outputs_latency_cost_frontier() -> None:
    single = simulate(policy="single", seed=7, tasks=1000)
    delayed = simulate(policy="delayed-hedge", seed=7, tasks=1000)
    race = simulate(policy="always-race", seed=7, tasks=1000)
    assert delayed.p95_seconds < single.p95_seconds
    assert delayed.attempt_seconds < race.attempt_seconds
    assert 0 < delayed.hedge_launch_rate < 1
