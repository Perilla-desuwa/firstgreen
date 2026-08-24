import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from firstgreen.clock import FakeClock
from firstgreen.planning.models import (
    ApprovedPlan,
    DecompositionDecision,
    PlannerProposal,
    ProposedTask,
)
from firstgreen.planning.planner import StructuredPlannerAdapter
from firstgreen.planning.workflow import (
    PlanningEngine,
    default_planning_config,
    load_plan,
    plan_to_manifest,
    save_plan,
)
from firstgreen.work_requests import request_from_token


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "src" / "auth").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "src" / "auth" / "service.py").write_text("def reset(): pass\n")
    (repo / "src" / "auth" / "routes.py").write_text("def route(): pass\n")
    (repo / "tests" / "test_auth.py").write_text("def test_auth(): pass\n")
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    return repo


def test_plan_persist_approve_edit_roundtrip_and_compile(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    engine = PlanningEngine(tmp_path / "state")
    config = default_planning_config()
    outcome = engine.plan_issue(
        "Add password reset service, API endpoint, tests, and documentation",
        repo,
        config,
    )
    assert outcome.plan.validation.valid
    path = save_plan(outcome.plan, tmp_path / "plan.yaml")
    loaded = load_plan(path)
    assert loaded.cache_key == outcome.plan.cache_key
    approved = engine.approve(outcome, config)
    manifest = plan_to_manifest(
        ApprovedPlan.model_validate(approved), adapter="fake", replay_safe=False
    )
    assert 1 <= len(manifest.tasks) <= 5
    assert all(task.verify.commands for task in manifest.tasks)
    assert all(task.limits.max_attempts == 3 for task in manifest.tasks)
    assert manifest.agent_defaults.timeout_seconds == 900
    assert all(not task.replay_safe for task in manifest.tasks)
    assert manifest.project.base_ref == approved.commit_sha
    assert [command.argv for command in manifest.verification_defaults.delivery_commands] == [
        command for command in approved.delivery_verifier
    ]
    for task in manifest.tasks:
        assert approved.request in task.prompt
        assert task.id in task.prompt
        assert "planned_writable_paths" in task.prompt
        assert "verification_hints" in task.prompt
        assert "scheduler_verifier_commands" in task.prompt
        assert "peer_task_boundaries" in task.prompt

    if len(manifest.tasks) > 1:
        first = manifest.tasks[0]
        for peer in manifest.tasks[1:]:
            assert peer.id in first.prompt
        assert "do not implement their deliverables" in first.prompt

    seed_task = approved.tasks[0]
    serial_plan = approved.model_copy(
        update={
            "decision": approved.decision.model_copy(update={"recommended_parallelism": 3}),
            "tasks": [
                seed_task.model_copy(update={"id": f"serial-{index}", "dependencies": []})
                for index in range(3)
            ],
            "parallelism_analysis": None,
        }
    )
    serial_manifest = plan_to_manifest(
        serial_plan,
        adapter="fake",
        replay_safe=False,
        policy="single",
    )
    assert serial_manifest.scheduler.concurrency.max_root == 1
    assert serial_manifest.scheduler.concurrency.total_agent_thread_budget == 1
    assert serial_manifest.scheduler.concurrency.verifier_slots == 1


def test_high_risk_auto_approval_is_refused(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    engine = PlanningEngine(tmp_path / "state")
    config = default_planning_config()
    outcome = engine.plan_issue("Add database migration and API endpoint", repo, config)
    if outcome.plan.risk_level != "low":
        try:
            engine.approve(outcome, config, policy_auto_approval=True)
        except ValueError as error:
            assert "eligible" in str(error)
        else:
            raise AssertionError("high-risk plan was auto-approved")


def test_manifest_uses_executable_python_verifier(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    engine = PlanningEngine(tmp_path / "state")
    outcome = engine.plan_issue("Fix one file typo", repo, default_planning_config(), mode="none")
    approved = engine.approve(outcome, default_planning_config())
    manifest = plan_to_manifest(approved, adapter="fake", replay_safe=True)
    manifest.tasks[0].verify.commands[0].argv = [sys.executable, "-m", "pytest"]
    assert manifest.tasks[0].verify.commands[0].argv[0] == sys.executable


def test_explicit_codex_provider_calls_planner_even_for_classifier_single_task(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)
    proposal = PlannerProposal(
        planner_version="structured",
        decision=DecompositionDecision(
            recommended_parallelism=1,
            decision="single_task",
            reason="planner confirmed one task",
        ),
        tasks=[ProposedTask(id="fix", objective="Fix the callback race")],
        call_count=1,
        input_tokens=None,
        output_tokens=None,
        estimated_cost=None,
        latency_seconds=0,
    )
    planner = StructuredPlannerAdapter(lambda _: proposal.model_dump_json())
    engine = PlanningEngine(tmp_path / "state", planner=planner)
    outcome = engine.plan_issue(
        "Fix the OAuth callback race condition", repo, default_planning_config(fake=False)
    )

    assert planner.calls == 1
    assert outcome.plan.planner_version == "structured"
    assert len(outcome.plan.tasks) == 1


def test_malformed_planner_output_falls_back_without_retry(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    planner = StructuredPlannerAdapter(lambda _: "{}")
    engine = PlanningEngine(tmp_path / "state", planner=planner)
    outcome = engine.plan_issue(
        "Add service, API endpoint, tests, and documentation",
        repo,
        default_planning_config(fake=False),
    )
    assert planner.calls == 1
    assert outcome.plan.planner_version == "deterministic-fallback-v1"
    assert len(outcome.plan.tasks) == 1
    assert "Planner failed (ValidationError)" in outcome.plan.decision.reason
    assert "Planner unavailable (ValidationError)" in (outcome.plan.tasks[0].uncertainty or "")
    with engine.repository.connect() as connection:
        failure = connection.execute(
            "SELECT payload FROM events WHERE type='planning.planner_failed'"
        ).fetchone()
    assert failure is not None
    assert json.loads(str(failure["payload"]))["error_type"] == "ValidationError"

    retry = StructuredPlannerAdapter(lambda _: "{}")
    repeated = PlanningEngine(tmp_path / "state", planner=retry).plan_issue(
        "Add service, API endpoint, tests, and documentation",
        repo,
        default_planning_config(fake=False),
    )
    assert retry.calls == 1
    assert not repeated.cache_hit


def test_user_edited_candidate_is_revalidated_and_persisted(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    engine = PlanningEngine(tmp_path / "state")
    config = default_planning_config()
    outcome = engine.plan_issue("Fix one file typo", repo, config)
    edited_plan = outcome.plan.model_copy(
        update={
            "tasks": [
                outcome.plan.tasks[0].model_copy(
                    update={"objective": "Fix the typo and document the behavior"}
                )
            ]
        }
    )

    edited = engine.replace_candidate(outcome, edited_plan, config)

    assert edited.plan.user_edited
    assert edited.plan.validation.valid
    with engine.repository.connect() as connection:
        persisted = connection.execute(
            "SELECT user_edited,plan_json FROM candidate_plans WHERE id=?",
            (outcome.plan_id,),
        ).fetchone()
    assert persisted is not None and persisted["user_edited"] == 1
    assert "Fix the typo and document" in str(persisted["plan_json"])


def test_planning_lifecycle_uses_injected_clock(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    instant = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
    engine = PlanningEngine(tmp_path / "state", clock=FakeClock(instant))
    outcome = engine.plan_issue("Fix one file typo", repo, default_planning_config(), mode="none")

    with engine.repository.transaction() as connection:
        request = connection.execute(
            "SELECT created_at,updated_at FROM planning_requests WHERE id=?",
            (outcome.request_id,),
        ).fetchone()
    assert request is not None
    assert request["created_at"] == instant.isoformat()
    assert request["updated_at"] == instant.isoformat()


def test_work_request_source_enters_the_production_planning_record(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    request_file = tmp_path / "request.md"
    request_file.write_text("Fix one file typo", encoding="utf-8")
    request = request_from_token(str(request_file), repo)
    engine = PlanningEngine(tmp_path / "state")

    outcome = engine.plan_request(request, default_planning_config(), mode="none")

    with engine.repository.connect() as connection:
        row = connection.execute(
            "SELECT config_snapshot FROM planning_requests WHERE id=?", (outcome.request_id,)
        ).fetchone()
    assert row is not None
    snapshot = json.loads(str(row["config_snapshot"]))
    assert snapshot["work_request_source"] == {
        "type": "file",
        "reference": str(request_file.resolve()),
    }
    assert outcome.plan.request == request.content
