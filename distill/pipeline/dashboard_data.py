# pyright: strict
"""Shared dashboard data functions used by both CLI and web UI."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

from distill.config import DistillConfig
from distill.ingestors.sites.scraper import SitePage, site_section_key
from distill.library import Library, TopicWatchEntry
from distill.library.freshness import collect_synthesis_freshness
from distill.library.paths import artifact_exists, find_artifact
from distill.pipeline.audit_transcripts import collect_thin_video_transcripts
from distill.pipeline.costs import (
    cost_anomaly_warnings,
    estimate_stage_cost,
    report_deep_research_estimate,
)
from distill.pipeline.dashboard_records import (
    CostRollup,
    CostRun,
    DashboardSnapshot,
    JsonObject,
    RecentArtifact,
    SiteManifest,
    SiteSectionState,
    TopicChange,
    TopicChangeHistoryRecord,
    json_object,
    object_list,
    site_manifest_from_json,
)


def duration_str(seconds: object) -> str:
    """Format seconds to human readable duration."""
    if seconds is None or not isinstance(seconds, (int, float)):
        return "?"
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def strip_frontmatter(content: str) -> str:
    """Strip YAML frontmatter from markdown content."""
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return content


def read_json_dict(path: Path) -> JsonObject:
    """Read a JSON-object file, returning ``{}`` on missing/corrupt/non-object content.

    Dashboard readers consume best-effort local ``metadata.json`` / ``*.json``
    files that can be truncated or hand-edited. A valid-JSON-but-non-object
    payload (a list or scalar) would otherwise crash a later ``.get(...)`` and
    take the whole dashboard down, so it is normalized to an empty mapping here.
    """
    try:
        data: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return json_object(data)


__all__ = [
    "build_site_section_state",
    "collect_corpus_health_warnings",
    "collect_recent_artifacts",
    "collect_stale_topic_watches",
    "collect_topic_changes",
    "count_paper_corpus",
    "count_site_corpus",
    "count_topic_outputs",
    "dashboard_snapshot",
    "entry_source_type",
    "estimate_topic_watch_cost",
    "estimated_topic_watch_sweep",
    "format_run_timestamp",
    "load_all_cost_runs",
    "load_latest_run_payload",
    "load_recent_cost_runs",
    "load_site_manifest",
    "load_topic_change_history",
    "parse_run_datetime",
    "source_cost_rollups",
    "stale_synthesis_warnings",
    "sum_recent_cost",
    "topic_cost_rollups",
    "topic_recent_costs",
    "topic_spend_last_days",
    "topic_trend_label",
    "topic_watch_budget_messages",
]

# ── Cost log helpers ────────────────────────────────────────────────


def load_recent_cost_runs(log_file: Path, limit: int = 5) -> list[CostRun]:
    if not log_file.exists():
        return []
    entries: list[CostRun] = []
    try:
        for line in log_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry: object = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Only dict rows are usable; a valid-JSON-but-non-object line would
            # crash consumers like ``sum_recent_cost`` (``entry.get(...)``) and
            # take the whole dashboard down on one corrupt cost_log.jsonl line.
            entry_row = json_object(entry)
            if isinstance(entry, dict):
                entries.append(entry_row)
    except OSError:
        return []
    return entries[-limit:]


def load_all_cost_runs(log_file: Path) -> list[CostRun]:
    return load_recent_cost_runs(log_file, limit=10000)


def load_latest_run_payload(log_dir: Path) -> JsonObject:
    latest = log_dir / "latest_run.json"
    if not latest.exists():
        return {}
    return read_json_dict(latest)


def _float_value(value: object, default: float = 0.0) -> float:
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _int_value(value: object, default: int = 0) -> int:
    if isinstance(value, (int, float, str)):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _invalid_cost_value(value: object) -> bool:
    return (
        _float_value(value) == 0.0
        and value is not None
        and value
        not in {
            0,
            "",
            "0",
            "0.0",
        }
    )


def sum_recent_cost(entries: Sequence[CostRun]) -> float:
    total = 0.0
    for entry in entries:
        total += _float_value(entry.get("actual_cost"))
    return total


# ── Timestamp helpers ───────────────────────────────────────────────


def format_run_timestamp(value: str) -> str:
    if not value:
        return "unknown"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime("%b %d %I:%M %p")
    except ValueError:
        return value


def parse_run_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except ValueError:
        return None


# ── Topic watch cost helpers ────────────────────────────────────────


def estimated_topic_watch_sweep(topic_watchlist: Sequence[TopicWatchEntry]) -> float:
    total = 0.0
    for entry in topic_watchlist:
        total += entry.limit * estimate_stage_cost("video_full")
        if entry.report:
            total += report_deep_research_estimate()
    return total


def estimate_topic_watch_cost(entry: TopicWatchEntry) -> float:
    total = entry.limit * estimate_stage_cost("video_full")
    if entry.report:
        total += report_deep_research_estimate()
    return total


def topic_spend_last_days(entries: Sequence[CostRun], topic: str, days: int = 30) -> float:
    cutoff = datetime.now() - timedelta(days=days)
    total = 0.0
    for entry in entries:
        metadata = json_object(entry.get("metadata"))
        if metadata.get("topic") != topic:
            continue
        ts = parse_run_datetime(str(entry.get("timestamp", "")))
        if ts is None or ts < cutoff:
            continue
        total += _float_value(entry.get("actual_cost"))
    return total


def topic_recent_costs(entries: Sequence[CostRun], topic: str, limit: int = 5) -> list[float]:
    values: list[tuple[datetime, float]] = []
    for entry in entries:
        metadata = json_object(entry.get("metadata"))
        if metadata.get("topic") != topic:
            continue
        ts = parse_run_datetime(str(entry.get("timestamp", "")))
        if ts is None:
            continue
        cost = _float_value(entry.get("actual_cost"))
        values.append((ts, cost))
    values.sort(key=lambda item: item[0], reverse=True)
    return [cost for _, cost in values[:limit]]


def topic_watch_budget_messages(
    entry: TopicWatchEntry, all_cost_entries: Sequence[CostRun]
) -> list[str]:
    messages: list[str] = []
    projected = estimate_topic_watch_cost(entry)
    if entry.max_run_cost and projected > entry.max_run_cost:
        messages.append(
            f"{entry.name} projected ${projected:.2f} exceeds max-run budget ${entry.max_run_cost:.2f}"
        )
    if entry.monthly_budget:
        monthly_spend = topic_spend_last_days(all_cost_entries, entry.topic, days=30)
        if monthly_spend + projected > entry.monthly_budget:
            messages.append(
                f"{entry.name} projected monthly spend ${monthly_spend + projected:.2f} "
                f"exceeds monthly budget ${entry.monthly_budget:.2f}"
            )
    recent_costs = topic_recent_costs(all_cost_entries, entry.topic, limit=4)
    if len(recent_costs) >= 2:
        baseline = sum(recent_costs[1:]) / max(len(recent_costs) - 1, 1)
        latest = recent_costs[0]
        if baseline > 0 and latest >= baseline * 2.5:
            messages.append(
                f"{entry.topic} spend spike: latest ${latest:.2f} vs recent baseline ${baseline:.2f}"
            )
    return messages


# ── Cost rollup helpers ─────────────────────────────────────────────


def entry_source_type(entry: CostRun) -> str:
    metadata = json_object(entry.get("metadata"))
    source_type = metadata.get("source_type")
    if source_type:
        return str(source_type)
    command = str(entry.get("command", ""))
    if command in {"site", "site-batch"}:
        return "website"
    if command == "report":
        return "report"
    return "youtube"


def topic_cost_rollups(
    entries: Sequence[CostRun], days: int = 30, limit: int = 5
) -> list[CostRollup]:
    cutoff = datetime.now() - timedelta(days=days)
    rollups: dict[str, tuple[float, int]] = {}
    for entry in entries:
        ts = parse_run_datetime(str(entry.get("timestamp", "")))
        if ts is None or ts < cutoff:
            continue
        metadata = json_object(entry.get("metadata"))
        topic = str(metadata.get("topic") or "").strip()
        if not topic:
            continue
        cost = _float_value(entry.get("actual_cost"))
        if _invalid_cost_value(entry.get("actual_cost")):
            continue
        current_cost, current_runs = rollups.get(topic, (0.0, 0))
        rollups[topic] = (current_cost + cost, current_runs + 1)
    items: list[CostRollup] = [(topic, cost, runs) for topic, (cost, runs) in rollups.items()]
    items.sort(key=lambda item: item[1], reverse=True)
    return items[:limit]


def source_cost_rollups(entries: Sequence[CostRun], days: int = 30) -> list[CostRollup]:
    cutoff = datetime.now() - timedelta(days=days)
    rollups: dict[str, tuple[float, int]] = {}
    for entry in entries:
        ts = parse_run_datetime(str(entry.get("timestamp", "")))
        if ts is None or ts < cutoff:
            continue
        source_type = entry_source_type(entry)
        cost = _float_value(entry.get("actual_cost"))
        if _invalid_cost_value(entry.get("actual_cost")):
            continue
        current_cost, current_runs = rollups.get(source_type, (0.0, 0))
        rollups[source_type] = (current_cost + cost, current_runs + 1)
    items: list[CostRollup] = [(source, cost, runs) for source, (cost, runs) in rollups.items()]
    items.sort(key=lambda item: item[1], reverse=True)
    return items


# ── Corpus counting ─────────────────────────────────────────────────


def count_site_corpus(config: DistillConfig, topics: list[str]) -> tuple[int, int]:
    site_count = 0
    page_count = 0
    for topic in topics:
        sites_dir = config.sites_dir(topic)
        if not sites_dir.exists():
            continue
        for site_dir in sites_dir.iterdir():
            if not site_dir.is_dir():
                continue
            site_count += 1
            pages_dir = site_dir / "pages"
            if not pages_dir.exists():
                continue
            for page_dir in pages_dir.iterdir():
                if page_dir.is_dir() and artifact_exists(page_dir, "content"):
                    page_count += 1
    return site_count, page_count


def count_paper_corpus(config: DistillConfig, topics: list[str]) -> int:
    total = 0
    for topic in topics:
        papers_dir = config.papers_dir(topic)
        if not papers_dir.exists():
            continue
        for paper_dir in papers_dir.iterdir():
            if paper_dir.is_dir() and artifact_exists(paper_dir, "paper"):
                total += 1
    return total


def count_topic_outputs(config: DistillConfig, topics: list[str]) -> tuple[int, int, int]:
    report_count = 0
    brief_count = 0
    synthesis_count = 0
    for topic in topics:
        topic_dir = config.topic_dir(topic)
        if artifact_exists(topic_dir, "report", identity=topic):
            report_count += 1
        if artifact_exists(topic_dir, "brief", identity=topic):
            brief_count += 1
        if artifact_exists(topic_dir, "topic_synthesis", identity=topic):
            synthesis_count += 1
    return report_count, brief_count, synthesis_count


# ── Artifact + health helpers ───────────────────────────────────────


def collect_recent_artifacts(
    config: DistillConfig, topics: list[str], limit: int = 6
) -> list[RecentArtifact]:
    artifacts: list[RecentArtifact] = []
    for topic in topics:
        topic_dir = config.topic_dir(topic)
        candidates = [
            (
                find_artifact(topic_dir, "topic_synthesis", identity=topic),
                "topic synthesis",
                topic,
            ),
            (
                find_artifact(topic_dir, "corpus_synthesis", identity=topic),
                "corpus synthesis",
                topic,
            ),
            (
                find_artifact(topic_dir, "paper_synthesis", identity=topic),
                "paper synthesis",
                topic,
            ),
            (find_artifact(topic_dir, "report", identity=topic), "report", topic),
            (find_artifact(topic_dir, "brief", identity=topic), "brief", topic),
        ]
        sites_dir = config.sites_dir(topic)
        if sites_dir.exists():
            for site_dir in sites_dir.iterdir():
                if site_dir.is_dir():
                    candidates.append(
                        (
                            find_artifact(
                                site_dir,
                                "site_synthesis",
                                identity=f"{topic}_{site_dir.name}",
                            ),
                            "site synthesis",
                            f"{topic} / {site_dir.name}",
                        )
                    )
                    candidates.append(
                        (
                            find_artifact(
                                site_dir,
                                "site_update",
                                identity=f"{topic}_{site_dir.name}",
                            ),
                            "site update",
                            f"{topic} / {site_dir.name}",
                        )
                    )
        for path_obj, kind, label in candidates:
            if not path_obj.exists():
                continue
            try:
                mtime = datetime.fromtimestamp(path_obj.stat().st_mtime)
            except OSError:
                continue
            artifacts.append((mtime, kind, label))
    artifacts.sort(key=lambda x: x[0], reverse=True)
    return artifacts[:limit]


def collect_stale_topic_watches(topic_watchlist: Sequence[TopicWatchEntry]) -> list[str]:
    stale: list[str] = []
    now = datetime.now()
    for entry in topic_watchlist:
        if not entry.last_run_at:
            stale.append(f"{entry.name} has never run")
            continue
        last = parse_run_datetime(entry.last_run_at)
        if last is None:
            stale.append(f"{entry.name} has invalid last-run state")
            continue
        max_age_days = 2 if entry.cadence == "daily" else 8
        if (now - last).days >= max_age_days:
            stale.append(f"{entry.name} is stale for its {entry.cadence} cadence")
    return stale


def collect_corpus_health_warnings(  # noqa: C901 — legacy, will refactor
    config: DistillConfig,
    lib: Library,
    topics: list[str],
    *,
    limit: int = 8,
    include_thin_transcripts: bool = True,
) -> list[str]:
    warnings: list[str] = []
    stale_cutoff = datetime.now() - timedelta(days=90)
    site_section_cutoff = datetime.now() - timedelta(days=30)

    for topic in topics:
        topic_dir = config.topic_dir(topic)
        for label, path_obj in (
            (
                "topic synthesis",
                find_artifact(topic_dir, "topic_synthesis", identity=topic),
            ),
            (
                "paper synthesis",
                find_artifact(topic_dir, "paper_synthesis", identity=topic),
            ),
            (
                "corpus synthesis",
                find_artifact(topic_dir, "corpus_synthesis", identity=topic),
            ),
            ("report", find_artifact(topic_dir, "report", identity=topic)),
        ):
            if not path_obj.exists():
                continue
            try:
                mtime = datetime.fromtimestamp(path_obj.stat().st_mtime)
            except OSError:
                continue
            if mtime < stale_cutoff:
                warnings.append(f"{topic} {label} is stale ({(datetime.now() - mtime).days}d old)")
                if len(warnings) >= limit:
                    return warnings

        for channel in lib.get_channels(topic):
            videos_dir = config.channel_dir(topic, channel.name) / "videos"
            if not videos_dir.exists():
                continue
            for video_dir in videos_dir.iterdir():
                if not video_dir.is_dir():
                    continue
                meta_path = video_dir / "metadata.json"
                metadata = read_json_dict(meta_path) if meta_path.exists() else {}
                title = str(metadata.get("title") or video_dir.name)

                insights_path = find_artifact(video_dir, "insights")
                if insights_path.exists():
                    try:
                        insight_len = len(
                            strip_frontmatter(insights_path.read_text(encoding="utf-8")).strip()
                        )
                    except OSError:
                        insight_len = 0
                    if insight_len and insight_len < 250:
                        warnings.append(
                            f"{topic} / {channel.name}: {title} insights look thin "
                            f"({insight_len} chars)"
                        )
                        if len(warnings) >= limit:
                            return warnings

        if include_thin_transcripts:
            for item in collect_thin_video_transcripts(topic_dir):
                warnings.append(
                    f"{topic} / {item.channel}: {item.title} transcript looks thin "
                    f"({item.transcript_chars} chars for {duration_str(item.duration_seconds)})"
                )
                if len(warnings) >= limit:
                    return warnings

        sites_dir = config.sites_dir(topic)
        if sites_dir.exists():
            for site_dir in sites_dir.iterdir():
                if not site_dir.is_dir():
                    continue
                site_manifest = _load_site_manifest(site_dir / "site.json")
                for section in site_manifest.get("sections", []):
                    last_crawled_at = parse_run_datetime(str(section.get("last_crawled_at", "")))
                    if last_crawled_at and last_crawled_at < site_section_cutoff:
                        warnings.append(
                            f"{topic} / {site_dir.name}: section "
                            f"{section.get('section', 'unknown')} is stale "
                            f"({(datetime.now() - last_crawled_at).days}d old)"
                        )
                        if len(warnings) >= limit:
                            return warnings
                pages_dir = site_dir / "pages"
                if not pages_dir.exists():
                    continue
                for page_dir in pages_dir.iterdir():
                    if not page_dir.is_dir():
                        continue
                    meta_path = page_dir / "metadata.json"
                    metadata = read_json_dict(meta_path) if meta_path.exists() else {}
                    title = str(metadata.get("title") or page_dir.name)
                    insights_path = find_artifact(page_dir, "insights")
                    if insights_path.exists():
                        try:
                            insight_len = len(
                                strip_frontmatter(insights_path.read_text(encoding="utf-8")).strip()
                            )
                        except OSError:
                            insight_len = 0
                        if insight_len and insight_len < 200:
                            warnings.append(
                                f"{topic} / {site_dir.name}: {title} page insights "
                                f"look thin ({insight_len} chars)"
                            )
                            if len(warnings) >= limit:
                                return warnings

        papers_dir = config.papers_dir(topic)
        if papers_dir.exists():
            for paper_dir in papers_dir.iterdir():
                if not paper_dir.is_dir():
                    continue
                meta_path = paper_dir / "metadata.json"
                metadata = read_json_dict(meta_path) if meta_path.exists() else {}
                title = str(metadata.get("title") or paper_dir.name)
                insights_path = find_artifact(paper_dir, "insights")
                if insights_path.exists():
                    try:
                        insight_len = len(
                            strip_frontmatter(insights_path.read_text(encoding="utf-8")).strip()
                        )
                    except OSError:
                        insight_len = 0
                    if insight_len and insight_len < 200:
                        warnings.append(
                            f"{topic}: {title} paper insights look thin ({insight_len} chars)"
                        )
                        if len(warnings) >= limit:
                            return warnings

    return warnings


def _topic_change_history_path(config: DistillConfig, topic: str) -> Path:
    return config.topic_dir(topic) / "change_history.jsonl"


def load_topic_change_history(config: DistillConfig, topic: str) -> list[TopicChangeHistoryRecord]:
    history_path = _topic_change_history_path(config, topic)
    if not history_path.exists():
        return []
    records: list[TopicChangeHistoryRecord] = []
    try:
        for line in history_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload: object = json.loads(line)
            except json.JSONDecodeError:
                continue
            row = json_object(payload)
            if not row:
                continue
            generated_at = parse_run_datetime(str(row.get("generated_at", "")))
            counts = json_object(row.get("counts"))
            if generated_at is None:
                continue
            records.append(
                {
                    "generated_at": generated_at,
                    "summary": str(row.get("summary", "") or ""),
                    "counts": {
                        "videos": _int_value(counts.get("videos")),
                        "pages": _int_value(counts.get("pages")),
                        "papers": _int_value(counts.get("papers")),
                        "outputs": _int_value(counts.get("outputs")),
                    },
                }
            )
    except OSError:
        return []
    records.sort(key=lambda item: item["generated_at"], reverse=True)
    return records


def topic_trend_label(config: DistillConfig, topic: str) -> str | None:
    records = load_topic_change_history(config, topic)
    if len(records) < 2:
        return None
    latest_counts = records[0]["counts"]
    previous_counts = records[1]["counts"]
    latest = (
        latest_counts["videos"]
        + latest_counts["pages"]
        + latest_counts["papers"]
        + latest_counts["outputs"]
    )
    previous = (
        previous_counts["videos"]
        + previous_counts["pages"]
        + previous_counts["papers"]
        + previous_counts["outputs"]
    )
    if latest > previous:
        return "trend: rising"
    if latest < previous:
        return "trend: cooling"
    return "trend: steady"


def collect_topic_changes(  # noqa: C901 — legacy, will refactor
    config: DistillConfig,
    lib: Library,
    topics: list[str],
    topic_watchlist: Sequence[TopicWatchEntry],
    limit: int = 6,
) -> list[TopicChange]:
    now = datetime.now()
    watch_baselines: dict[str, datetime | None] = {}
    for entry in topic_watchlist:
        parsed = parse_run_datetime(entry.last_run_at)
        current = watch_baselines.get(entry.topic)
        if current is None or (parsed is not None and parsed > current):
            watch_baselines[entry.topic] = parsed

    changes: list[tuple[datetime, str, str]] = []
    for topic in topics:
        baseline = watch_baselines.get(topic)
        if baseline is None:
            baseline = now - timedelta(days=7)

        new_videos = 0
        new_pages = 0
        refreshed_outputs: list[str] = []
        last_change = baseline

        for ch in lib.get_channels(topic):
            videos_dir = config.channel_dir(topic, ch.name) / "videos"
            if not videos_dir.exists():
                continue
            for video_dir in videos_dir.iterdir():
                insight_path = find_artifact(video_dir, "insights")
                if not video_dir.is_dir() or not insight_path.exists():
                    continue
                try:
                    mtime = datetime.fromtimestamp(insight_path.stat().st_mtime)
                except OSError:
                    continue
                if mtime > baseline:
                    new_videos += 1
                    last_change = max(last_change, mtime)

        sites_dir = config.sites_dir(topic)
        if sites_dir.exists():
            for site_dir in sites_dir.iterdir():
                if not site_dir.is_dir():
                    continue
                pages_dir = site_dir / "pages"
                if pages_dir.exists():
                    for page_dir in pages_dir.iterdir():
                        content_path = find_artifact(page_dir, "content")
                        if not page_dir.is_dir() or not content_path.exists():
                            continue
                        try:
                            mtime = datetime.fromtimestamp(content_path.stat().st_mtime)
                        except OSError:
                            continue
                        if mtime > baseline:
                            new_pages += 1
                            last_change = max(last_change, mtime)
                site_synth = find_artifact(
                    site_dir,
                    "site_synthesis",
                    identity=f"{topic}_{site_dir.name}",
                )
                if site_synth.exists():
                    try:
                        mtime = datetime.fromtimestamp(site_synth.stat().st_mtime)
                    except OSError:
                        mtime = None
                    if mtime and mtime > baseline:
                        refreshed_outputs.append("site synthesis")
                        last_change = max(last_change, mtime)

        topic_dir = config.topic_dir(topic)
        for label, path_obj in (
            ("synthesis", find_artifact(topic_dir, "topic_synthesis", identity=topic)),
            ("brief", find_artifact(topic_dir, "brief", identity=topic)),
            ("report", find_artifact(topic_dir, "report", identity=topic)),
        ):
            if not path_obj.exists():
                continue
            try:
                mtime = datetime.fromtimestamp(path_obj.stat().st_mtime)
            except OSError:
                continue
            if mtime > baseline:
                refreshed_outputs.append(label)
                last_change = max(last_change, mtime)

        if new_videos or new_pages or refreshed_outputs:
            parts: list[str] = []
            if new_videos:
                parts.append(f"+{new_videos} video{'s' if new_videos != 1 else ''}")
            if new_pages:
                parts.append(f"+{new_pages} page{'s' if new_pages != 1 else ''}")
            if refreshed_outputs:
                parts.append(", ".join(dict.fromkeys(refreshed_outputs)) + " refreshed")
            changes.append((last_change, topic, " / ".join(parts)))
        elif topic in watch_baselines:
            changes.append(
                (
                    baseline,
                    topic,
                    f"quiet since {format_run_timestamp(baseline.isoformat())}",
                )
            )

    changes.sort(key=lambda item: item[0], reverse=True)
    return [(topic, summary) for _, topic, summary in changes[:limit]]


# ── Site helpers ────────────────────────────────────────────────────


def load_site_manifest(path: Path) -> SiteManifest:
    """Load and parse a site manifest for command and dashboard callers."""
    return _load_site_manifest(path)


def _load_site_manifest(path: Path) -> SiteManifest:
    if not path.exists():
        return {"sections": []}
    return site_manifest_from_json(read_json_dict(path))


def build_site_section_state(pages: Sequence[SitePage]) -> list[SiteSectionState]:
    section_buckets: dict[str, list[SitePage]] = {}
    for page in pages:
        section = site_section_key(page.final_url or page.url)
        section_buckets.setdefault(section, []).append(page)

    section_state: list[SiteSectionState] = []
    for section, section_pages in sorted(section_buckets.items()):
        urls = sorted({page.final_url or page.url for page in section_pages})
        section_state.append(
            {
                "section": section,
                "page_count": len(section_pages),
                "urls": urls,
                "page_types": sorted({page.page_type for page in section_pages}),
            }
        )
    return section_state


def stale_synthesis_warnings(
    config: DistillConfig, topics: list[str], *, limit: int = 4
) -> list[str]:
    """Syntheses generated before sources that now sit under them.

    The source-relative complement to ``collect_corpus_health_warnings``'s
    90-day wall-clock check: a synthesis can be a week old and still stale if
    sources landed yesterday. Frontmatter-timestamped (mtime only as legacy
    fallback), so cloud-sync mtime rewrites cannot fake or mask staleness.
    """
    warnings: list[str] = []
    for topic in topics:
        freshness = collect_synthesis_freshness(config.topic_dir(topic), topic)
        for item in freshness.stale:
            row = json_object(item)
            warnings.append(
                f"{topic} {row.get('synthesis', 'synthesis')} predates "
                f"{_int_value(row.get('behind'))} newer source(s) by "
                f"{_int_value(row.get('gap_days'))}d -- regenerate with `distill corpus {topic}`"
            )
            if len(warnings) >= limit:
                return warnings
    return warnings


# ── Main snapshot ───────────────────────────────────────────────────


def dashboard_snapshot(config: DistillConfig) -> DashboardSnapshot:
    """Collect all dashboard data into a plain dict."""
    lib = Library(config)
    topics = lib.get_topics()
    watchlist = lib.get_watchlist()
    topic_watchlist = lib.get_topic_watchlist()

    total_channels = sum(len(lib.get_channels(t)) for t in topics)
    total_videos = 0
    full_videos = 0
    scan_videos = 0
    for topic in topics:
        for ch in lib.get_channels(topic):
            vdir = config.channel_dir(topic, ch.name) / "videos"
            if not vdir.exists():
                continue
            for d in vdir.iterdir():
                if not d.is_dir() or not artifact_exists(d, "insights"):
                    continue
                total_videos += 1
                meta_path = d / "metadata.json"
                meta = read_json_dict(meta_path) if meta_path.exists() else {}
                if meta.get("analysis_mode") == "scan":
                    scan_videos += 1
                else:
                    full_videos += 1

    site_count, page_count = count_site_corpus(config, topics)
    paper_count = count_paper_corpus(config, topics)
    report_count, brief_count, synthesis_count = count_topic_outputs(config, topics)
    # Check new location first, fall back to old
    _ops_log = config.library_dir / ".distill" / "cost_log.jsonl"
    _legacy_log = config.library_dir / "cost_log.jsonl"
    _cost_log = _ops_log if _ops_log.exists() else _legacy_log
    all_cost_entries = load_all_cost_runs(_cost_log)
    recent_runs = all_cost_entries[-6:]
    recent_spend = sum_recent_cost(recent_runs)
    latest_run = load_latest_run_payload(config.library_dir)
    latest_results = json_object(latest_run.get("results"))
    latest_issues = object_list(latest_run.get("issues"))
    recent_artifacts = collect_recent_artifacts(config, topics, limit=6)
    topic_changes = collect_topic_changes(config, lib, topics, topic_watchlist, limit=6)
    topic_trends = {topic: topic_trend_label(config, topic) for topic in topics}
    stale_watches = collect_stale_topic_watches(topic_watchlist)
    # Stale syntheses lead: confident prose missing newer sources outranks
    # wall-clock age and thin-artifact noise.
    corpus_warnings = (
        stale_synthesis_warnings(config, topics, limit=4)
        + collect_corpus_health_warnings(config, lib, topics, limit=8)
    )[:8]
    next_sweep_cost = estimated_topic_watch_sweep(topic_watchlist)
    topic_spend = topic_cost_rollups(all_cost_entries, days=30, limit=4)
    source_spend = source_cost_rollups(all_cost_entries, days=30)
    cost_warnings = cost_anomaly_warnings(all_cost_entries)
    budget_msgs: list[str] = []
    for entry in topic_watchlist:
        budget_msgs.extend(topic_watch_budget_messages(entry, all_cost_entries))

    return {
        "lib": lib,
        "topics": topics,
        "watchlist": watchlist,
        "topic_watchlist": topic_watchlist,
        "total_channels": total_channels,
        "total_videos": total_videos,
        "full_videos": full_videos,
        "scan_videos": scan_videos,
        "site_count": site_count,
        "page_count": page_count,
        "paper_count": paper_count,
        "report_count": report_count,
        "brief_count": brief_count,
        "synthesis_count": synthesis_count,
        "all_cost_entries": all_cost_entries,
        "recent_runs": recent_runs,
        "recent_spend": recent_spend,
        "latest_results": latest_results,
        "latest_issues": latest_issues,
        "recent_artifacts": recent_artifacts,
        "topic_changes": topic_changes,
        "topic_trends": topic_trends,
        "stale_topic_watches": stale_watches,
        "corpus_health_warnings": corpus_warnings,
        "next_sweep_cost": next_sweep_cost,
        "due_topic_watches": len(stale_watches),
        "topic_spend_rollups": topic_spend,
        "source_spend_rollups": source_spend,
        "cost_warnings": cost_warnings,
        "budget_messages": budget_msgs,
    }
