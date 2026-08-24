# FirstGreen Planning and Scheduling Testbed Specification

## 1. Purpose

Build a small, deterministic Python repository named `tinyshop` and use it to validate the FirstGreen planning and scheduling stack end to end.

The testbed must cover:

- tasks that should not be decomposed;
- tasks that can be decomposed into independent parallel work;
- tasks that can be decomposed but contain true dependency edges;
- tasks that appear decomposable but have overlapping write sets;
- tasks that require explicit human approval;
- malformed planner output;
- cyclic planner output;
- delayed hedging and first-verified-wins.

The default test suite must run without live LLM credentials. Live planner and live coding-agent runs are optional smoke tests.

---

## 2. Synthetic repository: `tinyshop`

### 2.1 Constraints

The repository should be deliberately small:

- approximately 300–500 lines of application code;
- approximately 250–450 lines of tests;
- Python 3.12 or later;
- `pytest` for tests;
- `ruff` for linting;
- `mypy` may be included but should not be required if it increases fixture complexity;
- no external database server;
- no external email service;
- no network access;
- deterministic behavior;
- all tests complete quickly.

Use plain Python functions or a minimal FastAPI application. Prefer plain Python when it produces a smaller fixture.

### 2.2 Suggested structure

```text
tinyshop/
├── pyproject.toml
├── README.md
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── models.py
│   ├── mailer.py
│   ├── audit.py
│   ├── cli.py
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── routes.py
│   │   └── service.py
│   └── orders/
│       ├── __init__.py
│       ├── routes.py
│       └── service.py
└── tests/
    ├── test_health.py
    ├── test_cli.py
    ├── test_auth.py
    ├── test_password_reset.py
    ├── test_orders.py
    ├── test_mailer.py
    └── test_audit.py
```

### 2.3 Required initial behavior

Implement a minimal baseline with these capabilities:

#### Health information

`app/main.py` exposes a function or endpoint returning:

```json
{"status": "ok"}
```

It does not initially include a Git commit field.

#### CLI

`app/cli.py` exposes a minimal command-line entry point.

It does not initially support `--version`.

#### Orders

- `Order` has at least `id`, `status`, and `user_id`.
- Valid initial statuses include `pending` and `completed`.
- `paginate_orders(items, page, page_size)` contains an intentional bug: `page_size=0` causes division by zero or otherwise fails incorrectly.
- No cancellation workflow exists initially.

#### Authentication

- A minimal login-success path exists in `app/auth/routes.py`.
- Password reset does not exist initially.
- There is a small in-memory user store or fixture.

#### Mailer

`app/mailer.py` provides a fake outbox:

```python
OUTBOX: list[dict[str, str]]
```

and a deterministic `send_email(...)` function.

#### Audit logging

`app/audit.py` contains an in-memory audit log helper, but login and password reset routes do not initially emit audit records.

### 2.4 Baseline quality gates

The freshly generated fixture repository must pass:

```bash
pytest -q
ruff check .
```

The intentional pagination bug should be represented by missing coverage rather than an already failing baseline test. The issue-specific test added later should expose it.

---

## 3. Planning test modes

The testbed must exercise three levels:

### Level A: deterministic planner and compiler tests

Use fake planner JSON. No LLM, no coding agent.

Validate:

- schema parsing;
- DAG edge generation;
- cycle detection;
- conflict generation;
- task merging;
- risk gating;
- fallback behavior.

### Level B: planning-only tests

Run:

```bash
firstgreen plan <issue-file>
```

When a live planner is unavailable, use deterministic issue-to-plan fixtures.

Validate the plan but do not execute coding tasks.

### Level C: complete execution tests

Fully execute only the smallest representative cases:

1. local bug: one coding attempt;
2. independent parallel tasks: two coding attempts;
3. dependency DAG: three or four coding attempts.

Keep hedging disabled during the initial end-to-end runs.

---

## 4. Scenario matrix

