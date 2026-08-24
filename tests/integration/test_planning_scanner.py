import subprocess
from pathlib import Path

from firstgreen.config import RepositoryScanConfig
from firstgreen.planning.scanner import HeuristicRepositoryScanner


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_python_repo_map_is_bounded_and_read_only(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src" / "auth").mkdir(parents=True)
    (repo / "tests" / "auth").mkdir(parents=True)
    (repo / ".github").mkdir()
    (repo / "src" / "auth" / "routes.py").write_text(
        "from auth.service import reset\n@router.post('/reset')\ndef route(): return reset()\n",
        encoding="utf-8",
    )
    (repo / "tests" / "auth" / "test_routes.py").write_text("def test_route(): pass\n")
    (repo / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\n[tool.ruff]\n[tool.mypy]\n", encoding="utf-8"
    )
    (repo / ".gitignore").write_text(".tmp/\n", encoding="utf-8")
    (repo / ".github" / "CODEOWNERS").write_text("/src/auth @security\n")
    (repo / "说明.md").write_text("只读扫描应支持 UTF-8 路径。\n", encoding="utf-8")
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    (repo / ".tmp" / "worktrees").mkdir(parents=True)
    (repo / ".tmp" / "worktrees" / "leaked.py").write_text("SECRET = True\n")
    before = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    repo_map = HeuristicRepositoryScanner().scan(
        repo,
        RepositoryScanConfig(
            language_profiles=["python", "generic"],
            include_git_history=True,
            max_history_commits=500,
            max_repo_map_tokens=20_000,
            max_files=2000,
        ),
    )
    after = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    routes = next(item for item in repo_map.files if item.path.endswith("routes.py"))
    assert repo_map.version == "repo-map-v2"
    assert routes.symbols == ["route"]
    assert routes.api_routes == ["/reset"]
    assert routes.tested_by == ["tests/auth/test_routes.py"]
    assert repo_map.commands["test"] == [["python", "-m", "pytest"]]
    assert repo_map.codeowners == {"/src/auth": ["@security"]}
    assert all(not item.path.startswith(".tmp/") for item in repo_map.files)
    assert any(item.path == "说明.md" for item in repo_map.files)
    assert before == after == ""


def test_python_verifiers_are_discovered_from_dependencies_and_config_files(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        "[project]\nname='fixture'\ndependencies=['pytest>=8', 'ruff>=0.8']\n",
        encoding="utf-8",
    )
    (repo / "mypy.ini").write_text("[mypy]\nstrict = true\n", encoding="utf-8")
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")

    repo_map = HeuristicRepositoryScanner().scan(
        repo,
        RepositoryScanConfig(
            language_profiles=["python", "generic"],
            include_git_history=True,
            max_history_commits=500,
            max_repo_map_tokens=20_000,
            max_files=2000,
        ),
    )

    assert repo_map.commands == {
        "test": [["python", "-m", "pytest"]],
        "lint": [["python", "-m", "ruff", "check", "."]],
        "typecheck": [["python", "-m", "mypy", "."]],
    }


def test_unittest_suite_is_discovered_without_python_project_metadata(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "tests" / "test_module.py").write_text(
        "import unittest\n\nclass TestValue(unittest.TestCase):\n"
        "    def test_value(self): self.assertEqual(1, 1)\n",
        encoding="utf-8",
    )
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")

    repo_map = HeuristicRepositoryScanner().scan(
        repo,
        RepositoryScanConfig(
            language_profiles=["python", "generic"],
            include_git_history=True,
            max_history_commits=500,
            max_repo_map_tokens=20_000,
            max_files=2000,
        ),
    )

    assert repo_map.commands["test"] == [
        ["python", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]
    ]


def test_pnpm_workspace_uses_pnpm_and_discovers_package_scoped_commands(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    package = repo / "packages" / "adapter"
    package.mkdir(parents=True)
    (repo / "package.json").write_text(
        '{"packageManager":"pnpm@10.0.0","scripts":{"test":"pnpm -r test"}}',
        encoding="utf-8",
    )
    (repo / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    (package / "package.json").write_text(
        '{"scripts":{"test":"vitest run","typecheck":"tsc --noEmit"}}',
        encoding="utf-8",
    )
    (package / "index.ts").write_text("export const value = 1;\n", encoding="utf-8")
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")

    repo_map = HeuristicRepositoryScanner().scan(
        repo,
        RepositoryScanConfig(
            language_profiles=["python", "generic"],
            include_git_history=True,
            max_history_commits=500,
            max_repo_map_tokens=20_000,
            max_files=2000,
        ),
    )

    assert repo_map.commands["setup"] == [["pnpm", "install", "--offline", "--frozen-lockfile"]]
    assert repo_map.commands["test"] == [["pnpm", "run", "test"]]
    assert repo_map.commands["test@packages/adapter"] == [
        ["pnpm", "--dir", "packages/adapter", "run", "test"]
    ]
    assert repo_map.commands["typecheck@packages/adapter"] == [
        ["pnpm", "--dir", "packages/adapter", "run", "typecheck"]
    ]
    adapter = next(item for item in repo_map.files if item.path.endswith("index.ts"))
    assert adapter.symbols == ["value"]


def test_simple_root_node_script_is_recorded_without_package_manager_wrapper(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text(
        '{"scripts":{"test":"node --test","lint":"node scripts/lint.mjs"}}',
        encoding="utf-8",
    )
    (repo / "index.js").write_text("export const value = 1;\n", encoding="utf-8")
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")

    repo_map = HeuristicRepositoryScanner().scan(
        repo,
        RepositoryScanConfig(
            language_profiles=["python", "generic"],
            include_git_history=False,
            max_history_commits=0,
            max_repo_map_tokens=20_000,
            max_files=2000,
        ),
    )

    assert repo_map.commands["test"] == [["node", "--test"]]
    assert repo_map.commands["lint"] == [["node", "scripts/lint.mjs"]]
