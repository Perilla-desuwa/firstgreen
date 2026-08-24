import asyncio
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from firstgreen.config import VerificationDefaults
from firstgreen.verifier.runner import CommandVerifier, VerificationCommand


def test_bare_verifier_executable_is_resolved_from_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = tmp_path / "target-python"
    calls: list[tuple[str, str | None]] = []

    def fake_which(executable: str, *, path: str | None = None) -> str:
        calls.append((executable, path))
        return str(expected)

    monkeypatch.setenv("PATH", "target-environment")
    monkeypatch.setattr(shutil, "which", fake_which)

    resolved = CommandVerifier()._resolve_executable("python", tmp_path)

    assert resolved == str(expected)
    assert calls == [("python", "target-environment")]


def test_explicit_verifier_override_wins_without_path_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = (tmp_path / "python").resolve()

    def unexpected_which(executable: str, *, path: str | None = None) -> str:
        raise AssertionError((executable, path))

    monkeypatch.setattr(shutil, "which", unexpected_which)
    resolved = CommandVerifier(executable_overrides={"python": str(expected)})._resolve_executable(
        "python", tmp_path
    )

    assert resolved == str(expected)


def test_launch_failure_is_safe_structured_diagnostic(tmp_path: Path) -> None:
    missing = (tmp_path / "missing-python").resolve()
    result = asyncio.run(
        CommandVerifier(executable_overrides={"python": str(missing)})._run(
            VerificationCommand(argv=("python", "-c", "print('never')")),
            tmp_path,
            1000,
        )
    )

    assert result.exit_code is None
    assert result.stdout == result.stderr == ""
    assert result.resolved_executable == str(missing)
    assert result.launch_error_kind is not None
    assert result.launch_error_kind.startswith("FileNotFoundError:")


def test_verifier_override_requires_absolute_target() -> None:
    with pytest.raises(ValidationError, match="must be absolute"):
        VerificationDefaults(
            all_must_pass=True,
            command_timeout_seconds=900,
            max_output_bytes=2_000_000,
            executable_overrides={"python": "relative/python"},
        )


def test_runtime_verifier_argv_cannot_be_empty() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        VerificationCommand(argv=())
