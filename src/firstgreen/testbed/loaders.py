"""Load and validate testbed issues, goldens, fake plans, schemas and metadata."""

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from firstgreen.testbed.models import (
    CandidateFixture,
    GoldenExpectation,
    HedgeFixtures,
    ScenarioMetadata,
)

SOURCE_TESTBED_ROOT = Path(__file__).resolve().parents[3] / "tests" / "firstgreen_testbed_package"
PACKAGED_TESTBED_ROOT = Path(__file__).resolve().parent / "fixtures"
TESTBED_ROOT = SOURCE_TESTBED_ROOT if SOURCE_TESTBED_ROOT.is_dir() else PACKAGED_TESTBED_ROOT
TESTBED_REPORTS_ROOT = (
    SOURCE_TESTBED_ROOT / "reports"
    if SOURCE_TESTBED_ROOT.is_dir()
    else Path.cwd() / "firstgreen-testbed-reports"
)
TESTBED_RUNTIME_ROOT = (
    SOURCE_TESTBED_ROOT / ".runtime"
    if SOURCE_TESTBED_ROOT.is_dir()
    else Path.cwd() / ".firstgreen-testbed-runtime"
)


class FixtureError(ValueError):
    """A supplied testbed fixture is missing or violates its schema."""


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise FixtureError(f"cannot read fixture {path}: {error}") from error


def load_issue(scenario: str, root: Path = TESTBED_ROOT) -> str:
    matches = sorted((root / "issues").glob(f"{scenario}_*.md"))
    if len(matches) != 1:
        raise FixtureError(f"expected one issue fixture for {scenario}, found {len(matches)}")
    text = _read(matches[0]).strip()
    if not text:
        raise FixtureError(f"issue fixture is empty: {matches[0]}")
    return text


def load_golden(scenario: str, root: Path = TESTBED_ROOT) -> GoldenExpectation:
    path = root / "golden" / f"{scenario}.yaml"
    try:
        return GoldenExpectation.model_validate(yaml.safe_load(_read(path)))
    except (ValidationError, yaml.YAMLError) as error:
        raise FixtureError(f"invalid golden fixture {path}: {error}") from error


def load_json_schema(name: str, root: Path = TESTBED_ROOT) -> dict[str, Any]:
    path = root / "schemas" / name
    try:
        value = json.loads(_read(path))
    except json.JSONDecodeError as error:
        raise FixtureError(f"invalid JSON schema {path}: {error}") from error
    if not isinstance(value, dict) or value.get("type") != "object":
        raise FixtureError(f"schema {path} must describe an object")
    if not isinstance(value.get("required"), list) or not isinstance(value.get("properties"), dict):
        raise FixtureError(f"schema {path} requires required[] and properties")
    return value


def _types(value: Any, declared: str | list[str]) -> bool:
    names = [declared] if isinstance(declared, str) else declared
    checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    return any(name in checks and checks[name](value) for name in names)


def validate_json_schema(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    declared = schema.get("type")
    if declared is not None and not _types(value, declared):
        raise FixtureError(f"{path}: expected {declared}, got {type(value).__name__}")
    if "enum" in schema and value not in schema["enum"]:
        raise FixtureError(f"{path}: value {value!r} is not in enum")
    if isinstance(value, dict):
        required = schema.get("required", [])
        missing = [name for name in required if name not in value]
        if missing:
            raise FixtureError(f"{path}: missing required fields {missing}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                raise FixtureError(f"{path}: unknown fields {unknown}")
        for name, item in value.items():
            if name in properties:
                validate_json_schema(item, properties[name], f"{path}.{name}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise FixtureError(f"{path}: too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise FixtureError(f"{path}: too many items")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                validate_json_schema(item, item_schema, f"{path}[{index}]")
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        raise FixtureError(f"{path}: string is too short")
    if isinstance(value, int) and not isinstance(value, bool):
        if value < schema.get("minimum", value):
            raise FixtureError(f"{path}: value is below minimum")
        if value > schema.get("maximum", value):
            raise FixtureError(f"{path}: value is above maximum")


def load_candidate_fixture(name: str, root: Path = TESTBED_ROOT) -> CandidateFixture:
    path = root / "fakes" / name
    try:
        value = json.loads(_read(path))
        validate_json_schema(value, load_json_schema("candidate_plan.schema.json", root))
        return CandidateFixture.model_validate(value)
    except (json.JSONDecodeError, ValidationError) as error:
        raise FixtureError(f"invalid candidate fixture {path}: {error}") from error


def load_hedge_fixtures(root: Path = TESTBED_ROOT) -> HedgeFixtures:
    path = root / "fakes" / "hedge_scenarios.yaml"
    try:
        return HedgeFixtures.model_validate(yaml.safe_load(_read(path)))
    except (ValidationError, yaml.YAMLError) as error:
        raise FixtureError(f"invalid hedge fixture {path}: {error}") from error


def scenario_metadata(root: Path = TESTBED_ROOT) -> dict[str, ScenarioMetadata]:
    result: dict[str, ScenarioMetadata] = {}
    for scenario in ("S1", "S2", "S3", "S4", "S5", "S6"):
        issue = sorted((root / "issues").glob(f"{scenario}_*.md"))
        result[scenario] = ScenarioMetadata(
            id=scenario,
            issue_file=issue[0] if len(issue) == 1 else None,
            golden_file=root / "golden" / f"{scenario}.yaml",
            planning_only=scenario in {"S4", "S5", "S6"},
            fake_execution=scenario in {"S1", "S2", "S3"},
            destructive=scenario == "S6",
        )
    result["F1"] = ScenarioMetadata(
        id="F1", issue_file=None, golden_file=None, planning_only=True, fake_execution=False
    )
    result["F2"] = ScenarioMetadata(
        id="F2", issue_file=None, golden_file=None, planning_only=True, fake_execution=False
    )
    result["H1"] = ScenarioMetadata(
        id="H1", issue_file=None, golden_file=None, planning_only=False, fake_execution=True
    )
    return result
