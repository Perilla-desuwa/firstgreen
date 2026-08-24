"""Non-secret, local machine defaults for the FirstGreen CLI."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class UserConfigError(ValueError):
    """Raised when the local CLI configuration cannot be loaded safely."""


class UserConfig(BaseModel):
    """Persisted convenience defaults; credentials are deliberately unsupported."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    adapter: Literal["codex_exec", "fake"] = "codex_exec"
    planner_provider: Literal["fake", "codex"] = "fake"
    codex_binary: str | None = None
    worker_model: str | None = None
    worker_reasoning: str | None = None
    planner_model: str = "auto"
    dirty_mode: Literal["block", "head", "snapshot"] = "block"
    state_dir: str | None = None
    recent_repositories: list[str] = Field(default_factory=list, max_length=20)


def user_config_path() -> Path:
    override = os.environ.get("FIRSTGREEN_CONFIG")
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".firstgreen" / "config.yaml").resolve()


def load_user_config(path: Path | None = None) -> UserConfig:
    target = (path or user_config_path()).expanduser().resolve()
    if not target.exists():
        return UserConfig()
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
        return UserConfig.model_validate(raw or {})
    except (OSError, ValidationError, yaml.YAMLError) as error:
        raise UserConfigError(f"invalid FirstGreen user config {target}: {error}") from error


def save_user_config(config: UserConfig, path: Path | None = None) -> Path:
    target = (path or user_config_path()).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f"{target.suffix}.tmp")
    temporary.write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


def codex_binary_candidates(
    *, explicit: str | None = None, configured: str | None = None
) -> tuple[str, ...]:
    """Return ordered local candidates without executing or authenticating them."""

    if explicit:
        return (explicit,)
    values: list[str] = []
    for value in (configured, os.environ.get("FIRSTGREEN_CODEX_BINARY")):
        if value:
            values.append(value)
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        executable = "codex.exe" if os.name == "nt" else "codex"
        values.append(str(Path(codex_home) / ".sandbox-bin" / executable))
    discovered = shutil.which("codex")
    if discovered:
        values.append(discovered)
    values.append("codex")
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = os.path.normcase(os.path.abspath(value)) if Path(value).is_absolute() else value
        if key not in seen:
            seen.add(key)
            unique.append(value)
    return tuple(unique)


def remember_repository(config: UserConfig, repository: Path) -> UserConfig:
    resolved = str(repository.expanduser().resolve())
    recent = [resolved, *(item for item in config.recent_repositories if item != resolved)][:20]
    return config.model_copy(update={"recent_repositories": recent})