| ID | Scenario | Planning expectation | Full live execution required |
|---|---|---|---|
| S1 | Pagination zero bug | Single task | Yes |
| S2 | CLI version + health commit | Two independent tasks | Yes |
| S3 | Password reset | Partially parallel DAG | Yes |
| S4 | Audit logging in two flows | Merge or exclusive write | Planning only |
| S5 | Order cancellation | Partially parallel DAG | Optional |
| S6 | Remove legacy DB field | Human approval required | Planning only |
| F1 | Cyclic planner output | Repair by merge or single-task fallback | Fake only |
| F2 | Coordination-only garbage task | Reject and fall back safely | Fake only |
| H1 | Delayed hedge | Backup starts after threshold; first verified wins | Fake worker by default |

---

# 5. Scenario specifications

## S1 — Local coupled bug: do not decompose

### Input

Use `issues/S1_pagination_zero_bug.md`.

### Expected planning result

```yaml
decision: single_task
recommended_parallelism: 1
risk_level: low
```

### Expected reasoning

- The implementation and regression test are tightly coupled.
- The likely changes are small.
- Separate coding agents would create more coordination overhead than useful parallelism.

### Expected likely paths

```text
app/orders/service.py
tests/test_orders.py
```

### Required verifier

```bash
pytest -q tests/test_orders.py
ruff check app/orders/service.py tests/test_orders.py
```

### Acceptance criteria

- Planner produces exactly one executable task.
- No separate “write tests” microtask is created.
- `page_size < 1` is rejected with a clear `ValueError` or equivalent domain error.
- Regression tests cover `page_size=0` and at least one negative value.

---

## S2 — Independent parallel work

### Input

Use `issues/S2_cli_and_health.md`.

### Expected planning result

```yaml
decision: decompose
recommended_parallelism: 2
risk_level: low
```

### Expected tasks

#### Task A: CLI version

Likely paths:

```text
app/cli.py
tests/test_cli.py
```

Verifier:

```bash
pytest -q tests/test_cli.py
```

#### Task B: Health commit field

Likely paths:

```text
app/main.py
tests/test_health.py
```

Verifier:

```bash
pytest -q tests/test_health.py
```

### Expected graph

```text
CLI version task ─────────────┐
                              ├── repository verification
Health commit task ───────────┘
```

There must be no dependency edge between Task A and Task B.

### Acceptance criteria

- Both tasks become ready at the same time.
- Their predicted write sets do not overlap.
- Static scheduling with two root slots starts both tasks without unnecessary serialization.
- Final repository verification runs after both complete.

---

## S3 — Decomposable work with true dependencies

### Input

Use `issues/S3_password_reset.md`.

### Expected planning result

```yaml
decision: decompose
recommended_parallelism: 2
risk_level: medium
```

Recommended parallelism may be reported as 2 or 3 depending on task granularity, but the DAG must contain at least one parallel branch and one join.

### Preferred task decomposition

#### Task A: Reset token model

Produces:

```text
reset-token-schema
```

Likely paths:

```text
app/models.py
```

#### Task B: Reset service

Requires:

```text
reset-token-schema
```

Produces:

```text
password-reset-service
```

Likely paths:

```text
app/auth/service.py
tests/test_password_reset.py
```

#### Task C: Reset email content

Produces:

```text
password-reset-email
```

Likely paths:

```text
app/mailer.py
```

This task may run in parallel with Task A or Task B, provided its write set is separate.

#### Task D: Reset routes and integration

Requires:

```text
password-reset-service
password-reset-email
```

Likely paths:

```text
app/auth/routes.py
tests/test_password_reset.py
```

### Preferred graph

```text
Token model ──→ Reset service ──┐
                                ├── Reset routes/integration ──→ final verification
Email content ──────────────────┘
```

If both Task B and Task D would write the same test file, the compiler should either:

- assign test ownership to one task;
- serialize them with an exclusive-write constraint; or
- merge test work into Task D.

It must not silently run overlapping writes concurrently.

### Functional requirements

