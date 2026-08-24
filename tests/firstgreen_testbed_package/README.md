# FirstGreen Planning & Scheduling Testbed

This package is a self-contained specification for building a small synthetic repository and validating FirstGreen's planning, DAG compilation, conflict handling, approval gates, scheduling, verification, and hedging behavior.

## Repository use

This specification package is integrated with the FirstGreen source tree. The implementation lives
under `src/firstgreen/testbed/`, the compatibility command is `python -m testbed.run`, and automated
checks live under `tests/testbed/`. `CODEX_AUTONOMOUS_TESTBED_PROMPT.md` is retained as the original
build-and-validation contract. Live LLM and Codex runs remain optional; the default suite is
deterministic and credential-free.

## Package contents

- `TESTBED_SPEC.md`: complete repository, scenario, expected behavior, and acceptance specification.
- `CODEX_AUTONOMOUS_TESTBED_PROMPT.md`: autonomous build-and-validate prompt for Codex.
- `issues/`: natural-language issue inputs.
- `golden/`: expected planning outcomes and constraints.
- `fakes/`: malformed, cyclic, and deterministic planner/worker fixtures.
- `schemas/`: suggested JSON schemas for candidate and approved plans.

## Primary success criteria

The testbed proves that FirstGreen can:

1. keep a small coupled task as one task;
2. create useful independent parallel work;
3. create a partially parallel DAG with true dependencies;
4. serialize or merge tasks with overlapping writes;
5. require approval for high-risk work;
6. reject malformed or coordination-only plans;
7. repair or safely collapse cyclic plans;
8. launch delayed hedges and atomically select the first verified winner.

## Run the implemented testbed

From the FirstGreen repository root:

```bash
uv run pytest -q
uv run python -m testbed.run --scenario all --fake-planner --fake-worker
```

The default command is deterministic, has no network dependency, and never invokes Codex. It
creates isolated TinyShop Git repositories and real FirstGreen worktrees under `.runtime/`, then
writes:

```text
reports/summary.md
reports/results.jsonl
reports/plans/
reports/timelines/
```

Failed scenario workspaces are preserved for inspection. S6 is planning-only and is never sent to
a worker.

## Optional live planner

Live planning replaces only the `PlannerAdapter`; deterministic compilation, validation, risk
gating and semantic golden comparison are unchanged. Both the flag and environment opt-in are
required:

```bash
FIRSTGREEN_RUN_LIVE_TESTBED_PLANNER=1 uv run python -m testbed.run \
  --scenario S3 --live-planner --fake-worker --model MODEL_ID \
  --reasoning low --live-timeout-seconds 900
```

Planner responses are cached by issue hash, repository commit, planner version, and configuration.
The live matrix is S1-S6 planning-only. Golden deviations are reported and never rewrite goldens.

## Optional live coding

Live coding replaces only the worker adapter and requires an existing Codex login. Hedging remains
disabled and only S1, S2, and S3 are allowed by the documented live matrix:

```bash
FIRSTGREEN_RUN_LIVE_TESTBED_CODING=1 uv run python -m testbed.run \
  --scenario S2 --fake-planner --live-coding --model MODEL_ID \
  --reasoning low --max-live-tasks 3 --live-timeout-seconds 900
```

The runner rejects `--scenario all` in either live mode. Coding is limited to S1-S3 and requires an
explicit model and `--max-live-tasks` acknowledgement before any worker starts. Planner calls are
limited to one per invocation; coding uses one primary attempt per task, one nested agent thread,
`workspace-write`, disabled hedging, a 60-1800 second per-attempt timeout, no automatic merge/push,
and the same deterministic verifiers as fake execution. A multi-task run succeeds only when its
scheduler-owned final delivery worktree also verifies. Token/cost fields are reported when Codex
emits them; unavailable values remain null rather than being estimated. The task, attempt, thread,
scenario, and timeout limits are hard controls; a monetary ceiling cannot be enforced when the CLI
does not expose price or billable cost before execution.

For direct live pytest selection, opt in to exactly one case:

```bash
FIRSTGREEN_RUN_LIVE_TESTBED_CODING=1 \
FIRSTGREEN_LIVE_TESTBED_SCENARIO=S2 \
FIRSTGREEN_LIVE_MODEL=MODEL_ID \
FIRSTGREEN_MAX_LIVE_TASKS=3 \
pytest -q tests/live/test_testbed_live.py
```

Set `FIRSTGREEN_CODEX_BINARY`, `FIRSTGREEN_LIVE_REASONING`, and
`FIRSTGREEN_LIVE_TIMEOUT_SECONDS` when their defaults are unsuitable. Failures and their workspaces
are preserved under the selected runtime root for inspection.

## Fixture differences and limits

- TinyShop uses plain Python rather than FastAPI and intentionally has no external services.
- H1 uses scaled short sleeps while preserving the fixture's ordering and verification outcomes.
- Downstream tasks receive only verifier-approved changed files from dependency winner worktrees;
  conflicting dependency snapshots are rejected.
- Native Windows is validated best-effort here; configured macOS/Linux CI still requires an actual
  remote CI run.
- Live authentication and paid calls are skipped unless their dedicated environment variable is
  set. A CLI flag without the environment opt-in records a skip.
