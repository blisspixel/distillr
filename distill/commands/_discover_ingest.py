"""Discover ingest helpers for mixed-source runs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import distill.cli_shared as cli_shared
from distill._console import console
from distill.commands._site_ingest import site_ingest_status_phase
from distill.ingestors.sites.scraper import SiteSeed
from distill.pipeline.costs import BudgetExceededError
from distill.pipeline.summary import BatchProgress

__all__ = ["ingest_papers", "ingest_sites"]


def ingest_papers(
    topic_name: str,
    config: Any,
    tracker: Any,
    summary: Any,
    ranked_papers: list[Any],
    *,
    analyze_paper_fn: Callable[..., tuple[str, str]],
    write_paper_artifacts_fn: Callable[..., Any],
    synthesize_papers_fn: Callable[..., Any],
    resolve_intent_fn: Callable[..., Any],
    find_artifact_fn: Callable[..., Any],
) -> None:
    """Analyze selected papers, isolate per-paper failures, then refresh synthesis."""
    console.print(f"\n[bold]Ingesting {len(ranked_papers)} paper(s)[/bold]")
    progress = BatchProgress("paper", len(ranked_papers), tracker)
    for item in ranked_papers:
        paper = item.paper
        if paper is None:
            continue
        item_start = progress.start_item()
        console.print(progress.item_line("analyze", paper.title))
        try:
            insights, document = analyze_paper_fn(
                paper, config, tracker=tracker, intent=resolve_intent_fn(config, topic_name)
            )
            paper_dir = write_paper_artifacts_fn(topic_name, paper, config, insights, document)
        except BudgetExceededError:
            raise
        except Exception as exc:
            console.print(f"  [red]failed: {exc}[/red]")
            cli_shared.record_exception_issue(
                summary,
                stage="paper-analysis",
                exc=exc,
                context=paper.title,
                details={"topic": topic_name, "paper_id": getattr(paper, "paper_id", "")},
            )
            progress.finish_item(item_start, success=False)
            console.print(progress.status_line("failed"))
            continue
        summary.add_output(find_artifact_fn(paper_dir, "paper"))
        summary.add_output(find_artifact_fn(paper_dir, "insights"))
        progress.finish_item(item_start, success=True)
        console.print(progress.status_line("done"))

    if synthesize_papers_fn(topic_name, config, tracker=tracker):
        summary.add_output(
            find_artifact_fn(config.topic_dir(topic_name), "paper_synthesis", identity=topic_name)
        )


def ingest_sites(
    topic_name: str,
    config: Any,
    tracker: Any,
    summary: Any,
    ranked_sites: list[Any],
    ingest_attachments: bool,
    *,
    has_videos: bool,
    process_site_seed_fn: Callable[..., Any],
    synthesize_site_topic_fn: Callable[..., Any],
    find_artifact_fn: Callable[..., Any],
) -> None:
    """Ingest selected site seeds, isolate per-seed failures, then refresh synthesis."""
    console.print(f"\n[bold]Ingesting {len(ranked_sites)} site seed(s)[/bold]")
    progress = BatchProgress("site", len(ranked_sites), tracker)
    for item in ranked_sites:
        seed = item.site_seed
        if seed is None:
            continue
        item_start = progress.start_item()
        console.print(progress.item_line("crawl", item.title))
        adjusted_seed = SiteSeed(
            url=seed.url,
            topic=topic_name,
            site_name=seed.site_name,
            label=seed.label,
            section_label=seed.section_label,
            source_hint=seed.source_hint,
            freshness_hint=seed.freshness_hint,
            discover_crawl=seed.discover_crawl,
            max_depth=max(0, seed.max_depth) if seed.discover_crawl else 0,
            max_pages=max(1, seed.max_pages) if seed.discover_crawl else 1,
            same_section_only=seed.same_section_only,
        )
        try:
            result = process_site_seed_fn(
                adjusted_seed,
                config,
                tracker,
                summary,
                scrape_only=False,
                ingest_attachments=ingest_attachments,
            )
        except BudgetExceededError:
            raise
        except Exception as exc:
            console.print(f"  [red]failed: {exc}[/red]")
            cli_shared.record_exception_issue(
                summary,
                stage="site-ingest",
                exc=exc,
                context=seed.url,
                details={"topic": topic_name, "site": seed.site_name or ""},
            )
            progress.finish_item(item_start, success=False)
            console.print(progress.status_line("failed"))
            continue
        progress.finish_item(item_start, success=True)
        console.print(progress.status_line(site_ingest_status_phase(result)))

    if has_videos:
        return
    try:
        if synthesize_site_topic_fn(topic_name, config, tracker=tracker):
            summary.add_output(
                find_artifact_fn(
                    config.topic_dir(topic_name), "topic_synthesis", identity=topic_name
                )
            )
    except Exception as exc:
        cli_shared.record_exception_issue(
            summary,
            stage="site-topic-synthesis",
            exc=exc,
            context=topic_name,
            details={"topic": topic_name},
        )
