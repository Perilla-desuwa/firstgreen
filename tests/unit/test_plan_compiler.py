from pathlib import Path

from firstgreen.config import DecompositionConfig, PlanningRiskConfig
from firstgreen.planning.compiler import can_auto_approve, compile_plan, write_overlap
from firstgreen.planning.models import (
    DecompositionDecision,
    PlannerProposal,
    ProposedTask,
    RepositoryFile,
    RepositoryMap,
)


def map_with_commands() -> RepositoryMap:
    return RepositoryMap(
        repo=Path("."),
        commit_sha="sha",
        files=[
            RepositoryFile(path="src/models/reset.py", kind="source"),
            RepositoryFile(path="src/auth/service.py", kind="source"),
            RepositoryFile(path="src/auth/routes.py", kind="source"),
            RepositoryFile(path="tests/test_reset.py", kind="test"),
        ],
        commands={"test": [["pytest"]]},
    )


def decomposition() -> DecompositionConfig:
    return DecompositionConfig(
        max_depth=1,
        max_tasks=5,
        minimum_expected_task_seconds=180,
        maximum_write_overlap=0.35,
        allow_single_task_fallback=True,
    )


def proposal(tasks: list[ProposedTask]) -> PlannerProposal:
    return PlannerProposal(
        planner_version="fake",
        decision=DecompositionDecision(
            recommended_parallelism=len(tasks),
            decision="decompose" if len(tasks) > 1 else "single_task",
            reason="test",
        ),
        tasks=tasks,
        call_count=1,
        input_tokens=None,
        output_tokens=None,
        estimated_cost=None,
        latency_seconds=0,
    )


def test_artifact_edges_and_conflicts_are_deterministic() -> None:
    result = compile_plan(
        "feature",
        proposal(
            [
                ProposedTask(
                    id="model",
                    objective="model",
                    produces=["schema"],
                    likely_paths=["src/models/reset.py"],
                    verification_hints=["model tests"],
                ),
                ProposedTask(
                    id="service",
                    objective="service",
                    requires=["schema"],
                    produces=["service"],
                    likely_paths=["src/auth/service.py"],
                    verification_hints=["service tests"],
                ),
                ProposedTask(
                    id="api",
                    objective="api",
                    produces=["api"],
                    requires=["service"],
                    likely_paths=["src/auth/routes.py"],
                    verification_hints=["api tests"],
                ),
            ]
        ),
        map_with_commands(),
        decomposition(),
        "key",
    )
    tasks = {task.id: task for task in result.tasks}
    assert tasks["service"].dependencies == ["model"]
    assert tasks["api"].dependencies == ["service"]
    assert result.validation.valid
    assert not result.conflicts


def test_workspace_task_receives_only_its_scoped_verifiers() -> None:
    repo_map = map_with_commands().model_copy(
        update={
            "files": [
                RepositoryFile(path="packages/adapter/src/index.ts", kind="source"),
                RepositoryFile(path="packages/ui/src/index.ts", kind="source"),
            ],
            "commands": {
                "setup": [["pnpm", "install", "--offline", "--frozen-lockfile"]],
                "test": [["pnpm", "run", "test"]],
                "test@packages/adapter": [["pnpm", "--dir", "packages/adapter", "run", "test"]],
                "typecheck@packages/adapter": [
                    ["pnpm", "--dir", "packages/adapter", "run", "typecheck"]
                ],
                "test@packages/ui": [["pnpm", "--dir", "packages/ui", "run", "test"]],
            },
        }
    )
    result = compile_plan(
        "adapter feature",
        proposal(
            [
                ProposedTask(
                    id="adapter",
                    objective="adapter",
                    produces=["adapter-output"],
                    likely_paths=["packages/adapter"],
                    verification_hints=["adapter tests"],
                )
            ]
        ),
        repo_map,
        decomposition(),
        "key",
    )

    assert result.tasks[0].verifier == [
        ["pnpm", "install", "--offline", "--frozen-lockfile"],
        ["pnpm", "--dir", "packages/adapter", "run", "test"],
        ["pnpm", "--dir", "packages/adapter", "run", "typecheck"],
    ]
    assert result.delivery_verifier == [
        ["pnpm", "install", "--offline", "--frozen-lockfile"],
        ["pnpm", "run", "test"],
    ]


def test_documentation_task_defers_full_repository_gates_to_delivery() -> None:
    repo_map = map_with_commands().model_copy(
        update={
            "files": [RepositoryFile(path="docs/usage.md", kind="docs")],
            "commands": {
                "test": [["pnpm", "run", "test"]],
                "typecheck": [["pnpm", "run", "typecheck"]],
            },
        }
    )
    result = compile_plan(
        "document usage",
        proposal(
            [
                ProposedTask(
                    id="docs",
                    objective="document usage",
                    produces=["usage-docs"],
                    likely_paths=["docs"],
                    verification_hints=["documentation checks"],
                )
            ]
        ),
        repo_map,
        decomposition(),
        "key",
    )

    assert result.tasks[0].verifier == [["git", "diff", "--check"]]
    assert result.delivery_verifier == [
        ["pnpm", "run", "test"],
        ["pnpm", "run", "typecheck"],
    ]


