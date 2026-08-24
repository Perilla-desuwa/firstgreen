import asyncio
from pathlib import Path

from firstgreen.db.repository import SQLiteRepository
from firstgreen.scheduler.racing import AttemptOutcome, first_verified_wins


def repository(tmp_path: Path) -> SQLiteRepository:
    result = SQLiteRepository(tmp_path / "state.db")
    result.initialize()
    with result.transaction() as connection:
        connection.execute(
            "INSERT INTO runs VALUES(?,?,?,?,?,?,?,NULL,NULL)",
            ("r", "h", ".", "sha", "{}", "running", "now"),
        )
        connection.execute(
            "INSERT INTO tasks(id,run_id,task_key,prompt,replay_safe,status) VALUES(?,?,?,?,?,?)",
            ("t", "r", "t", "p", 1, "verifying"),
        )
        connection.executemany(
            "INSERT INTO attempts(id,task_id,ordinal,role,status,base_sha,config_snapshot) "
            "VALUES(?,?,?,?,?,?,?)",
            [
                ("primary", "t", 1, "primary", "passed", "sha", "{}"),
                ("backup", "t", 2, "hedge", "passed", "sha", "{}"),
            ],
        )
    return result


def test_delayed_verified_backup_wins_and_cancels_primary(tmp_path: Path) -> None:
    repo = repository(tmp_path)

    async def primary() -> AttemptOutcome:
        await asyncio.sleep(1)
        return AttemptOutcome("primary", True)

    async def backup() -> AttemptOutcome:
        await asyncio.sleep(0.01)
        return AttemptOutcome("backup", True)

    result = asyncio.run(
        first_verified_wins(
            primary,
            backup,
            lambda attempt: repo.claim_winner("t", attempt, "later"),
            policy="delayed-hedge",
            replay_safe=True,
            hedge_delay_seconds=0.01,
        )
    )
    assert result.winner_attempt_id == "backup"
    assert result.launched_backup
    assert result.cancelled_attempt_ids == ("primary",)


def test_replay_unsafe_never_calls_backup(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    backup_called = False

    async def primary() -> AttemptOutcome:
        return AttemptOutcome("primary", True)

    async def backup() -> AttemptOutcome:
        nonlocal backup_called
        backup_called = True
        return AttemptOutcome("backup", True)

    result = asyncio.run(
        first_verified_wins(
            primary,
            backup,
            lambda attempt: repo.claim_winner("t", attempt, "later"),
            policy="delayed-hedge",
            replay_safe=False,
            hedge_delay_seconds=0,
        )
    )
    assert result.winner_attempt_id == "primary"
    assert not backup_called


def test_failed_primary_before_threshold_launches_verified_backup(tmp_path: Path) -> None:
    repo = repository(tmp_path)

    async def primary() -> AttemptOutcome:
        return AttemptOutcome("primary", False)

    async def backup() -> AttemptOutcome:
        return AttemptOutcome("backup", True)

    result = asyncio.run(
        first_verified_wins(
            primary,
            backup,
            lambda attempt: repo.claim_winner("t", attempt, "later"),
            policy="delayed-hedge",
            replay_safe=True,
            hedge_delay_seconds=10,
        )
    )
    assert result.winner_attempt_id == "backup"
    assert result.launched_backup
