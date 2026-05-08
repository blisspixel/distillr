"""Discover command helpers for the Distill CLI."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from rich import box
from rich.console import Console
from rich.table import Table

from distill.config import DistillConfig
from distill.ingestors.papers.arxiv import PaperRecord
from distill.ingestors.sites.scraper import SiteSeed
from distill.ingestors.youtube.discovery import VideoInfo
from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.discover import discover_query_generation_prompt, discover_rerank_prompt

# Constants duplicated from commands._helpers to avoid upward dependency.
SHORTS_THRESHOLD = 180

console = Console()
logger = logging.getLogger(__name__)


def _format_date(date_str: str) -> str:
    """Format YYYYMMDD or ISO date to readable format."""
    if not date_str:
        return "Unknown"
    try:
        if "T" in date_str:
            dt = datetime.fromisoformat(date_str)
            return dt.strftime("%b %d, %Y %I:%M %p")
        if len(date_str) == 8:
            dt = datetime.strptime(date_str, "%Y%m%d")
            return dt.strftime("%b %d, %Y")
    except (ValueError, TypeError):
        pass
    return date_str


__all__ = [
    "RankedDiscoverItem",
    "discover_fetch_videos",
    "discover_generate_queries",
    "discover_rerank",
    "display_ranked_discover",
]


@dataclass
class RankedDiscoverItem:
    kind: str
    identifier: str
    title: str
    subtitle: str
    date: str
    final_score: float
    goal_fit: float
    depth_score: float
    complementarity_score: float
    rationale: str
    paper: PaperRecord | None = None
    video: VideoInfo | None = None
    site_seed: SiteSeed | None = None


def _site_candidate_title(seed: SiteSeed) -> str:
    label = seed.label.strip()
    if label:
        return label
    parsed = urlparse(seed.url)
    host = parsed.netloc.removeprefix("www.") or seed.resolved_site_name()
    path = (parsed.path or "/").rstrip("/") or "/"
    return f"{host}{path}"


def _site_candidate_description(seed: SiteSeed) -> str:
    label = seed.label.strip()
    if label:
        return f"{label} | URL: {seed.url}"
    return f"Curated website seed | URL: {seed.url}"


def discover_generate_queries(
    goal: str,
    config: DistillConfig,
    tracker: CostTracker | None,
    *,
    paper_count: int,
    video_count: int,
    dedupe_query_strings,
) -> tuple[list[str], list[str]]:
    # Guard against the LLM being asked to do nothing useful when both sides are
    # disabled (e.g. via --papers-only and --videos-only somehow both off — caller
    # should have validated, but be defensive).
    if paper_count <= 0 and video_count <= 0:
        return [], []
    rc = RouterConfig()
    prompt = discover_query_generation_prompt(
        goal, paper_count=paper_count, video_count=video_count
    )
    response = llm_call(
        rc, workload_tag="rerank", prompt=prompt, max_tokens=768, call_type="discover_plan"
    )
    if tracker:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.input_tokens,
                completion_tokens=response.output_tokens,
                model=response.model,
                call_type="discover_plan",
            )
        )
    text = (response.text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    if not text:
        return [], []
    from distill.llm.json_extract import extract_json

    data = extract_json(text)
    if data is None:
        logger.warning("Failed to parse discover query generation response as JSON")
        return [], []
    paper_qs = data.get("paper_queries", []) if isinstance(data, dict) else []
    video_qs = data.get("video_queries", []) if isinstance(data, dict) else []
    paper_qs = dedupe_query_strings([q for q in paper_qs if isinstance(q, str)])
    video_qs = dedupe_query_strings([q for q in video_qs if isinstance(q, str)])
    # Honor the requested counts even if the LLM produced more on the disabled
    # side — keeps --papers-only / --videos-only from accidentally fetching the
    # excluded source type.
    if paper_count <= 0:
        paper_qs = []
    if video_count <= 0:
        video_qs = []
    return paper_qs, video_qs


def discover_fetch_videos(
    queries: list[str],
    effective_days: int,
    candidate_cap: int,
    shorts: bool,
    *,
    search_youtube_results,
    dedupe_candidates,
    enrich_videos,
    filter_recent_candidates,
) -> list[VideoInfo]:
    raw: list[VideoInfo] = []
    for idx, q in enumerate(queries, 1):
        console.print(f"[dim]Video search {idx}/{len(queries)}: {q}[/dim]")
        raw.extend(search_youtube_results(q, days=effective_days, hours=None, limit=candidate_cap))
    raw = dedupe_candidates(raw)
    if not raw:
        return []
    if not shorts:
        raw = [v for v in raw if v.duration > SHORTS_THRESHOLD]
    if not raw:
        return []
    enriched = enrich_videos(raw, max_videos=min(len(raw), 20))
    return filter_recent_candidates(enriched, effective_days, hours=None)


def discover_rerank(  # noqa: C901 — legacy, will refactor
    goal: str,
    papers: list[PaperRecord],
    videos: list[VideoInfo],
    sites: list[SiteSeed],
    config: DistillConfig,
    tracker: CostTracker | None,
) -> list[RankedDiscoverItem]:
    candidates: list[dict[str, Any]] = []
    paper_by_id = {p.paper_id: p for p in papers}
    video_by_id = {v.video_id: v for v in videos}
    site_by_id = {seed.url: seed for seed in sites}
    for p in papers:
        candidates.append(
            {
                "kind": "paper",
                "identifier": p.paper_id,
                "title": p.title,
                "subtitle": ", ".join((p.authors or [])[:3]) or "unknown",
                "date": (p.published_at or "")[:10],
                "description": p.abstract or "",
            }
        )
    for v in videos:
        candidates.append(
            {
                "kind": "video",
                "identifier": v.video_id,
                "title": v.title,
                "subtitle": v.channel_name or "unknown",
                "date": v.upload_date or "",
                "description": getattr(v, "description", "") or "",
            }
        )
    for seed in sites:
        candidates.append(
            {
                "kind": "site",
                "identifier": seed.url,
                "title": _site_candidate_title(seed),
                "subtitle": seed.resolved_site_name() or "website",
                "date": "",
                "description": _site_candidate_description(seed),
            }
        )
    if not candidates:
        return []

    rc = RouterConfig()
    prompt = discover_rerank_prompt(goal, candidates)
    response = llm_call(
        rc, workload_tag="rerank", prompt=prompt, max_tokens=8192, call_type="discover_rerank"
    )
    if tracker:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.input_tokens,
                completion_tokens=response.output_tokens,
                model=response.model,
                call_type="discover_rerank",
            )
        )
    text = (response.text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    if not text:
        return []
    from distill.llm.json_extract import extract_json

    data = extract_json(text)
    if data is None:
        logger.warning("Failed to parse discover rerank response as JSON")
        return []
    items = data.get("ranked_items", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []

    ranked: list[RankedDiscoverItem] = []
    for entry in items:
        kind = str(entry.get("kind", "")).strip()
        identifier = str(entry.get("identifier", "")).strip()
        if kind == "paper":
            paper = paper_by_id.get(identifier)
            if not paper:
                continue
            ranked.append(
                RankedDiscoverItem(
                    kind="paper",
                    identifier=identifier,
                    title=paper.title,
                    subtitle=", ".join((paper.authors or [])[:2]) or "unknown",
                    date=(paper.published_at or "")[:10],
                    final_score=float(entry.get("final_score", 0.0)),
                    goal_fit=float(entry.get("goal_fit", 0.0)),
                    depth_score=float(entry.get("depth_score", 0.0)),
                    complementarity_score=float(entry.get("complementarity_score", 0.0)),
                    rationale=str(entry.get("rationale", "")).strip(),
                    paper=paper,
                )
            )
        elif kind == "video":
            video = video_by_id.get(identifier)
            if not video:
                continue
            ranked.append(
                RankedDiscoverItem(
                    kind="video",
                    identifier=identifier,
                    title=video.title,
                    subtitle=video.channel_name or "unknown",
                    date=_format_date(video.upload_date or ""),
                    final_score=float(entry.get("final_score", 0.0)),
                    goal_fit=float(entry.get("goal_fit", 0.0)),
                    depth_score=float(entry.get("depth_score", 0.0)),
                    complementarity_score=float(entry.get("complementarity_score", 0.0)),
                    rationale=str(entry.get("rationale", "")).strip(),
                    video=video,
                )
            )
        elif kind == "site":
            seed = site_by_id.get(identifier)
            if not seed:
                continue
            ranked.append(
                RankedDiscoverItem(
                    kind="site",
                    identifier=identifier,
                    title=_site_candidate_title(seed),
                    subtitle=seed.resolved_site_name() or "website",
                    date="-",
                    final_score=float(entry.get("final_score", 0.0)),
                    goal_fit=float(entry.get("goal_fit", 0.0)),
                    depth_score=float(entry.get("depth_score", 0.0)),
                    complementarity_score=float(entry.get("complementarity_score", 0.0)),
                    rationale=str(entry.get("rationale", "")).strip(),
                    site_seed=seed,
                )
            )
    return sorted(ranked, key=lambda x: x.final_score, reverse=True)


def display_ranked_discover(items: list[RankedDiscoverItem], title: str) -> None:
    table = Table(title=title, box=box.SIMPLE_HEAVY)
    table.add_column("#", justify="right")
    table.add_column("Type")
    table.add_column("Title", overflow="fold")
    table.add_column("Source", overflow="fold")
    table.add_column("Date")
    table.add_column("Score", justify="right")
    table.add_column("Why", overflow="fold")
    for idx, item in enumerate(items, 1):
        table.add_row(
            str(idx),
            item.kind,
            item.title,
            item.subtitle,
            item.date or "-",
            f"{item.final_score:.2f}",
            item.rationale or "-",
        )
    console.print(table)
