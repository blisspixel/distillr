"""Cost history command group.

Commands: distill costs
"""

import typer

from distill.commands._logic import costs as _costs_fn

__all__ = ["app"]

app = typer.Typer(help="Cost tracking and history.", rich_markup_mode="rich")
app.command(rich_help_panel="Maintain")(_costs_fn)
