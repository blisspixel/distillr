# pyright: strict
"""Discover command helpers for the Distill CLI."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, cast
from urllib.parse import urlparse

from rich import box
from rich.table import Table

from distill._console import console
from distill.config import DistillConfig
from distill.ingestors.papers.arxiv import PaperRecord
from distill.ingestors.sites.scraper import SiteSeed
from distill.ingestors.youtube.discovery import VideoInfo
from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
from distill.pipeline.costs import (
    CostCalibration,
    CostEstimate,
    CostTracker,
    TokenUsage,
    estimate_discover_items,
)
from distill.prompts.discover import discover_query_generation_prompt, discover_rerank_prompt

# Constants duplicated from commands._helpers to avoid upward dependency.
SHORTS_THRESHOLD = 180
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
        return date_str
    return date_str


__all__ = [
    "RankedDiscoverItem",
    "SizingOption",
    "VideoContentStats",
    "build_sizing_options",
    "discover_fetch_videos",
    "discover_generate_queries",
    "discover_rerank",
    "display_ranked_discover",
    "filter_ingested_candidates",
    "format_video_content_stats",
    "summarize_video_content",
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


@dataclass(frozen=True)
class VideoContentStats:
    total: int
    full_videos: int
    shorts: int
    known_duration_seconds: int
    unknown_duration_count: int


type QueryDeduper = Callable[[list[str]], list[str]]
type VideoDeduper = Callable[[list[VideoInfo]], list[VideoInfo]]


class VideoSearcher(Protocol):
    def __call__(
        self, query_or_url: str, days: int = 60, limit: int = 20, hours: int | None = None
    ) -> list[VideoInfo]: ...


class VideoEnricher(Protocol):
    def __call__(
        self, videos: list[VideoInfo], max_videos: int | None = None
    ) -> list[VideoInfo]: ...


class RecentVideoFilter(Protocol):
    def __call__(
        self, videos: list[VideoInfo], days: int, hours: int | None = None
    ) -> list[VideoInfo]: ...


def _object_dict(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return cast("dict[str, object]", value)
    return None


def _object_list(value: object) -> list[object]:
    if isinstance(value, list):
        return cast("list[object]", value)
    return []


def _string_list(value: object) -> list[str]:
    return [item for item in _object_list(value) if isinstance(item, str)]


def _row_string(row: dict[str, object], key: str) -> str:
    return str(row.get(key, "")).strip()


def _row_float(row: dict[str, object], key: str) -> float:
    value = row.get(key, 0.0)
    if isinstance(value, int | float | str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def summarize_video_content(videos: list[VideoInfo]) -> VideoContentStats:
    """Summarize free YouTube metadata for preview and approval output."""
    shorts = 0
    known_duration_seconds = 0
    unknown_duration_count = 0
    for video in videos:
        duration = getattr(video, "duration", 0) or 0
        try:
            seconds = int(duration)
        except (TypeError, ValueError):
            seconds = 0
        if seconds > 0:
            known_duration_seconds += seconds
            if seconds <= SHORTS_THRESHOLD:
                shorts += 1
        else:
            unknown_duration_count += 1
    total = len(videos)
    return VideoContentStats(
        total=total,
        full_videos=total - shorts,
        shorts=shorts,
        known_duration_seconds=known_duration_seconds,
        unknown_duration_count=unknown_duration_count,
    )


def format_video_content_stats(stats: VideoContentStats) -> str:
    """Format video candidate counts plus known watch time for console output."""
    if stats.total <= 0:
        return "0 videos"
    count_parts: list[str] = []
    if stats.full_videos:
        count_parts.append(_plural(stats.full_videos, "video", "videos"))
    if stats.shorts:
        count_parts.append(_plural(stats.shorts, "Short", "Shorts"))
    counts = " + ".join(count_parts) if count_parts else _plural(stats.total, "video", "videos")
    if stats.known_duration_seconds <= 0:
        return f"{counts}, duration unknown"
    duration = _format_approx_duration(stats.known_duration_seconds)
    qualifier = "known content" if stats.unknown_duration_count else "content"
    text = f"{counts}, ~{duration} of {qualifier}"
    if stats.unknown_duration_count:
        text += f"; {_plural(stats.unknown_duration_count, 'unknown duration')}"
    return text


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    word = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {word}"


def _format_approx_duration(seconds: int) -> str:
    minutes = max(0, round(seconds / 60))
    if minutes < 60:
        return f"{minutes}m"
    hours, remainder = divmod(minutes, 60)
    if remainder == 0:
        return f"{hours}h"
    return f"{hours}h {remainder}m"


def _site_candidate_title(seed: SiteSeed) -> str:
    label = seed.label.strip()
    if label:
        return label
    parsed = urlparse(seed.url)
    host = parsed.netloc.removeprefix("www.") or seed.resolved_site_name()
    path = (parsed.path or "/").rstrip("/") or "/"
    return f"{host}{path}"


def _site_candidate_subtitle(seed: SiteSeed) -> str:
    parts = [seed.resolved_site_name() or "website"]
    if seed.section_label:
        parts.append(f"section: {seed.section_label}")
    if seed.source_hint:
        parts.append(seed.source_hint)
    parts.append(seed.url)
    return " | ".join(part for part in parts if part)


def _site_candidate_description(seed: SiteSeed) -> str:
    parts = [f"URL: {seed.url}"]
    if seed.section_label:
        parts.append(f"section: {seed.section_label}")
    if seed.source_hint:
        parts.append(f"source: {seed.source_hint}")
    if seed.freshness_hint:
        parts.append(f"freshness: {seed.freshness_hint}")
    label = seed.label.strip()
    if label:
        parts.insert(0, label)
    else:
        parts.insert(0, "Curated website seed")
    return " | ".join(parts)


def _site_candidate_date(seed: SiteSeed) -> str:
    return seed.freshness_hint or "-"


def discover_generate_queries(
    goal: str,
    config: DistillConfig,
    tracker: CostTracker | None,
    *,
    paper_count: int,
    video_count: int,
    dedupe_query_strings: QueryDeduper,
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
        rc,
        workload_tag="rerank",
        prompt=prompt,
        max_tokens=768,
        call_type="discover_plan",
        temperature=0.0,  # deterministic queries so re-previews search the same pool
        usage_tracker=tracker,
    )
    if tracker:
        tracker.record(TokenUsage.from_response(response, call_type="discover_plan"))
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

    data: object = extract_json(text)
    if data is None:
        logger.warning("Failed to parse discover query generation response as JSON")
        return [], []
    data_obj = _object_dict(data)
    paper_qs = dedupe_query_strings(
        _string_list(data_obj.get("paper_queries", [])) if data_obj is not None else []
    )
    video_qs = dedupe_query_strings(
        _string_list(data_obj.get("video_queries", [])) if data_obj is not None else []
    )
    # Treat model-produced arrays as proposals. The deterministic caller count
    # is authoritative for both disabled and enabled source types.
    paper_qs = paper_qs[: max(0, paper_count)]
    video_qs = video_qs[: max(0, video_count)]
    return paper_qs, video_qs


def discover_fetch_videos(
    queries: list[str],
    effective_days: int,
    candidate_cap: int,
    shorts: bool,
    *,
    search_youtube_results: VideoSearcher,
    dedupe_candidates: VideoDeduper,
    enrich_videos: VideoEnricher,
    filter_recent_candidates: RecentVideoFilter,
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


def filter_ingested_candidates(
    papers: list[PaperRecord],
    videos: list[VideoInfo],
    *,
    ingested: frozenset[str],
) -> tuple[list[PaperRecord], list[VideoInfo], int]:
    """Drop searched candidates whose identity is already in the topic's corpus.

    Returns the kept papers, kept videos, and how many candidates were
    excluded. Papers match on ``paper_id`` raw or version-stripped (a v1
    ingest still blocks the v2 search hit); videos match on ``video_id``
    exactly. Curated site seeds are deliberately *not* filtered -- they are a
    user-provided signal of intent, and the site pipeline already reuses
    unchanged page insights. Pure: no IO.
    """
    if not ingested:
        return papers, videos, 0
    from distill.library.ingested import normalize_arxiv_id

    kept_papers = [
        p
        for p in papers
        if p.paper_id not in ingested and normalize_arxiv_id(p.paper_id) not in ingested
    ]
    kept_videos = [v for v in videos if v.video_id not in ingested]
    excluded = (len(papers) - len(kept_papers)) + (len(videos) - len(kept_videos))
    return kept_papers, kept_videos, excluded


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
                "subtitle": _site_candidate_subtitle(seed),
                "date": _site_candidate_date(seed),
                "description": _site_candidate_description(seed),
            }
        )
    if not candidates:
        return []

    rc = RouterConfig()
    prompt = discover_rerank_prompt(goal, candidates)
    response = llm_call(
        rc,
        workload_tag="rerank",
        prompt=prompt,
        max_tokens=8192,
        call_type="discover_rerank",
        temperature=0.0,  # deterministic rerank so the previewed order is reproducible
        usage_tracker=tracker,
    )
    if tracker:
        tracker.record(TokenUsage.from_response(response, call_type="discover_rerank"))
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

    data: object = extract_json(text)
    if data is None:
        logger.warning("Failed to parse discover rerank response as JSON")
        return []
    data_obj = _object_dict(data)
    items = (
        _object_list(data_obj.get("ranked_items", []))
        if data_obj is not None
        else _object_list(data)
    )
    if not items:
        return []

    ranked: list[RankedDiscoverItem] = []
    for entry in items:
        # The LLM can return non-dict entries (e.g. [null] or bare strings);
        # skip them rather than crashing on entry.get.
        row = _object_dict(entry)
        if row is None:
            continue
        kind = _row_string(row, "kind")
        identifier = _row_string(row, "identifier")
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
                    final_score=_row_float(row, "final_score"),
                    goal_fit=_row_float(row, "goal_fit"),
                    depth_score=_row_float(row, "depth_score"),
                    complementarity_score=_row_float(row, "complementarity_score"),
                    rationale=_row_string(row, "rationale"),
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
                    final_score=_row_float(row, "final_score"),
                    goal_fit=_row_float(row, "goal_fit"),
                    depth_score=_row_float(row, "depth_score"),
                    complementarity_score=_row_float(row, "complementarity_score"),
                    rationale=_row_string(row, "rationale"),
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
                    subtitle=_site_candidate_subtitle(seed),
                    date=_site_candidate_date(seed),
                    final_score=_row_float(row, "final_score"),
                    goal_fit=_row_float(row, "goal_fit"),
                    depth_score=_row_float(row, "depth_score"),
                    complementarity_score=_row_float(row, "complementarity_score"),
                    rationale=_row_string(row, "rationale"),
                    site_seed=seed,
                )
            )
    # Curated site seeds are a user-provided signal of intent. The LLM rerank can
    # silently omit them from ranked_items -- e.g. when the goal is phrased around
    # one vendor, curated competitor seeds for a comparison get dropped entirely.
    # Re-attach any curated seed the rerank left out with a floor score so it
    # stays eligible for the per-source --site-limit slice instead of vanishing
    # without trace. The caller still caps the count via --site-limit.
    ranked_site_urls = {r.identifier for r in ranked if r.kind == "site"}
    for seed in sites:
        if seed.url in ranked_site_urls:
            continue
        ranked.append(
            RankedDiscoverItem(
                kind="site",
                identifier=seed.url,
                title=_site_candidate_title(seed),
                subtitle=_site_candidate_subtitle(seed),
                date=_site_candidate_date(seed),
                final_score=0.4,
                goal_fit=0.0,
                depth_score=0.0,
                complementarity_score=0.0,
                rationale="Curated seed retained (omitted by rerank; user-provided).",
                site_seed=seed,
            )
        )
    return sorted(ranked, key=lambda x: x.final_score, reverse=True)


# Below this console width the 7-column table degrades into mid-word folds
# ("fact-checkin g numerical" -- the dogfooded 2026-06-11 finding), exactly in
# the view a spend-approval decision reads. Use a stacked per-row layout there.
STACKED_LAYOUT_WIDTH = 110


def display_ranked_discover(
    items: list[RankedDiscoverItem], title: str, *, console_width: int | None = None
) -> None:
    """Render the goal-ranked shortlist, adapting the layout to console width.

    Wide consoles get the familiar table. Narrow consoles get a stacked
    per-item list whose long fields (title, rationale) wrap at word
    boundaries across the full width instead of character-folding inside
    starved table columns. ``console_width`` overrides detection for tests.
    """
    from rich.markup import escape

    width = console_width if console_width is not None else console.size.width
    if width < STACKED_LAYOUT_WIDTH:
        console.print(f"[bold]{escape(title)}[/bold]\n")
        for idx, item in enumerate(items, 1):
            # escape(): titles/rationales are untrusted-derived text; a stray
            # ``[...]`` must render literally, not parse as rich markup.
            console.print(
                f"  {idx}. \\[{item.kind}] [bold]{escape(item.title)}[/bold] "
                f"({item.final_score:.2f})"
            )
            meta = " | ".join(part for part in (item.subtitle, item.date) if part and part != "-")
            if meta:
                console.print(f"     [dim]{escape(meta)}[/dim]")
            if item.rationale:
                console.print(f"     [dim]{escape(item.rationale)}[/dim]")
        console.print()
        return

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


# ---- discovery-loop UX: rigor + score-cliff sizing -------------------------

# Minimum rerank final_score to keep, per rigor level. ``--rigor strict`` keeps
# only high-fit candidates; ``loose`` keeps almost everything goal-relevant.
#
# The thresholds are calibrated *per command*, not shared, because the three
# rerank prompts score on different criteria (see docs/architecture.md, "Rigor
# calibration"). ``discover`` gates on cross-source ``goal_fit`` and is the
# strictest; the single-source ``papers`` and ``latest`` rerankers optimize
# topical relevance and tend to score on-topic items a little higher, so their
# bars sit a notch lower to avoid discarding strong picks (the documented case:
# discover kept 0/33 videos on a topic where ``latest`` surfaced 5 strong ones).
RIGOR_THRESHOLDS: dict[str, float] = {"strict": 0.7, "balanced": 0.5, "loose": 0.3}
PAPER_RIGOR_THRESHOLDS: dict[str, float] = {"strict": 0.65, "balanced": 0.45, "loose": 0.3}
VIDEO_RIGOR_THRESHOLDS: dict[str, float] = {"strict": 0.6, "balanced": 0.4, "loose": 0.25}
RIGOR_LEVELS: tuple[str, ...] = tuple(RIGOR_THRESHOLDS)
# papers/latest add "off" (the default there): keep the rerank's picks as before,
# filter only when the user explicitly asks for a bar.
RIGOR_LEVELS_WITH_OFF: tuple[str, ...] = (*RIGOR_LEVELS, "off")

_SOURCE_RIGOR_TABLES: dict[str, dict[str, float]] = {
    "discover": RIGOR_THRESHOLDS,
    "paper": PAPER_RIGOR_THRESHOLDS,
    "video": VIDEO_RIGOR_THRESHOLDS,
}


def rigor_threshold(rigor: str) -> float:
    """Return the minimum ``final_score`` for a discover rigor level (default balanced)."""
    return RIGOR_THRESHOLDS.get(rigor, RIGOR_THRESHOLDS["balanced"])


def source_rigor_threshold(source: str, rigor: str) -> float:
    """Return the per-source minimum ``final_score`` for a rigor level.

    ``source`` is ``"discover"``, ``"paper"``, or ``"video"``; unknown sources
    fall back to the discover table. ``balanced`` is the per-table default.
    """
    table = _SOURCE_RIGOR_TABLES.get(source, RIGOR_THRESHOLDS)
    return table.get(rigor, table["balanced"])


def detect_score_cliff(scores: list[float], *, min_drop: float = 0.08) -> int:
    """Return how many top items sit above the largest rerank-score "cliff".

    Given final scores, find the biggest gap between consecutive scores (sorted
    high to low) and return the count of items before it -- the "obviously
    excellent" set. A drop must exceed ``min_drop`` to count as a cliff;
    otherwise (a flat distribution) every item is returned. Pure and
    order-independent (it sorts internally).
    """
    ordered = sorted(scores, reverse=True)
    if len(ordered) < 2:
        return len(ordered)
    biggest_drop = 0.0
    cliff_at = len(ordered)
    for i in range(1, len(ordered)):
        drop = ordered[i - 1] - ordered[i]
        if drop > biggest_drop:
            biggest_drop = drop
            cliff_at = i
    return cliff_at if biggest_drop >= min_drop else len(ordered)


@dataclass(frozen=True)
class SizingOption:
    """One "how much should I ingest?" choice with its per-source spend."""

    label: str
    basis: str  # human description of the cut, e.g. "score >= 0.50"
    items: list[RankedDiscoverItem]
    papers: int
    videos: int
    sites: int
    estimate: CostEstimate


def _cap_by_source(
    items: list[RankedDiscoverItem], *, paper_limit: int, video_limit: int, site_limit: int
) -> tuple[list[RankedDiscoverItem], list[RankedDiscoverItem], list[RankedDiscoverItem]]:
    """Split items by kind and apply each source's per-run cap (best-first order)."""
    papers = [r for r in items if r.kind == "paper"][:paper_limit]
    videos = [r for r in items if r.kind == "video"][:video_limit]
    sites = [r for r in items if r.kind == "site"][:site_limit]
    return papers, videos, sites


