"""OKF command group."""

from __future__ import annotations

from pathlib import Path

import typer

from distill._console import console
from distill.commands._json import emit_json, json_mode_active
from distill.library.okf import OkfIssue, validate_okf_bundle

__all__ = ["okf_app", "register", "validate"]

okf_app = typer.Typer(help="Validate Open Knowledge Format bundles.")


def _print_issues(issues: tuple[OkfIssue, ...], heading: str) -> None:
    if not issues:
        return
    console.print(f"[bold]{heading}[/bold]")
    for issue in issues:
        console.print(f"  [dim]{issue.path}[/dim]: {issue.message}")


@okf_app.command("validate")
def validate(
    path: Path = typer.Argument(..., help="Path to an OKF bundle directory"),
) -> None:
    """Validate an OKF bundle.

    Examples:
      distill okf validate output/okf-ai
      distill --json okf validate output/okf-ai
    """
    result = validate_okf_bundle(path)

    if json_mode_active():
        if result.ok:
            emit_json(result.to_dict())
        else:
            emit_json(result.to_dict(), error="OKF validation failed")
            raise typer.Exit(1)
        return

    if result.ok:
        console.print(f"[green]OKF valid:[/green] {result.root}")
    else:
        console.print(f"[red]OKF invalid:[/red] {result.root}")
    console.print(f"[dim]Markdown files checked: {result.files_checked}[/dim]")

    _print_issues(result.errors, "Errors")
    _print_issues(result.warnings, "Warnings")

    if not result.ok:
        raise typer.Exit(1)


def register(app: typer.Typer) -> None:
    """Attach the OKF command group."""
    app.add_typer(okf_app, name="okf", rich_help_panel="Knowledge")
