# pyright: strict
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import typer
from rich.text import Text

from distill import cli_shared
from distill._console import console
from distill.cli_shared import require_model as _require_model
from distill.cli_shared import topic_from_query as _topic_from_query
from distill.commands import _discover_options
from distill.commands._concept_ingest import (
    run_concepts_after_ingest as _run_concepts_after_ingest,
)
from distill.commands._discover_flow import (
    _discover_fetch_videos,
    _discover_generate_queries,
    _discover_ingest_set,
    _discover_rerank,
    _discover_sizing_flow,
    _display_ranked_discover,
    _is_fresh_topic,
)
from distill.commands._discover_sites import (
    load_discover_site_candidates,
    show_discover_site_summary,
)
from distill.commands._helpers import (
    _apply_verify_override,
    budgeted_cost_tracker,
    enforce_projected_workflow_budget,
    get_config,
    quote_cli_value,
    save_command_cost,
)
from distill.commands._helpers import (
    detect_ramp_source as _detect_ramp_source,
)
from distill.commands._helpers import (
    invoke_command as _invoke_command,
)
from distill.commands._helpers import (
    run_preflight as _preflight,
)
from distill.commands._helpers import (
    run_scope_report as _run_scope_report,
)
from distill.commands._json import emit_json, json_mode_active
from distill.commands._learning import (
    run_learning_command as _run_learning_command,
)
from distill.commands._site_batch import (
    estimate_site_batch_plan_cost,
    print_site_batch_plan,
    process_site_batch_seed,
    resolve_site_batch_seeds,
    run_site_batch_syntheses,
    site_batch_plan_payload,
)
from distill.commands._site_ingest import process_site_seed as _process_site_seed
from distill.commands.monitor import monitor
from distill.ingestors.papers.arxiv import PaperRecord, search_arxiv_multi
from distill.ingestors.sites.discovery import (
    discover_trusted_site_seeds as _discover_trusted_site_seeds,
)
from distill.ingestors.sites.scraper import SiteSeed, load_site_batch
from distill.ingestors.youtube.discovery import VideoInfo
from distill.library.ingested import ingested_source_ids
from distill.library.intent import make_intent, save_intent
from distill.library.paths import find_artifact, site_name_from_url
from distill.llm.cost_policy import CostPolicyError
from distill.llm.errors import ProviderBusyTimeoutError
from distill.llm.router import RouterConfig
from distill.pipeline.analysis.site import synthesize_site_topic
from distill.pipeline.costs import (
    BudgetExceededError,
    estimate_discover_items,
    estimate_synthesis_workflow_cost,
    load_cost_calibration,
)
from distill.pipeline.discovery import (
    RIGOR_LEVELS,
    detect_score_cliff,
    filter_ingested_candidates,
    format_video_content_stats,
    rigor_threshold,
    summarize_video_content,
)
from distill.pipeline.report.synthesize import run_synthesis
from distill.pipeline.summary import BatchProgress, RunSummary, display_summary
from distill.pipeline.synthesis.corpus import synthesize_corpus
from distill.target_safety import is_http_url, require_local_filesystem_target

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
    """Run a single-call Grok deep synthesis across one or more topics.

    Best for academic/technical corpus synthesis where the corpus is the ground
    truth and web augmentation would add noise. The configured model's context
    swallows the full corpus in one call, producing a long-form synthesis
    without the consulting-report compression bias that Deep Research imposes.
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
            "[red]Provide --context or --context-file - the synthesis needs instructions[/red]"
        )
        raise typer.Exit(1)

    config = get_config()
    _require_model()

    projected_cost = estimate_synthesis_workflow_cost(
        router_config=RouterConfig(),
    )
    enforce_projected_workflow_budget(config, "synthesize", projected_cost)
    tracker = budgeted_cost_tracker(config, "synthesize")
    try:
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
            f"{summary['total_output_tokens']:,} out - "
            f"Cost: {summary['estimated_total_cost']}[/dim]"
        )
    finally:
        save_command_cost(
            config,
            "synthesize",
            tracker,
            metadata={
                "topic": ",".join(expanded),
                "workflow": "synthesize",
                "source_type": "mixed",
                "name": name,
            },
            estimated_cost=projected_cost,
        )


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
    try:
        require_local_filesystem_target(target)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="target") from None
    if source == "auto":
        resolved_source = _detect_ramp_source(target)
    elif source == "youtube":
        resolved_source = "youtube-query"
    elif source == "website":
        resolved_source = (
            "website-batch" if not is_http_url(target) and Path(target).exists() else "website"
        )
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
    crawl_prefix: str = _discover_options.SITE_CRAWL_PREFIX_OPTION,
    ingest_attachments: bool = typer.Option(
        False,
        "--ingest-attachments",
        help="Pull PDF text and supported embedded video transcripts into the page corpus",
    ),
    report: bool = typer.Option(False, "--report", help="Run report after processing"),
    test: bool = typer.Option(False, "--test", help="Pass --test through to report generation"),
):
    """Crawl a website, extract page insights, synthesize, and optionally report."""
    config = get_config()
    if report and scrape_only:
        console.print("[red]--report cannot be used with --scrape-only[/red]")
        raise typer.Exit(2)
    seed = SiteSeed(
        url=url,
        topic=topic,
        site_name=name or site_name_from_url(url),
        max_depth=0 if seed_only else max_depth,
        max_pages=1 if seed_only else max_pages,
        crawl_prefix=crawl_prefix,
        same_section_only=same_section_only,
    )
    projected_cost: float | None = None
    ledger_estimate: float | None = None
    if not scrape_only:
        router_config = RouterConfig()
        ledger_estimate = estimate_site_batch_plan_cost(
            [seed],
            router_config=router_config,
        )
        projected_cost = estimate_site_batch_plan_cost(
            [seed],
            include_report=report,
            router_config=router_config,
        )
        enforce_projected_workflow_budget(config, "site", projected_cost)
        _require_model()
    tracker = budgeted_cost_tracker(config, "site")
    summary = RunSummary(command="site")
    summary.set_metadata(topic=topic, workflow="site", source_type="website")
    summary.estimated_cost = ledger_estimate
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
            site_synth = synthesize_site_topic(topic, config, tracker=tracker)
            if site_synth:
                summary.add_output(
                    find_artifact(config.topic_dir(topic), "site_synthesis", identity=topic)
                )
            corpus_synth = synthesize_corpus(topic, config, tracker=tracker)
            if corpus_synth:
                summary.add_output(
                    find_artifact(config.topic_dir(topic), "corpus_synthesis", identity=topic)
                )
        except (BudgetExceededError, CostPolicyError, ProviderBusyTimeoutError):
            raise
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
    preview: bool = typer.Option(
        False,
        "--preview",
        help="Show the resolved exact-page or shallow-crawl plan without writes",
    ),
    report: bool = typer.Option(False, "--report", help="Run report after processing"),
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
    batch = load_site_batch(path, topic_override=topic)
    target_topic = topic or batch.topic
    planned_seeds = resolve_site_batch_seeds(
        batch.seeds,
        seed_only=seed_only,
        same_section_only=same_section_only,
    )
    if preview:
        if json_mode_active():
            emit_json(site_batch_plan_payload(topic=target_topic, seeds=planned_seeds))
        else:
            print_site_batch_plan(topic=target_topic, seeds=planned_seeds)
        return
    projected_cost: float | None = None
    ledger_estimate: float | None = None
    if not scrape_only:
        router_config = RouterConfig()
        ledger_estimate = estimate_site_batch_plan_cost(
            planned_seeds,
            router_config=router_config,
        )
        projected_cost = estimate_site_batch_plan_cost(
            planned_seeds,
            include_report=report,
            router_config=router_config,
        )
        enforce_projected_workflow_budget(config, "site-batch", projected_cost)
        _require_model()
    tracker = budgeted_cost_tracker(config, "site-batch")
    summary = RunSummary(command="site-batch")
    summary.set_metadata(topic=target_topic, workflow="site-batch", source_type="website")
    summary.estimated_cost = ledger_estimate

    progress = BatchProgress("site", len(planned_seeds), tracker)
    for seed in planned_seeds:
        process_site_batch_seed(
            seed,
            config=config,
            tracker=tracker,
            summary=summary,
            progress=progress,
            scrape_only=scrape_only,
            ingest_attachments=ingest_attachments,
            process_site_seed=_process_site_seed,
        )

    if not scrape_only:
        run_site_batch_syntheses(target_topic, config, tracker, summary)

    if concepts_flag:
        _run_concepts_after_ingest(target_topic, tracker=tracker)
    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
    if report:
        _run_scope_report(target_topic, config, tracker, scope="topic", test=test, summary=summary)


def discover(  # noqa: C901 — legacy, will refactor
    goal: str = _discover_options.GOAL_ARGUMENT,
    goal_file: Path | None = _discover_options.GOAL_FILE_OPTION,
    topic: str = typer.Option("", "--topic", "-t", help="Topic to file under"),
    paper_limit: int = typer.Option(10, "--paper-limit", help="Max papers to ingest (default: 10)"),
    video_limit: int = typer.Option(10, "--video-limit", help="Max videos to ingest (default: 10)"),
    site_seeds: Path | None = _discover_options.SITE_SEEDS_OPTION,
    trusted_site: list[str] | None = _discover_options.TRUSTED_SITE_OPTION,
    site_limit: int = _discover_options.SITE_LIMIT_OPTION,
    site_crawl_depth: int = _discover_options.SITE_CRAWL_DEPTH_OPTION,
    site_crawl_pages: int = _discover_options.SITE_CRAWL_PAGES_OPTION,
    papers_only: bool = _discover_options.PAPERS_ONLY_OPTION,
    videos_only: bool = _discover_options.VIDEOS_ONLY_OPTION,
    days: int = _discover_options.DAYS_OPTION,
    shorts: bool = _discover_options.SHORTS_OPTION,
    ingest_attachments: bool = _discover_options.INGEST_ATTACHMENTS_OPTION,
    from_gaps: bool = _discover_options.FROM_GAPS_OPTION,
    rigor: str = _discover_options.RIGOR_OPTION,
    lens: str = _discover_options.LENS_OPTION,
    verify: str = _discover_options.VERIFY_OPTION,
    preview: bool = _discover_options.PREVIEW_OPTION,
    from_preview: str = _discover_options.FROM_PREVIEW_OPTION,
    size: bool = _discover_options.SIZE_OPTION,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the interactive confirmation prompt"),
    emit_replay_command: bool = typer.Option(
        True,
        "--emit-replay-command/--no-emit-replay-command",
        hidden=True,
    ),
) -> str | None:
    """Goal-aware cross-source discovery: papers + videos, reranked against a goal.

    With ``--from-gaps``, the goal is synthesized from the topic's coverage gaps
    (the inverse of goal-driven discovery): "you are thin on X, single-source on
    Y" becomes "find sources that fill X and Y". With ``--from-preview <id>``, the
    exact shortlist a previous ``--preview`` run saved is ingested verbatim.

    Examples:
      distill discover "agentic coding loops" --topic agentic-coding --preview
      distill discover "agentic coding loops" --topic agentic-coding --yes
      distill discover --goal-file private/agentic-coding.md --topic agentic-coding --yes
      distill discover --from-preview 20260619-120000 --topic agentic-coding
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
    if site_crawl_depth < 0 or site_crawl_pages < 1:
        console.print("[red]Site crawl depth must be >= 0 and crawl pages must be >= 1.[/red]")
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
    tracker = budgeted_cost_tracker(config, "discover")

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
                config.topic_dir(replay_topic),
                make_intent(snapshot.goal, lens=lens, rigor=snapshot.rigor),
            )
            from distill.pipeline.goals import save_topic_goal

            save_topic_goal(
                config.library_dir,
                replay_topic,
                snapshot.goal,
                now_iso=datetime.now().isoformat(),
            )
        replay_estimate = estimate_discover_items(
            papers=len(replay_papers),
            video_durations=[getattr(item.video, "duration", None) for item in replay_videos],
            sites=len(replay_sites),
            calibration=load_cost_calibration(config.library_dir),
            router_config=RouterConfig(),
        )
        replay_summary.estimated_cost = replay_estimate.expected
        enforce_projected_workflow_budget(config, "discover", replay_estimate.expected)
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
        return None

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
            trusted_sites=trusted_site or [],
            site_crawl_depth=site_crawl_depth,
            site_crawl_pages=site_crawl_pages,
            now_iso=datetime.now().isoformat(),
        )
    trusted_site_sources = trusted_site or []
    effective_site_limit = site_limit if site_seeds is not None or trusted_site_sources else 0
    if paper_limit <= 0 and video_limit <= 0 and effective_site_limit <= 0:
        console.print(
            "[red]Specify at least one source: papers, videos, --site-seeds, or --trusted-site with --site-limit > 0.[/red]"
        )
        raise typer.Exit(1)
    summary = RunSummary(command="discover")
    summary.set_metadata(topic=topic_name, workflow="discover", source_type="mixed")

    sites: list[SiteSeed] = []
    site_candidates = None
    if effective_site_limit > 0:
        trusted_site_cap = max(20, effective_site_limit * 4)
        try:
            site_candidates = load_discover_site_candidates(
                topic_name=topic_name,
                site_seeds=site_seeds,
                trusted_sites=trusted_site_sources,
                trusted_site_cap=trusted_site_cap,
                site_crawl_depth=site_crawl_depth,
                site_crawl_pages=site_crawl_pages,
                trusted_site_discoverer=_discover_trusted_site_seeds,
            )
        except FileNotFoundError as exc:
            console.print(f"[red]Site seed file not found: {site_seeds}[/red]")
            raise typer.Exit(1) from exc
        sites = site_candidates.sites

    # Goal files can be multi-line; keep console header compact.
    goal_headline = goal.splitlines()[0][:120] if goal else ""
    console.print(f"\n[bold]Discover: {goal_headline}[/bold]")
    if goal_file is not None:
        console.print(f"[dim]Goal loaded from {goal_file}[/dim]")
    console.print(
        f"[dim]Topic: {topic_name} | Papers: {paper_limit} | Videos: {video_limit} | Sites: {effective_site_limit} "
        f"| Days: {days}[/dim]\n"
    )
    show_discover_site_summary(
        site_candidates=site_candidates,
        site_seeds=site_seeds,
        trusted_site_sources=trusted_site_sources,
        site_crawl_depth=site_crawl_depth,
        site_crawl_pages=site_crawl_pages,
    )

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
        console.print(f"[dim]Website candidates: {len(sites)}[/dim]")
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
        video_stats = format_video_content_stats(summarize_video_content(videos))
        console.print(f"[dim]Found {video_stats} across {len(video_queries)} search(es)[/dim]")

    # Drop already-ingested search hits so rerank and ingest spend goes to new material.
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
            return None
        console.print("[red]No candidates found. Broaden the goal or widen --days.[/red]")
        raise typer.Exit(1)

    console.print("\n[dim]Reranking against goal...[/dim]")
    try:
        ranked = _discover_rerank(goal, papers, videos, sites, config, tracker)
    except (TypeError, ValueError) as exc:
        # Malformed rerank output should fail cleanly like the empty case.
        console.print(f"[red]Rerank produced malformed output: {exc}[/red]")
        raise typer.Exit(1) from exc
    if not ranked:
        console.print("[red]Rerank produced no ranked items.[/red]")
        raise typer.Exit(1)

    # Fresh topics get the size menu unless --yes or --preview selects a loop path.
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
        return None

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

    # Show a self-calibrating ingest estimate before committing the shortlist.
    cliff = detect_score_cliff([r.final_score for r in shortlist])
    calibration = load_cost_calibration(config.library_dir)
    estimate = estimate_discover_items(
        papers=len(ranked_papers),
        video_durations=[getattr(r.video, "duration", None) for r in ranked_videos],
        sites=len(ranked_sites),
        calibration=calibration,
        router_config=RouterConfig(),
    )
    console.print(
        f"  [dim]Top {cliff} sit above the score cliff (the clearly-excellent set). "
        f"Estimated ingest cost: {estimate.format()}.[/dim]"
    )
    # Preserve the shown estimate for estimator accuracy reporting.
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
            settings={
                "video_limit": video_limit,
                "paper_limit": paper_limit,
                "days": days,
                "shorts": shorts,
            },
        )
        if emit_replay_command:
            console.print(
                f"\n[dim]Previewed set saved as[/dim] [bold]{snapshot.id}[/bold]. "
                "[dim]Ingest exactly this set with:[/dim]"
            )
            try:
                quoted_topic = quote_cli_value(topic_name)
            except ValueError as exc:
                console.print(
                    "[yellow]No paste-ready replay command was emitted because the topic "
                    f"{exc}. Re-enter the literal topic with `distill discover "
                    f"--from-preview {snapshot.id}`.[/yellow]"
                )
            else:
                command = f"  distill discover --from-preview {snapshot.id} --topic={quoted_topic}"
                console.print(Text(command, style="cyan"), soft_wrap=True)
        else:
            console.print(f"\n[dim]Previewed set saved as[/dim] [bold]{snapshot.id}[/bold].")
        display_summary(
            summary,
            cost_tracker=tracker,
            console=console,
            log_dir=config.library_dir,
            preview=True,
        )
        return snapshot.id

    enforce_projected_workflow_budget(config, "discover", estimate.expected)
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
    return None


def register(app: typer.Typer) -> None:
    """Attach the discover preview commands to the app (called from distill.cli)."""
    app.command(name="synthesize", rich_help_panel="Discover")(synthesize_cmd)
    app.command(name="monitor", rich_help_panel="Discover")(monitor)
    app.command(name="ramp-up", rich_help_panel="Discover")(ramp_up)
    app.command(name="site", rich_help_panel="Discover")(site_cmd)
    app.command(name="site-batch", rich_help_panel="Discover")(site_batch_cmd)
    app.command(rich_help_panel="Discover")(discover)
