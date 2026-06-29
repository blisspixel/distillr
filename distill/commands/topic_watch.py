# pyright: strict
"""Recurring topic-watch command group."""

from __future__ import annotations

from datetime import datetime

import typer

from distill.cli_shared import (
    console,
)
from distill.cli_shared import (
    require_model as _require_model,
)
from distill.cli_shared import (
    topic_from_query as _topic_from_query,
)
from distill.commands import _learning_flow as _learning_flow_support
from distill.commands._helpers import (
    _complete_topic_watch_names,
    _complete_topics,
    get_config,
    run_preflight,
)
from distill.commands._learning import (
    preview_learning_selection,
    run_learning_command,
)
from distill.commands._topic_changes import (
    collect_topic_change_details,
    topic_trend_label,
    topic_watch_alert_lines,
    write_topic_change_briefing,
    write_watch_alert_digest,
)
from distill.commands._topic_watch import (
    normalize_topic_watch_ranking_mode,
    topic_watch_name,
    topic_watch_ranking_strategy,
)
from distill.library import Library
from distill.pipeline.dashboard_data import (
    load_all_cost_runs as _load_all_cost_runs,
)
from distill.pipeline.dashboard_data import (
    parse_run_datetime as _parse_run_datetime,
)
from distill.pipeline.dashboard_data import (
    topic_watch_budget_messages as _topic_watch_budget_messages,
)
from distill.pipeline.summary import log_preview_cost

_ACCENT = "rgb(100,149,237)"

_preflight = run_preflight
_preview_learning_selection = preview_learning_selection
_run_learning_command = run_learning_command

topic_watch_app = typer.Typer(
    help="Manage your recurring topic watches",
    invoke_without_command=True,
    rich_markup_mode="rich",
)


def register(app: typer.Typer) -> None:
    """Register the topic-watch command group on the root app."""
    app.add_typer(topic_watch_app, name="topic-watch")


@topic_watch_app.callback()
def topic_watch_default(ctx: typer.Context):
    """Show your topic-watch list."""
    if ctx.invoked_subcommand is not None:
        return
    config = get_config()
    lib = Library(config)
    watchlist = lib.get_topic_watchlist()

    if not watchlist:
        console.print()
        console.print("  [dim]No recurring topics configured[/dim]")
        console.print()
        console.print(
            '    distill topic-watch add "Microsoft AI news" --topic microsoft-news --cadence daily'
        )
        console.print()
        return

    console.print()
    max_name = min(max(len(e.name) for e in watchlist), 24)
    for e in watchlist:
        display_name = e.name if len(e.name) <= max_name else e.name[: max_name - 2] + ".."
        padding = " " * (max_name - len(display_name) + 2)
        mode = "report" if e.report else "learn"
        ranking_label = topic_watch_ranking_strategy(e.ranking_mode)["label"]
        trend_label = topic_trend_label(config, e.topic)
        trend_suffix = f" / {trend_label}" if trend_label else ""
        console.print(
            f"  [{_ACCENT}]{display_name}[/{_ACCENT}]{padding}[dim]{e.topic} / {e.cadence} / {e.days}d / {e.limit} picks / {ranking_label} / {mode}{trend_suffix}[/dim]"
        )
        console.print(f"  {' ' * max_name}  [dim]{e.query}[/dim]")

    console.print()
    console.print(f"  [dim]{len(watchlist)} recurring topics  ·  distill topic-watch run[/dim]")
    console.print()


