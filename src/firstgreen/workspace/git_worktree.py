"""Path-bounded git worktree management with marker confirmation."""

import asyncio
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from firstgreen.errors import WorkspaceSafetyError

MARKER = ".firstgreen-attempt.json"


@dataclass(frozen=True)
class WorkspaceSpec:
    run_id: str
    task_id: str
    attempt_id: str
    repo: Path
    base_ref: str


@dataclass(frozen=True)
class Workspace:
    id: str
    path: Path
    branch: str
    repo: Path
    base_sha: str
    run_id: str
    task_id: str
    attempt_id: str


@dataclass(frozen=True)
class WorkspaceStatus:
    exists: bool
    marker_valid: bool
    registered: bool


class WorkspaceManager(Protocol):
    async def create_attempt_workspace(self, spec: WorkspaceSpec) -> Workspace: ...
    async def inspect(self, workspace: Workspace) -> WorkspaceStatus: ...
    async def cleanup(
        self, workspace: Workspace, *, is_winner: bool = False, dry_run: bool = False
    ) -> None: ...


def _workspace_digest(spec: WorkspaceSpec) -> str:
    """Keep worktree and Git ref paths short without weakening stored identity."""
    payload = json.dumps(
        [spec.run_id, spec.task_id, spec.attempt_id, str(spec.repo.resolve()), spec.base_ref],
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


async def _git(repo: Path, *args: str) -> str:
    process = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(repo),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise WorkspaceSafetyError(stderr.decode(errors="replace").strip())
    return stdout.decode().strip()


class GitWorktreeManager:
    def __init__(self, root: Path, *, keep_winner: bool = True) -> None:
        self.root = root.resolve()
        self.keep_winner = keep_winner

    def _bounded(self, path: Path) -> Path:
        resolved = path.resolve()
        if resolved == self.root or not resolved.is_relative_to(self.root):
            raise WorkspaceSafetyError(f"workspace path outside dedicated root: {resolved}")
        return resolved

    async def create_attempt_workspace(self, spec: WorkspaceSpec) -> Workspace:
        repo = Path(await _git(spec.repo, "rev-parse", "--show-toplevel")).resolve()
        if spec.repo.resolve() != repo:
            raise WorkspaceSafetyError("repository must be its main worktree root")
        base_sha = await _git(repo, "rev-parse", f"{spec.base_ref}^{{commit}}")
        digest = _workspace_digest(spec)
        path = self._bounded(self.root / f"w-{digest[:20]}")
        branch = f"fg/{digest[:24]}"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise WorkspaceSafetyError(f"workspace already exists: {path}")
        await _git(repo, "worktree", "add", "-b", branch, str(path), base_sha)
        workspace = Workspace(
            spec.attempt_id,
            path,
            branch,
            repo,
            base_sha,
            spec.run_id,
            spec.task_id,
            spec.attempt_id,
        )
        try:
            (path / MARKER).write_text(
                json.dumps({**asdict(workspace), "path": str(path), "repo": str(repo)}, indent=2),
                encoding="utf-8",
            )
        except BaseException:
            await _git(repo, "worktree", "remove", "--force", str(path))
            raise
        return workspace

    async def create_backup_workspace(self, primary: Workspace, *, attempt_id: str) -> Workspace:
        """Create a hedge from the primary's pinned SHA, never from a moving branch."""
        return await self.create_attempt_workspace(
            WorkspaceSpec(
                primary.run_id,
                primary.task_id,
                attempt_id,
                primary.repo,
                primary.base_sha,
            )
        )

    def _marker_matches(self, workspace: Workspace) -> bool:
        marker = self._bounded(workspace.path) / MARKER
        if not marker.is_file():
            return False
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        expected = {
            "id": workspace.id,
            "run_id": workspace.run_id,
            "task_id": workspace.task_id,
            "attempt_id": workspace.attempt_id,
            "repo": str(workspace.repo),
            "base_sha": workspace.base_sha,
            "path": str(workspace.path),
            "branch": workspace.branch,
        }
        return all(data.get(key) == value for key, value in expected.items())

    async def inspect(self, workspace: Workspace) -> WorkspaceStatus:
        path = self._bounded(workspace.path)
        listing = await _git(workspace.repo, "worktree", "list", "--porcelain")
        registered_paths = [
            Path(line.removeprefix("worktree ")).resolve()
            for line in listing.splitlines()
            if line.startswith("worktree ")
        ]
        registered = path in registered_paths
        return WorkspaceStatus(path.exists(), self._marker_matches(workspace), registered)

    async def cleanup(
        self, workspace: Workspace, *, is_winner: bool = False, dry_run: bool = False
    ) -> None:
        path = self._bounded(workspace.path)
        if is_winner and self.keep_winner:
            return
        if not path.exists():
            return
        status = await self.inspect(workspace)
        if not status.marker_valid or not status.registered:
            raise WorkspaceSafetyError("cleanup requires matching marker and git registration")
        main = Path(await _git(workspace.repo, "rev-parse", "--show-toplevel")).resolve()
        if path == main:
            raise WorkspaceSafetyError("refusing to remove main worktree")
        if dry_run:
            return
        await _git(workspace.repo, "worktree", "remove", "--force", str(path))
        await _git(workspace.repo, "worktree", "prune")
