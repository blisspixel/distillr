"""Acceptance tests for the static setup signature."""

from io import StringIO

import pytest
from rich.console import Console

from distill.banner import show_banner, show_signature


@pytest.fixture
def terminal(monkeypatch):
    for name in ("NO_COLOR", "CI", "TERM", "DISTILL_BANNER"):
        monkeypatch.delenv(name, raising=False)
    output = StringIO()
    return Console(file=output, force_terminal=True, color_system="standard"), output


def test_signature_is_static_ansi_cyan(terminal):
    console, output = terminal
    assert show_banner(console)
    text = output.getvalue()
    assert "D I S T I L L" in text
    assert "38;2" not in text and "38;5" not in text
    assert "\x1b[2J" not in text


@pytest.mark.parametrize(
    "name,value",
    [
        ("NO_COLOR", "1"),
        ("NO_COLOR", ""),
        ("CI", "true"),
        ("TERM", "dumb"),
        ("DISTILL_BANNER", "off"),
    ],
)
def test_signature_honors_terminal_controls(terminal, monkeypatch, name, value):
    console, output = terminal
    monkeypatch.setenv(name, value)
    assert not show_banner(console)
    assert output.getvalue() == ""


def test_signature_never_prints_in_pipes():
    output = StringIO()
    assert not show_banner(Console(file=output))
    assert output.getvalue() == ""


def test_signature_once_per_version(terminal, tmp_path):
    console, output = terminal
    assert show_signature(console, tmp_path, "1.0")
    assert not show_signature(console, tmp_path, "1.0")
    assert show_signature(console, tmp_path, "1.1")
    assert output.getvalue().count("D I S T I L L") == 2


def test_signature_can_create_its_state_root(terminal, tmp_path):
    assert show_signature(terminal[0], tmp_path / "new-library", "1.0")
