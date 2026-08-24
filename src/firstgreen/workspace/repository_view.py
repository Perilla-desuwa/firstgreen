"""Immutable repository views for planning and worker consistency.

The target repository is always read-only.  When a dirty tree must be captured,
FirstGreen commits it only inside a managed clone under its state directory.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal
from uuid import uuid4

from firstgreen.errors import WorkspaceSafetyError

DirtyMode = Literal["block", "head", "snapshot"]
RepositoryMode = Literal["clean", "head", "snapshot"]
SNAPSHOT_MARKER = ".firstgreen-repository.json"


@dataclass(frozen=True)
class RepositoryView:
    source_repo: Path
    execution_repo: Path
    base_sha: str
    mode: RepositoryMode
    dirty_entries: tuple[str, ...]
    managed_root: Path | None = None


def _git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise WorkspaceSafetyError(detail or f"git command failed: {' '.join(args)}")
    return result.stdout


def _git_text(repo: Path, *args: str) -> str:
    return _git(repo, *args).decode(errors="replace").strip()


def _repository_root(repository: Path) -> Path:
    candidate = repository.expanduser().resolve()
    root = Path(_git_text(candidate, "rev-parse", "--show-toplevel")).resolve()
    if root != candidate:
        raise WorkspaceSafetyError(f"repository must be its Git worktree root: {root}")
    return root


def _dirty_entries(repo: Path, *, limit: int = 20) -> tuple[str, ...]:
    raw = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    entries: list[str] = []
    for line in raw.decode(errors="replace").splitlines():
        safe = "".join(character if character.isprintable() else "?" for character in line)
        entries.append(safe[:300])
        if len(entries) == limit:
            break
    return tuple(entries)


def _git_paths(repo: Path, *args: str) -> tuple[PurePosixPath, ...]:
    values: list[PurePosixPath] = []
    for raw in _git(repo, *args).split(b"\0"):
        if not raw:
            continue
        path = PurePosixPath(os.fsdecode(raw))
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise WorkspaceSafetyError(f"unsafe Git path in repository snapshot: {path}")
        values.append(path)
    return tuple(values)


def _bounded_path(root: Path, relative: PurePosixPath) -> Path:
    candidate = root.joinpath(*relative.parts)
    resolved_parent = candidate.parent.resolve()
    if resolved_parent != root and not resolved_parent.is_relative_to(root):
        raise WorkspaceSafetyError(f"snapshot path escapes managed repository: {relative}")
    return candidate


def _copy_working_changes(source: Path, destination: Path) -> None:
    changed = set(
        _git_paths(
            source,
            "diff",
            "--name-only",
            "-z",
            "--no-renames",
            "--diff-filter=ACMRTUXB",
            "HEAD",
            "--",
        )
    )
    changed.update(_git_paths(source, "ls-files", "--others", "--exclude-standard", "-z"))
    deleted = set(
        _git_paths(
            source,
            "diff",
            "--name-only",
            "-z",
            "--no-renames",
            "--diff-filter=D",
            "HEAD",
            "--",
        )
    )

    for relative in sorted(deleted, key=str):
        target = _bounded_path(destination, relative)
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.exists():
            raise WorkspaceSafetyError(f"cannot snapshot deletion of non-file path: {relative}")

    for relative in sorted(changed - deleted, key=str):
        source_path = _bounded_path(source, relative)
        destination_path = _bounded_path(destination, relative)
        try:
            source_mode = source_path.lstat().st_mode
        except OSError as error:
            raise WorkspaceSafetyError(
                f"cannot read changed path for snapshot: {relative}"
            ) from error
        if stat.S_ISLNK(source_mode):
            raise WorkspaceSafetyError(f"changed symbolic links are not snapshot-safe: {relative}")
        if not stat.S_ISREG(source_mode):
            raise WorkspaceSafetyError(f"changed path is not a regular file: {relative}")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        if destination_path.is_symlink():
            raise WorkspaceSafetyError(f"snapshot destination is a symbolic link: {relative}")
        shutil.copy2(source_path, destination_path)


def _managed_clone(
    source: Path,
    state_dir: Path,
    *,
    source_sha: str,
    mode: Literal["head", "snapshot"],
) -> tuple[Path, Path]:
    state = state_dir.expanduser().resolve()
    if state == source or state.is_relative_to(source):
        raise WorkspaceSafetyError(
            "managed repository snapshots must be outside the target repository"
        )
    root = state / "repository-snapshots" / f"r-{uuid4().hex[:16]}"
    repository = root / "repo"
    root.mkdir(parents=True, exist_ok=False)
    marker = {
        "version": 1,
        "source_repo": str(source),
        "execution_repo": str(repository),
        "source_sha": source_sha,
        "mode": mode,
    }
    (root / SNAPSHOT_MARKER).write_text(json.dumps(marker, indent=2), encoding="utf-8")
    result = subprocess.run(
        [
            "git",
            "clone",
            "--quiet",
            "--no-hardlinks",
            "--no-checkout",
            str(source),
            str(repository),
        ],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise WorkspaceSafetyError(detail or "could not create managed repository clone")
    _git(repository, "checkout", "--quiet", "--detach", source_sha)
    return root, repository


def prepare_repository_view(
    repository: Path,
    state_dir: Path,
    *,
    dirty_mode: DirtyMode = "block",
    base_ref: str = "HEAD",
) -> RepositoryView:
    """Return the exact repository and SHA that both planner and workers must use."""

    if dirty_mode not in {"block", "head", "snapshot"}:
        raise ValueError("dirty mode must be block, head, or snapshot")
    source = _repository_root(repository)
    source_sha = _git_text(source, "rev-parse", f"{base_ref}^{{commit}}")
    dirty_entries = _dirty_entries(source)
    if dirty_entries and dirty_mode == "block":
        sample = ", ".join(dirty_entries)
        raise WorkspaceSafetyError(
            "repository has uncommitted changes; commit/stash them, or explicitly use "
            f"--dirty-mode head|snapshot. Changed paths: {sample}"
        )
    if not dirty_entries and dirty_mode != "snapshot":
        return RepositoryView(source, source, source_sha, "clean", ())

    managed_mode: Literal["head", "snapshot"] = "snapshot" if dirty_mode == "snapshot" else "head"
    root, clone = _managed_clone(source, state_dir, source_sha=source_sha, mode=managed_mode)
    result_sha = source_sha
    if managed_mode == "snapshot":
        _copy_working_changes(source, clone)
        _git(clone, "add", "--all")
        environment = os.environ.copy()
        environment.update(
            {
                "GIT_AUTHOR_NAME": "FirstGreen Snapshot",
                "GIT_AUTHOR_EMAIL": "snapshot@firstgreen.invalid",
                "GIT_COMMITTER_NAME": "FirstGreen Snapshot",
                "GIT_COMMITTER_EMAIL": "snapshot@firstgreen.invalid",
            }
        )
        staged = subprocess.run(
            ["git", "-C", str(clone), "diff", "--cached", "--quiet"],
            check=False,
            capture_output=True,
        )
        if staged.returncode not in {0, 1}:
            raise WorkspaceSafetyError("could not inspect managed repository snapshot")
        if staged.returncode == 1:
            commit = subprocess.run(
                [
                    "git",
                    "-C",
                    str(clone),
                    "commit",
                    "--quiet",
                    "-m",
                    "FirstGreen working tree snapshot",
                ],
                check=False,
                capture_output=True,
                env=environment,
            )
            if commit.returncode != 0:
                detail = commit.stderr.decode(errors="replace").strip()
                raise WorkspaceSafetyError(detail or "could not commit managed repository snapshot")
            result_sha = _git_text(clone, "rev-parse", "HEAD")

    marker_path = root / SNAPSHOT_MARKER
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["base_sha"] = result_sha
    marker_path.write_text(json.dumps(marker, indent=2), encoding="utf-8")
    return RepositoryView(source, clone, result_sha, managed_mode, dirty_entries, root)
