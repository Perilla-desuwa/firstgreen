# Figure contract

Final report figures use PDF for LaTeX; GitHub may use SVG or PNG. Keep both forms when the figure
appears in both places. Do not export screenshots with private paths, account names, prompts, or
unsanitized worker messages. The tracked Ramsey SVGs are regenerated from the public raw journal by
`scripts/render_publication_figures.py`. The same script renders the JavaScript timeline from its
sanitized trace.

| Frozen basename | Required view | Data source | Report role |
|---|---|---|---|
| `system-overview` | Goal → extraction → approved DAG → scheduling → verified delivery; benchmark as a side consumer | Architecture, no measured data | Product identity |
| `ramsey-scaling` | Wall time and speedup for slots 1/2/4/8; all repetitions visible | Ramsey `raw.jsonl` | Headline live evidence |
| `ramsey-efficiency` | Parallel efficiency with ready-width/saturation annotation | Ramsey `raw.jsonl` | Explain scaling limit |
| `ramsey-trace` | Four concurrent shard roots, certificate join, and delivery | Sanitized four-slot repeat-one trace | Explain saturation mechanism |
| `critical-path-ablation` | Stable versus critical-path dispatch order and makespan | Registered ablation rows and median traces | Scheduler evidence |
| `javascript-live-timeline` | Documentation/core roots, verifier-rejected primaries, bounded repairs, dependent tests, and final delivery | Sanitized JavaScript trace JSON | End-to-end portability and completion-boundary evidence |

The broader `extraction-cases` card sheet remains optional supporting material. The technical
report uses the observed JavaScript timeline instead of a pre-run placeholder.

## Visual rules

- Use the same color for a task across a DAG and its trace.
- Show raw repetitions as points; summaries may be lines or bars but never hide a failed cell.
- Put units on every axis and identify scripted versus controlled-live in the title or subtitle.
- Do not connect missing or invalid points as if they were measured.
- Annotate ready width and $W/L$ beside the scaling curve.
- Export at least 1600 px width for README PNGs. Use vector PDF in the report.
- Add the experiment ID, code commit, and evidence version in a small footer or caption.
- Use an honest y-axis; wall-time bars start at zero.

The report compiles with visible placeholder boxes until these files exist. A missing figure must
therefore remain obvious rather than silently disappearing.
