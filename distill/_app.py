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
else:
    TyperClickCommand = click.Command
    TyperClickContext = click.Context


class DistillGroup(TyperGroup):
    """Command group that suggests the nearest command on a typo.

    Click's default for an unknown command is a bare "No such command 'x'".
    This appends a "Did you mean ...?" line (the clig.dev convention) using a
    difflib closest-match over the registered command names, so ``distill
    papres`` points at ``papers`` instead of dead-ending. Suggestion only; the
    original usage error and its exit code are unchanged.
    """

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


_HELP = (
    "Distill source material into usable intelligence.\n\n"
    "First-time setup (API-billed routes refused):\n"
    "  distill --cost-mode no-metered init\n"
    "      guided .env, provider, and browser setup\n"
    "  distill --cost-mode no-metered doctor\n"
    "      readiness check without API-billed provider probes\n"
    '  distill --cost-mode no-metered papers "topic" -n 5 --preview\n'
    "      shortlist without paper ingest; refuses ambiguous billing\n\n"
    "Cloud key validation requires explicit permission:\n"
    "  distill --cost-mode paid-ok init\n\n"
    "Then pick a starting point:\n"
    '  Build a topic corpus?   distill topic create "Microsoft Fabric best practices" --videos 10 --papers 10\n'
    '  Have one YouTube URL?  distill video "https://www.youtube.com/watch?v=..."\n'
    "  Have one website URL?  distill site https://example.com/page --topic scratch --seed-only\n"
    "  Have one paper URL?    distill paper https://arxiv.org/abs/2602.12670 --topic papers\n"
    '  Need the latest on a topic?  distill latest "Microsoft AI news" --topic microsoft-news\n'
    '  Want recurring updates?      distill monitor "Microsoft AI news" --topic microsoft-news\n'
)

app = typer.Typer(
    cls=DistillGroup,
    help=_HELP,
    invoke_without_command=True,
    rich_markup_mode="rich",
)
