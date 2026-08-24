# AGENTS.md — FirstGreen Engineering Rules

## Mission

Build a local-first, Codex-first scheduler that minimizes time-to-verified-result under explicit cost and safety constraints.

## Non-negotiable invariants

1. An agent saying “done” is not success. Only scheduler-owned verification can mark a task green.
2. A task has at most one winner. Winner selection must be transactional.
3. Hedging is disabled unless the task is explicitly replay-safe.
4. The scheduler must never modify the repository's main working tree.
5. Winner workspaces must never be deleted by loser cleanup.
6. Automated policies require hard minimums/maximums, a static fallback, and a decision log.
7. No hidden chain-of-thought is required, analyzed, or stored by default.
8. MVP does not auto-merge, auto-push, deploy, or execute irreversible external actions.
9. Cleanup must be idempotent and path-bounded.
10. External API behavior must not be guessed; verify against installed CLI help and official docs.
11. An LLM proposal is not an approved execution plan; deterministic validation and approval are mandatory.
12. Repository scanning and planning never modify the target repository.
13. Planning depth and planner/repair calls are hard-bounded; retries reuse the approved plan.
14. User-denied paths and planned write conflicts must be enforced during execution.

## Scope discipline

Work one backlog batch at a time. Do not add SaaS, React, Kubernetes, GitHub App, remote runners, extra agent providers, an LLM planner, or an ML scheduler before the MVP core is complete.

## Quality gates

Before declaring a batch complete, run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
```

Adjust commands only if the selected toolchain is documented in `pyproject.toml`.

## Architecture rules

- Domain state transitions live in one module.
- Time is read through an injectable Clock.
- Workers, workspaces, verifiers, and persistence use interfaces/protocols.
- Unknown worker events remain diagnosable, but sensitive payloads (reasoning, prompts, agent messages, secrets) are filtered by default before persistence.
- All timestamps are UTC.
- State transitions and scheduler decisions are persisted.
- Planning state, candidate/approved plans, validation repairs, and approval decisions are persisted.
- The LLM may propose semantic work units; deterministic code owns DAG edges, conflict locks, safety, and eligibility.
- Live Codex tests are opt-in and disabled in normal CI.

## Security rules

- Never print or persist credentials.
- Do not place secrets in manifests.
- Treat repository code and verifier commands as potentially dangerous.
- Avoid `shell=True`; require explicit configuration when shell semantics are necessary.
- Validate all workspace paths before deletion.