@topic_watch_app.command("add")
def topic_watch_add(
    query: str = typer.Argument(help="Topic query to monitor"),
    name: str | None = typer.Option(None, "--name", help="Stable name for this topic watch"),
    topic: str | None = typer.Option(None, "--topic", "-t", help="Topic to file under"),
    cadence: str = typer.Option("weekly", "--cadence", help="Run cadence: daily or weekly"),
    days: int = typer.Option(7, "--days", "-d", help="Lookback window in days"),
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
):
    """Add a recurring topic watch for stay-current workflows."""
    if cadence not in {"daily", "weekly"}:
        raise typer.BadParameter("--cadence must be 'daily' or 'weekly'")
    ranking_mode = normalize_topic_watch_ranking_mode(ranking)
    _learning_flow_support.validate_learning_options(sort, limit, days, per_channel_cap)

    config = get_config()
    lib = Library(config)
    topic_name = topic or _topic_from_query(query)
    watch_name = topic_watch_name(query, topic_name, name)
    ranking_strategy = topic_watch_ranking_strategy(ranking_mode)

    if lib.add_to_topic_watchlist(
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
    ):
        budget_bits: list[str] = []
        if max_run_cost:
            budget_bits.append(f"max ${max_run_cost:.2f}/run")
        if monthly_budget:
            budget_bits.append(f"${monthly_budget:.2f}/30d")
        budget_suffix = f" / {', '.join(budget_bits)}" if budget_bits else ""
        console.print(
            f"  Watching topic [{_ACCENT}]{watch_name}[/{_ACCENT}]  [dim]{topic_name} / {cadence} / {days}d / {limit} picks / {ranking_strategy['label']}{budget_suffix}[/dim]"
        )
        console.print(f"  [dim]{query}[/dim]")
        console.print()
        console.print(f"  [dim]distill topic-watch run {watch_name}[/dim]")
    else:
        console.print(f"  [dim]{watch_name} already exists[/dim]")


@topic_watch_app.command("remove")
def topic_watch_remove(
    name: str = typer.Argument(help="Topic-watch name", autocompletion=_complete_topic_watch_names),
):
    """Remove a recurring topic watch."""
    config = get_config()
    lib = Library(config)
    if lib.remove_from_topic_watchlist(name):
        console.print(f"  Removed topic watch {name}")
    else:
        console.print(f"  [red]{name} not found on topic-watch list[/red]")


@topic_watch_app.command("days")
def topic_watch_days(
    name: str = typer.Argument(help="Topic-watch name", autocompletion=_complete_topic_watch_names),
    days: int = typer.Argument(help="Lookback days for this topic watch"),
):
    """Set how far back a topic watch looks."""
    config = get_config()
    lib = Library(config)
    if lib.update_topic_watch_days(name, days):
        console.print(f"  [{_ACCENT}]{name}[/{_ACCENT}]  [dim]{days}d lookback[/dim]")
    else:
        console.print(f"  [red]{name} not found on topic-watch list[/red]")


@topic_watch_app.command("cadence")
def topic_watch_cadence(
    name: str = typer.Argument(help="Topic-watch name", autocompletion=_complete_topic_watch_names),
    cadence: str = typer.Argument(help="daily or weekly"),
):
    """Set cadence for a topic watch."""
    if cadence not in {"daily", "weekly"}:
        raise typer.BadParameter("cadence must be 'daily' or 'weekly'")
    config = get_config()
    lib = Library(config)
    if lib.update_topic_watch_cadence(name, cadence):
        console.print(f"  [{_ACCENT}]{name}[/{_ACCENT}]  [dim]{cadence} cadence[/dim]")
    else:
        console.print(f"  [red]{name} not found on topic-watch list[/red]")


@topic_watch_app.command("ranking")
def topic_watch_ranking(
    name: str = typer.Argument(help="Topic-watch name", autocompletion=_complete_topic_watch_names),
    ranking: str = typer.Argument(help="freshness, balanced, or popularity"),
):
    """Set ranking mode for a topic watch."""
    ranking_mode = normalize_topic_watch_ranking_mode(ranking)
    ranking_strategy = topic_watch_ranking_strategy(ranking_mode)
    config = get_config()
    lib = Library(config)
    if lib.update_topic_watch_ranking_mode(name, ranking_mode):
        console.print(f"  [{_ACCENT}]{name}[/{_ACCENT}]  [dim]{ranking_strategy['label']}[/dim]")
    else:
        console.print(f"  [red]{name} not found on topic-watch list[/red]")


