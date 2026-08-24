"""Deterministic production ready queue policies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from firstgreen.config import TaskConfig

ReadyQueuePolicy = Literal["stable", "critical_path"]


@dataclass(frozen=True)
class RankedTask:
    task: TaskConfig
    bottom_level_seconds: float
    ready_rank: tuple[float | int | str, ...]


def bottom_levels(tasks: list[TaskConfig]) -> dict[str, float]:
    """Compute duration plus the maximum successor rank for every task."""

    by_id = {task.id: task for task in tasks}
    successors: dict[str, list[str]] = {task.id: [] for task in tasks}
    for task in tasks:
        for dependency in task.dependencies:
            if dependency not in by_id:
                raise ValueError(f"unknown task dependency: {dependency}")
            successors[dependency].append(task.id)
    memo: dict[str, float] = {}
    visiting: set[str] = set()

    def rank(task_id: str) -> float:
        if task_id in memo:
            return memo[task_id]
        if task_id in visiting:
            raise ValueError("ready queue requires an acyclic task graph")
        visiting.add(task_id)
        tail = max((rank(item) for item in successors[task_id]), default=0.0)
        visiting.remove(task_id)
        result = round(by_id[task_id].estimated_duration_seconds + tail, 3)
        memo[task_id] = result
        return result

    for task_id in sorted(by_id):
        rank(task_id)
    return memo


def ranked_ready_tasks(
    tasks: list[TaskConfig],
    terminal_green: set[str],
    *,
    policy: ReadyQueuePolicy = "stable",
    all_tasks: list[TaskConfig] | None = None,
) -> list[RankedTask]:
    ranks = bottom_levels(all_tasks or tasks)
    ready = [task for task in tasks if all(dep in terminal_green for dep in task.dependencies)]
    if policy == "critical_path":
        ordered = sorted(
            ready,
            key=lambda task: (-ranks[task.id], -task.priority, task.id),
        )
        return [
            RankedTask(task, ranks[task.id], (-ranks[task.id], -task.priority, task.id))
            for task in ordered
        ]
    ordered = sorted(ready, key=lambda task: (-task.priority, task.id))
    return [RankedTask(task, ranks[task.id], (-task.priority, task.id)) for task in ordered]


def ready_tasks(
    tasks: list[TaskConfig],
    terminal_green: set[str],
    *,
    policy: ReadyQueuePolicy = "stable",
    all_tasks: list[TaskConfig] | None = None,
) -> list[TaskConfig]:
    return [
        item.task
        for item in ranked_ready_tasks(tasks, terminal_green, policy=policy, all_tasks=all_tasks)
    ]
