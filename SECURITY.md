# Security policy

## Supported versions

FirstGreen is currently a release candidate. Security fixes target the latest tagged release and
the default branch; older snapshots are not maintained.

## Reporting a vulnerability

When the public repository enables GitHub private vulnerability reporting, use that channel. Do
not open a public issue containing an exploit, credential, private prompt, repository contents, or
machine-specific sensitive data. If private reporting is not yet enabled, contact the repository
owner through the private contact method listed on their GitHub profile.

Include the affected version or commit, operating system, minimal reproduction, expected security
boundary, and whether credentials or external side effects may be involved. Redact secrets and
private source code.

## Security boundary

FirstGreen isolates worker edits in Git worktrees and does not auto-merge, push, deploy, or perform
irreversible external actions. Worktrees are **not** a container-grade sandbox. Repository code,
worker output, and verifier commands must be treated as potentially dangerous. See
[`docs/security-review.md`](docs/security-review.md) and
[`docs/known-limitations.md`](docs/known-limitations.md) before running untrusted code.
