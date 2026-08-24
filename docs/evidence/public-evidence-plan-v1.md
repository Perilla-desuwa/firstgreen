# FirstGreen public evidence plan v1

Status: protocol-frozen and fully observed on 2026-08-18. Every E0--E6 cell has a result or an
explicitly retained negative/invalid outcome.

This document freezes the minimum public evidence set for FirstGreen as a personal HPC/AI-infra
project. It does not turn benchmark infrastructure into the product. The product claim remains
`repository + goal -> parallelism extraction -> scheduling -> verified delivery`.

## Freeze rules

1. Do not change a goal, plan, task graph, verifier, model, reasoning effort, policy, repetition
   count, or exclusion after inspecting an outcome.
2. A frozen input is identified by repository base/tree ID plus exact file or Manifest hash.
3. Failed, invalid, timeout, sequential, and conflict-limited outcomes are retained.
4. A contract correction receives a new experiment ID; old evidence is never overwritten.
5. Scripted, controlled-live, and end-to-end case-study results remain separate.
6. Only the Ramsey matrix may support the headline live strong-scaling claim.
7. TinyShop and JavaScript end-to-end runs support product-path claims, not population-level
   planner-quality or speedup claims.

## Frozen minimum set

| ID | Evidence question | Frozen execution | Status |
|---|---|---|---|
| E0 | Does runtime accounting expose capacity and saturation? | `scripted-branch-join`, slots `1/2/4/8/16` | complete |
| E1 | Can extraction refuse false parallelism and detect write conflicts? | TinyShop S1 and S4, planning-only | complete as testbed evidence |
| E2 | Can one natural-language goal become an executed branch/join delivery? | TinyShop S3, Luna, two slots, one run | complete as a negative extraction result: two serial tasks in both preserved observations; execution and delivery verified |
| E3 | Does a fixed live DAG strong-scale, and where does it saturate? | Ramsey v2, Luna, `1/2/4/8 x 2` | complete: 8/8 cells and deliveries verified |
| E4 | Does critical-path ordering improve a scheduler-sensitive DAG? | stable vs critical-path scripted pair, three runs each | complete: 6/6 verified; median wall 8.984 s vs 7.766 s (13.56% lower) |
| E5 | Does the product path transfer to an independent JavaScript repo? | idempotent-checkout v1, Luna, recommended slots capped at two, one run | complete: three tasks, ready width two, observed overlap, two verifier-driven repairs, and 9/9 final tests |
| E6 | Does verification prevent false completion? | retain TinyShop S3 iteration-one rejection and blocked join | complete historical failure evidence |

Targeted hedge and bounded-AIMD tests remain supporting correctness evidence. No live hedge,
always-race, AIMD, 16-slot, multi-model, or full policy Cartesian product is part of v1.

## Exact existing inputs

- Scripted capacity Manifest: `benchmarks/scripted-branch-join.yaml`, SHA-256
  `94E2D61A7AC95CA9050970FDD741D53072D64DE6984EDCB0C64DDB7E0E28432D`.
- TinyShop source tree: Git tree `776283b66abaa167ef972e853681f0f29b18ee75`.
- TinyShop planning inputs:
  - `tests/firstgreen_testbed_package/issues/S1_pagination_zero_bug.md`, SHA-256
    `8A3672653F053D88AA19194030E3FFB707F01BC5E608B8D6CEAA3113E1ED55CF`;
  - `tests/firstgreen_testbed_package/issues/S3_password_reset.md`, SHA-256
    `4B3611B8FF7BB30E39A05BCD0CAA4B538AE2F6B9F6F15FE49C5144EF60039DCC`;
  - `tests/firstgreen_testbed_package/issues/S4_audit_logging_conflict.md`, SHA-256
    `B42832C803194C22C4105BF1C972DC47E91B0E7617A006285F98E7DBA5B21E6C`.
- Ramsey v2: use the exact contract and Manifest hash recorded in
  `docs/evidence/controlled-live-ramsey-v2-runbook.md`.
- Critical-path pair:
  - `benchmarks/scripted-critical-path-stable.yaml`, SHA-256
    `D813BB22E1AD5EA2A61AFCFE5733A78A9FF0CCEBC9BD0ABC3DBC5F74A237AA1A`;
  - `benchmarks/scripted-critical-path.yaml`, SHA-256
    `A5C79FAD0EDF6A62644299A453C1D18A3CA96109F9763B37AED5FCC4BAB07157`.
