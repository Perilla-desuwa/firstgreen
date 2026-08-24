"""Bounded, redacted verifier feedback for automatic repair attempts."""

import os
import re

from firstgreen.verifier.runner import VerificationResult

MAX_FEEDBACK_CHARS = 12_000
MAX_STREAM_EXCERPT_CHARS = 3_000
MAX_PATHS = 50

_SENSITIVE_ENV_NAME = re.compile(
    r"(?:^|_)(?:API_KEY|ACCESS_KEY|AUTHORIZATION|CREDENTIAL|PASSWORD|PASS|SECRET|TOKEN)(?:_|$)",
    re.IGNORECASE,
)
_SECRET_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{6,}\b"),
    re.compile(
        r"(?i)(\b(?:api[_ -]?key|authorization|credential|password|secret|token)\b"
        r"\s*[:=]\s*)([^\s,;]+)"
    ),
)


def _bounded(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    head = limit // 2
    tail = limit - head
    omitted = len(value) - limit
    return f"{value[:head]}\n...[{omitted} characters omitted]...\n{value[-tail:]}"


def _redact(value: str) -> str:
    rendered = _bounded(value, MAX_STREAM_EXCERPT_CHARS)
    sensitive_values = sorted(
        {
            secret
            for name, secret in os.environ.items()
            if len(secret) >= 4 and _SENSITIVE_ENV_NAME.search(name)
        },
        key=len,
        reverse=True,
    )
    for secret in sensitive_values:
        rendered = rendered.replace(secret, "[REDACTED]")
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            rendered = pattern.sub(r"\1[REDACTED]", rendered)
        else:
            rendered = pattern.sub("[REDACTED]", rendered)
    return "".join(
        character for character in rendered if character in "\n\t" or ord(character) >= 32
    )


def _paths(label: str, paths: tuple[str, ...]) -> list[str]:
    if not paths:
        return []
    lines = [f"{label}:"]
    lines.extend(f"- {path}" for path in paths[:MAX_PATHS])
    if len(paths) > MAX_PATHS:
        lines.append(f"- ...[{len(paths) - MAX_PATHS} paths omitted]...")
    return lines


def build_verification_feedback(result: VerificationResult) -> str:
    """Summarize useful failures without persisting or forwarding raw output."""

    lines = ["Scheduler-owned verification failed."]
    lines.extend(_paths("Changed paths", result.changed_paths))
    lines.extend(
        _paths("Disallowed changed paths (remove or revert these)", result.disallowed_paths)
    )
    for index, command in enumerate(result.commands, start=1):
        status = (
            "timed out"
            if command.timed_out
            else f"exit {command.exit_code}"
            if command.exit_code is not None
            else "could not launch"
        )
        lines.append(f"Verifier command {index}: {status}.")
        if command.launch_error_kind:
            lines.append(f"Launch error: {_redact(command.launch_error_kind)}")
        if command.stdout:
            lines.append("Filtered stdout excerpt:")
            lines.append(_redact(command.stdout))
        if command.stderr:
            lines.append("Filtered stderr excerpt:")
            lines.append(_redact(command.stderr))
        if command.output_truncated:
            lines.append("Verifier output was truncated by the scheduler.")
    return _bounded("\n".join(lines), MAX_FEEDBACK_CHARS)


def build_repair_prompt(
    original_prompt: str,
    feedback: str,
    *,
    attempt_number: int,
    max_attempts: int,
    allowed_changed_paths: tuple[str, ...],
) -> str:
    allowed = "\n".join(f"- {path}" for path in allowed_changed_paths) or "- unrestricted"
    return (
        f"{original_prompt}\n\n"
        "This is a scheduler-requested repair of a previous isolated attempt. "
        "Keep the existing useful changes, fix the reported verification failure, and do not "
        "weaken or remove tests.\n"
        f"Repair attempt: {attempt_number} of {max_attempts}.\n"
        f"Allowed changed paths:\n{allowed}\n\n"
        f"Filtered verifier feedback:\n{feedback}"
    )
