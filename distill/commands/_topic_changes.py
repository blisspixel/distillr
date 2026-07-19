# pyright: strict
"""Topic change and trend helpers for the Distill CLI."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import TypedDict

import typer

from distill.cli_shared import format_date as _format_date
from distill.config import DistillConfig
from distill.jsonl import append_jsonl_line
from distill.library import Library
from distill.library.locking import exclusive_path_lock
from distill.library.paths import (
    artifact_path,
    base_frontmatter,
    find_artifact,
    strip_frontmatter,
    tags_for,
    write_markdown_artifact,
)
from distill.parsing import read_bounded_json_object, read_bounded_jsonl_objects
from distill.pipeline.dashboard_data import format_run_timestamp as _format_run_timestamp
from distill.pipeline.dashboard_data import parse_run_datetime as _parse_run_datetime
from distill.pipeline.dashboard_records import JsonObject, TopicChangeCounts, json_object

_MAX_TOPIC_JSON_BYTES = 8 * 1024 * 1024
_MAX_TOPIC_HISTORY_BYTES = 8 * 1024 * 1024
_MAX_TOPIC_HISTORY_ROWS = 10_000
_LATEST_CHANGES_LOCK_TIMEOUT_SECONDS = 30.0


class _ChangedArtifact(TypedDict):
    title: str
    changed_at: datetime
    path: Path


class _VideoChange(_ChangedArtifact):
    channel: str
    upload_date: str


class _PageChange(_ChangedArtifact):
    site: str
    url: str


class _PaperChange(_ChangedArtifact):
    paper_id: str


class _RefreshedOutput(TypedDict):
    label: str
    changed_at: datetime
    path: Path


class _TopicChangeDetails(TypedDict):
    topic: str
    baseline: datetime | None
    effective_baseline: datetime
    generated_at: datetime
    last_change: datetime | None
    summary: str
    new_videos: list[_VideoChange]
    new_pages: list[_PageChange]
    new_papers: list[_PaperChange]
    refreshed_outputs: list[_RefreshedOutput]


class _TopicChangeHistoryRecord(TypedDict):
    generated_at: datetime
    topic: str
    watch_name: str
    query: str
    cadence: str
    baseline: str
    summary: str
    counts: TopicChangeCounts


def _read_json_file(path_obj: Path) -> JsonObject:
    return json_object(read_bounded_json_object(path_obj, max_bytes=_MAX_TOPIC_JSON_BYTES))


def _text_field(record: JsonObject, key: str, default: str = "") -> str:
    value = record.get(key)
    return default if value is None else str(value)


def _count_value(value: object) -> int:
    if isinstance(value, (int, float, str)):
        try:
            return int(value)
        except (OverflowError, ValueError):
            return 0
    return 0


def _topic_change_counts(value: object) -> TopicChangeCounts:
    counts = json_object(value)
    return {
        "videos": _count_value(counts.get("videos")),
        "pages": _count_value(counts.get("pages")),
        "papers": _count_value(counts.get("papers")),
        "outputs": _count_value(counts.get("outputs")),
    }


def _topic_change_history_path(config: DistillConfig, topic: str) -> Path:
    return config.topic_dir(topic) / "change_history.jsonl"


topic_change_history_path = _topic_change_history_path


def _topic_diff_output_path(config: DistillConfig, topic: str) -> Path:
    return artifact_path(config.topic_dir(topic), "topic_diff", identity=topic)


def topic_trends_output_path(config: DistillConfig, topic: str) -> Path:
    return artifact_path(config.topic_dir(topic), "topic_trends", identity=topic)


def watch_alerts_output_path(config: DistillConfig) -> Path:
    return artifact_path(config.library_dir, "watch_alerts", identity="library")


_topic_trends_output_path = topic_trends_output_path
_watch_alerts_output_path = watch_alerts_output_path


def _relative_library_path(config: DistillConfig, path_obj: Path) -> str:
    try:
        return str(path_obj.resolve().relative_to(config.library_dir.resolve()))
    except ValueError:
        return str(path_obj.resolve())


def _append_limited_section(
    lines: list[str], header: str, rendered_items: list[str], total_count: int, limit: int
) -> None:
    if total_count == 0:
        return
    lines.extend([f"## {header}", ""])
    for rendered in rendered_items:
        lines.extend(rendered.splitlines())
    remaining = total_count - limit
    if remaining > 0:
        lines.append(f"- ...and {remaining} more")
    lines.append("")


def _format_video_change(config: DistillConfig, item: _VideoChange) -> str:
    changed = _format_run_timestamp(item["changed_at"].isoformat())
    path = _relative_library_path(config, item["path"])
    return (
        f"- `{item['channel']}` - {item['title']}"
        f" ({_format_date(item['upload_date'])}; changed {changed})"
        f"  [`{path}`]"
    )


def _format_page_change(config: DistillConfig, item: _PageChange) -> str:
    lines = [
        f"- `{item['site']}` - {item['title']} "
        f"({_format_run_timestamp(item['changed_at'].isoformat())})"
    ]
    if item["url"]:
        lines.append(f"  URL: {item['url']}")
    lines.append(f"  Path: `{_relative_library_path(config, item['path'])}`")
    return "\n".join(lines)


def _format_paper_change(config: DistillConfig, item: _PaperChange) -> str:
    paper_id = f" (`{item['paper_id']}`)" if item["paper_id"] else ""
    changed = _format_run_timestamp(item["changed_at"].isoformat())
    path = _relative_library_path(config, item["path"])
    return f"- {item['title']}{paper_id} ({changed})  [`{path}`]"


def _format_refreshed_output(config: DistillConfig, item: _RefreshedOutput) -> str:
    changed = _format_run_timestamp(item["changed_at"].isoformat())
    path = _relative_library_path(config, item["path"])
    return f"- {item['label']} ({changed})  [`{path}`]"


def _count_total(counts: TopicChangeCounts) -> int:
    return counts["videos"] + counts["pages"] + counts["papers"] + counts["outputs"]


def _collect_topic_change_details(  # noqa: C901 — legacy, will refactor
    config: DistillConfig,
    lib: Library,
    topic: str,
    baseline: datetime | None,
) -> _TopicChangeDetails:
    now = datetime.now()
    effective_baseline = baseline or (now - timedelta(days=7))

    new_videos: list[_VideoChange] = []
    new_pages: list[_PageChange] = []
    new_papers: list[_PaperChange] = []
    refreshed_outputs: list[_RefreshedOutput] = []
    last_change: datetime | None = None

    def mark_change(changed_at: datetime | None) -> None:
        nonlocal last_change
        if changed_at is None:
            return
        last_change = changed_at if last_change is None else max(last_change, changed_at)

    for ch in lib.get_channels(topic):
        videos_dir = config.channel_dir(topic, ch.name) / "videos"
        if not videos_dir.exists():
            continue
        for video_dir in videos_dir.iterdir():
            insight_path = find_artifact(video_dir, "insights")
            if not video_dir.is_dir() or not insight_path.exists():
                continue
            try:
                changed_at = datetime.fromtimestamp(insight_path.stat().st_mtime)
            except OSError:
                continue
            if changed_at <= effective_baseline:
                continue
            meta = _read_json_file(video_dir / "metadata.json")
            new_videos.append(
                {
                    "title": _text_field(meta, "title", video_dir.name),
                    "channel": ch.name,
                    "upload_date": _text_field(meta, "upload_date"),
                    "changed_at": changed_at,
                    "path": insight_path,
                }
            )
            mark_change(changed_at)

        synth_path = find_artifact(
            config.channel_dir(topic, ch.name),
            "synthesis",
            identity=f"{topic}_{ch.name}",
        )
        if synth_path.exists():
            try:
                changed_at = datetime.fromtimestamp(synth_path.stat().st_mtime)
            except OSError:
                changed_at = None
            if changed_at and changed_at > effective_baseline:
                refreshed_outputs.append(
                    {
                        "label": f"channel synthesis: {ch.name}",
                        "changed_at": changed_at,
                        "path": synth_path,
                    }
                )
                mark_change(changed_at)

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
                        changed_at = datetime.fromtimestamp(content_path.stat().st_mtime)
                    except OSError:
                        continue
                    if changed_at <= effective_baseline:
                        continue
                    meta = _read_json_file(page_dir / "metadata.json")
                    new_pages.append(
                        {
                            "title": _text_field(meta, "title", page_dir.name),
                            "site": site_dir.name,
                            "url": _text_field(meta, "url"),
                            "changed_at": changed_at,
                            "path": content_path,
                        }
                    )
                    mark_change(changed_at)

            site_synth = find_artifact(
                site_dir,
                "site_synthesis",
                identity=f"{topic}_{site_dir.name}",
            )
            if site_synth.exists():
                try:
                    changed_at = datetime.fromtimestamp(site_synth.stat().st_mtime)
                except OSError:
                    changed_at = None
                if changed_at and changed_at > effective_baseline:
                    refreshed_outputs.append(
                        {
                            "label": f"site synthesis: {site_dir.name}",
                            "changed_at": changed_at,
                            "path": site_synth,
                        }
                    )
                    mark_change(changed_at)

    papers_dir = config.papers_dir(topic)
    if papers_dir.exists():
        for paper_dir in papers_dir.iterdir():
            insights_path = find_artifact(paper_dir, "insights")
            if not paper_dir.is_dir() or not insights_path.exists():
                continue
            try:
                changed_at = datetime.fromtimestamp(insights_path.stat().st_mtime)
            except OSError:
                continue
            if changed_at <= effective_baseline:
                continue
            meta = _read_json_file(paper_dir / "metadata.json")
            new_papers.append(
                {
                    "title": _text_field(meta, "title", paper_dir.name),
                    "paper_id": _text_field(meta, "paper_id"),
                    "changed_at": changed_at,
                    "path": insights_path,
                }
            )
            mark_change(changed_at)

    topic_dir = config.topic_dir(topic)
    for label, path_obj in (
        ("topic synthesis", find_artifact(topic_dir, "topic_synthesis", identity=topic)),
        ("paper synthesis", find_artifact(topic_dir, "paper_synthesis", identity=topic)),
        ("corpus synthesis", find_artifact(topic_dir, "corpus_synthesis", identity=topic)),
        ("brief", find_artifact(topic_dir, "brief", identity=topic)),
        ("report", find_artifact(topic_dir, "report", identity=topic)),
        ("watch update", find_artifact(topic_dir, "watch_update", identity=topic)),
    ):
        if not path_obj.exists():
            continue
        try:
            changed_at = datetime.fromtimestamp(path_obj.stat().st_mtime)
        except OSError:
            continue
        if changed_at > effective_baseline:
            refreshed_outputs.append(
                {
                    "label": label,
                    "changed_at": changed_at,
                    "path": path_obj,
                }
            )
            mark_change(changed_at)

    new_videos.sort(key=lambda item: item["changed_at"], reverse=True)
    new_pages.sort(key=lambda item: item["changed_at"], reverse=True)
    new_papers.sort(key=lambda item: item["changed_at"], reverse=True)
    refreshed_outputs.sort(key=lambda item: item["changed_at"], reverse=True)

    if new_videos or new_pages or new_papers or refreshed_outputs:
        parts: list[str] = []
        if new_videos:
            parts.append(f"+{len(new_videos)} video{'s' if len(new_videos) != 1 else ''}")
        if new_pages:
            parts.append(f"+{len(new_pages)} page{'s' if len(new_pages) != 1 else ''}")
        if new_papers:
            parts.append(f"+{len(new_papers)} paper{'s' if len(new_papers) != 1 else ''}")
        if refreshed_outputs:
            labels = [str(item["label"]) for item in refreshed_outputs]
            parts.append(", ".join(dict.fromkeys(labels)) + " refreshed")
        summary = " · ".join(parts)
    elif baseline is not None:
        summary = f"quiet since {_format_run_timestamp(baseline.isoformat())}"
    else:
        summary = "no recent change detected"

    return {
        "topic": topic,
        "baseline": baseline,
        "effective_baseline": effective_baseline,
        "generated_at": now,
        "last_change": last_change,
        "summary": summary,
        "new_videos": new_videos,
        "new_pages": new_pages,
        "new_papers": new_papers,
        "refreshed_outputs": refreshed_outputs,
    }


def collect_topic_change_details(
    config: DistillConfig,
    lib: Library,
    topic: str,
    baseline: datetime | None,
) -> _TopicChangeDetails:
    """Public topic-change detail collection seam for command modules."""
    return _collect_topic_change_details(config, lib, topic, baseline)


def topic_change_snapshot(
    config: DistillConfig, lib: Library, topic: str, baseline: datetime | None
) -> tuple[datetime | None, str]:
    details = _collect_topic_change_details(config, lib, topic, baseline)
    return details["last_change"], details["summary"]


_topic_change_snapshot = topic_change_snapshot


def _render_topic_diff_markdown(
    config: DistillConfig,
    *,
    title: str,
    topic: str,
    summary: str,
    baseline: datetime | None,
    effective_baseline: datetime,
    generated_at: datetime,
    new_videos: list[_VideoChange],
    new_pages: list[_PageChange],
    new_papers: list[_PaperChange],
    refreshed_outputs: list[_RefreshedOutput],
    watch_name: str | None = None,
    query: str | None = None,
    cadence: str | None = None,
    limit: int = 10,
) -> str:
    lines = [title, "", f"- Topic: `{topic}`"]
    if watch_name:
        lines.append(f"- Watch: `{watch_name}`")
    if query:
        lines.append(f"- Query: `{query}`")
    if cadence:
        lines.append(f"- Cadence: `{cadence}`")
    lines.append(f"- Generated: `{generated_at.isoformat(timespec='seconds')}`")
    if baseline is not None:
        lines.append(f"- Compared Against: `{baseline.isoformat(timespec='seconds')}`")
    else:
        lines.append(f"- Window Start: `{effective_baseline.isoformat(timespec='seconds')}`")
    lines.extend(["", "## Summary", "", f"- {summary}", ""])

    _append_limited_section(
        lines,
        "New Video Insights",
        [_format_video_change(config, item) for item in new_videos[:limit]],
        len(new_videos),
        limit,
    )
    _append_limited_section(
        lines,
        "New Website Pages",
        [_format_page_change(config, item) for item in new_pages[:limit]],
        len(new_pages),
        limit,
    )
    _append_limited_section(
        lines,
        "New Paper Insights",
        [_format_paper_change(config, item) for item in new_papers[:limit]],
        len(new_papers),
        limit,
    )
    _append_limited_section(
        lines,
        "Refreshed Outputs",
        [_format_refreshed_output(config, item) for item in refreshed_outputs[:limit]],
        len(refreshed_outputs),
        limit,
    )

    if not new_videos and not new_pages and not new_papers and not refreshed_outputs:
        lines.extend(["## Details", "", "- No new artifacts crossed the comparison window.", ""])

    return "\n".join(lines)


render_topic_diff_markdown = _render_topic_diff_markdown


def _append_topic_change_history(
    config: DistillConfig,
    *,
    topic: str,
    summary: str,
    baseline: datetime | None,
    generated_at: datetime,
    watch_name: str | None,
    query: str | None,
    cadence: str | None,
    new_videos: list[_VideoChange],
    new_pages: list[_PageChange],
    new_papers: list[_PaperChange],
    refreshed_outputs: list[_RefreshedOutput],
) -> Path:
    history_path = _topic_change_history_path(config, topic)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": generated_at.isoformat(),
        "topic": topic,
        "watch_name": watch_name or "",
        "query": query or "",
        "cadence": cadence or "",
        "baseline": baseline.isoformat() if baseline is not None else "",
        "summary": summary,
        "counts": {
            "videos": len(new_videos),
            "pages": len(new_pages),
            "papers": len(new_papers),
            "outputs": len(refreshed_outputs),
        },
    }
    append_jsonl_line(
        history_path,
        json.dumps(payload, ensure_ascii=False, allow_nan=False),
        durable=True,
    )
    return history_path


append_topic_change_history = _append_topic_change_history


def _load_topic_change_history(
    config: DistillConfig, topic: str
) -> list[_TopicChangeHistoryRecord]:
    history_path = _topic_change_history_path(config, topic)
    records: list[_TopicChangeHistoryRecord] = []
    for row in read_bounded_jsonl_objects(
        history_path,
        max_bytes=_MAX_TOPIC_HISTORY_BYTES,
        max_rows=_MAX_TOPIC_HISTORY_ROWS,
    ):
        payload = json_object(row)
        generated_at = _parse_run_datetime(str(payload.get("generated_at", "")))
        if generated_at is None:
            continue
        counts = _topic_change_counts(payload.get("counts"))
        records.append(
            {
                "generated_at": generated_at,
                "topic": _text_field(payload, "topic", topic),
                "watch_name": _text_field(payload, "watch_name"),
                "query": _text_field(payload, "query"),
                "cadence": _text_field(payload, "cadence"),
                "baseline": _text_field(payload, "baseline"),
                "summary": _text_field(payload, "summary"),
                "counts": counts,
            }
        )
    records.sort(key=lambda item: item["generated_at"], reverse=True)
    return records


load_topic_change_history = _load_topic_change_history


def _topic_trend_direction(records: list[_TopicChangeHistoryRecord]) -> str:
    if len(records) < 2:
        return "not enough history yet"
    latest = _count_total(records[0]["counts"])
    previous = _count_total(records[1]["counts"])
    if latest > previous:
        return "activity is increasing"
    if latest < previous:
        return "activity is cooling"
    return "activity is steady"


def _topic_trend_label(config: DistillConfig, topic: str, *, min_records: int = 2) -> str | None:
    records = _load_topic_change_history(config, topic)
    if len(records) < min_records:
        return None
    direction = _topic_trend_direction(records[:2])
    if direction == "not enough history yet":
        return None
    if direction == "activity is increasing":
        return "trend: rising"
    if direction == "activity is cooling":
        return "trend: cooling"
    return "trend: steady"


def topic_trend_label(config: DistillConfig, topic: str, *, min_records: int = 2) -> str | None:
    """Public topic trend label seam for command modules."""
    return _topic_trend_label(config, topic, min_records=min_records)


def _topic_watch_alert_lines(
    *,
    watch_name: str,
    topic: str,
    ranking_label: str,
    summary: str,
    change_details: _TopicChangeDetails,
    trend_label: str | None,
) -> list[str]:
    counts = {
        "videos": len(change_details["new_videos"]),
        "pages": len(change_details["new_pages"]),
        "papers": len(change_details["new_papers"]),
        "outputs": len(change_details["refreshed_outputs"]),
    }
    signal_score = counts["videos"] + counts["pages"] + counts["papers"] + counts["outputs"]
    notable = signal_score > 0 or trend_label == "trend: rising"
    if not notable:
        return []

    bits = [summary]
    if trend_label:
        bits.append(trend_label)
    bits.append(ranking_label)
    return [f"- `{watch_name}` ({topic}): " + " / ".join(bits)]


def topic_watch_alert_lines(
    *,
    watch_name: str,
    topic: str,
    ranking_label: str,
    summary: str,
    change_details: _TopicChangeDetails,
    trend_label: str | None,
) -> list[str]:
    """Public topic-watch alert-line seam for command modules."""
    return _topic_watch_alert_lines(
        watch_name=watch_name,
        topic=topic,
        ranking_label=ranking_label,
        summary=summary,
        change_details=change_details,
        trend_label=trend_label,
    )


def _write_watch_alert_digest(
    config: DistillConfig,
    *,
    generated_at: datetime,
    alert_lines: list[str],
) -> Path:
    lines = [
        "# Topic Watch Alerts",
        "",
        f"- Generated: `{generated_at.isoformat(timespec='seconds')}`",
        f"- Alerts: `{len(alert_lines)}`",
        "",
        "## Highlights",
        "",
    ]
    if alert_lines:
        lines.extend(alert_lines)
    else:
        lines.append("- No notable watch alerts in this run.")
    lines.append("")
    return write_markdown_artifact(
        config.library_dir,
        "watch_alerts",
        "\n".join(lines),
        identity="library",
        frontmatter=base_frontmatter(
            artifact_type="watch_alerts",
            title="Topic Watch Alerts",
            source="distill",
            tags=tags_for("", "watch"),
            synthesis_scope="operational",
            extra={"alerts": len(alert_lines), "legacy_filename": "watch_alerts.md"},
        ),
    )


def write_watch_alert_digest(
    config: DistillConfig,
    *,
    generated_at: datetime,
    alert_lines: list[str],
) -> Path:
    """Public watch-alert digest writer seam for command modules."""
    return _write_watch_alert_digest(
        config,
        generated_at=generated_at,
        alert_lines=alert_lines,
    )


def render_topic_trends_markdown(
    config: DistillConfig,
    *,
    topic: str,
    records: list[_TopicChangeHistoryRecord],
    generated_at: datetime,
    limit: int,
) -> str:
    selected = records[:limit]
    total_video = sum(item["counts"]["videos"] for item in selected)
    total_pages = sum(item["counts"]["pages"] for item in selected)
    total_papers = sum(item["counts"]["papers"] for item in selected)
    total_outputs = sum(item["counts"]["outputs"] for item in selected)
    active_windows = sum(1 for item in selected if _count_total(item["counts"]) > 0)
    primary_watch = next((item["watch_name"] for item in selected if item["watch_name"]), "")

    lines = [
        f"# Topic Trends: {topic}",
        "",
        f"- Topic: `{topic}`",
        f"- Generated: `{generated_at.isoformat(timespec='seconds')}`",
        f"- Windows Considered: `{len(selected)}`",
    ]
    if primary_watch:
        lines.append(f"- Primary Watch: `{primary_watch}`")
    lines.extend(
        [
            "",
            "## Summary",
            "",
            f"- {_topic_trend_direction(selected)}",
            f"- {active_windows}/{len(selected)} recent windows had measurable change"
            if selected
            else "- No recent windows yet",
            f"- Totals across selected windows: +{total_video} videos, +{total_pages} pages, +{total_papers} papers, {total_outputs} refreshed outputs",
            "",
        ]
    )

    if not selected:
        lines.extend(["## History", "", "- No topic change history has been recorded yet.", ""])
        return "\n".join(lines)

    lines.extend(["## Recent Windows", ""])
    for item in selected:
        changed_at = _format_run_timestamp(item["generated_at"].isoformat())
        counts = item["counts"]
        count_bits = [
            f"+{counts['videos']} video{'s' if counts['videos'] != 1 else ''}"
            if counts["videos"]
            else None,
            f"+{counts['pages']} page{'s' if counts['pages'] != 1 else ''}"
            if counts["pages"]
            else None,
            f"+{counts['papers']} paper{'s' if counts['papers'] != 1 else ''}"
            if counts["papers"]
            else None,
            f"{counts['outputs']} output{'s' if counts['outputs'] != 1 else ''} refreshed"
            if counts["outputs"]
            else None,
        ]
        count_bits = [bit for bit in count_bits if bit]
        lines.append(
            f"- `{changed_at}` - {item['summary'] or ', '.join(count_bits) or 'no recorded change'}"
        )
        if item["watch_name"]:
            lines.append(f"  Watch: `{item['watch_name']}`")
    lines.append("")

    lines.extend(
        [
            "## Artifacts",
            "",
            f"- History: `{_topic_change_history_path(config, topic)}`",
            f"- Latest diff: `{_topic_diff_output_path(config, topic)}`",
            "",
        ]
    )
    return "\n".join(lines)


_render_topic_trends_markdown = render_topic_trends_markdown


def _write_topic_change_briefing(
    config: DistillConfig,
    *,
    watch_name: str,
    topic: str,
    query: str,
    cadence: str,
    baseline: datetime | None,
    summary: str,
    change_details: _TopicChangeDetails | None = None,
) -> Path:
    details = change_details or _collect_topic_change_details(
        config,
        Library(config),
        topic,
        baseline,
    )
    generated_at = details["generated_at"]
    effective_baseline = details["effective_baseline"]
    new_videos = details["new_videos"]
    new_pages = details["new_pages"]
    new_papers = details["new_papers"]
    refreshed_outputs = details["refreshed_outputs"]

    topic_dir = config.topic_dir(topic)
    topic_dir.mkdir(parents=True, exist_ok=True)
    briefing_content = _render_topic_diff_markdown(
        config,
        title=f"# Topic Watch Update: {watch_name}",
        topic=topic,
        summary=summary,
        baseline=baseline,
        effective_baseline=effective_baseline,
        generated_at=generated_at,
        watch_name=watch_name,
        query=query,
        cadence=cadence,
        new_videos=new_videos,
        new_pages=new_pages,
        new_papers=new_papers,
        refreshed_outputs=refreshed_outputs,
    )
    briefing_path = write_markdown_artifact(
        topic_dir,
        "watch_update",
        briefing_content,
        identity=topic,
        frontmatter=base_frontmatter(
            artifact_type="watch_update",
            title=f"Topic Watch Update: {watch_name}",
            topic=topic,
            source="distill",
            tags=tags_for(topic, "watch"),
            synthesis_scope="operational",
            extra={
                "watch_name": watch_name,
                "query": query,
                "cadence": cadence,
                "legacy_filename": "watch_update.md",
            },
        ),
    )

    diff_content = _render_topic_diff_markdown(
        config,
        title=f"# Topic Diff: {topic}",
        topic=topic,
        summary=summary,
        baseline=baseline,
        effective_baseline=effective_baseline,
        generated_at=generated_at,
        watch_name=watch_name,
        query=query,
        cadence=cadence,
        new_videos=new_videos,
        new_pages=new_pages,
        new_papers=new_papers,
        refreshed_outputs=refreshed_outputs,
    )
    diff_path = write_markdown_artifact(
        topic_dir,
        "topic_diff",
        diff_content,
        identity=topic,
        frontmatter=base_frontmatter(
            artifact_type="topic_diff",
            title=f"Topic Diff: {topic}",
            topic=topic,
            source="distill",
            tags=tags_for(topic, "diff"),
            synthesis_scope="operational",
            extra={
                "watch_name": watch_name or "",
                "query": query or "",
                "cadence": cadence or "",
                "legacy_filename": "topic_diff.md",
            },
        ),
    )

    history_path = _append_topic_change_history(
        config,
        topic=topic,
        summary=summary,
        baseline=baseline,
        generated_at=generated_at,
        watch_name=watch_name,
        query=query,
        cadence=cadence,
        new_videos=new_videos,
        new_pages=new_pages,
        new_papers=new_papers,
        refreshed_outputs=refreshed_outputs,
    )

    latest_path = artifact_path(config.library_dir, "latest_changes", identity="library")
    entry = (
        f"## {watch_name}\n"
        f"- Topic: `{topic}`\n"
        f"- Generated: `{generated_at.isoformat(timespec='seconds')}`\n"
        f"- Summary: {summary}\n"
        f"- Diff: `{diff_path}`\n"
        f"- History: `{history_path}`\n"
        f"- File: `{briefing_path}`\n\n"
    )
    with exclusive_path_lock(
        config.library_dir / ".distill" / "latest_changes.lock",
        timeout_seconds=_LATEST_CHANGES_LOCK_TIMEOUT_SECONDS,
        timeout_message="Timed out updating the library latest-changes feed",
    ):
        existing = (
            strip_frontmatter(latest_path.read_text(encoding="utf-8"))
            if latest_path.exists()
            else ""
        )
        latest_path = write_markdown_artifact(
            config.library_dir,
            "latest_changes",
            entry + existing,
            identity="library",
            frontmatter=base_frontmatter(
                artifact_type="latest_changes",
                title="Latest Changes",
                source="distill",
                tags=tags_for("", "watch"),
                synthesis_scope="operational",
                extra={"legacy_filename": "latest_changes.md"},
            ),
        )
    return briefing_path


def write_topic_change_briefing(
    config: DistillConfig,
    *,
    watch_name: str,
    topic: str,
    query: str,
    cadence: str,
    baseline: datetime | None,
    summary: str,
    change_details: _TopicChangeDetails | None = None,
) -> Path:
    """Public topic-change briefing writer seam for command modules."""
    return _write_topic_change_briefing(
        config,
        watch_name=watch_name,
        topic=topic,
        query=query,
        cadence=cadence,
        baseline=baseline,
        summary=summary,
        change_details=change_details,
    )


def resolve_topic_diff_baseline(
    lib: Library,
    topic: str,
    *,
    watch_name: str | None,
    days: int,
) -> tuple[datetime | None, str | None, str | None, str | None]:
    if watch_name:
        entry = lib.get_topic_watch_entry(watch_name)
        if entry is None:
            raise typer.BadParameter(f"Unknown topic watch: {watch_name}")
        if entry.topic.lower() != topic.lower():
            raise typer.BadParameter(
                f"Topic watch {watch_name} belongs to {entry.topic}, not {topic}"
            )
        return _parse_run_datetime(entry.last_run_at), entry.name, entry.query, entry.cadence

    matching = [
        e for e in lib.get_topic_watchlist() if e.topic.lower() == topic.lower() and e.last_run_at
    ]
    if matching:
        matching.sort(
            key=lambda e: _parse_run_datetime(e.last_run_at) or datetime.min,
            reverse=True,
        )
        entry = matching[0]
        return _parse_run_datetime(entry.last_run_at), entry.name, entry.query, entry.cadence

    return datetime.now() - timedelta(days=days), None, None, None


_resolve_topic_diff_baseline = resolve_topic_diff_baseline
