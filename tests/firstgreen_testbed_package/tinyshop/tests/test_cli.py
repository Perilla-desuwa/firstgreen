import json

from app.cli import run


def test_health_command_outputs_json() -> None:
    code, output = run(["health"])
    assert code == 0
    assert json.loads(output)["status"] == "ok"


def test_echo_command_is_deterministic() -> None:
    assert run(["echo", "hello"]) == (0, "hello")


def test_no_command_returns_help() -> None:
    code, output = run([])
    assert code == 0
    assert "usage: tinyshop" in output