@topic_watch_app.command("budget")
def topic_watch_budget(
    name: str = typer.Argument(help="Topic-watch name", autocompletion=_complete_topic_watch_names),
    max_run_cost: float | None = typer.Option(
        None, "--max-run-cost", help="Maximum allowed projected cost for a single run"
    ),
    monthly_budget: float | None = typer.Option(
        None, "--monthly-budget", help="Maximum allowed rolling 30-day spend for this topic"
    ),
):
    """Set budget guardrails for a topic watch."""
    if max_run_cost is None and monthly_budget is None:
        raise typer.BadParameter("Provide --max-run-cost and/or --monthly-budget")
    config = get_config()
    lib = Library(config)
    if lib.update_topic_watch_budget(
        name, max_run_cost=max_run_cost, monthly_budget=monthly_budget
    ):
        parts: list[str] = []
        if max_run_cost is not None:
            parts.append(f"max-run ${max_run_cost:.2f}")
        if monthly_budget is not None:
            parts.append(f"monthly ${monthly_budget:.2f}")
        console.print(f"  [{_ACCENT}]{name}[/{_ACCENT}]  [dim]{' / '.join(parts)}[/dim]")
    else:
        console.print(f"  [red]{name} not found on topic-watch list[/red]")


@topic_watch_app.command("pause")
def topic_watch_pause(
    name: str = typer.Argument(help="Topic-watch name", autocompletion=_complete_topic_watch_names),
):
    """Pause a topic watch without removing it."""
    config = get_config()
    lib = Library(config)
    if lib.set_topic_watch_paused(name, True):
        console.print(f"  Paused {name}")
    else:
        console.print(f"  [red]{name} not found on topic-watch list[/red]")


@topic_watch_app.command("resume")
def topic_watch_resume(
    name: str = typer.Argument(help="Topic-watch name", autocompletion=_complete_topic_watch_names),
):
    """Resume a paused topic watch."""
    config = get_config()
    lib = Library(config)
    if lib.set_topic_watch_paused(name, False):
        console.print(f"  Resumed {name}")
    else:
        console.print(f"  [red]{name} not found on topic-watch list[/red]")


