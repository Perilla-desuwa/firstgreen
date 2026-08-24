"""`codex exec --json` subprocess adapter."""

import asyncio
import contextlib
import json
import os
import shutil
import signal
import subprocess
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

from firstgreen.adapters.base import (
    AttemptHandle,
    AttemptInspection,
    CancelResult,
    DoctorResult,
    StartAttemptRequest,
    WorkerEvent,
)
from firstgreen.adapters.codex_events import (
    oversized_codex_line,
    parse_codex_line,
    stream_reader_failed,
)

STREAM_READ_BYTES = 64 * 1024
MAX_STREAM_LINE_BYTES = 2_000_000


async def _bounded_stream_lines(
    reader: asyncio.StreamReader,
    *,
    max_line_bytes: int = MAX_STREAM_LINE_BYTES,
) -> AsyncIterator[tuple[bytes | None, int]]:
    """Read newline-delimited bytes without asyncio's 64 KiB readline limit.

    A line larger than ``max_line_bytes`` is drained but never retained. ``None``
    identifies that line to the caller, while the integer preserves its byte count
    for diagnostics. Later lines remain readable.
    """

    if max_line_bytes < 1:
        raise ValueError("max_line_bytes must be positive")
    buffered = bytearray()
    overflow_bytes = 0
    overflowed = False
    while chunk := await reader.read(STREAM_READ_BYTES):
        start = 0
        while start < len(chunk):
            newline = chunk.find(b"\n", start)
            end = len(chunk) if newline < 0 else newline
            segment = chunk[start:end]
            if overflowed:
                overflow_bytes += len(segment)
            elif len(buffered) + len(segment) > max_line_bytes:
                overflowed = True
                overflow_bytes = len(buffered) + len(segment)
                buffered.clear()
            else:
                buffered.extend(segment)
            if newline < 0:
                break
            if overflowed:
                yield None, overflow_bytes
            else:
                if buffered.endswith(b"\r"):
                    buffered.pop()
                line = bytes(buffered)
                yield line, len(line)
            buffered.clear()
            overflow_bytes = 0
            overflowed = False
            start = newline + 1
    if overflowed:
        yield None, overflow_bytes
    elif buffered:
        if buffered.endswith(b"\r"):
            buffered.pop()
        line = bytes(buffered)
        yield line, len(line)


def build_codex_argv(
    prompt: str,
    *,
    binary: str = "codex",
    sandbox: str = "workspace-write",
    max_threads: int = 1,
    disabled_features: tuple[str, ...] = ("code_mode", "code_mode_host"),
    extra_config: dict[str, str | int | bool] | None = None,
) -> list[str]:
    if sandbox not in {"read-only", "workspace-write", "danger-full-access"}:
        raise ValueError(f"unsupported sandbox: {sandbox}")
    if max_threads < 0:
        raise ValueError("max_threads cannot be negative")
    argv = [
        binary,
        "exec",
        "--json",
        "--sandbox",
        sandbox,
    ]
    if max_threads == 0:
        argv.extend(["-c", "agents.enabled=false"])
    else:
        argv.extend(["-c", f"agents.max_concurrent_threads_per_session={max_threads}"])
    for feature in disabled_features:
        if not feature or any(character.isspace() for character in feature):
            raise ValueError(f"invalid disabled feature: {feature!r}")
        argv.extend(["--disable", feature])
    for key, value in sorted((extra_config or {}).items()):
        argv.extend(["-c", f"{key}={str(value).lower() if isinstance(value, bool) else value}"])
    argv.append(prompt)
    return argv


@dataclass
class _Running:
    process: asyncio.subprocess.Process
    request: StartAttemptRequest
    queue: asyncio.Queue[WorkerEvent | None]
    tasks: list[asyncio.Task[None]] = field(default_factory=list)
    exit_code: int | None = None


