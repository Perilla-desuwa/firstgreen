# Release validation journal

This append-only journal retains release-pipeline failures and their disposition. Experimental
negative results remain with their experiment evidence; this file covers packaging and publication.

Pre-snapshot commit identifiers below describe private staging history and are intentionally not
reachable from the single-commit public repository.

## 2026-08-25 — package builder unavailable in the virtual environment

- Release: `v0.1.0-rc1`.
- Observed: the first `build-release-assets.ps1` invocation compiled the report, then stopped before
  producing the wheel or source distribution because `.venv` did not expose the `build` module.
- Classification: release-environment defect, not an experimental result and not a product-runtime
  failure.
- Fix: the release builder now adds the repository's documented `.deps` runtime to `PYTHONPATH`
  during the isolated package-build step, then restores the caller's environment.
- First rerun: the builder found the bundled module, then stopped when its default user-profile
  temporary directory was not writable in the controlled workspace. That follow-on failure is
  recorded below.

## 2026-08-25 — package builder selected an out-of-workspace temporary directory

- Release: `v0.1.0-rc1`.
- Observed: the package backend failed before creating an sdist because it attempted to write under
  the user's profile temporary directory, which the controlled release environment denied.
- Classification: release-environment defect; no package or evidence result was silently accepted.
- Fix: the release builder now binds `TEMP` and `TMP` to the path-bounded
  `tmp/release-build` directory for the package-build step and restores both variables afterward.
- First rerun: the same frontend still failed inside its child backend environment even though the
  temporary directory was now correctly bounded. The path repair remains in place, but was not
  sufficient by itself.

## 2026-08-25 — generic build frontend could not launch its backend in the controlled workspace

- Release: `v0.1.0-rc1`.
- Observed: `python -m build --no-isolation` continued to fail while creating the child backend
  request, now under the correct workspace path.
- Classification: release-tooling incompatibility with the controlled execution environment.
- Fix: invoke the Hatchling backend declared in `pyproject.toml` directly. A bounded probe produced
  both `firstgreen-0.1.0rc1.tar.gz` and `firstgreen-0.1.0rc1-py3-none-any.whl` without a child build
  environment.
- Full release rerun: pending at the time this entry was added.

## 2026-08-25 — generated package inventory was empty

- Release: `v0.1.0-rc1`.
- Observed: the full builder produced all named assets, but `.venv` had no `pip` module. The package
  inventory command failed while PowerShell continued, leaving an empty `package-lock.txt` inside
  an otherwise complete evidence zip.
- Classification: release-gate defect. The generated zip is invalid and must not be published.
- Fix: enumerate installed distributions through Python's standard `importlib.metadata`, with the
  bundled runtime on `PYTHONPATH`; an empty inventory or nonzero command now aborts the build.
- Rerun: passed. The verified archive contains 36 inventory rows.

## 2026-08-25 — source distribution included private untracked files

- Release: `v0.1.0-rc1`.
- Observed: external asset verification found the private project-plan `.docx` and untracked
  `docs/video/` drafts inside the generated sdist. Neither appeared in the evidence zip, but the
  source package was unsafe to publish.
- Classification: privacy/release-packaging defect. All assets from that build are invalidated.
- Fix: export `HEAD` with `git archive` into a path-bounded temporary source tree and run Hatchling
  only there. The builder also inspects the resulting sdist and rejects `.docx`, `docs/video/`, or
  `.codex_doc_review/` entries.
- Rerun: passed. External inspection found 280 sdist entries and zero forbidden entries.

## 2026-08-25 — stale backend temporary directory blocked the next build

- Release: `v0.1.0-rc1`.
- Observed: a directory left by the failed generic build frontend denied recursive cleanup, so the
  tracked-source build stopped before package generation.
- Classification: release-environment residue. The denied directory is under ignored `tmp/`, not
  tracked and not part of any release asset.
- Fix: allocate a new GUID-named, path-bounded temporary directory for every release build. Cleanup
  remains bounded and best-effort; a stale denied directory cannot be reused or block a later run.
- Rerun: passed; the tracked-source package and all evidence assets were generated.

## 2026-08-25 — sandboxed wheel installation could not create pip temporary directories

- Release: `v0.1.0-rc1`.
- Observed: two `pip install --no-deps --target` attempts failed before installation, first under the
  user temporary directory and then under a repository-bounded temporary directory. Both failures
  were permission denials in pip's transient target directory.
- Classification: validation-environment restriction, not a wheel-content failure.
- Resolution: rerun the same local-only install outside the filesystem sandbox, still using
  `--no-deps` and a target under repository `tmp/`. Installation succeeded; package metadata
  reported `0.1.0rc1`, and `python -m firstgreen.cli --help` rendered the command catalog.

