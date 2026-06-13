"""The did-you-mean suggestion on a mistyped command (distill._app.DistillGroup)."""

from __future__ import annotations

from typer.testing import CliRunner

from distill.cli import app

runner = CliRunner()


def test_typo_suggests_closest_command():
    result = runner.invoke(app, ["papres"])  # typo for "papers"
    assert result.exit_code != 0
    assert "Did you mean" in result.output
    assert "papers" in result.output


def test_valid_command_has_no_suggestion():
    result = runner.invoke(app, ["doctor", "--help"])
    assert result.exit_code == 0
    assert "Did you mean" not in result.output


def test_gibberish_command_still_errors_cleanly():
    """A command with no close match: still a clean usage error, no suggestion,
    no traceback."""
    result = runner.invoke(app, ["zzzzzzzz"])
    assert result.exit_code != 0
    assert "No such command" in result.output
