## Scope

Describe the problem and the smallest change that addresses it.

## Invariants and evidence

- [ ] Scheduler-owned verification remains the completion boundary.
- [ ] Main-tree isolation, transactional winner selection, and path-bounded cleanup are preserved.
- [ ] Planning/DAG/safety decisions remain deterministically validated.
- [ ] Frozen benchmark inputs were not tuned after inspecting results.
- [ ] New persisted or displayed worker data is sanitized.

## Validation

- [ ] `uv run ruff check .`
- [ ] `uv run ruff format --check .`
- [ ] `uv run mypy src tests`
- [ ] `uv run pytest`
- [ ] Documentation and known limitations are updated where needed.
