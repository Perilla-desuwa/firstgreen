"""Read-only, bounded repository scanner with Python-first heuristics."""

import ast
import json
import re
import shlex
import subprocess
import tomllib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Protocol

from firstgreen.config import RepositoryScanConfig
from firstgreen.planning.models import RepositoryFile, RepositoryMap, RepositoryModule

EXCLUDED_PARTS = {
    ".git",
    ".firstgreen",
    ".venv",
    ".deps",
    ".tmp",
    ".pytest-tmp",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
}
TEXT_SUFFIXES = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".java",
    ".go",
    ".rs",
    ".md",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".sql",
}


class RepositoryScanner(Protocol):
    def scan(self, repo: Path, config: RepositoryScanConfig) -> RepositoryMap: ...


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _git_visible_files(repo: Path) -> list[Path] | None:
    """Return tracked and non-ignored untracked files, or None outside Git."""

    result = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        return None
    return [repo / value for value in result.stdout.split("\0") if value]


def _kind(path: Path) -> str:
    parts = {part.lower() for part in path.parts}
    if "test" in path.name.lower() or parts & {"tests", "test"}:
        return "test"
    if parts & {"migrations", "migration", "alembic", "versions"}:
        return "migration"
    if path.suffix.lower() in {".md", ".rst"} or parts & {"docs", "doc"}:
        return "docs"
    if path.name in {"pyproject.toml", "package.json", "Makefile", "tox.ini"}:
        return "config"
    if path.suffix.lower() in {".py", ".js", ".ts", ".tsx", ".java", ".go", ".rs"}:
        return "source"
    return "other"


