import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import firstgreen.cli as cli_module
from firstgreen.adapters.base import DoctorResult
from firstgreen.adapters.codex_exec import CodexExecAdapter
from firstgreen.cli import app, normalize_cli_args
from firstgreen.db.repository import SQLiteRepository
from firstgreen.planning.planner import FakePlanner
from firstgreen.planning.workflow import load_plan
from firstgreen.user_config import UserConfig, load_user_config, save_user_config


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "src" / "auth").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "docs").mkdir()
    (repo / "src" / "auth" / "service.py").write_text("def reset(): pass\n")
    (repo / "src" / "auth" / "routes.py").write_text("def route(): pass\n")
    (repo / "tests" / "test_auth.py").write_text("def test_auth(): pass\n")
    (repo / "docs" / "auth.md").write_text("auth\n")
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    return repo


def test_scan_plan_validate_and_auto_approve_dry_run(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    issue = tmp_path / "issue.md"
    issue.write_text(
        "Add password reset service, API endpoint, tests, and documentation.", encoding="utf-8"
    )
    state = tmp_path / "state"
    plan_file = tmp_path / "plan.yaml"
    runner = CliRunner()
    scan_output = tmp_path / "nested" / "repo-map.json"
    scan = runner.invoke(
        app,
        [
            "scan",
            "--repo",
            str(repo),
            "--output",
            str(scan_output),
            "--no-history-analysis",
        ],
    )
    assert scan.exit_code == 0, scan.output
    assert json.loads(scan_output.read_text(encoding="utf-8"))["commit_sha"]
    planned = runner.invoke(
        app,
        [
            "plan",
            str(issue),
            "--repo",
            str(repo),
            "--output",
            str(plan_file),
            "--state-dir",
            str(state),
        ],
    )
    assert planned.exit_code == 0, planned.output
    assert "Planning result:" in planned.output
    validated = runner.invoke(app, ["validate-plan", str(plan_file)])
    assert validated.exit_code == 0, validated.output
    dry_run = runner.invoke(
        app,
        [
            "run",
            str(issue),
            "--plan",
            "auto",
            "--approve-plan",
            "--repo",
            str(repo),
            "--adapter",
            "fake",
            "--dry-run",
            "--state-dir",
            str(state),
        ],
    )
    assert dry_run.exit_code == 0, dry_run.output
    assert '"compiled_manifest"' in dry_run.output


def test_high_risk_issue_refuses_policy_auto_approval(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    issue = tmp_path / "issue.md"
    issue.write_text("Add database migration and API endpoint.", encoding="utf-8")
    result = CliRunner().invoke(
        app,
        [
            "run",
            str(issue),
            "--plan",
            "auto",
            "--approve-plan",
            "--repo",
            str(repo),
            "--adapter",
            "fake",
            "--dry-run",
            "--state-dir",
            str(tmp_path / "state"),
        ],
    )
    assert result.exit_code != 0
    assert "eligible" in result.output


def test_validate_plan_preserves_deterministic_repair_audit(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    plan_file = tmp_path / "plan.yaml"
    issue_file = tmp_path / "issue.md"
    issue_file.write_text(
        "Implement email delivery in unknown files and expose an API", encoding="utf-8"
    )
    runner = CliRunner()
    planned = runner.invoke(
        app,
        [
            "plan",
            str(issue_file),
            "--repo",
            str(repo),
            "--output",
            str(plan_file),
            "--state-dir",
            str(tmp_path / "state"),
        ],
    )
    assert planned.exit_code == 0, planned.output
    assert "fell back to one task" in planned.output

    validated = runner.invoke(app, ["validate-plan", str(plan_file)])
    assert validated.exit_code == 0, validated.output
    assert "fell back to one task" in validated.output


def test_inline_and_stdin_requests_need_no_issue_file(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    state = tmp_path / "state"
    runner = CliRunner()

    inline = runner.invoke(
        app,
        [
            "plan",
            "Fix the authentication service typo",
            "--repo",
            str(repo),
            "--state-dir",
            str(state),
        ],
    )
    assert inline.exit_code == 0, inline.output
    assert "Planning result:" in inline.output

    piped = runner.invoke(
        app,
        ["plan", "-", "--repo", str(repo), "--state-dir", str(state)],
        input="Fix the health response\n",
    )
    assert piped.exit_code == 0, piped.output
    assert "Planning result:" in piped.output


def test_inline_request_can_compile_without_execution(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "run",
            "Add password reset service, API endpoint, tests, and documentation.",
            "--repo",
            str(repo),
            "--adapter",
            "fake",
            "--yes",
            "--dry-run",
            "--state-dir",
            str(tmp_path / "state"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert '"compiled_manifest"' in result.output


def test_installed_entrypoint_routes_plain_text_to_request_command() -> None:
    assert normalize_cli_args([]) == ["request"]
    assert normalize_cli_args(["Fix upload collisions"]) == [
        "request",
        "Fix upload collisions",
    ]
    assert normalize_cli_args(["plan", "request.md"]) == ["plan", "request.md"]
    assert normalize_cli_args(["--help"]) == ["--help"]


def test_configure_persists_defaults_and_run_uses_them(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    config_path = tmp_path / "user-config.yaml"
    state = tmp_path / "configured-state"
    runner = CliRunner(env={"FIRSTGREEN_CONFIG": str(config_path)})

    configured = runner.invoke(
        app,
        [
            "configure",
            "--adapter",
            "fake",
            "--planner-provider",
            "fake",
            "--reasoning",
            "low",
            "--dirty-mode",
            "snapshot",
            "--state-dir",
            str(state),
        ],
    )
    assert configured.exit_code == 0, configured.output
    assert load_user_config(config_path).adapter == "fake"
    assert load_user_config(config_path).worker_reasoning == "low"
    assert load_user_config(config_path).dirty_mode == "snapshot"

    result = runner.invoke(
        app,
        [
            "run",
            "Fix the authentication service typo",
            "--repo",
            str(repo),
            "--yes",
            "--dirty-mode",
            "block",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip().splitlines()[-1])
    compiled = Path(payload["compiled_manifest"])
    assert compiled.is_relative_to(state)
    assert "adapter: fake" in compiled.read_text(encoding="utf-8")
    assert str(repo.resolve()) in load_user_config(config_path).recent_repositories


def test_interactive_request_preflights_configured_codex_before_reading_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = repository(tmp_path)
    config_path = tmp_path / "user-config.yaml"
    save_user_config(UserConfig(codex_binary="C:/mock/codex.exe"), config_path)
    calls: list[str] = []

    async def successful_doctor(self: CodexExecAdapter) -> DoctorResult:
        calls.append(self.binary)
        return DoctorResult(True, "ok")

    monkeypatch.setattr(CodexExecAdapter, "doctor", successful_doctor)
    cli_module._CODEX_PREFLIGHT_CACHE.clear()
    result = CliRunner(env={"FIRSTGREEN_CONFIG": str(config_path)}).invoke(
        app,
        [
            "request",
            "--repo",
            str(repo),
            "--yes",
            "--dry-run",
        ],
        input="Fix the authentication service typo\n",
    )

    assert result.exit_code == 0, result.output
    assert calls == ["C:/mock/codex.exe"]
    assert "Codex preflight: OK - C:/mock/codex.exe" in result.output


def test_plan_command_passes_selected_binary_and_model_to_codex_planner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = repository(tmp_path)
    selected: list[tuple[str, str]] = []

    async def successful_doctor(self: CodexExecAdapter) -> DoctorResult:
        return DoctorResult(True, "ok")

    def planner_factory(_work_dir: Path, *, binary: str, model: str) -> FakePlanner:
        selected.append((binary, model))
        return FakePlanner()

    monkeypatch.setattr(CodexExecAdapter, "doctor", successful_doctor)
    monkeypatch.setattr("firstgreen.cli.CodexPlannerAdapter", planner_factory)
    cli_module._CODEX_PREFLIGHT_CACHE.clear()
    result = CliRunner().invoke(
        app,
        [
            "plan",
            "增加数据库字段、服务逻辑、API 接口和回归测试",
            "--repo",
            str(repo),
            "--planner-provider",
            "codex",
            "--planner-model",
            "planner-small",
            "--codex-binary",
            "C:/mock/codex.exe",
            "--state-dir",
            str(tmp_path / "state"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert selected == [("C:/mock/codex.exe", "planner-small")]
    assert "Codex preflight: OK - C:/mock/codex.exe" in result.output


def test_dirty_repo_blocks_planning_until_mode_is_explicit(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    (repo / "src" / "auth" / "service.py").write_text("working tree\n", encoding="utf-8")
    runner = CliRunner()

    blocked = runner.invoke(
        app,
        ["plan", "Fix auth", "--repo", str(repo), "--state-dir", str(tmp_path / "state")],
    )

    assert blocked.exit_code != 0
    assert "uncommitted changes" in blocked.output


def test_snapshot_plan_records_source_and_uses_managed_repository(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    original_head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    changed = repo / "src" / "auth" / "service.py"
    changed.write_text("working tree\n", encoding="utf-8")
    (repo / "new.py").write_text("value = 1\n", encoding="utf-8")
    plan_file = tmp_path / "plan.yaml"

    result = CliRunner().invoke(
        app,
        [
            "plan",
            "Fix auth service and tests",
            "--repo",
            str(repo),
            "--dirty-mode",
            "snapshot",
            "--output",
            str(plan_file),
            "--state-dir",
            str(tmp_path / "state"),
        ],
    )

    assert result.exit_code == 0, result.output
    plan = load_plan(plan_file)
    assert plan.repository_mode == "snapshot"
    assert plan.source_repo == repo.resolve()
    assert plan.repo != repo.resolve()
    assert (plan.repo / "src" / "auth" / "service.py").read_text(encoding="utf-8") == (
        "working tree\n"
    )
    assert (plan.repo / "new.py").is_file()
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        == original_head
    )


def test_dirty_snapshot_runs_scheduler_from_same_repository_view(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    changed = repo / "src" / "auth" / "service.py"
    changed.write_text("def reset():\n    return 'working tree'\n", encoding="utf-8")
    original_status = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    state = tmp_path / "state"
    manifest = tmp_path / "fleet.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "project": {"repo": str(repo), "base_ref": "main"},
                "scheduler": {"concurrency": {}},
                "agent_defaults": {"adapter": "fake"},
                "verification_defaults": {},
                "workspace": {},
                "tasks": [
                    {
                        "id": "snapshot-smoke",
                        "prompt": "fake",
                        "verify": {
                            "commands": [
                                {"argv": [sys.executable, "-c", "print('snapshot green')"]}
                            ]
                        },
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "run",
            str(manifest),
            "--dirty-mode",
            "snapshot",
            "--no-tui",
            "--state-dir",
            str(state),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["verified"] == 1
    with SQLiteRepository(state / "state.db").connect() as connection:
        run = connection.execute(
            "SELECT repo_path,base_sha,policy_snapshot FROM runs WHERE id=?", (payload["run_id"],)
        ).fetchone()
        attempt = connection.execute(
            "SELECT workspace_path,status FROM attempts WHERE status='winner'"
        ).fetchone()
    assert run is not None
    assert Path(run["repo_path"]) != repo.resolve()
    assert (Path(run["repo_path"]) / "src" / "auth" / "service.py").read_text(
        encoding="utf-8"
    ) == "def reset():\n    return 'working tree'\n"
    policy_snapshot = json.loads(run["policy_snapshot"])
    assert policy_snapshot["repository_view"]["source_repo"] == str(repo.resolve())
    assert policy_snapshot["repository_view"]["base_sha"] == run["base_sha"]
    assert attempt is not None
    assert Path(attempt["workspace_path"]).is_dir()
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == original_status
    )


def test_natural_run_auto_binds_repository_virtualenv(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    if os.name == "nt":
        python = repo / ".venv" / "Scripts" / "python.exe"
    else:
        python = repo / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"placeholder")
    python.chmod(0o755)
    (repo / ".git" / "info" / "exclude").write_text(".venv/\n", encoding="utf-8")
    state = tmp_path / "state"

    result = CliRunner().invoke(
        app,
        [
            "run",
            "Fix the authentication service typo",
            "--repo",
            str(repo),
            "--adapter",
            "fake",
            "--yes",
            "--dry-run",
            "--state-dir",
            str(state),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip().splitlines()[-1])
    compiled = yaml.safe_load(Path(payload["compiled_manifest"]).read_text(encoding="utf-8"))
    verification = compiled["verification_defaults"]
    assert verification["executable_overrides"]["python"] == str(python.absolute())
    assert verification["environment_snapshot"]["mode"] == "repository-venv"
    assert "Verifier environment: repository-venv" in result.output


def test_missing_verifier_blocks_before_run_is_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = repository(tmp_path)
    manifest = tmp_path / "missing-verifier.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "project": {"repo": str(repo), "base_ref": "main"},
                "scheduler": {"concurrency": {}},
                "agent_defaults": {"adapter": "fake"},
                "verification_defaults": {},
                "workspace": {},
                "tasks": [
                    {
                        "id": "blocked",
                        "prompt": "must not start",
                        "verify": {"commands": [{"argv": ["no-such-verifier", "--check"]}]},
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "firstgreen.verifier.environment.shutil.which", lambda *_args, **_kwargs: None
    )
    state = tmp_path / "state"

    result = CliRunner().invoke(
        app,
        ["run", str(manifest), "--state-dir", str(state)],
    )

    assert result.exit_code == 2
    assert "no-such-verifier" in result.output
    assert not (state / "state.db").exists()
