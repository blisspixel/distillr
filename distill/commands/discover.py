"""Discover-panel preview commands, extracted from the _logic monolith.

`distill search` and `distill explore` preview the best recent YouTube videos
Distill would learn from, without ingesting. They delegate to the learning-flow
wrappers (still in _logic, which inject _logic-resident deps into
commands/_learning_flow.py). First slice of the coupled-core Discover extraction.
Registered via register() from distill.cli.
"""

from __future__ import annotations

from pathlib import Path

import typer

from distill._console import console
from distill.cli_shared import require_api_key as _require_api_key
from distill.cli_shared import topic_from_query as _topic_from_query
from distill.commands._helpers import _preflight, get_config
from distill.commands._logic import (
    _apply_verify_override,
    _persist_lens,
    _preview_learning_selection,
    _run_concepts_after_ingest,
    _run_learning_command,
    _validate_learning_options,
)
from distill.pipeline.costs import CostTracker
from distill.pipeline.report.brief import run_research_brief
from distill.pipeline.summary import RunSummary, display_summary, log_preview_cost

__all__ = [
    "brief_cmd",
    "explore_cmd",
    "latest_cmd",
    "learn_cmd",
    "register",
    "research_brief_cmd",
    "search_cmd",
]


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


def research_brief_cmd(
    topics: list[str] = typer.Option(
        ...,
        "--topic",
        "-t",
        help="Topic(s) to include in the briefing. Pass multiple times or comma-separated.",
    ),
    name: str = typer.Option(
        ...,
        "--name",
        "-n",
        help="Output filename stub. Writes to output/briefing-{name}.md.",
    ),
    context: str | None = typer.Option(
        None,
        "--context",
        help="Inline briefing context/instructions. Use --context-file for longer content.",
    ),
    context_file: Path | None = typer.Option(
        None,
        "--context-file",
        help="Path to a markdown file whose contents become the briefing prompt.",
    ),
):
    """Run a multi-topic Gemini Deep Research briefing grounded on existing corpora.

    Unlike `distill report` (4-phase strategic report, one topic) and `distill brief`
    (fast Grok-based single-topic brief), this runs a single Deep Research call
    across one or more topics with a user-supplied context block that shapes the
    briefing for a specific audience, decision, or downstream agent.

    The context file IS the prompt — distill handles file gathering, File Search
    grounding, Deep Research invocation, and output. Cost: ~$3-5 per briefing.

    Example:
        distill research-brief -t rag-research -t vector-dbs \\
            --context-file docs/briefing-contexts/product-decision.md --name rag-q2
    """
    expanded: list[str] = []
    for entry in topics:
        expanded.extend(t.strip() for t in entry.split(",") if t.strip())
    if not expanded:
        console.print("[red]At least one --topic is required[/red]")
        raise typer.Exit(1)

    if context_file:
        if not context_file.exists():
            console.print(f"[red]--context-file not found: {context_file}[/red]")
            raise typer.Exit(1)
        file_text = context_file.read_text(encoding="utf-8")
        context_text = f"{context}\n\n{file_text}" if context else file_text
    else:
        context_text = context or ""

    if not context_text.strip():
        console.print(
            "[red]Provide --context or --context-file — the briefing needs instructions[/red]"
        )
        raise typer.Exit(1)

    config = get_config()
    _require_api_key(config.gemini_api_key, "GEMINI_API_KEY required for Deep Research")

    tracker = CostTracker()
    summary = RunSummary(command="research-brief")
    summary.set_metadata(topic=",".join(expanded), workflow="research-brief")

    try:
        output_path = run_research_brief(
            topics=expanded,
            context=context_text,
            name=name,
            config=config,
            tracker=tracker,
        )
    except Exception as exc:
        summary.add_exception("research-brief", exc, context=",".join(expanded))
        display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
        raise
    if output_path is None:
        summary.add_issue(
            "research-brief",
            "Research briefing did not produce results",
            context=",".join(expanded),
        )
        display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
        raise typer.Exit(1)
    summary.add_output(output_path)
    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)