- User may request a password-reset token.
- Token expires after one hour.
- Fake mailer receives a message containing the token.
- A reset confirmation operation validates the token and updates the password or a deterministic stand-in.
- Expired and invalid tokens are rejected.

### Required verifier

```bash
pytest -q tests/test_password_reset.py
pytest -q
ruff check .
```

### Acceptance criteria

- DAG contains a real dependency edge.
- At least one branch can run in parallel.
- Integration work waits for prerequisites.
- Final behavior is fully verified.

---

## S4 — Apparently decomposable but conflicting writes

### Input

Use `issues/S4_audit_logging_conflict.md`.

### Expected planning result

Preferred result:

```yaml
decision: single_task
recommended_parallelism: 1
reason_code: excessive_write_overlap
```

Acceptable alternative:

- two tasks with an explicit mutual-exclusion constraint on `app/auth`;
- no concurrent write execution.

### Likely overlapping paths

```text
app/auth/routes.py
tests/test_auth.py
```

### Acceptance criteria

- The planner proposal may contain two semantic units.
- The deterministic compiler detects overlapping write sets.
- Tasks are merged or serialized.
- The system does not mistake mutual exclusion for a data dependency.
- Planning-only validation is sufficient; live coding execution is not required.

---

## S5 — Partial parallelism with a model prerequisite

### Input

Use `issues/S5_order_cancellation.md`.

### Expected task shape

```text
Order status model ──→ Cancellation service ──┐
                                               ├── API/integration
Cancellation email content ───────────────────┘
```

### Expected planning result

```yaml
decision: decompose
recommended_parallelism: 2
risk_level: low
```

### Acceptance criteria

- Status/model change precedes service implementation.
- Email content can run independently.
- API and integration verification wait for both service and email requirements.
- This case is optional if S3 already exercises the same scheduler behavior.

---

## S6 — High-risk destructive migration

### Input

Use `issues/S6_remove_legacy_token.md`.

### Expected planning result

```yaml
decision: decompose
risk_level: high
requires_human_approval: true
auto_approval: false
```

### Required risk tags

At least one of:

```text
database-migration
destructive-schema-change
```

### Expected state

```text
awaiting_plan_approval
```

### Acceptance criteria

- `--approve-plan` must not bypass configured mandatory approval for destructive schema work unless the policy explicitly permits it.
- Planner cannot mark the operation safe by itself.
- No coding agent or migration command starts during this test.
- Planning-only validation is sufficient.

---

## F1 — Cyclic planner output

### Input

Use `fakes/cyclic_candidate_plan.json`.

### Expected behavior

The compiler detects:

```text
task-a → task-b → task-a
```

Deterministic repair should attempt, in order:

1. determine whether the tasks have artificial boundaries and merge them;
2. remove an unjustified edge if it can be proven redundant by artifact declarations;
3. fall back to one task.

### Prohibited behavior

- executing the cyclic plan;
- silently ignoring the cycle;
- repeatedly calling an LLM without a hard bound.

### Acceptance criteria

Final result is either:

```yaml
validation: repaired
final_task_count: 1
```

or:

```yaml
validation: requires_review
execution_allowed: false
```

---

## F2 — Coordination-only garbage task

### Input

Use `fakes/coordination_only_candidate_plan.json`.

### Expected behavior

Reject tasks that have:

- no concrete artifact;
- no measurable completion condition;
- no verifier;
- objectives such as “think about the problem” or “coordinate agents.”

### Acceptance criteria

- Invalid tasks are removed or cause safe fallback.
- The plan becomes one concrete execution task or enters review.
- No coordination-only agent run is launched.

---

## H1 — Delayed hedge and first verified winner

### Default implementation

Use fake workers. Do not spend live coding-agent tokens for the main test.

### Worker behavior

#### Primary attempt A

```text
start at 0 seconds
sleep for 20 seconds
would eventually return a valid result
```

#### Hedge attempt B

```text
start only after the hedge threshold
sleep for 2 seconds
return a valid result
```

Set:

```yaml
hedge_after_seconds: 5
max_replicas: 1
cancel_loser: true
```

