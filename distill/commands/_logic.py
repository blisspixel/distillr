"""CLI business logic — all command functions and helpers.

This module holds the full implementation of every CLI command. It was
moved from ``distill/_cli_impl.py`` during the 0.7 CLI decomposition.
Individual ``commands/*.py`` modules import the functions they need from
here and register them on their Typer sub-apps.

The ``app``, ``topic_app``, and ``topic_watch_app`` Typer instances
defined here are **not** the ones used at runtime — they exist only so that the
decorated functions retain their Typer metadata (argument definitions, help text).
"""

import json
import os
import sys
import zipfile
from datetime import datetime
from hashlib import sha1
from pathlib import Path
from types import SimpleNamespace

import typer
from rich.panel import Panel

import distill.cli_shared as cli_shared
import distill.pipeline.discovery as _discover_support
from distill._app import app
from distill.banner import show_banner
from distill.cli_shared import (
    SHORTS_THRESHOLD,
    console,
)
from distill.cli_shared import (
    format_date as _format_date,
)
from distill.cli_shared import (
    output_path as _output_path,
)
from distill.cli_shared import (
    require_model as _require_model,
)
from distill.cli_shared import (
    resolve_video_channel_name as _shared_resolve_video_channel_name,
)
from distill.cli_shared import (
    strip_frontmatter as _strip_frontmatter,
)
from distill.cli_shared import (
    topic_from_query as _topic_from_query,
)
from distill.cli_shared import (
    tty_confirm as _tty_confirm,
)
from distill.cli_shared import (
    tty_prompt as _tty_prompt,
)
from distill.commands import _learning as _learning_support
from distill.commands import _learning_flow as _learning_flow_support
from distill.commands import _topic_changes as _topic_changes_support
from distill.commands._helpers import (
    _invoke_command,
    _preflight,
    _resolve_intent,
    get_config,
)
from distill.commands._topic_watch import (
    _normalize_topic_watch_ranking_mode,
    _topic_watch_name,
    _topic_watch_ranking_strategy,
)
from distill.config import DistillConfig

# Doctor check/probe helpers live in distill.doctor.checks; the two used by the
# doctor command (still in this module) are re-imported so it finds them in this
# namespace. init + the MCP doctor tool import from distill.doctor.checks directly.
from distill.ingestors.papers.arxiv import (
    PaperRecord,
    build_paper_document,
)
from distill.ingestors.sites.attachments import (
    collect_page_attachments,
    ingest_page_attachments,
    write_attachment_manifest,
)
from distill.ingestors.sites.scraper import (
    SiteSeed,
    build_page_document,
    crawl_site,
)
from distill.ingestors.youtube.browser_search import search_youtube_results
from distill.ingestors.youtube.discovery import (
    VideoInfo,
    enrich_videos,
    resolve_channel_name,
    search_videos,
)
from distill.ingestors.youtube.transcripts import get_transcript
from distill.library import Library
from distill.library.intent import (
    load_intent,
    make_intent,
    save_intent,
)
from distill.library.paths import (
    artifact_exists,
    base_frontmatter,
    find_artifact,
    tags_for,
    write_markdown_artifact,
    write_text_artifact,
)
from distill.library.state import ChannelState
from distill.llm.availability import model_available
from distill.pipeline.analysis.paper import analyze_paper, synthesize_papers
from distill.pipeline.analysis.site import analyze_site_page, synthesize_site, synthesize_site_topic
from distill.pipeline.analysis.video import (
    analyze_scan,
    analyze_short,
    analyze_video,
    generate_channel_context,
)
from distill.pipeline.costs import BudgetExceededError, CostTracker
from distill.pipeline.dashboard_data import _load_site_manifest as _load_site_manifest
from distill.pipeline.dashboard_data import build_site_section_state as _build_site_section_state
from distill.pipeline.dashboard_data import count_paper_corpus as _count_paper_corpus
from distill.pipeline.dashboard_data import count_site_corpus as _count_site_corpus
from distill.pipeline.dashboard_data import count_topic_outputs as _count_topic_outputs
from distill.pipeline.dashboard_data import load_all_cost_runs as _load_all_cost_runs
from distill.pipeline.dashboard_data import parse_run_datetime as _parse_run_datetime
from distill.pipeline.dashboard_data import (
    topic_watch_budget_messages as _topic_watch_budget_messages,
)
from distill.pipeline.ranking import chronological_rank, rerank_videos
from distill.pipeline.report.briefing import generate_topic_brief
from distill.pipeline.summary import (
    ETATracker,
    RunSummary,
    display_summary,
    log_preview_cost,
)
from distill.pipeline.synthesis.corpus import synthesize_corpus
from distill.pipeline.synthesis.topic import synthesize_channel, synthesize_topic

_replace_case_insensitive = _learning_support._replace_case_insensitive
_strip_intent_terms = _learning_support._strip_intent_terms
_strip_noise_terms = _learning_support._strip_noise_terms
_auto_skeptical_mode = _learning_support._auto_skeptical_mode
_effective_days = _learning_support._effective_days
_window_label = _learning_support._window_label
_default_report_focus = _learning_support._default_report_focus
_filter_recent_candidates = _learning_support._filter_recent_candidates
_dedupe_candidates = _learning_support._dedupe_candidates
_format_metric = _learning_support._format_metric
_apply_ranked_channel_cap = _learning_support._apply_ranked_channel_cap
_dedupe_query_strings = _learning_support._dedupe_query_strings
_heuristic_learning_queries = _learning_support._heuristic_learning_queries
_llm_expand_learning_queries = _learning_support._llm_expand_learning_queries
_llm_expand_paper_queries = _learning_support._llm_expand_paper_queries
_display_ranked_papers = _learning_support._display_ranked_papers
_display_ranked_videos = _learning_support._display_ranked_videos

_learning_flow_generate_and_export_topic_brief = (
    _learning_flow_support.generate_and_export_topic_brief
)
_RankedDiscoverItem = _discover_support.RankedDiscoverItem

_read_json_file = _topic_changes_support._read_json_file
_topic_change_history_path = _topic_changes_support._topic_change_history_path
_topic_diff_output_path = _topic_changes_support._topic_diff_output_path
_topic_trends_output_path = _topic_changes_support._topic_trends_output_path
_watch_alerts_output_path = _topic_changes_support._watch_alerts_output_path
_relative_library_path = _topic_changes_support._relative_library_path
_collect_topic_change_details = _topic_changes_support._collect_topic_change_details
_topic_change_snapshot = _topic_changes_support._topic_change_snapshot
_render_topic_diff_markdown = _topic_changes_support._render_topic_diff_markdown
_append_topic_change_history = _topic_changes_support._append_topic_change_history
_load_topic_change_history = _topic_changes_support._load_topic_change_history
_topic_trend_direction = _topic_changes_support._topic_trend_direction
_topic_trend_label = _topic_changes_support._topic_trend_label
_topic_watch_alert_lines = _topic_changes_support._topic_watch_alert_lines
_write_watch_alert_digest = _topic_changes_support._write_watch_alert_digest
_render_topic_trends_markdown = _topic_changes_support._render_topic_trends_markdown
_write_topic_change_briefing = _topic_changes_support._write_topic_change_briefing
_resolve_topic_diff_baseline = _topic_changes_support._resolve_topic_diff_baseline


def _expand_learning_queries(
    query: str,
    config: DistillConfig | None = None,
    tracker: CostTracker | None = None,
    *,
    skeptical: bool = False,
    expand: bool = True,
) -> list[str]:
    query = query.strip()
    if query.startswith("http://") or query.startswith("https://"):
        return [query]

    normalized = " ".join(query.split())
    variants = _heuristic_learning_queries(normalized, skeptical=skeptical)
    if expand and config and model_available("rerank"):
        llm_variants = _llm_expand_learning_queries(
            normalized,
            config,
            tracker=tracker,
            skeptical=skeptical,
        )
        if llm_variants:
            variants = [normalized, *llm_variants, *variants]
    return _dedupe_query_strings(variants)[:6]


def _expand_paper_queries(
    query: str,
    config: DistillConfig | None = None,
    tracker: CostTracker | None = None,
    *,
    expand: bool = True,
) -> list[str]:
    normalized = " ".join(query.split())
    if not normalized:
        return []
    variants = [normalized]
    if expand and config and model_available("rerank"):
        try:
            llm_variants = _llm_expand_paper_queries(normalized, config, tracker=tracker)
        except Exception as e:
            console.print(f"  [yellow]Query expansion fallback: {e}[/yellow]")
            llm_variants = []
        variants.extend(llm_variants)
    return _dedupe_query_strings(variants)[:6]


