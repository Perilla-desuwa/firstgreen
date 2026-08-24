# FirstGreen v0.1.0-rc1 — HPC-inspired coding-agent scheduler

FirstGreen turns a repository and engineering goal into a bounded, reviewable task DAG, then uses
critical-path-aware scheduling to execute isolated coding-agent work under explicit capacity. A
result counts only after scheduler-owned verification and final delivery.

## What this release demonstrates

- Parallelism extraction: work units, dependencies, conflicts, work/span, critical path, and slot
  recommendation.
- Scheduling: deterministic critical-path rank, resource-aware admission, bounded concurrency, and
  explainable traces.
- Completion boundary: isolated worktrees, scheduler-owned verification, transactional winner, and
  verified final delivery.
- Evidence: scripted capacity checks, a frozen controlled-live scaling matrix, a scheduler-policy
  ablation, and Python/JavaScript case studies.

## Headline result

On the frozen Ramsey workload using `gpt-5.6-luna`, median time to verified delivery changed from
503.29 seconds at one root slot to 153.48 seconds at four slots; the eight-slot median was 153.82
seconds, showing saturation at the DAG's ready width of four. Results are specific to the published
workload, model, host, and two-repetition protocol.

## Assets

- `firstgreen-0.1.0rc1-py3-none-any.whl`
- `firstgreen-0.1.0rc1.tar.gz`
- `firstgreen-evidence-0.1.0-rc1.zip`
- `firstgreen-evidence-0.1.0-rc1.zip.sha256`
- `firstgreen-technical-report-0.1.0-rc1.pdf`

## Reproduce and inspect

See `REPRODUCIBILITY.md` for the credential-free path, the opt-in live path, exact environment
requirements, and result-class definitions. The evidence archive is inspectable without a Codex
account or paid rerun.

## Important limits

This is a local development runtime, not a container security boundary. It does not auto-merge,
push, deploy, or perform irreversible external actions. Live results are specific to the published
workload, model, host, and experiment protocol.

Full changes are listed in `docs/release-notes.md`.
