"""Paper ingestion and corpus command group.

Commands: distill paper, distill papers, distill corpus
"""

import typer

from distill.commands._logic import corpus as _corpus_fn
from distill.commands._logic import paper as _paper_fn
from distill.commands._logic import papers as _papers_fn

__all__ = ["app"]

app = typer.Typer(help="Paper ingestion and corpus management.", rich_markup_mode="rich")
app.command(rich_help_panel="Discover")(_paper_fn)
app.command(rich_help_panel="Discover")(_papers_fn)
app.command(rich_help_panel="Maintain")(_corpus_fn)
