"""Dashboard and status command group.

Commands: distill dashboard, distill status
"""

import typer

from distill.commands._logic import dashboard as _dashboard_fn
from distill.commands._logic import status as _status_fn

__all__ = ["app"]

app = typer.Typer(help="Dashboard and library status.", rich_markup_mode="rich")
app.command(rich_help_panel="Maintain")(_dashboard_fn)
app.command(rich_help_panel="Maintain")(_status_fn)
