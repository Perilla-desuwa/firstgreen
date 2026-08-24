# Controlled-live Ramsey v2 runbook

Status: completed and validated on 2026-08-18.

This experiment promotes the historical Ramsey sharded-proof workload into the current
FirstGreen runtime. Preparation does not start a Codex planner or worker.

## Frozen contract

- Experiment ID: `controlled-live-ramsey-v2`
- Source base: `3121edac96345cb35a7bea74c3670071221a0e1f`
- Frozen local Manifest: `.tmp/controlled-live-ramsey-v2/frozen.manifest.yaml`
- Manifest SHA-256: `75E1CB02C450FFA184C6093C6EADF726B3C0989415ED72BCF10E448355D12FD4`
- Worker model: locally configured Luna, `gpt-5.6-luna`
- Reasoning effort: `low`
- Root slots: `1,2,4,8`
- Repetitions: `2`
- Task graph: four independent shard roots followed by one certificate join
- Ready width: four; the 8-slot point is expected to expose saturation, not eight-way work
- Worker-internal subagents: disabled
- Attempts: one per task
- Hedging: disabled because the coding tasks are not replay-safe
- Timeout: 900 seconds per attempt
- Verification: scheduler-owned AST/diff checks per shard and full `unittest` delivery gate

The historical approved task definitions, dependencies, paths, artifacts, and verifiers are
unchanged. The current compiler regenerated worker prompts with peer ownership boundaries and the
current critical-path/admission metadata. Capacity is the only field changed by the scaling driver
between cells.

## Historical provenance

The source plan is the reviewed five-task plan from the 2026-08-12 Ramsey experiment. Historical
pilot data remain separate from v2 raw results:

- one slot: 444.587 seconds, verified delivery;
- two slots: 875.316 seconds, verified after one repair and therefore not a clean speedup cell;
- four slots: 200.891 seconds, verified delivery after two earlier failed four-slot runs.

These values motivate the workload and preserve negative evidence. They are not averaged into the
new matrix because the FirstGreen code version, reasoning effort, retry policy,
and result schema differ.

## Preflight without live workers

```powershell
.\scripts\controlled-live-ramsey.ps1
```

The preflight verifies the exact Manifest hash, clean source repository and base SHA, strict schema,
Codex CLI availability, and current free memory. It never starts a Codex worker without both the
`-Run` switch and the environment opt-in.

## Authorized launch

Run only after the owner confirms memory and live execution:

```powershell
$env:FIRSTGREEN_RUN_CONTROLLED_LIVE = "1"
.\scripts\controlled-live-ramsey.ps1 -Run
```

The output directory is `benchmark-results/controlled-live-ramsey-v2`. If it already exists, the
launcher stops instead of overwriting or silently resuming it. Preserve partial, failed, and invalid
cells; contract fixes require a new experiment ID.

## Acceptance and reporting

- Every successful cell must verify all five tasks and final delivery.
- Failed cells remain in the append-only raw journal and are not imputed.
- Speedup uses the first valid one-slot cell as `T1` under the current driver.
- The 8-slot point must be described as overprovisioned relative to ready width four.
- Missing provider queue time and billable cost remain missing, not estimated.
- After completion, export a sanitized runtime trace and publish raw JSONL, summary, figure,
  environment, failures, and the exact FirstGreen commit SHA.

## Observed result

All eight registered cells completed with five verified task winners and a separately verified
final delivery. The frozen Manifest hash was unchanged; per-cell Manifests varied only in the
registered clone/base and capacity fields.

| Slots | Repeat 1 wall / speedup | Repeat 2 wall / speedup | Median wall |
|---:|---:|---:|---:|
| 1 | 446.45 s / 1.00× | 560.13 s / 0.80× | 503.29 s |
| 2 | 263.05 s / 1.70× | 209.06 s / 2.14× | 236.06 s |
| 4 | 139.69 s / 3.20× | 167.28 s / 2.67× | 153.48 s |
| 8 | 170.08 s / 2.62× | 137.56 s / 3.25× | 153.82 s |

Speedup and efficiency use the first valid one-slot cell (446.45 seconds), exactly as frozen above;
the second one-slot result is not silently promoted to a new baseline. The nearly identical four-
and eight-slot medians show saturation at the graph's ready width of four. Root-slot utilization
was 57.2–58.7% at four slots and 29.4–29.5% at eight slots. Provider and network variance remains
visible across the two repetitions, so the public figure must show both raw points.

- Evaluated FirstGreen commit: `4a9a98954f952080196a042264b080794faaaa6c`.
- Host: AMD Ryzen 7 7745HX, 16 logical processors, 63.69 GiB RAM, Windows 11, Python 3.12.13.
- Raw public journal: `results/controlled-live-ramsey-v2/raw.jsonl`.
- No provider queue-time or billable-cost claim is made.
