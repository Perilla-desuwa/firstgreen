# FirstGreen Repository-Aware Planning Subsystem

## Purpose

Users may submit an issue-sized natural-language engineering request instead of manually designing
a complete DAG. Planning produces either one executable task or a small validated DAG. It does not
manage product discovery, roadmaps, deployments, or recursive autonomous projects.

## Architecture and trust boundary

```text
Issue
  → read-only bounded RepositoryMap
  → deterministic single/decompose decision
  → optional one structured semantic planner call
  → deterministic artifact-edge compiler and conflict analyzer
  → validation, merge, or single-task fallback
  → human approval or low-risk policy approval
  → immutable Manifest for the existing scheduler
```

The planner may propose objectives, artifacts, likely paths, verification hints, risks, and
uncertainty. It never owns final edges, resource locks, safety, eligibility, approval, winner state,
or completion. The verifier remains the only source of truth for success.

## Modes

- `--plan none`: one execution task; no semantic decomposition call.
- `--plan auto`: scan, decide, optionally propose, compile, validate, display, approve, execute.
- Existing YAML/backlog: retained as authored and not unnecessarily replanned.

An effective parallelism of 1 is a valid planning result.

## Repository map

The MVP uses language-agnostic paths plus Python AST support for imports and route decorators. It
collects test relationships, pyproject/package commands, CODEOWNERS, limited Git co-change pairs,
and shared resource markers. File count and approximate token budgets truncate the map. Scanner
operations are read-only and the complete repository is never placed in the planner prompt.

## Compilation and validation

Artifact `produces/requires` relations become dependency edges. Write overlap becomes separate
capacity-one `write:<path>` resources, enforced by the scheduler. Import relations alone do not
serialize tasks. Compiler repairs artificial cycles and high-overlap boundaries by merging tasks.

Validation checks IDs, acyclicity, artifacts, executable verifiers, measurable outcomes, path
allow/deny rules, represented write conflicts, unknown dependencies, empty tasks, and the 1–5 task
bound. Failure falls back to one task when configured. There is no unbounded planner repair loop.

## Approval and editing

`firstgreen plan ISSUE --output plan.yaml` exports the candidate. Users may edit YAML and run
`firstgreen validate-plan plan.yaml`; validation always re-scans the pinned repository before
execution. `--approve-plan` only auto-approves valid low-risk plans. Migration, deployment,
security-policy, and external-side-effect tags require human review.

## Cost and caching

The cache key contains issue hash, commit SHA, planner version, model/configuration and path policy.
Ordinary retries and hedges reuse the compiled approved manifest. Planning wall time, tokens and
estimated cost are stored separately from execution. `--planner-budget 0` deterministically bypasses
the planner. Planning depth is 1 and ordinary maximum calls per issue is 1.

## CLI

```bash
firstgreen scan --repo .
firstgreen plan issue.md --repo . --output plan.yaml
firstgreen validate-plan plan.yaml
firstgreen run issue.md --plan none --repo .
firstgreen run issue.md --plan auto --repo .
firstgreen run issue.md --plan auto --approve-plan --repo .
firstgreen run plan.yaml --approve-plan
```

Fake planning is the credential-free default. A real single Codex planner call is explicit:

```bash
firstgreen plan issue.md --planner-provider codex --planner-model auto
```

## Deferred limitations

- Python analysis is heuristic, not compiler-grade symbol resolution.
- GitHub issue fetching is not included; exported issue/backlog files are accepted locally.
- `--repo-map-cache` is reserved but shared cross-process repo-map caching is not implemented.
- No automatic replan is performed yet; invalid boundaries are merged/fallbacked before execution.
- Predicted-vs-actual overlap/duration, realized parallelism, conflict rate and critical-path
  reduction remain null until execution attribution is linked across enough real runs.
- The live Codex planner test is opt-in and was not run in the current Windows environment.
