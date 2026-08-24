import os
from pathlib import Path

import pytest

from firstgreen.adapters.base import StartAttemptRequest
from firstgreen.adapters.codex_exec import CodexExecAdapter


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("FIRSTGREEN_RUN_LIVE_CODEX_TESTS") != "1",
    reason="set FIRSTGREEN_RUN_LIVE_CODEX_TESTS=1 to permit authenticated usage",
)
@pytest.mark.asyncio
async def test_authenticated_codex_smoke() -> None:
    adapter = CodexExecAdapter()
    doctor = await adapter.doctor()
    assert doctor.ok, doctor.message
    handle = await adapter.start(
        StartAttemptRequest(
            "live",
            "smoke",
            "attempt",
            "Inspect this repository and make no changes. Reply done.",
            Path.cwd(),
            120,
            {"sandbox": "workspace-write", "max_subagent_threads": 1},
        )
    )
    events = [event async for event in adapter.events(handle)]
    assert any(event.type == "worker.completed" for event in events)
