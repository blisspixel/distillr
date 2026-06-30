"""The did-you-mean suggestion on a mistyped command (distill._app.DistillGroup)."""

from __future__ import annotations

import click
from typer.testing import CliRunner

from distill._app import DistillGroup
from distill.cli import app

runner = CliRunner()


def _command_group(*names: str) -> DistillGroup:
    return DistillGroup(name="distill", commands={name: click.Command(name) for name in names})


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


def test_resolver_formats_single_suggestion():
    group = _command_group("papers")
    ctx = click.Context(group)

    try:
        group.resolve_command(ctx, ["papres"])
    except click.UsageError as exc:
        assert exc.message.endswith("Did you mean: papers?")
    else:  # pragma: no cover - this path would mean the typo unexpectedly resolved.
        raise AssertionError("Expected a usage error for a mistyped command")


def test_resolver_formats_multiple_suggestions():
    group = _command_group("paper", "papers", "profile")
    ctx = click.Context(group)

    try:
        group.resolve_command(ctx, ["papes"])
    except click.UsageError as exc:
        assert exc.message.endswith("Did you mean: papers, paper?")
    else:  # pragma: no cover - this path would mean the typo unexpectedly resolved.
        raise AssertionError("Expected a usage error for a mistyped command")


def test_resolver_leaves_unsuggested_errors_unchanged():
    group = _command_group("paper", "papers")
    ctx = click.Context(group)

    try:
        group.resolve_command(ctx, ["zzzzzzzz"])
    except click.UsageError as exc:
        assert "Did you mean:" not in exc.message
    else:  # pragma: no cover - this path would mean the invalid command resolved.
        raise AssertionError("Expected a usage error for an unknown command")


def test_resolver_handles_empty_args_defensively():
    group = _command_group("paper")
    ctx = click.Context(group)

    assert group.resolve_command(ctx, []) == (None, None, [])
