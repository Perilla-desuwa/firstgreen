from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_firstgreen_user_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep developer machine defaults out of deterministic tests."""

    monkeypatch.setenv("FIRSTGREEN_CONFIG", str(tmp_path / "user-config.yaml"))
