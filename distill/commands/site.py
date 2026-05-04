"""Website crawling and ingestion command group.

Commands: distill site, distill site-batch
"""

import typer

from distill._cli_impl import site_batch_cmd as _site_batch_cmd_fn
from distill._cli_impl import site_cmd as _site_cmd_fn

__all__ = ["app"]

app = typer.Typer(help="Website crawling and ingestion.", rich_markup_mode="rich")
app.command(name="site", rich_help_panel="Discover")(_site_cmd_fn)
app.command(name="site-batch", rich_help_panel="Discover")(_site_batch_cmd_fn)
