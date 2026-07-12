# pyright: strict
"""Top-level CLI callback for bare ``distill`` and global options."""

from __future__ import annotations

import sys

import typer

from distill._app import app
from distill._version import get_version
from distill.banner import show_banner
from distill.cli_shared import console
from distill.commands._helpers import (
    _apply_cost_mode_override,
    _apply_output_mode,
    get_config,
)

__all__ = [
    "_default",
    "_version_callback",
    "console",
    "default_callback",
    "get_model_override",
    "show_banner",
]


def _version_callback(value: bool) -> None:
    """Eager ``--version`` handler: print the version to stdout and exit 0.

    Eager so it works before any subcommand wiring or config load. An agent
    or bug report can read the version without a configured environment.
    """
    if value:
        typer.echo(get_version())
        raise typer.Exit()


@app.callback()
def default_callback(
    ctx: typer.Context,
    debug: bool = typer.Option(False, "--debug", help="Enable DEBUG-level logging to console"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress human output"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose logging"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON to stdout"),
    model: str = typer.Option("", "--model", "-m", help="Override model for all workloads"),
    cost_mode: str = typer.Option("", "--cost-mode", help="Override cost policy"),
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show the installed distill version and exit",
        callback=_version_callback,
        is_eager=True,
    ),
):
    """Distill - YouTube channels to strategic intelligence."""
    from distill._logging import configure_logging

    # In --json mode, redirect all human/progress/diagnostic output to stderr so
    # stdout carries only the JSON envelope. Called every invocation so a reused
    # process resets the stream instead of leaking a prior redirect.
    effective_debug = _apply_output_mode(
        ctx,
        quiet=quiet,
        verbose=verbose,
        debug=debug,
        json_output=json_output,
        model=model,
    )
    _apply_cost_mode_override(cost_mode)

    try:
        ops_dir = get_config().library_dir / ".distill"
    except Exception:
        ops_dir = None
    from distill.llm.run_context import update_current_run

    update_current_run(
        command=ctx.invoked_subcommand or "dashboard",
        ops_dir=ops_dir,
    )
    configure_logging(debug=effective_debug, ops_dir=ops_dir)

    if ctx.invoked_subcommand is None:
        # Only clear the screen for an interactive terminal. Clearing captured
        # output emits escape codes into agent and loop logs.
        if sys.stdout.isatty():
            console.clear()
        show_banner(console)
        # Lazy import keeps dashboard ownership separate from root wiring.
        from distill.commands.dashboard import show_dashboard

        show_dashboard()


_default = default_callback


def get_model_override(ctx: typer.Context | None = None) -> str:
    """Get the --model override from the CLI context, if set."""
    if ctx and ctx.obj:
        return ctx.obj.get("model", "")
    return ""
