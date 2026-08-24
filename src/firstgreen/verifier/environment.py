"""Read-only discovery and preflight for deterministic verifier executables."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from firstgreen.errors import FirstGreenError


class VerifierEnvironmentError(FirstGreenError):
    """Raised before workers start when a verifier executable cannot be resolved."""


@dataclass(frozen=True)
class DetectedVerifierEnvironment:
    mode: Literal["explicit", "repository-venv", "path", "not-required"]
    repository: Path
    environment_root: Path | None
    resolved_executables: dict[str, str]
    warnings: tuple[str, ...] = ()


def _absolute(path: Path) -> Path:
    """Make a path absolute without resolving a virtualenv interpreter symlink."""

    return Path(os.path.abspath(path.expanduser()))


def _usable_file(path: Path) -> bool:
    return path.is_file() and (os.name == "nt" or os.access(path, os.X_OK))


def _environment_interpreter(root: Path) -> Path | None:
    candidates = (
        root / "Scripts" / "python.exe",
        root / "bin" / "python3",
        root / "bin" / "python",
    )
    return next((_absolute(candidate) for candidate in candidates if _usable_file(candidate)), None)


def _repository_environment(repository: Path) -> tuple[Path, Path] | None:
    candidates = [repository / ".venv", repository / "venv"]
    for variable in ("VIRTUAL_ENV", "CONDA_PREFIX"):
        value = os.environ.get(variable)
        if not value:
            continue
        candidate = Path(value).expanduser().resolve()
        if candidate == repository or candidate.is_relative_to(repository):
            candidates.append(candidate)
    seen: set[Path] = set()
    for root in candidates:
        normalized = root.expanduser().resolve()
        if normalized in seen:
            continue
        seen.add(normalized)
        interpreter = _environment_interpreter(normalized)
        if interpreter is not None:
            return normalized, interpreter
    return None


def _environment_bin(root: Path) -> Path:
    scripts = root / "Scripts"
    return scripts if scripts.is_dir() else root / "bin"


def _local_tool(root: Path, executable: str) -> Path | None:
    path = shutil.which(executable, path=str(_environment_bin(root)))
    if path is None:
        return None
    candidate = _absolute(Path(path))
    return candidate if _usable_file(candidate) else None


def detect_verifier_environment(
    repository: Path,
    commands: Iterable[tuple[str, ...] | None],
    *,
    explicit_overrides: Mapping[str, str] | None = None,
) -> DetectedVerifierEnvironment:
    """Resolve verifier programs without importing or executing repository code."""

    repo = repository.expanduser().resolve()
    explicit = dict(explicit_overrides or {})
    names = sorted(
        {
            command[0]
            for command in commands
            if command
            and not Path(command[0]).expanduser().is_absolute()
            and Path(command[0]).parent == Path(".")
        }
    )
    if not names:
        return DetectedVerifierEnvironment("not-required", repo, None, {})

    local = _repository_environment(repo)
    environment_root = local[0] if local is not None else None
    interpreter = local[1] if local is not None else None
    resolved: dict[str, str] = {}
    missing: list[str] = []
    warnings: list[str] = []
    for name in names:
        selected: Path | None = None
        if name in explicit:
            selected = _absolute(Path(explicit[name]))
        elif name in {"python", "python3"} and interpreter is not None:
            selected = interpreter
        elif environment_root is not None:
            selected = _local_tool(environment_root, name)
        if selected is None:
            discovered = shutil.which(name, path=os.environ.get("PATH"))
            selected = _absolute(Path(discovered)) if discovered else None
        if selected is None or not _usable_file(selected):
            missing.append(name)
        else:
            resolved[name] = str(selected)

    if missing:
        raise VerifierEnvironmentError(
            "verifier executable preflight failed before any worker started; missing: "
            + ", ".join(missing)
        )
    python_names = {name for name in names if name in {"python", "python3"}}
    if python_names and interpreter is None and not python_names.intersection(explicit):
        warnings.append("no repository .venv/venv was found; Python verifier is pinned from PATH")
    if explicit:
        mode: Literal["explicit", "repository-venv", "path", "not-required"] = "explicit"
    elif environment_root is not None:
        mode = "repository-venv"
    else:
        mode = "path"
    return DetectedVerifierEnvironment(
        mode,
        repo,
        environment_root,
        resolved,
        tuple(warnings),
    )
