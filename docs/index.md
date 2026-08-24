# FirstGreen documentation

FirstGreen extracts parallelism from software-engineering goals and schedules coding agents to
reduce time-to-verified-result under explicit safety, cost, and concurrency limits.

Start with the repository README, then read the product PRD, technical specification, example
manifests, ADRs, security review, known limitations, and release notes.

The active implementation priority is the [HPC runtime roadmap](ROADMAP.md). Scaling evidence uses
the production runtime according to the [benchmark methodology](benchmark-methodology.md).

The first complete controlled-live matrix is the
[Ramsey v2 result](evidence/results/controlled-live-ramsey-v2/README.md): eight frozen Luna cells,
all with verified task winners and final delivery, showing speedup through ready width four and
saturation when capacity is increased to eight slots.

The [publication package](publication/README.md) defines the tagged repository, evidence archive,
technical report, claim/evidence boundary, and release checklist. Public reproduction starts in
the top-level `REPRODUCIBILITY.md`.

Repository-aware issue planning is specified in the top-level `04_PLANNING_SUBSYSTEM.md` document.
