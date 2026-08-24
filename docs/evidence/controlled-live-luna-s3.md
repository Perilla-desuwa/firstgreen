# Controlled-live evidence: Luna S3

Date: 2026-08-15 (Asia/Shanghai)

This is a bounded product-path smoke test, not a benchmark result. It tests whether a plan
extracted by the locally configured Codex Luna model can be validated, scheduled as parallel
work, verified per task, joined, and delivered through FirstGreen's production runtime.

## Configuration

- Planner and workers: local Codex configuration `gpt-5.6-sol` (Luna)
- Reasoning effort: `low`
- Scenario: TinyShop S3 password-reset workflow
- Policy: static, two root slots
- Hedging: disabled
- Attempts: one per task
- Maximum approved tasks: five
- Timeout: 900 seconds per attempt
- Repository execution: clean temporary clone plus isolated worktrees

## Iteration 1

Luna extracted two independent root tasks and one integration join. The mailer root passed. The
token-lifecycle root passed its functional tests but failed the scheduler-owned Ruff gate on three
`datetime.UTC` findings, so the join correctly remained blocked and no delivery was produced.

Inspection also showed that the token worker had implemented a second mail-delivery abstraction.
The writable paths were isolated, but the semantic ownership boundary was not explicit enough in
the worker handoff. This led to two product changes:

1. each worker now receives bounded descriptions of peer tasks and is told not to implement peer
   deliverables;
2. the verifier commands rendered in the worker prompt are regenerated from the final manifest,
   so testbed overrides cannot leave stale verifier instructions.

## Iteration 2

The repeated end-to-end run produced three tasks:

1. password-reset core;
2. password-reset mailer;
3. application-flow join depending on both roots.

Observed result:

| Field | Result |
|---|---:|
| Planning validation | passed |
| Root tasks admitted concurrently | 2 |
| Maximum persisted attempt parallelism | 2 |
| Verified tasks | 3 / 3 |
| Attempts | 3 |
| Execution wall time | 213.719 s |
| Final delivery verification | passed |
| Hedged attempts | 0 |

The two roots overlapped from 19:56:37 UTC until the mailer completed at 19:58:16 UTC. The core
completed at 19:58:25 UTC, and the integration join started only afterward. The core winner changed
only its model/service/test paths; the mailer winner changed only its mailer/test paths, confirming
that the revised semantic ownership boundary prevented the earlier duplicate mail implementation.

The Codex CLI reported 410,610 input/output tokens across the three worker attempts. It did not
report a billable cost, so no cost is estimated here.

## Interpretation and limitation

This result closes the controlled-live correctness gate for two-way extracted parallelism. It does
not establish speedup: a matched one-slot replay and wider 4/8-slot workloads have not yet been run.

The testbed process returned a non-zero overall status because its semantic golden currently uses
canonical artifact identifiers such as `reset-token-schema`, while Luna emitted equivalent but
different identifiers such as `password-reset-core-api`. Planning validation, all task verifiers,
and final delivery nevertheless passed. This naming deviation is retained as a testbed limitation;
it is not relabeled as a passing golden comparison.