def _python_metadata(path: Path) -> tuple[list[str], list[str], list[str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return [], [], []
    imports: set[str] = set()
    routes: set[str] = set()
    symbols = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr.lower()
                    in {
                        "get",
                        "post",
                        "put",
                        "patch",
                        "delete",
                        "route",
                    }
                    and decorator.args
                    and isinstance(decorator.args[0], ast.Constant)
                ):
                    routes.add(str(decorator.args[0].value))
    return sorted(symbols)[:50], sorted(imports)[:100], sorted(routes)[:50]


def _javascript_symbols(path: Path) -> list[str]:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")[:200_000]
    except OSError:
        return []
    patterns = (
        r"(?m)^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)",
        r"(?m)^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)",
        r"(?m)^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=",
    )
    return sorted({match for pattern in patterns for match in re.findall(pattern, source)})[:50]


def _javascript_package_manager(repo: Path, package: dict[str, object]) -> str:
    declared = package.get("packageManager")
    if isinstance(declared, str):
        name = declared.split("@", 1)[0].lower()
        if name in {"pnpm", "yarn", "bun", "npm"}:
            return name
    for marker, name in (
        ("pnpm-lock.yaml", "pnpm"),
        ("pnpm-workspace.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("bun.lock", "bun"),
        ("bun.lockb", "bun"),
        ("package-lock.json", "npm"),
        ("npm-shrinkwrap.json", "npm"),
    ):
        if (repo / marker).is_file():
            return name
    return "npm"


def _javascript_command(manager: str, script: str, directory: str | None = None) -> list[str]:
    if directory is None:
        return [manager, "run", script]
    if manager == "pnpm":
        return ["pnpm", "--dir", directory, "run", script]
    if manager == "yarn":
        return ["yarn", "--cwd", directory, "run", script]
    if manager == "bun":
        return ["bun", "--cwd", directory, "run", script]
    return ["npm", "--prefix", directory, "run", script]


def _direct_node_command(script: object) -> list[str] | None:
    if not isinstance(script, str) or not script.strip():
        return None
    if re.search(r"[\r\n|&;<>`$*?\[\]{}()]", script):
        return None
    try:
        argv = shlex.split(script, posix=True)
    except ValueError:
        return None
    if argv and argv[0].lower() in {"node", "node.exe"}:
        return argv
    return None


def _commands(repo: Path, visible_paths: list[Path]) -> dict[str, list[list[str]]]:
    commands: dict[str, list[list[str]]] = defaultdict(list)
    dependency_sections: list[object] = []
    pyproject = repo / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            data = {}
        tool = data.get("tool", {}) if isinstance(data, dict) else {}
        if isinstance(data, dict):
            dependency_sections.extend(
                [
                    data.get("project", {}),
                    data.get("dependency-groups", {}),
                ]
            )
        if isinstance(tool, dict):
            dependency_sections.extend([tool.get("uv", {}), tool.get("poetry", {})])
            if "pytest" in tool:
                commands["test"].append(["python", "-m", "pytest"])
            if "ruff" in tool:
                commands["lint"].append(["python", "-m", "ruff", "check", "."])
            if "mypy" in tool:
                commands["typecheck"].append(["python", "-m", "mypy", "."])
    dependency_text = json.dumps(dependency_sections, sort_keys=True).lower()
    if "pytest" in dependency_text and not commands["test"]:
        commands["test"].append(["python", "-m", "pytest"])
    if "ruff" in dependency_text and not commands["lint"]:
        commands["lint"].append(["python", "-m", "ruff", "check", "."])
    if "mypy" in dependency_text and not commands["typecheck"]:
        commands["typecheck"].append(["python", "-m", "mypy", "."])
    if any((repo / name).is_file() for name in ("pytest.ini", "tox.ini")) and not commands["test"]:
        commands["test"].append(["python", "-m", "pytest"])
    unittest_tests = any(
        path.name.startswith("test_") and path.suffix == ".py" and "tests" in path.parts
        for path in visible_paths
    )
    if unittest_tests and not commands["test"]:
        commands["test"].append(
            ["python", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]
        )
    if (
        any((repo / name).is_file() for name in ("ruff.toml", ".ruff.toml"))
        and not commands["lint"]
    ):
        commands["lint"].append(["python", "-m", "ruff", "check", "."])
    if (
        any((repo / name).is_file() for name in ("mypy.ini", ".mypy.ini"))
        and not commands["typecheck"]
    ):
        commands["typecheck"].append(["python", "-m", "mypy", "."])
    package = repo / "package.json"
    package_manager = "npm"
    if package.is_file():
        try:
            parsed = json.loads(package.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            parsed = {}
        package_manager = _javascript_package_manager(
            repo, parsed if isinstance(parsed, dict) else {}
        )
        if package_manager == "pnpm" and (repo / "pnpm-lock.yaml").is_file():
            commands["setup"].append(["pnpm", "install", "--offline", "--frozen-lockfile"])
        scripts = parsed.get("scripts", {}) if isinstance(parsed, dict) else {}
        if isinstance(scripts, dict):
            for name in ("test", "lint", "typecheck"):
                if name in scripts:
                    commands[name].append(
                        _direct_node_command(scripts[name])
                        or _javascript_command(package_manager, name)
                    )
    for nested in sorted(
        path for path in visible_paths if path.name == "package.json" and path != package
    ):
        try:
            parsed = json.loads(nested.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        scripts = parsed.get("scripts", {}) if isinstance(parsed, dict) else {}
        if not isinstance(scripts, dict):
            continue
        directory = nested.parent.relative_to(repo).as_posix()
        for name in ("test", "lint", "typecheck"):
            if name in scripts:
                commands[f"{name}@{directory}"].append(
                    _javascript_command(package_manager, name, directory)
                )
    if (repo / "Makefile").is_file():
        commands.setdefault("build", []).append(["make"])
    return dict(commands)


def _codeowners(repo: Path) -> dict[str, list[str]]:
    candidates = [
        repo / "CODEOWNERS",
        repo / ".github" / "CODEOWNERS",
        repo / "docs" / "CODEOWNERS",
    ]
    result: dict[str, list[str]] = {}
    for candidate in candidates:
        if not candidate.is_file():
            continue
        for line in candidate.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            fields = stripped.split()
            if len(fields) >= 2:
                result[fields[0]] = fields[1:]
        break
    return result


def _cochanges(repo: Path, max_commits: int) -> list[list[str]]:
    if max_commits <= 0:
        return []
    log = _git(repo, "log", f"-n{max_commits}", "--name-only", "--pretty=format:--COMMIT--")
    pairs: Counter[tuple[str, str]] = Counter()
    current: list[str] = []
    for line in [*log.splitlines(), "--COMMIT--"]:
        if line == "--COMMIT--":
            unique = sorted(set(current))[:30]
            for index, left in enumerate(unique):
                for right in unique[index + 1 :]:
                    pairs[(left, right)] += 1
            current = []
        elif line.strip():
            current.append(line.strip().replace("\\", "/"))
    return [list(pair) for pair, count in pairs.most_common(50) if count >= 2]


class HeuristicRepositoryScanner:
    version = "repo-map-v2"

    def scan(self, repo: Path, config: RepositoryScanConfig) -> RepositoryMap:
        root = Path(_git(repo, "rev-parse", "--show-toplevel") or repo).resolve()
        commit = _git(root, "rev-parse", "HEAD")
        visible = _git_visible_files(root)
        candidates = visible if visible is not None else list(root.rglob("*"))
        paths = sorted(
            path
            for path in candidates
            if path.is_file()
            and not path.is_symlink()
            and not any(part in EXCLUDED_PARTS for part in path.relative_to(root).parts)
            and (path.suffix.lower() in TEXT_SUFFIXES or path.name in {"Makefile", "CODEOWNERS"})
        )
        truncated = len(paths) > config.max_files
        paths = paths[: config.max_files]
        test_by_stem: dict[str, list[str]] = defaultdict(list)
        for path in paths:
            relative = path.relative_to(root).as_posix()
            if _kind(path.relative_to(root)) == "test":
                stem = path.stem.removeprefix("test_").removesuffix("_test")
                test_by_stem[stem].append(relative)
        files: list[RepositoryFile] = []
        dependencies: dict[str, set[str]] = defaultdict(set)
        module_tests: dict[str, set[str]] = defaultdict(set)
        module_paths: dict[str, set[str]] = defaultdict(set)
        resources: set[str] = set()
        for path in paths:
            relative_path = path.relative_to(root)
            relative = relative_path.as_posix()
            if path.suffix == ".py":
                symbols, imports, routes = _python_metadata(path)
            else:
                symbols = (
                    _javascript_symbols(path)
                    if path.suffix.lower() in {".js", ".ts", ".tsx"}
                    else []
                )
                imports, routes = [], []
            kind = _kind(relative_path)
            stem = path.stem.removeprefix("test_").removesuffix("_test")
            tested_by = sorted(test_by_stem.get(stem, [])) if kind == "source" else []
            files.append(
                RepositoryFile(
                    path=relative,
                    kind=kind,  # type: ignore[arg-type]
                    symbols=symbols,
                    imports=imports,
                    tested_by=tested_by,
                    api_routes=routes,
                )
            )
            parts = relative_path.parts
            module = parts[1] if len(parts) > 1 and parts[0] in {"src", "lib", "app"} else parts[0]
            module_paths[module].add(str(Path(*parts[:2]).as_posix()) if len(parts) > 1 else module)
            if kind == "test":
                module_tests[module].add(relative)
            for imported in imports:
                imported_parts = imported.split(".")
                if imported_parts:
                    dependencies[module].add(imported_parts[0])
            lowered = relative.lower()
            for marker in ("migration", "fixture", "generated", "database", "docker", "port"):
                if marker in lowered:
                    resources.add(marker)
        modules = [
            RepositoryModule(
                name=name,
                paths=sorted(module_paths[name]),
                depends_on=sorted(dependencies[name] - {name})[:30],
                tests=sorted(module_tests[name])[:50],
            )
            for name in sorted(module_paths)
        ]
        result = RepositoryMap(
            version=self.version,
            repo=root,
            commit_sha=commit,
            modules=modules,
            files=files,
            commands=_commands(root, paths),
            codeowners=_codeowners(root),
            cochange_groups=(
                _cochanges(root, config.max_history_commits) if config.include_git_history else []
            ),
            shared_resources=sorted(resources),
            truncated=truncated,
        )
        approximate_tokens = len(result.model_dump_json()) // 4
        if approximate_tokens > config.max_repo_map_tokens:
            ratio = config.max_repo_map_tokens / approximate_tokens
            keep = max(1, int(len(result.files) * ratio))
            result = result.model_copy(update={"files": result.files[:keep], "truncated": True})
        return result
