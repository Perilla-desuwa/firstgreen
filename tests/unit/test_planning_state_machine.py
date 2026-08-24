import pytest

from firstgreen.errors import TransitionError
from firstgreen.planning.models import IssueState
from firstgreen.planning.state_machine import require_planning_transition


def test_planning_requires_validation_and_approval_before_execution() -> None:
    require_planning_transition(IssueState.PLANNING, IssueState.PLAN_VALIDATION)
    require_planning_transition(IssueState.PLAN_VALIDATION, IssueState.AWAITING_PLAN_APPROVAL)
    require_planning_transition(IssueState.AWAITING_PLAN_APPROVAL, IssueState.PLAN_APPROVED)
    with pytest.raises(TransitionError):
        require_planning_transition(IssueState.PLANNING, IssueState.EXECUTING)
