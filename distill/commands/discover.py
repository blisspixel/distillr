"""Discover-panel preview commands, extracted from the _logic monolith.

`distill search` and `distill explore` preview the best recent YouTube videos
Distill would learn from, without ingesting. They delegate to the learning-flow
wrappers (still in _logic, which inject _logic-resident deps into
commands/_learning_flow.py). First slice of the coupled-core Discover extraction.
Registered via register() from distill.cli.
"""

from __future__ import annotations

import re
from pathlib import Path

import typer

from distill import cli_shared
from distill._console import console
from distill.cli_shared import require_api_key as _require_api_key
from distill.cli_shared import topic_from_query as _topic_from_query
from distill.commands._helpers import _invoke_command, _preflight, get_config
from distill.commands._logic import (
    _ACCENT,
    _apply_verify_override,
    _detect_ramp_source,
    _normalize_topic_watch_ranking_mode,
    _persist_lens,
    _preview_learning_selection,
    _process_site_seed,
    _run_concepts_after_ingest,
    _run_learning_command,
    _run_scope_report,
    _topic_watch_name,
    _topic_watch_ranking_strategy,
    _validate_learning_options,
    topic_watch_run,
)
from distill.ingestors.sites.scraper import SiteSeed, load_site_batch
from distill.library import Library
from distill.library.paths import find_artifact, site_name_from_url
from distill.pipeline.analysis.site import synthesize_site_topic
from distill.pipeline.costs import CostTracker
from distill.pipeline.report.brief import run_research_brief
from distill.pipeline.report.synthesize import run_synthesis
from distill.pipeline.summary import RunSummary, display_summary, log_preview_cost
from distill.pipeline.synthesis.corpus import synthesize_corpus

