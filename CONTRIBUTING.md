# Contributing

FirstGreen welcomes focused bug reports, reproducibility reports, documentation fixes, and small
changes that strengthen parallelism extraction, scheduling, observability, or verification.

## Before opening a change

- Read `AGENTS.md`, `docs/ROADMAP.md`, and `docs/known-limitations.md`.
- Keep work to one reviewable backlog batch. Discuss major new providers, remote execution, UI, or
  execution-boundary changes before implementation.
- Do not include credentials, private prompts, hidden reasoning, sensitive worker payloads,
  proprietary repositories, or paid live-run output that has not been sanitized.
- Use Python 3.12+ and the toolchain declared in `pyproject.toml`.

## Local checks

```bash
uv sync --all-extras
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
```

Live Codex tests are opt-in and must remain disabled in normal CI. Changes to benchmark inputs,
metrics, exclusions, or experiment IDs must follow `docs/benchmark-methodology.md`; never tune a
frozen input after inspecting its outcome.

## Reports and pull requests

For a bug, include the FirstGreen version/commit, host environment, a minimal sanitized Manifest or
reproduction, expected behavior, observed behavior, and relevant run ID. For a code change, explain
which invariant it affects, add proportionate tests, update public limitations, and keep unrelated
formatting out of the patch.

Report vulnerabilities privately as described in `SECURITY.md`.
