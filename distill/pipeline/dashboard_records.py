"""Typed records for the shared dashboard data boundary."""

# pyright: strict

from __future__ import annotations

from datetime import datetime
from typing import NotRequired, TypedDict, cast

from distill.library import Library, TopicWatchEntry, WatchEntry

__all__ = [
    "CostRollup",
    "CostRun",
    "DashboardSnapshot",
    "JsonObject",
    "RecentArtifact",
    "SiteManifest",
    "SiteManifestSection",
    "SiteSectionState",
    "TopicChange",
    "TopicChangeCounts",
    "TopicChangeHistoryRecord",
    "json_object",
    "object_list",
    "site_manifest_from_json",
]

JsonObject = dict[str, object]
CostRun = JsonObject
RecentArtifact = tuple[datetime, str, str]
TopicChange = tuple[str, str]
CostRollup = tuple[str, float, int]


class TopicChangeCounts(TypedDict):
    videos: int
    pages: int
    papers: int
    outputs: int


class TopicChangeHistoryRecord(TypedDict):
    generated_at: datetime
    summary: str
    counts: TopicChangeCounts


class SiteManifestSection(TypedDict):
    section: str
    page_count: int
    urls: list[str]
    page_types: list[str]
    last_crawled_at: str


class SiteManifest(TypedDict):
    sections: list[SiteManifestSection]


class SiteSectionState(TypedDict):
    section: str
    page_count: int
    urls: list[str]
    page_types: list[str]
    last_crawled_at: NotRequired[str]


class DashboardSnapshot(TypedDict):
    lib: Library
    topics: list[str]
    watchlist: list[WatchEntry]
    topic_watchlist: list[TopicWatchEntry]
    total_channels: int
    total_videos: int
    full_videos: int
    scan_videos: int
    site_count: int
    page_count: int
    paper_count: int
    report_count: int
    brief_count: int
    synthesis_count: int
    all_cost_entries: list[CostRun]
    recent_runs: list[CostRun]
    recent_spend: float
    latest_results: JsonObject
    latest_issues: list[object]
    recent_artifacts: list[RecentArtifact]
    topic_changes: list[TopicChange]
    topic_trends: dict[str, str | None]
    stale_topic_watches: list[str]
    corpus_health_warnings: list[str]
    next_sweep_cost: float
    due_topic_watches: int
    topic_spend_rollups: list[CostRollup]
    source_spend_rollups: list[CostRollup]
    budget_messages: list[str]


def json_object(value: object) -> JsonObject:
    """Return a JSON-object mapping, normalizing non-objects to an empty dict."""
    return cast(JsonObject, value) if isinstance(value, dict) else {}


def object_list(value: object) -> list[object]:
    """Return a JSON array, normalizing non-lists to an empty list."""
    return list(cast(list[object], value)) if isinstance(value, list) else []


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in cast(list[object], value) if item is not None]


def _int_value(value: object) -> int:
    if isinstance(value, (int, float, str)):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def site_manifest_from_json(value: object) -> SiteManifest:
    """Parse the dashboard subset of ``site.json`` into typed section rows."""
    raw = json_object(value)
    sections: list[SiteManifestSection] = []
    raw_sections = raw.get("sections")
    if isinstance(raw_sections, list):
        for item in cast(list[object], raw_sections):
            section = json_object(item)
            sections.append(
                {
                    "section": str(section.get("section") or "unknown"),
                    "page_count": _int_value(section.get("page_count")),
                    "urls": _string_list(section.get("urls")),
                    "page_types": _string_list(section.get("page_types")),
                    "last_crawled_at": str(section.get("last_crawled_at") or ""),
                }
            )
    return {"sections": sections}
