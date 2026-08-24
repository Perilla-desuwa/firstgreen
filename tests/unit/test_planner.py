import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from firstgreen.planning.decomposition import decide_decomposition
from firstgreen.planning.models import RepositoryFile, RepositoryMap, RepositoryModule
from firstgreen.planning.planner import (
    CodexPlannerAdapter,
    FakePlanner,
    PlannerCache,
    StructuredPlannerAdapter,
    planner_cache_key,
)


def repo_map() -> RepositoryMap:
    return RepositoryMap(
        repo=Path("."),
        commit_sha="sha",
        modules=[RepositoryModule(name="auth", paths=["src/auth"], tests=["tests/auth"])],
        files=[
            RepositoryFile(path="src/auth/models.py", kind="source"),
            RepositoryFile(path="src/auth/service.py", kind="source"),
            RepositoryFile(path="src/auth/routes.py", kind="source"),
            RepositoryFile(path="templates/mail/reset.html", kind="source"),
            RepositoryFile(path="tests/auth/test_reset.py", kind="test"),
        ],
        commands={"test": [["pytest"]]},
    )


def test_small_local_bug_bypasses_semantic_decomposition() -> None:
    decision = decide_decomposition("Fix the OAuth callback race condition", repo_map())
    assert decision.decision == "single_task"
    assert decision.recommended_parallelism == 1


def test_feature_uses_bounded_fake_planner() -> None:
    issue = "Add password reset schema, one-hour expiry service, email delivery, and API endpoint"
    decision = decide_decomposition(issue, repo_map())
    proposal = FakePlanner().propose(issue, repo_map(), decision, max_tasks=5)
    assert decision.decision == "decompose"
    assert 2 <= len(proposal.tasks) <= 5
    assert any(task.produces == ["data-schema"] for task in proposal.tasks)


def test_chinese_feature_is_decomposed_into_semantic_work_units() -> None:
    issue = "增加密码重置数据库字段、过期服务、通知邮件、API 接口和回归测试"
    decision = decide_decomposition(issue, repo_map())
    proposal = FakePlanner().propose(issue, repo_map(), decision, max_tasks=5)

    assert decision.decision == "decompose"
    assert decision.recommended_parallelism >= 2
    assert len(proposal.tasks) >= 3
    assert any(task.produces == ["data-schema"] for task in proposal.tasks)
    assert any(task.produces == ["email-delivery"] for task in proposal.tasks)
    assert any(task.produces == ["api-behavior"] for task in proposal.tasks)


def test_structured_planner_is_single_call_and_schema_checked() -> None:
    decision = decide_decomposition("Add schema and API endpoint", repo_map())
    adapter = StructuredPlannerAdapter(lambda _: "{}")
    with pytest.raises(ValidationError):
        adapter.propose("issue", repo_map(), decision, max_tasks=5)
    with pytest.raises(RuntimeError, match="budget"):
        adapter.propose("issue", repo_map(), decision, max_tasks=5)


def test_cache_key_and_cache_are_deterministic(tmp_path: Path) -> None:
    config = {"model": "fake", "max_tasks": 5}
    first = planner_cache_key("issue", "sha", "v1", config)
    second = planner_cache_key("issue", "sha", "v1", json.loads(json.dumps(config)))
    assert first == second
    decision = decide_decomposition("Fix one file typo", repo_map())
    proposal = FakePlanner().propose("Fix one file typo", repo_map(), decision, max_tasks=5)
    cache = PlannerCache(tmp_path)
    cache.save(first, proposal)
    assert cache.load(first) == proposal


def test_codex_planner_timeout_becomes_safe_fallback_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def time_out(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired("sensitive-command", 1)

    monkeypatch.setattr(subprocess, "run", time_out)
    decision = decide_decomposition("Add schema and API endpoint", repo_map())

    with pytest.raises(RuntimeError, match="bounded timeout"):
        CodexPlannerAdapter(tmp_path).propose("request", repo_map(), decision, max_tasks=5)
