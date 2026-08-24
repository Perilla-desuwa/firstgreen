from io import StringIO
from pathlib import Path

import pytest
from pydantic import ValidationError

import firstgreen.work_requests as work_requests
from firstgreen.work_requests import (
    WorkRequestSourceType,
    clipboard_request,
    request_from_token,
)


def test_inline_file_and_stdin_requests_share_one_model(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    request_file = tmp_path / "request.md"
    request_file.write_text("Fix the upload collision bug.\n", encoding="utf-8")

    inline = request_from_token("Fix it inline", repo)
    from_file = request_from_token(str(request_file), repo)
    from_stdin = request_from_token("-", repo, stream=StringIO("Fix it from stdin\n"))

    assert inline.source.type == WorkRequestSourceType.INLINE
    assert from_file.source.type == WorkRequestSourceType.FILE
    assert from_file.source.reference == str(request_file.resolve())
    assert from_stdin.source.type == WorkRequestSourceType.STDIN
    assert [inline.content, from_file.content, from_stdin.content] == [
        "Fix it inline",
        "Fix the upload collision bug.",
        "Fix it from stdin",
    ]
    assert len({inline.request_hash, from_file.request_hash, from_stdin.request_hash}) == 3


def test_empty_request_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        request_from_token("-", tmp_path, stream=StringIO(" \n"))


def test_clipboard_request_uses_clipboard_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(work_requests, "read_clipboard", lambda: "Copied requirement")

    request = clipboard_request(tmp_path)

    assert request.source.type == WorkRequestSourceType.CLIPBOARD
    assert request.content == "Copied requirement"
