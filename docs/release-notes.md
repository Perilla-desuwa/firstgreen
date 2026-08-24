# Release notes

## 0.1.0-rc1 — HPC runtime candidate

This candidate is an HPC-inspired parallelism-extraction and agent-scheduling
runtime. Verification, transactional winners, and workspace isolation define valid completion;
they support the acceleration objective rather than replace it. The first frozen controlled-live
`1/2/4/8 × 2` scaling matrix is complete and remains an evidence path, not a separate product path.

The package remains an RC because the final evidence archive, public identity metadata, tag, and
remote CI confirmation are still release-owner gates. The frozen Python/JavaScript cases,
critical-path ablation, and primary public figures are complete.

- Added strict YAML DAG manifests and a local one-shot scheduler.
- Added fake and Codex Exec worker adapters with privacy-filtered JSONL ingestion.
- Added path-bounded Git worktrees and deterministic command/path verification.
- Added transactional first-verified winner arbitration.
- Added delayed-hedge thresholds, policy gates, simulator baselines, and AIMD concurrency control.
- Added JSON, CSV, and standalone HTML reports.
- Added fault, race, cleanup, restart, and opt-in live tests.

This is a development-codename release candidate. It performs no automatic merge, push, or deploy.

### Repository-aware planning extension

- Added read-only bounded repository maps with Python, test, CODEOWNERS and Git-history heuristics.
- Added single/decompose classification, fake and opt-in Codex structured planners, and result cache.
- Added deterministic artifact DAG compilation, conflict locks, merging, validation and fallback.
- Added terminal/YAML plan review, low-risk approval policy and natural-language issue run modes.
- Added planning persistence, cost/latency metrics and separate reporting.
- Added frozen work/span analysis, critical paths, ready width, exposed parallelism, duration
  provenance, and bounded root-slot recommendations to plan review and execution manifests.
- Added a production critical-path ready queue with stable fallback, persisted selection ranks, and
  service-wide verifier capacity with queue-wait events.
- Added resource-aware admission holds so conflicting ready tasks do not occupy root capacity while
  independent work is available, plus deterministic branch/join speedup acceptance coverage.
- Added sanitized Chrome/Perfetto trace export, utilization/accounting summaries, lifecycle events,
  and a thin frozen-Manifest scaling driver with append-only raw JSONL cells.
- Added bounded verifier-feedback repair attempts that reuse the approved plan and isolated failed
  workspace state.
- Published the frozen Ramsey `1/2/4/8 × 2` Luna matrix, a ready-queue policy ablation, a TinyShop
  negative extraction result, and one independent JavaScript verified-delivery case.
- Hardened planner invocation, repository command discovery, path matching, cancellation cleanup,
  and root/subagent thread admission.
