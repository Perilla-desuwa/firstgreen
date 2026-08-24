# FirstGreen testbed implementation map

## Existing interfaces reused

| Testbed requirement | FirstGreen implementation |
|---|---|
| Repository inspection | `planning.scanner.HeuristicRepositoryScanner` |
| Fake semantic proposal | `planning.planner.PlannerAdapter` and `PlannerProposal` |
| DAG/artifact compilation | `planning.compiler.compile_plan` |
| Cycle repair and task merge | deterministic compiler repair path |
| Write-conflict serialization | `ConflictConstraint` plus scheduler keyed resources |
| Approval gates | `planning.compiler.can_auto_approve` |
| Isolated execution | `workspace.GitWorktreeManager` |
| Verified dependency composition | `workspace.VerifiedDependencyOverlay` |
| Fake/live worker switch | `service.WorkerAdapterFactory` / production `WorkerAdapter` contract |
| Verification and atomic winner | `verification.CommandVerifier` and SQLite winner CAS |
| Delayed hedge | `SchedulerService` plus production `first_verified_wins` coordinator |

## Files added or changed

- `tinyshop/`: versioned synthetic baseline repository without scenario fixes.
- `src/firstgreen/testbed/`: fixture loaders, semantic golden checker, deterministic adapters,
  production-scheduler execution, hedge scenarios, reporting, and command-line runner.
- `tests/testbed/`: schema, compiler, scheduler, hedge, and report integration tests.
- `reports/`: generated deterministic evidence; live-only fields remain explicitly skipped/null.
- Product README/backlog: testbed commands, batch status, and known deviations.

The fake adapters stop at the same `PlannerAdapter` and `WorkerAdapter` boundaries used by Codex.
All plan validation, manifest compilation, worktree creation, dependency release/composition,
verification, cancellation, cleanup and winner selection remain FirstGreen-owned. S6 is
planning-only and cannot be approved or executed by the harness.