@topic_watch_app.command("run")
def topic_watch_run(  # noqa: C901 - legacy, will refactor
    name: str | None = typer.Argument(
        None, help="Topic-watch name to run", autocompletion=_complete_topic_watch_names
    ),
    topic: str | None = typer.Option(
        None,
        "--topic",
        "-t",
        help="Only run topic watches in this topic",
        autocompletion=_complete_topics,
    ),
    preview: bool = typer.Option(
        False, "--preview", help="Preview the selected best-pick videos without processing"
    ),
    ignore_budget: bool = typer.Option(
        False, "--ignore-budget", help="Run even if budget guardrails would skip the watch"
    ),
):
    """Run recurring topic watches using the existing topic-learning pipeline."""
    _preflight()
    config = get_config()
    _require_model()
    lib = Library(config)
    watchlist = lib.get_topic_watchlist()

    if not watchlist:
        console.print("  [dim]Topic-watch list is empty. Add topics with:[/dim]")
        console.print(
            '    distill topic-watch add "Microsoft AI news" --topic microsoft-news --cadence daily'
        )
        return

    if name:
        match = [e for e in watchlist if e.name.lower() == name.lower()]
        if not match:
            console.print(f"  [red]{name} not on topic-watch list[/red]")
            return
        watchlist = match

    if topic:
        watchlist = [e for e in watchlist if e.topic.lower() == topic.lower()]
        if not watchlist:
            console.print(f"  [red]No watched topics in topic '{topic}'[/red]")
            return

    _ops_log = config.library_dir / ".distill" / "cost_log.jsonl"
    _legacy_log = config.library_dir / "cost_log.jsonl"
    _cost_log = _ops_log if _ops_log.exists() else _legacy_log
    all_cost_entries = _load_all_cost_runs(_cost_log)
    generated_alerts: list[str] = []
    alert_generated_at = datetime.now()

    for entry in watchlist:
        ranking = topic_watch_ranking_strategy(entry.ranking_mode)
        console.print()
        console.print(
            f"[bold]Topic Watch: {entry.name}[/bold] [dim]({entry.topic} / {entry.cadence} / {entry.days}d / {entry.limit} picks / {ranking['label']})[/dim]"
        )
        if entry.paused:
            console.print(
                "  [yellow]Paused[/yellow] [dim]resume with: distill topic-watch resume "
                f"{entry.name}[/dim]"
            )
            continue
        budget_messages = _topic_watch_budget_messages(entry, all_cost_entries)
        if budget_messages and not ignore_budget:
            console.print(f"  [yellow]Budget guardrail[/yellow] {budget_messages[0]}")
            console.print(f"  [dim]distill topic-watch run {entry.name} --ignore-budget[/dim]")
            continue
        if preview:
            preview_config, preview_tracker, _ = _preview_learning_selection(
                entry.query,
                days=entry.days,
                limit=entry.limit,
                sort=str(ranking["sort"]),
                per_channel_cap=entry.channel_cap,
                shorts=False,
                rerank=bool(ranking["rerank"]),
                header=f"Topic Watch Preview: {entry.name}",
                table_title=f"Selected Learning Set: {entry.name}",
            )
            log_preview_cost(
                preview_tracker,
                preview_config.library_dir,
                "topic-watch",
                metadata={"watch": entry.name, "topic": entry.topic or ""},
            )
            continue

        previous_run_at = _parse_run_datetime(entry.last_run_at)
        _run_learning_command(
            entry.query,
            topic=entry.topic,
            days=entry.days,
            limit=entry.limit,
            sort=str(ranking["sort"]),
            per_channel_cap=entry.channel_cap,
            shorts=False,
            rerank=bool(ranking["rerank"]),
            save=True,
            report=entry.report,
            test=False,
            generate_brief=False,
            header=f"Topic Watch: {entry.name}",
        )
        change_details = collect_topic_change_details(
            config,
            Library(config),
            entry.topic,
            previous_run_at,
        )
        change_summary = str(change_details.get("summary", "no recent change detected"))
        briefing_path = write_topic_change_briefing(
            config,
            watch_name=entry.name,
            topic=entry.topic,
            query=entry.query,
            cadence=entry.cadence,
            baseline=previous_run_at,
            summary=change_summary,
            change_details=change_details,
        )
        trend_label = topic_trend_label(config, entry.topic)
        alert_lines = topic_watch_alert_lines(
            watch_name=entry.name,
            topic=entry.topic,
            ranking_label=str(ranking["label"]),
            summary=change_summary,
            change_details=change_details,
            trend_label=trend_label,
        )
        if alert_lines:
            generated_alerts.extend(alert_lines)
        console.print(f"  [cyan]Update[/cyan] {change_summary}")
        if trend_label:
            console.print(f"  [dim]{trend_label}[/dim]")
        console.print(f"  [dim]{briefing_path}[/dim]")
        lib.mark_topic_watch_run(entry.name, datetime.now().isoformat())

    alerts_path = write_watch_alert_digest(
        config,
        generated_at=alert_generated_at,
        alert_lines=generated_alerts,
    )
    if generated_alerts:
        console.print()
        console.print("[bold yellow]Watch Alerts[/bold yellow]")
        for line in generated_alerts[:8]:
            console.print(f"  {line}")
        if len(generated_alerts) > 8:
            console.print(f"  [dim]...and {len(generated_alerts) - 8} more[/dim]")
    else:
        console.print()
        console.print("[dim]No notable watch alerts in this run.[/dim]")
    console.print(f"  [dim]{alerts_path}[/dim]")
