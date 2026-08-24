"""Bounded asynchronous verifier command runner."""

import asyncio
import hashlib
import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from firstgreen.path_patterns import path_matches


@dataclass(frozen=True)
class VerificationCommand:
    argv: tuple[str, ...] | None = None
    command: str | None = None
    shell: bool = False
    timeout_seconds: float = 900

    def __post_init__(self) -> None:
        if (self.argv is None) == (self.command is None):
            raise ValueError("provide exactly one of argv or command")
        if self.argv is not None and not self.argv:
            raise ValueError("argv verifier command cannot be empty")
        if self.command is not None and not self.shell:
            raise ValueError("string verifier commands require explicit shell=True")


@dataclass(frozen=True)
class VerificationRequest:
    attempt_id: str
    worktree: Path
    base_sha: str
    commands: tuple[VerificationCommand, ...]
    allowed_changed_paths: tuple[str, ...] = ()
    max_output_bytes: int = 2_000_000


@dataclass(frozen=True)
class CommandResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    output_truncated: bool
    started_at: str
    finished_at: str
    resolved_executable: str | None
    launch_error_kind: str | None


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    commands: tuple[CommandResult, ...]
    changed_paths: tuple[str, ...]
    disallowed_paths: tuple[str, ...]
    diff_hash: str


class Verifier(Protocol):
    async def verify(self, request: VerificationRequest) -> VerificationResult: ...


async def _run_capture(*argv: str, cwd: Path) -> bytes:
    process = await asyncio.create_subprocess_exec(
        *argv, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await process.communicate()
    if process.returncode != 0:
        return b""
    return stdout


async def changed_paths(worktree: Path, base_sha: str) -> tuple[str, ...]:
    sources = await asyncio.gather(
        _run_capture("git", "diff", "--name-only", f"{base_sha}...HEAD", cwd=worktree),
        _run_capture("git", "diff", "--name-only", cwd=worktree),
        _run_capture("git", "diff", "--name-only", "--cached", cwd=worktree),
        _run_capture("git", "ls-files", "--others", "--exclude-standard", cwd=worktree),
    )
    names = {
        line.strip().replace("\\", "/")
        for source in sources
        for line in source.decode(errors="replace").splitlines()
        if line.strip()
        and line.strip() != ".firstgreen-attempt.json"
        and "__pycache__" not in Path(line.strip()).parts
        and Path(line.strip()).suffix.lower() not in {".pyc", ".pyo"}
    }
    return tuple(sorted(names))


def _allowed(path: str, patterns: tuple[str, ...]) -> bool:
    return not patterns or any(path_matches(path, pattern) for pattern in patterns)


class CommandVerifier:
    def __init__(
        self,
        slots: int = 1,
        *,
        executable_overrides: Mapping[str, str] | None = None,
    ) -> None:
        if slots < 1:
            raise ValueError("verifier slots must be positive")
        self._semaphore = asyncio.Semaphore(slots)
        self._executable_overrides = dict(executable_overrides or {})

    def _resolve_executable(self, executable: str, cwd: Path) -> str:
        override = self._executable_overrides.get(executable)
        if override is not None:
            return os.path.abspath(Path(override).expanduser())
        candidate = Path(executable).expanduser()
        if candidate.is_absolute():
            return str(candidate)
        if candidate.parent != Path("."):
            return str((cwd / candidate).resolve())
        # On Windows, CreateProcess may search the host application's directory
        # before PATH. Resolve bare verifier tools ourselves so an activated target
        # repository environment wins deterministically.
        return shutil.which(executable, path=os.environ.get("PATH")) or executable

    async def verify(self, request: VerificationRequest) -> VerificationResult:
        async with self._semaphore:
            paths = await changed_paths(request.worktree, request.base_sha)
            disallowed = tuple(
                path for path in paths if not _allowed(path, request.allowed_changed_paths)
            )
            results: list[CommandResult] = []
            for command in request.commands:
                result = await self._run(command, request.worktree, request.max_output_bytes)
                results.append(result)
                if result.timed_out or result.exit_code != 0:
                    break
            diff = await _run_capture(
                "git", "diff", "--binary", request.base_sha, cwd=request.worktree
            )
            digest = hashlib.sha256(diff + "\0".join(paths).encode()).hexdigest()
            passed = (
                not disallowed
                and len(results) == len(request.commands)
                and all(result.exit_code == 0 and not result.timed_out for result in results)
            )
            return VerificationResult(passed, tuple(results), paths, disallowed, digest)

    async def _run(
        self, command: VerificationCommand, cwd: Path, max_output_bytes: int
    ) -> CommandResult:
        started_at = datetime.now(UTC).isoformat()
        resolved_executable: str | None = None
        try:
            if command.argv is not None:
                resolved_executable = self._resolve_executable(command.argv[0], cwd)
                process = await asyncio.create_subprocess_exec(
                    resolved_executable,
                    *command.argv[1:],
                    cwd=cwd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=os.environ.copy(),
                )
            else:
                assert command.command is not None and command.shell
                process = await asyncio.create_subprocess_shell(
                    command.command,
                    cwd=cwd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=os.environ.copy(),
                )
        except OSError as error:
            windows_code = getattr(error, "winerror", None)
            error_code = windows_code if windows_code is not None else error.errno
            return CommandResult(
                None,
                "",
                "",
                False,
                False,
                started_at,
                datetime.now(UTC).isoformat(),
                resolved_executable,
                f"{type(error).__name__}:{error_code}",
            )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=command.timeout_seconds
            )
            timed_out = False
        except asyncio.CancelledError:
            process.kill()
            await process.communicate()
            raise
        except TimeoutError:
            process.kill()
            stdout, stderr = await process.communicate()
            timed_out = True
        joined_length = len(stdout) + len(stderr)
        stdout_limit = min(len(stdout), max_output_bytes)
        remaining = max(0, max_output_bytes - stdout_limit)
        return CommandResult(
            process.returncode,
            stdout[:stdout_limit].decode(errors="replace"),
            stderr[:remaining].decode(errors="replace"),
            timed_out,
            joined_length > max_output_bytes,
            started_at,
            datetime.now(UTC).isoformat(),
            resolved_executable,
            None,
        )
