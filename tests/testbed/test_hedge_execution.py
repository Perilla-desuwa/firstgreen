import asyncio
from pathlib import Path

from firstgreen.adapters.base import AttemptHandle
from firstgreen.testbed.hedge import (
    HedgeAttemptProfile,
    execute_hedge_scenario,
)
from firstgreen.testbed.repository import create_tinyshop_repository
from firstgreen.workspace.git_worktree import GitWorktreeManager


def profiles(
    primary_seconds: float,
    primary_passes: bool,
    hedge_seconds: float,
    hedge_passes: bool,
) -> dict[str, HedgeAttemptProfile]:
    return {
        "primary": HedgeAttemptProfile(primary_seconds, primary_passes),
        "hedge": HedgeAttemptProfile(hedge_seconds, hedge_passes),
    }


def test_slow_primary_fast_verified_hedge_wins(tmp_path: Path) -> None:
    repo = create_tinyshop_repository(tmp_path, "h1-fast-hedge")
    outcome = asyncio.run(
        execute_hedge_scenario(
            repo,
            tmp_path / "state",
            profiles(2.0, True, 0.01, True),
        )
    )
    assert outcome.winner_role == "hedge"
    assert outcome.winner_count == 1
    primary, hedge = outcome.attempts
    assert primary.status == "cancelled"
    assert not primary.workspace.path.exists()
    assert hedge.workspace.path.is_dir()
    assert primary.workspace.base_sha == hedge.workspace.base_sha


def test_fast_invalid_hedge_cannot_beat_slower_verified_primary(tmp_path: Path) -> None:
    repo = create_tinyshop_repository(tmp_path, "h1-invalid-hedge")
    outcome = asyncio.run(
        execute_hedge_scenario(
            repo,
            tmp_path / "state",
            profiles(1.5, True, 0.01, False),
        )
    )
    assert outcome.winner_role == "primary"
    assert outcome.winner_count == 1
    primary, hedge = outcome.attempts
    assert primary.status == "winner"
    assert hedge.status == "failed"


def test_duplicate_verified_completion_commits_exactly_one_winner(tmp_path: Path) -> None:
    repo = create_tinyshop_repository(tmp_path, "h1-duplicate")
    outcome = asyncio.run(
        execute_hedge_scenario(
            repo,
            tmp_path / "state",
            profiles(0.01, True, 0.01, True),
            policy="always-race",
        )
    )
    assert outcome.winner_count == 1
    assert sum(record.status == "winner" for record in outcome.attempts) == 1


def test_cancel_is_idempotent_when_repeated_after_scheduler_cancel(tmp_path: Path) -> None:
    repo = create_tinyshop_repository(tmp_path, "h1-cancel")

    async def run_and_repeat_cancel() -> tuple[int, str]:
        outcome = await execute_hedge_scenario(
            repo,
            tmp_path / "state",
            profiles(2.0, True, 0.01, True),
        )
        primary = next(record for record in outcome.attempts if record.role == "primary")
        adapter = outcome.factory.adapters[primary.attempt_id]
        handle = AttemptHandle("hedge-fake", primary.attempt_id, None)
        await adapter.cancel(handle, "repeat one")
        await adapter.cancel(handle, "repeat two")
        await asyncio.sleep(0.05)
        return adapter.cancel_calls, adapter.status

    cancel_calls, status = asyncio.run(run_and_repeat_cancel())
    assert cancel_calls == 3
    assert status == "cancelled"


def test_cleanup_is_idempotent_and_winner_workspace_survives(tmp_path: Path) -> None:
    repo = create_tinyshop_repository(tmp_path, "h1-cleanup")
    outcome = asyncio.run(
        execute_hedge_scenario(
            repo,
            tmp_path / "state",
            profiles(2.0, True, 0.01, True),
        )
    )
    primary, hedge = outcome.attempts
    manager = GitWorktreeManager(outcome.state_dir / "worktrees", keep_winner=True)
    asyncio.run(manager.cleanup(primary.workspace))
    asyncio.run(manager.cleanup(primary.workspace))
    asyncio.run(manager.cleanup(hedge.workspace, is_winner=True))
    asyncio.run(manager.cleanup(hedge.workspace, is_winner=True))
    assert not primary.workspace.path.exists()
    assert hedge.workspace.path.is_dir()


def test_replay_unsafe_task_never_launches_hedge(tmp_path: Path) -> None:
    repo = create_tinyshop_repository(tmp_path, "h1-replay-unsafe")
    outcome = asyncio.run(
        execute_hedge_scenario(
            repo,
            tmp_path / "state",
            profiles(0.01, True, 0.01, True),
            replay_safe=False,
        )
    )
    assert outcome.winner_role == "primary"
    assert len(outcome.attempts) == 1
    assert not any(entry["role"] == "hedge" for entry in outcome.factory.timeline)
