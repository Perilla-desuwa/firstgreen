from firstgreen.planning.models import PlanTask
from firstgreen.planning.parallelism import analyze_parallelism


def task(
    task_id: str,
    duration: float,
    *,
    dependencies: list[str] | None = None,
    resources: list[str] | None = None,
) -> PlanTask:
    return PlanTask(
        id=task_id,
        objective=task_id,
        dependencies=dependencies or [],
        resources=resources or [],
        estimated_duration_seconds=duration,
        estimate_source="unit",
    )


def test_branch_join_analysis_reports_work_span_path_and_width() -> None:
    analysis = analyze_parallelism(
        [
            task("root", 2),
            task("left", 5, dependencies=["root"]),
            task("right", 3, dependencies=["root"]),
            task("join", 4, dependencies=["left", "right"]),
        ]
    )

    assert analysis.estimated_work_seconds == 14
    assert analysis.estimated_span_seconds == 11
    assert analysis.critical_path == ["root", "left", "join"]
    assert analysis.ready_width == 2
    assert analysis.exposed_parallelism == 1.273
    assert analysis.recommended_root_slots == 2


def test_resource_conflicts_reduce_ready_width_and_slot_recommendation() -> None:
    analysis = analyze_parallelism(
        [
            task("a", 5, resources=["write:shared"]),
            task("b", 5, resources=["write:shared"]),
        ]
    )

    assert analysis.ready_width == 1
    assert analysis.recommended_root_slots == 1
    assert "No dependency" in analysis.recommendation_reason


def test_analysis_hash_changes_with_duration_snapshot() -> None:
    before = analyze_parallelism([task("a", 1), task("b", 1)])
    after = analyze_parallelism([task("a", 2), task("b", 1)])

    assert before.estimate_hash != after.estimate_hash
