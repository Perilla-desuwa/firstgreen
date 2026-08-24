"""Semantic golden comparison without title or prose snapshots."""

from firstgreen.planning.compiler import can_auto_approve
from firstgreen.planning.models import CandidatePlan
from firstgreen.planning.workflow import default_planning_config
from firstgreen.testbed.models import GoldenCheck, GoldenExpectation


def _artifact_edges(plan: CandidatePlan) -> set[tuple[str, str]]:
    producers = {artifact: task.id for task in plan.tasks for artifact in task.produces}
    edges: set[tuple[str, str]] = set()
    for task in plan.tasks:
        for artifact in task.requires:
            if artifact in producers:
                edges.add((artifact, next(iter(task.produces), task.id)))
    return edges


def execution_allowed(plan: CandidatePlan) -> bool:
    risk = default_planning_config().risk
    return plan.validation.valid and not (
        plan.risk_level == "high"
        or any(tag in risk.require_manual_approval for task in plan.tasks for tag in task.risk_tags)
    )


def compare_golden(plan: CandidatePlan, golden: GoldenExpectation) -> GoldenCheck:
    violations: list[str] = []
    effective_decision = (
        "decompose_with_conflict"
        if plan.decision.decision == "decompose" and plan.conflicts
        else plan.decision.decision
    )
    allowed_decisions = set(golden.acceptable_decisions)
    if golden.decision:
        allowed_decisions.add(golden.decision)
    if allowed_decisions and effective_decision not in allowed_decisions:
        violations.append(f"decision {effective_decision!r} not in {sorted(allowed_decisions)}")
    effective_parallelism = (
        1
        if plan.conflicts and golden.forbid_concurrent_writes
        else plan.decision.recommended_parallelism
    )
    if golden.recommended_parallelism and not (
        golden.recommended_parallelism.min
        <= effective_parallelism
        <= golden.recommended_parallelism.max
    ):
        violations.append(f"recommended parallelism {effective_parallelism} outside golden range")
    if golden.task_count and not golden.task_count.min <= len(plan.tasks) <= golden.task_count.max:
        violations.append(f"task count {len(plan.tasks)} outside golden range")
    if golden.risk_level and plan.risk_level != golden.risk_level:
        violations.append(f"risk {plan.risk_level!r} != {golden.risk_level!r}")
    paths = {path for task in plan.tasks for path in task.likely_paths}
    for required in golden.required_paths:
        if required not in paths:
            violations.append(f"missing required path {required}")
    ids = {task.id for task in plan.tasks}
    for required in golden.required_semantic_tasks:
        if required not in ids:
            violations.append(f"missing semantic task {required}")
    dependencies = {
        (dependency, task.id) for task in plan.tasks for dependency in task.dependencies
    }
    for forbidden in golden.forbidden_edges:
        if forbidden in dependencies:
            violations.append(f"forbidden edge {forbidden}")
    if golden.required_final_barrier and not any(
        len(task.dependencies) >= 2 and "verification" in task.id for task in plan.tasks
    ):
        violations.append("missing final verification barrier")
    artifacts = {artifact for task in plan.tasks for artifact in task.produces}
    for required in golden.required_artifacts:
        if required not in artifacts:
            violations.append(f"missing artifact {required}")
    artifact_edges = _artifact_edges(plan)
    for relationship in golden.required_relationships:
        if relationship not in artifact_edges:
            violations.append(f"missing artifact relationship {relationship}")
    root_count = sum(not task.dependencies for task in plan.tasks)
    if golden.requires_parallel_branch and root_count < 2:
        violations.append("missing parallel branch")
    if golden.requires_join and not any(len(task.dependencies) >= 2 for task in plan.tasks):
        violations.append("missing dependency join")
    for resource in golden.required_conflict_resource:
        if not any(conflict.resource.startswith(resource) for conflict in plan.conflicts):
            violations.append(f"missing conflict resource {resource}")
    tags = {tag for task in plan.tasks for tag in task.risk_tags}
    for tag in golden.required_risk_tags:
        if tag not in tags:
            violations.append(f"missing risk tag {tag}")
    auto = can_auto_approve(plan, default_planning_config().risk, allow=True)
    if golden.requires_human_approval and auto:
        violations.append("mandatory human approval was bypassed")
    if golden.auto_approval is not None and auto != golden.auto_approval:
        violations.append(f"auto approval {auto} != {golden.auto_approval}")
    if execution_allowed(plan) != golden.execution_allowed:
        violations.append("execution eligibility differs from golden")
    for pattern in golden.forbidden_patterns:
        if any(pattern in task.id or pattern in task.objective for task in plan.tasks):
            violations.append(f"forbidden task pattern {pattern}")
    return GoldenCheck(passed=not violations, violations=violations)