def _select_learning_videos(
    query: str,
    config: DistillConfig,
    tracker: CostTracker,
    days: int,
    limit: int,
    sort: str,
    per_channel_cap: int,
    shorts: bool,
    rerank: bool,
    *,
    hours: int | None = None,
    skeptical: bool = False,
    expand: bool = True,
    top_by_date: bool = False,
    rigor: str = "off",
):
    effective_days = _effective_days(days, hours)
    candidate_limit = max(limit * 2, 12)
    raw_candidates = []
    # Strict chronological mode bypasses both rerank and the heuristic mix,
    # which means query expansion would only burn tokens and leak the query
    # to the LLM provider without ever influencing the final selection.
    effective_expand = expand and not top_by_date
    queries = _expand_learning_queries(
        query,
        config,
        tracker,
        skeptical=skeptical,
        expand=effective_expand,
    )
    for idx, variant in enumerate(queries, 1):
        console.print(f"[dim]Candidate search {idx}/{len(queries)}: {variant}[/dim]")
        raw_candidates.extend(
            search_youtube_results(
                variant,
                days=effective_days,
                hours=hours,
                limit=candidate_limit,
            )
        )
    raw_candidates = _dedupe_candidates(raw_candidates)
    if not raw_candidates:
        console.print(
            "[dim]Browser-based search returned no candidates; falling back to yt-dlp search[/dim]"
        )
        raw_candidates = search_videos(
            query,
            days=effective_days,
            limit=candidate_limit,
            sort=sort,
            per_channel_cap=max(per_channel_cap * 2, 4),
        )
    if not shorts:
        raw_candidates = [v for v in raw_candidates if v.duration > SHORTS_THRESHOLD]
        console.print(f"[dim]Filtered to {len(raw_candidates)} full-length candidates[/dim]")

    if not raw_candidates:
        return [], []

    enriched = enrich_videos(raw_candidates, max_videos=min(len(raw_candidates), 12))
    enriched = _filter_recent_candidates(enriched, effective_days, hours=hours)
    if top_by_date:
        # Strict chronological pick — bypass both LLM rerank and the heuristic
        # mix. Channel cap still applies to keep one prolific uploader from
        # monopolizing the slate.
        ranked = chronological_rank(enriched, top_n=max(limit * 2, 10))
    else:
        ranked = rerank_videos(
            query,
            enriched,
            config,
            tracker=tracker,
            top_n=max(limit * 2, 10),
            use_llm=rerank,
            skeptical=skeptical,
        )
        # A rigor bar drops sub-threshold videos before the channel cap; chronological
        # mode (top_by_date) bypasses scoring entirely, so rigor never applies there.
        ranked = _apply_source_rigor(
            ranked, source="video", rigor=rigor, rerank_on=rerank, limit=len(ranked)
        )
    selected = _apply_ranked_channel_cap(ranked, limit, per_channel_cap)
    return enriched, selected


def _preview_learning_selection(
    query: str,
    *,
    days: int,
    limit: int,
    sort: str,
    per_channel_cap: int,
    shorts: bool,
    rerank: bool,
    header: str,
    table_title: str,
    hours: int | None = None,
    skeptical: bool | None = None,
    expand: bool = True,
    top_by_date: bool = False,
    rigor: str = "off",
):
    return _learning_flow_support.preview_learning_selection(
        query,
        days=days,
        limit=limit,
        sort=sort,
        per_channel_cap=per_channel_cap,
        shorts=shorts,
        rerank=rerank,
        header=header,
        table_title=table_title,
        get_config=get_config,
        cost_tracker_factory=CostTracker,
        auto_skeptical_mode=_auto_skeptical_mode,
        window_label=_window_label,
        select_learning_videos=_select_learning_videos,
        display_ranked_videos=_display_ranked_videos,
        hours=hours,
        skeptical=skeptical,
        expand=expand,
        top_by_date=top_by_date,
        rigor=rigor,
    )


def _run_learning_command(
    query: str,
    *,
    topic: str | None,
    days: int,
    limit: int,
    sort: str,
    per_channel_cap: int,
    shorts: bool,
    rerank: bool,
    save: bool,
    report: bool,
    test: bool,
    generate_brief: bool,
    header: str,
    hours: int | None = None,
    skeptical: bool | None = None,
    expand: bool = True,
    focus: str | None = None,
    top_by_date: bool = False,
    post_ingest_callback=None,
    rigor: str = "off",
) -> None:
    _preflight()
    _learning_flow_support.run_learning_command(
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
        generate_brief=generate_brief,
        header=header,
        get_config=get_config,
        cost_tracker_factory=CostTracker,
        topic_from_query=_topic_from_query,
        auto_skeptical_mode=_auto_skeptical_mode,
        default_report_focus=_default_report_focus,
        window_label=_window_label,
        select_learning_videos=_select_learning_videos,
        display_ranked_videos=_display_ranked_videos,
        process_learning_selection=_process_learning_selection,
        hours=hours,
        skeptical=skeptical,
        expand=expand,
        focus=focus,
        top_by_date=top_by_date,
        post_ingest_callback=post_ingest_callback,
        rigor=rigor,
    )


def _process_learning_selection(
    topic_name: str,
    config: DistillConfig,
    tracker: CostTracker,
    selected,
    *,
    save: bool,
    report: bool,
    test: bool,
    generate_brief: bool,
    report_focus: str | None = None,
    post_ingest_callback=None,
) -> None:
    _learning_flow_support.process_learning_selection(
        topic_name,
        config,
        tracker,
        selected,
        save=save,
        report=report,
        test=test,
        generate_brief=generate_brief,
        library_factory=Library,
        run_summary_factory=RunSummary,
        output_path=_output_path,
        ensure_channel_context=_ensure_channel_context,
        process_video=_process_video,
        synthesize_channel=synthesize_channel,
        synthesize_topic=synthesize_topic,
        synthesize_corpus=synthesize_corpus,
        run_scope_report=_run_scope_report,
        generate_and_export_topic_brief=_generate_and_export_topic_brief,
        report_focus=report_focus,
        post_ingest_callback=post_ingest_callback,
    )


def _generate_and_export_topic_brief(
    topic_name: str, config: DistillConfig, tracker: CostTracker
) -> None:
    _learning_flow_generate_and_export_topic_brief(
        topic_name,
        config,
        tracker,
        generate_topic_brief=generate_topic_brief,
        output_path=_output_path,
    )


def _discover_generate_queries(
    goal: str,
    config: DistillConfig,
    tracker: CostTracker | None,
    *,
    paper_count: int,
    video_count: int,
) -> tuple[list[str], list[str]]:
    return _discover_support.discover_generate_queries(
        goal,
        config,
        tracker,
        paper_count=paper_count,
        video_count=video_count,
        dedupe_query_strings=_dedupe_query_strings,
    )


def _discover_fetch_videos(
    queries: list[str],
    effective_days: int,
    candidate_cap: int,
    shorts: bool,
) -> list[VideoInfo]:
    return _discover_support.discover_fetch_videos(
        queries,
        effective_days,
        candidate_cap,
        shorts,
        search_youtube_results=search_youtube_results,
        dedupe_candidates=_dedupe_candidates,
        enrich_videos=enrich_videos,
        filter_recent_candidates=_filter_recent_candidates,
    )


def _discover_rerank(
    goal: str,
    papers: list[PaperRecord],
    videos: list[VideoInfo],
    sites: list[SiteSeed],
    config: DistillConfig,
    tracker: CostTracker | None,
) -> list[_RankedDiscoverItem]:
    return _discover_support.discover_rerank(goal, papers, videos, sites, config, tracker)


def _display_ranked_discover(items: list[_RankedDiscoverItem], title: str) -> None:
    _discover_support.display_ranked_discover(items, title)


# `app` (the top-level Typer instance + its did-you-mean group class) is defined
# in distill._app and imported at the top of this module, so the hundreds of
# `@app.command` decorators below attach to that same instance.

topic_app = typer.Typer(
    help=(
        "Topic-first workflows.\n\n"
        "Recommended flow:\n"
        '  distill topic create "topic here" --videos 10 --papers 10\n'
        "  distill topic update <topic>\n"
        "  distill topic brief <topic>\n"
        "  distill topic report <topic>\n"
    ),
    rich_markup_mode="rich",
)
app.add_typer(topic_app, name="topic")


def _version_callback(value: bool) -> None:
    """Eager ``--version`` handler: print the version to stdout and exit 0.

    Eager so it works before any subcommand wiring or config load -- an agent
    or bug report can read the version without a configured environment.
    """
    if value:
        import typer as _typer

        _typer.echo(_get_version())
        raise _typer.Exit()


@app.callback()
def _default(
    ctx: typer.Context,
    debug: bool = typer.Option(False, "--debug", help="Enable DEBUG-level logging to console"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON to stdout"),
    model: str = typer.Option("", "--model", "-m", help="Override model for all workloads"),
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show the installed distill version and exit",
        callback=_version_callback,
        is_eager=True,
    ),
):
    """Distill - YouTube channels to strategic intelligence."""
    from distill._logging import configure_logging

    ctx.ensure_object(dict)
    ctx.obj["json"] = json_output
    ctx.obj["model"] = model
    # In --json mode, redirect all human/progress/diagnostic output to stderr so
    # stdout carries only the JSON envelope (commands write that envelope
    # directly to stdout). Called every invocation so a reused process resets
    # the stream rather than leaking a prior redirect. Supersedes the old
    # console.quiet approach, which dropped diagnostics entirely.
    from distill._console import set_json_mode
    from distill.commands._json import set_json_active

    set_json_mode(json_output)
    set_json_active(json_output)

    # Set model override as env var so pipeline functions pick it up
    # without needing ctx passed through every layer
    if model:
        import os

        os.environ["DISTILL_MODEL"] = model

    try:
        ops_dir = get_config().library_dir / ".distill"
    except Exception:
        ops_dir = None
    configure_logging(debug=debug, ops_dir=ops_dir)

    if ctx.invoked_subcommand is None:
        # Only clear the screen for an interactive terminal; clearing when output
        # is piped or captured (an agent shell, a loop) emits escape codes into
        # the captured stream.
        if sys.stdout.isatty():
            console.clear()
        show_banner(console)
        # Lazy import: the dashboard module imports helpers back from this
        # module, so importing it at module load would cycle.
        from distill.commands.dashboard import _show_dashboard

        _show_dashboard()


