"""Research brief command group.

Commands: distill research-brief
"""

import typer

from distill._cli_impl import research_brief_cmd as _research_brief_cmd_fn

__all__ = ["app"]

app = typer.Typer(help="Research brief generation.", rich_markup_mode="rich")
app.command(name="research-brief", rich_help_panel="Discover")(_research_brief_cmd_fn)
