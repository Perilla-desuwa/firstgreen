# Known limitations

- Parallelism extraction is heuristic and currently bounded to small plans; it does not optimize
  task granularity or communication cost globally. In the frozen TinyShop S3 case, two separate
  Luna observations both produced a correct but serial two-task graph where the fixture expected a
  branch/join, demonstrating that planning can under-extract available parallelism.
- Duration estimates currently use a deterministic structural heuristic, not historical runtime
  observations. Work/span and slot recommendations are therefore explainable planning estimates,
  not latency predictions. Critical-path scheduling consumes these estimates but does not claim an
  optimal schedule under unknown Agent runtimes.
- The Ramsey controlled-live matrix supplies one fixed-DAG strong-scaling result on one host and
  model. It does not establish general speedup across repositories, goals, models, or providers;
  the end-to-end extraction cases remain qualitative case studies.
- Runtime traces reconstruct Agent, verifier, and integration spans from local persisted timestamps.
  Provider-side queue time is unavailable, and idle-reason observations are diagnostic categories
  rather than exact causal attribution for every idle microsecond.
- Native Windows is best-effort; CI targets macOS and Linux and WSL2 is recommended on Windows.
- The one-shot CLI has conservative restart reconciliation, not universal subprocess reattachment.
- Cancellation is best-effort and cannot prove that provider-side work stopped immediately.
- Verifier commands execute repository code; FirstGreen is not a container or VM sandbox.
- SQLite supports one local scheduler and is not a distributed coordination database.
- Empirical quantiles do not yet use survival analysis for censored attempts.
- Simulator comparisons are synthetic and must not be presented as real-world savings.
- Public name, PyPI ownership, trademarks, and package namespace have not been cleared.
- Repository analysis is heuristic; Python gets first-class AST support but not full symbol resolution.
- GitHub issue fetching and multi-repository planning are not included; local issue/backlog files work.
- Shared repo-map caching and automatic execution-time replanning remain deferred.
- Realized planning quality metrics remain null until predicted tasks are linked to enough real runs.
- The Codex planner is explicit opt-in; its live smoke requires local Codex authentication.
