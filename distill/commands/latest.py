"""Content processing and latest-news command group.

Commands: distill latest, distill run, distill catch-up, distill reanalyze,
          distill channel, distill video
"""

import typer

from distill.commands._logic import catch_up as _catch_up_fn
from distill.commands._logic import channel_cmd as _channel_cmd_fn
from distill.commands._logic import latest_cmd as _latest_cmd_fn
from distill.commands._logic import reanalyze as _reanalyze_fn
from distill.commands._logic import run as _run_fn
from distill.commands._logic import video as _video_fn

__all__ = ["app"]

app = typer.Typer(help="Content processing and latest-news commands.", rich_markup_mode="rich")
app.command(name="latest", rich_help_panel="Discover")(_latest_cmd_fn)
app.command(rich_help_panel="Process")(_run_fn)
app.command(name="catch-up", rich_help_panel="Watch")(_catch_up_fn)
app.command(rich_help_panel="Maintain")(_reanalyze_fn)
app.command(name="channel", rich_help_panel="Process")(_channel_cmd_fn)
app.command(rich_help_panel="Process")(_video_fn)
