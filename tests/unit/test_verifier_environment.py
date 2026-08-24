import os
import sys
from pathlib import Path

import pytest

from firstgreen.verifier.environment import (
    VerifierEnvironmentError,
    detect_verifier_environment,
)


def repository_python(repo: Path) -> Path:
    if os.name == "nt":
        return repo / ".venv" / "Scripts" / "python.exe"
    return repo / ".venv" / "bin" / "python"


def test_repository_virtual_environment_wins_over_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python = repository_python(tmp_path)
    python.parent.mkdir(parents=True)
    python.write_bytes(b"placeholder")
    python.chmod(0o755)
    monkeypatch.setattr("firstgreen.verifier.environment.shutil.which", lambda *_args, **_kw: None)

    detected = detect_verifier_environment(tmp_path, [("python", "-m", "pytest")])

    assert detected.mode == "repository-venv"
    assert detected.environment_root == tmp_path / ".venv"
    assert detected.resolved_executables == {"python": str(python.absolute())}
    assert detected.warnings == ()


def test_path_fallback_is_absolute_and_warned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "firstgreen.verifier.environment.shutil.which", lambda *_args, **_kw: sys.executable
    )

    detected = detect_verifier_environment(tmp_path, [("python", "-c", "print('ok')")])

    assert detected.mode == "path"
    assert detected.resolved_executables["python"] == str(Path(sys.executable).absolute())
    assert detected.warnings


def test_missing_verifier_is_rejected_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("firstgreen.verifier.environment.shutil.which", lambda *_args, **_kw: None)

    with pytest.raises(VerifierEnvironmentError, match="missing: no-such-verifier"):
        detect_verifier_environment(tmp_path, [("no-such-verifier", "--check")])


def test_explicit_override_must_exist(tmp_path: Path) -> None:
    with pytest.raises(VerifierEnvironmentError, match="missing: python"):
        detect_verifier_environment(
            tmp_path,
            [("python", "-m", "pytest")],
            explicit_overrides={"python": str(tmp_path / "missing-python")},
        )


@pytest.mark.skipif(os.name == "nt", reason="Unix virtualenv interpreters are normally symlinks")
def test_virtualenv_interpreter_symlink_is_not_resolved_away(tmp_path: Path) -> None:
    python = repository_python(tmp_path)
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)

    detected = detect_verifier_environment(tmp_path, [("python", "-c", "print('ok')")])

    assert detected.resolved_executables["python"] == str(python.absolute())