__all__ = [
    "brief_cmd",
    "explore_cmd",
    "latest_cmd",
    "learn_cmd",
    "monitor",
    "ramp_up",
    "register",
    "research_brief_cmd",
    "search_cmd",
    "site_batch_cmd",
    "site_cmd",
    "synthesize_cmd",
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


def synthesize_cmd(
    topics: list[str] = typer.Option(
        ...,
        "--topic",
        "-t",
        help="Topic(s) to include. Pass multiple times or comma-separated.",
    ),
    name: str = typer.Option(
        ...,
        "--name",
        "-n",
        help="Output filename stub. Writes to output/synthesis-{name}.md.",
    ),
    context: str | None = typer.Option(None, "--context", help="Inline synthesis instructions."),
    context_file: Path | None = typer.Option(
        None,
        "--context-file",
        help="Path to a markdown file whose contents become the synthesis prompt.",
    ),
    max_tokens: int = typer.Option(
        32768,
        "--max-tokens",
        help="Max output tokens (default 32768 ≈ 120KB of output).",
    ),
):
    """Run a single-call grok-4.3 deep synthesis across one or more topics.

    Best for academic/technical corpus synthesis where the corpus is the ground
    truth and web augmentation would add noise. grok-4.3's 1M-token context
    swallows the full corpus in one call, producing a long-form synthesis
    without the consulting-report compression bias that Deep Research imposes.

    Example:
        distill synthesize -t rag-research,vector-dbs \\
            --context-file docs/briefing-contexts/lit-review.md --name rag-lit
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
            "[red]Provide --context or --context-file — the synthesis needs instructions[/red]"
        )
        raise typer.Exit(1)

    config = get_config()
    _require_api_key(config.xai_api_key, "XAI_API_KEY required for Grok synthesis")

    tracker = CostTracker()
    output_path = run_synthesis(
        topics=expanded,
        context=context_text,
        name=name,
        config=config,
        max_tokens=max_tokens,
        tracker=tracker,
    )
    if output_path is None:
        raise typer.Exit(1)

    summary = tracker.summary_dict()
    console.print(
        f"\n[dim]Tokens: {summary['total_input_tokens']:,} in / "
        f"{summary['total_output_tokens']:,} out — "
        f"Cost: {summary['estimated_total_cost']}[/dim]"
    )


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
    ranking_mode = _normalize_topic_watch_ranking_mode(ranking)
    _validate_learning_options(sort, limit, days, per_channel_cap)

    config = get_config()
    lib = Library(config)
    topic_name = topic or _topic_from_query(query)
    watch_name = _topic_watch_name(query, topic_name, name or None)
    ranking_strategy = _topic_watch_ranking_strategy(ranking_mode)

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


def ramp_up(
    target: str = typer.Argument(help="YouTube query, website URL, or website seed file"),
    topic: str = typer.Option("", "--topic", "-t", help="Topic to file under"),
    source: str = typer.Option("auto", "--source", help="auto, youtube, website, or paper"),
    report: bool = typer.Option(False, "--report", help="Generate a report after processing"),
    days: int = typer.Option(14, "--days", "-d", help="YouTube lookback window in days"),
    limit: int = typer.Option(10, "--limit", "-n", help="YouTube best-pick count"),
    seed_only: bool = typer.Option(
        True, "--seed-only/--crawl", help="For websites, keep to exact seed URLs by default"
    ),
    scrape_only: bool = typer.Option(
        False, "--scrape-only", help="For websites, save raw artifacts only"
    ),
    ingest_attachments: bool = typer.Option(
        False,
        "--ingest-attachments",
        help="For websites, pull PDF text and supported embedded video transcripts into the page corpus",
    ),
    test: bool = typer.Option(False, "--test", help="Pass --test through to report generation"),
):
    """Intent-first entry point for learning a source set quickly."""
    resolved_source = source
    if source == "auto":
        resolved_source = _detect_ramp_source(target)
    elif source == "youtube":
        resolved_source = "youtube-query"
    elif source == "website":
        resolved_source = "website-batch" if Path(target).exists() else "website"
    elif source == "paper":
        resolved_source = "paper"
    else:
        raise typer.BadParameter("--source must be auto, youtube, website, or paper")

    if resolved_source in {"youtube-query", "youtube-url"}:
        _run_learning_command(
            target,
            topic=topic or _topic_from_query(target),
            days=days,
            limit=limit,
            sort="date",
            per_channel_cap=3,
            shorts=False,
            rerank=True,
            save=True,
            report=report,
            test=test,
            generate_brief=False,
            header="Ramp-Up",
        )
        return

    if resolved_source == "paper":
        from distill.commands.papers import paper, papers

        if "arxiv.org" in target.lower() or re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", target):
            paper(target=target, topic=topic or "papers")
        else:
            _invoke_command(
                papers, query=target, topic=topic or _topic_from_query(target), limit=limit
            )
        return

    if resolved_source == "website":
        site_cmd(
            url=target,
            topic=topic or "web",
            name="",
            max_depth=1,
            max_pages=8,
            same_section_only=False,
            scrape_only=scrape_only,
            seed_only=seed_only,
            ingest_attachments=ingest_attachments,
            report=report,
            test=test,
        )
        return

    _invoke_command(
        site_batch_cmd,
        path=Path(target),
        topic=topic or "",
        scrape_only=scrape_only,
        seed_only=seed_only,
        same_section_only=False,
        ingest_attachments=ingest_attachments,
        report=report,
        test=test,
    )


def site_cmd(
    url: str = typer.Argument(help="Website URL to crawl and distill"),
    topic: str = typer.Option("web", "--topic", "-t", help="Topic to file under"),
    name: str = typer.Option("", "--name", help="Optional site name override"),
    max_pages: int = typer.Option(8, "--max-pages", help="Max pages to crawl from this seed"),
    max_depth: int = typer.Option(
        1, "--max-depth", help="How many link hops to follow from the seed"
    ),
    scrape_only: bool = typer.Option(
        False,
        "--scrape-only",
        help="Only save raw page artifacts; skip insights, synthesis, and reports",
    ),
    seed_only: bool = typer.Option(
        False, "--seed-only", help="Only scrape the exact seed URL; do not follow links"
    ),
    same_section_only: bool = typer.Option(
        False,
        "--same-section-only",
        help="When crawling, stay within the seed URL's top-level section (for example /topic, /partner, /lab, /docs)",
    ),
    ingest_attachments: bool = typer.Option(
        False,
        "--ingest-attachments",
        help="Pull PDF text and supported embedded video transcripts into the page corpus",
    ),
    report: bool = typer.Option(
        False, "--report", help="Run Deep Research report after processing"
    ),
    test: bool = typer.Option(False, "--test", help="Pass --test through to report generation"),
):
    """Crawl a website, extract page insights, synthesize, and optionally report."""
    config = get_config()
    if report and scrape_only:
        console.print("[red]--report cannot be used with --scrape-only[/red]")
        raise typer.Exit(2)
    if not scrape_only:
        _require_api_key(config.xai_api_key, "XAI_API_KEY required for website analysis")
    tracker = CostTracker()
    summary = RunSummary(command="site")
    summary.set_metadata(topic=topic, workflow="site", source_type="website")
    seed = SiteSeed(
        url=url,
        topic=topic,
        site_name=name or site_name_from_url(url),
        max_depth=0 if seed_only else max_depth,
        max_pages=1 if seed_only else max_pages,
        same_section_only=same_section_only,
    )
    _process_site_seed(
        seed,
        config,
        tracker,
        summary,
        scrape_only=scrape_only,
        ingest_attachments=ingest_attachments,
    )

    if not scrape_only:
        try:
            topic_synth = synthesize_site_topic(topic, config, tracker=tracker)
            if topic_synth:
                summary.add_output(
                    find_artifact(config.topic_dir(topic), "topic_synthesis", identity=topic)
                )
            corpus_synth = synthesize_corpus(topic, config, tracker=tracker)
            if corpus_synth:
                summary.add_output(
                    find_artifact(config.topic_dir(topic), "corpus_synthesis", identity=topic)
                )
        except Exception as exc:
            cli_shared.record_exception_issue(
                summary,
                stage="site-topic-synthesis",
                exc=exc,
                context=topic,
                details={"topic": topic},
            )

    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
    if report:
        _run_scope_report(topic, config, tracker, scope="topic", test=test, summary=summary)


def site_batch_cmd(
    path: Path = typer.Argument(help="JSON or TXT file containing website URLs/seeds"),
    topic: str = typer.Option("", "--topic", "-t", help="Optional topic override"),
    scrape_only: bool = typer.Option(
        False,
        "--scrape-only",
        help="Only save raw page artifacts; skip insights, synthesis, and reports",
    ),
    seed_only: bool = typer.Option(
        False, "--seed-only", help="Only scrape the exact seed URLs; do not follow links"
    ),
    same_section_only: bool = typer.Option(
        False,
        "--same-section-only",
        help="When crawling, stay within the seed URL's top-level section (for example /topic, /partner, /lab, /docs)",
    ),
    ingest_attachments: bool = typer.Option(
        False,
        "--ingest-attachments",
        help="Pull PDF text and supported embedded video transcripts into the page corpus",
    ),
    report: bool = typer.Option(
        False, "--report", help="Run Deep Research report after processing"
    ),
    test: bool = typer.Option(False, "--test", help="Pass --test through to report generation"),
    concepts_flag: bool = typer.Option(
        False,
        "--concepts",
        help="Run the concept playbook extraction over the topic after ingest succeeds",
    ),
):
    """Process a simple list or JSON config of websites."""
    config = get_config()
    if report and scrape_only:
        console.print("[red]--report cannot be used with --scrape-only[/red]")
        raise typer.Exit(2)
    if not scrape_only:
        _require_api_key(config.xai_api_key, "XAI_API_KEY required for website analysis")
    batch = load_site_batch(path, topic_override=topic)
    tracker = CostTracker()
    summary = RunSummary(command="site-batch")
    summary.set_metadata(topic=topic, workflow="site-batch", source_type="website")

    for seed in batch.seeds:
        adjusted_seed = SiteSeed(
            url=seed.url,
            topic=seed.topic,
            site_name=seed.site_name,
            label=seed.label,
            max_depth=0 if seed_only else seed.max_depth,
            max_pages=1 if seed_only else seed.max_pages,
            same_section_only=same_section_only or seed.same_section_only,
        )
        _process_site_seed(
            adjusted_seed,
            config,
            tracker,
            summary,
            scrape_only=scrape_only,
            ingest_attachments=ingest_attachments,
        )

    target_topic = topic or batch.topic
    if not scrape_only:
        try:
            topic_synth = synthesize_site_topic(target_topic, config, tracker=tracker)
            if topic_synth:
                summary.add_output(
                    find_artifact(
                        config.topic_dir(target_topic),
                        "topic_synthesis",
                        identity=target_topic,
                    )
                )
            corpus_synth = synthesize_corpus(target_topic, config, tracker=tracker)
            if corpus_synth:
                summary.add_output(
                    find_artifact(
                        config.topic_dir(target_topic),
                        "corpus_synthesis",
                        identity=target_topic,
                    )
                )
        except Exception as exc:
            cli_shared.record_exception_issue(
                summary,
                stage="site-topic-synthesis",
                exc=exc,
                context=target_topic,
                details={"topic": target_topic},
            )

    if concepts_flag:
        _run_concepts_after_ingest(target_topic, tracker=tracker)
    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
    if report:
        _run_scope_report(target_topic, config, tracker, scope="topic", test=test, summary=summary)


def register(app: typer.Typer) -> None:
    """Attach the discover preview commands to the app (called from distill.cli)."""
    app.command(name="search", rich_help_panel="Discover")(search_cmd)
    app.command(name="explore", rich_help_panel="Discover")(explore_cmd)
    app.command(name="research-brief", rich_help_panel="Discover")(research_brief_cmd)
    app.command(name="learn", rich_help_panel="Discover")(learn_cmd)
    app.command(name="brief", rich_help_panel="Discover")(brief_cmd)
    app.command(name="latest", rich_help_panel="Discover")(latest_cmd)
    app.command(name="synthesize", rich_help_panel="Discover")(synthesize_cmd)
    app.command(name="monitor", rich_help_panel="Discover")(monitor)
    app.command(name="ramp-up", rich_help_panel="Discover")(ramp_up)
    app.command(name="site", rich_help_panel="Discover")(site_cmd)
    app.command(name="site-batch", rich_help_panel="Discover")(site_batch_cmd)