- JavaScript case: use `docs/evidence/javascript-idempotent-checkout-v1.md`; candidate, approved
  Manifest, and runtime hashes are recorded there. The v1 run is complete and must not be
  overwritten.

## E2: TinyShop S3 Luna product-path run

- Experiment ID: `controlled-live-tinyshop-s3-luna-v1`.
- Input: frozen TinyShop tree and exact S3 issue above.
- Planner and workers: `gpt-5.6-luna`, reasoning `low`.
- Policy: `critical_path`, static two root slots.
- Maximum five tasks; planning depth one; bounded repairs; no worker subagents.
- Hedging disabled; timeout 900 seconds per attempt.
- Registered observation: one. A separately named retry was preserved after the original was
  mistakenly believed interrupted; both complete observations are reported and neither is used as
  a latency benchmark.
- Preserve planning rejection, verifier failure, blocked join, or failed delivery as the result.

The earlier S3 report used `gpt-5.6-sol` despite its historical filename. It may be reused as a
failure/correctness narrative but not mixed with Luna timing.

Both Luna observations produced the same two-task serial implementation-to-tests graph with ready
width one. Execution and final delivery verified in 184.719 s and 183.250 s respectively, but the
predeclared branch/join golden shape failed. This is the accepted negative extraction result.

## E3: Ramsey v2 flagship matrix

The Ramsey runbook is authoritative. Run `1/2/4/8 x 2` in its registered order with Luna, low
reasoning, no subagents, no hedge, and one attempt per task. Ready width is four, so the eight-slot
cell is an intentional saturation point. Do not add live 16 slots to v1.

## E4: critical-path ablation

The two Manifests must be byte-identical in task graph, estimates, fake latency, capacity,
verifiers, and delivery contract; only `scheduler.ready_queue_policy` differs.

- Capacity: two root slots and one verifier slot.
- Repetitions: three per policy.
- Stable policy is expected to admit `side-a` and `side-b` before `z-critical-1` because of the
  stable task-ID order.
- Critical-path policy is expected to admit `z-critical-1` immediately and advance
  `z-critical-2` before the join.
- Report actual order, makespan, utilization, and trace. If the expected makespan ordering does not
  appear, publish the negative result and inspect instrumentation; do not rename tasks.

This is deterministic policy evidence, not a claim about Codex latency.

The registered pair completed on commit `3c0a87122dc847e19d601b380d1ebea1d2a189cd`
with two root slots and the frozen one verifier slot. Stable order selected both side branches
before the long chain in all three runs. Critical-path order selected `z-critical-1` first in all
three runs and advanced `z-critical-2` before the remaining side branch in two. All six cells
verified five tasks and final delivery. The critical-path median wall time was 7.766 s versus
8.984 s for stable order, a 13.56% reduction on this scripted workload.

A pre-freeze smoke on 2026-08-18 verified all five tasks under both policies. The stable policy
selected `side-a`, `side-b`, then `z-critical-1`; the critical-path policy selected
`z-critical-1`, `side-a`, then `z-critical-2`. These smoke runs only validate that the workload is
scheduler-sensitive. They are not part of the registered three-per-policy result set.

## E5: independent JavaScript case

The design and acceptance contract are frozen in `javascript-idempotent-checkout-v1.md`. Its role
is to show language/repository portability with one public, standalone Node.js repository and one
end-to-end run. It receives no scaling matrix and no percentage headline.

The completed run extracted three tasks with two initially ready roots. Those roots started 9.5 ms
apart; two primary attempts were rejected by the verifier and succeeded through bounded repairs;
the composed delivery passed 9/9 tests in 289.085 s. This supports only the scoped portability and
product-path claim.

## Publication layout

README evidence order is frozen as:

1. product loop and one extracted-plan view;
2. Ramsey strong-scaling and efficiency figure;
3. one Ramsey runtime trace with saturation explanation;
4. TinyShop S1/S3/S4 extraction cards;
5. critical-path dispatch comparison;
6. JavaScript portability case;
7. historical verifier-rejection failure card;
8. reproduction commands, raw data, environment, limitations, and missing values.

The minimum public release is complete when E0-E6 have either an observed result or an explicitly
published failure/limitation, and E3 has no silently missing matrix cell.

All current live inputs can be checked without paid calls:

```powershell
.\scripts\controlled-live-ready.ps1
```