def test_python_dag_uses_local_compile_gate_before_terminal_full_suite() -> None:
    unittest = [
        "python",
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests",
        "-p",
        "test_*.py",
    ]
    repo_map = map_with_commands().model_copy(
        update={
            "files": [
                RepositoryFile(path="eom/backend/types.py", kind="source"),
                RepositoryFile(path="eom/checkpoint.py", kind="source"),
                RepositoryFile(path="tests/test_checkpoint.py", kind="test"),
            ],
            "commands": {"test": [unittest]},
        }
    )
    result = compile_plan(
        "add backend and checkpoint",
        proposal(
            [
                ProposedTask(
                    id="backend",
                    objective="backend",
                    produces=["backend-contract"],
                    likely_paths=["eom/backend"],
                ),
                ProposedTask(
                    id="checkpoint",
                    objective="checkpoint",
                    requires=["backend-contract"],
                    produces=["checkpoint"],
                    likely_paths=["eom/checkpoint.py"],
                ),
            ]
        ),
        repo_map,
        decomposition(),
        "key",
    )

    assert result.tasks[0].verifier[0][:2] == ["python", "-c"]
    assert result.tasks[0].verifier[0][-1] == "eom"
    assert "ast.parse" in result.tasks[0].verifier[0][2]
    assert result.tasks[0].verifier[1] == ["git", "diff", "--check"]
    assert result.tasks[1].verifier == [unittest]
    assert result.delivery_verifier == [unittest]


def test_new_python_files_receive_compile_gate_and_mixed_terminal_gets_full_suite() -> None:
    unittest = ["python", "-m", "unittest", "discover"]
    repo_map = map_with_commands().model_copy(
        update={
            "files": [RepositoryFile(path="README.md", kind="docs")],
            "commands": {"test": [unittest]},
        }
    )
    result = compile_plan(
        "create proofs",
        proposal(
            [
                ProposedTask(
                    id="proof",
                    objective="proof",
                    produces=["proof"],
                    likely_paths=["proofs/new_proof.py"],
                ),
                ProposedTask(
                    id="aggregate",
                    objective="aggregate",
                    requires=["proof"],
                    produces=["aggregate"],
                    likely_paths=["proofs/certificate.py", "README.md"],
                ),
            ]
        ),
        repo_map,
        decomposition(),
        "key",
    )

    assert result.tasks[0].verifier[0][:2] == ["python", "-c"]
    assert result.tasks[0].verifier[0][-1] == "proofs"
    assert "ast.parse" in result.tasks[0].verifier[0][2]
    assert result.tasks[0].verifier[1] == ["git", "diff", "--check"]
    assert result.tasks[1].verifier == [unittest]


def test_sibling_files_do_not_create_false_write_conflict() -> None:
    left = ProposedTask(id="a", objective="a", likely_paths=["src/auth/service.py"])
    right = ProposedTask(id="b", objective="b", likely_paths=["src/auth/routes.py"])
    assert write_overlap(left, right) == (0.0, None)


def test_overlap_without_artifacts_merges_tasks() -> None:
    left = ProposedTask(
        id="a", objective="a", likely_paths=["src/auth"], verification_hints=["test"]
    )
    right = ProposedTask(
        id="b", objective="b", likely_paths=["src/auth"], verification_hints=["test"]
    )
    assert write_overlap(left, right)[0] == 1
    result = compile_plan(
        "issue", proposal([left, right]), map_with_commands(), decomposition(), "key"
    )
    assert len(result.tasks) == 1
    assert result.validation.valid
    assert result.validation.repairs


def test_repeated_pairwise_conflicts_add_each_task_resource_once() -> None:
    result = compile_plan(
        "three-way integration",
        proposal(
            [
                ProposedTask(
                    id="left",
                    objective="left",
                    produces=["left-artifact"],
                    likely_paths=["src/auth/routes.py"],
                ),
                ProposedTask(
                    id="right",
                    objective="right",
                    produces=["right-artifact"],
                    likely_paths=["src/auth/routes.py"],
                ),
                ProposedTask(
                    id="integration",
                    objective="join",
                    produces=["verified-result"],
                    requires=["left-artifact", "right-artifact"],
                    likely_paths=["src/auth/routes.py"],
                ),
            ]
        ),
        map_with_commands(),
        decomposition(),
        "key",
    )

    assert len(result.conflicts) == 3
    assert all(task.resources == ["write:src/auth/routes.py"] for task in result.tasks)


