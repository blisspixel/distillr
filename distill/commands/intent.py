"""``distill intent`` -- inspect and set a topic's analysis intent.

Extracted from the ``_logic`` monolith (decomposition, how-we-build.md #1).
``intent set/show/clear`` configure a topic's ``CorpusIntent`` (goal, lens,
audience, rigor, budget); the lens shapes how every per-source insight is written,
so setting it once makes all later ingests into the topic read sources through it.
Registered via ``register()`` from ``distill.cli``.
"""

from __future__ import annotations

import typer

from distill._console import console
from distill.commands._helpers import get_config
from distill.library.intent import intent_path, load_intent, make_intent, save_intent

__all__ = ["intent_app", "register"]

intent_app = typer.Typer(
    help=(
        "Inspect and set a topic's analysis intent (goal, lens, audience, rigor).\n\n"
        "The lens shapes how every per-source insight is written; setting it once makes "
        "all later ingests into the topic (papers, latest, discover, MCP) read sources "
        "through it.\n\n"
        "  distill intent set <topic> --lens research\n"
        "  distill intent show <topic>\n"
    ),
    rich_markup_mode="rich",
)


@intent_app.command("set")
def intent_set(
    topic: str = typer.Argument(help="Topic to configure"),
    lens: str = typer.Option(
        "", "--lens", help="research | practitioner | competitive | academic | general"
    ),
    goal: str = typer.Option(
        "",
        "--goal",
        help="Research goal; carried into every analysis prompt so the model adapts to it",
    ),
    audience: str = typer.Option("", "--audience", help="Who reads the output (shapes register)"),
    rigor: str = typer.Option("", "--rigor", help="loose | balanced | strict"),
    budget: float | None = typer.Option(None, "--budget", help="Per-run budget ceiling in USD"),
) -> None:
    """Set or update the analysis intent for a topic (merges with any existing intent)."""
    config = get_config()
    topic_dir = config.topic_dir(topic)
    existing = load_intent(topic_dir)
    merged = make_intent(
        goal or (existing.goal if existing else ""),
        lens=lens or (existing.lens if existing else ""),
        audience=audience or (existing.audience if existing else ""),
        rigor=rigor or (existing.rigor if existing else ""),
        budget_usd=budget if budget is not None else (existing.budget_usd if existing else None),
    )
    path = save_intent(topic_dir, merged)
    console.print(
        f"  Intent for [bold]{topic}[/bold]: lens=[cyan]{merged.lens}[/cyan] rigor={merged.rigor}"
    )
    if merged.goal:
        console.print(f"  [dim]Goal: {merged.goal[:100]}[/dim]")
    console.print(f"  [dim]Saved {path}[/dim]")


@intent_app.command("show")
def intent_show(topic: str = typer.Argument(help="Topic to inspect")) -> None:
    """Show a topic's saved analysis intent."""
    config = get_config()
    intent = load_intent(config.topic_dir(topic))
    if intent is None:
        console.print(
            f"  No saved intent for [bold]{topic}[/bold]; analysis uses the neutral 'general' lens."
        )
        return
    console.print(f"  [bold]{topic}[/bold] intent:")
    console.print(f"    lens:       {intent.lens}")
    console.print(f"    rigor:      {intent.rigor}")
    console.print(f"    audience:   {intent.audience or '[unset]'}")
    budget_str = intent.budget_usd if intent.budget_usd is not None else "[unset]"
    console.print(f"    budget_usd: {budget_str}")
    if intent.goal:
        console.print(f"    goal:       {intent.goal}")


@intent_app.command("clear")
def intent_clear(topic: str = typer.Argument(help="Topic whose intent to remove")) -> None:
    """Remove a topic's saved intent (revert analysis to the neutral default)."""
    config = get_config()
    path = intent_path(config.topic_dir(topic))
    if path.exists():
        path.unlink()
        console.print(f"  Cleared intent for [bold]{topic}[/bold].")
    else:
        console.print(f"  No saved intent for [bold]{topic}[/bold].")


def register(app: typer.Typer) -> None:
    """Attach the intent sub-app to the main app (called from distill.cli)."""
    app.add_typer(intent_app, name="intent", rich_help_panel="Library")
