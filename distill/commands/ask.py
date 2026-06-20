"""``distill ask`` -- corpus-grounded question answering with verified promotion.

Design: ``docs/design/ask-loop.md``. The output->input half of the compounding
loop: answers are artifacts with receipts, and ``--save`` promotes a verified
answer into the corpus -- refused, never silently, when any load-bearing claim
lacks source support (invariant 8).
"""

from __future__ import annotations

import typer
from rich.markdown import Markdown

from distill._console import console
from distill.commands._helpers import _complete_topics, get_config
from distill.commands._helpers import require_model as _require_model
from distill.pipeline.ask import ask_corpus
from distill.pipeline.costs import CostTracker, save_run_log

__all__ = ["ask_cmd", "register"]


def ask_cmd(
    question: str = typer.Argument(help="The question to answer from the topic's corpus."),
    topic: str = typer.Option(
        ...,
        "--topic",
        "-t",
        help="Topic whose corpus grounds the answer.",
        autocompletion=_complete_topics,
    ),
    save: bool = typer.Option(
        False,
        "--save",
        help="Promote a verified answer into the corpus as a first-class insight "
        "(refused if any load-bearing claim lacks source support).",
    ),
):
    """Answer a question from the corpus, grounded-only, with citation receipts.

    Writes `answers/<slug>_Answer.md` with `[[wiki-links]]` to every cited
    source and a `_Verify.json` sidecar grounding the answer's numbers against
    the retrieved excerpts. `--save` re-ingests a clean answer so synthesis
    and future answers build on it -- the compounding step, verify-gated.
    """
    config = get_config()
    _require_model("qa")
    tracker = CostTracker()

    result = ask_corpus(question, topic=topic, config=config, save=save, tracker=tracker)

    if result.no_coverage:
        console.print(
            f"[yellow]Topic '{topic}' has no matching artifacts for this question.[/yellow] "
            "Ingest sources first (distill discover / papers / latest / ingest)."
        )
        raise typer.Exit(1)

    console.print()
    console.print(Markdown(result.answer_text))
    console.print()
    if result.answer_path is not None:
        console.print(
            f"  [green]Answer[/green]    {result.answer_path.relative_to(config.library_dir)}"
        )
    if result.saved_insight_path is not None:
        console.print(
            f"  [green]Promoted[/green]  {result.saved_insight_path.relative_to(config.library_dir)} "
            "[dim](now part of the corpus)[/dim]"
        )
    elif save and result.save_refused_reason:
        console.print(f"  [red]Not promoted[/red] {result.save_refused_reason}")
    console.print(f"\n  [dim]LLM spend: {tracker.format_cost()}[/dim]")
    save_run_log(config.library_dir, "ask", tracker)


def register(app: typer.Typer) -> None:
    """Register ``ask`` on the given app."""
    app.command(name="ask", rich_help_panel="Understand")(ask_cmd)