## 2026-08-25 — sandboxed pytest could not create fixture temporary directories

- Release: `v0.1.0-rc1`.
- Observed: the first run produced 247 setup errors under the user temporary directory. A second
  run bound both `TEMP` and `--basetemp` inside the repository, but the sandbox still denied the
  pytest lock directory. Neither run reached product assertions and neither is counted as a test
  failure.
- Classification: invalid test-environment runs.
- Resolution: rerun the unchanged suite outside the filesystem sandbox with `TEMP`, `TMP`, and
  `--basetemp` still path-bounded under `.pytest-tmp`; the command completed successfully. Ruff
  check, Ruff format check, and mypy had already passed in the sandbox.

## 2026-08-25 — clean-clone Git transport was blocked in the sandbox

- Release: `v0.1.0-rc1`.
- Observed: the first local `git clone --no-local` failed when Git for Windows could not create its
  signal pipe in the filesystem sandbox; no valid clone was produced.
- Classification: validation-environment restriction.
- Resolution: the same local-only clone completed outside the sandbox at commit `a157205901f3`.
  Its initial status was clean. The clone reported version `0.1.0rc1`, validated the fake Manifest,
  and completed a one-slot scripted scheduler smoke with one raw result row.
- Doctor result: Python, Git, repository cleanliness, worktree support, and state storage passed.
  Launching the Codex CLI subprocess remained permission-blocked in this controlled executor, so
  live Codex preflight is not claimed by this clean-clone gate.

## 2026-08-25 — first remote CI run failed Markdown formatting

- Release: `v0.1.0-rc1`.
- GitHub Actions run: `32756786423` at commit `a914ff57820c`.
- Observed: all four matrix jobs stopped at `ruff format --check`. The remote Ruff environment
  formatted fenced Python in `02_TECHNICAL_SPEC.md` and required blank lines before three
  dataclasses and one protocol class; the local non-preview invocation did not include Markdown.
- Classification: CI/tooling coverage gap, not a runtime or experiment failure.
- Fix: format the Markdown file with Ruff's Markdown preview mode and include the change in the
  single squashed RC preparation commit.
- Rerun: pending at the time this entry was added.

## 2026-08-25 — second single-snapshot CI run retained one Rich-rendering assertion

- Release: `v0.1.0-rc1`.
- GitHub Actions run: `32759393528` at single-root snapshot `c9e0910c52a2`.
- Observed: the first portability fixes removed the Python-path and executable-suffix failures. The
  remaining test correctly observed that planning rejected a dirty repository and matched the
  stable `uncommitted changes` diagnostic, but additionally required an option name to remain a
  contiguous substring in Rich's styled, width-dependent error rendering.
- Classification: terminal-presentation test defect; product dirty-tree enforcement passed.
- Fix: retain the behavioral exit-code and stable-diagnostic assertions, and remove the redundant
  presentation-specific substring check.
- Rerun: pending at the time this entry was added.

## 2026-08-25 — first single-snapshot CI run exposed platform-sensitive tests

- Release: `v0.1.0-rc1`.
- GitHub Actions run: `32758824961` at single-root snapshot `5e7ce088c011`.
- Observed: Ruff and mypy passed on all four matrix cells. Pytest then reported three assertions
  that encoded Windows or environment-specific presentation details: resolving a virtual-environment
  Python symlink to its base interpreter, expecting `codex.exe` on POSIX, and matching an unwrapped
  Rich error line. The product paths under test behaved as designed.
- Classification: cross-platform test-portability defect, not a scheduler-runtime failure.
- Fix: compare the verifier override using the same absolute-path contract as the CLI, select the
  expected Codex sandbox executable by platform, and assert the stable error tokens independently
  of terminal wrapping.
- Rerun: pending at the time this entry was added.

## 2026-08-25 — second remote CI run exposed a POSIX typing defect

- Release: `v0.1.0-rc1`.
- GitHub Actions runs: `32757066460` and the duplicate tag-triggered run `32757061587`, both at
  commit `429e46c5b4fb`.
- Observed: remote Ruff checks passed, then all four Python/OS matrix jobs failed mypy because
  `subprocess.CREATE_NEW_PROCESS_GROUP` is Windows-only and absent from the POSIX type surface.
- Classification: cross-platform typing defect in Codex process creation.
- Fix: resolve the Windows creation flag through `getattr(subprocess, "CREATE_NEW_PROCESS_GROUP",
  0)` and keep the value zero on non-Windows systems. CI now triggers once for the `main` branch
  instead of duplicating the run for the release tag.
- Rerun: pending at the time this entry was added.
