"""Terminal controls and shared diagnostic layout remain copyable and explicit."""

from io import StringIO

import pytest
from rich.console import Console
from typer.main import get_command
from typer.testing import CliRunner

from distill import cli
from distill.commands._diagnostics import print_diagnostic


def test_short_help_works_recursively_without_executing_commands():
    runner = CliRunner()
    root = get_command(cli.app)

    def visit(group, path):
        result = runner.invoke(cli.app, [*path, "-h"])
        assert result.exit_code == 0, result.output
        assert "Usage:" in result.output
        for name, command in getattr(group, "commands", {}).items():
            visit(command, [*path, name])

    visit(root, [])


@pytest.mark.parametrize("width", [40, 60, 80, 120])
def test_diagnostic_labels_align_and_keep_state_without_color(width):
    output = StringIO()
    console = Console(file=output, width=width, color_system=None, highlight=False)
    for label in ("API key", "Verification", "Local inference"):
        print_diagnostic(console, f"  OK {label}  Ready with numeric-only coverage")
    lines = output.getvalue().splitlines()
    first_lines = [line for line in lines if "OK " in line]
    assert len(first_lines) == 3
    assert len({line.index("Ready") for line in first_lines}) == 1
    assert "numeric-only coverage" in " ".join(line.strip() for line in lines)
    assert all(len(line) <= width for line in lines)
    assert "\x1b[" not in output.getvalue()
