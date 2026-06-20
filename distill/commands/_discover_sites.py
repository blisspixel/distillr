"""Website candidate loading for goal-aware discover."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from distill._console import console
from distill.ingestors.sites.discovery import discover_trusted_site_seeds
from distill.ingestors.sites.scraper import SiteSeed, canonicalize_url, load_site_batch

__all__ = ["DiscoverSiteCandidates", "load_discover_site_candidates", "show_discover_site_summary"]


@dataclass(frozen=True)
class DiscoverSiteCandidates:
    sites: list[SiteSeed]
    curated_count: int
    trusted_count: int
    trusted_sources: int


def load_discover_site_candidates(
    *,
    topic_name: str,
    site_seeds: Path | None,
    trusted_sites: list[str],
    trusted_site_cap: int,
    site_crawl_depth: int = 0,
    site_crawl_pages: int = 1,
    trusted_site_discoverer: Any = discover_trusted_site_seeds,
) -> DiscoverSiteCandidates:
    """Load curated site seeds and generated trusted-site page candidates."""
    curated: list[SiteSeed] = []
    if site_seeds is not None:
        if not site_seeds.exists():
            raise FileNotFoundError(site_seeds)
        curated = load_site_batch(site_seeds, topic_override=topic_name).seeds

    trusted_result = trusted_site_discoverer(
        trusted_sites,
        topic=topic_name,
        max_candidates=trusted_site_cap,
    )
    sites = _with_discover_crawl(
        _dedupe_site_seeds([*curated, *trusted_result.seeds]),
        max_depth=site_crawl_depth,
        max_pages=site_crawl_pages,
    )
    return DiscoverSiteCandidates(
        sites=sites,
        curated_count=len(curated),
        trusted_count=len(trusted_result.seeds),
        trusted_sources=trusted_result.source_count,
    )


def show_discover_site_summary(
    *,
    site_candidates: DiscoverSiteCandidates | None,
    site_seeds: Path | None,
    trusted_site_sources: list[str],
    site_crawl_depth: int,
    site_crawl_pages: int,
) -> None:
    if site_candidates is None:
        return
    if site_seeds is not None:
        console.print(
            f"[dim]Curated site seeds: {site_candidates.curated_count} loaded from {site_seeds}[/dim]"
        )
    if trusted_site_sources:
        console.print(
            f"[dim]Trusted-site candidates: {site_candidates.trusted_count} from "
            f"{site_candidates.trusted_sources} source(s)[/dim]"
        )
    if site_seeds is not None or trusted_site_sources:
        if site_crawl_depth > 0:
            console.print(
                f"[dim]Website crawl: depth {site_crawl_depth}, "
                f"max {site_crawl_pages} page(s) per selected seed[/dim]"
            )
        console.print()


def _dedupe_site_seeds(seeds: list[SiteSeed]) -> list[SiteSeed]:
    seen: set[str] = set()
    result: list[SiteSeed] = []
    for seed in seeds:
        key = canonicalize_url(seed.url)
        if key in seen:
            continue
        seen.add(key)
        result.append(seed)
    return result


def _with_discover_crawl(
    seeds: list[SiteSeed], *, max_depth: int, max_pages: int
) -> list[SiteSeed]:
    depth = max(0, max_depth)
    pages = max(1, max_pages) if depth > 0 else 1
    return [
        SiteSeed(
            url=seed.url,
            topic=seed.topic,
            site_name=seed.site_name,
            label=seed.label,
            section_label=seed.section_label,
            source_hint=seed.source_hint,
            freshness_hint=seed.freshness_hint,
            crawl_prefix=seed.crawl_prefix,
            discover_crawl=depth > 0,
            max_depth=depth,
            max_pages=pages,
            same_section_only=seed.same_section_only,
        )
        for seed in seeds
    ]
