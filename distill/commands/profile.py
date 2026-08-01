# pyright: strict
"""Recurring research profile commands."""

from __future__ import annotations

import os
from pathlib import Path
from typing import NoReturn

import typer
from rich.table import Table
from rich.text import Text

from distill._console import console
from distill.commands._helpers import get_config
from distill.commands._json import ExitCode, emit_json, json_mode_active
from distill.config import DistillConfig
from distill.library.okf import export_okf_bundle
from distill.library.profiles import (
    ProfileValidationError,
    ResearchProfile,
    find_research_profile,
    load_research_profile,
)
from distill.llm.cost_policy import CostMode, normalize_cost_mode
from distill.pipeline.profile_execution import MAX_PROFILE_TIMEOUT_SECONDS
from distill.pipeline.profile_preview import (
    ProfilePreviewResult,
    build_profile_preview,
    command_shell_label,
    command_text,
)
from distill.pipeline.profile_run import (
    ProfileRunResult,
    run_profile_preview,
)

__all__ = ["profile_app", "profile_preview_cmd", "profile_run_cmd", "register"]

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
    """Preview the current candidate set for a recurring profile.

    Examples:
      distill profile preview ai-developer-news
      distill profile preview examples/profiles/ai-developer-news.yaml --no-fetch
      distill --json profile preview ai-developer-news --limit 20
    """

    try:
        _config, path, result = _load_profile_preview(profile, limit, fetch_sources)
    except ProfileValidationError as exc:
        _exit_with_error(str(exc))
    except ValueError as exc:
        _exit_with_error(str(exc))

    if json_mode_active():
        emit_json(result.to_dict())
        return

    _render_profile_preview(result, path)


@profile_app.command(name="run")
def profile_run_cmd(
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
        help="Fetch feeds and YouTube channel metadata before selecting commands.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Execute the approved profile commands. Without this, only prints the plan.",
    ),
    timeout_seconds: int = typer.Option(
        1800,
        "--timeout",
        min=1,
        max=MAX_PROFILE_TIMEOUT_SECONDS,
        help="Maximum seconds to allow each profile command.",
    ),
):
    """Run a recurring profile through existing Distill commands.

    Without ``--yes``, prints the command plan and state path only. With
    ``--yes``, executes the approved commands and records their results.

    Examples:
      distill profile run ai-developer-news
      distill profile run ai-developer-news --yes
      distill --cost-mode no-metered profile run ai-developer-news --yes
    """

    try:
        config, path, preview = _load_profile_preview(profile, limit, fetch_sources)
        result = run_profile_preview(
            preview,
            library_dir=config.library_dir,
            approved=yes,
            profile_ref=profile,
            timeout_seconds=timeout_seconds,
            workflow_budgets_usd=config.cost_workflow_budgets_usd,
            result_finalizer=(
                (
                    lambda run_result: _maybe_export_okf_bundle(
                        config,
                        preview.topic,
                        run_result,
                    )
                )
                if yes and preview.okf_export_required
                else None
            ),
        )
    except ProfileValidationError as exc:
        _exit_with_error(str(exc))
    except ValueError as exc:
        _exit_with_error(str(exc))

    if json_mode_active():
        emit_json(result.to_dict())
    else:
        _render_profile_run(result, path)
    if yes and result.health_status not in {"ok", "complete"}:
        raise typer.Exit(1)


def _maybe_export_okf_bundle(
    config: DistillConfig,
    topic: str,
    result: ProfileRunResult,
) -> ProfileRunResult:
    from dataclasses import replace

    try:
        okf_result = export_okf_bundle(config, topic)
    except (OSError, ValueError) as exc:
        failed_result = replace(
            result,
            okf_bundle_required=True,
            okf_bundle_dir="",
            okf_bundle_valid=False,
            warnings=[
                *result.warnings,
                {"source": "okf_export", "message": str(exc)},
            ],
        )
        if not json_mode_active():
            console.print(f"[yellow]OKF export skipped: {exc}[/yellow]")
        return failed_result

    validation_errors = len(okf_result.validation.errors)
    validation_warnings = len(okf_result.validation.warnings)
    return replace(
        result,
        okf_bundle_required=True,
        okf_bundle_dir=str(okf_result.output_dir),
        okf_bundle_valid=okf_result.validation.ok,
        warnings=[
            *result.warnings,
            *(
                [
                    {
                        "source": "okf_export",
                        "message": (
                            f"OKF bundle validation failed with {validation_errors} error(s)"
                            if validation_errors
                            else f"OKF bundle written with {validation_warnings} warning(s)"
                        ),
                    }
                ]
                if validation_errors or validation_warnings
                else []
            ),
        ],
    )


def _load_profile_preview(
    profile: str,
    limit: int | None,
    fetch_sources: bool,
) -> tuple[DistillConfig, Path, ProfilePreviewResult]:
    config = get_config()
    path = find_research_profile(config.library_dir, profile)
    if not path.exists():
        _exit_with_error(
            f"Profile not found: {profile}",
            code=ExitCode.NOT_FOUND,
        )

    loaded = _apply_profile_cost_policy(
        load_research_profile(path),
        normalize_cost_mode(os.environ.get("DISTILL_COST_MODE", config.distill_cost_mode)),
    )
    result = build_profile_preview(
        loaded,
        fresh_item_limit=limit,
        fetch_sources=fetch_sources,
    )
    return config, path, result


