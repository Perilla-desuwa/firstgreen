import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from firstgreen.adapters.base import StartAttemptRequest
from firstgreen.adapters.codex_events import extract_usage, parse_codex_line
from firstgreen.adapters.codex_exec import (
    MAX_STREAM_LINE_BYTES,
    CodexExecAdapter,
    _bounded_stream_lines,
    _Running,
    build_codex_argv,
)


def test_command_builder_uses_verified_safe_flags_and_snapshot() -> None:
    argv = build_codex_argv("fix it", max_threads=3)
    assert argv == [
        "codex",
        "exec",
        "--json",
        "--sandbox",
        "workspace-write",
        "-c",
        "agents.max_concurrent_threads_per_session=3",
        "--disable",
        "code_mode",
        "--disable",
        "code_mode_host",
        "fix it",
    ]


def test_command_builder_can_explicitly_opt_in_to_codex_feature_defaults() -> None:
    argv = build_codex_argv("inspect", disabled_features=())
    assert "--disable" not in argv


def test_command_builder_can_disable_subagents() -> None:
    argv = build_codex_argv("inspect", max_threads=0)
    assert "agents.enabled=false" in argv
    assert not any(value.startswith("agents.max_concurrent_threads_per_session=") for value in argv)


def test_command_builder_rejects_invalid_feature_name() -> None:
    try:
        build_codex_argv("inspect", disabled_features=("bad feature",))
    except ValueError as error:
        assert "invalid disabled feature" in str(error)
    else:
        raise AssertionError("invalid feature name was accepted")


def test_unknown_event_is_tolerated_and_sensitive_payload_filtered() -> None:
    line = json.dumps({"type": "future.event", "reasoning": "private", "api_key": "secret", "x": 1})
    event = parse_codex_line(line)
    assert event.type == "worker.raw_event"
    assert event.payload["reasoning"] == "[FILTERED]"
    assert event.payload["api_key"] == "[REDACTED]"
    assert event.payload["x"] == 1


def test_malformed_event_and_usage() -> None:
    malformed = parse_codex_line("not-json api_key=secret")
    assert malformed.type == "worker.raw_event"
    assert malformed.raw is not None
    assert "secret" not in malformed.raw
    assert malformed.payload == {
        "type": "stream.unparseable",
        "raw": "[FILTERED]",
        "byte_length": 23,
    }
    event = parse_codex_line(
        '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":2}}'
    )
    assert extract_usage(event) == {"input_tokens": 10, "output_tokens": 2}


def test_command_output_is_filtered_by_default() -> None:
    event = parse_codex_line(
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "aggregated_output": "api_key=secret and local source",
                },
            }
        )
    )

    assert event.payload["item"]["aggregated_output"] == "[FILTERED]"
    assert event.raw is not None and "secret" not in event.raw


def test_chunked_reader_accepts_jsonl_larger_than_asyncio_readline_limit() -> None:
    long_line = json.dumps(
        {
            "type": "item.completed",
            "item": {"aggregated_output": "x" * 70_000},
        }
    ).encode()

    async def collect() -> list[tuple[bytes | None, int]]:
        reader = asyncio.StreamReader(limit=64 * 1024)
        reader.feed_data(long_line + b"\n")
        reader.feed_eof()
        return [item async for item in _bounded_stream_lines(reader)]

    lines = asyncio.run(collect())

    assert lines == [(long_line, len(long_line))]
    parsed_line = lines[0][0]
    assert parsed_line is not None
    assert parse_codex_line(parsed_line.decode()).type == "worker.activity"


def test_chunked_reader_drops_over_limit_line_and_keeps_following_event() -> None:
    oversized = b"x" * (MAX_STREAM_LINE_BYTES + 17)
    completed = b'{"type":"turn.completed"}'

    async def collect() -> list[tuple[bytes | None, int]]:
        reader = asyncio.StreamReader(limit=64 * 1024)
        reader.feed_data(oversized + b"\n" + completed + b"\n")
        reader.feed_eof()
        return [item async for item in _bounded_stream_lines(reader)]

    lines = asyncio.run(collect())

    assert lines == [(None, len(oversized)), (completed, len(completed))]
    parsed_line = lines[1][0]
    assert parsed_line is not None
    assert parse_codex_line(parsed_line.decode()).type == "worker.completed"


def test_stderr_persists_only_counts_without_sensitive_capture(tmp_path: Path) -> None:
    async def read() -> None:
        reader = asyncio.StreamReader(limit=64 * 1024)
        reader.feed_data(b"api_key=secret\nlocal source code\n")
        reader.feed_eof()
        process = cast(asyncio.subprocess.Process, SimpleNamespace(stderr=reader))
        request = StartAttemptRequest(
            "run",
            "task",
            "attempt",
            "prompt",
            tmp_path,
            60,
            {"artifact_dir": str(tmp_path)},
        )
        running = _Running(process, request, asyncio.Queue())
        await CodexExecAdapter()._read_stderr(running, capture_sensitive=False)

    asyncio.run(read())

    persisted = (tmp_path / "stderr.log").read_text(encoding="utf-8")
    assert "secret" not in persisted
    assert "source code" not in persisted
    assert json.loads(persisted) == {
        "type": "stderr.filtered",
        "line_count": 2,
        "byte_length": 31,
    }


def test_wait_does_not_block_on_descendant_owned_pipes(tmp_path: Path) -> None:
    class TimedOutProcess:
        pid = 123
        returncode = None

        async def wait(self) -> int:
            await asyncio.sleep(60)
            return 1

    async def run() -> None:
        process = cast(asyncio.subprocess.Process, TimedOutProcess())
        request = StartAttemptRequest("run", "task", "attempt", "prompt", tmp_path, 1, {})
        running = _Running(process, request, asyncio.Queue())
        readers = (asyncio.create_task(asyncio.sleep(60)), asyncio.create_task(asyncio.sleep(60)))
        adapter = CodexExecAdapter(cancel_grace_seconds=0.01)

        async def terminate(_: _Running) -> None:
            return None

        adapter._terminate = terminate  # type: ignore[assignment]
        await asyncio.wait_for(adapter._wait(running, readers), timeout=1.2)
        events = []
        while not running.queue.empty():
            events.append(await running.queue.get())
        assert events[-1] is None
        assert any(
            event is not None and event.payload.get("reason") == "timeout" for event in events
        )
        assert all(reader.cancelled() for reader in readers)

    asyncio.run(run())


@pytest.mark.skipif(os.name != "nt", reason="Windows process-tree behavior")
def test_windows_termination_invokes_recursive_taskkill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[object, ...]] = []

    class Killer:
        async def wait(self) -> int:
            return 0

    class Process:
        pid = 456
        returncode = None

        def terminate(self) -> None:
            self.returncode = 1

        async def wait(self) -> int:
            return 1

        def kill(self) -> None:
            self.returncode = 1

    async def create(*argv: object, **_: object) -> Killer:
        calls.append(argv)
        return Killer()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)

    async def run() -> None:
        request = StartAttemptRequest("run", "task", "attempt", "prompt", tmp_path, 1, {})
        running = _Running(cast(asyncio.subprocess.Process, Process()), request, asyncio.Queue())
        await CodexExecAdapter(cancel_grace_seconds=0.1)._terminate(running)

    asyncio.run(run())

    assert calls == [("taskkill.exe", "/PID", "456", "/T", "/F")]