def _apply_verify_override(verify: str) -> None:
    """Apply a per-run ``--verify`` override (process-scoped env set).

    ``get_config()`` builds a fresh ``DistillConfig`` per call (including
    inside the injected learning flows), so the override is applied where
    every instantiation reads it: the process environment. ``load_dotenv``
    never overwrites existing env vars, so the flag wins over ``.env``.
    Unlike a typo'd env var (which degrades to ``warn``), a typo'd *flag* is
    an interactive mistake the user can fix immediately -- it errors loudly.
    """
    if not verify:
        return
    value = verify.strip().lower()
    if value not in {"warn", "strict", "off"}:
        console.print(f"[red]Unknown --verify '{verify}'.[/red] Choose: warn, strict, off.")
        raise typer.Exit(1)
    os.environ["DISTILL_VERIFY"] = value


def _persist_lens(config: DistillConfig, topic_name: str, fallback_goal: str, lens: str) -> None:
    """Persist an explicit ``--lens`` choice as the topic's intent.

    Preserves any goal/audience/rigor/budget already saved (e.g. from a prior
    ``discover``); only the lens is overridden, with ``fallback_goal`` used when
    the topic has no saved goal yet.
    """
    existing = load_intent(config.topic_dir(topic_name))
    save_intent(
        config.topic_dir(topic_name),
        make_intent(
            goal=existing.goal if existing and existing.goal else fallback_goal,
            lens=lens,
            audience=existing.audience if existing else "",
            rigor=existing.rigor if existing else "",
            budget_usd=existing.budget_usd if existing else None,
        ),
    )


def get_model_override(ctx: typer.Context | None = None) -> str:
    """Get the --model override from the CLI context, if set."""
    if ctx and ctx.obj:
        return ctx.obj.get("model", "")
    return ""


_TOPIC_PROFILE_VERSION = 1


def _topic_profile_path(config: DistillConfig, topic: str) -> Path:
    return config.topic_dir(topic) / "topic_profile.json"


def _topic_exists(config: DistillConfig, topic: str) -> bool:
    lib = Library(config)
    return topic in lib.get_topics() or config.topic_dir(topic).exists()


