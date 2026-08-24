"""Planning-specific aggregate metrics; unavailable execution comparisons remain explicit."""

import json
from typing import Any

from firstgreen.db.repository import SQLiteRepository


def planning_metrics(repository: SQLiteRepository) -> dict[str, Any]:
    with repository.connect() as connection:
        rows = connection.execute(
            "SELECT plan_json,approved,user_edited,planning_latency_seconds,input_tokens,"
            "output_tokens,estimated_cost FROM candidate_plans"
        ).fetchall()
        invalid = connection.execute(
            "SELECT COUNT(*) FROM plan_validation_results WHERE valid=0"
        ).fetchone()[0]
    plans = [json.loads(row["plan_json"]) for row in rows]
    total = len(rows)
    decomposed = sum(plan.get("decision", {}).get("decision") == "decompose" for plan in plans)
    single = sum(len(plan.get("tasks", [])) == 1 for plan in plans)
    calls = sum(
        1
        for plan in plans
        if plan.get("planner_version")
        not in {
            "fake-planner-v1",
            "deterministic-fallback-v1",
            "budget-bypass-v1",
            "small-task-bypass-v1",
        }
    )
    return {
        "plans": total,
        "decomposition_acceptance_rate": decomposed / total if total else 0.0,
        "single_task_rate": single / total if total else 0.0,
        "dag_validation_failure_rate": invalid / total if total else 0.0,
        "user_edit_rate": sum(int(row["user_edited"]) for row in rows) / total if total else 0.0,
        "approval_rate": sum(int(row["approved"]) for row in rows) / total if total else 0.0,
        "planner_call_rate": calls / total if total else 0.0,
        "average_planning_seconds": (
            sum(float(row["planning_latency_seconds"]) for row in rows) / total if total else 0.0
        ),
        "planning_input_tokens": sum(int(row["input_tokens"] or 0) for row in rows),
        "planning_output_tokens": sum(int(row["output_tokens"] or 0) for row in rows),
        "planning_estimated_cost": sum(float(row["estimated_cost"] or 0) for row in rows),
        "predicted_vs_actual_write_overlap": None,
        "predicted_vs_actual_task_duration": None,
        "realized_parallelism": None,
        "critical_path_reduction": None,
        "duplicate_work_ratio": None,
        "merge_conflict_rate": None,
        "replanning_rate": 0.0,
    }
