import asyncio
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from firstgreen.db.repository import SQLiteRepository
from firstgreen.verifier.runner import CommandVerifier, VerificationCommand, VerificationRequest


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def repo(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-b", "main")
    git(path, "config", "user.email", "firstgreen@example.invalid")
    git(path, "config", "user.name", "FirstGreen Test")
    (path / "ok.txt").write_text("ok\n", encoding="utf-8")
    git(path, "add", ".")
    git(path, "commit", "-m", "base")
    return path, git(path, "rev-parse", "HEAD")


def test_agent_done_but_verifier_failure_is_not_green(tmp_path: Path) -> None:
    path, sha = repo(tmp_path)
    request = VerificationRequest(
        "a",
        path,
        sha,
        (
            VerificationCommand(
                argv=(sys.executable, "-c", "raise SystemExit(1)"), timeout_seconds=5
            ),
        ),
    )
    result = asyncio.run(CommandVerifier().verify(request))
    assert not result.passed


def test_output_cap_timeout_and_changed_path(tmp_path: Path) -> None:
    path, sha = repo(tmp_path)
    (path / "bad.txt").write_text("changed\n", encoding="utf-8")
    request = VerificationRequest(
        "a",
        path,
        sha,
        (VerificationCommand(argv=(sys.executable, "-c", "print('x' * 1000)"), timeout_seconds=5),),
        ("allowed/**",),
        20,
    )
    result = asyncio.run(CommandVerifier().verify(request))
    assert result.commands[0].output_truncated
    assert result.disallowed_paths == ("bad.txt",)
    assert not result.passed


def test_python_bytecode_caches_are_not_delivery_changes(tmp_path: Path) -> None:
    path, sha = repo(tmp_path)
    cache = path / "proofs" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "proof.cpython-310.pyc").write_bytes(b"generated")
    (path / "proofs" / "proof.py").write_text("VALUE = 1\n", encoding="utf-8")
    request = VerificationRequest(
        "a",
        path,
        sha,
        (VerificationCommand(argv=(sys.executable, "-c", "pass"), timeout_seconds=5),),
        ("proofs/proof.py",),
    )

    result = asyncio.run(CommandVerifier().verify(request))

    assert result.passed
    assert result.changed_paths == ("proofs/proof.py",)
    assert result.disallowed_paths == ()


def test_1000_way_winner_race_and_dependency_unlock(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "state.db")
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
        connection.execute(
            "INSERT INTO tasks(id,run_id,task_key,prompt,replay_safe,status) VALUES(?,?,?,?,?,?)",
            ("child", "r", "child", "p", 0, "queued"),
        )
        connection.execute(
            "INSERT INTO task_dependencies(task_id,dependency_id) VALUES('child','t')"
        )
        connection.executemany(
            "INSERT INTO attempts(id,task_id,ordinal,role,status,base_sha,config_snapshot) "
            "VALUES(?,?,?,?,?,?,?)",
            [(f"a{i}", "t", i, "primary", "passed", "sha", "{}") for i in range(1000)],
        )
    with ThreadPoolExecutor(max_workers=32) as pool:
        results = list(
            pool.map(lambda index: repository.claim_winner("t", f"a{index}", "later"), range(1000))
        )
    assert sum(results) == 1
    assert repository.unlock_dependencies("r") == ["child"]
