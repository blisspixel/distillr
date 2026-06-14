"""Discover-panel preview commands, extracted from the _logic monolith.

`distill search` and `distill explore` preview the best recent YouTube videos
Distill would learn from, without ingesting. They delegate to the learning-flow
wrappers (still in _logic, which inject _logic-resident deps into
commands/_learning_flow.py). First slice of the coupled-core Discover extraction.
Registered via register() from distill.cli.
"""

from __future__ import annotations

import typer

from distill._console import console
from distill.commands._helpers import _preflight
from distill.commands._logic import _preview_learning_selection, _validate_learning_options
from distill.pipeline.summary import log_preview_cost

__all__ = ["explore_cmd", "register", "search_cmd"]


def search_cmd(
    query: str = typer.Argument(help="Topic or question to learn from YouTube"),
    days: int = typer.Option(60, "--days", "-d", help="Recency window in days (default: 60)"),
    hours: int | None = typer.Option(
        None,
        "--hours",
        help="Exact recency window in hours (overrides day precision where possible)",
    ),
    limit: int = typer.Option(
        5, "--limit", "-n", help="How many best-pick videos to show (default: 5)"
    ),
    sort: str = typer.Option(
        "relevance", "--sort", help="Candidate search order: relevance or date"
    ),
    per_channel_cap: int = typer.Option(2, "--channel-cap", help="Max final picks per channel"),
    shorts: bool = typer.Option(
        False, "--shorts/--no-shorts", help="Include short-form videos under 3 minutes"
    ),
    rerank: bool = typer.Option(
        True,
        "--rerank/--no-rerank",
        help="Use LLM reranking to pick the best videos (default: on)",
    ),
):
    """Preview the best recent YouTube videos Distill would learn from."""
    _preflight()
    _validate_learning_options(sort, limit, days, per_channel_cap, hours=hours)
    config, tracker, _selected = _preview_learning_selection(
        query,
        days=days,
        limit=limit,
        sort=sort,
        per_channel_cap=per_channel_cap,
        shorts=shorts,
        rerank=rerank,
        header="Search",
        table_title="Best Videos to Learn From",
        hours=hours,
    )
    if rerank and not config.xai_api_key:
        console.print("[yellow]XAI_API_KEY missing; used deterministic ranking fallback[/yellow]")
    console.print('\n[dim]Run `distill learn "..."` to process these picks.[/dim]')
    log_preview_cost(tracker, config.library_dir, "search")


def explore_cmd(
    query: str = typer.Argument(help="Topic or question to explore on YouTube"),
    days: int = typer.Option(90, "--days", "-d", help="Recency window in days (default: 90)"),
    limit: int = typer.Option(
        10, "--limit", "-n", help="How many ranked videos to show (default: 10)"
    ),
    sort: str = typer.Option(
        "relevance", "--sort", help="Candidate search order: relevance or date"
    ),
    per_channel_cap: int = typer.Option(3, "--channel-cap", help="Max final picks per channel"),
    shorts: bool = typer.Option(
        False, "--shorts/--no-shorts", help="Include short-form videos under 3 minutes"
    ),
    rerank: bool = typer.Option(
        True,
        "--rerank/--no-rerank",
        help="Use LLM reranking to pick the best videos (default: on)",
    ),
):
    """Broader preview mode for exploring a topic before processing it."""
    _preflight()
    _validate_learning_options(sort, limit, days, per_channel_cap)
    config, tracker, _selected = _preview_learning_selection(
        query,
        days=days,
        limit=limit,
        sort=sort,
        per_channel_cap=per_channel_cap,
        shorts=shorts,
        rerank=rerank,
        header="Explore",
        table_title="Broader Topic Coverage",
    )
    if rerank and not config.xai_api_key:
        console.print("[yellow]XAI_API_KEY missing; used deterministic ranking fallback[/yellow]")
    console.print(
        '\n[dim]Run `distill latest "..."` or `distill learn "..."` to process the best set.[/dim]'
    )
    log_preview_cost(tracker, config.library_dir, "explore")


def register(app: typer.Typer) -> None:
    """Attach the discover preview commands to the app (called from distill.cli)."""
    app.command(name="search", rich_help_panel="Discover")(search_cmd)
    app.command(name="explore", rich_help_panel="Discover")(explore_cmd)
