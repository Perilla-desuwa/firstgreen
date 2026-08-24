# Controlled-live Ramsey v2 result

Status: complete and validated. All eight registered cells produced five verified task winners and
a separately verified final delivery.

## Scope

- Evaluated FirstGreen commit: `4a9a98954f952080196a042264b080794faaaa6c`.
- Frozen Manifest SHA-256:
  `75e1cb02c450ffa184c6093c6eadf726b3c0989415ed72bcf10e448355d12fd4`.
- Source base: `3121edac96345cb35a7bea74c3670071221a0e1f`.
- Worker: `gpt-5.6-luna`, low reasoning, no subagents, one attempt, no hedge.
- Graph: four independent shards followed by one certificate join; ready width four.
- Host: AMD Ryzen 7 7745HX, 16 logical processors, 63.69 GiB RAM, Windows 11,
  Python 3.12.13.
- Experiment date: 2026-08-18.

## Raw outcome

| Slots | Repeat 1 wall / speedup | Repeat 2 wall / speedup | Median wall | Root-slot utilization range |
|---:|---:|---:|---:|---:|
| 1 | 446.45 s / 1.00× | 560.13 s / 0.80× | 503.29 s | 99.3–99.5% |
| 2 | 263.05 s / 1.70× | 209.06 s / 2.14× | 236.06 s | 81.6–81.6% |
| 4 | 139.69 s / 3.20× | 167.28 s / 2.67× | 153.48 s | 57.2–58.7% |
| 8 | 170.08 s / 2.62× | 137.56 s / 3.25× | 153.82 s | 29.4–29.5% |

`T1` is the first valid one-slot cell (446.45 seconds), as registered before execution. The second
one-slot repetition remains visible and produces a 0.80× row against that baseline. The occasional
efficiency over 100% at two slots reflects remote latency variance against one fixed baseline, not
superlinear algorithmic speedup.

The main result is scoped but clear: the frozen live workload accelerated through four slots, while
the four- and eight-slot median wall times were nearly identical. At eight configured slots only
four branch tasks could be ready, and average active-agent count remained about 2.35; utilization
therefore fell to roughly half the four-slot value. More allocated capacity did not create more
application parallelism.

## Validation performed

- `raw.jsonl` has exactly the registered `(slots, repetition)` Cartesian set and one frozen hash.
- Rebuilt `summary.json` is byte-for-data equivalent to the eight append-only raw rows.
- Every SQLite run is `completed`; every cell has five verified tasks and five winner attempts.
- Every final delivery is `verified`, with all delivery verification commands passed at exit 0.
- Per-cell Manifest differences are limited to the registered repository clone/base and capacity
  fields.
- Launcher stderr is empty. No cell was discarded, imputed, or rerun under altered inputs.

Provider-side queue time and billable cost were unavailable and are not estimated. Two repetitions
are enough for a transparent personal-project demonstration, not for a population-level claim.

## Files

- `raw.jsonl` — sanitized append-only result rows.
- `slots-4-repeat-1.trace.json` — representative sanitized four-slot branch/join trace.
- `../../../publication/figures/ramsey-scaling.svg` — both raw repetitions plus the median.
- `../../../publication/figures/ramsey-efficiency.svg` — utilization and saturation.
- `../../../publication/figures/ramsey-trace.svg` — four roots, certificate join, and delivery.
- `../../controlled-live-ramsey-v2-runbook.md` — predeclared contract and full interpretation.

Regenerate both SVGs from the tracked journal:

```powershell
python scripts/render_publication_figures.py `
  docs/evidence/results/controlled-live-ramsey-v2/raw.jsonl `
  docs/publication/figures `
  --ramsey-trace docs/evidence/results/controlled-live-ramsey-v2/slots-4-repeat-1.trace.json
```
