"""JSON, CSV, and static HTML run exports."""

import csv
import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, select_autoescape

from firstgreen.db.repository import SQLiteRepository
from firstgreen.reporting.planning import planning_metrics


def event_data(
    repository: SQLiteRepository, run_id: str, *, limit: int = 200
) -> list[dict[str, Any]]:
    """Return persisted, already-filtered worker events for terminal diagnostics."""

    bounded_limit = max(1, min(limit, 2000))
    with repository.connect() as connection:
        rows = connection.execute(
            "SELECT e.sequence,e.type,e.timestamp,e.attempt_id,e.payload,t.task_key "
            "FROM events e LEFT JOIN tasks t ON t.id=e.task_id "
            "WHERE e.run_id=? ORDER BY e.sequence DESC LIMIT ?",
            (run_id, bounded_limit),
        ).fetchall()
    events: list[dict[str, Any]] = []
    for row in reversed(rows):
        try:
            payload: object = json.loads(str(row["payload"]))
        except ValueError:
            payload = {"diagnostic": "invalid persisted JSON payload"}
        events.append(
            {
                "sequence": row["sequence"],
                "type": row["type"],
                "timestamp": row["timestamp"],
                "task_key": row["task_key"],
                "attempt_id": row["attempt_id"],
                "payload": payload,
            }
        )
    return events


