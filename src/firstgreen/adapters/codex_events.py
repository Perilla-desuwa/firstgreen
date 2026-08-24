"""Tolerant Codex JSONL normalization with privacy-first payload filtering."""

import json
from datetime import UTC, datetime
from typing import Any

from firstgreen.adapters.base import WorkerEvent

SENSITIVE_KEYS = {
    "aggregated_output",
    "reasoning",
    "text",
    "prompt",
    "message",
    "content",
    "arguments",
    "command",
    "output",
    "stderr",
    "stdout",
}
SECRET_KEYS = {"authorization", "api_key", "token", "secret", "password", "credential"}


def _filtered(value: Any, *, capture_sensitive: bool, key: str = "") -> Any:
    lowered = key.lower()
    if lowered in SECRET_KEYS:
        return "[REDACTED]"
    if not capture_sensitive and lowered in SENSITIVE_KEYS:
        return "[FILTERED]"
    if isinstance(value, dict):
        return {
            str(child_key): _filtered(
                child_value, capture_sensitive=capture_sensitive, key=str(child_key)
            )
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [_filtered(item, capture_sensitive=capture_sensitive) for item in value]
    return value


def parse_codex_line(line: str, *, capture_sensitive: bool = False) -> WorkerEvent:
    now = datetime.now(UTC)
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        payload = {
            "type": "stream.unparseable",
            "raw": "[FILTERED]",
            "byte_length": len(line.encode("utf-8", errors="replace")),
        }
        return WorkerEvent(
            "worker.raw_event", now, payload, json.dumps(payload, ensure_ascii=False)
        )
    if not isinstance(parsed, dict):
        payload = {
            "type": "stream.non_object",
            "value_type": type(parsed).__name__,
        }
        return WorkerEvent(
            "worker.raw_event", now, payload, json.dumps(payload, ensure_ascii=False)
        )
    event_type = str(parsed.get("type", "unknown"))
    payload = _filtered(parsed, capture_sensitive=capture_sensitive)
    normalized = "worker.raw_event"
    if event_type == "thread.started":
        normalized = "worker.started"
    elif event_type == "turn.completed":
        normalized = "worker.completed"
    elif event_type in {"turn.failed", "error"}:
        normalized = "worker.failed"
    elif event_type.startswith("item.") or event_type == "turn.started":
        normalized = "worker.activity"
    return WorkerEvent(normalized, now, payload, json.dumps(payload, ensure_ascii=False))


def oversized_codex_line(byte_length: int) -> WorkerEvent:
    """Represent a dropped over-limit line without retaining its sensitive contents."""

    payload = {
        "type": "stream.line_dropped",
        "reason": "line_exceeds_hard_limit",
        "byte_length": byte_length,
    }
    return WorkerEvent(
        "worker.raw_event",
        datetime.now(UTC),
        payload,
        json.dumps(payload, ensure_ascii=False),
    )


def stream_reader_failed(stream: str, error: BaseException) -> WorkerEvent:
    """Return a content-free terminal diagnostic for an unexpected reader failure."""

    payload = {
        "type": "stream.read_failed",
        "stream": stream,
        "error_type": type(error).__name__,
    }
    return WorkerEvent(
        "worker.failed",
        datetime.now(UTC),
        payload,
        json.dumps(payload, ensure_ascii=False),
    )


def extract_usage(event: WorkerEvent) -> dict[str, int] | None:
    usage = event.payload.get("usage")
    if not isinstance(usage, dict):
        return None
    return {str(key): int(value) for key, value in usage.items() if isinstance(value, int)}
