# pyright: strict
from __future__ import annotations

import typer

from distill._console import console
from distill.cli_shared import topic_from_query as _topic_from_query
from distill.commands._helpers import get_config
from distill.commands._learning import (
    preview_learning_selection as _preview_learning_selection,
)
from distill.commands._learning_flow import (
    validate_learning_options as _validate_learning_options,
)
from distill.commands._topic_watch import (
    normalize_topic_watch_ranking_mode,
    topic_watch_name,
    topic_watch_ranking_strategy,
)
from distill.commands.topic_watch import topic_watch_run
from distill.library import Library
from distill.pipeline.summary import log_preview_cost

__all__ = ["monitor"]

_ACCENT = "rgb(100,149,237)"


def monitor(
    query: str = typer.Argument(help="Topic query to monitor on a recurring cadence"),
    topic: str = typer.Option("", "--topic", "-t", help="Topic to file under"),
    name: str = typer.Option("", "--name", help="Explicit watch name"),
    cadence: str = typer.Option("daily", "--cadence", help="Run cadence: daily or weekly"),
    days: int = typer.Option(1, "--days", "-d", help="Lookback window in days"),
    limit: int = typer.Option(10, "--limit", "-n", help="How many best-pick videos to process"),
    sort: str = typer.Option("date", "--sort", help="Candidate search order: relevance or date"),
    per_channel_cap: int = typer.Option(3, "--channel-cap", help="Max final picks per channel"),
    ranking: str = typer.Option(
        "balanced", "--ranking", help="Ranking mode: freshness, balanced, or popularity"
    ),
    report: bool = typer.Option(
        False, "--report", help="Also generate a full topic report when this watch runs"
    ),
    max_run_cost: float = typer.Option(
        0.0, "--max-run-cost", help="Pause this watch if projected run cost exceeds this amount"
    ),
    monthly_budget: float = typer.Option(
        0.0,
        "--monthly-budget",
        help="Pause this watch if projected 30-day spend exceeds this amount",
    ),
    now: bool = typer.Option(False, "--now", help="Run the watch immediately after creating it"),
    preview: bool = typer.Option(
        False, "--preview", help="Preview the selected best-pick videos instead of processing"
    ),
):
    """Create a recurring topic monitor with optional immediate run."""
    if cadence not in {"daily", "weekly"}:
        raise typer.BadParameter("--cadence must be 'daily' or 'weekly'")
    ranking_mode = normalize_topic_watch_ranking_mode(ranking)
    _validate_learning_options(sort, limit, days, per_channel_cap)

    config = get_config()
    lib = Library(config)
    topic_name = topic or _topic_from_query(query)
    watch_name = topic_watch_name(query, topic_name, name or None)
    ranking_strategy = topic_watch_ranking_strategy(ranking_mode)

    created = lib.add_to_topic_watchlist(
        watch_name,
        query,
        topic=topic_name,
        cadence=cadence,
        days=days,
        limit=limit,
        sort=sort,
        channel_cap=per_channel_cap,
        ranking_mode=ranking_mode,
        report=report,
        max_run_cost=max_run_cost,
        monthly_budget=monthly_budget,
    )
    if created:
        console.print(
            f"  Monitoring [{_ACCENT}]{watch_name}[/{_ACCENT}]  [dim]{topic_name} / {cadence} / {days}d / {limit} picks / {ranking_strategy['label']}[/dim]"
        )
        console.print(f"  [dim]{query}[/dim]")
    else:
        console.print(f"  [dim]{watch_name} already exists; using existing watch[/dim]")

    if preview:
        preview_config, preview_tracker, _ = _preview_learning_selection(
            query,
            days=days,
            limit=limit,
            sort=str(ranking_strategy["sort"]),
            per_channel_cap=per_channel_cap,
            shorts=False,
            rerank=bool(ranking_strategy["rerank"]),
            header=f"Monitor Preview: {watch_name}",
            table_title=f"Selected Learning Set: {watch_name}",
        )
        log_preview_cost(
            preview_tracker,
            preview_config.library_dir,
            "monitor",
            metadata={"watch": watch_name, "topic": topic_name or ""},
        )
        return

    if now:
        topic_watch_run(name=watch_name, preview=False, topic=None, ignore_budget=False)
    else:
        console.print()
        console.print(f"  [dim]distill topic-watch run {watch_name}[/dim]")
