# Reproducing FirstGreen evidence

FirstGreen's product is parallelism extraction plus agent scheduling. Its benchmark tooling is a
thin evidence consumer of the same approved plan, scheduler, worktree, verifier, and delivery path.

## Evidence levels

- **Credential-free scripted evidence** validates capacity, scheduling, accounting, isolation,
  verification, delivery, and trace generation with deterministic workers.
- **Controlled-live evidence** invokes the explicitly named authenticated coding-agent model on a
  frozen approved plan. Only this class can support the scoped live speedup statement.
- **End-to-end case studies** evaluate extraction through delivery on individual repositories. They
  show product-path behavior, not general planner accuracy or population-level speedup.

Failed, invalid, interrupted, sequential, and negative results are retained. Exact validity rules
are in `docs/benchmark-methodology.md` and the frozen matrix is in
`docs/evidence/public-evidence-plan-v1.md`.

## Credential-free reproduction

Requirements: Python 3.12+, Git with worktree support, and `uv`.

```bash
uv sync --all-extras
uv run fg doctor
uv run fg request --planner-provider fake --adapter fake
uv run fg benchmark scaling benchmarks/scripted-branch-join.yaml \
  --slots 1,2,4,8,16 --output-dir benchmark-results/scripted
```

Rebuild the matrix summary from its append-only raw journal rather than editing a summary by hand.
Open exported Chrome/Perfetto trace JSON in a compatible trace viewer; the files contain sanitized
scheduler lifecycle events, not model reasoning.

## Controlled-live reproduction

Live runs are opt-in, paid/model-dependent, and disabled in normal CI. Before enabling them, inspect
the corresponding runbook and verify its repository base, issue, Manifest hash, model, reasoning
effort, capacity, and attempt limits. The release evidence uses `gpt-5.6-luna` with low reasoning.

On Windows, validate all frozen inputs without starting a live worker:

```powershell
.\scripts\controlled-live-ready.ps1
```

Each live launcher requires its own explicit environment gate documented in the launcher and
runbook. Do not run two controlled-live matrices concurrently on the same host. Do not rerun a
failed cell under changed inputs and present it as the original experiment; use a new experiment ID.

## Release artifact inspection

The GitHub Release evidence zip is designed to be inspectable without an account or another paid
run. Verify its external SHA-256 first, then verify every file against the internal
`SHA256SUMS.txt`. `ARTIFACT-METADATA.json` identifies the code commit, protocol, model, host summary,
and all missing, invalid, or failed cells.

The archive layout is specified in `docs/publication/artifact-manifest.md`. It intentionally omits
credentials, private prompts, hidden reasoning, unfiltered messages, complete worktrees, and raw
machine state.

## Expected variability

Scripted wall times still depend on host filesystem and process overhead. Controlled-live latency
also depends on provider load and network conditions. Exact times need not match the publication;
the reproducibility target is the frozen contract, outcome classification, accounting invariants,
and qualitative scaling/saturation behavior. A changed model or provider is a new experiment.
