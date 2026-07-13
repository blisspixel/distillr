# pyright: strict
"""Discover command helper flow.

These helpers keep the public discover command module below the module-size
cap while preserving the same command-level patch points during decomposition.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import distill.pipeline.discovery as _discover_support
from distill._console import console
from distill.cli_shared import tty_confirm as _tty_confirm
from distill.cli_shared import tty_prompt as _tty_prompt
from distill.commands import _discover_ingest as _discover_ingest_support
from distill.commands._helpers import resolve_intent as _resolve_intent
from distill.commands._learning import (
    dedupe_candidates as _dedupe_candidates,
)
from distill.commands._learning import (
    dedupe_query_strings as _dedupe_query_strings,
)
from distill.commands._learning import (
    filter_recent_candidates as _filter_recent_candidates,
)
from distill.commands._learning import (
    process_learning_selection as _process_learning_selection,
)
from distill.commands._paper_artifacts import write_paper_artifacts as _write_paper_artifacts
from distill.commands._site_ingest import process_site_seed as _process_site_seed
from distill.config import DistillConfig
from distill.ingestors.papers.arxiv import PaperRecord
from distill.ingestors.sites.scraper import SiteSeed
from distill.ingestors.youtube.browser_search import search_youtube_results
from distill.ingestors.youtube.discovery import VideoInfo, enrich_videos
from distill.library.paths import find_artifact
from distill.llm.router import RouterConfig
from distill.parsing import parse_ascii_uint
from distill.pipeline.analysis.paper import analyze_paper, synthesize_papers
from distill.pipeline.analysis.site import synthesize_site_topic
from distill.pipeline.costs import CostTracker, load_cost_calibration
from distill.pipeline.summary import RunSummary, display_summary
from distill.pipeline.synthesis.corpus import synthesize_corpus

__all__ = [
    "_confirm_discover_ingest",
    "_discover_fetch_videos",
    "_discover_generate_queries",
    "_discover_ingest_papers",
    "_discover_ingest_set",
    "_discover_ingest_sites",
    "_discover_ingest_videos",
    "_discover_rerank",
    "_discover_sizing_flow",
    "_display_ranked_discover",
    "_is_fresh_topic",
    "_sizing_option_line",
]


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
) -> list[_discover_support.RankedDiscoverItem]:
    return _discover_support.discover_rerank(goal, papers, videos, sites, config, tracker)


def _display_ranked_discover(items: list[_discover_support.RankedDiscoverItem], title: str) -> None:
    _discover_support.display_ranked_discover(items, title)


def _is_fresh_topic(config: DistillConfig, topic_name: str) -> bool:
    """True when the topic has no ingested artifacts yet."""
    topic_dir = config.topic_dir(topic_name)
    if not topic_dir.exists():
        return True
    return not any(topic_dir.rglob("*.md"))


def _sizing_option_line(index: int, opt: _discover_support.SizingOption) -> str:
    """Format one sizing-menu row."""
    parts: list[str] = []
    if opt.papers:
        parts.append(f"{opt.papers} paper(s)")
    if opt.videos:
        parts.append(f"{opt.videos} video(s)")
    if opt.sites:
        parts.append(f"{opt.sites} site(s)")
    breakdown = ", ".join(parts) if parts else "0 items"
    return (
        f"  [bold]{index}[/bold]. {opt.label} - {len(opt.items)} item(s) "
        f"({breakdown}); {opt.basis} - {opt.estimate.format()}"
    )


def _discover_sizing_flow(
    *,
    goal: str,
    topic_name: str,
    config: DistillConfig,
    tracker: CostTracker,
    summary: RunSummary,
    ranked: list[_discover_support.RankedDiscoverItem],
    paper_limit: int,
    video_limit: int,
    site_limit: int,
    ingest_attachments: bool,
) -> None:
    """Preview by default, then ingest the selected size."""
    from distill.pipeline.preview_cache import preview_cache_dir, save_preview

    _display_ranked_discover(
        sorted(ranked, key=lambda r: r.final_score, reverse=True)[:25],
        title=f"Goal-Ranked Candidates ({len(ranked)} reranked)",
    )
    options = _discover_support.build_sizing_options(
        ranked,
        paper_limit=paper_limit,
        video_limit=video_limit,
        site_limit=site_limit,
        calibration=load_cost_calibration(config.library_dir),
        router_config=RouterConfig(),
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

    choice = _tty_prompt("\nChoose a size", default="1", non_tty_default="n").strip().lower()
    if choice in ("n", "no", "cancel", ""):
        console.print("[yellow]Aborted by user.[/yellow]")
        return
    idx = parse_ascii_uint(choice) or 0
    if idx < 1 or idx > len(options):
        console.print(f"[yellow]'{choice}' is not a listed option. Aborted.[/yellow]")
        return

    chosen = options[idx - 1]
    est = chosen.estimate
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
        yes=True,
    )


def _confirm_discover_ingest(
    topic_name: str,
    ranked_papers: list[_discover_support.RankedDiscoverItem],
    ranked_videos: list[_discover_support.RankedDiscoverItem],
    ranked_sites: list[_discover_support.RankedDiscoverItem],
) -> bool:
    """Prompt before ingesting; return True to proceed."""
    parts: list[str] = []
    if ranked_papers:
        parts.append(f"{len(ranked_papers)} paper(s)")
    if ranked_videos:
        parts.append(f"{len(ranked_videos)} video(s)")
    if ranked_sites:
        parts.append(f"{len(ranked_sites)} site seed(s)")
    ingest_summary = ", ".join(parts) if parts else "0 items"
    return _tty_confirm(f"\nIngest {ingest_summary} into topic '{topic_name}'?", default=False)


def _discover_ingest_papers(
    topic_name: str,
    config: DistillConfig,
    tracker: CostTracker,
    summary: RunSummary,
    ranked_papers: list[Any],
) -> None:
    """Analyze and write selected papers, then refresh paper synthesis."""
    _discover_ingest_support.ingest_papers(
        topic_name,
        config,
        tracker,
        summary,
        ranked_papers,
        analyze_paper_fn=analyze_paper,
        write_paper_artifacts_fn=_write_paper_artifacts,
        synthesize_papers_fn=synthesize_papers,
        resolve_intent_fn=_resolve_intent,
        find_artifact_fn=find_artifact,
    )


def _discover_ingest_videos(
    topic_name: str,
    config: DistillConfig,
    tracker: CostTracker,
    ranked_videos: list[_discover_support.RankedDiscoverItem],
) -> None:
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
    topic_name: str,
    config: DistillConfig,
    tracker: CostTracker,
    summary: RunSummary,
    ranked_sites: list[Any],
    ingest_attachments: bool,
    *,
    has_videos: bool,
) -> None:
    """Ingest selected site seeds, then refresh site topic synthesis."""
    _discover_ingest_support.ingest_sites(
        topic_name,
        config,
        tracker,
        summary,
        ranked_sites,
        ingest_attachments,
        has_videos=has_videos,
        process_site_seed_fn=_process_site_seed,
        synthesize_site_topic_fn=synthesize_site_topic,
        find_artifact_fn=find_artifact,
    )


def _discover_ingest_set(
    *,
    topic_name: str,
    config: DistillConfig,
    tracker: CostTracker,
    summary: RunSummary,
    ranked_papers: list[Any],
    ranked_videos: list[_discover_support.RankedDiscoverItem],
    ranked_sites: list[Any],
    ingest_attachments: bool,
    yes: bool,
) -> None:
    """Ingest an already-ranked discover set."""
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