def _load_topic_profile(config: DistillConfig, topic: str) -> dict | None:
    path = _topic_profile_path(config, topic)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _save_topic_profile(
    config: DistillConfig,
    *,
    topic: str,
    goal: str,
    videos: int,
    papers: int,
    days: int,
    shorts: bool,
) -> Path:
    path = _topic_profile_path(config, topic)
    path.parent.mkdir(parents=True, exist_ok=True)
    prior = _load_topic_profile(config, topic) or {}
    created_at = str(prior.get("created_at", "")) or datetime.now().isoformat()
    payload = {
        "version": _TOPIC_PROFILE_VERSION,
        "topic": topic,
        "goal": goal,
        "videos": videos,
        "papers": papers,
        "days": days,
        "shorts": shorts,
        "created_at": created_at,
        "updated_at": datetime.now().isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _resolve_topic_workflow_config(
    config: DistillConfig,
    *,
    topic: str,
    goal: str,
    videos: int,
    papers: int,
    days: int,
    shorts: bool,
) -> dict:
    goal_text = " ".join(goal.split()).strip()
    if not goal_text:
        console.print("[red]Goal cannot be empty[/red]")
        raise typer.Exit(1)
    if days <= 0:
        console.print("[red]--days must be positive[/red]")
        raise typer.Exit(1)
    if videos < 0 or papers < 0:
        console.print("[red]--videos and --papers cannot be negative[/red]")
        raise typer.Exit(1)
    if videos == 0 and papers == 0:
        console.print("[red]Specify at least one source with --videos or --papers[/red]")
        raise typer.Exit(1)
    topic_name = topic.strip() or _topic_from_query(goal_text[:80])
    return {
        "topic": topic_name,
        "goal": goal_text,
        "videos": videos,
        "papers": papers,
        "days": days,
        "shorts": shorts,
        "mixed_sources": papers > 0,
    }


def _run_topic_workflow(
    *,
    goal: str,
    topic: str,
    videos: int,
    papers: int,
    days: int,
    shorts: bool,
    preview: bool,
    brief: bool,
    report_after: bool,
    test: bool,
) -> str:
    config = get_config()
    resolved = _resolve_topic_workflow_config(
        config,
        topic=topic,
        goal=goal,
        videos=videos,
        papers=papers,
        days=days,
        shorts=shorts,
    )
    topic_name = str(resolved["topic"])

    if bool(resolved["mixed_sources"]):
        from distill.commands.discover import discover  # extracted to commands/discover.py

        _invoke_command(
            discover,
            goal=str(resolved["goal"]),
            goal_file=None,
            topic=topic_name,
            paper_limit=int(resolved["papers"]),
            video_limit=int(resolved["videos"]),
            days=int(resolved["days"]),
            shorts=bool(resolved["shorts"]),
            preview=preview,
            yes=True,
        )
    elif preview:
        # Videos-only preview must NOT ingest. _run_learning_command always
        # processes (real spend); route to the dry-run preview path instead,
        # mirroring latest_cmd. Without this, `topic preview --papers 0` (and
        # `topic create --preview --papers 0`) fully ingested before the
        # "preview only" notice below ever ran.
        _preview_learning_selection(
            str(resolved["goal"]),
            days=int(resolved["days"]),
            limit=int(resolved["videos"]),
            sort="relevance",
            per_channel_cap=max(2, min(int(resolved["videos"]), 3)),
            shorts=bool(resolved["shorts"]),
            rerank=True,
            header="Topic Preview",
            table_title="Topic Preview Learning Set",
        )
    else:
        _run_learning_command(
            str(resolved["goal"]),
            topic=topic_name,
            days=int(resolved["days"]),
            limit=int(resolved["videos"]),
            sort="relevance",
            per_channel_cap=max(2, min(int(resolved["videos"]), 3)),
            shorts=bool(resolved["shorts"]),
            rerank=True,
            save=True,
            report=False,
            test=test,
            generate_brief=False,
            header="Topic Create",
        )

    if preview:
        console.print(
            f'\n[dim]Preview only. Run `distill topic create "{resolved["goal"]}" --topic {topic_name}` to ingest.[/dim]'
        )
        return topic_name

    profile_path = _save_topic_profile(
        config,
        topic=topic_name,
        goal=str(resolved["goal"]),
        videos=int(resolved["videos"]),
        papers=int(resolved["papers"]),
        days=int(resolved["days"]),
        shorts=bool(resolved["shorts"]),
    )
    console.print(f"[dim]Saved topic profile: {profile_path}[/dim]")

    if brief:
        _generate_and_export_topic_brief(topic_name, config, CostTracker())
    if report_after:
        from distill.commands.reports import report

        _invoke_command(report, topic=topic_name, test=test)
    return topic_name


def _render_topic_summary(topic: str) -> None:
    config = get_config()
    lib = Library(config)
    if topic not in lib.get_topics() and not config.topic_dir(topic).exists():
        console.print(f"[red]Topic not found: {topic}[/red]")
        raise typer.Exit(1)

    channels = lib.get_channels(topic)
    video_count = 0
    for ch in channels:
        state = ChannelState(config.channel_dir(topic, ch.name) / "state.json")
        video_count += state.get_processed_count()

    artifacts = []
    topic_dir = config.topic_dir(topic)
    for label, path_obj in [
        ("topic synthesis", find_artifact(topic_dir, "topic_synthesis", identity=topic)),
        ("brief", find_artifact(topic_dir, "brief", identity=topic)),
        ("report", find_artifact(topic_dir, "report", identity=topic)),
        ("paper synthesis", find_artifact(topic_dir, "paper_synthesis", identity=topic)),
        ("corpus synthesis", find_artifact(topic_dir, "corpus_synthesis", identity=topic)),
    ]:
        if path_obj.exists():
            artifacts.append(label)

    profile = _load_topic_profile(config, topic)
    paper_count = _count_paper_corpus(config, [topic])
    site_count, page_count = _count_site_corpus(config, [topic])
    lines = [f"[bold]{topic}[/bold]"]
    if profile and profile.get("goal"):
        lines.append(f"[dim]Goal:[/dim] {profile['goal']}")
    lines.append(
        f"[dim]Corpus:[/dim] {len(channels)} channel(s), {video_count} processed video(s), {paper_count} paper(s), {site_count} site(s) / {page_count} page(s)"
    )
    if profile:
        lines.append(
            f"[dim]Plan:[/dim] videos={profile.get('videos', 0)} papers={profile.get('papers', 0)} days={profile.get('days', 0)} shorts={'on' if profile.get('shorts') else 'off'}"
        )
    if artifacts:
        lines.append(f"[dim]Artifacts:[/dim] {', '.join(artifacts)}")
    lines.append(
        f"[dim]Next:[/dim] distill topic update {topic}  |  distill topic brief {topic}  |  distill topic report {topic}"
    )
    console.print(Panel("\n".join(lines), title="Topic Summary", border_style="cyan"))


def _complete_watched_channels(incomplete: str) -> list[str]:
    """Autocomplete for watched channel names."""
    try:
        lib = Library(get_config())
        return [
            e.name for e in lib.get_watchlist() if e.name.lower().startswith(incomplete.lower())
        ]
    except Exception:
        return []


def _complete_topic_watch_names(incomplete: str) -> list[str]:
    """Autocomplete for topic-watch names."""
    try:
        lib = Library(get_config())
        return [
            e.name
            for e in lib.get_topic_watchlist()
            if e.name.lower().startswith(incomplete.lower())
        ]
    except Exception:
        return []


def _complete_topics(incomplete: str) -> list[str]:
    """Autocomplete for topic names."""
    try:
        lib = Library(get_config())
        return [t for t in lib.get_topics() if t.lower().startswith(incomplete.lower())]
    except Exception:
        return []


@topic_app.command("create")
def topic_create(
    goal: str = typer.Argument(help="Natural-language topic goal or research prompt"),
    topic: str = typer.Option("", "--topic", "-t", help="Explicit topic slug/name"),
    videos: int = typer.Option(10, "--videos", help="How many videos to ingest"),
    papers: int = typer.Option(10, "--papers", help="How many papers to ingest"),
    days: int = typer.Option(30, "--days", "-d", help="Video recency window in days"),
    shorts: bool = typer.Option(
        False, "--shorts/--no-shorts", help="Include short-form videos under 3 minutes"
    ),
    preview: bool = typer.Option(
        False, "--preview", help="Show the plan without ingesting the topic corpus"
    ),
    brief: bool = typer.Option(
        False, "--brief", help="Generate a concise topic brief after ingestion"
    ),
    report_after: bool = typer.Option(
        False, "--report", help="Generate a full topic report after ingestion"
    ),
    test: bool = typer.Option(False, "--test", help="Cheaper/faster report mode"),
):
    """Create a topic corpus from a single goal using the configured source mix."""
    _run_topic_workflow(
        goal=goal,
        topic=topic,
        videos=videos,
        papers=papers,
        days=days,
        shorts=shorts,
        preview=preview,
        brief=brief,
        report_after=report_after,
        test=test,
    )


@topic_app.command("preview")
def topic_preview(
    goal: str = typer.Argument(help="Natural-language topic goal or research prompt"),
    topic: str = typer.Option("", "--topic", "-t", help="Optional topic slug/name"),
    videos: int = typer.Option(10, "--videos", help="How many videos to plan for"),
    papers: int = typer.Option(10, "--papers", help="How many papers to plan for"),
    days: int = typer.Option(30, "--days", "-d", help="Video recency window in days"),
    shorts: bool = typer.Option(
        False, "--shorts/--no-shorts", help="Include short-form videos under 3 minutes"
    ),
):
    """Preview the topic plan without ingesting anything."""
    _run_topic_workflow(
        goal=goal,
        topic=topic,
        videos=videos,
        papers=papers,
        days=days,
        shorts=shorts,
        preview=True,
        brief=False,
        report_after=False,
        test=False,
    )


@topic_app.command("update")
def topic_update(
    topic: str = typer.Argument(help="Existing topic name", autocompletion=_complete_topics),
    goal: str | None = typer.Option(None, "--goal", help="Override the stored goal"),
    videos: int | None = typer.Option(None, "--videos", help="Override stored video count"),
    papers: int | None = typer.Option(None, "--papers", help="Override stored paper count"),
    days: int | None = typer.Option(None, "--days", "-d", help="Override stored day window"),
    shorts: bool | None = typer.Option(
        None, "--shorts/--no-shorts", help="Override whether Shorts are included"
    ),
    preview: bool = typer.Option(False, "--preview", help="Preview the refreshed plan only"),
    brief: bool = typer.Option(False, "--brief", help="Generate a brief after update"),
    report_after: bool = typer.Option(False, "--report", help="Generate a report after update"),
    test: bool = typer.Option(False, "--test", help="Cheaper/faster report mode"),
):
    """Refresh a topic using its saved topic profile, with optional overrides."""
    _preflight()
    config = get_config()
    profile = _load_topic_profile(config, topic)
    if profile is None:
        console.print(
            f'[red]No topic profile found for {topic}[/red]\n[dim]Create one first with `distill topic create "..." --topic {topic}`[/dim]'
        )
        raise typer.Exit(1)

    resolved_goal = goal or str(profile.get("goal", "")).strip()
    resolved_videos = int(profile.get("videos", 0) if videos is None else videos)
    resolved_papers = int(profile.get("papers", 0) if papers is None else papers)
    resolved_days = int(profile.get("days", 30) if days is None else days)
    resolved_shorts = bool(profile.get("shorts", False) if shorts is None else shorts)

    _run_topic_workflow(
        goal=resolved_goal,
        topic=topic,
        videos=resolved_videos,
        papers=resolved_papers,
        days=resolved_days,
        shorts=resolved_shorts,
        preview=preview,
        brief=brief,
        report_after=report_after,
        test=test,
    )


@topic_app.command("brief")
def topic_brief(
    topic: str = typer.Argument(help="Existing topic name", autocompletion=_complete_topics),
    report_after: bool = typer.Option(False, "--report", help="Also generate a full report"),
    test: bool = typer.Option(False, "--test", help="Cheaper/faster report mode"),
):
    """Generate a concise markdown brief from an existing topic corpus."""
    config = get_config()
    if not _topic_exists(config, topic):
        console.print(f"[red]Topic not found: {topic}[/red]")
        raise typer.Exit(1)
    _generate_and_export_topic_brief(topic, config, CostTracker())
    if report_after:
        from distill.commands.reports import report

        _invoke_command(report, topic=topic, test=test)


@topic_app.command("report")
def topic_report(
    topic: str = typer.Argument(help="Existing topic name", autocompletion=_complete_topics),
    focus: str | None = typer.Option(None, "--focus", "-f", help="Custom research focus"),
    test: bool = typer.Option(False, "--test", "-t", help="Test mode (cheaper, faster)"),
    legacy: bool = typer.Option(
        False, "--legacy", help="Use single-shot Deep Research (no section writing)"
    ),
    research_only: bool = typer.Option(
        False, "--research-only", help="Run Phase 1 only (raw research, no section writing)"
    ),
    sections_filter: str | None = typer.Option(
        None, "--sections", "-s", help="Comma-separated section IDs to write"
    ),
    no_qa: bool = typer.Option(False, "--no-qa", help="Skip QA review phase"),
):
    """Generate a full research report for an existing topic."""
    from distill.commands.reports import report

    report(
        topic=topic,
        channel=None,
        all_topics=False,
        focus=focus,
        test=test,
        legacy=legacy,
        research_only=research_only,
        sections_filter=sections_filter,
        no_qa=no_qa,
    )


@topic_app.command("show")
def topic_show(
    topic: str = typer.Argument(help="Existing topic name", autocompletion=_complete_topics),
    what: str = typer.Option(
        "summary",
        "--what",
        "-w",
        help="What to show: summary, synthesis, report",
    ),
):
    """Show the current state or key outputs for a topic."""
    # `synthesis` / `findings` now live in commands/view.py; imported lazily here
    # to avoid a module-load cycle (view imports completion helpers from _logic).
    from distill.commands.view import findings, synthesis

    if what == "summary":
        _render_topic_summary(topic)
        return
    if what == "synthesis":
        synthesis(topic=topic, channel=None)
        return
    if what == "report":
        findings(topic=topic, channel=None)
        return
    console.print("[red]Unknown --what. Use: summary, synthesis, report[/red]")
    raise typer.Exit(1)


@topic_app.command("export")
def topic_export(
    topic: str = typer.Argument(help="Existing topic name", autocompletion=_complete_topics),
    what: str = typer.Option(
        "report",
        "--what",
        "-w",
        help="What to export: report, synthesis, bundle",
    ),
    bundle_format: str = typer.Option(
        "bundle", "--format", help="Bundle format for --what bundle: bundle or deepr"
    ),
):
    """Export topic artifacts in the same formats as the lower-level export command."""
    from distill.commands.reports import export

    export(topic=topic, what=what, channel=None, bundle_format=bundle_format)


@topic_app.command("watch")
def topic_watch(
    topic: str = typer.Argument(help="Existing topic name", autocompletion=_complete_topics),
    cadence: str = typer.Option("daily", "--cadence", help="Run cadence: daily or weekly"),
    days: int | None = typer.Option(None, "--days", "-d", help="Override lookback window"),
    limit: int | None = typer.Option(None, "--videos", help="Override video pick count"),
    name: str = typer.Option("", "--name", help="Explicit watch name"),
    report_after: bool = typer.Option(
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
    """Create a recurring topic watch using the saved topic profile."""
    config = get_config()
    profile = _load_topic_profile(config, topic)
    if profile is None:
        console.print(
            f'[red]No topic profile found for {topic}[/red]\n[dim]Create one first with `distill topic create "..." --topic {topic}`[/dim]'
        )
        raise typer.Exit(1)

    from distill.commands.discover import monitor  # extracted to commands/discover.py

    monitor(
        query=str(profile.get("goal", "")).strip(),
        topic=topic,
        name=name,
        cadence=cadence,
        days=int(profile.get("days", 30) if days is None else days),
        limit=int(profile.get("videos", 10) if limit is None else limit),
        sort="date",
        per_channel_cap=3,
        ranking="balanced",
        report=report_after,
        max_run_cost=max_run_cost,
        monthly_budget=monthly_budget,
        now=now,
        preview=preview,
    )


def _show_latest_insights(  # noqa: C901 — legacy, will refactor
    config: DistillConfig, topic: str, channel_name: str, limit: int = 3
) -> None:
    """Print a compact summary of the latest video insights for a channel."""
    videos_dir = config.videos_dir(topic, channel_name)
    if not videos_dir.exists():
        return
    vid_list = []
    for vid_dir in videos_dir.iterdir():
        if not vid_dir.is_dir():
            continue
        meta_file = vid_dir / "metadata.json"
        insights_file = find_artifact(vid_dir, "insights")
        if not meta_file.exists() or not insights_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            meta["_dir"] = vid_dir
            vid_list.append(meta)
        except (OSError, json.JSONDecodeError):
            continue
    if not vid_list:
        return
    vid_list.sort(key=lambda v: v.get("upload_date", ""), reverse=True)
    selected = vid_list[:limit]

    console.print(f"\n  [bold]Latest from {channel_name}[/bold]\n")
    for i, meta in enumerate(selected, 1):
        title = meta.get("title", "Unknown")
        date = _format_date(meta.get("upload_date", ""))
        vid_dir = meta["_dir"]
        insights_file = find_artifact(vid_dir, "insights")
        content = insights_file.read_text(encoding="utf-8")
        # Strip frontmatter
        content = _strip_frontmatter(content)
        # Extract just the Summary section
        summary_text = ""
        in_summary = False
        for line in content.split("\n"):
            if line.strip().lower().startswith("## summary") or line.strip().lower().startswith(
                "## quick take"
            ):
                in_summary = True
                continue
            if in_summary and line.strip().startswith("## "):
                break
            if in_summary:
                summary_text += line + "\n"
        summary_text = summary_text.strip()
        if not summary_text:
            # Fallback: first non-empty paragraph
            for line in content.split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    summary_text = line
                    break
        # Truncate if too long
        if len(summary_text) > 300:
            summary_text = summary_text[:297] + "..."

        console.print(f"  [bold]{i}. {title}[/bold]")
        console.print(f"  [dim]{date}[/dim]")
        console.print(f"  {summary_text}\n")

    console.print(f"  [dim]distill show {channel_name}                     Full insights[/dim]")
    console.print(f"  [dim]distill synthesis {channel_name}                Synthesis[/dim]\n")


def _resolve_video_channel_name(url: str, video_info) -> str:
    return _shared_resolve_video_channel_name(url, video_info, resolve_channel_name)


def _ensure_channel_context(
    topic: str,
    channel_name: str,
    videos: list,
    config: DistillConfig,
    tracker: CostTracker,
) -> None:
    from distill.commands import _helpers

    _helpers.generate_channel_context = generate_channel_context
    _helpers.console = console
    cli_shared.generate_channel_context = generate_channel_context
    cli_shared.console = console
    return cli_shared.ensure_channel_context(topic, channel_name, videos, config, tracker)


def _process_video(
    topic: str,
    channel_name: str,
    video,
    config: DistillConfig,
    tracker: CostTracker,
    summary: RunSummary,
    state: ChannelState | None = None,
    analysis_mode: str = "auto",
    custom_instructions: str = "",
    eta: ETATracker | None = None,
) -> bool:
    from distill.commands import _helpers

    _helpers.analyze_short = analyze_short
    _helpers.analyze_video = analyze_video
    _helpers.analyze_scan = analyze_scan
    _helpers.get_transcript = get_transcript
    _helpers.console = console
    cli_shared.analyze_short = analyze_short
    cli_shared.analyze_video = analyze_video
    cli_shared.analyze_scan = analyze_scan
    cli_shared.get_transcript = get_transcript
    cli_shared.console = console
    return cli_shared.process_video(
        topic,
        channel_name,
        video,
        config,
        tracker,
        summary,
        state=state,
        analysis_mode=analysis_mode,
        custom_instructions=custom_instructions,
        eta=eta,
    )


def _run_scope_report(
    topic: str,
    config: DistillConfig,
    tracker: CostTracker,
    scope: str,
    channel_name: str | None = None,
    test: bool = False,
    summary: RunSummary | None = None,
    focus: str | None = None,
) -> None:
    from distill.commands import _helpers

    _helpers.console = console
    cli_shared.console = console
    return cli_shared.run_scope_report(
        topic,
        config,
        tracker,
        scope,
        channel_name=channel_name,
        test=test,
        summary=summary,
        focus=focus,
    )


def _get_version() -> str:
    """Get package version from metadata. Distribution is named ``distillr``."""
    from importlib.metadata import version

    for dist in ("distillr", "distill"):
        try:
            v = version(dist)
        except Exception:
            continue
        if v:  # guard against malformed metadata yielding an empty/None version
            return v
    return "dev"


def _truncate_channel_list(names: list[str], max_width: int, extra_count: int = 0) -> str:
    """Build a comma-separated channel list that fits within max_width."""
    if not names:
        return ""
    result = names[0]
    shown = 1
    for name in names[1:]:
        candidate = result + ", " + name
        if len(candidate) > max_width:
            break
        result = candidate
        shown += 1
    remaining = len(names) - shown + extra_count
    if remaining > 0:
        result += f" +{remaining} more"
    return result


def _site_section_change_summary(previous: dict, current_sections: list[dict]) -> list[str]:
    previous_sections = {
        item.get("section", ""): item
        for item in previous.get("sections", [])
        if isinstance(item, dict) and item.get("section")
    }
    messages: list[str] = []
    for item in current_sections:
        name = item["section"]
        prev = previous_sections.get(name)
        if prev is None:
            messages.append(f"{name} added ({item['page_count']} pages)")
            continue
        prev_urls = set(prev.get("urls", []))
        curr_urls = set(item.get("urls", []))
        if curr_urls != prev_urls:
            added = len(curr_urls - prev_urls)
            removed = len(prev_urls - curr_urls)
            bits = []
            if added:
                bits.append(f"+{added}")
            if removed:
                bits.append(f"-{removed}")
            messages.append(f"{name} changed ({', '.join(bits)})")
    for name, prev in previous_sections.items():
        if name not in {item["section"] for item in current_sections}:
            messages.append(f"{name} missing (was {prev.get('page_count', 0)} pages)")
    return messages[:8]


def _content_hash(text: str) -> str:
    # SHA-1 used for change-detection/deduplication only, not security.
    return sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()


def _collect_topic_bundle_files(config: DistillConfig, topic: str) -> list[Path]:
    topic_dir = config.topic_dir(topic)
    if not topic_dir.exists():
        return []
    files: list[Path] = []
    for path_obj in topic_dir.rglob("*"):
        if not path_obj.is_file():
            continue
        if path_obj.suffix.lower() not in {".md", ".json", ".txt"}:
            continue
        files.append(path_obj)
    files.sort()
    return files


def _topic_bundle_manifest(
    config: DistillConfig, topic: str, export_format: str, files: list[Path]
) -> dict:
    lib = Library(config)
    channels = lib.get_channels(topic)
    site_count, page_count = _count_site_corpus(config, [topic])
    paper_count = _count_paper_corpus(config, [topic])
    report_count, brief_count, synthesis_count = _count_topic_outputs(config, [topic])
    video_count = 0
    for ch in channels:
        videos_dir = config.channel_dir(topic, ch.name) / "videos"
        if not videos_dir.exists():
            continue
        for video_dir in videos_dir.iterdir():
            if video_dir.is_dir() and artifact_exists(video_dir, "insights"):
                video_count += 1
    return {
        "topic": topic,
        "format": export_format,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_types": {
            "youtube": bool(channels),
            "website": bool(site_count),
            "papers": bool(paper_count),
        },
        "counts": {
            "channels": len(channels),
            "videos": video_count,
            "sites": site_count,
            "pages": page_count,
            "papers": paper_count,
            "topic_syntheses": synthesis_count,
            "briefs": brief_count,
            "reports": report_count,
            "files": len(files),
        },
        "files": [
            {
                "path": str(path_obj.relative_to(config.topic_dir(topic)).as_posix()),
                "bytes": path_obj.stat().st_size,
                "kind": path_obj.suffix.lower().removeprefix("."),
            }
            for path_obj in files
        ],
    }


def _export_topic_bundle(config: DistillConfig, topic: str, export_format: str) -> Path:
    if export_format not in {"deepr", "bundle"}:
        raise typer.BadParameter("--format must be 'deepr' or 'bundle'")
    topic_dir = config.topic_dir(topic)
    if not topic_dir.exists():
        raise typer.Exit(1)
    files = _collect_topic_bundle_files(config, topic)
    if not files:
        raise typer.Exit(1)

    zip_path = _output_path(config, f"corpus-{topic}-{export_format}.zip")
    manifest = _topic_bundle_manifest(config, topic, export_format, files)

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        for path_obj in files:
            arcname = Path(topic) / path_obj.relative_to(topic_dir)
            zf.write(path_obj, arcname=str(arcname.as_posix()))
    return zip_path


# ─── Power Commands ──────────────────────────────────────────────────


# ─── Library Management ───────────────────────────────────────────────


# ─── Browsing & Inspection ────────────────────────────────────────────
# `show`, `package-latest`, `synthesis`, `findings` (+ their `_show_payload` /
# `_emit_content_json` helpers) moved to commands/view.py (decomposition slice 4).


# ─── Processing ────────────────────────────────────────────────────────


# ─── Report Generation ─────────────────────────────────────────────────


# ─── Status & Doctor ──────────────────────────────────────────────────


def _run_concepts_after_ingest(
    topic: str,
    *,
    tracker: "CostTracker | None" = None,
) -> None:
    """Run the concept playbook over a topic after an ingest succeeds.

    Helper for the ``--concepts`` opt-in flag on ``distill papers``,
    ``distill latest``, and ``distill site-batch``. Best-effort: any
    extraction failure logs but does not fail the ingest -- the freshly-
    ingested insights are still valuable on their own.
    """
    from distill.concepts import run_concepts
    from distill.llm import RouterConfig

    config = get_config()
    topic_dir = config.topic_dir(topic)
    if not topic_dir.exists():
        console.print(f"[dim]--concepts skipped (topic dir missing: {topic_dir})[/dim]")
        return
    console.print("\n[bold]Concept playbook[/bold]")
    try:
        summary = run_concepts(topic=topic, topic_dir=topic_dir, rc=RouterConfig(), tracker=tracker)
    except Exception as exc:
        console.print(f"[yellow]Concept extraction failed: {exc}[/yellow]")
        return
    console.print(
        f"  scanned={summary.insights_scanned} "
        f"extracted={summary.insights_extracted} "
        f"mentions+={summary.mentions_added} "
        f"notes={summary.notes_written} (concepts={summary.concepts_written}, entities={summary.entities_written}, unchanged={summary.concepts_unchanged})"
    )


concepts_app = typer.Typer(
    help=(
        "Concept and entity playbook for a topic.\n\n"
        "  distill concepts build <topic>            extract + merge playbook notes\n"
        "  distill concepts log <topic> <slug>       list a note's history snapshots\n"
        "  distill concepts diff <topic> <slug>      diff a note against its history\n"
        "  distill concepts rollback <topic> <slug> <timestamp>   restore a snapshot\n"
    ),
    rich_markup_mode="rich",
    no_args_is_help=True,
)
app.add_typer(concepts_app, name="concepts", rich_help_panel="Library")
# The `concepts build` command (and the log/diff/rollback recovery surface) live
# in commands/concepts.py and are attached to concepts_app via its register().


# ─── Cleanup ────────────────────────────────────────────────────────


# `costs` + `cleanup` (and the cost-private telemetry helpers) moved to
# commands/maintain.py (decomposition: Maintain slice 1).


# ─── Migration ───────────────────────────────────────────────────────


# ─── Topic Watch ────────────────────────────────────────────────────

topic_watch_app = typer.Typer(
    help="Manage your recurring topic watches",
    invoke_without_command=True,
    rich_markup_mode="rich",
)
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
        ranking_label = _topic_watch_ranking_strategy(e.ranking_mode)["label"]
        trend_label = _topic_trend_label(config, e.topic)
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
    ranking_mode = _normalize_topic_watch_ranking_mode(ranking)
    _learning_flow_support.validate_learning_options(sort, limit, days, per_channel_cap)

    config = get_config()
    lib = Library(config)
    topic_name = topic or _topic_from_query(query)
    watch_name = _topic_watch_name(query, topic_name, name)
    ranking_strategy = _topic_watch_ranking_strategy(ranking_mode)

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
        budget_bits = []
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
    ranking_mode = _normalize_topic_watch_ranking_mode(ranking)
    ranking_strategy = _topic_watch_ranking_strategy(ranking_mode)
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
        parts = []
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
def topic_watch_run(  # noqa: C901 — legacy, will refactor
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

    # Check new location first, fall back to old
    _ops_log = config.library_dir / ".distill" / "cost_log.jsonl"
    _legacy_log = config.library_dir / "cost_log.jsonl"
    _cost_log = _ops_log if _ops_log.exists() else _legacy_log
    all_cost_entries = _load_all_cost_runs(_cost_log)
    generated_alerts: list[str] = []
    alert_generated_at = datetime.now()

    for entry in watchlist:
        ranking = _topic_watch_ranking_strategy(entry.ranking_mode)
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
        change_details = _collect_topic_change_details(
            config,
            # Reload: _run_learning_command builds its own Library and may have
            # saved a newly-discovered channel to disk this run; the outer lib
            # (loaded before the run) would miss it and undercount the diff.
            Library(config),
            entry.topic,
            previous_run_at,
        )
        change_summary = str(change_details.get("summary", "no recent change detected"))
        briefing_path = _write_topic_change_briefing(
            config,
            watch_name=entry.name,
            topic=entry.topic,
            query=entry.query,
            cadence=entry.cadence,
            baseline=previous_run_at,
            summary=change_summary,
            change_details=change_details,
        )
        trend_label = _topic_trend_label(config, entry.topic)
        alert_lines = _topic_watch_alert_lines(
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

    alerts_path = _write_watch_alert_digest(
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


# ─── Watch List ──────────────────────────────────────────────────────


_ACCENT = "rgb(100,149,237)"


# ─── Catch-Up ────────────────────────────────────────────────────────


def _print_goal_refreshes(config, *, topic_filter: str | None = None) -> list[str]:
    """Print (and return) the refresh commands for persisted topic goals."""
    from distill.pipeline.goals import goal_refresh_command, load_topic_goals

    goals = load_topic_goals(config.library_dir)
    if topic_filter:
        goals = {t: e for t, e in goals.items() if t == topic_filter}
    lines = [goal_refresh_command(t, e) for t, e in sorted(goals.items())]
    if lines:
        console.print("\n  [dim]Goal-driven topics — refresh against their saved goals:[/dim]")
        for line in lines:
            console.print(f"  [cyan]{line}[/cyan]")
    return lines


def _process_site_seed(  # noqa: C901 — legacy, will refactor
    seed: SiteSeed,
    config: DistillConfig,
    tracker: CostTracker,
    summary: RunSummary,
    scrape_only: bool = False,
    ingest_attachments: bool = False,
) -> tuple[str, int]:
    site_name = seed.resolved_site_name()
    mode_label = "scrape-only" if scrape_only else "full"
    console.print(f"\n[bold]Site: {site_name}[/bold]")
    console.print(
        f"[dim]Seed: {seed.url} | max_pages={seed.max_pages} depth={seed.max_depth} mode={mode_label} | attachments={'on' if ingest_attachments else 'inventory-only'}[/dim]"
    )

    pages = crawl_site(seed)
    if not pages:
        summary.add_issue(
            "site-crawl",
            "No pages were extracted from the site.",
            context=seed.url,
            details={"site": site_name, "topic": seed.topic, "scrape_only": scrape_only},
        )
        return site_name, 0

    site_dir = config.site_dir(seed.topic, site_name)
    pages_dir = config.site_pages_dir(seed.topic, site_name)
    pages_dir.mkdir(parents=True, exist_ok=True)
    site_manifest_path = site_dir / "site.json"
    previous_manifest = _load_site_manifest(site_manifest_path)
    crawled_at = datetime.now().isoformat(timespec="seconds")
    section_state = _build_site_section_state(pages)
    for section in section_state:
        section["last_crawled_at"] = crawled_at
    section_changes = _site_section_change_summary(previous_manifest, section_state)
    manifest = {
        "seed_url": seed.url,
        "site_name": site_name,
        "page_count": len(pages),
        "max_depth": seed.max_depth,
        "max_pages": seed.max_pages,
        "scrape_only": scrape_only,
        "ingest_attachments": ingest_attachments,
        "generated_at": crawled_at,
        "sections": section_state,
        "section_changes": section_changes,
    }
    site_manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    summary.add_output(site_manifest_path)
    if section_changes:
        update_lines = [
            f"# Site Update: {site_name}",
            "",
            f"- Seed: {seed.url}",
            f"- Generated: {crawled_at}",
            "",
            "## Section Changes",
        ]
        update_lines.extend(f"- {item}" for item in section_changes)
        update_path = write_markdown_artifact(
            site_dir,
            "site_update",
            "\n".join(update_lines),
            identity=f"{seed.topic}_{site_name}",
            frontmatter=base_frontmatter(
                artifact_type="site_update",
                title=f"Site Update: {site_name}",
                topic=seed.topic,
                source="website",
                url=seed.url,
                tags=tags_for(seed.topic, "website", "update"),
                synthesis_scope="operational",
                extra={"site": site_name, "legacy_filename": "site_update.md"},
            ),
        )
        summary.add_output(update_path)

    analyzed_pages = 0
    skipped_pages = 0
    for index, page_obj in enumerate(pages, 1):
        console.print(f"  [{index}/{len(pages)}] [bold]{page_obj.title}[/bold]")
        page_dir = config.site_page_dir(seed.topic, site_name, page_obj.title, page_obj.page_id)
        page_dir.mkdir(parents=True, exist_ok=True)
        attachments = []
        if ingest_attachments:
            attachments, attachment_context = ingest_page_attachments(page_obj, page_dir, config)
            if attachment_context:
                page_obj.attachment_context = attachment_context
        else:
            attachments = collect_page_attachments(page_obj)
        if not attachments:
            attachments = collect_page_attachments(page_obj)
        attachment_manifest = write_attachment_manifest(page_dir, attachments)
        if attachment_manifest:
            summary.add_output(attachment_manifest)
            for item in attachments:
                if item.text_path:
                    attachment_text_path = page_dir / "attachments" / item.text_path
                    summary.add_output(attachment_text_path)
        page_document = build_page_document(page_obj)
        content_hash = _content_hash(page_document)
        previous_metadata = {}
        metadata_path = page_dir / "metadata.json"
        if metadata_path.exists():
            try:
                previous_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                previous_metadata = {}
        page_meta = page_obj.metadata()
        page_meta["content_hash"] = content_hash
        metadata_path = page_dir / "metadata.json"
        metadata_path.write_text(json.dumps(page_meta, indent=2), encoding="utf-8")
        summary.add_output(metadata_path)
        page_frontmatter = base_frontmatter(
            artifact_type="content",
            title=page_obj.title,
            topic=seed.topic,
            source="website",
            source_id=page_obj.page_id,
            url=page_obj.final_url or page_obj.url,
            date=page_obj.published_at,
            authors=page_obj.authors,
            tags=[*tags_for(seed.topic, "website"), *page_obj.tags],
            synthesis_scope="source-content",
            extra={
                "site": page_obj.site_name,
                "page_type": page_obj.page_type,
                "canonical_url": page_meta.get("canonical_url", ""),
                "section": page_meta.get("section", ""),
                "legacy_filename": "content.md",
            },
        )
        content_path = write_markdown_artifact(
            page_dir,
            "content",
            page_document,
            frontmatter=page_frontmatter,
        )
        summary.add_output(content_path)
        if page_obj.transcript.strip():
            transcript_path = write_text_artifact(
                page_dir,
                "transcript",
                page_obj.transcript,
                extension="txt",
            )
            summary.add_output(transcript_path)
        if scrape_only:
            continue
        insights_path = find_artifact(page_dir, "insights")
        if previous_metadata.get("content_hash") == content_hash and insights_path.exists():
            skipped_pages += 1
            summary.add_output(insights_path)
            console.print("    [dim]unchanged page — reusing existing insights[/dim]")
            continue
        try:
            insights = analyze_site_page(
                page_obj, config, tracker=tracker, intent=_resolve_intent(config, seed.topic)
            )

            # Write-time verify hook: ground numeric claims against the page
            # content receipt *before* committing; strict mode refuses.
            from distill.pipeline.verify import resolve_verify_mode, run_verify_hook

            outcome = run_verify_hook(
                page_dir,
                insights,
                page_document,
                mode=resolve_verify_mode(config.distill_verify),
                insight_name=insights_path.name,
                source_name=content_path.name,
            )
            if outcome is not None and not outcome.report.ok:
                style = "red" if outcome.refused else "yellow"
                console.print(f"  [{style}]{outcome.summary_line}[/{style}]")
            if outcome is not None and outcome.refused:
                summary.add_issue("verify", outcome.summary_line, context=page_obj.url)
                continue

            insights_path = write_markdown_artifact(
                page_dir,
                "insights",
                insights,
                frontmatter={
                    **page_frontmatter,
                    "type": "insights",
                    "synthesis_scope": "single-source",
                    "legacy_filename": "insights.md",
                },
            )
            summary.add_output(insights_path)
            analyzed_pages += 1
        except Exception as exc:
            console.print(f"  [red]Insight extraction failed: {exc}[/red]")
            cli_shared.record_exception_issue(
                summary,
                stage="site-page-analysis",
                exc=exc,
                context=page_obj.url,
                details={"site": site_name, "topic": seed.topic, "title": page_obj.title},
            )

    if scrape_only:
        return site_name, len(pages)

    manifest["analyzed_pages"] = analyzed_pages
    manifest["skipped_pages"] = skipped_pages
    site_manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    try:
        synthesis = synthesize_site(seed.topic, site_name, config, tracker=tracker)
        if synthesis:
            summary.add_output(
                find_artifact(
                    config.site_dir(seed.topic, site_name),
                    "site_synthesis",
                    identity=f"{seed.topic}_{site_name}",
                )
            )
    except Exception as exc:
        cli_shared.record_exception_issue(
            summary,
            stage="site-synthesis",
            exc=exc,
            context=seed.url,
            details={"site": site_name, "topic": seed.topic},
        )

    return site_name, len(pages)


def _write_paper_artifacts(
    topic: str,
    paper: PaperRecord,
    config: DistillConfig,
    insights: str,
    document: str | None = None,
) -> Path:
    paper_dir = config.paper_dir(topic, paper.title, paper.paper_id)
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "metadata.json").write_text(
        json.dumps(paper.metadata(), indent=2),
        encoding="utf-8",
    )
    paper_doc = document if document is not None else build_paper_document(paper)
    paper_frontmatter = base_frontmatter(
        artifact_type="paper",
        title=paper.title,
        topic=topic,
        source=paper.source,
        source_id=paper.paper_id,
        url=paper.abs_url,
        date=paper.published_at,
        authors=paper.authors,
        tags=[*tags_for(topic, paper.source), *paper.categories],
        synthesis_scope="source-content",
        extra={
            "paper_id": paper.paper_id,
            "pdf_url": paper.pdf_url,
            "updated_at": paper.updated_at,
            "categories": paper.categories,
            "legacy_filename": "paper.md",
        },
    )
    write_markdown_artifact(paper_dir, "paper", paper_doc, frontmatter=paper_frontmatter)
    # Write-time verify hook: ground the insight's numeric claims against the
    # paper text receipt *before* committing it; strict mode refuses the write.
    from distill.library.paths import artifact_filename
    from distill.pipeline.verify import resolve_verify_mode, run_verify_hook

    outcome = run_verify_hook(
        paper_dir,
        insights,
        paper_doc,
        mode=resolve_verify_mode(config.distill_verify),
        insight_name=artifact_filename(paper_dir.name, "insights"),
        source_name=artifact_filename(paper_dir.name, "paper"),
    )
    if outcome is not None and not outcome.report.ok:
        style = "red" if outcome.refused else "yellow"
        console.print(f"    [{style}]{outcome.summary_line}[/{style}]")
    if outcome is not None and outcome.refused:
        return paper_dir

    write_markdown_artifact(
        paper_dir,
        "insights",
        insights,
        frontmatter={
            **paper_frontmatter,
            "type": "insights",
            "synthesis_scope": "single-paper",
            "legacy_filename": "insights.md",
        },
    )
    return paper_dir


def _apply_source_rigor(ranked: list, *, source: str, rigor: str, rerank_on: bool, limit: int):
    """Drop reranked items below the per-source rigor bar, then cap at ``limit``.

    ``rigor="off"`` (the papers/latest default) is a passthrough. Rigor is
    calibrated to the LLM rerank's ``final_score``; with ``--no-rerank`` the
    scores are heuristic and off that scale, so an explicit bar is skipped with a
    warning rather than mis-filtering. Used by ``papers`` and ``latest``.
    """
    if rigor == "off":
        return ranked[:limit]
    if not rerank_on:
        console.print(
            f"[yellow]--rigor {rigor} needs the LLM rerank (it scores on the rerank's scale); "
            "ignoring it under --no-rerank.[/yellow]"
        )
        return ranked[:limit]
    from distill.pipeline.discovery import source_rigor_threshold

    threshold = source_rigor_threshold(source, rigor)
    kept = [r for r in ranked if r.final_score >= threshold]
    if len(kept) < len(ranked):
        console.print(
            f"  [dim]--rigor {rigor}: kept {len(kept)}/{len(ranked)} candidate(s) "
            f"(score >= {threshold:.2f})[/dim]"
        )
    if not kept:
        console.print(
            f"[yellow]No candidates clear the '{rigor}' bar (score >= {threshold:.2f}). "
            "Try --rigor loose.[/yellow]"
        )
    return kept[:limit]


def _is_fresh_topic(config, topic_name: str) -> bool:
    """True when the topic has no ingested artifacts yet (drives sizing-as-default)."""
    topic_dir = config.topic_dir(topic_name)
    if not topic_dir.exists():
        return True
    return not any(topic_dir.rglob("*.md"))


def _sizing_option_line(index: int, opt) -> str:
    """Format one sizing-menu row: number, label, source breakdown, basis, spend."""
    parts = []
    if opt.papers:
        parts.append(f"{opt.papers} paper(s)")
    if opt.videos:
        parts.append(f"{opt.videos} video(s)")
    if opt.sites:
        parts.append(f"{opt.sites} site(s)")
    breakdown = ", ".join(parts) if parts else "0 items"
    return (
        f"  [bold]{index}[/bold]. {opt.label} — {len(opt.items)} item(s) "
        f"({breakdown}); {opt.basis} — {opt.estimate.format()}"
    )


def _discover_sizing_flow(
    *,
    goal: str,
    topic_name: str,
    config,
    tracker,
    summary,
    ranked: list,
    paper_limit: int,
    video_limit: int,
    site_limit: int,
    ingest_attachments: bool,
) -> None:
    """Preview-as-default: show ranked candidates, offer sized options, ingest the pick.

    The chosen set is saved to the preview cache so the exact selection is
    re-runnable with ``--from-preview``. The menu choice is itself the
    confirmation, so the downstream ingest runs without a second prompt.
    """
    from distill.pipeline.costs import load_cost_calibration
    from distill.pipeline.discovery import build_sizing_options
    from distill.pipeline.preview_cache import preview_cache_dir, save_preview

    _display_ranked_discover(
        sorted(ranked, key=lambda r: r.final_score, reverse=True)[:25],
        title=f"Goal-Ranked Candidates ({len(ranked)} reranked)",
    )
    options = build_sizing_options(
        ranked,
        paper_limit=paper_limit,
        video_limit=video_limit,
        site_limit=site_limit,
        calibration=load_cost_calibration(config.library_dir),
    )
    if not options:
        console.print(
            "[yellow]No candidates worth ingesting at any quality bar. "
            "Broaden the goal or widen --days.[/yellow]"
        )
        return

    console.print("\n[bold]How much of this should I ingest?[/bold]")
    for i, opt in enumerate(options, 1):
        console.print(_sizing_option_line(i, opt))
    console.print("  [bold]n[/bold]. Cancel")

    # Interactive default is option 1; with no TTY, cancel instead -- proceeding
    # would ingest (spend) unattended. A loop ingests via --yes (rigor path).
    choice = _tty_prompt("\nChoose a size", default="1", non_tty_default="n").strip().lower()
    if choice in ("n", "no", "cancel", ""):
        console.print("[yellow]Aborted by user.[/yellow]")
        return
    try:
        idx = int(choice)
    except ValueError:
        idx = 0
    if idx < 1 or idx > len(options):
        console.print(f"[yellow]'{choice}' is not a listed option. Aborted.[/yellow]")
        return

    chosen = options[idx - 1]
    est = chosen.estimate
    # The accepted menu option's spend is the estimate of record for this run.
    summary.estimated_cost = est.expected
    snapshot = save_preview(
        preview_cache_dir(config.library_dir),
        goal=goal,
        model="",
        rigor=chosen.label,
        items=chosen.items,
        estimate={
            "expected": est.expected,
            "low": est.low,
            "high": est.high,
            "calibrated": est.calibrated,
        },
        now_iso=datetime.now().isoformat(),
    )
    console.print(
        f"[dim]Selected '{chosen.label}' set, saved as {snapshot.id} "
        f"(re-runnable with --from-preview {snapshot.id}).[/dim]"
    )
    _discover_ingest_set(
        topic_name=topic_name,
        config=config,
        tracker=tracker,
        summary=summary,
        ranked_papers=[it for it in chosen.items if it.kind == "paper"],
        ranked_videos=[it for it in chosen.items if it.kind == "video"],
        ranked_sites=[it for it in chosen.items if it.kind == "site"],
        ingest_attachments=ingest_attachments,
        yes=True,  # the menu selection IS the confirmation
    )


def _confirm_discover_ingest(topic_name, ranked_papers, ranked_videos, ranked_sites) -> bool:
    """Prompt before ingesting; return True to proceed."""
    parts = []
    if ranked_papers:
        parts.append(f"{len(ranked_papers)} paper(s)")
    if ranked_videos:
        parts.append(f"{len(ranked_videos)} video(s)")
    if ranked_sites:
        parts.append(f"{len(ranked_sites)} site seed(s)")
    ingest_summary = ", ".join(parts) if parts else "0 items"
    return _tty_confirm(f"\nIngest {ingest_summary} into topic '{topic_name}'?", default=False)


def _discover_ingest_papers(topic_name, config, tracker, summary, ranked_papers) -> None:
    """Analyze and write the ranked papers, then refresh the paper synthesis.

    One failed paper must not kill the run: the failure is recorded as a run
    issue and the loop continues, so the synthesis still covers everything
    that landed and a convergent re-run retries only the failures. (The
    dogfood library carried the scar of the old behavior: a topic with five
    papers newer than its last synthesis, from a run that died mid-loop.)
    """
    console.print(f"\n[bold]Ingesting {len(ranked_papers)} paper(s)[/bold]")
    for idx, item in enumerate(ranked_papers, 1):
        paper = item.paper
        if paper is None:
            continue
        console.print(f"  [{idx}/{len(ranked_papers)}] [bold]{paper.title}[/bold]")
        try:
            insights, document = analyze_paper(
                paper, config, tracker=tracker, intent=_resolve_intent(config, topic_name)
            )
            paper_dir = _write_paper_artifacts(topic_name, paper, config, insights, document)
        except BudgetExceededError:
            raise  # the spend cap is a hard stop, never a per-item issue
        except Exception as exc:
            console.print(f"  [red]failed: {exc}[/red]")
            cli_shared.record_exception_issue(
                summary,
                stage="paper-analysis",
                exc=exc,
                context=paper.title,
                details={"topic": topic_name, "paper_id": getattr(paper, "paper_id", "")},
            )
            continue
        summary.add_output(find_artifact(paper_dir, "paper"))
        summary.add_output(find_artifact(paper_dir, "insights"))
    if synthesize_papers(topic_name, config, tracker=tracker):
        summary.add_output(
            find_artifact(config.topic_dir(topic_name), "paper_synthesis", identity=topic_name)
        )


def _discover_ingest_videos(topic_name, config, tracker, ranked_videos) -> None:
    """Ingest the ranked videos through the shared learning pipeline."""
    console.print(f"\n[bold]Ingesting {len(ranked_videos)} video(s)[/bold]")
    video_items = [
        SimpleNamespace(video=r.video, final_score=r.final_score, rationale=r.rationale)
        for r in ranked_videos
        if r.video is not None
    ]
    _process_learning_selection(
        topic_name,
        config,
        tracker,
        video_items,
        save=True,
        report=False,
        test=False,
        generate_brief=False,
    )


def _discover_ingest_sites(
    topic_name, config, tracker, summary, ranked_sites, ingest_attachments, *, has_videos
) -> None:
    """Ingest the ranked site seeds (single page each)."""
    console.print(f"\n[bold]Ingesting {len(ranked_sites)} site seed(s)[/bold]")
    for idx, item in enumerate(ranked_sites, 1):
        seed = item.site_seed
        if seed is None:
            continue
        console.print(f"  [{idx}/{len(ranked_sites)}] [bold]{item.title}[/bold]")
        adjusted_seed = SiteSeed(
            url=seed.url,
            topic=topic_name,
            site_name=seed.site_name,
            label=seed.label,
            max_depth=0,
            max_pages=1,
            same_section_only=seed.same_section_only,
        )
        try:
            _process_site_seed(
                adjusted_seed,
                config,
                tracker,
                summary,
                scrape_only=False,
                ingest_attachments=ingest_attachments,
            )
        except BudgetExceededError:
            raise  # the spend cap is a hard stop, never a per-item issue
        except Exception as exc:
            console.print(f"  [red]failed: {exc}[/red]")
            cli_shared.record_exception_issue(
                summary,
                stage="site-ingest",
                exc=exc,
                context=seed.url,
                details={"topic": topic_name, "site": seed.site_name or ""},
            )
    # When videos were also ingested, they own the topic_synthesis artifact
    # (written by synthesize_topic). Running the website topic synthesis here
    # would overwrite it and drop the video story from the user-facing
    # Topic_Synthesis.md. The website material is still bridged into the corpus
    # synthesis via the per-site syntheses, so skip the site-level topic
    # synthesis in mixed (video + site) runs.
    if has_videos:
        return
    try:
        if synthesize_site_topic(topic_name, config, tracker=tracker):
            summary.add_output(
                find_artifact(config.topic_dir(topic_name), "topic_synthesis", identity=topic_name)
            )
    except Exception as exc:
        cli_shared.record_exception_issue(
            summary,
            stage="site-topic-synthesis",
            exc=exc,
            context=topic_name,
            details={"topic": topic_name},
        )


def _discover_ingest_set(
    *,
    topic_name: str,
    config,
    tracker,
    summary,
    ranked_papers: list,
    ranked_videos: list,
    ranked_sites: list,
    ingest_attachments: bool,
    yes: bool,
) -> None:
    """Ingest an already-ranked discover set (papers + videos + site seeds).

    Shared by the live discover flow and ``--from-preview`` replay so a previewed
    set ingests through the exact same path it would on a fresh run. Each ranked
    item carries its source payload (``.paper`` / ``.video`` / ``.site_seed``).
    """
    if not yes and not _confirm_discover_ingest(
        topic_name, ranked_papers, ranked_videos, ranked_sites
    ):
        console.print("[yellow]Aborted by user.[/yellow]")
        display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
        return

    if ranked_papers:
        _discover_ingest_papers(topic_name, config, tracker, summary, ranked_papers)
    if ranked_videos:
        _discover_ingest_videos(topic_name, config, tracker, ranked_videos)
    if ranked_sites:
        _discover_ingest_sites(
            topic_name,
            config,
            tracker,
            summary,
            ranked_sites,
            ingest_attachments,
            has_videos=bool(ranked_videos),
        )

    if synthesize_corpus(topic_name, config, tracker=tracker):
        summary.add_output(
            find_artifact(config.topic_dir(topic_name), "corpus_synthesis", identity=topic_name)
        )
    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)


def main():
    """Entry point for the `distill` CLI command."""
    app()


if __name__ == "__main__":
    main()
