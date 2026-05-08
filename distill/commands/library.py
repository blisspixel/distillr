"""Library management command group.

Commands: distill add, distill remove, distill library, distill videos,
          distill show, distill package-latest, distill synthesis,
          distill findings, distill diff, distill trends, distill open
"""

import typer

from distill.commands._logic import add as _add_fn
from distill.commands._logic import diff as _diff_fn
from distill.commands._logic import findings as _findings_fn
from distill.commands._logic import library_cmd as _library_cmd_fn
from distill.commands._logic import open_cmd as _open_cmd_fn
from distill.commands._logic import package_latest as _package_latest_fn
from distill.commands._logic import remove as _remove_fn
from distill.commands._logic import show as _show_fn
from distill.commands._logic import synthesis as _synthesis_fn
from distill.commands._logic import trends as _trends_fn
from distill.commands._logic import videos as _videos_fn

__all__ = ["app"]

app = typer.Typer(help="Library management and viewing.", rich_markup_mode="rich")
app.command(rich_help_panel="Library")(_add_fn)
app.command(rich_help_panel="Library")(_remove_fn)
app.command(name="library", rich_help_panel="Library")(_library_cmd_fn)
app.command(rich_help_panel="Library")(_videos_fn)
app.command(rich_help_panel="View")(_show_fn)
app.command(name="package-latest", rich_help_panel="View")(_package_latest_fn)
app.command(rich_help_panel="View")(_synthesis_fn)
app.command(rich_help_panel="View")(_findings_fn)
app.command(rich_help_panel="View")(_diff_fn)
app.command(rich_help_panel="View")(_trends_fn)
app.command(name="open", rich_help_panel="Maintain")(_open_cmd_fn)
