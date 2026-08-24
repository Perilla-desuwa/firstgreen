from firstgreen.config import CommandConfig, TaskConfig, VerifyConfig
from firstgreen.scheduler.queue import bottom_levels, ranked_ready_tasks, ready_tasks


def task(
    task_id: str,
    duration: float,
    *,
    dependencies: list[str] | None = None,
    priority: int = 0,
) -> TaskConfig:
    return TaskConfig(
        id=task_id,
        prompt=task_id,
        dependencies=dependencies or [],
        priority=priority,
        estimated_duration_seconds=duration,
        estimate_source="test",
        verify=VerifyConfig(commands=[CommandConfig(argv=["true"])]),
    )


def test_bottom_level_includes_longest_successor_chain() -> None:
    tasks = [
        task("short-root", 1, priority=5),
        task("critical-root", 2),
        task("critical-tail", 10, dependencies=["critical-root"]),
    ]

    assert bottom_levels(tasks) == {
        "short-root": 1,
        "critical-root": 12,
        "critical-tail": 10,
    }
    assert [item.task.id for item in ranked_ready_tasks(tasks, set(), policy="critical_path")] == [
        "critical-root",
        "short-root",
    ]


def test_stable_policy_preserves_priority_then_id_order() -> None:
    tasks = [task("b", 100), task("a", 1), task("priority", 1, priority=2)]

    assert [item.id for item in ready_tasks(tasks, set())] == ["priority", "a", "b"]


def test_critical_path_ties_fall_back_to_priority_then_id() -> None:
    tasks = [task("b", 5), task("a", 5), task("priority", 5, priority=1)]

    ranked = ranked_ready_tasks(tasks, set(), policy="critical_path")
    assert [item.task.id for item in ranked] == ["priority", "a", "b"]
