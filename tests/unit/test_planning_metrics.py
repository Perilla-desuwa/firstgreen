import json
from pathlib import Path

from firstgreen.db.repository import SQLiteRepository
from firstgreen.reporting.planning import planning_metrics


def test_planning_metrics_keep_cost_separate(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "state.db")
    repository.initialize()
    with repository.transaction() as connection:
        connection.execute(
            "INSERT INTO planning_requests VALUES(?,?,?,?,?,?,?,?,?)",
            ("p", "hash", "issue", ".", "sha", "plan_approved", "{}", "now", "now"),
        )
        plan = {
            "planner_version": "codex-planner-v1",
            "decision": {"decision": "decompose"},
            "tasks": [{}, {}],
        }
        connection.execute(
            "INSERT INTO candidate_plans(id,planning_request_id,planner_version,cache_key,"
            "plan_json,approved,user_edited,planning_latency_seconds,input_tokens,output_tokens,"
            "estimated_cost,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            ("c", "p", "codex-planner-v1", "key", json.dumps(plan), 1, 0, 2.5, 10, 5, 0.03, "now"),
        )
        connection.execute(
            "INSERT INTO plan_validation_results VALUES(?,?,?,?,?)",
            ("v", "c", 1, "{}", "now"),
        )
    metrics = planning_metrics(repository)
    assert metrics["decomposition_acceptance_rate"] == 1
    assert metrics["planning_estimated_cost"] == 0.03
    assert metrics["realized_parallelism"] is None
