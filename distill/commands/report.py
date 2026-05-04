"""Report and export command group.

Commands: distill report, distill brief, distill export
"""

import typer

from distill._cli_impl import brief_cmd as _brief_cmd_fn
from distill._cli_impl import export as _export_fn
from distill._cli_impl import report as _report_fn

__all__ = ["app"]

app = typer.Typer(help="Report generation and export.", rich_markup_mode="rich")
app.command(rich_help_panel="Reports")(_report_fn)
app.command(name="brief", rich_help_panel="Discover")(_brief_cmd_fn)
app.command(rich_help_panel="Reports")(_export_fn)
