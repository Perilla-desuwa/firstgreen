"""SQLite repository with WAL, foreign keys, append-only events and atomic winners."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol


class Repository(Protocol):
    def initialize(self) -> None: ...
    def claim_winner(self, task_id: str, attempt_id: str, now: str) -> bool: ...


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_migrations(version) VALUES (1);
CREATE TABLE IF NOT EXISTS runs(
 id TEXT PRIMARY KEY, manifest_hash TEXT NOT NULL, repo_path TEXT NOT NULL,
 base_sha TEXT NOT NULL, policy_snapshot TEXT NOT NULL, status TEXT NOT NULL,
 created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT);
CREATE TABLE IF NOT EXISTS tasks(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), task_key TEXT NOT NULL,
 prompt TEXT NOT NULL, replay_safe INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL,
 winner_attempt_id TEXT, verified_at TEXT, UNIQUE(run_id, task_key));
CREATE TABLE IF NOT EXISTS task_dependencies(
 task_id TEXT NOT NULL REFERENCES tasks(id), dependency_id TEXT NOT NULL REFERENCES tasks(id),
 PRIMARY KEY(task_id, dependency_id));
CREATE TABLE IF NOT EXISTS attempts(
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), ordinal INTEGER NOT NULL,
 role TEXT NOT NULL, status TEXT NOT NULL, base_sha TEXT NOT NULL, config_snapshot TEXT NOT NULL,
 workspace_path TEXT, branch TEXT, started_at TEXT, finished_at TEXT, UNIQUE(task_id, ordinal));
CREATE TABLE IF NOT EXISTS verification_runs(
 id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL REFERENCES attempts(id), command_index INTEGER NOT NULL,
 verification_round INTEGER NOT NULL DEFAULT 1,
 command_json TEXT NOT NULL, status TEXT NOT NULL, exit_code INTEGER, started_at TEXT, finished_at TEXT,
 output_path TEXT, UNIQUE(attempt_id, verification_round, command_index));
CREATE TABLE IF NOT EXISTS events(
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, run_id TEXT, task_id TEXT,
 attempt_id TEXT, type TEXT NOT NULL, timestamp TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TABLE IF NOT EXISTS scheduler_decisions(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL, task_id TEXT, attempt_id TEXT,
 decision_type TEXT NOT NULL, signals TEXT NOT NULL, policy_version TEXT NOT NULL,
 policy_snapshot TEXT NOT NULL, timestamp TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS resource_leases(
 id TEXT PRIMARY KEY, resource_key TEXT NOT NULL, owner_id TEXT NOT NULL,
 acquired_at TEXT NOT NULL, expires_at TEXT, released_at TEXT);
CREATE TABLE IF NOT EXISTS runtime_samples(
 id INTEGER PRIMARY KEY AUTOINCREMENT, repo_fingerprint TEXT NOT NULL, task_class TEXT NOT NULL,
 adapter TEXT NOT NULL, model TEXT NOT NULL, verifier_profile TEXT NOT NULL,
 duration_seconds REAL NOT NULL, outcome TEXT NOT NULL, censored INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS task_winners(
 task_id TEXT PRIMARY KEY REFERENCES tasks(id), attempt_id TEXT NOT NULL UNIQUE REFERENCES attempts(id));
CREATE TABLE IF NOT EXISTS deliveries(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE REFERENCES runs(id), status TEXT NOT NULL,
 workspace_path TEXT, branch TEXT, base_sha TEXT NOT NULL, diff_hash TEXT,
 created_at TEXT NOT NULL, verified_at TEXT, error_kind TEXT);
CREATE TABLE IF NOT EXISTS delivery_verification_runs(
 id TEXT PRIMARY KEY, delivery_id TEXT NOT NULL REFERENCES deliveries(id), command_index INTEGER NOT NULL,
 command_json TEXT NOT NULL, status TEXT NOT NULL, exit_code INTEGER, started_at TEXT, finished_at TEXT,
 output_path TEXT, UNIQUE(delivery_id, command_index));
CREATE TABLE IF NOT EXISTS planning_requests(
 id TEXT PRIMARY KEY, issue_hash TEXT NOT NULL, issue_text TEXT NOT NULL, repo_path TEXT NOT NULL,
 commit_sha TEXT NOT NULL, state TEXT NOT NULL, config_snapshot TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS repository_maps(
 id TEXT PRIMARY KEY, planning_request_id TEXT NOT NULL REFERENCES planning_requests(id),
 map_version TEXT NOT NULL, map_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS candidate_plans(
 id TEXT PRIMARY KEY, planning_request_id TEXT NOT NULL REFERENCES planning_requests(id),
 planner_version TEXT NOT NULL, cache_key TEXT NOT NULL, plan_json TEXT NOT NULL,
 approved INTEGER NOT NULL DEFAULT 0, user_edited INTEGER NOT NULL DEFAULT 0,
 planning_latency_seconds REAL NOT NULL DEFAULT 0, input_tokens INTEGER, output_tokens INTEGER,
 estimated_cost REAL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plan_validation_results(
 id TEXT PRIMARY KEY, candidate_plan_id TEXT NOT NULL REFERENCES candidate_plans(id),
 valid INTEGER NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL);
"""


class SQLiteRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate_verification_rounds(connection)
            self._migrate_deliveries(connection)

    @staticmethod
    def _migrate_verification_rounds(connection: sqlite3.Connection) -> None:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(verification_runs)").fetchall()
        }
        if "verification_round" in columns:
            connection.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (2)")
            return
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute("ALTER TABLE verification_runs RENAME TO verification_runs_v1")
            connection.execute(
                "CREATE TABLE verification_runs("
                "id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL REFERENCES attempts(id), "
                "command_index INTEGER NOT NULL, verification_round INTEGER NOT NULL DEFAULT 1, "
                "command_json TEXT NOT NULL, status TEXT NOT NULL, exit_code INTEGER, "
                "started_at TEXT, finished_at TEXT, output_path TEXT, "
                "UNIQUE(attempt_id, verification_round, command_index))"
            )
            connection.execute(
                "INSERT INTO verification_runs(id,attempt_id,command_index,verification_round,"
                "command_json,status,exit_code,started_at,finished_at,output_path) "
                "SELECT id,attempt_id,command_index,1,command_json,status,exit_code,started_at,"
                "finished_at,output_path FROM verification_runs_v1"
            )
            connection.execute("DROP TABLE verification_runs_v1")
            connection.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (2)")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    @staticmethod
    def _migrate_deliveries(connection: sqlite3.Connection) -> None:
        connection.executescript(
            "CREATE TABLE IF NOT EXISTS deliveries("
            "id TEXT PRIMARY KEY,run_id TEXT NOT NULL UNIQUE REFERENCES runs(id),"
            "status TEXT NOT NULL,workspace_path TEXT,branch TEXT,base_sha TEXT NOT NULL,"
            "diff_hash TEXT,created_at TEXT NOT NULL,verified_at TEXT,error_kind TEXT);"
            "CREATE TABLE IF NOT EXISTS delivery_verification_runs("
            "id TEXT PRIMARY KEY,delivery_id TEXT NOT NULL REFERENCES deliveries(id),"
            "command_index INTEGER NOT NULL,command_json TEXT NOT NULL,status TEXT NOT NULL,"
            "exit_code INTEGER,started_at TEXT,finished_at TEXT,output_path TEXT,"
            "UNIQUE(delivery_id,command_index));"
        )
        connection.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (3)")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def append_event(
        self,
        event_id: str,
        event_type: str,
        timestamp: str,
        payload: dict[str, Any],
        *,
        run_id: str | None = None,
        task_id: str | None = None,
        attempt_id: str | None = None,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO events(id,run_id,task_id,attempt_id,type,timestamp,payload) VALUES(?,?,?,?,?,?,?)",
                (event_id, run_id, task_id, attempt_id, event_type, timestamp, json.dumps(payload)),
            )

    def claim_winner(self, task_id: str, attempt_id: str, now: str) -> bool:
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE tasks SET winner_attempt_id=?,status='verified',verified_at=? "
                "WHERE id=? AND winner_attempt_id IS NULL AND status NOT IN ('cancelled','blocked')",
                (attempt_id, now, task_id),
            )
            if cursor.rowcount != 1:
                return False
            connection.execute(
                "INSERT INTO task_winners(task_id,attempt_id) VALUES(?,?)", (task_id, attempt_id)
            )
            connection.execute("UPDATE attempts SET status='winner' WHERE id=?", (attempt_id,))
            connection.execute(
                "UPDATE attempts SET status='superseded',finished_at=? "
                "WHERE task_id=? AND id<>? AND status IN ('passed','verifying','agent_completed')",
                (now, task_id, attempt_id),
            )
            return True

    def unlock_dependencies(self, run_id: str) -> list[str]:
        """Make queued tasks ready only when every dependency is verified."""
        with self.transaction() as connection:
            rows = connection.execute(
                "SELECT t.id FROM tasks t WHERE t.run_id=? AND t.status='queued' "
                "AND NOT EXISTS (SELECT 1 FROM task_dependencies d JOIN tasks p ON p.id=d.dependency_id "
                "WHERE d.task_id=t.id AND p.status<>'verified')",
                (run_id,),
            ).fetchall()
            ids = [str(row[0]) for row in rows]
            connection.executemany(
                "UPDATE tasks SET status='ready' WHERE id=?", [(item,) for item in ids]
            )
            return ids

    def add_runtime_sample(
        self,
        *,
        repo_fingerprint: str,
        task_class: str,
        adapter: str,
        model: str,
        verifier_profile: str,
        duration_seconds: float,
        outcome: str,
        censored: bool = False,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO runtime_samples(repo_fingerprint,task_class,adapter,model,"
                "verifier_profile,duration_seconds,outcome,censored) VALUES(?,?,?,?,?,?,?,?)",
                (
                    repo_fingerprint,
                    task_class,
                    adapter,
                    model,
                    verifier_profile,
                    duration_seconds,
                    outcome,
                    int(censored),
                ),
            )

    def runtime_samples(self, *, include_cancelled: bool = False) -> list[sqlite3.Row]:
        query = "SELECT * FROM runtime_samples WHERE censored=0"
        if not include_cancelled:
            query += " AND outcome<>'cancelled'"
        with self.connect() as connection:
            return list(connection.execute(query).fetchall())

    def record_decision(
        self,
        *,
        decision_id: str,
        run_id: str,
        decision_type: str,
        signals: dict[str, Any],
        policy_version: str,
        policy_snapshot: dict[str, Any],
        timestamp: str,
        task_id: str | None = None,
        attempt_id: str | None = None,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO scheduler_decisions(id,run_id,task_id,attempt_id,decision_type,"
                "signals,policy_version,policy_snapshot,timestamp) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    decision_id,
                    run_id,
                    task_id,
                    attempt_id,
                    decision_type,
                    json.dumps(signals, sort_keys=True),
                    policy_version,
                    json.dumps(policy_snapshot, sort_keys=True),
                    timestamp,
                ),
            )

    def reconcile_orphans(self, timestamp: str) -> dict[str, int]:
        """Conservatively terminalize work that a restarted process cannot reattach to."""
        with self.transaction() as connection:
            running = connection.execute(
                "UPDATE attempts SET status='orphaned',finished_at=? WHERE status='running'",
                (timestamp,),
            ).rowcount
            interrupted = connection.execute(
                "UPDATE attempts SET status='failed',finished_at=? "
                "WHERE status IN ('starting','verifying')",
                (timestamp,),
            ).rowcount
            failed_tasks = connection.execute(
                "UPDATE tasks SET status='failed' WHERE status IN ('running','verifying') "
                "AND winner_attempt_id IS NULL",
            ).rowcount
            released = connection.execute(
                "UPDATE resource_leases SET released_at=? WHERE released_at IS NULL AND owner_id IN "
                "(SELECT id FROM attempts WHERE status IN ('orphaned','failed','cancelled','superseded'))",
                (timestamp,),
            ).rowcount
        return {
            "orphaned_attempts": running,
            "interrupted_attempts": interrupted,
            "failed_tasks": failed_tasks,
            "released_leases": released,
        }

    def workspace_identity_matches(
        self, *, attempt_id: str, path: str, branch: str, base_sha: str
    ) -> bool:
        """Confirm cleanup identity against scheduler-owned persistence."""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT workspace_path,branch,base_sha FROM attempts WHERE id=?", (attempt_id,)
            ).fetchone()
        return row is not None and (
            str(row["workspace_path"]),
            str(row["branch"]),
            str(row["base_sha"]),
        ) == (path, branch, base_sha)
