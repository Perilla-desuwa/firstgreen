"""Create isolated, deterministic Git copies of the TinyShop baseline."""

import os
import shutil
import subprocess
from pathlib import Path

from firstgreen.testbed.loaders import TESTBED_ROOT

TINYSHOP_SOURCE = TESTBED_ROOT / "tinyshop"


def _git(repo: Path, *args: str) -> str:
    environment = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2026-07-14T00:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-07-14T00:00:00+00:00",
    }
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    if result.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def create_tinyshop_repository(workspace: Path, name: str) -> Path:
    """Copy the immutable baseline and make one deterministic local Git repository."""
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    target = (workspace / f"tinyshop-{name.lower()}").resolve()
    if target.parent != workspace:
        raise ValueError("scenario repository escaped its workspace")
    if target.exists():
        raise FileExistsError(f"scenario repository already exists: {target}")
    shutil.copytree(
        TINYSHOP_SOURCE,
        target,
        ignore=shutil.ignore_patterns(".git", ".pytest_cache", ".ruff_cache", "__pycache__"),
    )
    _git(target, "init", "-b", "main")
    _git(target, "config", "user.email", "testbed@example.invalid")
    _git(target, "config", "user.name", "FirstGreen Testbed")
    _git(target, "add", ".")
    _git(target, "commit", "-m", "tinyshop baseline")
    return target


def repository_commit(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD")
