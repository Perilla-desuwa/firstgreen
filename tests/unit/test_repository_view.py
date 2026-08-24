import json
import subprocess
from pathlib import Path

import pytest

from firstgreen.errors import WorkspaceSafetyError
from firstgreen.workspace.repository_view import SNAPSHOT_MARKER, prepare_repository_view


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def repository(tmp_path: Path) -> Path:
    repo = tmp_path / "source"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    (repo / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (repo / "changed.txt").write_text("base\n", encoding="utf-8")
    (repo / "deleted.txt").write_text("delete me\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    return repo


def make_dirty(repo: Path) -> None:
    (repo / "changed.txt").write_text("working tree\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    (repo / "ignored.txt").write_text("ignored\n", encoding="utf-8")
    (repo / "deleted.txt").unlink()


def test_dirty_repository_is_blocked_by_default(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    make_dirty(repo)

    with pytest.raises(WorkspaceSafetyError, match="uncommitted changes"):
        prepare_repository_view(repo, tmp_path / "state")


def test_head_mode_uses_clean_managed_clone_at_original_sha(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    source_sha = git(repo, "rev-parse", "HEAD")
    make_dirty(repo)

    view = prepare_repository_view(repo, tmp_path / "state", dirty_mode="head")

    assert view.mode == "head"
    assert view.base_sha == source_sha
    assert view.execution_repo != repo
    assert (view.execution_repo / "changed.txt").read_text(encoding="utf-8") == "base\n"
    assert not (view.execution_repo / "new.txt").exists()
    assert (view.execution_repo / "deleted.txt").is_file()
    assert git(view.execution_repo, "status", "--porcelain") == ""


def test_snapshot_captures_visible_tree_without_mutating_source(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    make_dirty(repo)
    source_head = git(repo, "rev-parse", "HEAD")
    source_index = git(repo, "write-tree")
    source_status = git(repo, "status", "--porcelain", "--untracked-files=all")

    view = prepare_repository_view(repo, tmp_path / "state", dirty_mode="snapshot")

    assert view.mode == "snapshot"
    assert view.base_sha != source_head
    assert (view.execution_repo / "changed.txt").read_text(encoding="utf-8") == "working tree\n"
    assert (view.execution_repo / "new.txt").read_text(encoding="utf-8") == "new\n"
    assert not (view.execution_repo / "deleted.txt").exists()
    assert not (view.execution_repo / "ignored.txt").exists()
    assert git(view.execution_repo, "status", "--porcelain") == ""
    assert git(repo, "rev-parse", "HEAD") == source_head
    assert git(repo, "write-tree") == source_index
    assert git(repo, "status", "--porcelain", "--untracked-files=all") == source_status
    assert view.managed_root is not None
    marker = json.loads((view.managed_root / SNAPSHOT_MARKER).read_text(encoding="utf-8"))
    assert marker["source_repo"] == str(repo.resolve())
    assert marker["execution_repo"] == str(view.execution_repo)
    assert marker["base_sha"] == view.base_sha


def test_snapshot_root_cannot_be_inside_target_repository(tmp_path: Path) -> None:
    repo = repository(tmp_path)

    with pytest.raises(WorkspaceSafetyError, match="outside the target repository"):
        prepare_repository_view(repo, repo / ".state", dirty_mode="snapshot")
