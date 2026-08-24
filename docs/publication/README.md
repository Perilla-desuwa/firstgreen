# FirstGreen publication package

This directory turns FirstGreen into a reviewable engineering artifact. The repository and its
normal product path remain the primary asset; benchmark results and the technical report explain
and test the acceleration claim.

## Recommended release form

Publish one coherent versioned object in this order:

1. **GitHub repository** — source, product quickstart, architecture, limitations, and tests.
2. **GitHub Release** — immutable tag, wheel/sdist, evidence archive, checksums, and release notes.
3. **Evidence bundle** — frozen inputs, raw journals, summaries, traces, environment metadata, and
   figures. It must be possible to inspect failures without running paid workers again.
4. **Technical report** — a 4–6 page engineering report generated from
   `technical-report.tex`. It is a technical report, not a claim of peer review.
5. **Optional archive and distribution** — add a DOI archive, package index, project page, or video
   only after the versioned repository and evidence bundle exist.

The intended asset chain is therefore:

`repository -> tagged release -> reproducible evidence -> technical report -> demo/video`

## Files and ownership

| File | Role | Normally edited after experiments? |
|---|---|---|
| `technical-report.tex` | Complete paper-like narrative and figure placement | Only if conclusions change |
| `results.tex` | Version, environment, measured values, and result wording | **Yes** |
| `figures/` | Publication figures and their frozen naming contract | **Yes** |
| `claim-evidence-matrix.md` | Prevents stronger claims than the data supports | Update observed status |
| `artifact-manifest.md` | Defines the evidence archive contents | Update hashes and sizes |
| `release-checklist.md` | Owner-facing release gate | Check boxes only |
| `release-validation.md` | Append-only packaging/publication failure journal | Append after failures and fixes |
| `release-body.md` | GitHub Release description template | Fill version and results |
| `references.bib` | Primary scheduling and tail-latency references | Rarely |
| `/REPRODUCIBILITY.md` | Public reproduction entry point | Update exact release paths |
| `/CITATION.cff` | Citation metadata for the tagged software and report | Update each release |

The report deliberately imports measurements from `results.tex`. Once the prose is accepted, the
normal finalization loop is:

1. finish the frozen experiment cells;
2. copy only observed values and precise result wording into `results.tex`;
3. place final PDF figures in `figures/` using the frozen names;
4. compile and visually inspect the report;
5. run the claim/evidence and release checklists;
6. package the evidence and create the tag.

Tracked result figures are rebuilt from sanitized public data, not edited by hand:

```powershell
python scripts/render_publication_figures.py `
  docs/evidence/results/controlled-live-ramsey-v2/raw.jsonl `
  docs/publication/figures `
  --js-trace docs/evidence/results/javascript-idempotent-checkout-v1/trace.json `
  --ramsey-trace docs/evidence/results/controlled-live-ramsey-v2/slots-4-repeat-1.trace.json `
  --ablation-summary docs/evidence/results/critical-path-ablation/summary.json `
  --ablation-stable-trace docs/evidence/results/critical-path-ablation/stable-median.trace.json `
  --ablation-critical-trace docs/evidence/results/critical-path-ablation/critical-median.trace.json
```

Build a placeholder draft for layout work:

```powershell
.\scripts\build-technical-report.ps1 -AllowPlaceholders
```

The release build omits `-AllowPlaceholders`; it fails if result, author, date, or repository
placeholders remain and writes `output/pdf/firstgreen-technical-report.pdf`.

Build the wheel, source distribution, versioned report, evidence archive, checksum sidecar, and
filled release body from a clean tracked tree:

```powershell
.\scripts\build-release-assets.ps1
```

## Version policy

- Use `v0.1.0-rc1` if extraction or production critical-path scheduling is incomplete, remote CI is
  unconfirmed, or a required evidence cell is silently missing.
- A failed or negative experiment does not by itself prevent an honest release. Retain it, explain
  it, and narrow the claim.
- Use `v0.1.0` only after the roadmap release gate is met and all public files name the same commit,
  code version, model, input hashes, and evidence-bundle checksum.
- Never change a frozen workload after viewing a result. Corrections use a new experiment ID.

## What not to publish

Do not include credentials, raw prompts, hidden reasoning, private repository contents, unfiltered
worker messages, `.firstgreen` state, complete worktrees, or machine-specific user paths. Public
traces and databases must pass the sanitization checks in the release checklist.
