from datetime import UTC, datetime

import pytest

from firstgreen.clock import FakeClock
from firstgreen.domain.models import AttemptStatus, RunStatus, TaskStatus
from firstgreen.domain.state_machine import (
    ATTEMPT_TRANSITIONS,
    RUN_TRANSITIONS,
    TASK_TRANSITIONS,
    require_transition,
)
from firstgreen.errors import TransitionError


def test_illegal_state_transition() -> None:
    with pytest.raises(TransitionError):
        require_transition(TaskStatus.QUEUED, TaskStatus.VERIFIED, TASK_TRANSITIONS)


def test_agent_completion_is_not_winner() -> None:
    require_transition(AttemptStatus.RUNNING, AttemptStatus.AGENT_COMPLETED, ATTEMPT_TRANSITIONS)


def test_failed_terminal_states_only_reopen_for_explicit_reverification() -> None:
    require_transition(RunStatus.FAILED, RunStatus.RUNNING, RUN_TRANSITIONS)
    require_transition(TaskStatus.FAILED, TaskStatus.VERIFYING, TASK_TRANSITIONS)
    require_transition(AttemptStatus.FAILED, AttemptStatus.VERIFYING, ATTEMPT_TRANSITIONS)


def test_fake_clock_is_utc() -> None:
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    clock.advance(2)
    assert clock.now().timestamp() == datetime(2026, 1, 1, 0, 0, 2, tzinfo=UTC).timestamp()
