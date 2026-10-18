"""The top-level Typer ``app`` and its command-group class.

Pulled out of the ``_logic`` monolith so the app's construction is small and
reusable and ``_logic`` shrinks toward the ROADMAP's "cli.py is wiring" goal.
Foundational: imports only typer/click/difflib, nothing from ``distill``, so it
sits at the bottom of the import graph beside ``_console`` / ``_bootstrap``.
"""

# pyright: strict

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING

import click
import typer
from typer.core import TyperGroup

if TYPE_CHECKING:
    from typer._click.core import Command as TyperClickCommand
    from typer._click.core import Context as TyperClickContext
    from typer._click.formatting import HelpFormatter as TyperHelpFormatter
else:
    TyperClickCommand = click.Command
    TyperClickContext = click.Context
    TyperHelpFormatter = click.HelpFormatter


class DistillGroup(TyperGroup):
    """Command group that suggests the nearest command on a typo.

    Click's default for an unknown command is a bare "No such command 'x'".
    This appends a "Did you mean ...?" line (the clig.dev convention) using a
    difflib closest-match over the registered command names, so ``distill
    papres`` points at ``papers`` instead of dead-ending. Suggestion only; the
    original usage error and its exit code are unchanged.
    """

    def format_help(self, ctx: TyperClickContext, formatter: TyperHelpFormatter) -> None:
        if ctx.parent is not None:
            super().format_help(ctx, formatter)
            return
        formatter.write_usage(ctx.command_path, "[OPTIONS] COMMAND [ARGS]...")
        formatter.write_paragraph()
        formatter.write_text(
            "A research desk with current sources, inspectable receipts, and a Markdown corpus."
        )
        with formatter.section("Options"):
            records = [parameter.get_help_record(ctx) for parameter in self.get_params(ctx)]
            formatter.write_dl([record for record in records if record is not None])
        panels = {
            "Start": {"init", "doctor", "provider", "update"},
            "Add sources": {
                "ingest",
                "paper",
                "papers",
                "video",
                "channel",
                "site",
                "site-batch",
                "discover",
                "topic",
                "ramp-up",
                "learn",
            },
            "Keep current": {"watch", "topic-watch", "monitor", "latest", "catch-up", "profile"},
            "Read and ask": {
                "ask",
                "show",
                "synthesize",
                "synthesis",
                "report",
                "export",
                "serve",
                "library",
                "videos",
                "findings",
                "diff",
                "trends",
                "dashboard",
                "research-brief",
            },
            "Check": {"audit", "costs", "status", "bench", "eval"},
            "Operate": set[str](),
        }
        grouped: dict[str, list[str]] = {panel: [] for panel in panels}
        for command in self.list_commands(ctx):
            panel = next(
                (name for name, commands in panels.items() if command in commands), "Operate"
            )
            grouped[panel].append(command)
        for name, commands in grouped.items():
            with formatter.section(name):
                formatter.write_text(", ".join(commands))
        formatter.write_paragraph()
        formatter.write_text(
            "Start: distill --cost-mode no-metered init\nModels: distill provider list\nDetails: distill COMMAND --help or docs/usage.md"
        )

    def resolve_command(
        self, ctx: TyperClickContext, args: list[str]
    ) -> tuple[str | None, TyperClickCommand | None, list[str]]:
        if not args:
            return None, None, []
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError as exc:
            typed = args[0]
            matches = difflib.get_close_matches(typed, self.list_commands(ctx), n=3, cutoff=0.5)
            if matches and exc.message:
                hint = matches[0] if len(matches) == 1 else ", ".join(matches)
                exc.message = f"{exc.message}\n\nDid you mean: {hint}?"
            raise


_HELP = "Current sources, inspectable receipts, and a plain-Markdown research corpus."

app = typer.Typer(
    cls=DistillGroup,
    help=_HELP,
    invoke_without_command=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)