def run_data(repository: SQLiteRepository, run_id: str) -> dict[str, Any]:
    with repository.connect() as connection:
        run = connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if run is None:
            raise ValueError(f"run not found: {run_id}")
        tasks = connection.execute(
            "SELECT task_key,status,winner_attempt_id,verified_at FROM tasks WHERE run_id=? "
            "ORDER BY task_key",
            (run_id,),
        ).fetchall()
        decisions = connection.execute(
            "SELECT decision_type,signals,policy_version,timestamp FROM scheduler_decisions "
            "WHERE run_id=? ORDER BY timestamp",
            (run_id,),
        ).fetchall()
        attempts = connection.execute(
            "SELECT a.id,t.task_key,a.role,a.status,a.workspace_path,a.branch,a.started_at,a.finished_at "
            "FROM attempts a JOIN tasks t ON t.id=a.task_id WHERE t.run_id=? ORDER BY t.task_key,a.ordinal",
            (run_id,),
        ).fetchall()
        verifications = connection.execute(
            "SELECT v.attempt_id,t.task_key,v.verification_round,v.command_index,v.command_json,"
            "v.status,v.exit_code,v.started_at,v.finished_at,v.output_path FROM verification_runs v "
            "JOIN attempts a ON a.id=v.attempt_id JOIN tasks t ON t.id=a.task_id "
            "WHERE t.run_id=? ORDER BY t.task_key,a.ordinal,v.verification_round,v.command_index",
            (run_id,),
        ).fetchall()
        delivery = connection.execute(
            "SELECT * FROM deliveries WHERE run_id=?", (run_id,)
        ).fetchone()
        delivery_verifications = (
            connection.execute(
                "SELECT command_index,command_json,status,exit_code,started_at,finished_at,"
                "output_path FROM delivery_verification_runs WHERE delivery_id=? "
                "ORDER BY command_index",
                (delivery["id"],),
            ).fetchall()
            if delivery is not None
            else []
        )
        runtime_events = connection.execute(
            "SELECT e.sequence,e.type,e.attempt_id,e.payload,t.task_key "
            "FROM events e LEFT JOIN tasks t ON t.id=e.task_id "
            "WHERE e.run_id=? AND e.type IN ('worker.completed','worker.usage',"
            "'verifier.completed','delivery.verifier_completed') ORDER BY e.sequence",
            (run_id,),
        ).fetchall()
    usage_totals: dict[str, int] = {}
    usage_attempts: set[str] = set()
    latest_verifier_by_attempt: dict[str, dict[str, Any]] = {}
    delivery_evidence: dict[str, Any] | None = None
    for row in runtime_events:
        try:
            payload = json.loads(str(row["payload"]))
        except ValueError:
            continue
        if not isinstance(payload, dict):
            continue
        attempt_id = str(row["attempt_id"] or "")
        if row["type"] in {"worker.completed", "worker.usage"}:
            raw_usage = payload.get("usage")
            usage = raw_usage if isinstance(raw_usage, dict) else payload
            recorded = False
            for key, value in usage.items():
                if isinstance(value, int) and not isinstance(value, bool):
                    usage_totals[str(key)] = usage_totals.get(str(key), 0) + value
                    recorded = True
            if recorded and attempt_id:
                usage_attempts.add(attempt_id)
        if row["type"] == "verifier.completed" and attempt_id:
            latest_verifier_by_attempt[attempt_id] = {
                "sequence": int(row["sequence"]),
                "attempt_id": attempt_id,
                "task_key": row["task_key"],
                "passed": bool(payload.get("passed")),
                "verification_round": int(payload.get("verification_round", 1)),
                "changed_paths": [
                    str(item) for item in payload.get("changed_paths", []) if isinstance(item, str)
                ],
                "disallowed_paths": [
                    str(item)
                    for item in payload.get("disallowed_paths", [])
                    if isinstance(item, str)
                ],
                "diff_hash": str(payload.get("diff_hash") or ""),
            }
        if row["type"] == "delivery.verifier_completed":
            delivery_evidence = {
                "passed": bool(payload.get("passed")),
                "changed_paths": [
                    str(item) for item in payload.get("changed_paths", []) if isinstance(item, str)
                ],
                "disallowed_paths": [
                    str(item)
                    for item in payload.get("disallowed_paths", [])
                    if isinstance(item, str)
                ],
                "diff_hash": str(payload.get("diff_hash") or ""),
            }
    input_tokens = usage_totals.get("input_tokens", 0)
    output_tokens = usage_totals.get("output_tokens", 0)
    reported_total = usage_totals.get("total_tokens")
    if reported_total is None:
        reported_total = usage_totals.get("tokens", input_tokens + output_tokens)
    latest_verifiers = sorted(
        latest_verifier_by_attempt.values(), key=lambda item: int(item["sequence"])
    )
    changed_paths = sorted(
        {path for verification in latest_verifiers for path in verification["changed_paths"]}
    )
    disallowed_paths = sorted(
        {path for verification in latest_verifiers for path in verification["disallowed_paths"]}
    )
    if delivery_evidence is not None:
        changed_paths = sorted(
            set(changed_paths).union(str(path) for path in delivery_evidence["changed_paths"])
        )
        disallowed_paths = sorted(
            set(disallowed_paths).union(str(path) for path in delivery_evidence["disallowed_paths"])
        )
    try:
        policy_snapshot = json.loads(str(run["policy_snapshot"]))
    except ValueError:
        policy_snapshot = {}
    return {
        "run": dict(run),
        "tasks": [dict(row) for row in tasks],
        "attempts": [dict(row) for row in attempts],
        "verifications": [dict(row) for row in verifications],
        "delivery": (
            {
                **dict(delivery),
                "verifications": [dict(row) for row in delivery_verifications],
                "evidence": delivery_evidence,
            }
            if delivery is not None
            else None
        ),
        "decisions": [dict(row) for row in decisions],
        "summary": {
            "verified": sum(row["status"] == "verified" for row in tasks),
            "failed": sum(row["status"] in {"failed", "blocked"} for row in tasks),
            "hedges": sum(row["role"] == "hedge" for row in attempts),
            "delivery_verified": delivery is not None and delivery["status"] == "verified",
        },
        "usage": {
            "reported": bool(usage_totals),
            "attempts_reported": len(usage_attempts),
            "input_tokens": input_tokens,
            "cached_input_tokens": usage_totals.get("cached_input_tokens", 0),
            "output_tokens": output_tokens,
            "reasoning_output_tokens": usage_totals.get("reasoning_output_tokens", 0),
            "total_tokens": reported_total,
            "raw_totals": usage_totals,
        },
        "changes": {
            "changed_paths": changed_paths,
            "disallowed_paths": disallowed_paths,
            "latest_by_attempt": latest_verifiers,
        },
        "planning": policy_snapshot.get("planning"),
        "planning_metrics": planning_metrics(repository),
    }


def export_json(repository: SQLiteRepository, run_id: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(run_data(repository, run_id), indent=2), encoding="utf-8")
    return path


def export_csv(repository: SQLiteRepository, run_id: str, path: Path) -> Path:
    data = run_data(repository, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=["task_key", "status", "winner_attempt_id", "verified_at"]
        )
        writer.writeheader()
        writer.writerows(data["tasks"])
    return path


