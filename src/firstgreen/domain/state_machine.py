"""The only legal source of domain state transitions."""

from collections.abc import Mapping, Set
from enum import StrEnum

from firstgreen.domain.models import AttemptStatus, RunStatus, TaskStatus
from firstgreen.errors import TransitionError

RUN_TRANSITIONS: Mapping[RunStatus, Set[RunStatus]] = {
    RunStatus.CREATED: {RunStatus.RUNNING, RunStatus.CANCELLED},
    RunStatus.RUNNING: {RunStatus.COMPLETED, RunStatus.CANCELLED, RunStatus.FAILED},
    RunStatus.FAILED: {RunStatus.RUNNING},
}
TASK_TRANSITIONS: Mapping[TaskStatus, Set[TaskStatus]] = {
    TaskStatus.QUEUED: {TaskStatus.READY, TaskStatus.BLOCKED, TaskStatus.CANCELLED},
    TaskStatus.READY: {TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.BLOCKED},
    TaskStatus.RUNNING: {TaskStatus.VERIFYING, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.VERIFYING: {
        TaskStatus.RUNNING,
        TaskStatus.VERIFIED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.FAILED: {TaskStatus.VERIFYING},
}
ATTEMPT_TRANSITIONS: Mapping[AttemptStatus, Set[AttemptStatus]] = {
    AttemptStatus.CREATED: {AttemptStatus.STARTING, AttemptStatus.CANCELLED},
    AttemptStatus.STARTING: {AttemptStatus.RUNNING, AttemptStatus.FAILED, AttemptStatus.CANCELLED},
    AttemptStatus.RUNNING: {
        AttemptStatus.AGENT_COMPLETED,
        AttemptStatus.FAILED,
        AttemptStatus.CANCELLED,
        AttemptStatus.ORPHANED,
    },
    AttemptStatus.AGENT_COMPLETED: {AttemptStatus.VERIFYING, AttemptStatus.FAILED},
    AttemptStatus.VERIFYING: {AttemptStatus.PASSED, AttemptStatus.FAILED, AttemptStatus.CANCELLED},
    AttemptStatus.PASSED: {AttemptStatus.WINNER, AttemptStatus.SUPERSEDED},
    AttemptStatus.ORPHANED: {AttemptStatus.FAILED, AttemptStatus.CANCELLED},
    AttemptStatus.FAILED: {AttemptStatus.VERIFYING},
}


def require_transition[S: StrEnum](current: S, new: S, table: Mapping[S, Set[S]]) -> None:
    if new not in table.get(current, set()):
        raise TransitionError(f"illegal transition: {current.value} -> {new.value}")
