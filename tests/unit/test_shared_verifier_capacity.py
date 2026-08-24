import asyncio
from pathlib import Path

import pytest

from firstgreen.config import Manifest
from firstgreen.service import SchedulerService
from firstgreen.verifier.runner import CommandVerifier, VerificationCommand, VerificationResult
from firstgreen.workspace.git_worktree import Workspace


def manifest(slots: int) -> Manifest:
    return Manifest.model_validate(
        {
            "version": 1,
            "project": {"repo": "."},
            "scheduler": {
                "concurrency": {
                    "max_root": 2,
                    "initial_root": 2,
                    "total_agent_thread_budget": 2,
                    "verifier_slots": slots,
                }
            },
            "agent_defaults": {},
            "verification_defaults": {},
            "workspace": {},
            "tasks": [
                {
                    "id": "task",
                    "prompt": "task",
                    "verify": {"commands": [{"argv": ["true"]}]},
                }
            ],
        }
    )


def test_verifier_slots_are_shared_across_concurrent_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    active = 0
    maximum = 0

    async def fake_verify(self: CommandVerifier, request: object) -> VerificationResult:
        nonlocal active, maximum
        del self, request
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.03)
        active -= 1
        return VerificationResult(True, (), (), (), "hash")

    monkeypatch.setattr(CommandVerifier, "verify", fake_verify)
    configured = manifest(1)
    service = SchedulerService(tmp_path / "state")
    service._verifier_semaphore = asyncio.Semaphore(1)
    task = configured.tasks[0]
    command = (VerificationCommand(argv=("true",)),)

    async def exercise() -> None:
        workspaces = [
            Workspace(
                f"attempt-{index}",
                tmp_path / f"workspace-{index}",
                f"branch-{index}",
                tmp_path,
                "sha",
                "run",
                f"task-{index}",
                f"attempt-{index}",
            )
            for index in range(2)
        ]
        await asyncio.gather(
            *[
                service._verify_workspace(configured, task, workspace, command)
                for workspace in workspaces
            ]
        )

    asyncio.run(exercise())
    assert maximum == 1
    with service.repository.connect() as connection:
        events = connection.execute(
            "SELECT payload FROM events WHERE type='verifier.admitted' ORDER BY sequence"
        ).fetchall()
    assert len(events) == 2
