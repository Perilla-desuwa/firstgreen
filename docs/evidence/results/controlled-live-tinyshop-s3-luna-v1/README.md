# TinyShop S3 Luna result

Status: execution and delivery passed; extraction result negative.

The original run was thought to have been interrupted when the network dropped, but its persisted
record was complete. A separately named `retry1` was nevertheless run without changing the source,
issue, model, reasoning, task ceiling, verifier, or policy. Both observations converged on the same
two-task serial shape:

```text
password-reset implementation -> password-reset tests -> final delivery verification
```

| Observation | Planner | Tasks / ready width | Execution | Delivery | Golden shape |
|---|---:|---:|---:|---|---|
| initial | 17.984 s | 2 / 1 | 184.719 s | verified | failed |
| retry1 | 20.078 s | 2 / 1 | 183.250 s | verified | failed |

The coding agents implemented the requested behavior and the scheduler verified the final delivery
in both observations. The negative result is specifically that `gpt-5.6-luna` did not extract the
fixture's expected branch/join topology. It grouped implementation paths into one umbrella task and
placed tests after it, so no root-level speedup was available.

Subsequent plan-only probes were assigned new planner versions and experiment IDs. They exposed
three reusable defects rather than being silently tuned away:

1. a test-only root can look parallel while being unable to pass in its isolated base workspace;
2. two semantic branches that both own the same routing file compile to a safe capacity-one lock;
3. repeated pairwise conflicts originally duplicated one resource key and could self-deadlock.

The compiler now rejects unverifiable test-only terminal branches, exposes file symbols in the
bounded repository map, audits path ownership in the planner contract, and deduplicates resource
locks. These changes improve safety and diagnosability, but this S3 observation remains a published
negative extraction result. It is not included in the Ramsey speedup calculation.
