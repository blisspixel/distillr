# pyright: strict
"""Website batch command helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from distill._console import console
from distill.commands._helpers import record_exception_issue
from distill.commands._site_ingest import site_ingest_status_phase
from distill.ingestors.sites.scraper import MAX_SITE_BATCH_PAGES, SiteSeed
from distill.library.paths import find_artifact
from distill.llm.cost_policy import CostPolicyError
from distill.llm.errors import ProviderBusyTimeoutError
from distill.llm.router import RouterConfig
from distill.pipeline.analysis.site import synthesize_site_topic
from distill.pipeline.costs import (
    BudgetExceededError,
    CostTracker,
    estimate_site_batch_workflow_cost,
)
from distill.pipeline.summary import BatchProgress, RunSummary
from distill.pipeline.synthesis.corpus import synthesize_corpus

__all__ = [
    "SiteBatchPlanRow",
    "estimate_site_batch_plan_cost",
    "print_site_batch_plan",
    "process_site_batch_seed",
    "resolve_site_batch_seeds",
    "run_site_batch_syntheses",
    "site_batch_plan_payload",
    "site_batch_plan_rows",
    "site_batch_seed",
]


@dataclass(frozen=True)
class SiteBatchPlanRow:
    index: int
    url: str
    topic: str
    label: str
    mode: str
    max_depth: int
    max_pages: int
    boundary: str


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
        section_label=seed.section_label,
        source_hint=seed.source_hint,
        freshness_hint=seed.freshness_hint,
        crawl_prefix=seed.crawl_prefix,
        discover_crawl=seed.discover_crawl,
        max_depth=0 if seed_only else seed.max_depth,
        max_pages=1 if seed_only else seed.max_pages,
        same_section_only=same_section_only or seed.same_section_only,
    )


def resolve_site_batch_seeds(
    seeds: list[SiteSeed],
    *,
    seed_only: bool,
    same_section_only: bool,
) -> list[SiteSeed]:
    resolved = [
        site_batch_seed(
            seed,
            seed_only=seed_only,
            same_section_only=same_section_only,
        )
        for seed in seeds
    ]
    if sum(seed.max_pages for seed in resolved) > MAX_SITE_BATCH_PAGES:
        raise ValueError(f"site batch page budget exceeds {MAX_SITE_BATCH_PAGES}")
    return resolved


def site_batch_plan_rows(seeds: list[SiteSeed]) -> list[SiteBatchPlanRow]:
    return [_site_batch_plan_row(index, seed) for index, seed in enumerate(seeds, 1)]


def print_site_batch_plan(*, topic: str, seeds: list[SiteSeed]) -> None:
    rows = site_batch_plan_rows(seeds)
    console.print("[bold]Site batch preview[/bold]")
    console.print(f"[dim]Topic: {topic} | seeds: {len(rows)} | writes: none[/dim]")
    for row in rows:
        label = f" | label={row.label}" if row.label else ""
        console.print(
            f"{row.index}. {row.mode} | pages={row.max_pages} depth={row.max_depth} "
            f"| topic={row.topic} | boundary={row.boundary}{label} | {row.url}"
        )


def site_batch_plan_payload(*, topic: str, seeds: list[SiteSeed]) -> dict[str, Any]:
    rows = site_batch_plan_rows(seeds)
    return {
        "workflow": "site-batch",
        "preview": True,
        "topic": topic,
        "seed_count": len(rows),
        "writes": False,
        "seeds": [asdict(row) for row in rows],
    }


def estimate_site_batch_plan_cost(
    seeds: list[SiteSeed],
    *,
    include_report: bool = False,
    router_config: RouterConfig | None = None,
) -> float:
    planned_pages = sum(max(0, seed.max_pages) for seed in seeds)
    active_seeds = sum(1 for seed in seeds if seed.max_pages > 0)
    synthesis_calls = active_seeds + 2 if planned_pages > 0 else 0
    return estimate_site_batch_workflow_cost(
        planned_pages,
        synthesis_calls=synthesis_calls,
        include_report=include_report,
        router_config=router_config,
    )


def _site_batch_plan_row(index: int, seed: SiteSeed) -> SiteBatchPlanRow:
    return SiteBatchPlanRow(
        index=index,
        url=seed.url,
        topic=seed.topic,
        label=seed.label,
        mode=_site_batch_mode(seed),
        max_depth=seed.max_depth,
        max_pages=seed.max_pages,
        boundary=_site_batch_boundary(seed),
    )


def _site_batch_mode(seed: SiteSeed) -> str:
    if seed.max_depth <= 0 or seed.max_pages <= 1:
        return "exact-page"
    return "shallow-crawl"


def _site_batch_boundary(seed: SiteSeed) -> str:
    if seed.max_depth <= 0 or seed.max_pages <= 1:
        return "seed URL only"
    parts: list[str] = []
    if seed.crawl_prefix:
        parts.append(f"prefix {seed.crawl_prefix}")
    if seed.same_section_only:
        parts.append("same-section")
    if not parts:
        parts.append("same-host")
    return ", ".join(parts)


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
        result = process_site_seed(
            seed,
            config,
            tracker,
            summary,
            scrape_only=scrape_only,
            ingest_attachments=ingest_attachments,
        )
    except (BudgetExceededError, CostPolicyError, ProviderBusyTimeoutError):
        raise
    except Exception as exc:
        console.print(f"  [red]failed: {exc}[/red]")
        record_exception_issue(
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
    console.print(progress.status_line(site_ingest_status_phase(result)))


def run_site_batch_syntheses(
    target_topic: str,
    config: Any,
    tracker: CostTracker,
    summary: RunSummary,
) -> None:
    try:
        site_synth = synthesize_site_topic(target_topic, config, tracker=tracker)
        if site_synth:
            summary.add_output(
                find_artifact(
                    config.topic_dir(target_topic),
                    "site_synthesis",
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
    except (BudgetExceededError, CostPolicyError, ProviderBusyTimeoutError):
        raise
    except Exception as exc:
        record_exception_issue(
            summary,
            stage="site-topic-synthesis",
            exc=exc,
            context=target_topic,
            details={"topic": target_topic},
        )
