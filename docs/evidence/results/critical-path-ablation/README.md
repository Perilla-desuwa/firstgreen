# Critical-path ready-queue ablation

Status: complete on 2026-08-18. All six registered cells verified five tasks and final delivery.

This deterministic experiment isolates one scheduler decision. Both Manifests contain the same
five-task DAG, duration estimates, fake-worker configuration, verifiers, two root slots, and one
declared verifier slot. Their frozen source differs only in
`scheduler.ready_queue_policy`: `stable` versus `critical_path`. The matrix runner sets verifier
capacity from the frozen Manifest in both policies, so the executed pair remains byte-equivalent
except for ready-queue policy.

| Policy | Wall times | Median wall | Median makespan | Median root-slot utilization |
|---|---:|---:|---:|---:|
| stable | 9.735 / 8.984 / 7.453 s | 8.984 s | 8.906 s | 42.32% |
| critical path | 7.766 / 6.140 / 8.344 s | 7.766 s | 7.682 s | 45.84% |

Critical-path ranking reduced median wall time by 13.56% in this scripted workload. This is a
causal scheduler-policy test, not evidence about live Codex latency.

## Dispatch evidence

The persisted `ready_queue_select` decisions were identical across all three repetitions within
each policy:

Stable selected `side-a -> side-b -> z-critical-1 -> z-critical-2 -> join` in all three runs.
Critical-path selected `z-critical-1` first in all three runs; it advanced `z-critical-2` before
`side-b` in two runs, while runtime completion order caused `side-b` to take the free slot first in
the third.

Stable order consumes the initial two slots with both short side branches. Critical-path order
admits `z-critical-1` immediately alongside `side-a`, allowing the dependent long-chain stage to
become ready earlier. Dynamic completion order still determines which ready task sees a free slot;
that does not change the initial policy choice or the dependency rule.

## Reproduction

```powershell
.\fg.ps1 benchmark scaling benchmarks/scripted-critical-path-stable.yaml `
  --slots 2 --repetitions 3 `
  --output-dir benchmark-results/critical-path-ablation/stable `
  --no-write-figure --preserve-verifier-slots

.\fg.ps1 benchmark scaling benchmarks/scripted-critical-path.yaml `
  --slots 2 --repetitions 3 `
  --output-dir benchmark-results/critical-path-ablation/critical `
  --no-write-figure --preserve-verifier-slots
```

Evaluated commit: `3c0a87122dc847e19d601b380d1ebea1d2a189cd`.

Frozen Manifest SHA-256:

- stable: `D813BB22E1AD5EA2A61AFCFE5733A78A9FF0CCEBC9BD0ABC3DBC5F74A237AA1A`;
- critical path: `A5C79FAD0EDF6A62644299A453C1D18A3CA96109F9763B37AED5FCC4BAB07157`.

## Retained protocol deviations

An initial three-cell stable invocation completed its scheduler runs and wrote raw rows, then
returned nonzero because the scaling-figure writer required a one-slot baseline. The raw rows are
retained in `stable-pre-export-fix.raw.jsonl`, but excluded from the paired statistic because no
critical-path cells ran under that exact command state. Commit `c7b9519` added the explicit
`--no-write-figure` fixed-capacity mode; both policies were then rerun from scratch on that commit.

A subsequent paired run completed with two verifier slots because the generic scaling driver
scaled verifier capacity with root capacity. Both policies were still symmetric, but that pair did
not match the predeclared one-verifier protocol. Its raw rows are retained under
`protocol-deviation-verifier2-*.raw.jsonl` and excluded. Commit `3c0a871` added
`--preserve-verifier-slots`; the reported pair is the first pair run from scratch with both
fixed-capacity controls.

Public files are sanitized and path-free. The median traces are the middle wall-time observations
for each policy. Local SQLite databases, cloned repositories, and full path-bearing reports are not
published.

SHA-256 checksums:

```text
2EC8BBDB1D471098C7400A7091FA303848310427F565217BC510E3044A07366B  critical.raw.jsonl
D8EC026937D7F403F1E3172E8E0E134767A66A4EAC6F55A342364840FC1C4DBD  critical-median.trace.json
D2FF1F1CAEC0AF849E53CA28C0B219A3688B3B61F7DC6535E622F080916586E3  stable.raw.jsonl
A54B23CE766DE73B9BB61795F20CEB8264AE383CDAE3F6BE283224DFA9291F43  stable-median.trace.json
25B2877EDB03338B8309D3A4820ADBAB84BF1E06720F16CE82FABCC304408EBC  stable-pre-export-fix.raw.jsonl
933864771B8615C7B6AFFEC571C5FE71A02A066560D0D03DBD9F742C1CBC2458  protocol-deviation-verifier2-critical.raw.jsonl
C6DE7E1EBF36DDDC965548100F4BF99418424CFA7E94042A6DA2F2441DABEA22  protocol-deviation-verifier2-stable.raw.jsonl
```
