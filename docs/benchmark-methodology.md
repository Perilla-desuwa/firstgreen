# Benchmark methodology

FirstGreen benchmarks are evidence consumers of the production runtime. They do not own a second
task model, DAG compiler, scheduler, verifier, or winner path.

## Frozen input

Each matrix accepts one reviewed Manifest compiled from an approved plan or authored through the
same strict schema. The driver hashes and re-parses the exact bytes before execution. Across cells
it may change only root/thread/verifier capacity; task IDs, prompts, dependencies, resources,
duration snapshot, worker configuration, and verifier commands stay fixed.

By default, verifier capacity scales with root capacity. Fixed-capacity policy ablations use
`--preserve-verifier-slots` so the frozen Manifest value remains unchanged, and
`--no-write-figure` when no one-slot speedup baseline exists.

## Raw journal and summary

Every completed cell appends one `scaling-cell-v1` JSON object to `raw.jsonl`. Existing rows are
never rewritten. `summary.json` is a rebuildable convenience view. Each row records the frozen
Manifest hash, slots, repetition, run ID, wall time, speedup, efficiency, outcome, and runtime
accounting reconstructed from that cell's SQLite database.

`T1` is the first valid one-slot cell. For a valid `N`-slot cell, `S_N = T1 / T_N` and
`E_N = S_N / N`. Missing or failed cells remain missing/failed; they are not imputed.

## Result classes

- `scripted`: deterministic/fake worker input with real scheduler, worktree, verifier, database,
  delivery, and trace paths. This validates orchestration and capacity accounting only.
- `controlled-live`: authenticated Codex workers on a frozen approved plan. This is the only class
  that can support a live coding-speed claim.
- `invalid`: the frozen contract, environment, verifier, or instrumentation changed. Preserve the
  row and start a new experiment ID after fixing the contract.
- `failed`: the unchanged cell ran but did not produce verified delivery. Keep it in raw results.

Negative speedup, saturation, verifier contention, and failed cells are publishable results. Do not
edit prompts, plans, repetitions, or exclusions after inspecting the curve. Provider-side queue
time and billable cost remain unavailable when the installed CLI does not report them.

## Reproduction

```bash
uv sync --all-extras
uv run fg benchmark scaling benchmarks/scripted-branch-join.yaml \
  --slots 1,2,4,8,16 --output-dir benchmark-results/scripted
```

The committed scripted Manifest has four independent branches and one join. More than four root
slots cannot expose more branch parallelism, so efficiency should fall after saturation. Exact wall
times are environment-dependent.
