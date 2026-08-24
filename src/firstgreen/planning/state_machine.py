"""Centralized planning lifecycle transitions."""

from collections.abc import Mapping, Set

from firstgreen.errors import TransitionError
from firstgreen.planning.models import IssueState

PLANNING_TRANSITIONS: Mapping[IssueState, Set[IssueState]] = {
    IssueState.RECEIVED: {IssueState.REPO_SCANNING, IssueState.CANCELLED},
    IssueState.REPO_SCANNING: {IssueState.PLANNING, IssueState.FAILED, IssueState.CANCELLED},
    IssueState.PLANNING: {IssueState.PLAN_VALIDATION, IssueState.FAILED, IssueState.CANCELLED},
    IssueState.PLAN_VALIDATION: {
        IssueState.AWAITING_PLAN_APPROVAL,
        IssueState.PLAN_APPROVED,
        IssueState.FAILED,
    },
    IssueState.AWAITING_PLAN_APPROVAL: {
        IssueState.PLAN_APPROVED,
        IssueState.CANCELLED,
        IssueState.FAILED,
    },
    IssueState.PLAN_APPROVED: {IssueState.EXECUTION_READY, IssueState.CANCELLED},
    IssueState.EXECUTION_READY: {IssueState.EXECUTING, IssueState.CANCELLED},
    IssueState.EXECUTING: {
        IssueState.COMPLETED,
        IssueState.FAILED,
        IssueState.CANCELLED,
    },
}


def require_planning_transition(current: IssueState, new: IssueState) -> None:
    if new not in PLANNING_TRANSITIONS.get(current, set()):
        raise TransitionError(f"illegal planning transition: {current.value} -> {new.value}")
