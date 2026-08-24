"""First-verified-wins coordination for primary and optional backup attempts."""

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AttemptOutcome:
    attempt_id: str
    verified: bool
    ordinal: int = 0
    verification_feedback: str | None = None


@dataclass(frozen=True)
class RaceResult:
    winner_attempt_id: str | None
    launched_backup: bool
    cancelled_attempt_ids: tuple[str, ...]
    outcomes: tuple[AttemptOutcome, ...] = ()


AttemptFactory = Callable[[], Coroutine[Any, Any, AttemptOutcome]]
WinnerClaim = Callable[[str], bool]


async def first_verified_wins(
    primary_factory: AttemptFactory,
    backup_factory: AttemptFactory,
    claim_winner: WinnerClaim,
    *,
    policy: str,
    replay_safe: bool,
    hedge_delay_seconds: float,
) -> RaceResult:
    """Launch selectively, require verification, atomically claim, then cancel losers."""
    primary: asyncio.Task[AttemptOutcome] = asyncio.create_task(primary_factory(), name="primary")
    tasks: set[asyncio.Task[AttemptOutcome]] = {primary}
    outcomes: list[AttemptOutcome] = []
    launched_backup = False
    if policy == "always-race" and replay_safe:
        tasks.add(asyncio.create_task(backup_factory(), name="backup"))
        launched_backup = True
    elif policy in {"delayed-hedge", "auto"} and replay_safe:
        done, _ = await asyncio.wait({primary}, timeout=hedge_delay_seconds)
        if done:
            outcome = primary.result()
            outcomes.append(outcome)
            if outcome.verified and claim_winner(outcome.attempt_id):
                return RaceResult(outcome.attempt_id, False, (), tuple(outcomes))
            tasks.clear()
        tasks.add(asyncio.create_task(backup_factory(), name="backup"))
        launched_backup = True
    cancelled: list[str] = []
    while tasks:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        tasks = set(pending)
        for finished in done:
            outcome = finished.result()
            outcomes.append(outcome)
            if not outcome.verified:
                continue
            if not claim_winner(outcome.attempt_id):
                continue
            for loser in pending:
                loser.cancel()
                cancelled.append(loser.get_name())
            await asyncio.gather(*pending, return_exceptions=True)
            return RaceResult(
                outcome.attempt_id,
                launched_backup,
                tuple(sorted(cancelled)),
                tuple(outcomes),
            )
    return RaceResult(None, launched_backup, (), tuple(outcomes))
