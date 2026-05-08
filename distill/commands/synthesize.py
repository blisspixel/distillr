"""Synthesis command group.

Commands: distill synthesize, distill resynthesize
"""

import typer

from distill.commands._logic import resynthesize as _resynthesize_fn
from distill.commands._logic import synthesize_cmd as _synthesize_cmd_fn

__all__ = ["app"]

app = typer.Typer(help="Synthesis and re-synthesis commands.", rich_markup_mode="rich")
app.command(name="synthesize", rich_help_panel="Discover")(_synthesize_cmd_fn)
app.command(rich_help_panel="Maintain")(_resynthesize_fn)
