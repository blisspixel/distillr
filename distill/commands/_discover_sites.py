"""Website candidate loading for goal-aware discover."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from distill.ingestors.sites.discovery import discover_trusted_site_seeds
from distill.ingestors.sites.scraper import SiteSeed, canonicalize_url, load_site_batch

__all__ = ["DiscoverSiteCandidates", "load_discover_site_candidates"]


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
    sites = _dedupe_site_seeds([*curated, *trusted_result.seeds])
    return DiscoverSiteCandidates(
        sites=sites,
        curated_count=len(curated),
        trusted_count=len(trusted_result.seeds),
        trusted_sources=trusted_result.source_count,
    )


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
