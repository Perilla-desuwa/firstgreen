You are building and validating the FirstGreen planning and scheduling testbed.

Read, in order:

1. `README.md`
2. `TESTBED_SPEC.md`
3. all files under `issues/`, `golden/`, `fakes/`, and `schemas/`
4. the existing FirstGreen product, technical specification, backlog, and `AGENTS.md` if present

Your job is to create a small synthetic Python repository called `tinyshop`, build a deterministic test harness around it, and validate the planning and scheduling behaviors specified in `TESTBED_SPEC.md`.

## Core rules

- Do not require live LLM or Codex credentials for the default test suite.
- Implement deterministic fake planners and fake workers first.
- Treat golden files as semantic invariants, not exact wording snapshots.
- Do not weaken a golden expectation merely to make a test pass.
- Do not claim live integration succeeded unless it was actually run.
- Do not execute destructive migration scenario S6.
- Preserve failed scenario workspaces for inspection.
- Keep the fixture small and fast.
- Use repository copies or worktrees so scenarios are isolated.
- Run formatting, linting, type checking if configured, and tests after every implementation batch.

## Required implementation batches

### Batch T0 — Inspect and plan

- Inspect the current repository.
- Identify whether FirstGreen code already exists.
- Produce a concise implementation map.
- Do not rewrite unrelated scheduling code.

Exit criteria:

- clear list of files to add or change;
- clear mapping from testbed requirements to existing interfaces.

### Batch T1 — Build baseline `tinyshop`

Create the synthetic repository exactly within the size and behavior constraints in `TESTBED_SPEC.md`.

Required baseline commands:

```bash
pytest -q
ruff check .
```

Exit criteria:

- baseline tests green;
- intentional pagination bug exists but is not yet covered by a failing baseline test;
- no network or external services.

### Batch T2 — Add issue and golden loaders

Implement loaders for:

- natural-language issue files;
- semantic golden YAML;
- fake candidate-plan JSON;
- scenario metadata.

Exit criteria:

- all supplied files parse;
- schemas are validated;
- invalid fixtures fail with clear errors.

### Batch T3 — Fake planner and deterministic compiler tests

Implement or connect:

- fake planner adapter;
- candidate-plan schema validation;
- deterministic DAG compiler;
- cycle detection;
- artifact edge generation;
- conflict constraints;
- task merging;
- risk approval gates;
- single-task fallback.

Run scenarios S1–S6, F1, and F2 in planning-only fake mode.

Exit criteria:

- golden semantic checks pass;
- cyclic and garbage plans cannot execute;
- S6 remains approval-blocked.

### Batch T4 — Fake worker and scheduler execution

Implement deterministic fake workers and verifiers.

Validate:

- ready queue behavior;
- dependency release;
- maximum observed parallelism;
- conflict serialization;
- atomic winner assignment;
- idempotent cancellation and cleanup.

Exit criteria:

- S1, S2, and S3 execute with fake workers;
- observed scheduling matches golden constraints.

### Batch T5 — Delayed hedge tests

Implement H1 with either virtual time or short deterministic sleeps.

Required tests:

1. slow primary, fast verified hedge;
2. fast hedge that fails verification, slower primary that passes;
3. duplicate completion race where only one winner is committed;
4. cancellation repeated twice;
5. cleanup repeated twice.

Exit criteria:

- first verified winner semantics hold;
- no raw-completion winner bug;
- winner workspace survives cleanup.

### Batch T6 — Optional live planner integration

Only run when credentials are explicitly available.

- run planning-only S1–S6 once;
- cache by issue hash, repository commit, planner version, and configuration;
- compare against semantic golden expectations;
- report deviations without silently changing goldens.

Exit criteria:

- truthful report of which live tests ran and which were skipped.

### Batch T7 — Optional live coding integration

Only run when credentials and budget are explicitly available.

Run only:

- S1;
- S2;
- S3.

Keep hedging disabled.

Exit criteria:

- deterministic verifiers pass;
- costs, tokens, wall time, and attempt counts are reported;
- failures are preserved for inspection.

### Batch T8 — Reporting and documentation

Generate:

```text
reports/summary.md
reports/results.jsonl
reports/plans/
reports/timelines/
```

Document:

- how to run fake-only tests;
- how to run planning-only live tests;
- how to run live coding tests;
- cost controls;
- known limitations;
- any differences between the implemented fixture and the specification.

## Golden comparison rules

Do not compare exact task titles or prose.

Compare:

- single-task versus decomposition decision;
- allowed task-count range;
- required and forbidden edges;
- required artifacts;
- conflict constraints;
- approval requirements;
- risk tags;
- recommended-parallelism range;
- whether execution is allowed.

## Final validation commands

Provide and run one command for the default credential-free suite, such as:

```bash
pytest -q
python -m testbed.run --scenario all --fake-planner --fake-worker
```

At completion, report:

1. implemented batches;
2. passing scenarios;
3. skipped live scenarios;
4. remaining gaps;
5. exact commands to reproduce the results.

Do not stop after merely generating files. Build the fixture, implement the harness, run the deterministic validation suite, and fix failures until it passes or a genuine repository/environment limitation blocks progress.
