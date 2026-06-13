"""Tests for the `--version` flag and the TTY-safe prompt/confirm helpers.

These are the agent/loop-friendliness guards (June 2026 CLI audit): a CLI an
agent drives must report its version without a configured env and must never
block on an interactive prompt when there is no TTY.
"""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from distill.cli import app
from distill.commands._helpers import tty_confirm, tty_prompt

runner = CliRunner()


def test_version_flag_prints_version_and_exits_zero() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    # Whatever the installed metadata reports (a dotted version or "dev"),
    # it is a single non-empty token on its own line.
    assert result.stdout.strip()
    assert "\n" not in result.stdout.strip()


def test_version_short_flag() -> None:
    result = runner.invoke(app, ["-V"])
    assert result.exit_code == 0
    assert result.stdout.strip()


class TestTtyConfirm:
    def test_interactive_delegates_to_typer(self) -> None:
        with (
            patch("distill.commands._helpers.sys.stdin.isatty", return_value=True),
            patch("distill.commands._helpers.typer.confirm", return_value=True) as confirm,
        ):
            assert tty_confirm("proceed?", default=False) is True
            confirm.assert_called_once()

    def test_non_tty_returns_default_without_prompting(self) -> None:
        with (
            patch("distill.commands._helpers.sys.stdin.isatty", return_value=False),
            patch("distill.commands._helpers.typer.confirm") as confirm,
        ):
            # default False -> the action is blocked, no prompt issued
            assert tty_confirm("proceed?", default=False) is False
            # default True -> proceeds (matches "enter = yes" semantics)
            assert tty_confirm("proceed?", default=True) is True
            confirm.assert_not_called()


class TestTtyPrompt:
    def test_interactive_delegates_to_typer(self) -> None:
        with (
            patch("distill.commands._helpers.sys.stdin.isatty", return_value=True),
            patch("distill.commands._helpers.typer.prompt", return_value="3") as prompt,
        ):
            assert tty_prompt("choose", default="1") == "3"
            prompt.assert_called_once()

    def test_non_tty_returns_default_without_prompting(self) -> None:
        with (
            patch("distill.commands._helpers.sys.stdin.isatty", return_value=False),
            patch("distill.commands._helpers.typer.prompt") as prompt,
        ):
            assert tty_prompt("choose", default="q") == "q"
            prompt.assert_not_called()

    def test_non_tty_default_overrides_interactive_default(self) -> None:
        # Where the interactive default would act (spend), non_tty_default is the
        # safe unattended fallback.
        with (
            patch("distill.commands._helpers.sys.stdin.isatty", return_value=False),
            patch("distill.commands._helpers.typer.prompt") as prompt,
        ):
            assert tty_prompt("size?", default="1", non_tty_default="n") == "n"
            prompt.assert_not_called()