### Expected timeline

```text
0s: attempt A starts
5s: attempt B starts
7s: attempt B completes
7s: verifier passes B
7s: B atomically becomes winner
7s: A is cancelled
```

### Acceptance criteria

- No hedge starts before the threshold.
- At most one hedge is launched.
- The winner is selected by verifier success, not raw completion alone.
- Winner assignment is atomic.
- Loser cancellation is issued.
- Cleanup does not remove the winner workspace.
- Replaying cancellation and cleanup is idempotent.

### Additional negative case

Attempt B returns earlier but fails verification; Attempt A later passes.

Expected result:

- B does not win;
- A remains active;
- A becomes the winner after verification.

---

# 6. Golden plan format

Golden files in `golden/` describe semantic expectations, not exact natural-language wording.

Tests should compare invariant fields such as:

- `decision`;
- task count range;
- required artifacts;
- required dependency relationships;
- forbidden dependency relationships;
- conflicts;
- risk tags;
- approval state;
- recommended parallelism range.

Do not require exact task names generated by an LLM.

---

# 7. Test harness requirements

Implement a test harness that can:

1. construct a fresh copy of `tinyshop` for every scenario;
2. apply scenario-specific issue input;
3. run planner or inject a fake candidate plan;
4. compile and validate an approved plan;
5. compare the plan to semantic golden expectations;
6. optionally execute tasks with fake or real workers;
7. run deterministic verifiers;
8. collect a JSON result record;
9. preserve failed workspaces for inspection;
10. clean successful ephemeral workspaces safely.

Suggested command:

```bash
python -m testbed.run --scenario S1
python -m testbed.run --scenario all --fake-planner --fake-worker
python -m testbed.run --scenario S3 --live-planner
python -m testbed.run --scenario S2 --live-coding
```

---

# 8. Required result record

Each scenario should emit a structured result such as:

```json
{
  "scenario": "S3",
  "planning": {
    "decision": "decompose",
    "candidate_task_count": 4,
    "approved_task_count": 4,
    "recommended_parallelism": 2,
    "validation_passed": true,
    "human_approval_required": false
  },
  "execution": {
    "attempt_count": 4,
    "verified": true,
    "wall_seconds": 18.2,
    "maximum_observed_parallelism": 2,
    "hedges_launched": 0
  },
  "golden_check": {
    "passed": true,
    "violations": []
  }
}
```

---

# 9. Cost-control policy

Default CI and local tests:

- fake planner;
- fake workers;
- no API credentials;
- no network;
- hedge simulation with short sleeps or virtual time.

Optional live planner suite:

- run each of S1–S6 at most once per repository commit and planner version;
- cache by issue hash + repository commit + planner configuration;
- skip unchanged cases.

Optional live coding suite:

- execute only S1, S2, and S3;
- keep hedging off initially;
- cap attempts per task;
- use strict token, time, and cost budgets;
- never run S6.

---

# 10. Required reports

Generate:

```text
reports/summary.md
reports/results.jsonl
reports/plans/<scenario>.yaml
reports/timelines/<scenario>.json
```

`summary.md` should contain:

- pass/fail table;
- planned versus realized parallelism;
- task count;
- conflicts and merges;
- approval decisions;
- verifier outcome;
- hedge timeline;
- live token/cost data when available;
- deviations from golden expectations.

---

# 11. Definition of done

The testbed is complete when:

1. the baseline `tinyshop` fixture passes its own tests;
2. all fake planner/compiler tests pass deterministically;
3. S1 is kept as one task;
4. S2 produces two independent ready tasks;
5. S3 produces a valid partial-parallel DAG;
6. S4 is merged or protected by exclusive-write constraints;
7. S6 cannot auto-execute;
8. F1 cannot execute cyclic output;
9. F2 cannot launch coordination-only work;
10. H1 selects the first verified winner and cancels the loser;
11. all tests run without live credentials by default;
12. optional live tests are clearly separated and truthfully reported.
