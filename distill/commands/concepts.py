"""distill concepts -- per-topic concept and entity playbook command.

Thin Typer wrapper; the body lives in ``distill.commands._logic.concepts``
and the orchestration in ``distill.concepts.run_concepts``.
"""

import typer

from distill.commands._logic import concepts as _concepts_fn

__all__ = ["app"]

app = typer.Typer(
    help="Extract and merge concept playbook notes for a topic.", rich_markup_mode="rich"
)
app.command(rich_help_panel="Library")(_concepts_fn)
