"""Shared dashboard data functions used by both CLI and web UI."""

import json
from datetime import datetime, timedelta
from pathlib import Path

from distill.cli_shared import duration_str, strip_frontmatter
from distill.config import DistillConfig
from distill.library import Library
from distill.site_scraper import site_section_key

# ── Cost log helpers ────────────────────────────────────────────────


def load_recent_cost_runs(log_file: Path, limit: int = 5) -> list[dict]:
    if not log_file.exists():
        return []
    entries = []
    try:
        for line in log_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return entries[-limit:]


def load_all_cost_runs(log_file: Path) -> list[dict]:
    return load_recent_cost_runs(log_file, limit=10000)


def load_latest_run_payload(log_dir: Path) -> dict:
    latest = log_dir / "latest_run.json"
    if not latest.exists():
        return {}
    try:
        return json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def sum_recent_cost(entries: list[dict]) -> float:
    total = 0.0
    for entry in entries:
        try:
            total += float(entry.get("actual_cost") or 0)
        except (TypeError, ValueError):
            continue
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


def estimated_topic_watch_sweep(topic_watchlist) -> float:
    total = 0.0
    for entry in topic_watchlist:
        total += entry.limit * 0.006
        if entry.report:
            total += 2.55
    return total


def estimate_topic_watch_cost(entry) -> float:
    total = entry.limit * 0.006
    if entry.report:
        total += 2.55
    return total


def topic_spend_last_days(entries: list[dict], topic: str, days: int = 30) -> float:
    cutoff = datetime.now() - timedelta(days=days)
    total = 0.0
    for entry in entries:
        metadata = entry.get("metadata") or {}
        if metadata.get("topic") != topic:
            continue
        ts = parse_run_datetime(str(entry.get("timestamp", "")))
        if ts is None or ts < cutoff:
            continue
        try:
            total += float(entry.get("actual_cost") or 0.0)
        except (TypeError, ValueError):
            continue
    return total


def topic_recent_costs(entries: list[dict], topic: str, limit: int = 5) -> list[float]:
    values: list[tuple[datetime, float]] = []
    for entry in entries:
        metadata = entry.get("metadata") or {}
        if metadata.get("topic") != topic:
            continue
        ts = parse_run_datetime(str(entry.get("timestamp", "")))
        if ts is None:
            continue
        try:
            cost = float(entry.get("actual_cost") or 0.0)
        except (TypeError, ValueError):
            continue
        values.append((ts, cost))
    values.sort(key=lambda item: item[0], reverse=True)
    return [cost for _, cost in values[:limit]]


def topic_watch_budget_messages(entry, all_cost_entries: list[dict]) -> list[str]:
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


def entry_source_type(entry: dict) -> str:
    metadata = entry.get("metadata") or {}
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
    entries: list[dict], days: int = 30, limit: int = 5
) -> list[tuple[str, float, int]]:
    cutoff = datetime.now() - timedelta(days=days)
    rollups: dict[str, dict[str, float | int]] = {}
    for entry in entries:
        ts = parse_run_datetime(str(entry.get("timestamp", "")))
        if ts is None or ts < cutoff:
            continue
        metadata = entry.get("metadata") or {}
        topic = str(metadata.get("topic") or "").strip()
        if not topic:
            continue
        bucket = rollups.setdefault(topic, {"cost": 0.0, "runs": 0})
        try:
            bucket["cost"] += float(entry.get("actual_cost") or 0.0)
        except (TypeError, ValueError):
            continue
        bucket["runs"] += 1
    items = [(topic, float(data["cost"]), int(data["runs"])) for topic, data in rollups.items()]
    items.sort(key=lambda item: item[1], reverse=True)
    return items[:limit]


def source_cost_rollups(entries: list[dict], days: int = 30) -> list[tuple[str, float, int]]:
    cutoff = datetime.now() - timedelta(days=days)
    rollups: dict[str, dict[str, float | int]] = {}
    for entry in entries:
        ts = parse_run_datetime(str(entry.get("timestamp", "")))
        if ts is None or ts < cutoff:
            continue
        source_type = entry_source_type(entry)
        bucket = rollups.setdefault(source_type, {"cost": 0.0, "runs": 0})
        try:
            bucket["cost"] += float(entry.get("actual_cost") or 0.0)
        except (TypeError, ValueError):
            continue
        bucket["runs"] += 1
    items = [(source, float(data["cost"]), int(data["runs"])) for source, data in rollups.items()]
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
                if page_dir.is_dir() and (page_dir / "content.md").exists():
                    page_count += 1
    return site_count, page_count


