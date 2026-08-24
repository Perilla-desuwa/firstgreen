import json
from pathlib import Path

import pytest

from firstgreen.testbed.loaders import (
    TESTBED_ROOT,
    FixtureError,
    load_candidate_fixture,
    load_golden,
    load_hedge_fixtures,
    load_issue,
    scenario_metadata,
    validate_json_schema,
)


def test_all_supplied_scenario_fixtures_parse() -> None:
    for scenario in ("S1", "S2", "S3", "S4", "S5", "S6"):
        assert load_issue(scenario).startswith("#")
        assert load_golden(scenario).scenario == scenario
    assert len(load_hedge_fixtures().scenarios) == 2
    assert load_candidate_fixture("cyclic_candidate_plan.json").tasks
    assert load_candidate_fixture("coordination_only_candidate_plan.json").tasks
    assert set(scenario_metadata()) == {"S1", "S2", "S3", "S4", "S5", "S6", "F1", "F2", "H1"}


def test_invalid_candidate_has_clear_schema_path(tmp_path: Path) -> None:
    root = tmp_path
    (root / "fakes").mkdir()
    (root / "schemas").mkdir()
    source_schema = TESTBED_ROOT / "schemas" / "candidate_plan.schema.json"
    (root / "schemas" / source_schema.name).write_text(
        source_schema.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (root / "fakes" / "invalid.json").write_text(
        json.dumps({"decision": "decompose", "recommended_parallelism": 2, "tasks": [{}]}),
        encoding="utf-8",
    )
    with pytest.raises(FixtureError, match=r"\$\.tasks\[0\].*missing required"):
        load_candidate_fixture("invalid.json", root)


def test_schema_validator_rejects_unknown_fields() -> None:
    schema = {
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
        "additionalProperties": False,
    }
    with pytest.raises(FixtureError, match="unknown fields"):
        validate_json_schema({"name": "ok", "extra": True}, schema)