class CodexExecAdapter:
    def __init__(self, binary: str = "codex", *, cancel_grace_seconds: float = 5.0) -> None:
        self.binary = binary
        self.cancel_grace_seconds = cancel_grace_seconds
        self._running: dict[str, _Running] = {}

    async def doctor(self) -> DoctorResult:
        binary = shutil.which(self.binary)
        if binary is None:
            return DoctorResult(False, "Codex CLI not found; install it and run codex login")
        try:
            process = await asyncio.create_subprocess_exec(
                binary,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
        except (OSError, TimeoutError) as error:
            return DoctorResult(False, f"Codex CLI could not run: {error}")
        output = (stdout or stderr).decode(errors="replace").strip()
        if process.returncode != 0:
            return DoctorResult(False, f"Codex CLI returned {process.returncode}: {output}")
        try:
            help_process = await asyncio.create_subprocess_exec(
                binary,
                "exec",
                "--help",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            help_stdout, help_stderr = await asyncio.wait_for(
                help_process.communicate(), timeout=10
            )
        except (OSError, TimeoutError) as error:
            return DoctorResult(False, f"Codex Exec help could not run: {error}", output)
        help_output = (help_stdout or help_stderr).decode(errors="replace")
        required_flags = {"--json", "--sandbox", "--disable"}
        missing = sorted(flag for flag in required_flags if flag not in help_output)
        if help_process.returncode != 0 or missing:
            detail = f"missing required flags: {', '.join(missing)}" if missing else "help failed"
            return DoctorResult(False, f"Codex Exec is incompatible: {detail}", output)
        return DoctorResult(
            True,
            "Codex CLI and required Exec flags are available; authentication is verified only "
            "by the opt-in live smoke test",
            output,
        )

    async def start(self, request: StartAttemptRequest) -> AttemptHandle:
        config = request.adapter_config
        sandbox = str(config.get("sandbox", "workspace-write"))
        max_threads = int(config.get("max_subagent_threads", 1))
        raw_disabled = config.get("disabled_features", ["code_mode", "code_mode_host"])
        disabled_features = (
            tuple(str(value) for value in raw_disabled)
            if isinstance(raw_disabled, list)
            else ("code_mode", "code_mode_host")
        )
        raw_extra = config.get("config", {})
        extra: dict[str, str | int | bool] = {}
        if isinstance(raw_extra, dict):
            extra = {
                str(key): value
                for key, value in raw_extra.items()
                if isinstance(value, str | int | bool)
            }
        argv = build_codex_argv(
            request.prompt,
            binary=self.binary,
            sandbox=sandbox,
            max_threads=max_threads,
            disabled_features=disabled_features,
            extra_config=extra,
        )
        creationflags = (
            int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) if os.name == "nt" else 0
        )
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=request.worktree,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=os.name != "nt",
            creationflags=creationflags,
        )
        queue: asyncio.Queue[WorkerEvent | None] = asyncio.Queue(maxsize=1000)
        running = _Running(process, request, queue)
        self._running[request.attempt_id] = running
        capture_sensitive = bool(config.get("capture_sensitive_events", False))
        stdout_task = asyncio.create_task(self._read_stdout(running, capture_sensitive))
        stderr_task = asyncio.create_task(self._read_stderr(running, capture_sensitive))
        wait_task = asyncio.create_task(self._wait(running, (stdout_task, stderr_task)))
        running.tasks = [stdout_task, stderr_task, wait_task]
        return AttemptHandle("codex_exec", request.attempt_id, process.pid)

    async def _read_stdout(self, running: _Running, capture_sensitive: bool) -> None:
        assert running.process.stdout is not None
        artifact = self._artifact_path(running.request, "events.jsonl")
        try:
            async for line, byte_length in _bounded_stream_lines(running.process.stdout):
                event = (
                    oversized_codex_line(byte_length)
                    if line is None
                    else parse_codex_line(
                        line.decode(errors="replace"), capture_sensitive=capture_sensitive
                    )
                )
                await running.queue.put(event)
                if artifact is not None and event.raw is not None:
                    self._append(artifact, event.raw)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await running.queue.put(stream_reader_failed("stdout", error))
            await self._terminate(running)

    async def _read_stderr(self, running: _Running, capture_sensitive: bool) -> None:
        assert running.process.stderr is not None
        artifact = self._artifact_path(running.request, "stderr.log")
        line_count = 0
        byte_length = 0
        try:
            async for line, line_bytes in _bounded_stream_lines(running.process.stderr):
                line_count += 1
                byte_length += line_bytes
                if artifact is not None and capture_sensitive:
                    rendered = (
                        f"[oversized stderr line dropped: {line_bytes} bytes]"
                        if line is None
                        else line.decode(errors="replace")
                    )
                    self._append(artifact, rendered)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await running.queue.put(stream_reader_failed("stderr", error))
            await self._terminate(running)
        finally:
            if artifact is not None and not capture_sensitive and line_count:
                self._append(
                    artifact,
                    json.dumps(
                        {
                            "type": "stderr.filtered",
                            "line_count": line_count,
                            "byte_length": byte_length,
                        },
                        sort_keys=True,
                    ),
                )

    async def _wait(
        self,
        running: _Running,
        readers: tuple[asyncio.Task[None], asyncio.Task[None]],
    ) -> None:
        try:
            running.exit_code = await asyncio.wait_for(
                running.process.wait(), timeout=running.request.timeout_seconds
            )
        except TimeoutError:
            await self._terminate(running)
            await running.queue.put(parse_codex_line('{"type":"turn.failed","reason":"timeout"}'))
        try:
            await asyncio.wait_for(
                asyncio.gather(*readers, return_exceptions=True),
                timeout=self.cancel_grace_seconds,
            )
        except TimeoutError:
            # A descendant can outlive the Codex parent while retaining an inherited
            # stdout/stderr pipe. Never let pipe EOF defeat the attempt timeout.
            for reader in readers:
                reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)
        await running.queue.put(None)

    def _artifact_path(self, request: StartAttemptRequest, name: str) -> Path | None:
        configured = request.adapter_config.get("artifact_dir")
        if not isinstance(configured, str):
            return None
        root = Path(configured).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root / name

    @staticmethod
    def _append(path: Path, line: str) -> None:
        with path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")

    async def events(self, handle: AttemptHandle) -> AsyncIterator[WorkerEvent]:
        running = self._running[handle.external_id]
        while True:
            event = await running.queue.get()
            if event is None:
                break
            yield event

    async def _terminate(self, running: _Running) -> None:
        process = running.process
        if process.returncode is not None:
            return
        if os.name != "nt":
            with contextlib.suppress(ProcessLookupError):
                os.kill(-process.pid, signal.SIGTERM)
        else:
            # CREATE_NEW_PROCESS_GROUP does not make Process.terminate() recursive.
            # Kill the complete tree so model-launched test processes cannot retain
            # our pipes after the parent reaches its hard timeout.
            with contextlib.suppress(OSError, TimeoutError):
                killer = await asyncio.create_subprocess_exec(
                    "taskkill.exe",
                    "/PID",
                    str(process.pid),
                    "/T",
                    "/F",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(killer.wait(), timeout=self.cancel_grace_seconds)
            if process.returncode is None:
                process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=self.cancel_grace_seconds)
        except TimeoutError:
            if os.name != "nt":
                with contextlib.suppress(ProcessLookupError):
                    os.kill(-process.pid, 9)
            else:
                process.kill()
            await process.wait()

    async def cancel(self, handle: AttemptHandle, reason: str) -> CancelResult:
        running = self._running.get(handle.external_id)
        if running is None:
            return CancelResult(False, "attempt handle not found")
        await self._terminate(running)
        return CancelResult(True, reason)

    async def inspect(self, handle: AttemptHandle) -> AttemptInspection:
        running = self._running.get(handle.external_id)
        if running is None:
            return AttemptInspection("unknown")
        code = running.process.returncode
        return AttemptInspection("running" if code is None else "terminal", code)