def count_paper_corpus(config: DistillConfig, topics: list[str]) -> int:
    total = 0
    for topic in topics:
        papers_dir = config.papers_dir(topic)
        if not papers_dir.exists():
            continue
        for paper_dir in papers_dir.iterdir():
            if paper_dir.is_dir() and (paper_dir / "paper.md").exists():
                total += 1
    return total


def count_topic_outputs(config: DistillConfig, topics: list[str]) -> tuple[int, int, int]:
    report_count = 0
    brief_count = 0
    synthesis_count = 0
    for topic in topics:
        topic_dir = config.topic_dir(topic)
        if (topic_dir / "report.md").exists():
            report_count += 1
        if (topic_dir / "brief.md").exists():
            brief_count += 1
        if (topic_dir / "topic_synthesis.md").exists():
            synthesis_count += 1
    return report_count, brief_count, synthesis_count


# ── Artifact + health helpers ───────────────────────────────────────


def collect_recent_artifacts(
    config: DistillConfig, topics: list[str], limit: int = 6
) -> list[tuple[datetime, str, str]]:
    artifacts = []
    for topic in topics:
        topic_dir = config.topic_dir(topic)
        candidates = [
            (topic_dir / "topic_synthesis.md", "topic synthesis", topic),
            (topic_dir / "corpus_synthesis.md", "corpus synthesis", topic),
            (topic_dir / "paper_synthesis.md", "paper synthesis", topic),
            (topic_dir / "report.md", "report", topic),
            (topic_dir / "brief.md", "brief", topic),
        ]
        sites_dir = config.sites_dir(topic)
        if sites_dir.exists():
            for site_dir in sites_dir.iterdir():
                if site_dir.is_dir():
                    candidates.append(
                        (site_dir / "synthesis.md", "site synthesis", f"{topic} / {site_dir.name}")
                    )
                    candidates.append(
                        (site_dir / "site_update.md", "site update", f"{topic} / {site_dir.name}")
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


def collect_stale_topic_watches(topic_watchlist) -> list[str]:
    stale = []
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


def collect_corpus_health_warnings(
    config: DistillConfig,
    lib: Library,
    topics: list[str],
    *,
    limit: int = 8,
) -> list[str]:
    warnings: list[str] = []
    stale_cutoff = datetime.now() - timedelta(days=90)
    site_section_cutoff = datetime.now() - timedelta(days=30)

    for topic in topics:
        topic_dir = config.topic_dir(topic)
        for name in (
            "topic_synthesis.md",
            "paper_synthesis.md",
            "corpus_synthesis.md",
            "report.md",
        ):
            path_obj = topic_dir / name
            if not path_obj.exists():
                continue
            try:
                mtime = datetime.fromtimestamp(path_obj.stat().st_mtime)
            except OSError:
                continue
            if mtime < stale_cutoff:
                warnings.append(f"{topic} {name} is stale ({(datetime.now() - mtime).days}d old)")
                if len(warnings) >= limit:
                    return warnings

        for channel in lib.get_channels(topic):
            videos_dir = config.channel_dir(topic, channel.name) / "videos"
            if not videos_dir.exists():
                continue
            for video_dir in videos_dir.iterdir():
                if not video_dir.is_dir():
                    continue
                metadata = {}
                meta_path = video_dir / "metadata.json"
                if meta_path.exists():
                    try:
                        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        metadata = {}
                title = str(metadata.get("title") or video_dir.name)
                dur = int(metadata.get("duration") or 0)

                transcript_path = video_dir / "transcript.txt"
                if transcript_path.exists():
                    try:
                        transcript_len = len(transcript_path.read_text(encoding="utf-8").strip())
                    except OSError:
                        transcript_len = 0
                    if dur >= 1800 and transcript_len < 500:
                        warnings.append(
                            f"{topic} / {channel.name}: {title} transcript looks thin "
                            f"({transcript_len} chars for {duration_str(dur)})"
                        )
                        if len(warnings) >= limit:
                            return warnings

                insights_path = video_dir / "insights.md"
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
                    metadata = {}
                    meta_path = page_dir / "metadata.json"
                    if meta_path.exists():
                        try:
                            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
                        except (OSError, json.JSONDecodeError):
                            metadata = {}
                    title = str(metadata.get("title") or page_dir.name)
                    insights_path = page_dir / "insights.md"
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
                metadata = {}
                meta_path = paper_dir / "metadata.json"
                if meta_path.exists():
                    try:
                        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        metadata = {}
                title = str(metadata.get("title") or paper_dir.name)
                insights_path = paper_dir / "insights.md"
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


def load_topic_change_history(config: DistillConfig, topic: str) -> list[dict]:
    history_path = _topic_change_history_path(config, topic)
    if not history_path.exists():
        return []
    records = []
    try:
        for line in history_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            generated_at = parse_run_datetime(str(payload.get("generated_at", "")))
            counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
            if generated_at is None:
                continue
            records.append(
                {
                    "generated_at": generated_at,
                    "summary": str(payload.get("summary", "") or ""),
                    "counts": {
                        "videos": int(counts.get("videos", 0) or 0),
                        "pages": int(counts.get("pages", 0) or 0),
                        "papers": int(counts.get("papers", 0) or 0),
                        "outputs": int(counts.get("outputs", 0) or 0),
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
    latest = sum(int(v) for v in records[0]["counts"].values())
    previous = sum(int(v) for v in records[1]["counts"].values())
    if latest > previous:
        return "trend: rising"
    if latest < previous:
        return "trend: cooling"
    return "trend: steady"


def collect_topic_changes(
    config: DistillConfig,
    lib: Library,
    topics: list[str],
    topic_watchlist,
    limit: int = 6,
) -> list[tuple[str, str]]:
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
                insight_path = video_dir / "insights.md"
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
                        content_path = page_dir / "content.md"
                        if not page_dir.is_dir() or not content_path.exists():
                            continue
                        try:
                            mtime = datetime.fromtimestamp(content_path.stat().st_mtime)
                        except OSError:
                            continue
                        if mtime > baseline:
                            new_pages += 1
                            last_change = max(last_change, mtime)
                site_synth = site_dir / "synthesis.md"
                if site_synth.exists():
                    try:
                        mtime = datetime.fromtimestamp(site_synth.stat().st_mtime)
                    except OSError:
                        mtime = None
                    if mtime and mtime > baseline:
                        refreshed_outputs.append("site synthesis")
                        last_change = max(last_change, mtime)

        topic_dir = config.topic_dir(topic)
        for label, filename in (
            ("synthesis", "topic_synthesis.md"),
            ("brief", "brief.md"),
            ("report", "report.md"),
        ):
            path_obj = topic_dir / filename
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
            parts = []
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


def _load_site_manifest(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def build_site_section_state(pages) -> list[dict]:
    section_buckets: dict[str, list] = {}
    for page in pages:
        section = site_section_key(page.final_url or page.url)
        section_buckets.setdefault(section, []).append(page)

    section_state: list[dict] = []
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


# ── Main snapshot ───────────────────────────────────────────────────


def dashboard_snapshot(config: DistillConfig) -> dict:
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
                if not d.is_dir() or not (d / "insights.md").exists():
                    continue
                total_videos += 1
                meta_path = d / "metadata.json"
                try:
                    if meta_path.exists():
                        meta = json.loads(meta_path.read_text(encoding="utf-8"))
                        if meta.get("analysis_mode") == "scan":
                            scan_videos += 1
                        else:
                            full_videos += 1
                    else:
                        full_videos += 1
                except (OSError, json.JSONDecodeError):
                    full_videos += 1

    site_count, page_count = count_site_corpus(config, topics)
    paper_count = count_paper_corpus(config, topics)
    report_count, brief_count, synthesis_count = count_topic_outputs(config, topics)
    all_cost_entries = load_all_cost_runs(config.library_dir / "cost_log.jsonl")
    recent_runs = all_cost_entries[-6:]
    recent_spend = sum_recent_cost(recent_runs)
    latest_run = load_latest_run_payload(config.library_dir)
    latest_results = latest_run.get("results", {}) if latest_run else {}
    latest_issues = latest_run.get("issues", []) if latest_run else []
    recent_artifacts = collect_recent_artifacts(config, topics, limit=6)
    topic_changes = collect_topic_changes(config, lib, topics, topic_watchlist, limit=6)
    topic_trends = {topic: topic_trend_label(config, topic) for topic in topics}
    stale_watches = collect_stale_topic_watches(topic_watchlist)
    corpus_warnings = collect_corpus_health_warnings(config, lib, topics, limit=8)
    next_sweep_cost = estimated_topic_watch_sweep(topic_watchlist)
    topic_spend = topic_cost_rollups(all_cost_entries, days=30, limit=4)
    source_spend = source_cost_rollups(all_cost_entries, days=30)
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
        "budget_messages": budget_msgs,
    }
