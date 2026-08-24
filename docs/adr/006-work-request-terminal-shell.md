# ADR-006: WorkRequest CLI and foreground TUI

Status: Accepted

## Context

The first planning interface accepted an issue file path. That was useful for deterministic fixtures,
but it made an issue tracker look like the product boundary and required users to create an
intermediate file before asking for ordinary repository work.

## Decision

`WorkRequest` is the user-facing input model. Its source can be inline text, a local file, stdin, or
the local clipboard; GitHub, Linear, and API sources remain future adapters to the same model. The
installed `fg` entry point routes no arguments or plain text to the interactive request flow.

The terminal UI is a foreground view over the production `PlanningEngine`, `SchedulerService`, and
SQLite state. It does not own task transitions, verification, winner selection, or cleanup. Existing
manifests and v0.1 plan YAML using `issue`/`issue_hash` remain readable; newly serialized plans use
`request`/`request_hash`.

The first terminal UI does not detach or claim daemon behavior. Cross-process cancellation remains
conservative until a real local daemon owns subprocess lifetimes.

## Consequences

- Daily use no longer requires a GitHub issue or a request file.
- Scripts retain explicit subcommands and JSON output when stdout is not a terminal.
- Clipboard access uses local argv-only platform commands and never a shell.
- Rich is a direct runtime dependency for plan and run dashboards.
- Advanced manifests remain supported for reproducible automation.