def _apply_profile_cost_policy(profile: ResearchProfile, configured: CostMode) -> ResearchProfile:
    """Apply the most restrictive no-metered policy across CLI and profile scope."""

    if configured == "no-metered" or profile.cost_mode == "no-metered":
        limits = profile.limits.model_copy(update={"max_metered_usd": 0.0})
        return profile.model_copy(update={"cost_mode": "no-metered", "limits": limits})
    if profile.cost_mode != "auto":
        return profile
    return profile.model_copy(update={"cost_mode": configured})


def _exit_with_error(message: str, *, code: ExitCode = ExitCode.RUNTIME_ERROR) -> NoReturn:
    from distill.commands._json import emit_json_refusal, phase_for_exit_code

    if json_mode_active():
        reason = "not_found" if code == ExitCode.NOT_FOUND else "runtime_error"
        emit_json_refusal(
            reason=reason,
            error=message,
            phase=phase_for_exit_code(code),
            action="profile",
        )
    else:
        console.print(f"[red]{message}[/red]")
    raise typer.Exit(int(code))


def _render_profile_preview(result: ProfilePreviewResult, path: Path) -> None:
    console.print(Text.assemble("\n", ("Profile Preview", "bold"), " ", (result.profile, "dim")))
    console.print(
        Text(
            f"Topic: {result.topic} | Cost mode: {result.cost_mode} | "
            f"Fresh item limit: {result.fresh_item_limit}",
            style="dim",
        )
    )
    console.print(Text(f"Profile: {path}\n", style="dim"))

    table = Table(show_header=True, header_style="bold")
    table.add_column("#", justify="right", no_wrap=True)
    table.add_column("Type", no_wrap=True)
    table.add_column("Source", overflow="fold")
    table.add_column("Title", overflow="fold")
    table.add_column("Published", no_wrap=True)

    for index, candidate in enumerate(result.candidates, 1):
        table.add_row(
            str(index),
            candidate.kind,
            Text(candidate.source_label),
            Text(candidate.title),
            candidate.published_at or "",
        )

    console.print(table)
    if result.candidates:
        console.print(Text(f"\nCommands ({command_shell_label()})", style="bold"))
        for index, candidate in enumerate(result.candidates, 1):
            console.print(
                Text.assemble("  ", (f"{index}.", "dim"), " ", command_text(candidate.command))
            )
    console.print(f"\n[dim]Ordering: {result.ordering}[/dim]")
    if result.warnings:
        console.print("\n[yellow]Warnings[/yellow]")
        for warning in result.warnings:
            console.print(Text(f"  {warning.source}: {warning.message}"))


def _render_profile_run(result: ProfileRunResult, path: Path) -> None:
    console.print(Text.assemble("\n", ("Profile Run", "bold"), " ", (result.profile, "dim")))
    console.print(
        Text(
            f"Topic: {result.topic} | Cost mode: {result.cost_mode} | "
            f"Health: {result.health_status}",
            style="dim",
        )
    )
    console.print(Text(f"Profile: {path}", style="dim"))
    console.print(Text(f"State: {result.state_path}\n", style="dim"))

    table = Table(show_header=True, header_style="bold")
    table.add_column("#", justify="right", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Type", no_wrap=True)
    table.add_column("Title", overflow="fold")

    for index, item in enumerate(result.commands, 1):
        status = item.status if not item.skip_reason else f"{item.status}: {item.skip_reason}"
        table.add_row(str(index), Text(status), item.kind, Text(item.title))

    console.print(table)
    if result.commands:
        console.print(Text(f"\nCommands ({command_shell_label()})", style="bold"))
        for index, item in enumerate(result.commands, 1):
            console.print(
                Text.assemble("  ", (f"{index}.", "dim"), " ", command_text(item.command))
            )
    console.print(
        f"\n[dim]Selected: {result.selected_count} | Skipped: {result.skipped_count} | "
        f"Succeeded: {result.succeeded_count} | Failed: {result.failed_count}[/dim]"
    )
    if not result.approved and result.selected_count:
        console.print("\n[yellow]Preview only.[/yellow] Re-run with --yes to execute.")
    if result.failed_count:
        console.print(
            "\n[red]One or more profile commands failed. See the state file for tails.[/red]"
        )
    if result.okf_bundle_dir:
        status = "valid" if result.okf_bundle_valid else "invalid"
        console.print(f"\n[green]OKF bundle ({status}):[/green] {result.okf_bundle_dir}")
        console.print(f"[dim]  distill okf validate {result.okf_bundle_dir}[/dim]")
    if result.warnings:
        console.print("\n[yellow]Warnings[/yellow]")
        for warning in result.warnings:
            console.print(Text(f"  {warning['source']}: {warning['message']}"))


def register(app: typer.Typer) -> None:
    """Attach recurring profile commands."""

    app.add_typer(profile_app, name="profile", rich_help_panel="Discover")