def learn_cmd(
    query: str = typer.Argument(help="Topic or question to learn from YouTube"),
    topic: str | None = typer.Option(
        None, "--topic", "-t", help="Topic to file under (default: derived from query)"
    ),
    days: int = typer.Option(60, "--days", "-d", help="Recency window in days (default: 60)"),
    hours: int | None = typer.Option(
        None,
        "--hours",
        help="Exact recency window in hours (overrides day precision where possible)",
    ),
    limit: int = typer.Option(
        5, "--limit", "-n", help="How many best-pick videos to process (default: 5)"
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
    save: bool = typer.Option(
        True,
        "--save/--ephemeral",
        help="Save discovered channels into the library (default: save)",
    ),
    report: bool = typer.Option(
        False, "--report", "-r", help="Generate a topic report after processing"
    ),
    test: bool = typer.Option(False, "--test", help="Test mode for research (cheaper)"),
):
    """Learn a topic fast by processing the best recent YouTube videos by default."""
    _validate_learning_options(sort, limit, days, per_channel_cap, hours=hours)
    _run_learning_command(
        query,
        topic=topic,
        days=days,
        limit=limit,
        sort=sort,
        per_channel_cap=per_channel_cap,
        shorts=shorts,
        rerank=rerank,
        save=save,
        report=report,
        test=test,
        generate_brief=False,
        header="Learning",
        hours=hours,
    )


def brief_cmd(
    query: str = typer.Argument(help="Topic or question to learn and turn into a short brief"),
    topic: str | None = typer.Option(
        None, "--topic", "-t", help="Topic to file under (default: derived from query)"
    ),
    days: int = typer.Option(60, "--days", "-d", help="Recency window in days (default: 60)"),
    hours: int | None = typer.Option(
        None,
        "--hours",
        help="Exact recency window in hours (overrides day precision where possible)",
    ),
    limit: int = typer.Option(
        5, "--limit", "-n", help="How many best-pick videos to process (default: 5)"
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
    save: bool = typer.Option(
        True,
        "--save/--ephemeral",
        help="Save discovered channels into the library (default: save)",
    ),
    report: bool = typer.Option(
        False,
        "--report",
        "-r",
        help="Also generate a full topic report after processing",
    ),
    test: bool = typer.Option(False, "--test", help="Test mode for research (cheaper)"),
):
    """Learn a topic and generate a concise markdown brief."""
    _validate_learning_options(sort, limit, days, per_channel_cap, hours=hours)
    _run_learning_command(
        query,
        topic=topic,
        days=days,
        limit=limit,
        sort=sort,
        per_channel_cap=per_channel_cap,
        shorts=shorts,
        rerank=rerank,
        save=save,
        report=report,
        test=test,
        generate_brief=True,
        header="Briefing",
        hours=hours,
    )


def latest_cmd(
    query: str = typer.Argument(help="Topic or question to get current on quickly"),
    topic: str | None = typer.Option(
        None, "--topic", "-t", help="Topic to file under (default: derived from query)"
    ),
    days: int = typer.Option(3, "--days", "-d", help="Recency window in days (default: 3)"),
    hours: int | None = typer.Option(
        None,
        "--hours",
        help="Exact recency window in hours (overrides day precision where possible)",
    ),
    limit: int = typer.Option(
        10, "--limit", "-n", help="How many best-pick videos to process (default: 10)"
    ),
    sort: str = typer.Option("date", "--sort", help="Candidate search order: relevance or date"),
    per_channel_cap: int = typer.Option(3, "--channel-cap", help="Max final picks per channel"),
    shorts: bool = typer.Option(
        True, "--shorts/--no-shorts", help="Include short-form videos under 3 minutes"
    ),
    rerank: bool = typer.Option(
        True,
        "--rerank/--no-rerank",
        help="Use LLM reranking to pick the best videos (default: on)",
    ),
    rigor: str = typer.Option(
        "off",
        "--rigor",
        help="Quality bar on the rerank score: strict | balanced | loose | off (default off). "
        "Drops candidates below the per-source threshold before the channel cap; needs --rerank.",
    ),
    lens: str = typer.Option(
        "",
        "--lens",
        help="Analysis lens for per-source insights: research | practitioner | competitive | "
        "academic | general. Persists as the topic's intent so later ingests inherit it. "
        "Default: the topic's saved intent, else neutral 'general'.",
    ),
    verify: str = typer.Option(
        "",
        "--verify",
        help="Claim-grounding mode for this run: warn | strict | off "
        "(default: the DISTILL_VERIFY setting, else warn).",
    ),
    top_by_date: bool = typer.Option(
        False,
        "--top-by-date",
        help="Pick the most-recently-uploaded videos in the window, ignoring "
        "rerank quality scoring. Use when you literally want 'last N uploads' "
        "rather than relevance- or quality-ranked picks. Implies --no-rerank.",
    ),
    save: bool = typer.Option(
        True,
        "--save/--ephemeral",
        help="Save discovered channels into the library (default: save)",
    ),
    preview: bool = typer.Option(
        False, "--preview", help="Preview the selected set without processing it"
    ),
    report: bool = typer.Option(
        False, "--report", "-r", help="Generate a topic report after processing"
    ),
    brief: bool = typer.Option(
        False, "--brief", help="Generate a concise topic brief after processing"
    ),
    test: bool = typer.Option(False, "--test", help="Test mode for research (cheaper)"),
    concepts_flag: bool = typer.Option(
        False,
        "--concepts",
        help="Run the concept playbook extraction over the topic after ingest succeeds",
    ),
):
    """Opinionated topic-first workflow for getting current fast."""
    from distill.pipeline.discovery import RIGOR_LEVELS_WITH_OFF

    _validate_learning_options(sort, limit, days, per_channel_cap, hours=hours)
    if rigor not in RIGOR_LEVELS_WITH_OFF:
        console.print(
            f"[red]Unknown --rigor '{rigor}'.[/red] Choose: {', '.join(RIGOR_LEVELS_WITH_OFF)}."
        )
        raise typer.Exit(1)
    _apply_verify_override(verify)
    # --top-by-date is the user saying "I want the N most recent uploads, period."
    # Force-disable LLM rerank and query expansion so chronological mode does
    # not quietly spend tokens on ranking/search variants it will ignore.
    effective_rerank = rerank and not top_by_date
    effective_expand = not top_by_date
    if lens:
        _persist_lens(get_config(), topic or _topic_from_query(query), query, lens)
    if preview:
        config, tracker, _selected = _preview_learning_selection(
            query,
            days=days,
            hours=hours,
            limit=limit,
            sort=sort,
            per_channel_cap=per_channel_cap,
            shorts=shorts,
            rerank=effective_rerank,
            header="Latest",
            table_title="Latest Best-Pick Learning Set",
            expand=effective_expand,
            top_by_date=top_by_date,
            rigor=rigor,
        )
        if effective_rerank and not config.xai_api_key:
            console.print(
                "[yellow]XAI_API_KEY missing; used deterministic ranking fallback[/yellow]"
            )
        console.print("\n[dim]Run without `--preview` to process this set.[/dim]")
        log_preview_cost(
            tracker,
            config.library_dir,
            "latest",
            metadata={"topic": topic} if topic else None,
        )
        return

    # Thread concept extraction through the learning workflow's tracker so
    # --concepts spend lands in the same cost_log.jsonl row as the rest of
    # the run, instead of going untracked. Earlier the call site here
    # invoked the concepts helper without a tracker because the learning
    # flow owns its tracker internally and doesn't return it.
    from collections.abc import Callable as _Callable

    post_ingest_callback: _Callable[[str, CostTracker], None] | None = (
        (lambda topic_name, tracker: _run_concepts_after_ingest(topic_name, tracker=tracker))
        if concepts_flag
        else None
    )
    _run_learning_command(
        query,
        topic=topic,
        days=days,
        hours=hours,
        limit=limit,
        sort=sort,
        per_channel_cap=per_channel_cap,
        shorts=shorts,
        rerank=effective_rerank,
        save=save,
        report=report,
        test=test,
        generate_brief=brief,
        header="Latest",
        expand=effective_expand,
        top_by_date=top_by_date,
        post_ingest_callback=post_ingest_callback,
        rigor=rigor,
    )


def register(app: typer.Typer) -> None:
    """Attach the discover preview commands to the app (called from distill.cli)."""
    app.command(name="search", rich_help_panel="Discover")(search_cmd)
    app.command(name="explore", rich_help_panel="Discover")(explore_cmd)
    app.command(name="research-brief", rich_help_panel="Discover")(research_brief_cmd)
    app.command(name="learn", rich_help_panel="Discover")(learn_cmd)
    app.command(name="brief", rich_help_panel="Discover")(brief_cmd)
    app.command(name="latest", rich_help_panel="Discover")(latest_cmd)
