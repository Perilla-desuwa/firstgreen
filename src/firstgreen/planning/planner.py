"""Bounded semantic planner adapters and deterministic result caching."""

import hashlib
import json
import os
import re
import subprocess
import time
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from firstgreen.planning.models import (
    DecompositionDecision,
    PlannerProposal,
    ProposedTask,
    RepositoryMap,
)


class PlannerAdapter(Protocol):
    version: str

    def propose(
        self,
        issue: str,
        repo_map: RepositoryMap,
        decision: DecompositionDecision,
        *,
        max_tasks: int,
    ) -> PlannerProposal: ...


PlannerCall = Callable[[str], str]


def planner_cache_key(
    issue: str, commit_sha: str, planner_version: str, configuration: dict[str, object]
) -> str:
    payload = json.dumps(
        {
            "issue_hash": hashlib.sha256(issue.encode()).hexdigest(),
            "commit_sha": commit_sha,
            "planner_version": planner_version,
            "configuration": configuration,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def build_planner_prompt(
    issue: str, repo_map: RepositoryMap, decision: DecompositionDecision, max_tasks: int
) -> str:
    compact_map = repo_map.model_dump(mode="json")
    return json.dumps(
        {
            "optimization_objective": (
                "Minimize critical-path time to a scheduler-verified result by extracting the "
                "largest useful, safe, coarse-grained parallelism exposed by the repository and "
                "request. Coordination cost, write conflicts, and final integration still count."
            ),
            "parallelism_target": {
                "prepass_recommended_ready_width": decision.recommended_parallelism,
                "rule": (
                    "Treat the deterministic prepass width as a challenge to satisfy, not a value "
                    "to copy blindly. If the proposed artifact graph exposes less ready width, the "
                    "decision reason must identify the concrete data dependency, write conflict, "
                    "or startup-cost reason that eliminates each candidate branch. The fact that "
                    "one agent could implement the whole feature is not such a reason."
                ),
            },
            "parallelism_extraction_procedure": [
                (
                    "Derive concrete deliverable artifacts and their true data dependencies from "
                    "the acceptance criteria before grouping work by engineering discipline."
                ),
                (
                    "When decomposition is indicated, search explicitly for component-owned or "
                    "artifact-owned branches with disjoint write paths, followed by a bounded "
                    "integration or verification join when one is genuinely required."
                ),
                (
                    "Distinguish a true execution dependency from coordination convenience. A "
                    "shared contract described by the issue or existing code is not by itself a "
                    "dependency; require another task only when its repository changes are needed "
                    "before this task can start."
                ),
                (
                    "Do not automatically serialize all tests after all implementation. Tests may "
                    "be owned by the corresponding artifact task or independently authored from "
                    "the request and existing interfaces when their write paths do not conflict."
                ),
                (
                    "When implementation spans disjoint model, service, API, UI, adapter, message, "
                    "or documentation boundaries, attempt component-owned implementation tasks "
                    "before using one umbrella implementation task plus one trailing test task."
                ),
                (
                    "A test-only branch for behavior absent from the base revision cannot become "
                    "independently green in its isolated workspace. Assign focused tests to their "
                    "component task, or make verification/integration a downstream join that sees "
                    "the verified dependency changes. Never count an unverifiable test-only branch "
                    "as extracted parallelism."
                ),
                (
                    "When a decomposable feature crosses three or more source files or component "
                    "roles, treat one task owning every source path as presumptive "
                    "under-extraction. "
                    "Attempt a prerequisite artifact, independent consumer branches, and a final "
                    "integration owner. Keep the umbrella only when concrete coupling or "
                    "overlapping writes make those boundaries unsafe."
                ),
                (
                    "Before returning, audit exact likely-path ownership. Sibling tasks intended "
                    "to run concurrently must not claim the same writable file or an overlapping "
                    "ancestor directory. Assign a shared wiring path to exactly one branch or to "
                    "the downstream integration join; otherwise report the lower safe width."
                ),
                (
                    "Audit the proposed graph once: remove decorative edges, split an umbrella "
                    "implementation task when independent artifacts and paths exist, and retain "
                    "only parallel branches large enough to justify agent startup overhead."
                ),
            ],
            "instruction": (
                "Propose 1-5 semantic engineering work units. Avoid microtasks, duplicates, "
                "invented paths, speculative interfaces, and decorative dependencies. Identify "
                "artifacts, likely paths, verification hints, risks, and uncertainty. For work "
                "spanning several components, prefer separate artifact-owned tasks over one broad "
                "implementation task when the repository exposes disjoint write boundaries. "
                "Recommend one task when useful parallelism is absent; never invent concurrency "
                "merely to increase task count. Artifact identifiers are exact opaque strings; "
                "each must describe an independently consumable semantic deliverable rather than "
                "repeat a filename. Every requires entry must exactly match one produces entry or "
                "an external_artifact; "
                "do not use repository instruction files such as AGENTS.md as artifacts unless "
                "the issue explicitly asks to create them. Select likely_paths from the supplied "
                "repository map; use file symbols, imports, and test links to identify component "
                "boundaries, prefer the narrowest real file or directory boundary, and "
                "minimize sibling write overlap. Verification hints must identify the smallest "
                "relevant deterministic test or typecheck. Do not decide final DAG edges or "
                "safety approval."
            ),
            "max_tasks": max_tasks,
            "issue": issue,
            "decomposition_decision": decision.model_dump(mode="json"),
            "repository_map": compact_map,
        },
        separators=(",", ":"),
    )


class StructuredPlannerAdapter:
    """Validate one external structured planner call; never retries by default."""

    version = "structured-planner-v6"

    def __init__(self, call: PlannerCall) -> None:
        self.call = call
        self.calls = 0

    def propose(
        self,
        issue: str,
        repo_map: RepositoryMap,
        decision: DecompositionDecision,
        *,
        max_tasks: int,
    ) -> PlannerProposal:
        if self.calls >= 1:
            raise RuntimeError("planner call budget exhausted")
        self.calls += 1
        started = time.monotonic()
        raw = self.call(build_planner_prompt(issue, repo_map, decision, max_tasks))
        parsed = PlannerProposal.model_validate_json(raw)
        if len(parsed.tasks) > max_tasks:
            raise ValueError("planner exceeded maximum task count")
        return parsed.model_copy(
            update={"call_count": 1, "latency_seconds": time.monotonic() - started}
        )


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return result[:40] or "task"


class FakePlanner:
    """Deterministic semantic planner for tests and credential-free demos."""

    version = "fake-planner-v1"

    def propose(
        self,
        issue: str,
        repo_map: RepositoryMap,
        decision: DecompositionDecision,
        *,
        max_tasks: int,
    ) -> PlannerProposal:
        if decision.decision == "single_task":
            tasks = [
                ProposedTask(
                    id="issue",
                    objective=issue.strip(),
                    likely_paths=decision.relevant_paths,
                    verification_hints=["run repository verifier"],
                )
            ]
            return PlannerProposal(
                planner_version=self.version,
                decision=decision,
                tasks=tasks,
                call_count=0,
                input_tokens=None,
                output_tokens=None,
                estimated_cost=None,
                latency_seconds=0,
            )
        lowered = issue.lower()
        available = [file.path for file in repo_map.files]

        def mentions(*markers: str) -> bool:
            return any(marker in lowered for marker in markers)

        def matching(*markers: str) -> list[str]:
            matches = [
                path for path in available if any(marker in path.lower() for marker in markers)
            ]
            return matches[:8]

        candidates: list[ProposedTask] = []
        if mentions("schema", "model", "migration", "database", "数据库", "模型", "迁移", "字段"):
            candidates.append(
                ProposedTask(
                    id="data-model",
                    objective="Implement the required data model and persistence artifact.",
                    produces=["data-schema"],
                    likely_paths=matching("model", "migration", "schema"),
                    verification_hints=["run model and migration tests"],
                    risk_tags=["database-migration"]
                    if mentions("migration", "迁移", "数据库")
                    else [],
                )
            )
        if mentions("email", "mail", "template", "notification", "邮件", "模板", "通知"):
            candidates.append(
                ProposedTask(
                    id="email-artifact",
                    objective="Implement the email delivery or template artifact.",
                    produces=["email-delivery"],
                    likely_paths=matching("mail", "email", "template"),
                    verification_hints=["run email or snapshot tests"],
                )
            )
        if mentions("service", "behavior", "expiry", "expiration", "服务", "逻辑", "行为", "过期"):
            candidates.append(
                ProposedTask(
                    id="service-logic",
                    objective="Implement the core service behavior and business rules.",
                    produces=["service-behavior"],
                    requires=["data-schema"]
                    if any(t.id == "data-model" for t in candidates)
                    else [],
                    likely_paths=matching("service", "auth"),
                    verification_hints=["run service unit tests"],
                )
            )
        if mentions("api", "endpoint", "route", "controller", "接口", "端点", "路由", "控制器"):
            requires = [artifact for task in candidates for artifact in task.produces]
            candidates.append(
                ProposedTask(
                    id="api-layer",
                    objective="Expose the behavior through the requested API surface.",
                    produces=["api-behavior"],
                    requires=requires,
                    likely_paths=matching("route", "api", "controller"),
                    verification_hints=["run API integration tests"],
                )
            )
        if mentions("docs", "documentation", "readme", "文档", "说明", "使用指南"):
            candidates.append(
                ProposedTask(
                    id="documentation",
                    objective="Update user-facing documentation for the completed behavior.",
                    likely_paths=matching("docs", "readme"),
                    verification_hints=["run documentation checks"],
                )
            )
        if len(candidates) < 2:
            candidates = [
                ProposedTask(
                    id=_slug(issue[:30]),
                    objective=issue.strip(),
                    likely_paths=decision.relevant_paths,
                    verification_hints=["run repository verifier"],
                )
            ]
            decision = decision.model_copy(
                update={
                    "decision": "single_task",
                    "recommended_parallelism": 1,
                    "reason": "Semantic work units did not produce useful independent artifacts.",
                }
            )
        return PlannerProposal(
            planner_version=self.version,
            decision=decision,
            tasks=candidates[:max_tasks],
            call_count=1,
            input_tokens=None,
            output_tokens=None,
            estimated_cost=None,
            latency_seconds=0,
        )


class PlannerCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def load(self, key: str) -> PlannerProposal | None:
        path = self.root / f"{key}.json"
        if not path.is_file():
            return None
        try:
            return PlannerProposal.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def save(self, key: str, proposal: PlannerProposal) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{key}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(proposal.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)
        return path


def build_codex_planner_argv(
    prompt: str,
    schema_path: Path,
    output_path: Path,
    *,
    binary: str = "codex",
    model: str = "auto",
    reasoning_effort: str | None = None,
) -> list[str]:
    argv = [
        binary,
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--json",
        "--output-schema",
        str(schema_path),
        "-o",
        str(output_path),
    ]
    if model != "auto":
        argv.extend(["--model", model])
    if reasoning_effort is not None:
        argv.extend(["-c", f"model_reasoning_effort={reasoning_effort}"])
    # Prompts can exceed Windows' roughly 32K CreateProcess command-line limit for
    # large repository maps. Codex treats `-` as a request to read the prompt from
    # stdin, keeping argv bounded regardless of repository size.
    argv.append("-")
    return argv


def codex_strict_output_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return the strict object schema required by current Codex structured output."""

    result = deepcopy(schema)

    def visit(node: object) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                node["required"] = list(properties)
                node["additionalProperties"] = False
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(result)
    return result


def _codex_usage(stdout: str) -> tuple[int | None, int | None]:
    input_tokens: int | None = None
    output_tokens: int | None = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except (TypeError, ValueError):
            continue
        if not isinstance(event, dict) or event.get("type") != "turn.completed":
            continue
        usage = event.get("usage")
        if not isinstance(usage, dict):
            continue
        raw_input = usage.get("input_tokens")
        raw_output = usage.get("output_tokens")
        input_tokens = raw_input if isinstance(raw_input, int) else input_tokens
        output_tokens = raw_output if isinstance(raw_output, int) else output_tokens
    return input_tokens, output_tokens


class CodexPlannerAdapter:
    """Explicit opt-in, single-call Codex planner over a compressed repository map."""

    version = "codex-planner-v6"

    def __init__(
        self,
        work_dir: Path,
        *,
        binary: str = "codex",
        model: str = "auto",
        reasoning_effort: str | None = "medium",
        timeout_seconds: float = 180,
    ) -> None:
        self.work_dir = work_dir.resolve()
        self.binary = binary
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.timeout_seconds = timeout_seconds
        self.calls = 0

    def propose(
        self,
        issue: str,
        repo_map: RepositoryMap,
        decision: DecompositionDecision,
        *,
        max_tasks: int,
    ) -> PlannerProposal:
        if self.calls >= 1:
            raise RuntimeError("planner call budget exhausted")
        self.calls += 1
        self.work_dir.mkdir(parents=True, exist_ok=True)
        identifier = uuid4().hex
        schema_path = self.work_dir / f"{identifier}.schema.json"
        output_path = self.work_dir / f"{identifier}.result.json"
        schema_path.write_text(
            json.dumps(codex_strict_output_schema(PlannerProposal.model_json_schema()), indent=2),
            encoding="utf-8",
        )
        prompt = build_planner_prompt(issue, repo_map, decision, max_tasks)
        started = time.monotonic()
        try:
            environment = os.environ.copy()
            environment["PYTHONUTF8"] = "1"
            environment["PYTHONIOENCODING"] = "utf-8"
            result = subprocess.run(
                build_codex_planner_argv(
                    prompt,
                    schema_path,
                    output_path,
                    binary=self.binary,
                    model=self.model,
                    reasoning_effort=self.reasoning_effort,
                ),
                cwd=self.work_dir,
                capture_output=True,
                text=True,
                input=prompt,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=self.timeout_seconds,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"Codex planner failed with exit code {result.returncode}; "
                    "see local diagnostics"
                )
            proposal = PlannerProposal.model_validate_json(output_path.read_text(encoding="utf-8"))
            if len(proposal.tasks) > max_tasks:
                raise ValueError("planner exceeded maximum task count")
            input_tokens, output_tokens = _codex_usage(result.stdout)
            return proposal.model_copy(
                update={
                    "planner_version": self.version,
                    "call_count": 1,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "latency_seconds": time.monotonic() - started,
                }
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("Codex planner exceeded its bounded timeout") from error
        except OSError as error:
            raise RuntimeError(
                f"Codex planner local process failed ({type(error).__name__})"
            ) from error
        finally:
            schema_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)
