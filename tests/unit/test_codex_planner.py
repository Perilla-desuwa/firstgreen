import json
import subprocess
from pathlib import Path

import pytest

from firstgreen.planning.models import DecompositionDecision, PlannerProposal, RepositoryMap
from firstgreen.planning.planner import (
    CodexPlannerAdapter,
    StructuredPlannerAdapter,
    build_codex_planner_argv,
    build_planner_prompt,
    codex_strict_output_schema,
)


def test_codex_planner_builder_is_read_only_structured_and_reads_prompt_from_stdin() -> None:
    argv = build_codex_planner_argv(
        "compact prompt",
        Path("schema.json"),
        Path("result.json"),
        model="model-name",
        reasoning_effort="low",
    )
    assert argv[:8] == [
        "codex",
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--json",
        "--output-schema",
    ]
    assert "danger-full-access" not in argv
    assert argv[-1] == "-"
    assert "compact prompt" not in argv
    assert argv[argv.index("--model") + 1] == "model-name"
    assert "model_reasoning_effort=low" in argv


def test_planner_prompt_makes_parallelism_extraction_the_optimization_objective(
    tmp_path: Path,
) -> None:
    prompt = json.loads(
        build_planner_prompt(
            "Add a workflow across the model, service, and mailer.",
            RepositoryMap(repo=tmp_path, commit_sha="sha"),
            DecompositionDecision(
                recommended_parallelism=3,
                decision="decompose",
                reason="Several artifact boundaries are present.",
            ),
            5,
        )
    )

    objective = prompt["optimization_objective"]
    procedure = " ".join(prompt["parallelism_extraction_procedure"])
    assert "critical-path time" in objective
    assert prompt["parallelism_target"]["prepass_recommended_ready_width"] == 3
    assert "concrete data dependency" in prompt["parallelism_target"]["rule"]
    assert "true data dependencies" in procedure
    assert "integration or verification join" in procedure
    assert "Do not automatically serialize all tests" in procedure
    assert "cannot become independently green" in procedure
    assert "presumptive under-extraction" in procedure
    assert "audit exact likely-path ownership" in procedure
    assert "downstream integration join" in procedure
    assert "remove decorative edges" in procedure


def test_codex_planner_version_changes_when_extraction_policy_changes(tmp_path: Path) -> None:
    assert CodexPlannerAdapter(tmp_path).version == "codex-planner-v6"
    assert StructuredPlannerAdapter(lambda _: "{}").version == "structured-planner-v6"


def test_codex_schema_requires_every_declared_object_property() -> None:
    schema = codex_strict_output_schema(PlannerProposal.model_json_schema())

    def assert_strict(node: object) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                assert node["required"] == list(properties)
                assert node["additionalProperties"] is False
            for value in node.values():
                assert_strict(value)
        elif isinstance(node, list):
            for value in node:
                assert_strict(value)

    assert_strict(schema)


def test_codex_planner_uses_utf8_strict_schema_and_records_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        schema_path = Path(argv[argv.index("--output-schema") + 1])
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assert schema["required"] == list(schema["properties"])
        output_path = Path(argv[argv.index("-o") + 1])
        output_path.write_text(
            json.dumps(
                {
                    "planner_version": "model",
                    "decision": {
                        "recommended_parallelism": 1,
                        "decision": "single_task",
                        "reason": "one unit",
                        "relevant_paths": [],
                    },
                    "tasks": [
                        {
                            "id": "task",
                            "objective": "fix",
                            "produces": [],
                            "requires": [],
                            "likely_paths": [],
                            "verification_hints": [],
                            "risk_tags": [],
                            "uncertainty": None,
                            "read_only": False,
                        }
                    ],
                    "external_artifacts": [],
                    "call_count": 1,
                    "input_tokens": None,
                    "output_tokens": None,
                    "estimated_cost": None,
                    "latency_seconds": 0,
                }
            ),
            encoding="utf-8",
        )
        stdout = json.dumps(
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 123, "output_tokens": 45},
            }
        )
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    monkeypatch.setattr("firstgreen.planning.planner.subprocess.run", fake_run)
    proposal = CodexPlannerAdapter(
        tmp_path / "not-a-repository", binary="codex", model="gpt-5.6-luna"
    ).propose(
        "fix",
        RepositoryMap(repo=tmp_path, commit_sha="sha"),
        DecompositionDecision(
            recommended_parallelism=1,
            decision="single_task",
            reason="small",
        ),
        max_tasks=5,
    )

    argv = captured["argv"]
    kwargs = captured["kwargs"]
    assert isinstance(argv, list) and "--skip-git-repo-check" in argv and "--json" in argv
    assert isinstance(kwargs, dict)
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"
    assert isinstance(kwargs["input"], str)
    assert '"issue":"fix"' in kwargs["input"]
    environment = kwargs["env"]
    assert isinstance(environment, dict)
    assert environment["PYTHONUTF8"] == "1"
    assert environment["PYTHONIOENCODING"] == "utf-8"
    assert (proposal.input_tokens, proposal.output_tokens) == (123, 45)
