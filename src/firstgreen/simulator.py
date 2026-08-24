"""Deterministic synthetic workload simulator."""

import random
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SimulationResult:
    policy: str
    seed: int
    tasks: int
    p95_seconds: float
    attempt_seconds: float
    verified: int
    hedge_launch_rate: float
    hedge_win_rate: float
    wasted_attempt_seconds: float


def simulate(
    *, policy: str, seed: int, tasks: int = 100, hedge_after_seconds: float = 25.0
) -> SimulationResult:
    if policy not in {"single", "always-race", "delayed-hedge", "auto"}:
        raise ValueError(f"unknown policy: {policy}")
    rng = random.Random(seed)
    runtimes = [rng.lognormvariate(2.5, 1.0) for _ in range(tasks)]
    attempt_seconds = sum(runtimes)
    observed = runtimes[:]
    hedges = 0
    hedge_wins = 0
    wasted = 0.0
    if policy == "always-race":
        backups = [rng.lognormvariate(2.5, 1.0) for _ in range(tasks)]
        observed = [min(a, b) for a, b in zip(runtimes, backups, strict=True)]
        attempt_seconds = 2 * sum(observed)
        wasted = sum(observed)
        hedges = tasks
        hedge_wins = sum(b < a for a, b in zip(runtimes, backups, strict=True))
    elif policy in {"delayed-hedge", "auto"}:
        backups = [rng.lognormvariate(2.5, 1.0) for _ in range(tasks)]
        observed = []
        attempt_seconds = 0.0
        for primary, backup in zip(runtimes, backups, strict=True):
            if primary <= hedge_after_seconds:
                observed.append(primary)
                attempt_seconds += primary
                continue
            hedges += 1
            winner_time = min(primary, hedge_after_seconds + backup)
            backup_time = winner_time - hedge_after_seconds
            observed.append(winner_time)
            attempt_seconds += winner_time + backup_time
            wasted += backup_time
            hedge_wins += hedge_after_seconds + backup < primary
    ordered = sorted(observed)
    p95 = ordered[max(0, int(0.95 * len(ordered)) - 1)]
    return SimulationResult(
        policy,
        seed,
        tasks,
        p95,
        attempt_seconds,
        tasks,
        hedges / tasks,
        hedge_wins / hedges if hedges else 0.0,
        wasted,
    )


def simulation_dict(*, policy: str, seed: int, tasks: int = 100) -> dict[str, object]:
    return asdict(simulate(policy=policy, seed=seed, tasks=tasks))
