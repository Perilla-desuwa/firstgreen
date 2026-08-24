import os
from pathlib import Path

import pytest

from firstgreen.planning.decomposition import decide_decomposition
from firstgreen.planning.models import RepositoryMap
from firstgreen.planning.planner import CodexPlannerAdapter


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("FIRSTGREEN_RUN_LIVE_CODEX_PLANNER_TESTS") != "1",
    reason="set FIRSTGREEN_RUN_LIVE_CODEX_PLANNER_TESTS=1 to permit one planner call",
)
def test_live_codex_planner_single_task(tmp_path: Path) -> None:
    repo_map = RepositoryMap(repo=Path.cwd(), commit_sha="live")
    issue = "Fix one local typo."
    decision = decide_decomposition(issue, repo_map)
    proposal = CodexPlannerAdapter(tmp_path).propose(issue, repo_map, decision, max_tasks=5)
    assert 1 <= len(proposal.tasks) <= 5
    assert proposal.call_count == 1
