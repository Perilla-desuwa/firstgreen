from pathlib import Path

import pytest
from pydantic import ValidationError

from firstgreen.config import Manifest, load_manifest
from firstgreen.scheduler.queue import ready_tasks
from firstgreen.simulator import simulate


def test_example_manifest_parses() -> None:
    manifest = load_manifest(Path("examples/fleet.yaml"))
    assert manifest.scheduler.ready_queue_policy == "stable"
    assert ready_tasks(manifest.tasks, set())[0].id == "issue-418"


def test_cycle_is_rejected() -> None:
    base = {
        "version": 1,
        "project": {"repo": "."},
        "scheduler": {"concurrency": {}},
        "agent_defaults": {},
        "verification_defaults": {},
        "workspace": {},
        "tasks": [
            {
                "id": "a",
                "prompt": "a",
                "dependencies": ["b"],
                "verify": {"commands": [{"argv": ["true"]}]},
            },
            {
                "id": "b",
                "prompt": "b",
                "dependencies": ["a"],
                "verify": {"commands": [{"argv": ["true"]}]},
            },
        ],
    }
    with pytest.raises(ValidationError, match="cycle"):
        Manifest.model_validate(base)


def test_empty_verifier_argv_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at least 1 item"):
        Manifest.model_validate(
            {
                "version": 1,
                "project": {"repo": "."},
                "scheduler": {"concurrency": {}},
                "agent_defaults": {},
                "verification_defaults": {},
                "workspace": {},
                "tasks": [
                    {
                        "id": "task",
                        "prompt": "task",
                        "verify": {"commands": [{"argv": []}]},
                    }
                ],
            }
        )


def test_simulation_is_reproducible() -> None:
    assert simulate(policy="single", seed=42) == simulate(policy="single", seed=42)
