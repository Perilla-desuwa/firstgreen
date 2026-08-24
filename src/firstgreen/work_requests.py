"""User-facing work request inputs.

GitHub issues are one possible source, not FirstGreen's product boundary.  This
module normalizes local inputs before they enter the existing planning engine.
"""

from __future__ import annotations

import hashlib
import platform
import shutil
import subprocess
import sys
from enum import StrEnum
from pathlib import Path
from typing import IO, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkRequestSourceType(StrEnum):
    INLINE = "inline"
    CLIPBOARD = "clipboard"
    STDIN = "stdin"
    FILE = "file"
    GITHUB = "github"
    LINEAR = "linear"
    API = "api"


class WorkRequestSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: WorkRequestSourceType
    reference: str | None = None


class WorkRequest(BaseModel):
    """A normalized request ready for repository-aware planning."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    source: WorkRequestSource
    content: str = Field(min_length=1)
    repository: Path
    source_repository: Path | None = None
    repository_mode: Literal["clean", "head", "snapshot"] = "clean"
    dirty_entries: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("content")
    @classmethod
    def non_empty_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("work request content cannot be empty")
        return normalized

    @property
    def request_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


class ClipboardUnavailable(RuntimeError):
    """Raised when no safe local clipboard reader can be used."""


def inline_request(content: str, repository: Path) -> WorkRequest:
    return WorkRequest(
        source=WorkRequestSource(type=WorkRequestSourceType.INLINE),
        content=content,
        repository=repository.expanduser().resolve(),
    )


def stdin_request(repository: Path, stream: IO[str] | None = None) -> WorkRequest:
    source = stream or sys.stdin
    return WorkRequest(
        source=WorkRequestSource(type=WorkRequestSourceType.STDIN, reference="-"),
        content=source.read(),
        repository=repository.expanduser().resolve(),
    )


def file_request(path: Path, repository: Path) -> WorkRequest:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"work request file does not exist: {path}")
    return WorkRequest(
        source=WorkRequestSource(type=WorkRequestSourceType.FILE, reference=str(resolved)),
        content=resolved.read_text(encoding="utf-8"),
        repository=repository.expanduser().resolve(),
    )


def request_from_token(
    token: str,
    repository: Path,
    *,
    stream: IO[str] | None = None,
) -> WorkRequest:
    """Resolve ``-``, an existing file, or inline natural-language text."""

    if token == "-":
        return stdin_request(repository, stream)
    candidate = Path(token).expanduser()
    try:
        if candidate.exists():
            return file_request(candidate, repository)
    except OSError:
        # Long natural-language requests are not reliable filesystem paths on Windows.
        pass
    return inline_request(token, repository)


def _clipboard_command() -> list[str] | None:
    system = platform.system()
    if system == "Windows":
        executable = shutil.which("powershell.exe") or shutil.which("powershell")
        if executable:
            return [executable, "-NoProfile", "-NonInteractive", "-Command", "Get-Clipboard -Raw"]
    elif system == "Darwin":
        executable = shutil.which("pbpaste")
        if executable:
            return [executable]
    else:
        for name, arguments in (
            ("wl-paste", ["--no-newline"]),
            ("xclip", ["-selection", "clipboard", "-o"]),
        ):
            executable = shutil.which(name)
            if executable:
                return [executable, *arguments]
    return None


def read_clipboard() -> str:
    """Read the local clipboard without a shell or network access."""

    command = _clipboard_command()
    if command is None:
        raise ClipboardUnavailable(
            "no supported clipboard reader found (PowerShell, pbpaste, wl-paste, or xclip)"
        )
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        raise ClipboardUnavailable("clipboard reader failed")
    content = result.stdout.strip()
    if not content:
        raise ClipboardUnavailable("clipboard is empty")
    return content


def clipboard_request(repository: Path) -> WorkRequest:
    return WorkRequest(
        source=WorkRequestSource(type=WorkRequestSourceType.CLIPBOARD),
        content=read_clipboard(),
        repository=repository.expanduser().resolve(),
    )
