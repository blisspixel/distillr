"""Website batch command helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import distill.cli_shared as cli_shared
from distill._console import console
from distill.ingestors.sites.scraper import SiteSeed
from distill.pipeline.costs import BudgetExceededError, CostTracker
from distill.pipeline.summary import BatchProgress, RunSummary

__all__ = ["process_site_batch_seed", "site_batch_seed"]


def site_batch_seed(
    seed: SiteSeed,
    *,
    seed_only: bool,
    same_section_only: bool,
) -> SiteSeed:
    return SiteSeed(
        url=seed.url,
        topic=seed.topic,
        site_name=seed.site_name,
        label=seed.label,
        max_depth=0 if seed_only else seed.max_depth,
        max_pages=1 if seed_only else seed.max_pages,
        same_section_only=same_section_only or seed.same_section_only,
    )


def process_site_batch_seed(
    seed: SiteSeed,
    *,
    config: Any,
    tracker: CostTracker,
    summary: RunSummary,
    progress: BatchProgress,
    scrape_only: bool,
    ingest_attachments: bool,
    process_site_seed: Callable[..., object],
) -> None:
    item_start = progress.start_item()
    progress_title = seed.label or seed.resolved_site_name()
    console.print(progress.item_line("crawl", progress_title))
    try:
        process_site_seed(
            seed,
            config,
            tracker,
            summary,
            scrape_only=scrape_only,
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
            details={"topic": seed.topic, "site": seed.site_name or ""},
        )
        progress.finish_item(item_start, success=False)
        console.print(progress.status_line("failed"))
        return
    progress.finish_item(item_start, success=True)
    console.print(progress.status_line("done"))