def build_sizing_options(
    ranked: list[RankedDiscoverItem],
    *,
    paper_limit: int,
    video_limit: int,
    site_limit: int,
    calibration: CostCalibration | None = None,
    router_config: RouterConfig | None = None,
) -> list[SizingOption]:
    """Derive nested "excellent / good / everything" ingest sizes from a reranked set.

    Each option applies a quality cut (the score cliff, then the balanced and loose
    rigor thresholds), caps by the per-source limits, and attaches a metadata-aware
    spend estimate. Options that resolve to the same item set are de-duplicated, and
    the result is sorted smallest-first so the menu reads as a ladder. Pure: no IO.
    """
    ordered = sorted(ranked, key=lambda r: r.final_score, reverse=True)
    cliff = detect_score_cliff([r.final_score for r in ordered])
    cuts = [
        ("Excellent", f"top {cliff} above the score cliff", ordered[:cliff]),
        (
            "Including good",
            f"score >= {RIGOR_THRESHOLDS['balanced']:.2f}",
            [r for r in ordered if r.final_score >= RIGOR_THRESHOLDS["balanced"]],
        ),
        (
            "Everything worthwhile",
            f"score >= {RIGOR_THRESHOLDS['loose']:.2f}",
            [r for r in ordered if r.final_score >= RIGOR_THRESHOLDS["loose"]],
        ),
    ]
    options: list[SizingOption] = []
    seen: set[tuple[str, ...]] = set()
    for label, basis, subset in cuts:
        papers, videos, sites = _cap_by_source(
            subset, paper_limit=paper_limit, video_limit=video_limit, site_limit=site_limit
        )
        selected = papers + videos + sites
        if not selected:
            continue
        key = tuple(sorted(it.identifier for it in selected))
        if key in seen:
            continue
        seen.add(key)
        estimate = estimate_discover_items(
            papers=len(papers),
            video_durations=[getattr(v.video, "duration", None) for v in videos],
            sites=len(sites),
            calibration=calibration,
            router_config=router_config,
        )
        options.append(
            SizingOption(
                label=label,
                basis=basis,
                items=selected,
                papers=len(papers),
                videos=len(videos),
                sites=len(sites),
                estimate=estimate,
            )
        )
    options.sort(key=lambda o: len(o.items))
    return options
