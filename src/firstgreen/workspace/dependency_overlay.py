"""Safely compose verified dependency snapshots into a downstream worktree."""

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from firstgreen.config import TaskConfig
from firstgreen.errors import WorkspaceSafetyError
from firstgreen.verifier.runner import changed_paths
from firstgreen.workspace.git_worktree import Workspace


@dataclass(frozen=True)
class DependencySnapshot:
    """A scheduler-owned, verifier-approved dependency workspace."""

    task: TaskConfig
    workspace: Path
    base_sha: str


class WorkspacePreparer(Protocol):
    async def prepare(
        self, workspace: Workspace, dependencies: tuple[DependencySnapshot, ...]
    ) -> None: ...


class RepairWorkspacePreparer(Protocol):
    async def prepare(self, workspace: Workspace, failed_workspace: Workspace) -> None: ...


def _bounded_child(root: Path, relative: str) -> Path:
    candidate = PurePosixPath(relative)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise WorkspaceSafetyError(f"unsafe dependency path: {relative}")
    resolved = (root / Path(*candidate.parts)).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise WorkspaceSafetyError(f"dependency path escapes workspace: {relative}")
    return resolved


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class VerifiedDependencyOverlay:
    """Copy only changed files from verified direct dependencies.

    A dependency winner may already include its own ancestors. Copying its verified
    diff therefore carries the full validated chain into a downstream worktree.
    Conflicting snapshots are rejected instead of being resolved by copy order.
    """

    async def prepare(
        self, workspace: Workspace, dependencies: tuple[DependencySnapshot, ...]
    ) -> None:
        target_root = workspace.path.resolve()
        copied: dict[str, str | None] = {}
        for dependency in dependencies:
            source_root = dependency.workspace.resolve()
            for relative in await changed_paths(source_root, dependency.base_sha):
                source = _bounded_child(source_root, relative)
                target = _bounded_child(target_root, relative)
                if source.is_symlink():
                    raise WorkspaceSafetyError(
                        f"dependency overlay refuses symbolic link: {relative}"
                    )
                digest = _digest(source) if source.is_file() else None
                if relative in copied and copied[relative] != digest:
                    raise WorkspaceSafetyError(
                        f"verified dependencies contain conflicting file: {relative}"
                    )
                copied[relative] = digest
                if source.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                elif source.exists():
                    raise WorkspaceSafetyError(
                        f"dependency overlay supports files only: {relative}"
                    )
                elif target.is_file():
                    target.unlink()
                elif target.exists():
                    raise WorkspaceSafetyError(
                        f"dependency deletion is not a regular file: {relative}"
                    )


class FailedAttemptOverlay:
    """Carry an unverified attempt forward only into its isolated repair worktree."""

    async def prepare(self, workspace: Workspace, failed_workspace: Workspace) -> None:
        if (
            workspace.repo.resolve() != failed_workspace.repo.resolve()
            or workspace.base_sha != failed_workspace.base_sha
            or workspace.run_id != failed_workspace.run_id
            or workspace.task_id != failed_workspace.task_id
            or workspace.attempt_id == failed_workspace.attempt_id
        ):
            raise WorkspaceSafetyError("repair overlay requires matching isolated task identity")
        source_root = failed_workspace.path.resolve()
        target_root = workspace.path.resolve()
        for relative in await changed_paths(source_root, failed_workspace.base_sha):
            source = _bounded_child(source_root, relative)
            target = _bounded_child(target_root, relative)
            if source.is_symlink():
                raise WorkspaceSafetyError(f"repair overlay refuses symbolic link: {relative}")
            if source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            elif source.exists():
                raise WorkspaceSafetyError(f"repair overlay supports files only: {relative}")
            elif target.is_file():
                target.unlink()
            elif target.exists():
                raise WorkspaceSafetyError(f"repair deletion is not a regular file: {relative}")
