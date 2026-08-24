import random
from pathlib import Path

from firstgreen.db.repository import SQLiteRepository


def seeded_repository(path: Path, attempts: int = 20) -> SQLiteRepository:
    repository = SQLiteRepository(path)
    repository.initialize()
    with repository.transaction() as connection:
        connection.execute(
            "INSERT INTO runs VALUES(?,?,?,?,?,?,?,NULL,NULL)",
            ("r", "h", ".", "sha", "{}", "running", "now"),
        )
        connection.execute(
            "INSERT INTO tasks(id,run_id,task_key,prompt,replay_safe,status) VALUES(?,?,?,?,?,?)",
            ("t", "r", "t", "p", 1, "verifying"),
        )
        connection.executemany(
            "INSERT INTO attempts(id,task_id,ordinal,role,status,base_sha,config_snapshot) "
            "VALUES(?,?,?,?,?,?,?)",
            [(f"a{i}", "t", i, "hedge", "passed", "sha", "{}") for i in range(attempts)],
        )
    return repository


def test_random_claim_order_never_changes_winner(tmp_path: Path) -> None:
    for seed in range(25):
        repository = seeded_repository(tmp_path / f"state-{seed}.db")
        order = list(range(20))
        random.Random(seed).shuffle(order)
        outcomes = [repository.claim_winner("t", f"a{index}", f"time-{index}") for index in order]
        assert outcomes.count(True) == 1
        repository.reconcile_orphans("restart")
        with repository.connect() as connection:
            winners = connection.execute("SELECT attempt_id FROM task_winners").fetchall()
            task = connection.execute(
                "SELECT status,winner_attempt_id FROM tasks WHERE id='t'"
            ).fetchone()
        assert len(winners) == 1
        assert task["status"] == "verified"
        assert task["winner_attempt_id"] == winners[0][0]
