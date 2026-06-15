"""Discover-panel preview commands, extracted from the _logic monolith.

`distill search` and `distill explore` preview the best recent YouTube videos
Distill would learn from, without ingesting. They delegate to the learning-flow
wrappers (still in _logic, which inject _logic-resident deps into
commands/_learning_flow.py). First slice of the coupled-core Discover extraction.
Registered via register() from distill.cli.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import typer

from distill import cli_shared
from distill._console import console
from distill.cli_shared import require_model as _require_model
from distill.cli_shared import topic_from_query as _topic_from_query
from distill.commands._helpers import (
    _detect_ramp_source,
    _invoke_command,
    _preflight,
    get_config,
)
from distill.commands._learning_flow import (
    validate_learning_options as _validate_learning_options,
)
from distill.commands._logic import (
    _ACCENT,
    _apply_verify_override,
    _discover_fetch_videos,
    _discover_generate_queries,
    _discover_ingest_set,
    _discover_rerank,
    _discover_sizing_flow,
    _display_ranked_discover,
    _is_fresh_topic,
    _preview_learning_selection,
    _process_site_seed,
    _run_concepts_after_ingest,
    _run_learning_command,
    _run_scope_report,
    topic_watch_run,
)
from distill.commands._topic_watch import (
    _normalize_topic_watch_ranking_mode,
    _topic_watch_name,
    _topic_watch_ranking_strategy,
)
from distill.ingestors.papers.arxiv import PaperRecord, search_arxiv_multi
from distill.ingestors.sites.scraper import SiteSeed, load_site_batch
from distill.ingestors.youtube.discovery import VideoInfo
from distill.library import Library
from distill.library.ingested import ingested_source_ids
from distill.library.intent import make_intent, save_intent
from distill.library.paths import find_artifact, site_name_from_url
from distill.pipeline.analysis.site import synthesize_site_topic
from distill.pipeline.costs import CostTracker, estimate_discover_items, load_cost_calibration
from distill.pipeline.discovery import (
    RIGOR_LEVELS,
    detect_score_cliff,
    filter_ingested_candidates,
    rigor_threshold,
)
from distill.pipeline.report.synthesize import run_synthesis
from distill.pipeline.summary import RunSummary, display_summary, log_preview_cost
from distill.pipeline.synthesis.corpus import synthesize_corpus

__all__ = [
    "discover",
    "monitor",
    "ramp_up",
    "register",
    "site_batch_cmd",
    "site_cmd",
    "synthesize_cmd",
]


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
    _require_model()

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
        _require_model()
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
        _require_model()
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


def discover(  # noqa: C901 — legacy, will refactor
    goal: str = typer.Argument(
        "",
        help='Research goal, e.g. "help an AI compose great music". Omit if using --goal-file.',
    ),
    goal_file: Path | None = typer.Option(
        None,
        "--goal-file",
        help="Path to a markdown file whose contents become the goal. Enables reusable, "
        "goal-driven topic refreshes. Overrides the positional argument if both are provided.",
    ),
    topic: str = typer.Option("", "--topic", "-t", help="Topic to file under"),
    paper_limit: int = typer.Option(10, "--paper-limit", help="Max papers to ingest (default: 10)"),
    video_limit: int = typer.Option(10, "--video-limit", help="Max videos to ingest (default: 10)"),
    site_seeds: Path | None = typer.Option(
        None,
        "--site-seeds",
        help="Optional JSON/TXT seed file of curated website URLs to include in the goal-aware rerank",
    ),
    site_limit: int = typer.Option(
        10,
        "--site-limit",
        help="Max curated website seeds to ingest when --site-seeds is provided (default: 10)",
    ),
    papers_only: bool = typer.Option(
        False,
        "--papers-only",
        help="Skip videos entirely (equivalent to --video-limit 0). Use when the topic "
        "has thin or unrigorous YouTube coverage and you only want academic sources.",
    ),
    videos_only: bool = typer.Option(
        False,
        "--videos-only",
        help="Skip papers entirely (equivalent to --paper-limit 0). Use when the topic "
        "is better covered by talks/lectures than by formal papers.",
    ),
    days: int = typer.Option(
        365, "--days", "-d", help="YouTube recency window in days (default: 365)"
    ),
    shorts: bool = typer.Option(
        False, "--shorts/--no-shorts", help="Include short-form videos under 3 minutes"
    ),
    ingest_attachments: bool = typer.Option(
        False,
        "--ingest-attachments",
        help="For selected site seeds, pull PDF text and supported embedded video transcripts into the page corpus",
    ),
    from_gaps: bool = typer.Option(
        False,
        "--from-gaps",
        help="Derive the goal from an existing topic's coverage gaps (requires --topic). "
        "Turns research_gaps into auto-generated discover queries.",
    ),
    rigor: str = typer.Option(
        "balanced",
        "--rigor",
        help="Quality bar for the reranked shortlist: strict | balanced | loose. "
        "Drops candidates whose rerank score is below the level's threshold.",
    ),
    lens: str = typer.Option(
        "",
        "--lens",
        help="Analysis lens for per-source insights: research | practitioner | competitive | "
        "academic | general. Default: inferred from the goal. Persisted as the topic's intent so "
        "later ingests inherit it.",
    ),
    verify: str = typer.Option(
        "",
        "--verify",
        help="Claim-grounding mode for this run: warn | strict | off "
        "(default: the DISTILL_VERIFY setting, else warn).",
    ),
    preview: bool = typer.Option(
        False, "--preview", help="Show the goal-ranked plan without ingesting"
    ),
    from_preview: str = typer.Option(
        "",
        "--from-preview",
        help="Replay and ingest the exact set saved by an earlier --preview run, by its id. "
        "Skips query-generation and the rerank, so you commit to precisely what you saw.",
    ),
    size: bool = typer.Option(
        False,
        "--size",
        help="Force the size-then-approve menu (excellent / good / everything, each with its "
        "spend) even on a topic that already has artifacts. On a fresh topic this is the default.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the interactive confirmation prompt"),
):
    """Goal-aware cross-source discovery: papers + videos, reranked against a goal.

    With ``--from-gaps``, the goal is synthesized from the topic's coverage gaps
    (the inverse of goal-driven discovery): "you are thin on X, single-source on
    Y" becomes "find sources that fill X and Y". With ``--from-preview <id>``, the
    exact shortlist a previous ``--preview`` run saved is ingested verbatim.
    """

    _preflight()
    if from_preview and (from_gaps or preview):
        console.print(
            "[red]--from-preview replays a saved set; it can't combine with "
            "--from-gaps or --preview.[/red]"
        )
        raise typer.Exit(1)
    if rigor not in RIGOR_LEVELS:
        console.print(f"[red]Unknown --rigor '{rigor}'.[/red] Choose: {', '.join(RIGOR_LEVELS)}.")
        raise typer.Exit(1)
    _apply_verify_override(verify)
    if papers_only and videos_only:
        console.print(
            "[red]--papers-only and --videos-only are mutually exclusive. "
            "Pick one, or omit both to discover across both sources.[/red]"
        )
        raise typer.Exit(1)
    if papers_only:
        video_limit = 0
    if videos_only:
        paper_limit = 0
    if paper_limit < 0 or video_limit < 0 or site_limit < 0:
        console.print("[red]Source limits cannot be negative.[/red]")
        raise typer.Exit(1)
    if goal_file is not None:
        if not goal_file.exists():
            console.print(f"[red]Goal file not found: {goal_file}[/red]")
            raise typer.Exit(1)
        goal = goal_file.read_text(encoding="utf-8").strip()
    if from_gaps and not topic:
        console.print("[red]--from-gaps requires --topic <name> to analyze.[/red]")
        raise typer.Exit(1)
    if not goal.strip() and not from_gaps and not from_preview:
        console.print("[red]Goal is empty. Provide a goal argument or --goal-file path.[/red]")
        raise typer.Exit(1)

    config = get_config()
    _require_model()
    tracker = CostTracker()

    if from_preview:
        from distill.pipeline.preview_cache import (
            PreviewCacheError,
            load_preview,
            preview_cache_dir,
        )

        try:
            snapshot = load_preview(preview_cache_dir(config.library_dir), from_preview)
        except PreviewCacheError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        replay_topic = topic or _topic_from_query(snapshot.goal[:80])
        replay_summary = RunSummary(command="discover")
        replay_summary.set_metadata(topic=replay_topic, workflow="discover", source_type="mixed")
        replay_papers = [it for it in snapshot.items if it.kind == "paper"]
        replay_videos = [it for it in snapshot.items if it.kind == "video"]
        replay_sites = [it for it in snapshot.items if it.kind == "site"]
        goal_line = snapshot.goal.splitlines()[0][:120] if snapshot.goal else ""
        console.print(
            f"\n[bold]Replaying previewed set {snapshot.id}[/bold] "
            f"({len(replay_papers)} paper(s), {len(replay_videos)} video(s), "
            f"{len(replay_sites)} site(s)) into topic '{replay_topic}'"
        )
        if goal_line:
            console.print(f"[dim]Goal: {goal_line}[/dim]")
        console.print()
        if snapshot.goal:
            save_intent(
                config.topic_dir(replay_topic), make_intent(snapshot.goal, lens=lens, rigor=rigor)
            )
        _discover_ingest_set(
            topic_name=replay_topic,
            config=config,
            tracker=tracker,
            summary=replay_summary,
            ranked_papers=replay_papers,
            ranked_videos=replay_videos,
            ranked_sites=replay_sites,
            ingest_attachments=ingest_attachments,
            yes=yes,
        )
        return

    if from_gaps:
        from distill.pipeline.gaps import gap_discovery_goal, topic_gap_summary

        gap_summary = topic_gap_summary(config, topic)
        goal = gap_discovery_goal(gap_summary)
        console.print(f"[cyan]Gap-driven discovery for '{topic}'. Detected gaps:[/cyan]")
        for g in gap_summary["gaps"]:
            console.print(f"  [dim]- {g}[/dim]")
        console.print(f"  [dim]Synthesized goal:[/dim] {goal[:160]}...")
        console.print()

    topic_name = topic or _topic_from_query(goal[:80])
    if not preview:
        # Persist the corpus intent so analysis (this run and later ingests into
        # this topic) reads sources with the chosen lens and the goal in context.
        save_intent(config.topic_dir(topic_name), make_intent(goal, lens=lens, rigor=rigor))
    if not from_gaps:
        # Persist the goal<->topic association so catch-up can surface the
        # refresh command on a cadence (the goal-file watch hook). Gap-derived
        # goals are synthetic and refresh via --from-gaps instead.
        from distill.pipeline.goals import save_topic_goal

        save_topic_goal(
            config.library_dir,
            topic_name,
            goal,
            goal_file=str(goal_file) if goal_file is not None else "",
            site_seeds=str(site_seeds) if site_seeds is not None else "",
            now_iso=datetime.now().isoformat(),
        )
    effective_site_limit = site_limit if site_seeds is not None else 0
    if paper_limit <= 0 and video_limit <= 0 and effective_site_limit <= 0:
        console.print(
            "[red]Specify at least one source: papers, videos, or --site-seeds with --site-limit > 0.[/red]"
        )
        raise typer.Exit(1)
    summary = RunSummary(command="discover")
    summary.set_metadata(topic=topic_name, workflow="discover", source_type="mixed")

    sites: list[SiteSeed] = []
    if site_seeds is not None:
        if not site_seeds.exists():
            console.print(f"[red]Site seed file not found: {site_seeds}[/red]")
            raise typer.Exit(1)
        site_batch = load_site_batch(site_seeds, topic_override=topic_name)
        if effective_site_limit > 0:
            sites = site_batch.seeds

    # Goal files can be multi-line; keep console header compact.
    goal_headline = goal.splitlines()[0][:120] if goal else ""
    console.print(f"\n[bold]Discover: {goal_headline}[/bold]")
    if goal_file is not None:
        console.print(f"[dim]Goal loaded from {goal_file}[/dim]")
    console.print(
        f"[dim]Topic: {topic_name} | Papers: {paper_limit} | Videos: {video_limit} | Sites: {effective_site_limit} "
        f"| Days: {days}[/dim]\n"
    )
    if site_seeds is not None:
        console.print(f"[dim]Curated site seeds: {len(sites)} loaded from {site_seeds}[/dim]")
        console.print()

    # When the user has restricted to a single source via --papers-only / --videos-only,
    # don't pay for query generation on the disabled side.
    paper_query_count = 5 if paper_limit > 0 else 0
    video_query_count = 5 if video_limit > 0 else 0
    paper_queries, video_queries = _discover_generate_queries(
        goal, config, tracker, paper_count=paper_query_count, video_count=video_query_count
    )
    if not paper_queries and not video_queries and not sites:
        console.print("[red]Query generation produced no queries. Try a more concrete goal.[/red]")
        raise typer.Exit(1)

    if paper_queries:
        console.print(
            f"[dim]Paper queries ({len(paper_queries)}): {', '.join(paper_queries)}[/dim]"
        )
    if video_queries:
        console.print(
            f"[dim]Video queries ({len(video_queries)}): {', '.join(video_queries)}[/dim]"
        )
    if sites:
        console.print(f"[dim]Curated site candidates: {len(sites)}[/dim]")
    console.print()

    papers: list[PaperRecord] = []
    if paper_queries:
        per_query_cap = max(paper_limit, 8)
        papers = search_arxiv_multi(paper_queries, limit_per_query=per_query_cap, sort="relevance")
        console.print(
            f"[dim]Found {len(papers)} unique papers across {len(paper_queries)} search(es)[/dim]"
        )

    videos: list[VideoInfo] = []
    if video_queries:
        videos = _discover_fetch_videos(
            video_queries, effective_days=days, candidate_cap=20, shorts=shorts
        )
        console.print(
            f"[dim]Found {len(videos)} unique videos across {len(video_queries)} search(es)[/dim]"
        )

    # Corpus-aware dedup: drop searched candidates the topic already contains so
    # rerank slots and ingest spend go to new material, and gap-driven re-runs
    # converge instead of re-suggesting the corpus. Curated site seeds are kept
    # (user-provided intent; the site pipeline reuses unchanged page insights).

    papers, videos, excluded_ingested = filter_ingested_candidates(
        papers, videos, ingested=ingested_source_ids(config.topic_dir(topic_name))
    )
    if excluded_ingested:
        console.print(
            f"[dim]Excluded {excluded_ingested} candidate(s) already in '{topic_name}'.[/dim]"
        )

    if not papers and not videos and not sites:
        if excluded_ingested:
            # A converged corpus is a clean no-op, not an error: every candidate
            # the search surfaced is already ingested.
            console.print(
                f"[green]Corpus is current: every candidate found is already in "
                f"'{topic_name}'.[/green]"
            )
            display_summary(
                summary, cost_tracker=tracker, console=console, log_dir=config.library_dir
            )
            return
        console.print("[red]No candidates found. Broaden the goal or widen --days.[/red]")
        raise typer.Exit(1)

    console.print("\n[dim]Reranking against goal...[/dim]")
    try:
        ranked = _discover_rerank(goal, papers, videos, sites, config, tracker)
    except (TypeError, ValueError) as exc:
        # Malformed rerank output (e.g. a null/non-numeric score) must not crash
        # discover with a traceback; surface a clean error like the empty case.
        console.print(f"[red]Rerank produced malformed output: {exc}[/red]")
        raise typer.Exit(1) from exc
    if not ranked:
        console.print("[red]Rerank produced no ranked items.[/red]")
        raise typer.Exit(1)

    # Preview-as-default: on a fresh topic (or when --size is forced), present the
    # size-then-approve menu instead of auto-applying --rigor. --yes and --preview
    # keep the non-interactive paths below.
    if not preview and not yes and (size or _is_fresh_topic(config, topic_name)):
        _discover_sizing_flow(
            goal=goal,
            topic_name=topic_name,
            config=config,
            tracker=tracker,
            summary=summary,
            ranked=ranked,
            paper_limit=paper_limit,
            video_limit=video_limit,
            site_limit=effective_site_limit,
            ingest_attachments=ingest_attachments,
        )
        return

    # --rigor: drop candidates below the level's rerank-score (final_score) threshold.

    threshold = rigor_threshold(rigor)
    kept = [r for r in ranked if r.final_score >= threshold]
    if not kept:
        console.print(
            f"[yellow]No candidates clear the '{rigor}' bar (score >= {threshold:.2f}). "
            "Try --rigor loose or a broader goal.[/yellow]"
        )
        raise typer.Exit(1)
    if len(kept) < len(ranked):
        console.print(
            f"  [dim]--rigor {rigor}: kept {len(kept)}/{len(ranked)} candidates "
            f"(score >= {threshold:.2f})[/dim]"
        )
    ranked = kept

    # Apply per-source limits after ranking
    ranked_papers = [r for r in ranked if r.kind == "paper"][:paper_limit]
    ranked_videos = [r for r in ranked if r.kind == "video"][:video_limit]
    ranked_sites = [r for r in ranked if r.kind == "site"][:effective_site_limit]
    shortlist = sorted(
        ranked_papers + ranked_videos + ranked_sites,
        key=lambda x: x.final_score,
        reverse=True,
    )

    _display_ranked_discover(shortlist, title=f"Goal-Ranked Corpus Plan ({len(shortlist)} items)")

    # Size the set: the score "cliff" marks the clearly-excellent top, and a
    # metadata-aware, self-calibrating cost estimate shows the likely spend
    # before committing (per-video duration scales the estimate; rates calibrate
    # against cost_log.jsonl history once enough runs accrue).

    cliff = detect_score_cliff([r.final_score for r in shortlist])
    calibration = load_cost_calibration(config.library_dir)
    estimate = estimate_discover_items(
        papers=len(ranked_papers),
        video_durations=[getattr(r.video, "duration", None) for r in ranked_videos],
        sites=len(ranked_sites),
        calibration=calibration,
    )
    console.print(
        f"  [dim]Top {cliff} sit above the score cliff (the clearly-excellent set). "
        f"Estimated ingest cost: {estimate.format()}.[/dim]"
    )
    # Record the shown estimate so the run log carries estimated-vs-actual and
    # `distill costs` can report estimator accuracy.
    summary.estimated_cost = estimate.expected

    if preview:
        from distill.pipeline.preview_cache import preview_cache_dir, save_preview

        snapshot = save_preview(
            preview_cache_dir(config.library_dir),
            goal=goal,
            model="",
            rigor=rigor,
            items=shortlist,
            estimate={
                "expected": estimate.expected,
                "low": estimate.low,
                "high": estimate.high,
                "calibrated": estimate.calibrated,
            },
            now_iso=datetime.now().isoformat(),
        )
        console.print(
            f"\n[dim]Previewed set saved as[/dim] [bold]{snapshot.id}[/bold]. "
            "[dim]Ingest exactly this set with:[/dim]\n"
            f"  [cyan]distill discover --from-preview {snapshot.id} --topic {topic_name}[/cyan]"
        )
        display_summary(
            summary,
            cost_tracker=tracker,
            console=console,
            log_dir=config.library_dir,
            preview=True,
        )
        return

    _discover_ingest_set(
        topic_name=topic_name,
        config=config,
        tracker=tracker,
        summary=summary,
        ranked_papers=ranked_papers,
        ranked_videos=ranked_videos,
        ranked_sites=ranked_sites,
        ingest_attachments=ingest_attachments,
        yes=yes,
    )


def register(app: typer.Typer) -> None:
    """Attach the discover preview commands to the app (called from distill.cli)."""
    app.command(name="synthesize", rich_help_panel="Discover")(synthesize_cmd)
    app.command(name="monitor", rich_help_panel="Discover")(monitor)
    app.command(name="ramp-up", rich_help_panel="Discover")(ramp_up)
    app.command(name="site", rich_help_panel="Discover")(site_cmd)
    app.command(name="site-batch", rich_help_panel="Discover")(site_batch_cmd)
    app.command(rich_help_panel="Discover")(discover)
