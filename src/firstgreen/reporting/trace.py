"""Sanitized runtime summary and Chrome/Perfetto trace export."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from firstgreen.db.repository import SQLiteRepository


def _micros(value: str, origin: datetime) -> float:
    return (datetime.fromisoformat(value) - origin).total_seconds() * 1_000_000


def runtime_observability(repository: SQLiteRepository, run_id: str) -> dict[str, Any]:
    with repository.connect() as connection:
        run = connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if run is None:
            raise ValueError(f"run not found: {run_id}")
        attempts = connection.execute(
            "SELECT a.id,t.task_key,a.role,a.started_at,a.finished_at FROM attempts a "
            "JOIN tasks t ON t.id=a.task_id WHERE t.run_id=? AND a.started_at IS NOT NULL "
            "ORDER BY a.started_at",
            (run_id,),
        ).fetchall()
        verifications = connection.execute(
            "SELECT v.id,t.task_key,v.started_at,v.finished_at FROM verification_runs v "
            "JOIN attempts a ON a.id=v.attempt_id JOIN tasks t ON t.id=a.task_id "
            "WHERE t.run_id=? AND v.started_at IS NOT NULL ORDER BY v.started_at",
            (run_id,),
        ).fetchall()
        events = connection.execute(
            "SELECT type,timestamp,payload FROM events WHERE run_id=? ORDER BY sequence",
            (run_id,),
        ).fetchall()
    started = datetime.fromisoformat(str(run["started_at"] or run["created_at"]))
    finished = datetime.fromisoformat(
        str(run["finished_at"] or run["started_at"] or run["created_at"])
    )
    makespan = max(0.0, (finished - started).total_seconds())
    agent_seconds = sum(
        max(
            0.0,
            (
                datetime.fromisoformat(str(row["finished_at"] or run["finished_at"]))
                - datetime.fromisoformat(str(row["started_at"]))
            ).total_seconds(),
        )
        for row in attempts
        if row["finished_at"] is not None or run["finished_at"] is not None
    )
    verifier_seconds = sum(
        max(
            0.0,
            (
                datetime.fromisoformat(str(row["finished_at"] or run["finished_at"]))
                - datetime.fromisoformat(str(row["started_at"]))
            ).total_seconds(),
        )
        for row in verifications
        if row["finished_at"] is not None or run["finished_at"] is not None
    )
    queue_wait = 0.0
    idle_reason_observations = {
        "dependency_limited": 0,
        "parallelism_exhausted": 0,
        "resource_locked": 0,
        "verifier_limited": 0,
    }
    for row in events:
        try:
            payload = json.loads(str(row["payload"]))
        except (TypeError, ValueError):
            continue
        if row["type"] == "verifier.admitted":
            wait = float(payload.get("queue_wait_seconds", 0))
            queue_wait += wait
            if wait >= 0.001:
                idle_reason_observations["verifier_limited"] += 1
        elif row["type"] == "scheduler.ready_set":
            ready_count = len(payload.get("ready_task_keys", []))
            pending_count = int(payload.get("pending_count", 0))
            running_count = int(payload.get("running_count", 0))
            if ready_count == 0 and pending_count > 0:
                idle_reason_observations["dependency_limited"] += 1
            elif ready_count == 0 and running_count > 0:
                idle_reason_observations["parallelism_exhausted"] += 1
    with repository.connect() as connection:
        resource_holds = connection.execute(
            "SELECT COUNT(*) FROM scheduler_decisions WHERE run_id=? "
            "AND decision_type='admission_hold'",
            (run_id,),
        ).fetchone()[0]
    idle_reason_observations["resource_locked"] = int(resource_holds)
    try:
        policy = json.loads(str(run["policy_snapshot"]))
        root_slots = int(policy["concurrency"]["max_root"])
    except (KeyError, TypeError, ValueError):
        root_slots = 1
    root_capacity_seconds = makespan * max(1, root_slots)
    return {
        "run_id": run_id,
        "makespan_seconds": makespan,
        "agent_seconds": agent_seconds,
        "verifier_seconds": verifier_seconds,
        "verifier_queue_wait_seconds": queue_wait,
        "average_active_agents": agent_seconds / makespan if makespan else 0.0,
        "root_slot_utilization": (
            min(1.0, agent_seconds / root_capacity_seconds) if root_capacity_seconds else 0.0
        ),
        "idle_root_slot_seconds": max(0.0, root_capacity_seconds - agent_seconds),
        "idle_reason_observations": idle_reason_observations,
        "attempt_count": len(attempts),
    }


def export_trace(repository: SQLiteRepository, run_id: str, path: Path) -> Path:
    with repository.connect() as connection:
        run = connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if run is None:
            raise ValueError(f"run not found: {run_id}")
        attempts = connection.execute(
            "SELECT a.id,t.task_key,a.role,a.started_at,a.finished_at FROM attempts a "
            "JOIN tasks t ON t.id=a.task_id WHERE t.run_id=? AND a.started_at IS NOT NULL",
            (run_id,),
        ).fetchall()
        verifications = connection.execute(
            "SELECT v.id,t.task_key,v.started_at,v.finished_at FROM verification_runs v "
            "JOIN attempts a ON a.id=v.attempt_id JOIN tasks t ON t.id=a.task_id "
            "WHERE t.run_id=? AND v.started_at IS NOT NULL",
            (run_id,),
        ).fetchall()
        delivery = connection.execute(
            "SELECT id,created_at,verified_at FROM deliveries WHERE run_id=?", (run_id,)
        ).fetchone()
    origin = datetime.fromisoformat(str(run["started_at"] or run["created_at"]))
    trace_events: list[dict[str, Any]] = []
    for row in attempts:
        if row["finished_at"] is None:
            continue
        start = datetime.fromisoformat(str(row["started_at"]))
        finish = datetime.fromisoformat(str(row["finished_at"]))
        trace_events.append(
            {
                "name": f"{row['task_key']} [{row['role']}]",
                "cat": "agent",
                "ph": "X",
                "pid": "firstgreen",
                "tid": "agents",
                "ts": _micros(str(row["started_at"]), origin),
                "dur": (finish - start).total_seconds() * 1_000_000,
                "args": {"task_key": row["task_key"], "role": row["role"]},
            }
        )
    for row in verifications:
        if row["finished_at"] is None:
            continue
        start = datetime.fromisoformat(str(row["started_at"]))
        finish = datetime.fromisoformat(str(row["finished_at"]))
        trace_events.append(
            {
                "name": str(row["task_key"]),
                "cat": "verifier",
                "ph": "X",
                "pid": "firstgreen",
                "tid": "verifier",
                "ts": _micros(str(row["started_at"]), origin),
                "dur": (finish - start).total_seconds() * 1_000_000,
                "args": {"task_key": row["task_key"]},
            }
        )
    if delivery is not None and delivery["verified_at"] is not None:
        delivery_start = datetime.fromisoformat(str(delivery["created_at"]))
        delivery_finish = datetime.fromisoformat(str(delivery["verified_at"]))
        trace_events.append(
            {
                "name": "final delivery",
                "cat": "integration",
                "ph": "X",
                "pid": "firstgreen",
                "tid": "integration",
                "ts": _micros(str(delivery["created_at"]), origin),
                "dur": (delivery_finish - delivery_start).total_seconds() * 1_000_000,
                "args": {},
            }
        )
    payload = {
        "traceEvents": sorted(trace_events, key=lambda item: (item["ts"], item["tid"])),
        "displayTimeUnit": "ms",
        "metadata": runtime_observability(repository, run_id),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
