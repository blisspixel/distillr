"""Discovery command group.

Commands: distill discover, distill learn, distill explore, distill search,
          distill monitor, distill ramp-up
"""

import typer

from distill.commands._logic import discover as _discover_fn
from distill.commands._logic import explore_cmd as _explore_cmd_fn
from distill.commands._logic import learn_cmd as _learn_cmd_fn
from distill.commands._logic import monitor as _monitor_fn
from distill.commands._logic import ramp_up as _ramp_up_fn
from distill.commands._logic import search_cmd as _search_cmd_fn

__all__ = ["app"]

app = typer.Typer(help="Discovery and learning commands.", rich_markup_mode="rich")
app.command(rich_help_panel="Discover")(_discover_fn)
app.command(name="learn", rich_help_panel="Discover")(_learn_cmd_fn)
app.command(name="explore", rich_help_panel="Discover")(_explore_cmd_fn)
app.command(name="search", rich_help_panel="Discover")(_search_cmd_fn)
app.command(name="monitor", rich_help_panel="Discover")(_monitor_fn)
app.command(name="ramp-up", rich_help_panel="Discover")(_ramp_up_fn)
