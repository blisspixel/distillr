# pyright: strict
"""Top-level CLI callback for bare ``distill`` and global options."""

from __future__ import annotations

import os
import sys

import typer
from rich.markup import escape

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
    "get_provider_override",
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
    model: str = typer.Option(
        "",
        "--model",
        "-m",
        help="Override model for all workloads (cloud ids may auto-select provider)",
    ),
    provider: str = typer.Option(
        "",
        "--provider",
        "-p",
        help="Override analysis provider for all workloads (xai, gemini, anthropic, ollama, ...)",
    ),
    role: str = typer.Option(
        "",
        "--role",
        help="Local model role for this run: fast | standard | deep | unfiltered",
    ),
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

    initial_provider_environment = {
        name: os.environ.get(name, "")
        for name in (
            "DISTILL_PROVIDER",
            "DISTILL_ANALYSIS_PROVIDER",
            "XAI_API_KEY",
        )
    }
    # In --json mode, redirect all human/progress/diagnostic output to stderr so
    # stdout carries only the JSON envelope. Called every invocation so a reused
    # process resets the stream instead of leaking a prior redirect.
    model = _apply_role_override(role, model)
    effective_debug = _apply_output_mode(
        ctx,
        quiet=quiet,
        verbose=verbose,
        debug=debug,
        json_output=json_output,
        model=model,
        provider=provider,
    )
    _apply_cost_mode_override(cost_mode)
    ctx.obj["initial_provider_environment"] = initial_provider_environment
    ctx.obj["pre_dotenv_environment_keys"] = tuple(os.environ)

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
        # Global JSON mode is also a dashboard read surface. Emit one envelope
        # and keep stderr free of the human banner and panels.
        if json_output:
            from distill.commands.dashboard import show_dashboard

            show_dashboard()
            return
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


def get_provider_override(ctx: typer.Context | None = None) -> str:
    """Get the --provider override from the CLI context, if set."""
    if ctx and ctx.obj:
        return ctx.obj.get("provider", "")
    return ""


def _apply_role_override(role: str, model: str) -> str:
    """Resolve ``--role`` to a model id, unless ``--model`` already named one.

    An explicit ``--model`` always wins: naming a model is more specific than
    naming a role, and silently overriding it would make the more precise flag
    the weaker one. An unconfigured role is a usage error rather than a silent
    fallback -- falling back would run the wrong brain without saying so.
    """
    # These annotations describe the Typer-parsed contract, not a runtime
    # guarantee: the callback is also invoked directly (tests, internal callers),
    # where an unpassed option arrives as Typer's OptionInfo sentinel. Dropping
    # these checks makes a direct call raise AttributeError on .strip().
    if not isinstance(role, str) or not role.strip():  # pyright: ignore[reportUnnecessaryIsInstance]  -- runtime sentinel, not str
        return model
    requested = role.strip().lower()
    from distill.commands._json import ExitCode
    from distill.llm.model_roles import ROLES, resolve_role_model

    if requested not in ROLES:
        console.print(f"[red]Unknown --role '{escape(role)}'.[/red] Choose: {', '.join(ROLES)}.")
        raise typer.Exit(ExitCode.USAGE_ERROR)
    if isinstance(model, str) and model.strip():  # pyright: ignore[reportUnnecessaryIsInstance]  -- runtime sentinel, not str
        return model  # --model is the more specific instruction
    resolved = resolve_role_model(requested)
    if not resolved:
        console.print(
            f"[red]No model assigned to the '{requested}' role.[/red] "
            f"Set it with `distill roles set {requested} <model-id>`, "
            f"or see suggestions with `distill roles`."
        )
        raise typer.Exit(ExitCode.CONFIG_ERROR)
    return resolved
