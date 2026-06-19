"""Recurring research profile commands."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from distill._console import console
from distill.commands._helpers import get_config
from distill.commands._json import emit_json, json_mode_active
from distill.library.profiles import (
    ProfileValidationError,
    find_research_profile,
    load_research_profile,
)
from distill.pipeline.profile_preview import (
    ProfilePreviewResult,
    build_profile_preview,
    command_text,
)

__all__ = ["profile_app", "profile_preview_cmd", "register"]

profile_app = typer.Typer(help="Manage recurring research profiles.")


@profile_app.command(name="preview")
def profile_preview_cmd(
    profile: str = typer.Argument(help="Profile name under library/profiles, or a YAML path."),
    limit: int | None = typer.Option(
        None,
        "--limit",
        "-n",
        min=1,
        help="Maximum fresh item rows from feeds and YouTube.",
    ),
    fetch_sources: bool = typer.Option(
        True,
        "--fetch/--no-fetch",
        help="Fetch feeds and YouTube channel metadata before showing candidates.",
    ),
):
    """Preview the current candidate set for a recurring profile."""

    config = get_config()
    path = find_research_profile(config.library_dir, profile)
    if not path.exists():
        _exit_with_error(f"Profile not found: {path}")

    try:
        loaded = load_research_profile(path)
        result = build_profile_preview(
            loaded,
            fresh_item_limit=limit,
            fetch_sources=fetch_sources,
        )
    except ProfileValidationError as exc:
        _exit_with_error(str(exc))
    except ValueError as exc:
        _exit_with_error(str(exc))

    if json_mode_active():
        emit_json(result.to_dict())
        return

    _render_profile_preview(result, path)


def _exit_with_error(message: str) -> None:
    if json_mode_active():
        emit_json(error=message)
    else:
        console.print(f"[red]{message}[/red]")
    raise typer.Exit(1)


def _render_profile_preview(result: ProfilePreviewResult, path: Path) -> None:
    console.print(f"\n[bold]Profile Preview[/bold] [dim]{result.profile}[/dim]")
    console.print(
        f"[dim]Topic: {result.topic} | Cost mode: {result.cost_mode} | "
        f"Fresh item limit: {result.fresh_item_limit}[/dim]"
    )
    console.print(f"[dim]Profile: {path}[/dim]\n")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Type", no_wrap=True)
    table.add_column("Source", overflow="fold")
    table.add_column("Title", overflow="fold")
    table.add_column("Published", no_wrap=True)
    table.add_column("Command", overflow="fold")

    for candidate in result.candidates:
        table.add_row(
            candidate.kind,
            candidate.source_label,
            candidate.title,
            candidate.published_at or "",
            command_text(candidate.command),
        )

    console.print(table)
    console.print(f"\n[dim]Ordering: {result.ordering}[/dim]")
    if result.warnings:
        console.print("\n[yellow]Warnings[/yellow]")
        for warning in result.warnings:
            console.print(f"  {warning.source}: {warning.message}")


def register(app: typer.Typer) -> None:
    """Attach recurring profile commands."""

    app.add_typer(profile_app, name="profile", rich_help_panel="Discover")