def test_isolated_test_only_terminal_branch_falls_back_safely() -> None:
    result = compile_plan(
        "add a new workflow and tests",
        proposal(
            [
                ProposedTask(
                    id="implementation",
                    objective="implement the workflow",
                    produces=["workflow"],
                    likely_paths=["src/auth/service.py"],
                ),
                ProposedTask(
                    id="tests",
                    objective="add tests for the new workflow",
                    produces=["workflow-tests"],
                    likely_paths=["tests/test_reset.py"],
                ),
            ]
        ),
        map_with_commands(),
        decomposition(),
        "key",
    )

    assert len(result.tasks) == 1
    assert any("isolated test-only terminal branch" in item for item in result.validation.repairs)


def test_test_only_branch_is_valid_when_a_downstream_join_consumes_it() -> None:
    result = compile_plan(
        "add a new workflow and tests",
        proposal(
            [
                ProposedTask(
                    id="implementation",
                    objective="implement the workflow",
                    produces=["workflow"],
                    likely_paths=["src/auth/service.py"],
                ),
                ProposedTask(
                    id="tests",
                    objective="author tests from the contract",
                    produces=["workflow-tests"],
                    likely_paths=["tests/test_reset.py"],
                ),
                ProposedTask(
                    id="integration",
                    objective="integrate and verify the workflow",
                    produces=["verified-workflow"],
                    requires=["workflow", "workflow-tests"],
                    likely_paths=["src/auth/routes.py"],
                ),
            ]
        ),
        map_with_commands(),
        decomposition(),
        "key",
    )

    assert len(result.tasks) == 3
    assert result.validation.valid
    tests_task = next(task for task in result.tasks if task.id == "tests")
    assert tests_task.verifier[0][:2] == ["python", "-c"]


def test_missing_artifact_falls_back_safely() -> None:
    result = compile_plan(
        "issue",
        proposal(
            [
                ProposedTask(
                    id="consumer",
                    objective="consume",
                    requires=["missing"],
                    likely_paths=["src/auth/service.py"],
                    verification_hints=["test"],
                )
            ]
        ),
        map_with_commands(),
        decomposition(),
        "key",
    )
    assert len(result.tasks) == 1
    assert result.tasks[0].id == "request"
    assert result.validation.valid
    assert "fell back to one task" in result.validation.repairs


def test_single_task_fallback_covers_modules_but_excludes_instruction_files() -> None:
    repo_map = map_with_commands().model_copy(
        update={
            "files": [
                RepositoryFile(path="AGENTS.md", kind="docs"),
                RepositoryFile(path="apps/server/src/index.ts", kind="source"),
                RepositoryFile(path="packages/protocol/src/index.ts", kind="source"),
                RepositoryFile(path="package.json", kind="config"),
            ]
        }
    )
    result = compile_plan(
        "broad feature",
        proposal(
            [
                ProposedTask(
                    id="unsafe",
                    objective="broad feature",
                    likely_paths=[],
                    verification_hints=["repository tests"],
                )
            ]
        ),
        repo_map,
        decomposition(),
        "key",
    )

    assert result.tasks[0].likely_paths == ["apps", "package.json", "packages"]


def test_high_risk_plan_cannot_auto_approve() -> None:
    result = compile_plan(
        "migration",
        proposal(
            [
                ProposedTask(
                    id="migration",
                    objective="migration",
                    likely_paths=["src/models/reset.py"],
                    verification_hints=["test"],
                    risk_tags=["database-migration"],
                )
            ]
        ),
        map_with_commands(),
        decomposition(),
        "key",
    )
    risk = PlanningRiskConfig(require_manual_approval=["database-migration"])
    assert not can_auto_approve(result, risk, allow=True)


def test_repaired_plan_cannot_auto_approve() -> None:
    result = compile_plan(
        "bounded fallback",
        proposal(
            [
                ProposedTask(
                    id="unknown-write",
                    objective="edit an unknown file",
                    likely_paths=[],
                    verification_hints=["test"],
                )
            ]
        ),
        map_with_commands(),
        decomposition(),
        "key",
    )
    assert result.validation.valid
    assert result.validation.repairs
    assert not can_auto_approve(result, PlanningRiskConfig(), allow=True)


def test_artificial_artifact_cycle_is_repaired_by_merge() -> None:
    result = compile_plan(
        "cyclic proposal",
        proposal(
            [
                ProposedTask(
                    id="a",
                    objective="a",
                    produces=["a-artifact"],
                    requires=["b-artifact"],
                    likely_paths=["src/models/reset.py"],
                    verification_hints=["test"],
                ),
                ProposedTask(
                    id="b",
                    objective="b",
                    produces=["b-artifact"],
                    requires=["a-artifact"],
                    likely_paths=["src/auth/service.py"],
                    verification_hints=["test"],
                ),
            ]
        ),
        map_with_commands(),
        decomposition(),
        "key",
    )
    assert len(result.tasks) == 1
    assert result.validation.valid
    assert any("cycle" in repair for repair in result.validation.repairs)
