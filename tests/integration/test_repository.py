import sqlite3
from pathlib import Path

import pytest

from firstgreen.db.repository import SCHEMA, SQLiteRepository


def seed(repository: SQLiteRepository) -> None:
    with repository.transaction() as connection:
        connection.execute(
            "INSERT INTO runs VALUES(?,?,?,?,?,?,?,NULL,NULL)",
            ("r", "h", ".", "sha", "{}", "running", "2026-01-01T00:00:00Z"),
        )
        connection.execute(
            "INSERT INTO tasks(id,run_id,task_key,prompt,replay_safe,status) VALUES(?,?,?,?,?,?)",
            ("t", "r", "task", "p", 1, "verifying"),
        )
        for ordinal in (1, 2):
            connection.execute(
                "INSERT INTO attempts(id,task_id,ordinal,role,status,base_sha,config_snapshot) "
                "VALUES(?,?,?,?,?,?,?)",
                (f"a{ordinal}", "t", ordinal, "primary", "passed", "sha", "{}"),
            )


def test_unique_constraints_and_atomic_winner(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "state.db")
    repository.initialize()
    seed(repository)
    assert repository.claim_winner("t", "a1", "2026-01-01T00:00:01Z")
    assert not repository.claim_winner("t", "a2", "2026-01-01T00:00:01Z")
    with repository.connect() as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("SELECT COUNT(*) FROM task_winners").fetchone()[0] == 1


def test_transaction_rollback_and_append_only(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "state.db")
    repository.initialize()
    with pytest.raises(RuntimeError), repository.transaction() as connection:
        connection.execute(
            "INSERT INTO events(id,type,timestamp,payload) VALUES('e','x','now','{}')"
        )
        raise RuntimeError("rollback")
    with repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    repository.append_event("e", "x", "now", {})
    repository.append_event("e", "x", "now", {})
    with repository.connect() as connection, pytest.raises(sqlite3.DatabaseError):
        connection.execute("DELETE FROM events")


def test_restart_reconciliation_is_idempotent(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "state.db")
    repository.initialize()
    seed(repository)
    with repository.transaction() as connection:
        connection.execute("UPDATE attempts SET status='running' WHERE id='a1'")
        connection.execute("UPDATE tasks SET status='running' WHERE id='t'")
        connection.execute(
            "INSERT INTO resource_leases(id,resource_key,owner_id,acquired_at) "
            "VALUES('l','test','a1','now')"
        )
    first = repository.reconcile_orphans("later")
    second = repository.reconcile_orphans("later-again")
    assert first["orphaned_attempts"] == 1
    assert first["released_leases"] == 1
    assert second["orphaned_attempts"] == 0
    assert second["released_leases"] == 0


def test_workspace_cleanup_identity_requires_database_match(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "state.db")
    repository.initialize()
    seed(repository)
    with repository.transaction() as connection:
        connection.execute(
            "UPDATE attempts SET workspace_path='root/run/a1',branch='firstgreen/a1' WHERE id='a1'"
        )
    assert repository.workspace_identity_matches(
        attempt_id="a1", path="root/run/a1", branch="firstgreen/a1", base_sha="sha"
    )
    assert not repository.workspace_identity_matches(
        attempt_id="a1", path="root/run/a2", branch="firstgreen/a1", base_sha="sha"
    )


def test_verification_round_migration_preserves_existing_audit_rows(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    old_schema = SCHEMA.replace(" verification_round INTEGER NOT NULL DEFAULT 1,\n", "").replace(
        "UNIQUE(attempt_id, verification_round, command_index)",
        "UNIQUE(attempt_id, command_index)",
    )
    with sqlite3.connect(path) as connection:
        connection.executescript(old_schema)
    repository = SQLiteRepository(path)
    seed(repository)
    with repository.transaction() as connection:
        connection.execute(
            "INSERT INTO verification_runs(id,attempt_id,command_index,command_json,status) "
            "VALUES('v1','a1',0,'{}','failed')"
        )

    repository.initialize()

    with repository.transaction() as connection:
        preserved = connection.execute(
            "SELECT verification_round,status FROM verification_runs WHERE id='v1'"
        ).fetchone()
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        connection.execute(
            "INSERT INTO verification_runs(id,attempt_id,command_index,verification_round,"
            "command_json,status) VALUES('v2','a1',0,2,'{}','passed')"
        )
    assert preserved is not None and tuple(preserved) == (1, "failed")
    assert [row[0] for row in versions] == [1, 2, 3]
