"""Deterministic DAG compilation, conflict analysis, merging, validation and fallback."""

import hashlib

from firstgreen.config import DecompositionConfig, PlanningRiskConfig
from firstgreen.path_patterns import path_matches
from firstgreen.planning.models import (
    CandidatePlan,
    ConflictConstraint,
    DecompositionDecision,
    PlannerProposal,
    PlanTask,
    PlanValidationResult,
    ProposedTask,
    RepositoryMap,
)
from firstgreen.planning.parallelism import analyze_parallelism, estimate_task_duration

_PYTHON_SYNTAX_CHECK = """\
import ast
import pathlib
import sys

paths = []
for raw in sys.argv[1:]:
    candidate = pathlib.Path(raw)
    paths.extend([candidate] if candidate.is_file() else sorted(candidate.rglob("*.py")))
for path in paths:
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
"""


def _normal(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def _looks_like_test_path(path: str) -> bool:
    normalized = _normal(path).lower()
    parts = normalized.split("/")
    name = parts[-1]
    return bool(
        {"test", "tests", "spec", "specs"} & set(parts[:-1])
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
        or name.endswith("_test.py")
    )


def _has_source_scope(task: PlanTask, repo_map: RepositoryMap) -> bool:
    for likely_path in task.likely_paths:
        normalized = _normal(likely_path)
        if _looks_like_test_path(normalized):
            continue
        if normalized.split("/", 1)[0].lower() in {"app", "src", "lib", "packages"}:
            return True
        if any(
            file.kind in {"source", "migration"}
            and _common_resource(file.path, normalized) is not None
            for file in repo_map.files
        ):
            return True
    return False


def _common_resource(left: str, right: str) -> str | None:
    a, b = _normal(left), _normal(right)
    if a == b:
        return a
    if a.startswith(b + "/"):
        return b
    if b.startswith(a + "/"):
        return a
    return None


def write_overlap(left: ProposedTask, right: ProposedTask) -> tuple[float, str | None]:
    left_paths = {_normal(path) for path in left.likely_paths}
    right_paths = {_normal(path) for path in right.likely_paths}
    if not left_paths or not right_paths or left.read_only or right.read_only:
        return 0.0, None
    overlaps: list[str] = []
    for first in left_paths:
        for second in right_paths:
            resource = _common_resource(first, second)
            if resource:
                overlaps.append(resource)
    denominator = max(1, len(left_paths | right_paths))
    return min(1.0, len(set(overlaps)) / denominator), min(overlaps) if overlaps else None


def _inherited_verifier(repo_map: RepositoryMap) -> list[list[str]]:
    result: list[list[str]] = []
    for category in ("setup", "test", "lint", "typecheck"):
        result.extend(repo_map.commands.get(category, []))
    return result


def _python_compile_verifier(task: ProposedTask, repo_map: RepositoryMap) -> list[list[str]]:
    roots: set[str] = set()
    for likely_path in task.likely_paths:
        normalized = _normal(likely_path)
        if not normalized:
            continue
        is_python = normalized.endswith(".py") or any(
            file.kind == "source"
            and file.path.endswith(".py")
            and _common_resource(file.path, normalized) is not None
            for file in repo_map.files
        )
        if is_python:
            roots.add(normalized.split("/", 1)[0])
    if not roots:
        return []
    return [
        ["python", "-c", _PYTHON_SYNTAX_CHECK, *sorted(roots)],
        ["git", "diff", "--check"],
    ]


def _task_verifier(
    task: ProposedTask, repo_map: RepositoryMap, *, terminal: bool
) -> list[list[str]]:
    scoped: list[list[str]] = list(repo_map.commands.get("setup", []))
    found_scope = False
    for category in ("test", "lint", "typecheck"):
        prefix = f"{category}@"
        for key, commands in sorted(repo_map.commands.items()):
            if not key.startswith(prefix):
                continue
            scope = key.removeprefix(prefix)
            if any(path_matches(path, f"{scope}/**") for path in task.likely_paths):
                scoped.extend(commands)
                found_scope = True
    if not found_scope:
        matched_kinds = {
            file.kind
            for file in repo_map.files
            if any(
                _common_resource(file.path, likely_path) is not None
                for likely_path in task.likely_paths
            )
        }
        has_planned_python = any(_normal(path).endswith(".py") for path in task.likely_paths)
        if matched_kinds and matched_kinds <= {"docs"} and not has_planned_python:
            return [["git", "diff", "--check"]]
        if not terminal and repo_map.commands.get("test"):
            compile_verifier = _python_compile_verifier(task, repo_map)
            if compile_verifier:
                return [*scoped, *compile_verifier]
        return _inherited_verifier(repo_map)
    return [command for index, command in enumerate(scoped) if command not in scoped[:index]]


def _plan_task(task: ProposedTask, dependencies: list[str], verifier: list[list[str]]) -> PlanTask:
    return PlanTask(
        id=task.id,
        objective=task.objective,
        produces=list(task.produces),
        requires=list(task.requires),
        likely_paths=list(task.likely_paths),
        verification_hints=list(task.verification_hints),
        risk_tags=list(task.risk_tags),
        uncertainty=task.uncertainty,
        read_only=task.read_only,
        dependencies=sorted(set(dependencies)),
        verifier=[list(command) for command in verifier],
        resources=[],
    )


def _cycle_nodes(tasks: list[PlanTask]) -> set[str]:
    graph = {task.id: task.dependencies for task in tasks}
    visiting: list[str] = []
    visited: set[str] = set()
    cycle: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            cycle.update(visiting[visiting.index(node) :])
            return
        if node in visited:
            return
        visiting.append(node)
        for dependency in graph.get(node, []):
            if dependency in graph:
                visit(dependency)
        visiting.pop()
        visited.add(node)

    for node in graph:
        visit(node)
    return cycle


def _merge_tasks(
    tasks: list[PlanTask], merge_ids: set[str], reason: str
) -> tuple[list[PlanTask], str]:
    selected = [task for task in tasks if task.id in merge_ids]
    if len(selected) < 2:
        return tasks, ""
    merged_id = "merged-" + hashlib.sha256("|".join(sorted(merge_ids)).encode()).hexdigest()[:8]
    internal_artifacts = {artifact for task in selected for artifact in task.produces}
    merged = PlanTask(
        id=merged_id,
        objective="; ".join(task.objective for task in selected),
        produces=sorted(internal_artifacts),
        requires=sorted(
            {item for task in selected for item in task.requires if item not in internal_artifacts}
        ),
        likely_paths=sorted({item for task in selected for item in task.likely_paths}),
        verification_hints=sorted({item for task in selected for item in task.verification_hints}),
        risk_tags=sorted({item for task in selected for item in task.risk_tags}),
        uncertainty="Merged deterministically because proposed boundaries were unsafe.",
        read_only=all(task.read_only for task in selected),
        dependencies=sorted(
            {item for task in selected for item in task.dependencies if item not in merge_ids}
        ),
        verifier=[
            command
            for index, command in enumerate(
                [command for task in selected for command in task.verifier]
            )
            if command not in [command for task in selected for command in task.verifier][:index]
        ],
        resources=sorted({item for task in selected for item in task.resources}),
        estimated_duration_seconds=round(
            sum(task.estimated_duration_seconds for task in selected), 3
        ),
        estimate_source="merged",
    )
    remaining: list[PlanTask] = []
    for task in tasks:
        if task.id in merge_ids:
            continue
        dependencies = [
            merged_id if dependency in merge_ids else dependency for dependency in task.dependencies
        ]
        remaining.append(task.model_copy(update={"dependencies": sorted(set(dependencies))}))
    remaining.append(merged)
    return sorted(remaining, key=lambda task: task.id), f"merged {sorted(merge_ids)}: {reason}"


def _path_known(path: str, repo_map: RepositoryMap) -> bool:
    normalized = _normal(path)
    known = [_normal(file.path) for file in repo_map.files]
    return any(
        item == normalized or item.startswith(normalized + "/") or normalized.startswith(item + "/")
        for item in known
    )


def validate_plan(
    tasks: list[PlanTask],
    conflicts: list[ConflictConstraint],
    repo_map: RepositoryMap,
    external_artifacts: list[str],
    *,
    max_tasks: int,
    allow_paths: tuple[str, ...] = (),
    deny_paths: tuple[str, ...] = (),
) -> PlanValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    ids = [task.id for task in tasks]
    if len(ids) != len(set(ids)):
        errors.append("task ids must be unique")
    if not tasks or len(tasks) > max_tasks:
        errors.append(f"plan must contain between 1 and {max_tasks} tasks")
    cycle = _cycle_nodes(tasks)
    if cycle:
        errors.append(f"dependency cycle: {sorted(cycle)}")
    producers: dict[str, str] = {}
    for task in tasks:
        for artifact in task.produces:
            if artifact in producers:
                errors.append(f"artifact {artifact!r} has multiple producers")
            producers[artifact] = task.id
    external = set(external_artifacts)
    depended_on = {dependency for task in tasks for dependency in task.dependencies}
    has_source_task = any(_has_source_scope(task, repo_map) for task in tasks)
    for task in tasks:
        normalized_objective = task.objective.strip().lower()
        coordination_only = (
            not task.produces
            and not task.likely_paths
            and any(
                phrase in normalized_objective
                for phrase in (
                    "think about the problem",
                    "coordinate the other agents",
                    "discuss possible solutions",
                )
            )
        )
        if not normalized_objective or coordination_only:
            errors.append(f"task {task.id} is empty or coordination-only")
        if not task.verifier and not task.verification_hints:
            errors.append(f"task {task.id} has no measurable completion condition")
        if not task.verifier:
            errors.append(f"task {task.id} has no executable verifier")
        if not task.read_only and not task.likely_paths:
            errors.append(f"write task {task.id} has no bounded likely paths")
        test_only_root = bool(task.likely_paths) and all(
            _looks_like_test_path(path) for path in task.likely_paths
        )
        if (
            test_only_root
            and not task.dependencies
            and task.id not in depended_on
            and has_source_task
        ):
            errors.append(
                f"task {task.id} is an isolated test-only terminal branch for new behavior; "
                "attach it to an implementation artifact or add a downstream integration join"
            )
        for artifact in task.requires:
            if artifact not in producers and artifact not in external:
                errors.append(f"task {task.id} requires missing artifact {artifact}")
        for dependency in task.dependencies:
            if dependency not in ids:
                errors.append(f"task {task.id} has unknown dependency {dependency}")
        for path in task.likely_paths:
            normalized = _normal(path)
            if deny_paths and any(path_matches(normalized, pattern) for pattern in deny_paths):
                errors.append(f"task {task.id} uses denied path {path}")
            if allow_paths and not any(
                path_matches(normalized, pattern) for pattern in allow_paths
            ):
                errors.append(f"task {task.id} is outside allowed paths: {path}")
            if not _path_known(path, repo_map):
                warnings.append(f"task {task.id} predicts unknown path {path}")
    conflict_pairs = {tuple(sorted((item.task_a, item.task_b))) for item in conflicts}
    for index, left in enumerate(tasks):
        for right in tasks[index + 1 :]:
            overlap, _ = write_overlap(left, right)
            if overlap and tuple(sorted((left.id, right.id))) not in conflict_pairs:
                errors.append(f"write conflict not represented: {left.id}, {right.id}")
    return PlanValidationResult(valid=not errors, errors=errors, warnings=warnings)


def _single_task_plan(
    issue: str,
    proposal: PlannerProposal,
    repo_map: RepositoryMap,
    cache_key: str,
    repairs: list[str],
) -> CandidatePlan:
    instruction_files = {"AGENTS.md", "CLAUDE.md", "CODEX.md"}
    repository_scope = {
        path.split("/", 1)[0] if "/" in path else path
        for file in repo_map.files
        if (path := _normal(file.path)) and path not in instruction_files
    }
    paths = sorted(repository_scope)
    verifier = _inherited_verifier(repo_map)
    task = PlanTask(
        id="request",
        objective=issue.strip(),
        produces=["request-result"],
        requires=[],
        likely_paths=paths,
        verification_hints=["run repository verifier"],
        risk_tags=sorted({tag for item in proposal.tasks for tag in item.risk_tags}),
        uncertainty=None,
        read_only=False,
        dependencies=[],
        verifier=verifier,
        resources=[],
    )
    validation = validate_plan([task], [], repo_map, [], max_tasks=1)
    validation = validation.model_copy(update={"repairs": repairs})
    decision = DecompositionDecision(
        recommended_parallelism=1,
        decision="single_task",
        reason="Deterministic validation selected the safer single-task fallback.",
        relevant_paths=paths,
    )
    return _candidate(issue, proposal, repo_map, cache_key, decision, [task], [], validation)


def _candidate(
    issue: str,
    proposal: PlannerProposal,
    repo_map: RepositoryMap,
    cache_key: str,
    decision: DecompositionDecision,
    tasks: list[PlanTask],
    conflicts: list[ConflictConstraint],
    validation: PlanValidationResult,
) -> CandidatePlan:
    risk_tags = {tag for task in tasks for tag in task.risk_tags}
    risk_level = (
        "high"
        if risk_tags
        & {
            "database-migration",
            "deployment",
            "destructive-schema-change",
            "external-side-effect",
            "security-policy",
        }
        else "medium"
        if risk_tags
        else "low"
    )
    analysis = analyze_parallelism(tasks)
    decision = decision.model_copy(
        update={"recommended_parallelism": analysis.recommended_root_slots}
    )
    return CandidatePlan(
        planner_version=proposal.planner_version,
        request=issue,
        request_hash=hashlib.sha256(issue.encode()).hexdigest(),
        repo=repo_map.repo,
        commit_sha=repo_map.commit_sha,
        repository_map_version=repo_map.version,
        decision=decision,
        tasks=tasks,
        parallelism_analysis=analysis,
        delivery_verifier=_inherited_verifier(repo_map),
        conflicts=conflicts,
        external_artifacts=proposal.external_artifacts,
        risk_level=risk_level,  # type: ignore[arg-type]
        validation=validation,
        approved=False,
        user_edited=False,
        cache_key=cache_key,
        planning_latency_seconds=proposal.latency_seconds,
        planning_input_tokens=proposal.input_tokens,
        planning_output_tokens=proposal.output_tokens,
        planning_estimated_cost=proposal.estimated_cost,
    )


def compile_plan(
    issue: str,
    proposal: PlannerProposal,
    repo_map: RepositoryMap,
    decomposition: DecompositionConfig,
    cache_key: str,
    *,
    allow_paths: tuple[str, ...] = (),
    deny_paths: tuple[str, ...] = (),
) -> CandidatePlan:
    producer = {artifact: task.id for task in proposal.tasks for artifact in task.produces}
    depended_on = {
        producer[required]
        for task in proposal.tasks
        for required in task.requires
        if required in producer
    }
    tasks = [
        estimate_task_duration(
            _plan_task(
                task,
                [producer[item] for item in task.requires if item in producer],
                _task_verifier(task, repo_map, terminal=task.id not in depended_on),
            ),
            minimum_seconds=decomposition.minimum_expected_task_seconds,
        )
        for task in proposal.tasks[: decomposition.max_tasks]
    ]
    for task in tasks:
        if any(word in task.id.lower() for word in ("integration", "verification")):
            task.dependencies.extend(item.id for item in tasks if item.id != task.id)
            task.dependencies = sorted(set(task.dependencies))
    repairs: list[str] = []
    cycle = _cycle_nodes(tasks)
    if cycle:
        tasks, repair = _merge_tasks(tasks, cycle, "artificial dependency cycle")
        if repair:
            repairs.append(repair)
    changed = True
    while changed:
        changed = False
        for index, left in enumerate(tasks):
            for right in tasks[index + 1 :]:
                overlap, _ = write_overlap(left, right)
                independent = bool(left.produces and right.produces)
                if overlap > decomposition.maximum_write_overlap and not independent:
                    tasks, repair = _merge_tasks(
                        tasks, {left.id, right.id}, "write overlap exceeds threshold"
                    )
                    repairs.append(repair)
                    changed = True
                    break
            if changed:
                break
    conflicts: list[ConflictConstraint] = []
    for index, left in enumerate(tasks):
        for right in tasks[index + 1 :]:
            overlap, resource = write_overlap(left, right)
            if overlap and resource:
                conflicts.append(
                    ConflictConstraint(
                        task_a=left.id,
                        task_b=right.id,
                        constraint="exclusive_write",
                        resource=resource,
                    )
                )
                resource_key = f"write:{resource}"
                if resource_key not in left.resources:
                    left.resources.append(resource_key)
                if resource_key not in right.resources:
                    right.resources.append(resource_key)
    validation = validate_plan(
        tasks,
        conflicts,
        repo_map,
        proposal.external_artifacts,
        max_tasks=decomposition.max_tasks,
        allow_paths=allow_paths,
        deny_paths=deny_paths,
    ).model_copy(update={"repairs": repairs})
    decision = proposal.decision
    if len(tasks) == 1:
        decision = decision.model_copy(
            update={"decision": "single_task", "recommended_parallelism": 1}
        )
    candidate = _candidate(
        issue, proposal, repo_map, cache_key, decision, tasks, conflicts, validation
    )
    if not validation.valid and decomposition.allow_single_task_fallback:
        return _single_task_plan(
            issue,
            proposal,
            repo_map,
            cache_key,
            [*repairs, *validation.errors, "fell back to one task"],
        )
    return candidate


def can_auto_approve(plan: CandidatePlan, risk: PlanningRiskConfig, allow: bool) -> bool:
    manual = set(risk.require_manual_approval)
    tags = {tag for task in plan.tasks for tag in task.risk_tags}
    return (
        allow
        and plan.validation.valid
        and not plan.validation.repairs
        and plan.risk_level == "low"
        and not tags & manual
    )
