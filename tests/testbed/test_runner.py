import json
from pathlib import Path

import pytest

from firstgreen.testbed.loaders import load_json_schema, validate_json_schema
from firstgreen.testbed.run import main


def test_fake_runner_generates_valid_reports(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    result = main(
        [
            "--scenario",
            "S1",
            "--fake-planner",
            "--fake-worker",
            "--reports-dir",
            str(reports),
            "--runtime-dir",
            str(tmp_path / "runtime"),
        ]
    )
    assert result == 0
    assert (reports / "summary.md").is_file()
    assert (reports / "plans/S1.yaml").is_file()
    assert (reports / "timelines/S1.json").is_file()
    records = (reports / "results.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(records) == 1
    validate_json_schema(json.loads(records[0]), load_json_schema("result_record.schema.json"))


@pytest.mark.parametrize(
    "argv",
    [
        ["--scenario", "all", "--live-planner"],
        ["--scenario", "all", "--live-coding"],
        ["--scenario", "S4", "--live-coding"],
        ["--scenario", "F1", "--live-planner"],
    ],
)
def test_live_modes_require_one_allowed_scenario(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        main(argv)


def test_paid_live_coding_requires_model_and_task_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIRSTGREEN_RUN_LIVE_TESTBED_CODING", "1")
    monkeypatch.delenv("FIRSTGREEN_LIVE_MODEL", raising=False)
    with pytest.raises(SystemExit, match="explicit --model"):
        main(["--scenario", "S2", "--live-coding"])
    with pytest.raises(SystemExit, match="--max-live-tasks"):
        main(["--scenario", "S2", "--live-coding", "--model", "test-model"])


def test_live_flag_without_environment_opt_in_records_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FIRSTGREEN_RUN_LIVE_TESTBED_CODING", raising=False)
    reports = tmp_path / "reports"
    result = main(
        [
            "--scenario",
            "S2",
            "--live-coding",
            "--reports-dir",
            str(reports),
            "--runtime-dir",
            str(tmp_path / "runtime"),
        ]
    )
    record = json.loads((reports / "results.jsonl").read_text(encoding="utf-8"))
    assert result == 0
    assert record["live_coding"] == "skipped"
    assert record["execution"] is None


def test_live_task_cap_blocks_before_codex_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FIRSTGREEN_RUN_LIVE_TESTBED_CODING", "1")
    reports = tmp_path / "reports"
    result = main(
        [
            "--scenario",
            "S2",
            "--live-coding",
            "--model",
            "test-model",
            "--max-live-tasks",
            "1",
            "--reports-dir",
            str(reports),
            "--runtime-dir",
            str(tmp_path / "runtime"),
        ]
    )
    record = json.loads((reports / "results.jsonl").read_text(encoding="utf-8"))
    assert result == 1
    assert record["live_coding"] == "ran"
    assert record["execution"]["attempt_count"] == 0
    assert any("worker execution failed" in item for item in record["golden_check"]["violations"])
