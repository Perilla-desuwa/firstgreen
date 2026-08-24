import os
from pathlib import Path

import pytest

from firstgreen.user_config import (
    UserConfig,
    UserConfigError,
    codex_binary_candidates,
    load_user_config,
    remember_repository,
    save_user_config,
)


def test_user_config_round_trip_and_repository_history(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    configured = UserConfig(
        codex_binary="C:/tools/codex.exe",
        worker_model="small-model",
        worker_reasoning="low",
        planner_provider="codex",
        dirty_mode="snapshot",
    )

    save_user_config(configured, path)
    loaded = load_user_config(path)
    remembered = remember_repository(loaded, tmp_path / "repo")

    assert loaded == configured
    assert loaded.dirty_mode == "snapshot"
    assert remembered.recent_repositories == [str((tmp_path / "repo").resolve())]
    assert "credential" not in path.read_text(encoding="utf-8").lower()


def test_user_config_rejects_unknown_secret_fields(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("version: 1\napi_key: do-not-store\n", encoding="utf-8")

    with pytest.raises(UserConfigError, match="invalid FirstGreen user config"):
        load_user_config(path)


def test_codex_candidates_prefer_explicit_and_codex_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    monkeypatch.delenv("FIRSTGREEN_CODEX_BINARY", raising=False)

    assert codex_binary_candidates(explicit="C:/chosen/codex.exe") == ("C:/chosen/codex.exe",)
    candidates = codex_binary_candidates(configured="C:/configured/codex.exe")
    assert candidates[0] == "C:/configured/codex.exe"
    executable = "codex.exe" if os.name == "nt" else "codex"
    assert str(tmp_path / "codex-home" / ".sandbox-bin" / executable) in candidates
