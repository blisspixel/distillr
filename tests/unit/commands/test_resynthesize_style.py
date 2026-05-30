"""Validation test for `distill resynthesize --style`."""

from __future__ import annotations

from typer.testing import CliRunner

from distill import cli

runner = CliRunner()


def test_resynthesize_rejects_unknown_style() -> None:
    result = runner.invoke(cli.app, ["resynthesize", "tkg", "--style", "bogus"])
    assert result.exit_code == 2
    assert "unknown --style" in result.output.lower()


def test_resynthesize_help_lists_styles() -> None:
    result = runner.invoke(cli.app, ["resynthesize", "--help"])
    assert result.exit_code == 0
    assert "exec" in result.output and "disagreements-only" in result.output
