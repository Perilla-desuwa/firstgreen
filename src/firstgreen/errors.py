class FirstGreenError(Exception):
    """Base user-facing error."""


class TransitionError(FirstGreenError):
    """A domain state transition violated the centralized table."""


class WorkspaceSafetyError(FirstGreenError):
    """A workspace operation failed a safety invariant."""
