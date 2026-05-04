"""Web dashboard server command group.

Commands: distill serve
"""

import typer

from distill._cli_impl import serve as _serve_fn

__all__ = ["app"]

app = typer.Typer(help="Local web dashboard.", rich_markup_mode="rich")
app.command(rich_help_panel="View")(_serve_fn)
