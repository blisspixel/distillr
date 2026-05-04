"""Content processing and latest-news command group.

Commands: distill latest, distill run, distill catch-up, distill reanalyze,
          distill channel, distill video
"""

import typer

from distill._cli_impl import catch_up as _catch_up_fn
from distill._cli_impl import channel_cmd as _channel_cmd_fn
from distill._cli_impl import latest_cmd as _latest_cmd_fn
from distill._cli_impl import reanalyze as _reanalyze_fn
from distill._cli_impl import run as _run_fn
from distill._cli_impl import video as _video_fn

__all__ = ["app"]

app = typer.Typer(help="Content processing and latest-news commands.", rich_markup_mode="rich")
app.command(name="latest", rich_help_panel="Discover")(_latest_cmd_fn)
app.command(rich_help_panel="Process")(_run_fn)
app.command(name="catch-up", rich_help_panel="Watch")(_catch_up_fn)
app.command(rich_help_panel="Maintain")(_reanalyze_fn)
app.command(name="channel", rich_help_panel="Process")(_channel_cmd_fn)
app.command(rich_help_panel="Process")(_video_fn)