TEMPLATE = """<!doctype html><html><head><meta charset="utf-8"><title>FirstGreen {{ run.run.id }}</title>
<style>body{font-family:system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem;line-height:1.45}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:.5rem;text-align:left;vertical-align:top}.verified,.winner,.passed{color:#087830}.failed,.blocked{color:#b42318}code{font-size:.85em;overflow-wrap:anywhere}.summary{display:flex;gap:1.5rem;flex-wrap:wrap}.warning{color:#b42318}</style></head>
<body><h1>FirstGreen report</h1><p><code>{{ run.run.id }}</code> | <strong class="{{ run.run.status }}">{{ run.run.status }}</strong></p>
<div class="summary"><span>Verified: {{ run.summary.verified }}</span><span>Failed/blocked: {{ run.summary.failed }}</span><span>Attempts: {{ run.attempts|length }}</span><span>Hedges: {{ run.summary.hedges }}</span></div>
{% if run.usage.reported %}<h2>Worker usage</h2><p>Input: {{ run.usage.input_tokens }} | Cached input: {{ run.usage.cached_input_tokens }} | Output: {{ run.usage.output_tokens }} | Reasoning output: {{ run.usage.reasoning_output_tokens }} | Reported total: {{ run.usage.total_tokens }}</p>{% else %}<h2>Worker usage</h2><p>Not reported by this worker adapter.</p>{% endif %}
{% if run.planning %}<h2>Planning</h2><p>Decision: {{ run.planning.decision }} | Tasks: {{ run.planning.task_count }} | Wall time: {{ run.planning.planning_latency_seconds }}s | Estimated cost: {{ run.planning.planning_estimated_cost or 0 }}</p>{% endif %}
{% if run.delivery %}<h2>Final delivery</h2><p>Status: <strong class="{{ run.delivery.status }}">{{ run.delivery.status }}</strong> | Workspace: <code>{{ run.delivery.workspace_path or '' }}</code> | Base: <code>{{ run.delivery.base_sha }}</code></p>{% if run.delivery.error_kind %}<p class="warning">Failure kind: {{ run.delivery.error_kind }}</p>{% endif %}<table><tr><th>Command</th><th>Status</th><th>Exit</th></tr>{% for v in run.delivery.verifications %}<tr><td><code>{{ v.command_json }}</code></td><td class="{{ v.status }}">{{ v.status }}</td><td>{{ v.exit_code if v.exit_code is not none else '' }}</td></tr>{% endfor %}</table>{% endif %}
<h2>Tasks</h2><table><tr><th>Task</th><th>Status</th><th>Winner</th><th>Verified at</th></tr>
{% for task in run.tasks %}<tr><td>{{ task.task_key }}</td><td class="{{ task.status }}">{{ task.status }}</td><td>{{ task.winner_attempt_id or '' }}</td><td>{{ task.verified_at or '' }}</td></tr>{% endfor %}</table>
<h2>Attempts / timeline</h2><table><tr><th>Task</th><th>Role</th><th>Status</th><th>Workspace</th><th>Started</th></tr>
{% for a in run.attempts %}<tr><td>{{ a.task_key }}</td><td>{{ a.role }}</td><td>{{ a.status }}</td><td><code>{{ a.workspace_path }}</code></td><td>{{ a.started_at or '' }}</td></tr>{% endfor %}</table>
<h2>Verification</h2><table><tr><th>Task</th><th>Round</th><th>Command</th><th>Status</th><th>Exit</th></tr>
{% for v in run.verifications %}<tr><td>{{ v.task_key }}</td><td>{{ v.verification_round }}</td><td><code>{{ v.command_json }}</code></td><td class="{{ v.status }}">{{ v.status }}</td><td>{{ v.exit_code if v.exit_code is not none else '' }}</td></tr>{% endfor %}</table>
<h2>Changed files</h2>{% if run.changes.changed_paths %}<ul>{% for path in run.changes.changed_paths %}<li><code>{{ path }}</code></li>{% endfor %}</ul>{% else %}<p>No changed paths were reported by the verifier.</p>{% endif %}
{% if run.changes.disallowed_paths %}<p class="warning"><strong>Disallowed paths detected:</strong></p><ul class="warning">{% for path in run.changes.disallowed_paths %}<li><code>{{ path }}</code></li>{% endfor %}</ul>{% endif %}
<h2>Policy decisions</h2><table><tr><th>Time</th><th>Decision</th><th>Policy</th><th>Signals</th></tr>
{% for d in run.decisions %}<tr><td>{{ d.timestamp }}</td><td>{{ d.decision_type }}</td><td>{{ d.policy_version }}</td><td><code>{{ d.signals }}</code></td></tr>{% endfor %}</table></body></html>"""


def report_html(repository: SQLiteRepository, run_id: str, path: Path) -> Path:
    environment = Environment(autoescape=select_autoescape(default=True))
    rendered = environment.from_string(TEMPLATE).render(run=run_data(repository, run_id))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    return path
