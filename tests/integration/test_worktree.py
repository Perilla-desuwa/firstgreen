import asyncio
import subprocess
from pathlib import Path

import pytest

from firstgreen.errors import WorkspaceSafetyError
from firstgreen.workspace.git_worktree import GitWorktreeManager, WorkspaceSpec


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "firstgreen@example.invalid")
    git(repo, "config", "user.name", "FirstGreen Test")
    (repo / "file.txt").write_text("main\n", encoding="utf-8")
    git(repo, "add", "file.txt")
    git(repo, "commit", "-m", "base")
    return repo


def test_create_and_idempotent_cleanup_preserve_main(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    root = tmp_path / "workspaces"
    manager = GitWorktreeManager(root)
    spec = WorkspaceSpec("run", "task", "attempt", repo, "main")
    workspace = asyncio.run(manager.create_attempt_workspace(spec))
    assert workspace.path.is_relative_to(root)
    assert (repo / "file.txt").read_text(encoding="utf-8") == "main\n"
    asyncio.run(manager.cleanup(workspace))
    asyncio.run(manager.cleanup(workspace))
    assert repo.exists()


def test_winner_retained_and_tampered_marker_refused(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    manager = GitWorktreeManager(tmp_path / "workspaces")
    workspace = asyncio.run(
        manager.create_attempt_workspace(WorkspaceSpec("r", "t", "a", repo, "main"))
    )
    asyncio.run(manager.cleanup(workspace, is_winner=True))
    assert workspace.path.exists()
    (workspace.path / ".firstgreen-attempt.json").write_text("{}", encoding="utf-8")
    with pytest.raises(WorkspaceSafetyError, match="marker"):
        asyncio.run(manager.cleanup(workspace))


def test_boundary_rejects_root_and_parent(tmp_path: Path) -> None:
    manager = GitWorktreeManager(tmp_path / "root")
    with pytest.raises(WorkspaceSafetyError):
        manager._bounded(tmp_path)


def test_backup_uses_primary_pinned_sha_after_branch_moves(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    manager = GitWorktreeManager(tmp_path / "workspaces")
    primary = asyncio.run(
        manager.create_attempt_workspace(WorkspaceSpec("r", "t", "a1", repo, "main"))
    )
    (repo / "later.txt").write_text("later", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "move main")
    backup = asyncio.run(manager.create_backup_workspace(primary, attempt_id="a2"))
    assert backup.base_sha == primary.base_sha
    assert not (backup.path / "later.txt").exists()


def test_workspace_uses_short_hashed_path_and_ref_for_windows_safety(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    root = tmp_path / "worktrees"
    manager = GitWorktreeManager(root)
    workspace = asyncio.run(
        manager.create_attempt_workspace(
            WorkspaceSpec(
                "run_" + "r" * 80,
                "task-" + "t" * 80,
                "attempt_" + "a" * 80,
                repo,
                "main",
            )
        )
    )
    assert workspace.path.parent == root.resolve()
    assert len(workspace.path.name) == 22
    assert workspace.branch.startswith("fg/")
    assert len(workspace.branch) == 27
