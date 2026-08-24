"""Deterministic work/span analysis for approved execution DAGs."""

from __future__ import annotations

import hashlib
import itertools
import json
import math

from firstgreen.planning.models import ParallelismAnalysis, PlanTask


def estimate_task_duration(task: PlanTask, *, minimum_seconds: int) -> PlanTask:
    """Attach a bounded, explainable v0.1 estimate without trusting planner arithmetic."""

    base = float(max(1, minimum_seconds))
    factor = 0.75 if task.read_only else 1.0
    factor += min(0.6, 0.1 * max(0, len(task.likely_paths) - 1))
    factor += min(0.3, 0.05 * max(0, len(task.verifier) - 1))
    factor += min(0.3, 0.1 * len(task.risk_tags))
    duration = round(max(1.0, base * factor), 3)
    return task.model_copy(
        update={
            "estimated_duration_seconds": duration,
            "estimate_source": "deterministic_heuristic_v1",
        }
    )


def _ancestors(tasks: list[PlanTask]) -> dict[str, set[str]]:
    by_id = {task.id: task for task in tasks}
    memo: dict[str, set[str]] = {}
    visiting: set[str] = set()

    def visit(task_id: str) -> set[str]:
        if task_id in memo:
            return memo[task_id]
        if task_id in visiting:
            raise ValueError("parallelism analysis requires an acyclic task graph")
        visiting.add(task_id)
        result: set[str] = set()
        for dependency in by_id[task_id].dependencies:
            if dependency not in by_id:
                raise ValueError(f"unknown task dependency: {dependency}")
            result.add(dependency)
            result.update(visit(dependency))
        visiting.remove(task_id)
        memo[task_id] = result
        return result

    for task in tasks:
        visit(task.id)
    return memo


def _ready_width(tasks: list[PlanTask], ancestors: dict[str, set[str]]) -> int:
    """Return the largest dependency- and resource-compatible antichain."""

    best = 1
    for size in range(2, len(tasks) + 1):
        for group in itertools.combinations(tasks, size):
            ids = {task.id for task in group}
            if any((ancestors[task.id] & ids) for task in group):
                continue
            resources = [resource for task in group for resource in task.resources]
            if len(resources) != len(set(resources)):
                continue
            best = size
    return best


def analyze_parallelism(tasks: list[PlanTask], *, max_root_slots: int = 5) -> ParallelismAnalysis:
    if not tasks:
        raise ValueError("parallelism analysis requires at least one task")
    by_id = {task.id: task for task in tasks}
    if len(by_id) != len(tasks):
        raise ValueError("parallelism analysis requires unique task ids")
    ancestors = _ancestors(tasks)
    finish: dict[str, float] = {}
    predecessor: dict[str, str | None] = {}
    remaining = set(by_id)
    while remaining:
        ready = sorted(
            task_id
            for task_id in remaining
            if all(dependency in finish for dependency in by_id[task_id].dependencies)
        )
        if not ready:
            raise ValueError("parallelism analysis requires an acyclic task graph")
        for task_id in ready:
            task = by_id[task_id]
            parent = max(task.dependencies, key=lambda item: (finish[item], item), default=None)
            start = finish[parent] if parent is not None else 0.0
            finish[task_id] = start + task.estimated_duration_seconds
            predecessor[task_id] = parent
            remaining.remove(task_id)

    sink = max(finish, key=lambda item: (finish[item], item))
    critical_path: list[str] = []
    cursor: str | None = sink
    while cursor is not None:
        critical_path.append(cursor)
        cursor = predecessor[cursor]
    critical_path.reverse()

    work = round(sum(task.estimated_duration_seconds for task in tasks), 3)
    span = round(finish[sink], 3)
    width = _ready_width(tasks, ancestors)
    exposed = round(max(1.0, work / span), 3)
    bounded_max = max(1, min(max_root_slots, len(tasks)))
    recommended = max(1, min(width, bounded_max, math.ceil(exposed)))
    if recommended == 1:
        reason = "No dependency- and resource-compatible parallel work is exposed."
    else:
        reason = (
            f"Bounded by ready width {width}, estimated W/L {exposed:.3f}, "
            f"and the {bounded_max}-slot product limit."
        )
    snapshot = [
        {
            "id": task.id,
            "dependencies": sorted(task.dependencies),
            "resources": sorted(task.resources),
            "duration": task.estimated_duration_seconds,
            "source": task.estimate_source,
        }
        for task in sorted(tasks, key=lambda item: item.id)
    ]
    estimate_hash = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return ParallelismAnalysis(
        estimated_work_seconds=work,
        estimated_span_seconds=span,
        critical_path=critical_path,
        ready_width=width,
        exposed_parallelism=exposed,
        recommended_root_slots=recommended,
        recommendation_reason=reason,
        estimate_hash=estimate_hash,
    )
