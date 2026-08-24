# JavaScript idempotent-checkout controlled-live result

Status: completed and delivery-verified on 2026-08-18.

This is one end-to-end portability case, not a scaling benchmark. FirstGreen scanned an
independent Apache-2.0 Node.js repository, used `gpt-5.6-luna` to extract a three-task plan,
compiled and approved it, ran the production scheduler with two root slots, and verified one
composed delivery.

## Observed DAG and execution

```text
core idempotent checkout ──> focused tests ──┐
documentation ──────────────────────────────┼─> final delivery verification
```

The core and documentation attempts began 9.5 ms apart. Documentation verified after 55.1 s.
The core primary failed `node --test`, its bounded repair passed, and only then did the dependent
test task start. The test primary exposed another behavioral defect and failed; its bounded repair
passed. All three tasks became transactional winners and the final delivery passed 9/9 tests.

| Field | Observed value |
|---|---:|
| Planner / worker | `gpt-5.6-luna` medium / low |
| Planned tasks / ready width | 3 / 2 |
| Estimated work / span | 684 s / 486 s |
| Scheduler makespan | 289.085 s |
| Maximum observed agent parallelism | 2 |
| Root-slot utilization | 59.16% |
| Attempts | 5: 3 primary + 2 repair |
| Verified tasks / failed tasks | 3 / 0 |
| Final verification | 9/9 Node tests passed |
| Hedged attempts | 0 |

The first core attempt required the new key without updating the existing checkout test and was
rejected. The first test attempt then demonstrated that the current implementation did not reject
a missing key. These failed attempts were not counted as completed work; filtered verifier feedback
triggered one repair for each task. This is direct evidence for the verifier-owned completion
boundary, while the near-simultaneous root starts are evidence that the extracted parallelism was
actually scheduled.

## Frozen identity

- Evaluated FirstGreen commit: `834de42968614eca7f37a92ddf8c1399081fb6e3`.
- Source base: `59184e7b6ea77e6d6445b8544ef82edbe15e6996`.
- Issue SHA-256: `A4D8293373084A61DAE5234A0A210E8CCE774B2FB93778334C91CE9BCD95F64B`.
- Reviewed candidate SHA-256: `E2B7BA77AC0D8D3CC8B9CD36A1C5AE9EEA186C972634BCA08B82D7E6B4C61A89`.
- Frozen Manifest SHA-256: `D6213E5DB3B697B5D866DFCC65886A2A944AF7B6CB062A068A41B0C9D32DE9F3`.
- Persisted runtime Manifest hash: `557B0E9BB0B2BBC5008F0AC649768A4A8E7A7FCECF4630C58F828D506F1D0AFD`.

## Public files

- `summary.json`: path-free run summary used by the report.
- `attempts.csv`: verified task winners and timestamps.
- `trace.json`: sanitized Chrome/Perfetto trace with attempt, verifier, and delivery intervals.
- `delivery.diff`: final four-file delivered patch.

SHA-256 checksums:

```text
3835E8A372FDC966FA3C38D0BDA901A25433ACAD104EDDE2958B97BA2957E29D  attempts.csv
5FF7C81B542A8911878D12E4CE67D4B57728C878C0351529DCA6FF9A50C1019E  delivery.diff
096C971F378DCA350BD2411A7860FF1B198171ED15F2E9E0988D1537378C4EFA  trace.json
```

The local SQLite database, complete worktrees, prompts, reasoning, and raw agent messages are not
published. The reported token total is CLI telemetry, not a monetary cost; billable cost remains
unknown.
