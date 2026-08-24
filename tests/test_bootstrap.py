from typer.testing import CliRunner

from firstgreen.cli import app


def test_help() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "verified coding-agent" in result.stdout
    for command in (
        "doctor",
        "init",
        "validate",
        "run",
        "status",
        "cancel",
        "report",
        "export",
        "benchmark",
        "scan",
        "plan",
        "validate-plan",
    ):
        assert command in result.stdout
