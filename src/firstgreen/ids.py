"""Typed, sortable-enough identifiers."""

from typing import NewType
from uuid import uuid4

RunId = NewType("RunId", str)
TaskId = NewType("TaskId", str)
AttemptId = NewType("AttemptId", str)
VerificationId = NewType("VerificationId", str)
EventId = NewType("EventId", str)
DecisionId = NewType("DecisionId", str)
LeaseId = NewType("LeaseId", str)


def new_id(prefix: str) -> str:
    """Return an opaque identifier; user text never becomes a filesystem component."""
    return f"{prefix}_{uuid4().hex}"
