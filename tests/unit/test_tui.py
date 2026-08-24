from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

from rich.console import Console

from firstgreen.planning.models import (
    CandidatePlan,
    DecompositionDecision,
    ParallelismAnalysis,
    PlanTask,
    PlanValidationResult,
)
from firstgreen.tui import (
    ask_plan_action,
    events_renderable,
    plan_renderable,
    read_multiline_request,
    result_renderable,
    run_renderable,
)


def candidate_plan() -> CandidatePlan:
    return CandidatePlan(
        planner_version="fake-v1",
        request="Fix upload collisions",
        request_hash="hash",
        repo=Path("."),
        commit_sha="sha",
        repository_map_version="repo-map-v1",
        decision=DecompositionDecision(
            recommended_parallelism=2,
            decision="decompose",
            reason="storage and tests can be verified independently",
        ),
        tasks=[
            PlanTask(
                id="storage",
                objective="Rename colliding uploads",
                likely_paths=["src/storage.py"],
                verifier=[["python", "-m", "pytest"]],
            ),
            PlanTask(
                id="integration",
                objective="Add regression tests",
                dependencies=["storage"],
                likely_paths=["tests/test_storage.py"],
                verifier=[["python", "-m", "pytest"]],
            ),
        ],
        parallelism_analysis=ParallelismAnalysis(
            estimated_work_seconds=2,
            estimated_span_seconds=2,
            critical_path=["storage", "integration"],
            ready_width=1,
            exposed_parallelism=1,
            recommended_root_slots=1,
            recommendation_reason="Dependency chain is sequential.",
            estimate_hash="hash",
        ),
        risk_level="low",
        validation=PlanValidationResult(valid=True),
        cache_key="key",
        planning_latency_seconds=0,
        planning_input_tokens=None,
        planning_output_tokens=None,
        planning_estimated_cost=None,
    )


def render(value: object, *, width: int = 120) -> str:
    output = StringIO()
    Console(file=output, color_system=None, width=width).print(value)
    return output.getvalue()


def test_plan_tui_shows_dag_and_verification() -> None:
    output = render(plan_renderable(candidate_plan()))

    assert "Recommended root slots" in output
    assert "Estimated work / span" in output
    assert "Critical path" in output
    assert "FirstGreen plan review" in output
    assert "Nothing has been executed yet" in output
    assert "Execution DAG" in output
    assert "Starts after" in output
    assert "storage" in output
    assert "integration" in output
    assert "src/storage.py" in output
    assert "python -m pytest" in output
    assert "Required before any worker starts" in output


def test_plan_action_reprompts_until_valid() -> None:
    answers = iter(["wrong", "s"])

    assert ask_plan_action(reader=lambda _prompt: next(answers)) == "single"


def test_multiline_request_submits_on_blank_line() -> None:
    answers = iter(["Fix upload collisions", "and add tests", ""])

    assert read_multiline_request(reader=lambda _prompt: next(answers)) == (
        "Fix upload collisions\nand add tests"
    )


def test_run_tui_uses_persisted_scheduler_shape() -> None:
    output = render(
        run_renderable(
            {
                "run": {
                    "id": "run_1",
                    "status": "running",
                    "created_at": "2026-07-14T00:00:00+00:00",
                    "started_at": "2026-07-14T00:00:00+00:00",
                },
                "tasks": [
                    {"task_key": "storage", "status": "verified"},
                    {"task_key": "tests", "status": "running"},
                ],
                "attempts": [
                    {"task_key": "storage", "role": "primary", "status": "winner"},
                    {"task_key": "tests", "role": "primary", "status": "running"},
                ],
                "summary": {"verified": 1, "failed": 0},
                "planning": {"planning_estimated_cost": None},
            },
            now=datetime(2026, 7, 14, 0, 1, 5, tzinfo=UTC),
        )
    )

    assert "storage" in output
    assert "verified" in output
    assert "Agents: 1 active" in output
    assert "Elapsed: 01:05" in output
    assert "Cost: unavailable" in output


def test_event_tui_renders_filtered_payload() -> None:
    output = render(
        events_renderable(
            [
                {
                    "timestamp": "2026-07-14T00:00:00+00:00",
                    "task_key": "storage",
                    "type": "worker.unknown",
                    "payload": {"event_type": "future-event"},
                }
            ]
        )
    )

    assert "worker.unknown" in output
    assert "future-event" in output


def test_result_tui_shows_scheduler_evidence_and_next_steps(tmp_path: Path) -> None:
    output = render(
        result_renderable(
            {
                "run": {
                    "id": "run_1",
                    "status": "completed",
                    "repo_path": "C:/repo",
                    "base_sha": "1234567890abcdef",
                    "created_at": "2026-07-14T00:00:00+00:00",
                    "started_at": "2026-07-14T00:00:00+00:00",
                    "finished_at": "2026-07-14T00:01:05+00:00",
                },
                "tasks": [
                    {
                        "task_key": "storage",
                        "status": "verified",
                        "winner_attempt_id": "attempt_1",
                    }
                ],
                "attempts": [
                    {
                        "id": "attempt_1",
                        "task_key": "storage",
                        "role": "primary",
                        "status": "winner",
                        "workspace_path": "C:/state/workspaces/run_1/storage/attempt_1",
                    }
                ],
                "verifications": [
                    {
                        "task_key": "storage",
                        "verification_round": 1,
                        "command_json": '{"argv":["python","-m","pytest"]}',
                        "status": "passed",
                        "exit_code": 0,
                    }
                ],
                "summary": {"verified": 1, "failed": 0, "hedges": 0},
                "usage": {
                    "reported": True,
                    "input_tokens": 10,
                    "cached_input_tokens": 4,
                    "output_tokens": 2,
                    "reasoning_output_tokens": 1,
                    "total_tokens": 12,
                },
                "changes": {
                    "changed_paths": ["src/storage.py", "tests/test_storage.py"],
                    "disallowed_paths": [],
                },
            },
            report_path=tmp_path / "report.html",
            manifest_path=tmp_path / "manifest.yaml",
            state_dir=tmp_path / "state",
        ),
        width=300,
    )

    assert "FirstGreen result: VERIFIED" in output
    assert "attempt_1" in output
    assert "python -m pytest" in output
    assert "src/storage.py" in output
    assert "reported total 12" in output
    assert "Main working tree" in output
    assert "FirstGreen did not merge" in output
    assert "fg report run_1 --open" in output


def test_failed_result_tui_prints_exact_reverify_command(tmp_path: Path) -> None:
    output = render(
        result_renderable(
            {
                "run": {
                    "id": "run_failed",
                    "status": "failed",
                    "repo_path": "C:/repo",
                    "base_sha": "1234567890abcdef",
                },
                "tasks": [{"task_key": "storage", "status": "failed"}],
                "attempts": [
                    {
                        "id": "attempt_failed",
                        "task_key": "storage",
                        "role": "primary",
                        "status": "failed",
                        "workspace_path": "C:/failed-workspace",
                    }
                ],
                "verifications": [],
                "summary": {"verified": 0, "failed": 1, "hedges": 0},
                "usage": {"reported": False},
                "changes": {"changed_paths": [], "disallowed_paths": []},
            },
            report_path=tmp_path / "report.html",
            manifest_path=tmp_path / "manifest.yaml",
            state_dir=tmp_path / "state",
        ),
        width=300,
    )

    assert "FirstGreen result: NOT VERIFIED" in output
    assert "fg reverify run_failed --attempt attempt_failed" in output
    assert "manifest.yaml" in output
