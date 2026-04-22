"""Distill CLI -- Turn YouTube channels into strategic intelligence."""

import json
import os
import re
import webbrowser
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha1
from html import escape
from pathlib import Path
from types import SimpleNamespace

import typer
from dotenv import load_dotenv
from openai import OpenAI
from rich import box
from rich.columns import Columns
from rich.panel import Panel
from rich.table import Table

import distill.cli_shared as cli_shared
from distill.analysis import (
    XAI_BASE_URL,
    analyze_scan,
    analyze_short,
    analyze_video,
    generate_channel_context,
)
from distill.banner import show_banner
from distill.briefing import generate_topic_brief
from distill.browser_search import search_youtube_results
from distill.cli_shared import (
    SHORTS_THRESHOLD,
    console,
)
from distill.cli_shared import (
    duration_str as _duration_str,
)
from distill.cli_shared import (
    format_date as _format_date,
)
from distill.cli_shared import (
    output_path as _output_path,
)
from distill.cli_shared import (
    print_markdown_safely as _print_markdown_safely,
)
from distill.cli_shared import (
    print_text_safely as _print_text_safely,
)
from distill.cli_shared import (
    require_api_key as _require_api_key,
)
from distill.cli_shared import (
    resolve_video_channel_name as _shared_resolve_video_channel_name,
)
from distill.cli_shared import (
    safe_console_text as _safe_console_text,
)
from distill.cli_shared import (
    strip_frontmatter as _strip_frontmatter,
)
from distill.cli_shared import (
    topic_from_query as _topic_from_query,
)
from distill.config import DistillConfig, site_name_from_url, slugify_title
from distill.corpus_analysis import synthesize_corpus
from distill.costs import CostTracker, TokenUsage, estimate_run_cost
from distill.discovery import (
    VideoInfo,
    discover_videos,
    enrich_videos,
    get_video_info,
    resolve_channel_name,
    search_videos,
)
from distill.docx_export import markdown_to_docx
from distill.library import Library
from distill.paper_analysis import analyze_paper, synthesize_papers
from distill.paper_ingest import (
    PaperRecord,
    build_paper_document,
    fetch_arxiv_paper,
    search_arxiv_multi,
    search_arxiv_papers,
)
from distill.prompts import (
    discover_query_generation_prompt,
    discover_rerank_prompt,
    paper_query_expansion_prompt,
    search_query_expansion_prompt,
)
from distill.ranking import RankedPaper, rerank_papers, rerank_videos
from distill.research import run_deep_research
from distill.research_brief import run_research_brief
from distill.site_analysis import analyze_site_page, synthesize_site, synthesize_site_topic
from distill.site_attachments import (
    collect_page_attachments,
    ingest_page_attachments,
    write_attachment_manifest,
)
from distill.site_scraper import (
    SiteSeed,
    build_page_document,
    crawl_site,
    load_site_batch,
    site_section_key,
)
from distill.state import ChannelState
from distill.summary import ETATracker, RunSummary, VideoResult, display_estimate, display_summary
from distill.synthesis import synthesize_channel, synthesize_topic
from distill.synthesize import run_synthesis
from distill.transcripts import get_transcript

app = typer.Typer(
    help=(
        "Distill source material into usable intelligence.\n\n"
        "Pick a starting point:\n"
        '  Have one YouTube URL?  distill video "https://www.youtube.com/watch?v=..."\n'
        "  Have one website URL?  distill site https://example.com/page --topic scratch --seed-only\n"
        "  Have one paper URL?    distill paper https://arxiv.org/abs/2602.12670 --topic papers\n"
        '  Need the latest on a topic?  distill latest "Microsoft AI news" --topic microsoft-news\n'
        '  Want recurring updates?      distill monitor "Microsoft AI news" --topic microsoft-news\n'
    ),
    invoke_without_command=True,
    rich_markup_mode="rich",
)


@app.callback()
def _default(ctx: typer.Context):
    """Distill - YouTube channels to strategic intelligence."""
    if ctx.invoked_subcommand is None:
        console.clear()
        show_banner(console)
        _show_dashboard()


def get_config() -> DistillConfig:
    load_dotenv()
    return DistillConfig()


def _complete_watched_channels(incomplete: str) -> list[str]:
    """Autocomplete for watched channel names."""
    try:
        lib = Library(get_config())
        return [
            e.name for e in lib.get_watchlist() if e.name.lower().startswith(incomplete.lower())
        ]
    except Exception:
        return []


def _complete_topic_watch_names(incomplete: str) -> list[str]:
    """Autocomplete for topic-watch names."""
    try:
        lib = Library(get_config())
        return [
            e.name
            for e in lib.get_topic_watchlist()
            if e.name.lower().startswith(incomplete.lower())
        ]
    except Exception:
        return []


def _complete_topics(incomplete: str) -> list[str]:
    """Autocomplete for topic names."""
    try:
        lib = Library(get_config())
        return [t for t in lib.get_topics() if t.lower().startswith(incomplete.lower())]
    except Exception:
        return []


def _resolve_topic_for_channel(
    lib: Library, topic: str | None, channel: str | None
) -> tuple[str | None, str | None]:
    """Auto-resolve topic when only a channel name is given.

    If topic looks like a channel name (not a known topic), treat it as
    the channel and resolve the topic from the library.

    Returns (topic, channel) with resolved values.
    """
    if topic and channel:
        return topic, channel

    # If topic is provided but isn't a known topic, maybe it's a channel name
    if topic and not channel and topic not in lib.get_topics():
        found = lib.find_channel(topic)
        if found:
            return found.topic, found.name

    # If channel is provided but topic is missing, look up the channel
    if channel and not topic:
        found = lib.find_channel(channel)
        if found:
            return found.topic, found.name

    return topic, channel


def _show_latest_insights(
    config: DistillConfig, topic: str, channel_name: str, limit: int = 3
) -> None:
    """Print a compact summary of the latest video insights for a channel."""
    videos_dir = config.videos_dir(topic, channel_name)
    if not videos_dir.exists():
        return
    vid_list = []
    for vid_dir in videos_dir.iterdir():
        if not vid_dir.is_dir():
            continue
        meta_file = vid_dir / "metadata.json"
        insights_file = vid_dir / "insights.md"
        if not meta_file.exists() or not insights_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            meta["_dir"] = vid_dir
            vid_list.append(meta)
        except (OSError, json.JSONDecodeError):
            continue
    if not vid_list:
        return
    vid_list.sort(key=lambda v: v.get("upload_date", ""), reverse=True)
    selected = vid_list[:limit]

    console.print(f"\n  [bold]Latest from {channel_name}[/bold]\n")
    for i, meta in enumerate(selected, 1):
        title = meta.get("title", "Unknown")
        date = _format_date(meta.get("upload_date", ""))
        vid_dir = meta["_dir"]
        insights_file = vid_dir / "insights.md"
        content = insights_file.read_text(encoding="utf-8")
        # Strip frontmatter
        content = _strip_frontmatter(content)
        # Extract just the Summary section
        summary_text = ""
        in_summary = False
        for line in content.split("\n"):
            if line.strip().lower().startswith("## summary") or line.strip().lower().startswith(
                "## quick take"
            ):
                in_summary = True
                continue
            if in_summary and line.strip().startswith("## "):
                break
            if in_summary:
                summary_text += line + "\n"
        summary_text = summary_text.strip()
        if not summary_text:
            # Fallback: first non-empty paragraph
            for line in content.split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    summary_text = line
                    break
        # Truncate if too long
        if len(summary_text) > 300:
            summary_text = summary_text[:297] + "..."

        console.print(f"  [bold]{i}. {title}[/bold]")
        console.print(f"  [dim]{date}[/dim]")
        console.print(f"  {summary_text}\n")

    console.print(f"  [dim]distill show {channel_name}                     Full insights[/dim]")
    console.print(f"  [dim]distill synthesis {channel_name}                Synthesis[/dim]\n")


def _file_link(path: Path) -> str:
    """Return a clickable file:// link for terminals that support it."""
    resolved = path.resolve()
    # file:// URI with forward slashes
    uri = resolved.as_uri() if hasattr(resolved, "as_uri") else f"file:///{resolved}"
    # Rich hyperlink: clickable text in supporting terminals, plain path elsewhere
    return f"[link={uri}]{resolved}[/link]"


def _resolve_video_channel_name(url: str, video_info) -> str:
    return _shared_resolve_video_channel_name(url, video_info, resolve_channel_name)


def _ensure_channel_context(
    topic: str,
    channel_name: str,
    videos: list,
    config: DistillConfig,
    tracker: CostTracker,
) -> None:
    cli_shared.generate_channel_context = generate_channel_context
    cli_shared.console = console
    return cli_shared.ensure_channel_context(topic, channel_name, videos, config, tracker)


def _process_video(
    topic: str,
    channel_name: str,
    video,
    config: DistillConfig,
    tracker: CostTracker,
    summary: RunSummary,
    state: ChannelState | None = None,
    analysis_mode: str = "auto",
    custom_instructions: str = "",
    eta: ETATracker | None = None,
) -> bool:
    cli_shared.analyze_short = analyze_short
    cli_shared.analyze_video = analyze_video
    cli_shared.analyze_scan = analyze_scan
    cli_shared.get_transcript = get_transcript
    cli_shared.console = console
    return cli_shared.process_video(
        topic,
        channel_name,
        video,
        config,
        tracker,
        summary,
        state=state,
        analysis_mode=analysis_mode,
        custom_instructions=custom_instructions,
        eta=eta,
    )


def _run_scope_report(
    topic: str,
    config: DistillConfig,
    tracker: CostTracker,
    scope: str,
    channel_name: str | None = None,
    test: bool = False,
    summary: RunSummary | None = None,
    focus: str | None = None,
) -> None:
    cli_shared.console = console
    return cli_shared.run_scope_report(
        topic,
        config,
        tracker,
        scope,
        channel_name=channel_name,
        test=test,
        summary=summary,
        focus=focus,
    )


def _get_version() -> str:
    """Get package version from metadata."""
    try:
        from importlib.metadata import version

        return version("distill")
    except Exception:
        return "dev"


def _truncate_channel_list(names: list[str], max_width: int, extra_count: int = 0) -> str:
    """Build a comma-separated channel list that fits within max_width."""
    if not names:
        return ""
    result = names[0]
    shown = 1
    for name in names[1:]:
        candidate = result + ", " + name
        if len(candidate) > max_width:
            break
        result = candidate
        shown += 1
    remaining = len(names) - shown + extra_count
    if remaining > 0:
        result += f" +{remaining} more"
    return result


def _load_recent_cost_runs(log_file: Path, limit: int = 5) -> list[dict]:
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


def _load_all_cost_runs(log_file: Path) -> list[dict]:
    return _load_recent_cost_runs(log_file, limit=10000)


def _load_latest_run_payload(log_dir: Path) -> dict:
    latest = log_dir / "latest_run.json"
    if not latest.exists():
        return {}
    try:
        return json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _estimated_topic_watch_sweep(topic_watchlist) -> float:
    total = 0.0
    for entry in topic_watchlist:
        total += entry.limit * 0.006
        if entry.report:
            total += 2.55
    return total


def _estimate_topic_watch_cost(entry) -> float:
    total = entry.limit * 0.006
    if entry.report:
        total += 2.55
    return total


def _topic_spend_last_days(entries: list[dict], topic: str, days: int = 30) -> float:
    cutoff = datetime.now() - timedelta(days=days)
    total = 0.0
    for entry in entries:
        metadata = entry.get("metadata") or {}
        if metadata.get("topic") != topic:
            continue
        ts = _parse_run_datetime(str(entry.get("timestamp", "")))
        if ts is None or ts < cutoff:
            continue
        try:
            total += float(entry.get("actual_cost") or 0.0)
        except (TypeError, ValueError):
            continue
    return total


def _topic_recent_costs(entries: list[dict], topic: str, limit: int = 5) -> list[float]:
    values: list[tuple[datetime, float]] = []
    for entry in entries:
        metadata = entry.get("metadata") or {}
        if metadata.get("topic") != topic:
            continue
        ts = _parse_run_datetime(str(entry.get("timestamp", "")))
        if ts is None:
            continue
        try:
            cost = float(entry.get("actual_cost") or 0.0)
        except (TypeError, ValueError):
            continue
        values.append((ts, cost))
    values.sort(key=lambda item: item[0], reverse=True)
    return [cost for _, cost in values[:limit]]


def _topic_watch_budget_messages(entry, all_cost_entries: list[dict]) -> list[str]:
    messages: list[str] = []
    projected = _estimate_topic_watch_cost(entry)
    if entry.max_run_cost and projected > entry.max_run_cost:
        messages.append(
            f"{entry.name} projected ${projected:.2f} exceeds max-run budget ${entry.max_run_cost:.2f}"
        )
    if entry.monthly_budget:
        monthly_spend = _topic_spend_last_days(all_cost_entries, entry.topic, days=30)
        if monthly_spend + projected > entry.monthly_budget:
            messages.append(
                f"{entry.name} projected monthly spend ${monthly_spend + projected:.2f} exceeds monthly budget ${entry.monthly_budget:.2f}"
            )
    recent_costs = _topic_recent_costs(all_cost_entries, entry.topic, limit=4)
    if len(recent_costs) >= 2:
        baseline = sum(recent_costs[1:]) / max(len(recent_costs) - 1, 1)
        latest = recent_costs[0]
        if baseline > 0 and latest >= baseline * 2.5:
            messages.append(
                f"{entry.topic} spend spike: latest ${latest:.2f} vs recent baseline ${baseline:.2f}"
            )
    return messages


def _entry_source_type(entry: dict) -> str:
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


def _topic_cost_rollups(
    entries: list[dict], days: int = 30, limit: int = 5
) -> list[tuple[str, float, int]]:
    cutoff = datetime.now() - timedelta(days=days)
    rollups: dict[str, dict[str, float | int]] = {}
    for entry in entries:
        ts = _parse_run_datetime(str(entry.get("timestamp", "")))
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


def _source_cost_rollups(entries: list[dict], days: int = 30) -> list[tuple[str, float, int]]:
    cutoff = datetime.now() - timedelta(days=days)
    rollups: dict[str, dict[str, float | int]] = {}
    for entry in entries:
        ts = _parse_run_datetime(str(entry.get("timestamp", "")))
        if ts is None or ts < cutoff:
            continue
        source_type = _entry_source_type(entry)
        bucket = rollups.setdefault(source_type, {"cost": 0.0, "runs": 0})
        try:
            bucket["cost"] += float(entry.get("actual_cost") or 0.0)
        except (TypeError, ValueError):
            continue
        bucket["runs"] += 1
    items = [(source, float(data["cost"]), int(data["runs"])) for source, data in rollups.items()]
    items.sort(key=lambda item: item[1], reverse=True)
    return items


def _count_site_corpus(config: DistillConfig, topics: list[str]) -> tuple[int, int]:
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


def _count_paper_corpus(config: DistillConfig, topics: list[str]) -> int:
    total = 0
    for topic in topics:
        papers_dir = config.papers_dir(topic)
        if not papers_dir.exists():
            continue
        for paper_dir in papers_dir.iterdir():
            if paper_dir.is_dir() and (paper_dir / "paper.md").exists():
                total += 1
    return total


def _count_topic_outputs(config: DistillConfig, topics: list[str]) -> tuple[int, int, int]:
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


def _load_site_manifest(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _build_site_section_state(pages) -> list[dict]:
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


def _site_section_change_summary(previous: dict, current_sections: list[dict]) -> list[str]:
    previous_sections = {
        item.get("section", ""): item
        for item in previous.get("sections", [])
        if isinstance(item, dict) and item.get("section")
    }
    messages: list[str] = []
    for item in current_sections:
        name = item["section"]
        prev = previous_sections.get(name)
        if prev is None:
            messages.append(f"{name} added ({item['page_count']} pages)")
            continue
        prev_urls = set(prev.get("urls", []))
        curr_urls = set(item.get("urls", []))
        if curr_urls != prev_urls:
            added = len(curr_urls - prev_urls)
            removed = len(prev_urls - curr_urls)
            bits = []
            if added:
                bits.append(f"+{added}")
            if removed:
                bits.append(f"-{removed}")
            messages.append(f"{name} changed ({', '.join(bits)})")
    for name, prev in previous_sections.items():
        if name not in {item["section"] for item in current_sections}:
            messages.append(f"{name} missing (was {prev.get('page_count', 0)} pages)")
    return messages[:8]


def _content_hash(text: str) -> str:
    # SHA-1 used for change-detection/deduplication only, not security.
    return sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()


def _sum_recent_cost(entries: list[dict]) -> float:
    total = 0.0
    for entry in entries:
        try:
            total += float(entry.get("actual_cost") or 0)
        except (TypeError, ValueError):
            continue
    return total


def _dashboard_metric(label: str, value: str, note: str = "") -> Panel:
    body = f"[bold]{value}[/bold]"
    if note:
        body += f"\n[dim]{note}[/dim]"
    return Panel(body, title=label, border_style="dim", padding=(0, 1))


def _format_run_timestamp(value: str) -> str:
    if not value:
        return "unknown"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime("%b %d %I:%M %p")
    except ValueError:
        return value


def _parse_run_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except ValueError:
        return None


def _collect_recent_artifacts(
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


def _collect_stale_topic_watches(topic_watchlist) -> list[str]:
    stale = []
    now = datetime.now()
    for entry in topic_watchlist:
        if not entry.last_run_at:
            stale.append(f"{entry.name} has never run")
            continue
        last = _parse_run_datetime(entry.last_run_at)
        if last is None:
            stale.append(f"{entry.name} has invalid last-run state")
            continue
        max_age_days = 2 if entry.cadence == "daily" else 8
        if (now - last).days >= max_age_days:
            stale.append(f"{entry.name} is stale for its {entry.cadence} cadence")
    return stale


def _collect_corpus_health_warnings(
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
                duration = int(metadata.get("duration") or 0)

                transcript_path = video_dir / "transcript.txt"
                if transcript_path.exists():
                    try:
                        transcript_len = len(transcript_path.read_text(encoding="utf-8").strip())
                    except OSError:
                        transcript_len = 0
                    if duration >= 1800 and transcript_len < 500:
                        warnings.append(
                            f"{topic} / {channel.name}: {title} transcript looks thin ({transcript_len} chars for {_duration_str(duration)})"
                        )
                        if len(warnings) >= limit:
                            return warnings

                insights_path = video_dir / "insights.md"
                if insights_path.exists():
                    try:
                        insight_len = len(
                            _strip_frontmatter(insights_path.read_text(encoding="utf-8")).strip()
                        )
                    except OSError:
                        insight_len = 0
                    if insight_len and insight_len < 250:
                        warnings.append(
                            f"{topic} / {channel.name}: {title} insights look thin ({insight_len} chars)"
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
                    last_crawled_at = _parse_run_datetime(str(section.get("last_crawled_at", "")))
                    if last_crawled_at and last_crawled_at < site_section_cutoff:
                        warnings.append(
                            f"{topic} / {site_dir.name}: section {section.get('section', 'unknown')} is stale ({(datetime.now() - last_crawled_at).days}d old)"
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
                                _strip_frontmatter(
                                    insights_path.read_text(encoding="utf-8")
                                ).strip()
                            )
                        except OSError:
                            insight_len = 0
                        if insight_len and insight_len < 200:
                            warnings.append(
                                f"{topic} / {site_dir.name}: {title} page insights look thin ({insight_len} chars)"
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
                            _strip_frontmatter(insights_path.read_text(encoding="utf-8")).strip()
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


def _collect_topic_changes(
    config: DistillConfig, lib: Library, topics: list[str], topic_watchlist, limit: int = 6
) -> list[tuple[str, str]]:
    now = datetime.now()
    watch_baselines: dict[str, datetime | None] = {}
    for entry in topic_watchlist:
        parsed = _parse_run_datetime(entry.last_run_at)
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
            changes.append((last_change, topic, " · ".join(parts)))
        elif topic in watch_baselines:
            changes.append(
                (baseline, topic, f"quiet since {_format_run_timestamp(baseline.isoformat())}")
            )

    changes.sort(key=lambda item: item[0], reverse=True)
    return [(topic, summary) for _, topic, summary in changes[:limit]]


def _read_json_file(path_obj: Path) -> dict:
    try:
        return json.loads(path_obj.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _topic_change_history_path(config: DistillConfig, topic: str) -> Path:
    return config.topic_dir(topic) / "change_history.jsonl"


def _topic_diff_output_path(config: DistillConfig, topic: str) -> Path:
    return config.topic_dir(topic) / "topic_diff.md"


def _topic_trends_output_path(config: DistillConfig, topic: str) -> Path:
    return config.topic_dir(topic) / "topic_trends.md"


def _watch_alerts_output_path(config: DistillConfig) -> Path:
    return config.library_dir / "watch_alerts.md"


def _relative_library_path(config: DistillConfig, path_obj: Path) -> str:
    try:
        return str(path_obj.resolve().relative_to(config.library_dir.resolve()))
    except ValueError:
        return str(path_obj.resolve())


def _collect_topic_change_details(
    config: DistillConfig,
    lib: Library,
    topic: str,
    baseline: datetime | None,
) -> dict[str, object]:
    now = datetime.now()
    effective_baseline = baseline or (now - timedelta(days=7))

    new_videos: list[dict[str, object]] = []
    new_pages: list[dict[str, object]] = []
    new_papers: list[dict[str, object]] = []
    refreshed_outputs: list[dict[str, object]] = []
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
            insight_path = video_dir / "insights.md"
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
                    "title": meta.get("title", video_dir.name),
                    "channel": ch.name,
                    "upload_date": meta.get("upload_date", ""),
                    "changed_at": changed_at,
                    "path": insight_path,
                }
            )
            mark_change(changed_at)

        synth_path = config.channel_dir(topic, ch.name) / "synthesis.md"
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
                    content_path = page_dir / "content.md"
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
                            "title": meta.get("title", page_dir.name),
                            "site": site_dir.name,
                            "url": meta.get("url", ""),
                            "changed_at": changed_at,
                            "path": content_path,
                        }
                    )
                    mark_change(changed_at)

            site_synth = site_dir / "synthesis.md"
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
            insights_path = paper_dir / "insights.md"
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
                    "title": meta.get("title", paper_dir.name),
                    "paper_id": meta.get("paper_id", ""),
                    "changed_at": changed_at,
                    "path": insights_path,
                }
            )
            mark_change(changed_at)

    topic_dir = config.topic_dir(topic)
    for label, filename in (
        ("topic synthesis", "topic_synthesis.md"),
        ("paper synthesis", "paper_synthesis.md"),
        ("corpus synthesis", "corpus_synthesis.md"),
        ("brief", "brief.md"),
        ("report", "report.md"),
        ("watch update", "watch_update.md"),
    ):
        path_obj = topic_dir / filename
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
        parts = []
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


def _topic_change_snapshot(
    config: DistillConfig, lib: Library, topic: str, baseline: datetime | None
) -> tuple[datetime | None, str]:
    details = _collect_topic_change_details(config, lib, topic, baseline)
    return details.get("last_change"), str(details.get("summary", "no recent change detected"))


def _render_topic_diff_markdown(
    config: DistillConfig,
    *,
    title: str,
    topic: str,
    summary: str,
    baseline: datetime | None,
    effective_baseline: datetime,
    generated_at: datetime,
    new_videos: list[dict[str, object]],
    new_pages: list[dict[str, object]],
    new_papers: list[dict[str, object]],
    refreshed_outputs: list[dict[str, object]],
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

    def append_section(header: str, items: list[dict[str, object]], formatter) -> None:
        if not items:
            return
        lines.extend([f"## {header}", ""])
        for item in items[:limit]:
            rendered = formatter(item)
            lines.extend(rendered.splitlines())
        remaining = len(items) - limit
        if remaining > 0:
            lines.append(f"- ...and {remaining} more")
        lines.append("")

    append_section(
        "New Video Insights",
        new_videos,
        lambda item: (
            f"- `{item['channel']}` — {item['title']}"
            f" ({_format_date(str(item.get('upload_date') or ''))}; changed {_format_run_timestamp(item['changed_at'].isoformat())})"
            f"  [`{_relative_library_path(config, item['path'])}`]"
        ),
    )
    append_section(
        "New Website Pages",
        new_pages,
        lambda item: "\n".join(
            [
                f"- `{item['site']}` — {item['title']} ({_format_run_timestamp(item['changed_at'].isoformat())})",
                *([f"  URL: {item['url']}"] if item.get("url") else []),
                f"  Path: `{_relative_library_path(config, item['path'])}`",
            ]
        ),
    )
    append_section(
        "New Paper Insights",
        new_papers,
        lambda item: (
            f"- {item['title']}"
            + (f" (`{item['paper_id']}`)" if item.get("paper_id") else "")
            + f" ({_format_run_timestamp(item['changed_at'].isoformat())})"
            + f"  [`{_relative_library_path(config, item['path'])}`]"
        ),
    )
    append_section(
        "Refreshed Outputs",
        refreshed_outputs,
        lambda item: (
            f"- {item['label']} ({_format_run_timestamp(item['changed_at'].isoformat())})"
            f"  [`{_relative_library_path(config, item['path'])}`]"
        ),
    )

    if not new_videos and not new_pages and not new_papers and not refreshed_outputs:
        lines.extend(["## Details", "", "- No new artifacts crossed the comparison window.", ""])

    return "\n".join(lines)


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
    new_videos: list[dict[str, object]],
    new_pages: list[dict[str, object]],
    new_papers: list[dict[str, object]],
    refreshed_outputs: list[dict[str, object]],
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
    with history_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")
    return history_path


def _load_topic_change_history(config: DistillConfig, topic: str) -> list[dict[str, object]]:
    history_path = _topic_change_history_path(config, topic)
    if not history_path.exists():
        return []

    records: list[dict[str, object]] = []
    for line in history_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        generated_at = _parse_run_datetime(str(payload.get("generated_at", "")))
        if generated_at is None:
            continue
        counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
        records.append(
            {
                "generated_at": generated_at,
                "topic": payload.get("topic", topic),
                "watch_name": payload.get("watch_name", "") or "",
                "query": payload.get("query", "") or "",
                "cadence": payload.get("cadence", "") or "",
                "baseline": payload.get("baseline", "") or "",
                "summary": payload.get("summary", "") or "",
                "counts": {
                    "videos": int(counts.get("videos", 0) or 0),
                    "pages": int(counts.get("pages", 0) or 0),
                    "papers": int(counts.get("papers", 0) or 0),
                    "outputs": int(counts.get("outputs", 0) or 0),
                },
            }
        )
    records.sort(key=lambda item: item["generated_at"], reverse=True)
    return records


def _topic_trend_direction(records: list[dict[str, object]]) -> str:
    if len(records) < 2:
        return "not enough history yet"
    latest = sum(int(v) for v in records[0]["counts"].values())
    previous = sum(int(v) for v in records[1]["counts"].values())
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


def _topic_watch_alert_lines(
    *,
    watch_name: str,
    topic: str,
    ranking_label: str,
    summary: str,
    change_details: dict[str, object],
    trend_label: str | None,
) -> list[str]:
    counts = {
        "videos": len(list(change_details.get("new_videos", []))),
        "pages": len(list(change_details.get("new_pages", []))),
        "papers": len(list(change_details.get("new_papers", []))),
        "outputs": len(list(change_details.get("refreshed_outputs", []))),
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


def _write_watch_alert_digest(
    config: DistillConfig,
    *,
    generated_at: datetime,
    alert_lines: list[str],
) -> Path:
    output_path = _watch_alerts_output_path(config)
    output_path.parent.mkdir(parents=True, exist_ok=True)
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
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def _render_topic_trends_markdown(
    config: DistillConfig,
    *,
    topic: str,
    records: list[dict[str, object]],
    generated_at: datetime,
    limit: int,
) -> str:
    selected = records[:limit]
    total_video = sum(int(item["counts"].get("videos", 0)) for item in selected)
    total_pages = sum(int(item["counts"].get("pages", 0)) for item in selected)
    total_papers = sum(int(item["counts"].get("papers", 0)) for item in selected)
    total_outputs = sum(int(item["counts"].get("outputs", 0)) for item in selected)
    active_windows = sum(1 for item in selected if sum(int(v) for v in item["counts"].values()) > 0)
    primary_watch = next((item["watch_name"] for item in selected if item.get("watch_name")), "")

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
            f"- `{changed_at}` — {item['summary'] or ', '.join(count_bits) or 'no recorded change'}"
        )
        if item.get("watch_name"):
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


def _write_topic_change_briefing(
    config: DistillConfig,
    *,
    watch_name: str,
    topic: str,
    query: str,
    cadence: str,
    baseline: datetime | None,
    summary: str,
    change_details: dict[str, object] | None = None,
) -> Path:
    details = change_details or _collect_topic_change_details(
        config,
        Library(config),
        topic,
        baseline,
    )
    generated_at = details.get("generated_at") or datetime.now()
    effective_baseline = details.get("effective_baseline") or (baseline or generated_at)
    new_videos = list(details.get("new_videos", []))
    new_pages = list(details.get("new_pages", []))
    new_papers = list(details.get("new_papers", []))
    refreshed_outputs = list(details.get("refreshed_outputs", []))

    topic_dir = config.topic_dir(topic)
    topic_dir.mkdir(parents=True, exist_ok=True)
    briefing_path = topic_dir / "watch_update.md"
    briefing_path.write_text(
        _render_topic_diff_markdown(
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
        ),
        encoding="utf-8",
    )

    diff_path = _topic_diff_output_path(config, topic)
    diff_path.write_text(
        _render_topic_diff_markdown(
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
        ),
        encoding="utf-8",
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

    latest_path = config.library_dir / "latest_changes.md"
    existing = latest_path.read_text(encoding="utf-8") if latest_path.exists() else ""
    entry = (
        f"## {watch_name}\n"
        f"- Topic: `{topic}`\n"
        f"- Generated: `{generated_at.isoformat(timespec='seconds')}`\n"
        f"- Summary: {summary}\n"
        f"- Diff: `{diff_path}`\n"
        f"- History: `{history_path}`\n"
        f"- File: `{briefing_path}`\n\n"
    )
    latest_path.write_text(entry + existing, encoding="utf-8")
    return briefing_path


def _resolve_topic_diff_baseline(
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
            key=lambda e: _parse_run_datetime(e.last_run_at) or datetime.min, reverse=True
        )
        entry = matching[0]
        return _parse_run_datetime(entry.last_run_at), entry.name, entry.query, entry.cadence

    return datetime.now() - timedelta(days=days), None, None, None


def _build_start_here_table() -> Table:
    table = Table.grid(expand=True)
    table.add_column(style="bold cyan", width=23)
    table.add_column()
    table.add_row("Have one YouTube URL?", 'distill video "https://www.youtube.com/watch?v=..."')
    table.add_row(
        "Have one website URL?",
        "distill site https://example.com/page --topic scratch --seed-only",
    )
    table.add_row(
        "Have one paper URL?",
        "distill paper https://arxiv.org/abs/2602.12670 --topic papers",
    )
    table.add_row(
        "Need latest on a topic?",
        'distill latest "Microsoft AI news" --topic microsoft-news',
    )
    table.add_row(
        "Want recurring updates?",
        'distill monitor "Microsoft AI news" --topic microsoft-news',
    )
    return table


def _show_first_run_home(version: str, help_hint: str = "distill --help for all commands") -> None:
    console.print(f"  [dim]v{version}[/dim]  ·  [bold]Distill Start[/bold]")
    console.print("  [dim]Distill one thing first. Build the library later.[/dim]")
    console.print()
    console.print(
        Panel(
            _build_start_here_table(),
            title="Pick A Starting Point",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )
    console.print()

    notes = Table.grid(expand=True)
    notes.add_column(style="bold cyan", width=14)
    notes.add_column()
    notes.add_row("What happens", "Each command saves artifacts into your library for reuse later.")
    notes.add_row(
        "Use --topic", "Choose where the output gets filed. Default topic: [bold]ai[/bold]."
    )
    notes.add_row(
        "Then",
        "Open the generated files, run [bold]distill videos <topic>[/bold], or generate synthesis/report later.",
    )
    console.print(Panel(notes, title="How Distill Works", border_style="green", box=box.ROUNDED))
    console.print()
    console.print(f"  [dim]{help_hint}[/dim]")


def _show_dashboard():
    """Show an operational home screen when running `distill` with no arguments."""
    version = _get_version()

    try:
        config = get_config()
    except Exception:
        _show_first_run_home(version)
        return

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

    site_count, page_count = _count_site_corpus(config, topics)
    paper_count = _count_paper_corpus(config, topics)
    report_count, brief_count, synthesis_count = _count_topic_outputs(config, topics)
    all_cost_entries = _load_all_cost_runs(config.library_dir / "cost_log.jsonl")
    recent_runs = all_cost_entries[-6:]
    recent_spend = _sum_recent_cost(recent_runs)
    latest_run = _load_latest_run_payload(config.library_dir)
    latest_results = latest_run.get("results", {}) if latest_run else {}
    latest_issues = latest_run.get("issues", []) if latest_run else []
    recent_artifacts = _collect_recent_artifacts(config, topics, limit=6)
    topic_changes = _collect_topic_changes(config, lib, topics, topic_watchlist, limit=6)
    stale_topic_watches = _collect_stale_topic_watches(topic_watchlist)
    corpus_health_warnings = _collect_corpus_health_warnings(config, lib, topics, limit=6)
    next_sweep_cost = _estimated_topic_watch_sweep(topic_watchlist)
    due_topic_watches = len(stale_topic_watches)
    topic_spend_rollups = _topic_cost_rollups(all_cost_entries, days=30, limit=4)
    source_spend_rollups = _source_cost_rollups(all_cost_entries, days=30)
    budget_messages = []
    for entry in topic_watchlist:
        budget_messages.extend(_topic_watch_budget_messages(entry, all_cost_entries))

    is_first_run = not any(
        [
            topics,
            watchlist,
            topic_watchlist,
            total_videos,
            site_count,
            paper_count,
            all_cost_entries,
        ]
    )
    if is_first_run:
        _show_first_run_home(version)
        return

    console.print(
        f"  [dim]v{version}[/dim]  ·  [bold]Distill Home[/bold]  "
        f"[dim]stay current / learn fast / build corpus[/dim]"
    )
    console.print(
        '  [dim]Quick commands: distill video "https://www.youtube.com/watch?v=..."  |  '
        'distill latest "Microsoft AI news" --topic microsoft-news  |  distill --help[/dim]'
    )
    console.print()

    overview_cards = [
        _dashboard_metric("Topics", str(len(topics)), "tracked research buckets"),
        _dashboard_metric("Channels", str(total_channels), "YouTube sources in corpus"),
        _dashboard_metric(
            "Videos",
            str(total_videos),
            f"{full_videos} full / {scan_videos} scan"
            if total_videos
            else "no analyzed videos yet",
        ),
        _dashboard_metric(
            "Sites",
            str(site_count),
            f"{page_count} captured pages" if page_count else "no site pages captured",
        ),
        _dashboard_metric("Papers", str(paper_count), "captured paper records"),
        _dashboard_metric("Channel Watch", str(len(watchlist)), "recurring creator monitoring"),
        _dashboard_metric("Topic Watch", str(len(topic_watchlist)), "recurring topic monitoring"),
        _dashboard_metric(
            "Recent Spend",
            f"${recent_spend:.2f}",
            f"last {len(recent_runs)} run{'s' if len(recent_runs) != 1 else ''}"
            if recent_runs
            else "no cost log yet",
        ),
        _dashboard_metric(
            "Next Sweep",
            f"${next_sweep_cost:.2f}",
            "topic-watch estimate" if topic_watchlist else "add topic watches to estimate",
        ),
    ]
    console.print(Columns(overview_cards, equal=True, expand=True))
    console.print()

    stay_current = Table.grid(expand=True)
    stay_current.add_column(style="bold cyan", width=14)
    stay_current.add_column()
    if topics:
        topic_lines = []
        for topic in topics[:6]:
            ch_count = len(lib.get_channels(topic))
            topic_lines.append(
                f"{topic} [dim]({ch_count} channel{'s' if ch_count != 1 else ''})[/dim]"
            )
        if len(topics) > 6:
            topic_lines.append(f"[dim]+{len(topics) - 6} more[/dim]")
        stay_current.add_row("Topics", "\n".join(topic_lines))
    else:
        stay_current.add_row("Topics", "[dim]No topics yet[/dim]")
    if watchlist:
        channel_lines = []
        for entry in watchlist[:5]:
            suffix = " / custom" if entry.instructions else ""
            channel_lines.append(f"{entry.name} [dim]{entry.topic} / {entry.days}d{suffix}[/dim]")
        if len(watchlist) > 5:
            channel_lines.append(f"[dim]+{len(watchlist) - 5} more[/dim]")
        stay_current.add_row("Channel Watch", "\n".join(channel_lines))
    else:
        stay_current.add_row("Channel Watch", "[dim]No channel watches configured[/dim]")
    if topic_watchlist:
        topic_watch_lines = []
        for entry in topic_watchlist[:5]:
            mode = "report" if entry.report else "learn"
            ranking_label = _topic_watch_ranking_strategy(entry.ranking_mode)["label"]
            trend_label = _topic_trend_label(config, entry.topic)
            last = (
                f" / last {_format_run_timestamp(entry.last_run_at)}" if entry.last_run_at else ""
            )
            budget_bits = []
            if entry.max_run_cost:
                budget_bits.append(f"max ${entry.max_run_cost:.2f}/run")
            if entry.monthly_budget:
                budget_bits.append(f"${entry.monthly_budget:.2f}/30d")
            if entry.paused:
                budget_bits.append("paused")
            budget_suffix = f" / {', '.join(budget_bits)}" if budget_bits else ""
            trend_suffix = f" / {trend_label}" if trend_label else ""
            topic_watch_lines.append(
                f"{entry.name} [dim]{entry.topic} / {entry.cadence} / {entry.days}d / {entry.limit} picks / {ranking_label} / {mode}{budget_suffix}{last}{trend_suffix}[/dim]"
            )
        if len(topic_watchlist) > 5:
            topic_watch_lines.append(f"[dim]+{len(topic_watchlist) - 5} more[/dim]")
        stay_current.add_row("Topic Watch", "\n".join(topic_watch_lines))
    else:
        stay_current.add_row("Topic Watch", "[dim]No topic watches configured[/dim]")
    stay_current.add_row(
        "Run Health",
        (
            f"[bold]{due_topic_watches}[/bold] due topic watch{'es' if due_topic_watches != 1 else ''}"
            if topic_watchlist
            else "[dim]Add topic watches to monitor spaces, not just creators[/dim]"
        ),
    )

    recent = Table.grid(expand=True, padding=(0, 2))
    recent.add_column(style="bold dim", width=16)
    recent.add_column(style="bold dim")
    recent.add_column(style="bold dim", justify="right", width=8)
    recent.add_column(style="bold dim", justify="right", width=9)
    recent.add_row("When", "Command", "Cost", "Time")
    if recent_runs:
        for entry in reversed(recent_runs):
            recent.add_row(
                _format_run_timestamp(entry.get("timestamp", "")),
                str(entry.get("command", "unknown")),
                f"${float(entry.get('actual_cost') or 0):.2f}",
                f"{float(entry.get('elapsed_seconds') or 0):.1f}s",
            )
    else:
        recent.add_row("-", "No runs logged yet", "-", "-")

    changed = Table.grid(expand=True)
    changed.add_column(style="bold cyan", width=14)
    changed.add_column()
    if topic_changes:
        for topic, summary in topic_changes:
            trend_label = _topic_trend_label(config, topic)
            if trend_label:
                summary = f"{summary} [dim]({trend_label})[/dim]"
            changed.add_row(topic, summary)
    elif recent_artifacts:
        for mtime, kind, label in recent_artifacts:
            changed.add_row(kind, f"{label} [dim]{mtime.strftime('%b %d %I:%M %p')}[/dim]")
    else:
        changed.add_row("Artifacts", "[dim]No recent synthesis/report artifacts detected[/dim]")

    learn_fast = Table.grid(expand=True)
    learn_fast.add_column(style="bold cyan", width=14)
    learn_fast.add_column()
    learn_fast.add_row(
        "Outputs",
        (f"{synthesis_count} topic syntheses\n{report_count} reports / {brief_count} briefs"),
    )
    if recent_artifacts:
        top_artifacts = []
        for _mtime, kind, label in recent_artifacts[:4]:
            top_artifacts.append(f"{label} [dim]({kind})[/dim]")
        learn_fast.add_row("Newest Work", "\n".join(top_artifacts))
    else:
        learn_fast.add_row("Newest Work", "[dim]No recent synthesis or reports yet[/dim]")
    if recent_runs:
        last_command = recent_runs[-1].get("command", "unknown")
        last_cost = float(recent_runs[-1].get("actual_cost") or 0)
        learn_fast.add_row("Last Run", f"{last_command} [dim]${last_cost:.2f} actual[/dim]")
    else:
        learn_fast.add_row("Last Run", "[dim]No runs logged yet[/dim]")

    build_corpus = Table.grid(expand=True)
    build_corpus.add_column(style="bold cyan", width=14)
    build_corpus.add_column()
    build_corpus.add_row(
        "Corpus Mix",
        (
            f"{total_videos} video insight{'s' if total_videos != 1 else ''} [dim]({full_videos} full / {scan_videos} scan)[/dim]\n"
            f"{page_count} site page{'s' if page_count != 1 else ''} across {site_count} site{'s' if site_count != 1 else ''}\n"
            f"{paper_count} paper{'s' if paper_count != 1 else ''}"
        ),
    )
    build_corpus.add_row(
        "Coverage",
        (
            f"{len(topics)} topic{'s' if len(topics) != 1 else ''}\n"
            f"{total_channels} channel source{'s' if total_channels != 1 else ''}"
        ),
    )
    build_corpus.add_row(
        "Spend",
        f"[bold]${recent_spend:.2f}[/bold] [dim]recent actual[/dim]\n"
        + (
            f"[bold]~${next_sweep_cost:.2f}[/bold] [dim]next topic-watch sweep[/dim]"
            if topic_watchlist
            else "[dim]No topic-watch spend forecast yet[/dim]"
        ),
    )
    if topic_spend_rollups:
        build_corpus.add_row(
            "Top Spend",
            "\n".join(
                f"{topic} [dim]${cost:.2f} / {runs} run{'s' if runs != 1 else ''}[/dim]"
                for topic, cost, runs in topic_spend_rollups
            ),
        )
    if source_spend_rollups:
        build_corpus.add_row(
            "By Source",
            "\n".join(
                f"{source} [dim]${cost:.2f} / {runs} run{'s' if runs != 1 else ''}[/dim]"
                for source, cost, runs in source_spend_rollups[:4]
            ),
        )

    attention = Table.grid(expand=True)
    attention.add_column(style="bold cyan", width=14)
    attention.add_column()
    if latest_results.get("failed"):
        attention.add_row(
            "Failures",
            f"[yellow]{latest_results.get('failed')} failed video items in latest run[/yellow]",
        )
    if latest_issues:
        attention.add_row(
            "Issues",
            f"[yellow]{len(latest_issues)} persisted run issue{'s' if len(latest_issues) != 1 else ''}[/yellow]",
        )
    if stale_topic_watches:
        for idx, item in enumerate(stale_topic_watches[:3]):
            attention.add_row("Stale" if idx == 0 else "", f"[yellow]{item}[/yellow]")
    if corpus_health_warnings:
        for idx, item in enumerate(corpus_health_warnings[:3]):
            attention.add_row("Corpus" if idx == 0 else "", f"[yellow]{item}[/yellow]")
    if budget_messages:
        for idx, item in enumerate(budget_messages[:3]):
            attention.add_row("Budget" if idx == 0 else "", f"[yellow]{item}[/yellow]")
    if not watchlist and not topic_watchlist:
        attention.add_row("Watch State", "[dim]No recurring watches configured yet[/dim]")
    if attention.row_count == 0:
        attention.add_row(
            "Status", "[green]No immediate issues detected from the latest run logs[/green]"
        )
    attention.add_row(
        "Artifacts", "[dim]library/latest_run.json · library/latest_run_errors.md[/dim]"
    )

    top_row = Columns(
        [
            Panel(stay_current, title="Stay Current", border_style="blue"),
            Panel(learn_fast, title="Learn Fast", border_style="green"),
            Panel(build_corpus, title="Build Corpus", border_style="magenta"),
        ],
        equal=True,
        expand=True,
    )
    bottom_row = Columns(
        [
            Panel(recent, title="Recent Activity", border_style="white"),
            Panel(changed, title="What Changed", border_style="cyan"),
            Panel(attention, title="Needs Attention", border_style="yellow"),
        ],
        equal=True,
        expand=True,
    )
    console.print(top_row)
    console.print()
    console.print(bottom_row)
    console.print()

    if topics:
        primary_topic = topics[0]
        next_actions = [
            ("distill topic-watch run", "Refresh recurring topic watches"),
            ("distill catch-up", "Refresh watched channels with scan analysis"),
            (f"distill run {primary_topic} --refresh", "Resume deep processing for a topic"),
            (f"distill report {primary_topic}", "Build or refresh a deep research report"),
        ]
    else:
        next_actions = [
            (
                'distill latest "Microsoft AI latest news" --topic microsoft-news',
                "Create a fresh stay-current topic",
            ),
            (
                'distill topic-watch add "Microsoft AI news" --topic microsoft-news --cadence daily',
                "Start a recurring topic watch",
            ),
            ("distill watch add https://www.youtube.com/@YourChannel", "Track a creator you trust"),
            (
                "distill site-batch configs/example_seeds.json --topic example --seed-only",
                "Analyze a curated website source set",
            ),
        ]

    actions = Table.grid(expand=True, padding=(0, 2))
    actions.add_column(style="bold dim", width=32)
    actions.add_column(style="bold dim")
    actions.add_row("Next Command", "Why")
    for cmd, why in next_actions:
        actions.add_row(cmd, why)
    console.print(Panel(actions, title="Recommended Next Actions", border_style="cyan"))
    console.print()
    console.print("  [dim]distill --help for all commands[/dim]")


def _collect_topic_bundle_files(config: DistillConfig, topic: str) -> list[Path]:
    topic_dir = config.topic_dir(topic)
    if not topic_dir.exists():
        return []
    files: list[Path] = []
    for path_obj in topic_dir.rglob("*"):
        if not path_obj.is_file():
            continue
        if path_obj.suffix.lower() not in {".md", ".json", ".txt"}:
            continue
        files.append(path_obj)
    files.sort()
    return files


def _topic_bundle_manifest(
    config: DistillConfig, topic: str, export_format: str, files: list[Path]
) -> dict:
    lib = Library(config)
    channels = lib.get_channels(topic)
    site_count, page_count = _count_site_corpus(config, [topic])
    paper_count = _count_paper_corpus(config, [topic])
    report_count, brief_count, synthesis_count = _count_topic_outputs(config, [topic])
    video_count = 0
    for ch in channels:
        videos_dir = config.channel_dir(topic, ch.name) / "videos"
        if not videos_dir.exists():
            continue
        for video_dir in videos_dir.iterdir():
            if video_dir.is_dir() and (video_dir / "insights.md").exists():
                video_count += 1
    return {
        "topic": topic,
        "format": export_format,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_types": {
            "youtube": bool(channels),
            "website": bool(site_count),
            "papers": bool(paper_count),
        },
        "counts": {
            "channels": len(channels),
            "videos": video_count,
            "sites": site_count,
            "pages": page_count,
            "papers": paper_count,
            "topic_syntheses": synthesis_count,
            "briefs": brief_count,
            "reports": report_count,
            "files": len(files),
        },
        "files": [
            {
                "path": str(path_obj.relative_to(config.topic_dir(topic)).as_posix()),
                "bytes": path_obj.stat().st_size,
                "kind": path_obj.suffix.lower().removeprefix("."),
            }
            for path_obj in files
        ],
    }


def _export_topic_bundle(config: DistillConfig, topic: str, export_format: str) -> Path:
    if export_format not in {"deepr", "bundle"}:
        raise typer.BadParameter("--format must be 'deepr' or 'bundle'")
    topic_dir = config.topic_dir(topic)
    if not topic_dir.exists():
        raise typer.Exit(1)
    files = _collect_topic_bundle_files(config, topic)
    if not files:
        raise typer.Exit(1)

    zip_path = _output_path(config, f"corpus-{topic}-{export_format}.zip")
    manifest = _topic_bundle_manifest(config, topic, export_format, files)

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        for path_obj in files:
            arcname = Path(topic) / path_obj.relative_to(topic_dir)
            zf.write(path_obj, arcname=str(arcname.as_posix()))
    return zip_path


def _detect_ramp_source(target: str) -> str:
    target_path = Path(target)
    if target_path.exists():
        return "website-batch"
    lowered = target.lower()
    if "arxiv.org" in lowered:
        return "paper"
    if lowered.startswith("http://") or lowered.startswith("https://"):
        if "youtube.com" in lowered or "youtu.be" in lowered:
            return "youtube-url"
        return "website"
    return "youtube-query"


def _dashboard_snapshot(config: DistillConfig) -> dict:
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

    site_count, page_count = _count_site_corpus(config, topics)
    paper_count = _count_paper_corpus(config, topics)
    report_count, brief_count, synthesis_count = _count_topic_outputs(config, topics)
    all_cost_entries = _load_all_cost_runs(config.library_dir / "cost_log.jsonl")
    recent_runs = all_cost_entries[-6:]
    recent_spend = _sum_recent_cost(recent_runs)
    latest_run = _load_latest_run_payload(config.library_dir)
    latest_results = latest_run.get("results", {}) if latest_run else {}
    latest_issues = latest_run.get("issues", []) if latest_run else []
    recent_artifacts = _collect_recent_artifacts(config, topics, limit=6)
    topic_changes = _collect_topic_changes(config, lib, topics, topic_watchlist, limit=6)
    stale_topic_watches = _collect_stale_topic_watches(topic_watchlist)
    corpus_health_warnings = _collect_corpus_health_warnings(config, lib, topics, limit=8)
    next_sweep_cost = _estimated_topic_watch_sweep(topic_watchlist)
    due_topic_watches = len(stale_topic_watches)
    topic_spend_rollups = _topic_cost_rollups(all_cost_entries, days=30, limit=4)
    source_spend_rollups = _source_cost_rollups(all_cost_entries, days=30)
    budget_messages: list[str] = []
    for entry in topic_watchlist:
        budget_messages.extend(_topic_watch_budget_messages(entry, all_cost_entries))

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
        "stale_topic_watches": stale_topic_watches,
        "corpus_health_warnings": corpus_health_warnings,
        "next_sweep_cost": next_sweep_cost,
        "due_topic_watches": due_topic_watches,
        "topic_spend_rollups": topic_spend_rollups,
        "source_spend_rollups": source_spend_rollups,
        "budget_messages": budget_messages,
    }


def _render_dashboard_html(version: str, snapshot: dict) -> str:
    def list_items(items: list[str]) -> str:
        if not items:
            return "<li>None</li>"
        return "".join(f"<li>{escape(item)}</li>" for item in items)

    metrics = [
        ("Topics", str(len(snapshot["topics"]))),
        ("Channels", str(snapshot["total_channels"])),
        ("Videos", str(snapshot["total_videos"])),
        ("Sites", str(snapshot["site_count"])),
        ("Papers", str(snapshot["paper_count"])),
        ("Recent Spend", f"${snapshot['recent_spend']:.2f}"),
        ("Next Sweep", f"${snapshot['next_sweep_cost']:.2f}"),
    ]
    metric_cards = "".join(
        f"<div class='card metric'><div class='label'>{escape(label)}</div><div class='value'>{escape(value)}</div></div>"
        for label, value in metrics
    )

    topic_lines = [
        f"{topic} ({len(snapshot['lib'].get_channels(topic))} channels)"
        for topic in snapshot["topics"][:8]
    ]
    channel_watch_lines = [
        f"{entry.name} - {entry.topic} / {entry.days}d" for entry in snapshot["watchlist"][:8]
    ]
    topic_watch_lines = []
    for entry in snapshot["topic_watchlist"][:8]:
        bits = [entry.topic, entry.cadence, f"{entry.days}d", f"{entry.limit} picks"]
        if entry.max_run_cost:
            bits.append(f"max ${entry.max_run_cost:.2f}/run")
        if entry.monthly_budget:
            bits.append(f"${entry.monthly_budget:.2f}/30d")
        if entry.paused:
            bits.append("paused")
        trend_label = (snapshot.get("topic_trends") or {}).get(entry.topic)
        if trend_label:
            bits.append(trend_label)
        topic_watch_lines.append(f"{entry.name} - {' / '.join(bits)}")

    recent_rows = (
        "".join(
            "<tr>"
            f"<td>{escape(_format_run_timestamp(entry.get('timestamp', '')))}</td>"
            f"<td>{escape(str(entry.get('command', 'unknown')))}</td>"
            f"<td>${float(entry.get('actual_cost') or 0):.2f}</td>"
            f"<td>{float(entry.get('elapsed_seconds') or 0):.1f}s</td>"
            "</tr>"
            for entry in reversed(snapshot["recent_runs"])
        )
        or "<tr><td>-</td><td>No runs logged yet</td><td>-</td><td>-</td></tr>"
    )

    changed_lines = []
    for topic, summary in snapshot["topic_changes"]:
        trend_label = (snapshot.get("topic_trends") or {}).get(topic)
        if trend_label:
            changed_lines.append(f"{topic}: {summary} ({trend_label})")
        else:
            changed_lines.append(f"{topic}: {summary}")
    if not changed_lines:
        changed_lines = [
            f"{kind}: {label} {mtime.strftime('%b %d %I:%M %p')}"
            for mtime, kind, label in snapshot["recent_artifacts"]
        ]
    attention_lines = []
    if snapshot["latest_results"].get("failed"):
        attention_lines.append(
            f"Latest run failed items: {snapshot['latest_results'].get('failed')}"
        )
    if snapshot["latest_issues"]:
        attention_lines.append(f"Latest run issues: {len(snapshot['latest_issues'])}")
    attention_lines.extend(snapshot["stale_topic_watches"][:5])
    attention_lines.extend(snapshot["corpus_health_warnings"][:5])
    attention_lines.extend(snapshot["budget_messages"][:5])
    if not attention_lines:
        attention_lines = ["No immediate issues detected"]

    topic_spend_lines = [
        f"{topic} - ${cost:.2f} / {runs} runs"
        for topic, cost, runs in snapshot["topic_spend_rollups"]
    ]
    source_spend_lines = [
        f"{source} - ${cost:.2f} / {runs} runs"
        for source, cost, runs in snapshot["source_spend_rollups"]
    ]

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Distill Dashboard</title>
  <style>
    :root {{
      --bg: #f6f2e9;
      --panel: #fffdf8;
      --ink: #1c1f26;
      --muted: #6b7280;
      --line: #d9cfbf;
      --accent: #0f766e;
      --accent2: #b45309;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Georgia, 'Times New Roman', serif; background: linear-gradient(180deg, #f4efe4 0%, var(--bg) 100%); color: var(--ink); }}
    .wrap {{ max-width: 1400px; margin: 0 auto; padding: 28px; }}
    h1 {{ margin: 0; font-size: 2.1rem; }}
    .sub {{ color: var(--muted); margin-top: 8px; }}
    .grid {{ display: grid; gap: 16px; }}
    .metrics {{ grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); margin: 24px 0; }}
    .cols3 {{ grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }}
    .card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 18px; padding: 18px; box-shadow: 0 8px 24px rgba(28,31,38,0.05); }}
    .metric .label {{ font-size: 0.85rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }}
    .metric .value {{ font-size: 2rem; margin-top: 8px; }}
    h2 {{ margin: 0 0 12px 0; font-size: 1.15rem; }}
    ul {{ margin: 0; padding-left: 18px; }}
    li {{ margin: 6px 0; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.95rem; }}
    th, td {{ text-align: left; padding: 10px 8px; border-bottom: 1px solid var(--line); }}
    th {{ color: var(--muted); font-weight: 600; }}
    .footer {{ margin-top: 20px; color: var(--muted); font-size: 0.9rem; }}
    .accent {{ color: var(--accent); }}
    .warn {{ color: var(--accent2); }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Distill Dashboard</h1>
    <div class="sub">v{escape(version)} · stay current / learn fast / build corpus</div>
    <div class="grid metrics">{metric_cards}</div>

    <div class="grid cols3">
      <section class="card">
        <h2>Stay Current</h2>
        <ul>{list_items(topic_lines)}</ul>
        <h2 style="margin-top:16px;">Channel Watches</h2>
        <ul>{list_items(channel_watch_lines)}</ul>
        <h2 style="margin-top:16px;">Topic Watches</h2>
        <ul>{list_items(topic_watch_lines)}</ul>
      </section>

      <section class="card">
        <h2>Learn Fast</h2>
        <ul>
          <li>{snapshot["synthesis_count"]} topic syntheses</li>
          <li>{snapshot["report_count"]} reports / {snapshot["brief_count"]} briefs</li>
          <li>{snapshot["page_count"]} site pages</li>
        </ul>
        <h2 style="margin-top:16px;">What Changed</h2>
        <ul>{list_items(changed_lines)}</ul>
      </section>

      <section class="card">
        <h2>Build Corpus</h2>
        <ul>
          <li>{snapshot["total_videos"]} video insights ({snapshot["full_videos"]} full / {snapshot["scan_videos"]} scan)</li>
          <li>{snapshot["site_count"]} sites / {snapshot["page_count"]} pages</li>
          <li>{len(snapshot["topics"])} topics / {snapshot["total_channels"]} channels</li>
        </ul>
        <h2 style="margin-top:16px;">Top Spend (30d)</h2>
        <ul>{list_items(topic_spend_lines)}</ul>
        <h2 style="margin-top:16px;">By Source (30d)</h2>
        <ul>{list_items(source_spend_lines)}</ul>
      </section>
    </div>

    <div class="grid cols3" style="margin-top:16px;">
      <section class="card" style="grid-column: span 2;">
        <h2>Recent Activity</h2>
        <table>
          <thead><tr><th>When</th><th>Command</th><th>Cost</th><th>Time</th></tr></thead>
          <tbody>{recent_rows}</tbody>
        </table>
      </section>
      <section class="card">
        <h2>Needs Attention</h2>
        <ul>{list_items(attention_lines)}</ul>
      </section>
    </div>

    <div class="footer">
      Source artifacts: <span class="accent">library/latest_run.json</span>,
      <span class="accent">library/latest_run_errors.md</span>,
      <span class="accent">library/latest_changes.md</span>
    </div>
  </div>
</body>
</html>"""


# ─── Power Commands ──────────────────────────────────────────────────


@app.command(rich_help_panel="Process")
def video(
    url: str = typer.Argument(help="YouTube video URL"),
    topic: str = typer.Option("ai", "--topic", "-t", help="Topic to file under"),
    show: bool = typer.Option(
        False,
        "--show",
        help="Print the analysis inline instead of just linking transcript and insights files.",
    ),
):
    """Transcribe and analyze a single YouTube video.

    By default this writes transcript + analysis artifacts and keeps console output concise.
    Use --show to print the analysis inline.
    """
    config = get_config()
    _require_api_key(config.xai_api_key, "XAI_API_KEY required for analysis")

    tracker = CostTracker()
    summary = RunSummary(command="video")

    console.print("\n[bold]Fetching video info...[/bold]")
    info = get_video_info(url)
    if not info:
        summary.add_issue(
            "video-info",
            "Could not get video info. Check the URL.",
            context=url,
            details={"topic": topic},
        )
        display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
        console.print("[red]Could not get video info. Check the URL.[/red]")
        raise typer.Exit(1)

    channel_name = _resolve_video_channel_name(url, info)
    console.print(f"[bold]{info.title}[/bold]")
    console.print(f"[dim]{_format_date(info.upload_date)} | {_duration_str(info.duration)}[/dim]\n")

    success = _process_video(topic, channel_name, info, config, tracker, summary)
    if not success:
        display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
        raise typer.Exit(1)

    video_dir = config.video_dir_slug(topic, channel_name, info.title, info.video_id)
    transcript_file = video_dir / "transcript.txt"
    insights_file = video_dir / "insights.md"

    try:
        console.print(
            Panel(
                _safe_console_text(
                    console,
                    f"[bold]{info.title}[/bold]\n[dim]{_format_date(info.upload_date)} | {channel_name}[/dim]",
                ),
                border_style="cyan",
            )
        )
    except Exception as exc:
        cli_shared.record_exception_issue(
            summary,
            stage="render-preview-panel",
            exc=exc,
            context=info.video_id,
            details={"channel": channel_name, "title": info.title},
            severity="warning",
        )
        _print_text_safely(
            console, f"{info.title}\n{_format_date(info.upload_date)} | {channel_name}"
        )

    if show:
        content = _strip_frontmatter(insights_file.read_text(encoding="utf-8"))
        _print_markdown_safely(
            console,
            content,
            summary=summary,
            stage="render-preview-content",
            context=info.video_id,
            details={"channel": channel_name, "title": info.title},
        )

    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)

    console.print()
    console.print(f"  transcript.txt  {_file_link(transcript_file)}")
    console.print(f"  insights.md    {_file_link(insights_file)}")
    if not show:
        console.print("  [dim]Use --show to print the analysis inline[/dim]")
    console.print(
        f"  [dim]distill synthesis {channel_name}  |  distill videos {channel_name}[/dim]"
    )


@app.command(name="channel", rich_help_panel="Process")
def channel_cmd(
    url: str = typer.Argument(help="YouTube channel URL"),
    topic: str = typer.Option("ai", "--topic", "-t", help="Topic to file under"),
    months: int = typer.Option(None, "--months", "-m", help="Lookback window (default: 3)"),
    report: bool = typer.Option(
        False, "--report", "-r", help="Also generate a full report after processing"
    ),
    limit: int | None = typer.Option(None, "--limit", "-n", help="Max videos to process"),
    shorts: bool = typer.Option(
        True, "--shorts/--no-shorts", help="Include YouTube Shorts (default: yes)"
    ),
    test: bool = typer.Option(False, "--test", help="Test mode for research (cheaper)"),
):
    """Process a full YouTube channel -- discover, transcribe, analyze.

    Adds the channel to your library, discovers recent videos, gets transcripts,
    and runs 2-pass Grok analysis on each. Use --report to also generate a full report.

    Examples:
      distill channel https://www.youtube.com/@NateBJones
      distill channel https://www.youtube.com/@SecurityGuy --topic security --months 6
      distill channel https://www.youtube.com/@NateBJones --report
    """
    config = get_config()
    _require_api_key(config.xai_api_key, "XAI_API_KEY required")

    lookback = months or config.distill_default_months
    name = resolve_channel_name(url)
    console.print(f"\n[bold]Channel: {name}[/bold]")
    console.print(f"[dim]Topic: {topic} | Lookback: {lookback} months[/dim]\n")

    lib = Library(config)
    if lib.add_channel(topic, url, name):
        console.print(f"[green]Added {name} to {topic}[/green]")
    else:
        console.print(f"[dim]{name} already in {topic}[/dim]")

    console.print("Discovering videos...")
    videos = discover_videos(url, lookback, include_shorts=shorts)
    console.print(f"[green]Found {len(videos)} videos[/green]")

    if limit:
        videos = videos[:limit]
        console.print(f"[dim]Limited to {limit} videos[/dim]")

    if not videos:
        console.print("[yellow]No videos found in date range[/yellow]")
        return

    tracker = CostTracker()
    summary = RunSummary(command="channel")
    state = ChannelState(config.channel_dir(topic, name) / "state.json")

    # Pre-run estimate
    new_vids = [v for v in videos if not state.is_processed(v.video_id)]
    if new_vids:
        full_est = sum(1 for v in new_vids if v.duration > SHORTS_THRESHOLD)
        short_est = sum(1 for v in new_vids if v.duration <= SHORTS_THRESHOLD)
        display_estimate(full_est, short_est, console=console, include_report=report)

    _ensure_channel_context(topic, name, videos, config, tracker)
    eta = ETATracker(total=len(new_vids))

    for i, vid in enumerate(videos, 1):
        if state.is_processed(vid.video_id):
            console.print(f"  [{i}/{len(videos)}] [dim]Already done: {vid.title[:60]}[/dim]")
            continue

        eta_hint = f"  [dim]{eta.eta_str}[/dim]" if eta.eta_str else ""
        console.print(f"\n  [{i}/{len(videos)}] [bold]{vid.title}[/bold]")
        console.print(
            f"  [dim]{_format_date(vid.upload_date)} | {_duration_str(vid.duration)}[/dim]{eta_hint}"
        )
        _process_video(topic, name, vid, config, tracker, summary, state=state, eta=eta)

    console.print(f"\nSynthesizing {name}...")
    try:
        synthesize_channel(topic, name, config, tracker=tracker)
        synth_file = config.channel_dir(topic, name) / "synthesis.md"
        if synth_file.exists():
            summary.add_output(synth_file)
        else:
            summary.add_issue(
                "channel-synthesis", "No synthesis output written", context=f"{topic}/{name}"
            )
    except Exception as e:
        console.print(f"[red]Synthesis failed: {e}[/red]")
        summary.add_exception(
            "channel-synthesis",
            e,
            context=f"{topic}/{name}",
            details={"topic": topic, "channel": name},
        )

    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)

    if not report:
        console.print("\n  [dim]What's next:[/dim]")
        console.print(f"  [dim]  distill show {name}                          View insights[/dim]")
        console.print(f"  [dim]  distill synthesis {name}                     Read synthesis[/dim]")
        console.print(
            f"  [dim]  distill report {name}                         Deep research report[/dim]"
        )
        console.print(
            f"  [dim]  distill watch add {videos[0].channel_url if videos and videos[0].channel_url else '<url>'}  Track this channel[/dim]"
        )

    if report:
        _run_scope_report(
            topic,
            config,
            tracker,
            scope="channel",
            channel_name=name,
            test=test,
        )


def _expand_learning_queries(
    query: str,
    config: DistillConfig | None = None,
    tracker: CostTracker | None = None,
    *,
    skeptical: bool = False,
    expand: bool = True,
) -> list[str]:
    query = query.strip()
    if query.startswith("http://") or query.startswith("https://"):
        return [query]

    normalized = " ".join(query.split())
    variants = _heuristic_learning_queries(normalized, skeptical=skeptical)
    if expand and config and config.xai_api_key:
        llm_variants = _llm_expand_learning_queries(
            normalized,
            config,
            tracker=tracker,
            skeptical=skeptical,
        )
        if llm_variants:
            variants = [normalized, *llm_variants, *variants]
    return _dedupe_query_strings(variants)[:6]


def _heuristic_learning_queries(query: str, *, skeptical: bool = False) -> list[str]:
    normalized = " ".join(query.split())
    lowered = normalized.lower()
    variants = [normalized]

    if "best practices" in lowered:
        variants.append(
            _replace_case_insensitive(normalized, "best practices", "architecture best practices")
        )
        variants.append(
            _replace_case_insensitive(normalized, "best practices", "implementation guide")
        )
        variants.append(_replace_case_insensitive(normalized, "best practices", "tutorial"))
    elif "best practice" in lowered:
        variants.append(
            _replace_case_insensitive(normalized, "best practice", "architecture best practices")
        )

    if any(
        term in lowered
        for term in [
            "best practice",
            "best practices",
            "architecture",
            "implementation",
            "guide",
        ]
    ):
        base = _strip_intent_terms(normalized)
        if base and base.lower() != normalized.lower():
            variants.append(f"{base} architecture")
            variants.append(f"{base} implementation")
            variants.append(f"{base} walkthrough")

    if skeptical or _looks_like_rumor_query(normalized):
        base = _strip_noise_terms(normalized) or normalized
        variants.extend(
            [
                f"{base} source code",
                f"{base} sourcemap",
                f"{base} validation",
                f"{base} debunk",
                f"{base} what leaked",
            ]
        )

    return _dedupe_query_strings(variants)


def _llm_expand_learning_queries(
    query: str,
    config: DistillConfig,
    *,
    tracker: CostTracker | None = None,
    skeptical: bool = False,
) -> list[str]:
    client = OpenAI(api_key=config.xai_api_key, base_url=XAI_BASE_URL)
    model = config.xai_model_for("rerank")
    prompt = search_query_expansion_prompt(query, skeptical=skeptical)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=512,
        timeout=90,
    )
    if tracker and response.usage:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.usage.prompt_tokens or 0,
                completion_tokens=response.usage.completion_tokens or 0,
                model=model,
                call_type="search_expand",
            )
        )
    content = response.choices[0].message.content if response.choices else ""
    if not content:
        return []
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    data = json.loads(text)
    queries = data.get("queries", []) if isinstance(data, dict) else []
    return [q.strip() for q in queries if isinstance(q, str) and q.strip()]


def _dedupe_query_strings(queries: list[str]) -> list[str]:
    deduped = []
    seen = set()
    for item in queries:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item.strip())
    return deduped


def _expand_paper_queries(
    query: str,
    config: DistillConfig | None = None,
    tracker: CostTracker | None = None,
    *,
    expand: bool = True,
) -> list[str]:
    """Expand a single arXiv query into a small set of variants.

    Mirrors _expand_learning_queries but with paper-appropriate heuristics.
    Returns at most 6 unique queries, always including the original.
    """
    normalized = " ".join(query.split())
    if not normalized:
        return []
    variants = [normalized]
    if expand and config and config.xai_api_key:
        try:
            llm_variants = _llm_expand_paper_queries(normalized, config, tracker=tracker)
        except Exception as e:
            console.print(f"  [yellow]Query expansion fallback: {e}[/yellow]")
            llm_variants = []
        variants.extend(llm_variants)
    return _dedupe_query_strings(variants)[:6]


def _llm_expand_paper_queries(
    query: str,
    config: DistillConfig,
    *,
    tracker: CostTracker | None = None,
) -> list[str]:
    client = OpenAI(api_key=config.xai_api_key, base_url=XAI_BASE_URL)
    model = config.xai_model_for("rerank")
    prompt = paper_query_expansion_prompt(query)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=512,
        timeout=90,
    )
    if tracker and response.usage:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.usage.prompt_tokens or 0,
                completion_tokens=response.usage.completion_tokens or 0,
                model=model,
                call_type="paper_expand",
            )
        )
    content = response.choices[0].message.content if response.choices else ""
    if not content:
        return []
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    data = json.loads(text)
    queries = data.get("queries", []) if isinstance(data, dict) else []
    return [q.strip() for q in queries if isinstance(q, str) and q.strip()]


def _display_ranked_papers(ranked: list[RankedPaper], title: str) -> None:
    table = Table(title=title, box=box.SIMPLE_HEAVY)
    table.add_column("#", justify="right")
    table.add_column("Title", overflow="fold")
    table.add_column("Authors", overflow="fold")
    table.add_column("Published")
    table.add_column("Categories", overflow="fold")
    table.add_column("Score", justify="right")
    table.add_column("Why", overflow="fold")
    for idx, item in enumerate(ranked, 1):
        authors = ", ".join(item.paper.authors[:2]) if item.paper.authors else "unknown"
        if item.paper.authors and len(item.paper.authors) > 2:
            authors += f" +{len(item.paper.authors) - 2}"
        categories = ", ".join(item.paper.categories[:3]) if item.paper.categories else "-"
        published = (item.paper.published_at or "")[:10] or "-"
        table.add_row(
            str(idx),
            item.paper.title,
            authors,
            published,
            categories,
            f"{item.final_score:.2f}",
            item.rationale,
        )
    console.print(table)


def _replace_case_insensitive(text: str, old: str, new: str) -> str:
    idx = text.lower().find(old.lower())
    if idx < 0:
        return text
    return text[:idx] + new + text[idx + len(old) :]


def _strip_intent_terms(query: str) -> str:
    intent_terms = {
        "best",
        "practice",
        "practices",
        "architecture",
        "implementation",
        "guide",
        "walkthrough",
        "tutorial",
        "how",
        "to",
        "for",
    }
    words = [word for word in query.split() if word.lower() not in intent_terms]
    return " ".join(words).strip()


def _strip_noise_terms(query: str) -> str:
    noise_terms = {
        "analysis",
        "latest",
        "news",
        "rumor",
        "rumour",
        "leak",
        "leaked",
    }
    words = [word for word in query.split() if word.lower() not in noise_terms]
    return " ".join(words).strip()


def _looks_like_rumor_query(query: str) -> bool:
    lowered = query.lower()
    rumor_terms = {
        "leak",
        "leaked",
        "rumor",
        "rumour",
        "source code",
        "hack",
        "breach",
        "exposed",
        "incident",
        "analysis",
    }
    return any(term in lowered for term in rumor_terms)


def _auto_skeptical_mode(query: str, *, hours: int | None, days: int) -> bool:
    now = datetime.now()
    if now.month == 4 and now.day == 1 and (hours is None or hours <= 48 or days <= 2):
        return True
    return _looks_like_rumor_query(query)


def _effective_days(days: int, hours: int | None) -> int:
    if hours is None:
        return days
    return max(days, max(1, (hours + 23) // 24))


def _window_label(days: int, hours: int | None) -> str:
    if hours is not None:
        return f"{hours} hours"
    return f"{days} days"


def _default_report_focus(query: str, *, skeptical: bool) -> str | None:
    if not skeptical:
        return None
    return (
        f"Treat this as a rumor-sensitive topic. Cross-validate creator claims for '{query}' across independent videos and external primary sources. "
        "Separate concrete technical evidence from reaction content, satire, April 1 jokes, and unsupported amplification."
    )


def _filter_recent_candidates(videos: list, days: int, hours: int | None = None) -> list:
    cutoff = (
        datetime.now() - timedelta(hours=hours)
        if hours is not None
        else datetime.now() - timedelta(days=days)
    )
    filtered = []
    for video in videos:
        published_at = getattr(video, "published_at", "")
        if published_at:
            try:
                upload_dt = datetime.fromisoformat(published_at)
            except ValueError:
                upload_dt = None
            if upload_dt is not None:
                if upload_dt >= cutoff:
                    filtered.append(video)
                continue
        if not getattr(video, "upload_date", ""):
            filtered.append(video)
            continue
        try:
            upload_dt = datetime.strptime(video.upload_date, "%Y%m%d")
        except ValueError:
            filtered.append(video)
            continue
        if upload_dt >= cutoff:
            filtered.append(video)
    return filtered


def _dedupe_candidates(videos: list) -> list:
    deduped = []
    seen = set()
    for video in videos:
        if video.video_id in seen:
            continue
        seen.add(video.video_id)
        deduped.append(video)
    return deduped


def _format_metric(value: int) -> str:
    if not value:
        return "-"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def _select_learning_videos(
    query: str,
    config: DistillConfig,
    tracker: CostTracker,
    days: int,
    limit: int,
    sort: str,
    per_channel_cap: int,
    shorts: bool,
    rerank: bool,
    *,
    hours: int | None = None,
    skeptical: bool = False,
    expand: bool = True,
):
    effective_days = _effective_days(days, hours)
    candidate_limit = max(limit * 2, 12)
    raw_candidates = []
    queries = _expand_learning_queries(
        query,
        config,
        tracker,
        skeptical=skeptical,
        expand=expand,
    )
    for idx, variant in enumerate(queries, 1):
        console.print(f"[dim]Candidate search {idx}/{len(queries)}: {variant}[/dim]")
        raw_candidates.extend(
            search_youtube_results(
                variant,
                days=effective_days,
                hours=hours,
                limit=candidate_limit,
            )
        )
    raw_candidates = _dedupe_candidates(raw_candidates)
    if not raw_candidates:
        console.print(
            "[dim]Browser-based search returned no candidates; falling back to yt-dlp search[/dim]"
        )
        raw_candidates = search_videos(
            query,
            days=effective_days,
            limit=candidate_limit,
            sort=sort,
            per_channel_cap=max(per_channel_cap * 2, 4),
        )
    if not shorts:
        raw_candidates = [v for v in raw_candidates if v.duration > SHORTS_THRESHOLD]
        console.print(f"[dim]Filtered to {len(raw_candidates)} full-length candidates[/dim]")

    if not raw_candidates:
        return [], []

    enriched = enrich_videos(raw_candidates, max_videos=min(len(raw_candidates), 12))
    enriched = _filter_recent_candidates(enriched, effective_days, hours=hours)
    ranked = rerank_videos(
        query,
        enriched,
        config,
        tracker=tracker,
        top_n=max(limit * 2, 10),
        use_llm=rerank,
        skeptical=skeptical,
    )
    selected = _apply_ranked_channel_cap(ranked, limit, per_channel_cap)
    return enriched, selected


def _apply_ranked_channel_cap(ranked, limit: int, per_channel_cap: int):
    selected = []
    counts = {}
    for item in ranked:
        channel_key = (item.video.channel_name or "unknown").strip().lower() or "unknown"
        if counts.get(channel_key, 0) >= per_channel_cap:
            continue
        selected.append(item)
        counts[channel_key] = counts.get(channel_key, 0) + 1
        if len(selected) >= limit:
            break
    return selected


def _display_ranked_videos(ranked, title: str):
    table = Table(title=title, box=box.SIMPLE_HEAVY)
    table.add_column("#", justify="right")
    table.add_column("Title", overflow="fold")
    table.add_column("Channel")
    table.add_column("Date")
    table.add_column("Views", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Why", overflow="fold")
    for idx, item in enumerate(ranked, 1):
        table.add_row(
            str(idx),
            item.video.title,
            item.video.channel_name or "unknown",
            _format_date(item.video.upload_date),
            _format_metric(item.video.view_count),
            f"{item.final_score:.2f}",
            item.rationale,
        )
    console.print(table)


@app.command(name="search", rich_help_panel="Discover")
def search_cmd(
    query: str = typer.Argument(help="Topic or question to learn from YouTube"),
    days: int = typer.Option(60, "--days", "-d", help="Recency window in days (default: 60)"),
    hours: int | None = typer.Option(
        None,
        "--hours",
        help="Exact recency window in hours (overrides day precision where possible)",
    ),
    limit: int = typer.Option(
        5, "--limit", "-n", help="How many best-pick videos to show (default: 5)"
    ),
    sort: str = typer.Option(
        "relevance", "--sort", help="Candidate search order: relevance or date"
    ),
    per_channel_cap: int = typer.Option(2, "--channel-cap", help="Max final picks per channel"),
    shorts: bool = typer.Option(
        False, "--shorts/--no-shorts", help="Include short-form videos under 3 minutes"
    ),
    rerank: bool = typer.Option(
        True,
        "--rerank/--no-rerank",
        help="Use LLM reranking to pick the best videos (default: on)",
    ),
):
    """Preview the best recent YouTube videos Distill would learn from."""
    _validate_learning_options(sort, limit, days, per_channel_cap, hours=hours)
    config, _tracker, _selected = _preview_learning_selection(
        query,
        days=days,
        limit=limit,
        sort=sort,
        per_channel_cap=per_channel_cap,
        shorts=shorts,
        rerank=rerank,
        header="Search",
        table_title="Best Videos to Learn From",
        hours=hours,
    )
    if rerank and not config.xai_api_key:
        console.print("[yellow]XAI_API_KEY missing; used deterministic ranking fallback[/yellow]")
    console.print('\n[dim]Run `distill learn "..."` to process these picks.[/dim]')


@app.command(name="explore", rich_help_panel="Discover")
def explore_cmd(
    query: str = typer.Argument(help="Topic or question to explore on YouTube"),
    days: int = typer.Option(90, "--days", "-d", help="Recency window in days (default: 90)"),
    limit: int = typer.Option(
        10, "--limit", "-n", help="How many ranked videos to show (default: 10)"
    ),
    sort: str = typer.Option(
        "relevance", "--sort", help="Candidate search order: relevance or date"
    ),
    per_channel_cap: int = typer.Option(3, "--channel-cap", help="Max final picks per channel"),
    shorts: bool = typer.Option(
        False, "--shorts/--no-shorts", help="Include short-form videos under 3 minutes"
    ),
    rerank: bool = typer.Option(
        True,
        "--rerank/--no-rerank",
        help="Use LLM reranking to pick the best videos (default: on)",
    ),
):
    """Broader preview mode for exploring a topic before processing it."""
    _validate_learning_options(sort, limit, days, per_channel_cap)
    config, _tracker, _selected = _preview_learning_selection(
        query,
        days=days,
        limit=limit,
        sort=sort,
        per_channel_cap=per_channel_cap,
        shorts=shorts,
        rerank=rerank,
        header="Explore",
        table_title="Broader Topic Coverage",
    )
    if rerank and not config.xai_api_key:
        console.print("[yellow]XAI_API_KEY missing; used deterministic ranking fallback[/yellow]")
    console.print(
        '\n[dim]Run `distill latest "..."` or `distill learn "..."` to process the best set.[/dim]'
    )


@app.command(name="learn", rich_help_panel="Discover")
def learn_cmd(
    query: str = typer.Argument(help="Topic or question to learn from YouTube"),
    topic: str | None = typer.Option(
        None, "--topic", "-t", help="Topic to file under (default: derived from query)"
    ),
    days: int = typer.Option(60, "--days", "-d", help="Recency window in days (default: 60)"),
    hours: int | None = typer.Option(
        None,
        "--hours",
        help="Exact recency window in hours (overrides day precision where possible)",
    ),
    limit: int = typer.Option(
        5, "--limit", "-n", help="How many best-pick videos to process (default: 5)"
    ),
    sort: str = typer.Option(
        "relevance", "--sort", help="Candidate search order: relevance or date"
    ),
    per_channel_cap: int = typer.Option(2, "--channel-cap", help="Max final picks per channel"),
    shorts: bool = typer.Option(
        False, "--shorts/--no-shorts", help="Include short-form videos under 3 minutes"
    ),
    rerank: bool = typer.Option(
        True,
        "--rerank/--no-rerank",
        help="Use LLM reranking to pick the best videos (default: on)",
    ),
    save: bool = typer.Option(
        True,
        "--save/--ephemeral",
        help="Save discovered channels into the library (default: save)",
    ),
    report: bool = typer.Option(
        False, "--report", "-r", help="Generate a topic report after processing"
    ),
    test: bool = typer.Option(False, "--test", help="Test mode for research (cheaper)"),
):
    """Learn a topic fast by processing the best recent YouTube videos by default."""
    _validate_learning_options(sort, limit, days, per_channel_cap, hours=hours)
    _run_learning_command(
        query,
        topic=topic,
        days=days,
        limit=limit,
        sort=sort,
        per_channel_cap=per_channel_cap,
        shorts=shorts,
        rerank=rerank,
        save=save,
        report=report,
        test=test,
        generate_brief=False,
        header="Learning",
        hours=hours,
    )


@app.command(name="latest", rich_help_panel="Discover")
def latest_cmd(
    query: str = typer.Argument(help="Topic or question to get current on quickly"),
    topic: str | None = typer.Option(
        None, "--topic", "-t", help="Topic to file under (default: derived from query)"
    ),
    days: int = typer.Option(3, "--days", "-d", help="Recency window in days (default: 3)"),
    hours: int | None = typer.Option(
        None,
        "--hours",
        help="Exact recency window in hours (overrides day precision where possible)",
    ),
    limit: int = typer.Option(
        10, "--limit", "-n", help="How many best-pick videos to process (default: 10)"
    ),
    sort: str = typer.Option("date", "--sort", help="Candidate search order: relevance or date"),
    per_channel_cap: int = typer.Option(3, "--channel-cap", help="Max final picks per channel"),
    shorts: bool = typer.Option(
        True, "--shorts/--no-shorts", help="Include short-form videos under 3 minutes"
    ),
    rerank: bool = typer.Option(
        True,
        "--rerank/--no-rerank",
        help="Use LLM reranking to pick the best videos (default: on)",
    ),
    save: bool = typer.Option(
        True,
        "--save/--ephemeral",
        help="Save discovered channels into the library (default: save)",
    ),
    preview: bool = typer.Option(
        False, "--preview", help="Preview the selected set without processing it"
    ),
    report: bool = typer.Option(
        False, "--report", "-r", help="Generate a topic report after processing"
    ),
    brief: bool = typer.Option(
        False, "--brief", help="Generate a concise topic brief after processing"
    ),
    test: bool = typer.Option(False, "--test", help="Test mode for research (cheaper)"),
):
    """Opinionated topic-first workflow for getting current fast."""
    _validate_learning_options(sort, limit, days, per_channel_cap, hours=hours)
    if preview:
        config, _tracker, _selected = _preview_learning_selection(
            query,
            days=days,
            hours=hours,
            limit=limit,
            sort=sort,
            per_channel_cap=per_channel_cap,
            shorts=shorts,
            rerank=rerank,
            header="Latest",
            table_title="Latest Best-Pick Learning Set",
        )
        if rerank and not config.xai_api_key:
            console.print(
                "[yellow]XAI_API_KEY missing; used deterministic ranking fallback[/yellow]"
            )
        console.print("\n[dim]Run without `--preview` to process this set.[/dim]")
        return

    _run_learning_command(
        query,
        topic=topic,
        days=days,
        hours=hours,
        limit=limit,
        sort=sort,
        per_channel_cap=per_channel_cap,
        shorts=shorts,
        rerank=rerank,
        save=save,
        report=report,
        test=test,
        generate_brief=brief,
        header="Latest",
    )


@app.command(name="brief", rich_help_panel="Discover")
def brief_cmd(
    query: str = typer.Argument(help="Topic or question to learn and turn into a short brief"),
    topic: str | None = typer.Option(
        None, "--topic", "-t", help="Topic to file under (default: derived from query)"
    ),
    days: int = typer.Option(60, "--days", "-d", help="Recency window in days (default: 60)"),
    hours: int | None = typer.Option(
        None,
        "--hours",
        help="Exact recency window in hours (overrides day precision where possible)",
    ),
    limit: int = typer.Option(
        5, "--limit", "-n", help="How many best-pick videos to process (default: 5)"
    ),
    sort: str = typer.Option(
        "relevance", "--sort", help="Candidate search order: relevance or date"
    ),
    per_channel_cap: int = typer.Option(2, "--channel-cap", help="Max final picks per channel"),
    shorts: bool = typer.Option(
        False, "--shorts/--no-shorts", help="Include short-form videos under 3 minutes"
    ),
    rerank: bool = typer.Option(
        True,
        "--rerank/--no-rerank",
        help="Use LLM reranking to pick the best videos (default: on)",
    ),
    save: bool = typer.Option(
        True,
        "--save/--ephemeral",
        help="Save discovered channels into the library (default: save)",
    ),
    report: bool = typer.Option(
        False,
        "--report",
        "-r",
        help="Also generate a full topic report after processing",
    ),
    test: bool = typer.Option(False, "--test", help="Test mode for research (cheaper)"),
):
    """Learn a topic and generate a concise markdown brief."""
    _validate_learning_options(sort, limit, days, per_channel_cap, hours=hours)
    _run_learning_command(
        query,
        topic=topic,
        days=days,
        limit=limit,
        sort=sort,
        per_channel_cap=per_channel_cap,
        shorts=shorts,
        rerank=rerank,
        save=save,
        report=report,
        test=test,
        generate_brief=True,
        header="Briefing",
        hours=hours,
    )


@app.command(name="research-brief", rich_help_panel="Discover")
def research_brief_cmd(
    topics: list[str] = typer.Option(
        ...,
        "--topic",
        "-t",
        help="Topic(s) to include in the briefing. Pass multiple times or comma-separated.",
    ),
    name: str = typer.Option(
        ...,
        "--name",
        "-n",
        help="Output filename stub. Writes to output/briefing-{name}.md.",
    ),
    context: str | None = typer.Option(
        None,
        "--context",
        help="Inline briefing context/instructions. Use --context-file for longer content.",
    ),
    context_file: Path | None = typer.Option(
        None,
        "--context-file",
        help="Path to a markdown file whose contents become the briefing prompt.",
    ),
):
    """Run a multi-topic Gemini Deep Research briefing grounded on existing corpora.

    Unlike `distill report` (4-phase strategic report, one topic) and `distill brief`
    (fast Grok-based single-topic brief), this runs a single Deep Research call
    across one or more topics with a user-supplied context block that shapes the
    briefing for a specific audience, decision, or downstream agent.

    The context file IS the prompt — distill handles file gathering, File Search
    grounding, Deep Research invocation, and output. Cost: ~$3-5 per briefing.

    Example:
        distill research-brief -t rag-research -t vector-dbs \\
            --context-file docs/briefing-contexts/product-decision.md --name rag-q2
    """
    expanded: list[str] = []
    for entry in topics:
        expanded.extend(t.strip() for t in entry.split(",") if t.strip())
    if not expanded:
        console.print("[red]At least one --topic is required[/red]")
        raise typer.Exit(1)

    if context_file:
        if not context_file.exists():
            console.print(f"[red]--context-file not found: {context_file}[/red]")
            raise typer.Exit(1)
        file_text = context_file.read_text(encoding="utf-8")
        context_text = f"{context}\n\n{file_text}" if context else file_text
    else:
        context_text = context or ""

    if not context_text.strip():
        console.print(
            "[red]Provide --context or --context-file — the briefing needs instructions[/red]"
        )
        raise typer.Exit(1)

    config = get_config()
    _require_api_key(config.gemini_api_key, "GEMINI_API_KEY required for Deep Research")

    output_path = run_research_brief(
        topics=expanded,
        context=context_text,
        name=name,
        config=config,
    )
    if output_path is None:
        raise typer.Exit(1)


@app.command(name="synthesize", rich_help_panel="Discover")
def synthesize_cmd(
    topics: list[str] = typer.Option(
        ...,
        "--topic",
        "-t",
        help="Topic(s) to include. Pass multiple times or comma-separated.",
    ),
    name: str = typer.Option(
        ...,
        "--name",
        "-n",
        help="Output filename stub. Writes to output/synthesis-{name}.md.",
    ),
    context: str | None = typer.Option(None, "--context", help="Inline synthesis instructions."),
    context_file: Path | None = typer.Option(
        None,
        "--context-file",
        help="Path to a markdown file whose contents become the synthesis prompt.",
    ),
    max_tokens: int = typer.Option(
        32768,
        "--max-tokens",
        help="Max output tokens (default 32768 ≈ 120KB of output).",
    ),
):
    """Run a single-call Grok 4.20 deep synthesis across one or more topics.

    Best for academic/technical corpus synthesis where the corpus is the ground
    truth and web augmentation would add noise. Grok 4.20's 2M-token context
    swallows the full corpus in one call, producing a long-form synthesis
    without the consulting-report compression bias that Deep Research imposes.

    Example:
        distill synthesize -t rag-research,vector-dbs \\
            --context-file docs/briefing-contexts/lit-review.md --name rag-lit
    """
    expanded: list[str] = []
    for entry in topics:
        expanded.extend(t.strip() for t in entry.split(",") if t.strip())
    if not expanded:
        console.print("[red]At least one --topic is required[/red]")
        raise typer.Exit(1)

    if context_file:
        if not context_file.exists():
            console.print(f"[red]--context-file not found: {context_file}[/red]")
            raise typer.Exit(1)
        file_text = context_file.read_text(encoding="utf-8")
        context_text = f"{context}\n\n{file_text}" if context else file_text
    else:
        context_text = context or ""

    if not context_text.strip():
        console.print(
            "[red]Provide --context or --context-file — the synthesis needs instructions[/red]"
        )
        raise typer.Exit(1)

    config = get_config()
    _require_api_key(config.xai_api_key, "XAI_API_KEY required for Grok synthesis")

    tracker = CostTracker()
    output_path = run_synthesis(
        topics=expanded,
        context=context_text,
        name=name,
        config=config,
        max_tokens=max_tokens,
        tracker=tracker,
    )
    if output_path is None:
        raise typer.Exit(1)

    summary = tracker.summary_dict()
    console.print(
        f"\n[dim]Tokens: {summary['total_input_tokens']:,} in / "
        f"{summary['total_output_tokens']:,} out — "
        f"Cost: {summary['estimated_total_cost']}[/dim]"
    )


def _validate_learning_options(
    sort: str, limit: int, days: int, per_channel_cap: int, hours: int | None = None
) -> None:
    if sort not in {"relevance", "date"}:
        console.print("[red]--sort must be 'relevance' or 'date'[/red]")
        raise typer.Exit(1)
    if limit <= 0 or days <= 0 or per_channel_cap <= 0:
        console.print("[red]--limit, --days, and --channel-cap must be positive[/red]")
        raise typer.Exit(1)
    if hours is not None and hours <= 0:
        console.print("[red]--hours must be positive[/red]")
        raise typer.Exit(1)


def _preview_learning_selection(
    query: str,
    *,
    days: int,
    limit: int,
    sort: str,
    per_channel_cap: int,
    shorts: bool,
    rerank: bool,
    header: str,
    table_title: str,
    hours: int | None = None,
    skeptical: bool | None = None,
    expand: bool = True,
):
    config = get_config()
    tracker = CostTracker()
    skeptical_mode = (
        _auto_skeptical_mode(query, hours=hours, days=days) if skeptical is None else skeptical
    )
    console.print(f"\n[bold]{header}: {query}[/bold]")
    console.print(
        f"[dim]Window: {_window_label(days, hours)} | Best picks: {limit} | Candidate order: {sort} | "
        f"Channel cap: {per_channel_cap} | Rerank: {'on' if rerank else 'off'} | Skeptical: {'on' if skeptical_mode else 'off'}[/dim]\n"
    )

    _, selected = _select_learning_videos(
        query,
        config,
        tracker,
        days=days,
        limit=limit,
        sort=sort,
        per_channel_cap=per_channel_cap,
        shorts=shorts,
        rerank=rerank,
        hours=hours,
        skeptical=skeptical_mode,
        expand=expand,
    )
    if not selected:
        console.print("[yellow]No recent videos matched the search criteria[/yellow]")
        raise typer.Exit(0)

    _display_ranked_videos(selected, title=table_title)
    return config, tracker, selected


def _run_learning_command(
    query: str,
    *,
    topic: str | None,
    days: int,
    limit: int,
    sort: str,
    per_channel_cap: int,
    shorts: bool,
    rerank: bool,
    save: bool,
    report: bool,
    test: bool,
    generate_brief: bool,
    header: str,
    hours: int | None = None,
    skeptical: bool | None = None,
    expand: bool = True,
    focus: str | None = None,
) -> None:
    config = get_config()
    if not config.xai_api_key:
        console.print("[red]XAI_API_KEY required[/red]")
        raise typer.Exit(1)

    topic_name = topic or _topic_from_query(query)
    tracker = CostTracker()
    skeptical_mode = (
        _auto_skeptical_mode(query, hours=hours, days=days) if skeptical is None else skeptical
    )
    report_focus = focus or _default_report_focus(query, skeptical=skeptical_mode)
    console.print(f"\n[bold]{header}: {query}[/bold]")
    console.print(
        f"[dim]Topic: {topic_name} | Window: {_window_label(days, hours)} | Best picks: {limit} | Candidate order: {sort} | "
        f"Channel cap: {per_channel_cap} | Rerank: {'on' if rerank else 'off'} | Skeptical: {'on' if skeptical_mode else 'off'}[/dim]\n"
    )
    if skeptical_mode:
        console.print(
            "[yellow]Suspicion-aware discovery enabled for rumor-heavy or April 1 style coverage[/yellow]\n"
        )

    _, selected = _select_learning_videos(
        query,
        config,
        tracker,
        days=days,
        limit=limit,
        sort=sort,
        per_channel_cap=per_channel_cap,
        shorts=shorts,
        rerank=rerank,
        hours=hours,
        skeptical=skeptical_mode,
        expand=expand,
    )
    if not selected:
        console.print("[yellow]No recent videos matched the search criteria[/yellow]")
        raise typer.Exit(0)

    _display_ranked_videos(selected, title="Selected Learning Set")
    _process_learning_selection(
        topic_name,
        config,
        tracker,
        selected,
        save=save,
        report=report,
        test=test,
        generate_brief=generate_brief,
        report_focus=report_focus,
    )


def _process_learning_selection(
    topic_name: str,
    config: DistillConfig,
    tracker: CostTracker,
    selected,
    *,
    save: bool,
    report: bool,
    test: bool,
    generate_brief: bool,
    report_focus: str | None = None,
) -> None:
    grouped = {}
    for item in selected:
        video = item.video
        channel_name = (video.channel_name or "unknown").strip() or "unknown"
        grouped.setdefault(channel_name, []).append(video)

    lib = Library(config)
    summary = RunSummary(command="learn")
    summary.set_metadata(topic=topic_name, workflow="learn", source_type="youtube")

    # Pre-run estimate
    all_vids = [item.video for item in selected]
    full_est = sum(1 for v in all_vids if v.duration > SHORTS_THRESHOLD)
    short_est = sum(1 for v in all_vids if v.duration <= SHORTS_THRESHOLD)
    display_estimate(full_est, short_est, console=console, include_report=report)

    console.print(f"  Processing {len(selected)} best-pick videos across {len(grouped)} channels")

    for channel_name, videos in grouped.items():
        channel_url = next((v.channel_url for v in videos if v.channel_url), "")
        if save and channel_url:
            if lib.add_channel(topic_name, channel_url, channel_name):
                console.print(f"[green]Added {channel_name} to {topic_name}[/green]")
            else:
                console.print(f"[dim]{channel_name} already in {topic_name}[/dim]")
        elif save:
            console.print(
                f"[yellow]Could not resolve a stable channel URL for {channel_name}; processing without library registration[/yellow]"
            )

        console.print(f"\n[bold]Channel: {channel_name}[/bold]")
        state = ChannelState(config.channel_dir(topic_name, channel_name) / "state.json")
        _ensure_channel_context(topic_name, channel_name, videos, config, tracker)
        eta = ETATracker(total=len(videos))

        for i, video in enumerate(videos, 1):
            if state.is_processed(video.video_id):
                console.print(f"  [{i}/{len(videos)}] [dim]Already done: {video.title[:60]}[/dim]")
                continue

            eta_hint = f"  [dim]{eta.eta_str}[/dim]" if eta.eta_str else ""
            console.print(f"\n  [{i}/{len(videos)}] [bold]{video.title}[/bold]")
            console.print(
                f"  [dim]{_format_date(video.upload_date)} | {_duration_str(video.duration)}[/dim]{eta_hint}"
            )
            _process_video(
                topic_name,
                channel_name,
                video,
                config,
                tracker,
                summary,
                state=state,
                eta=eta,
            )

        console.print(f"\nSynthesizing {channel_name}...")
        try:
            synthesize_channel(topic_name, channel_name, config, tracker=tracker)
            synth_file = config.channel_dir(topic_name, channel_name) / "synthesis.md"
            cli_shared.record_output_or_issue(
                summary,
                synth_file,
                stage="channel-synthesis",
                context=f"{topic_name}/{channel_name}",
                details={"topic": topic_name, "channel": channel_name},
                missing_message="No synthesis output written",
            )
        except Exception as e:
            console.print(f"[red]Synthesis failed: {e}[/red]")
            cli_shared.record_exception_issue(
                summary,
                stage="channel-synthesis",
                exc=e,
                context=f"{topic_name}/{channel_name}",
                details={"topic": topic_name, "channel": channel_name},
            )

    if grouped:
        console.print(f"\nSynthesizing topic '{topic_name}'...")
        try:
            synthesize_topic(topic_name, config, tracker=tracker)
            topic_synth = config.topic_dir(topic_name) / "topic_synthesis.md"
            cli_shared.record_output_or_issue(
                summary,
                topic_synth,
                stage="topic-synthesis",
                context=topic_name,
                details={"topic": topic_name},
                missing_message="No topic synthesis output written",
            )
        except Exception as e:
            console.print(f"[red]Topic synthesis failed: {e}[/red]")
            cli_shared.record_exception_issue(
                summary,
                stage="topic-synthesis",
                exc=e,
                context=topic_name,
                details={"topic": topic_name},
            )
    try:
        corpus_synth = synthesize_corpus(topic_name, config, tracker=tracker)
        if corpus_synth:
            summary.add_output(config.topic_dir(topic_name) / "corpus_synthesis.md")
    except Exception as e:
        cli_shared.record_exception_issue(
            summary,
            stage="corpus-synthesis",
            exc=e,
            context=topic_name,
            details={"topic": topic_name},
        )

    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)

    if not generate_brief and not report:
        console.print("\n  [dim]What's next:[/dim]")
        console.print(
            f"  [dim]  distill show {topic_name}                    View video insights[/dim]"
        )
        console.print(
            f"  [dim]  distill synthesis {topic_name}               Read the synthesis[/dim]"
        )
        console.print(
            f"  [dim]  distill report {topic_name}                  Deep research report[/dim]"
        )
        console.print(
            f"  [dim]  distill videos {topic_name}                  List all processed videos[/dim]"
        )

    if generate_brief:
        _generate_and_export_topic_brief(topic_name, config, tracker)

    if report:
        _run_scope_report(
            topic_name,
            config,
            tracker,
            scope="topic",
            test=test,
            summary=summary,
            focus=report_focus,
        )


def _generate_and_export_topic_brief(
    topic_name: str, config: DistillConfig, tracker: CostTracker
) -> None:
    console.print(f"\n[bold cyan]Generating brief for {topic_name}...[/bold cyan]")
    brief_path = generate_topic_brief(topic_name, config, tracker=tracker)
    if not brief_path:
        console.print("[yellow]Brief generation did not produce content[/yellow]")
        return

    import shutil

    output_copy = _output_path(config, f"brief-{topic_name}.md")
    shutil.copy2(brief_path, output_copy)
    console.print(f"[green]Brief:   {brief_path}[/green]")
    console.print(f"[green]Output:  {output_copy}[/green]")


# ─── Library Management ───────────────────────────────────────────────


@app.command(rich_help_panel="Library")
def add(
    topic: str = typer.Argument(help="Topic to add channel to (e.g., 'ai', 'security')"),
    url: str = typer.Argument(help="YouTube channel URL"),
):
    """Add a channel to a topic."""
    config = get_config()
    lib = Library(config)

    name = resolve_channel_name(url)
    console.print(f"Adding [bold]{name}[/bold] to topic [bold]{topic}[/bold]...")

    if lib.add_channel(topic, url, name):
        console.print(f"[green]Added {name} to {topic}[/green]")
        console.print(f"[dim]Next: distill run {topic}[/dim]")
    else:
        console.print(f"[yellow]{name} already exists in {topic}[/yellow]")


@app.command(rich_help_panel="Library")
def remove(
    topic: str = typer.Argument(help="Topic", autocompletion=_complete_topics),
    url: str = typer.Argument(help="YouTube channel URL to remove"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Remove a channel from a topic."""
    config = get_config()
    lib = Library(config)

    if not yes and not typer.confirm(
        f"Remove channel from '{topic}'? (library entry only, data stays on disk)"
    ):
        raise typer.Abort()

    if lib.remove_channel(topic, url):
        console.print(f"[green]Removed from {topic}[/green]")
    else:
        console.print(f"[yellow]Not found in {topic}[/yellow]")


@app.command(name="library", rich_help_panel="Library")
def library_cmd():
    """Show what's in your library."""
    config = get_config()
    lib = Library(config)

    topics = lib.get_topics()
    if not topics:
        console.print(
            Panel(
                "[dim]Library is empty.\n\nGet started:[/dim]\n"
                '  distill latest "Microsoft Fabric best practices"\n'
                "  distill add ai https://www.youtube.com/@SomeChannel\n"
                "  distill run ai",
                title="Distill Library",
                border_style="dim",
            )
        )
        return

    for topic in topics:
        channels = lib.get_channels(topic)
        table = Table(
            title=f"Topic: {topic}",
            show_header=True,
            box=box.ROUNDED,
            title_style="bold cyan",
        )
        table.add_column("Channel", style="bold")
        table.add_column("Videos", justify="right", style="green")
        table.add_column("Last Refresh", style="dim")
        table.add_column("Artifacts", style="dim")

        for ch in channels:
            state_file = config.channel_dir(topic, ch.name) / "state.json"
            state = ChannelState(state_file)

            artifacts = []
            if (config.channel_dir(topic, ch.name) / "synthesis.md").exists():
                artifacts.append("synthesis")
            if (config.channel_dir(topic, ch.name) / "report.md").exists():
                artifacts.append("report")

            table.add_row(
                ch.name,
                str(state.get_processed_count()),
                _format_date(state.get_last_refresh() or ""),
                ", ".join(artifacts) if artifacts else "-",
            )

        console.print(table)

        # Topic-level artifacts
        topic_artifacts = []
        if (config.topic_dir(topic) / "topic_synthesis.md").exists():
            topic_artifacts.append("topic_synthesis.md")
        if (config.topic_dir(topic) / "report.md").exists():
            topic_artifacts.append("report.md")
        if topic_artifacts:
            console.print(f"  [dim]Topic files: {', '.join(topic_artifacts)}[/dim]")

        # Actionable hints per topic
        console.print(
            f"  [dim]distill videos {topic}  |  "
            f"distill synthesis {topic}  |  "
            f"distill run {topic} --refresh[/dim]"
        )
        console.print()


# ─── Browsing & Inspection ────────────────────────────────────────────


@app.command(rich_help_panel="Library")
def videos(
    topic: str = typer.Argument(help="Topic or channel name", autocompletion=_complete_topics),
    channel: str | None = typer.Option(
        None, "--channel", "-c", help="Specific channel (default: all in topic)"
    ),
    limit: int = typer.Option(20, "--limit", "-n", help="Max videos to show"),
):
    """List processed videos with metadata."""
    config = get_config()
    lib = Library(config)
    topic, channel = _resolve_topic_for_channel(lib, topic, channel)

    channels = lib.get_channels(topic)
    if channel:
        channels = [ch for ch in channels if ch.name == channel]

    if not channels:
        console.print(f"[yellow]No channels found for topic '{topic}'[/yellow]")
        return

    for ch in channels:
        videos_dir = config.videos_dir(topic, ch.name)
        if not videos_dir.exists():
            continue

        # Collect all video metadata
        vid_list = []
        for vid_dir in sorted(videos_dir.iterdir()):
            if not vid_dir.is_dir():
                continue
            meta_file = vid_dir / "metadata.json"
            if meta_file.exists():
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                meta["_dir"] = vid_dir
                meta["_has_transcript"] = (vid_dir / "transcript.txt").exists()
                meta["_has_insights"] = (vid_dir / "insights.md").exists()
                vid_list.append(meta)

        # Sort by upload date, newest first
        vid_list.sort(key=lambda v: v.get("upload_date", ""), reverse=True)

        table = Table(
            title=f"{ch.name} - {len(vid_list)} videos",
            show_header=True,
            box=box.ROUNDED,
            title_style="bold cyan",
        )
        table.add_column("#", style="dim", justify="right")
        table.add_column("Date", style="dim")
        table.add_column("Title")
        table.add_column("Duration", justify="right", style="dim")
        table.add_column("Status", justify="center")

        for i, v in enumerate(vid_list[:limit], 1):
            has_t = v.get("_has_transcript", False)
            has_i = v.get("_has_insights", False)

            if has_t and has_i:
                status = "[green]complete[/green]"
            elif has_t:
                status = "[yellow]transcript only[/yellow]"
            else:
                status = "[red]missing[/red]"

            table.add_row(
                str(i),
                _format_date(v.get("upload_date", "")),
                v.get("title", "Unknown")[:70],
                _duration_str(v.get("duration", 0)),
                status,
            )

        console.print(table)

        if len(vid_list) > limit:
            console.print(
                f"  [dim]Showing {limit}/{len(vid_list)} -- use --limit to see more[/dim]"
            )

        # Next steps
        ch_flag = f" -c {ch.name}" if channel else ""
        console.print(
            f"  [dim]distill show {topic} 1{ch_flag}            View insights for video #1[/dim]"
        )
        console.print(
            f"  [dim]distill synthesis {topic}{ch_flag}          Read the synthesis[/dim]"
        )
        console.print()


@app.command(rich_help_panel="View")
def show(
    topic: str = typer.Argument(help="Topic or channel name", autocompletion=_complete_topics),
    index_or_channel: str = typer.Argument(
        "1",
        help="Video number (newest=1) or channel name",
        autocompletion=_complete_watched_channels,
    ),
    channel: str | None = typer.Option(
        None,
        "--channel",
        "-c",
        help="Specific channel",
        autocompletion=_complete_watched_channels,
    ),
    what: str = typer.Option(
        "insights", "--what", "-w", help="What to show: insights, transcript, metadata"
    ),
):
    """Read insights or transcript for a specific video."""
    config = get_config()
    lib = Library(config)

    # Parse second arg: if it looks like an int, use as index; otherwise treat as channel
    index = 1
    if index_or_channel.isdigit():
        index = int(index_or_channel)
    else:
        # Treat as channel name (positional overrides -c flag)
        channel = index_or_channel

    topic, channel = _resolve_topic_for_channel(lib, topic, channel)
    channels = lib.get_channels(topic)
    if channel:
        channels = [ch for ch in channels if ch.name == channel]
    if not channels:
        console.print("[yellow]No channels found[/yellow]")
        return

    ch = channels[0]
    videos_dir = config.videos_dir(topic, ch.name)

    if not videos_dir.exists():
        console.print(f"[yellow]No videos found for {ch.name}[/yellow]")
        return

    # Collect and sort videos
    vid_list = []
    for vid_dir in sorted(videos_dir.iterdir()):
        if not vid_dir.is_dir():
            continue
        meta_file = vid_dir / "metadata.json"
        if meta_file.exists():
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            meta["_dir"] = vid_dir
            vid_list.append(meta)

    vid_list.sort(key=lambda v: v.get("upload_date", ""), reverse=True)

    if index < 1 or index > len(vid_list):
        console.print(f"[red]Video #{index} not found. Range: 1-{len(vid_list)}[/red]")
        return

    video = vid_list[index - 1]
    vid_dir = video["_dir"]

    title = video.get("title", "Unknown")
    date = _format_date(video.get("upload_date", ""))

    total = len(vid_list)
    ch_name = ch.name
    pos_label = f"[dim][{index}/{total}][/dim]"

    if what == "insights":
        file_path = vid_dir / "insights.md"
        if not file_path.exists():
            console.print("[red]No insights found for this video[/red]")
            console.print(f"[dim]Run: distill run {topic} -c {ch_name} --refresh[/dim]")
            return
        console.print(
            Panel(
                f"{pos_label}  [bold]{title}[/bold]\n"
                f"[dim]{date} | {_duration_str(video.get('duration', 0))} | {ch_name}[/dim]\n"
                f"[dim]{video.get('url', '')}[/dim]",
                border_style="cyan",
            )
        )
        content = file_path.read_text(encoding="utf-8")
        # Strip YAML frontmatter for display
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                content = parts[2].strip()
        _print_markdown_safely(console, content)

        # Footer: navigation + file link
        console.print()
        nav = []
        if index > 1:
            nav.append(f"[dim]<< distill show {ch_name} {index - 1}[/dim]")
        if index < total:
            nav.append(f"[dim]distill show {ch_name} {index + 1} >>[/dim]")
        if nav:
            console.print(f"  {'  |  '.join(nav)}")
        console.print(f"  [dim]-w transcript[/dim]  |  {_file_link(file_path)}")

    elif what == "transcript":
        file_path = vid_dir / "transcript.txt"
        if not file_path.exists():
            console.print("[red]No transcript found[/red]")
            console.print(f"[dim]Run: distill run {topic} -c {ch_name} --refresh[/dim]")
            return
        console.print(
            Panel(
                f"{pos_label}  [bold]{title}[/bold]\n[dim]{date} | Transcript[/dim]",
                border_style="cyan",
            )
        )
        text = file_path.read_text(encoding="utf-8")
        # Show first 3000 chars with note about full length
        if len(text) > 3000:
            console.print(text[:3000])
            console.print(f"\n[dim]... ({len(text):,} chars total - showing first 3000)[/dim]")
        else:
            console.print(text)

        console.print()
        console.print(f"  [dim]-w insights[/dim]  |  {_file_link(file_path)}")

    elif what == "metadata":
        console.print(
            Panel(
                f"{pos_label}  [bold]{title}[/bold]\n[dim]{date} | Metadata[/dim]",
                border_style="cyan",
            )
        )
        console.print_json(json.dumps(video, indent=2, default=str))

    else:
        console.print(f"[red]Invalid --what={what}[/red]")
        console.print("[dim]Valid options: insights, transcript, metadata[/dim]")


@app.command(name="package-latest", rich_help_panel="View")
def package_latest(
    topic: str = typer.Argument(help="Topic or channel name", autocompletion=_complete_topics),
    channel: str | None = typer.Option(
        None, "--channel", "-c", help="Specific channel", autocompletion=_complete_watched_channels
    ),
    limit: int = typer.Option(10, "--limit", "-n", help="Number of latest videos to include"),
    include_transcript: bool = typer.Option(
        False, "--transcript", "-t", help="Include full transcripts (can be large)"
    ),
):
    """Package the latest videos into a single markdown file with links, insights, and optionally transcripts."""
    config = get_config()
    lib = Library(config)
    topic, channel = _resolve_topic_for_channel(lib, topic, channel)

    channels = lib.get_channels(topic)
    if channel:
        channels = [ch for ch in channels if ch.name == channel]
    if not channels:
        console.print("[yellow]No channels found[/yellow]")
        return

    # Collect videos across selected channels
    all_videos: list[tuple[str, dict, Path]] = []
    for ch in channels:
        videos_dir = config.videos_dir(topic, ch.name)
        if not videos_dir.exists():
            continue
        for vid_dir in videos_dir.iterdir():
            if not vid_dir.is_dir():
                continue
            meta_file = vid_dir / "metadata.json"
            if meta_file.exists():
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                all_videos.append((ch.name, meta, vid_dir))

    all_videos.sort(key=lambda v: v[1].get("upload_date", ""), reverse=True)
    selected = all_videos[:limit]

    if not selected:
        console.print("[yellow]No videos found[/yellow]")
        return

    # Build the markdown
    parts: list[str] = []
    channel_label = channel or "all channels"
    parts.append(f"# Latest {len(selected)} Videos — {topic} / {channel_label}")
    parts.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    for i, (ch_name, meta, vid_dir) in enumerate(selected, 1):
        title = meta.get("title", "Unknown")
        date = _format_date(meta.get("upload_date", ""))
        duration = _duration_str(meta.get("duration", 0))
        url = meta.get("url", "")

        parts.append(f"---\n\n## {i}. {title}\n")
        parts.append(f"**Channel:** {ch_name}  ")
        parts.append(f"**Date:** {date}  ")
        parts.append(f"**Duration:** {duration}  ")
        if url:
            parts.append(f"**Link:** {url}\n")

        # Insights
        insights_file = vid_dir / "insights.md"
        if insights_file.exists():
            content = insights_file.read_text(encoding="utf-8")
            # Strip YAML frontmatter
            if content.startswith("---"):
                fm_parts = content.split("---", 2)
                if len(fm_parts) >= 3:
                    content = fm_parts[2].strip()
            parts.append(f"\n### Insights\n\n{content}\n")

        # Transcript (optional)
        if include_transcript:
            transcript_file = vid_dir / "transcript.txt"
            if transcript_file.exists():
                transcript = transcript_file.read_text(encoding="utf-8")
                parts.append(f"\n### Transcript\n\n{transcript}\n")

    output_text = "\n".join(parts)

    # Write to output
    slug = channel or topic
    filename = f"latest-{slug}.md"
    out_path = _output_path(config, filename)
    out_path.write_text(output_text, encoding="utf-8")

    size_kb = len(output_text.encode("utf-8")) / 1024
    console.print(f"  [green]Packaged {len(selected)} videos -> {out_path}[/green]")
    console.print(f"  [dim]{size_kb:.1f} KB[/dim]")
    console.print(f"\n  {_file_link(out_path)}")


@app.command(rich_help_panel="View")
def synthesis(
    topic: str = typer.Argument(help="Topic or channel name", autocompletion=_complete_topics),
    channel: str | None = typer.Option(
        None, "--channel", "-c", help="Channel synthesis (default: topic synthesis)"
    ),
):
    """Read the synthesis document for a channel or topic."""
    config = get_config()
    lib = Library(config)
    topic, channel = _resolve_topic_for_channel(lib, topic, channel)

    if channel:
        file_path = config.channel_dir(topic, channel) / "synthesis.md"
        label = f"Channel Synthesis: {channel}"
    else:
        # Try topic synthesis first, fall back to first channel
        file_path = config.topic_dir(topic) / "topic_synthesis.md"
        label = f"Topic Synthesis: {topic}"
        if not file_path.exists():
            # Fall back to first channel synthesis
            lib = Library(config)
            channels = lib.get_channels(topic)
            if channels:
                file_path = config.channel_dir(topic, channels[0].name) / "synthesis.md"
                label = f"Channel Synthesis: {channels[0].name}"

    if not file_path.exists():
        # Check if there are any processed videos at all
        lib = Library(config)
        ch_list = lib.get_channels(topic)
        total_processed = 0
        for ch_entry in ch_list:
            state_path = config.channel_dir(topic, ch_entry.name) / "state.json"
            if state_path.parent.exists():
                st = ChannelState(state_path)
                total_processed += st.get_processed_count()

        if total_processed == 0:
            ch_name = channel or (ch_list[0].name if ch_list else "")
            console.print("[yellow]No synthesis yet -- no videos have been processed.[/yellow]")
            if ch_name:
                console.print(
                    f"[dim]  distill catch-up {ch_name}           Scan for new videos[/dim]"
                )
                console.print(
                    f"[dim]  distill run {topic} --refresh        Full 2-pass analysis[/dim]"
                )
            return
        else:
            console.print("[yellow]No synthesis found. Generating one now...[/yellow]")
            try:
                tracker = CostTracker()
                if channel:
                    synthesize_channel(topic, channel, config, tracker=tracker)
                    console.print(f"[green]Synthesis generated for {channel}[/green]")
                    file_path = config.channel_dir(topic, channel) / "synthesis.md"
                else:
                    synthesize_topic(topic, config, tracker=tracker)
                    console.print(f"[green]Topic synthesis generated for {topic}[/green]")
                    file_path = config.topic_dir(topic) / "topic_synthesis.md"
            except Exception as e:
                console.print(f"[red]Synthesis failed: {e}[/red]")
                return
            if not file_path.exists():
                return

    console.print(Panel(f"[bold]{label}[/bold]", border_style="cyan"))
    content = file_path.read_text(encoding="utf-8")
    _print_markdown_safely(console, content)

    # Next steps
    console.print()
    console.print(f"  {_file_link(file_path)}")
    ch_flag = f" -c {channel}" if channel else ""
    console.print(
        f"  [dim]distill videos {topic}{ch_flag}  |  "
        f"distill export {topic} --what synthesis{ch_flag}[/dim]"
    )


@app.command(rich_help_panel="View")
def findings(
    topic: str = typer.Argument(help="Topic or channel name", autocompletion=_complete_topics),
    channel: str | None = typer.Option(
        None, "--channel", "-c", help="Channel report (default: topic report)"
    ),
):
    """Read the generated report."""
    config = get_config()
    lib = Library(config)
    topic, channel = _resolve_topic_for_channel(lib, topic, channel)

    if channel:
        file_path = config.channel_dir(topic, channel) / "report.md"
        label = f"Report: {channel}"
    else:
        file_path = config.topic_dir(topic) / "report.md"
        label = f"Report: {topic}"

    if not file_path.exists():
        console.print(f"[yellow]No report yet. Run 'distill report {topic}' first.[/yellow]")
        return

    console.print(Panel(f"[bold]{label}[/bold]", border_style="green"))
    content = file_path.read_text(encoding="utf-8")
    _print_markdown_safely(console, content)

    # Next steps
    console.print()
    console.print(f"  {_file_link(file_path)}")
    ch_flag = f" -c {channel}" if channel else ""
    console.print(f"  [dim]distill export {topic}{ch_flag}  |  distill open {topic}[/dim]")


@app.command(rich_help_panel="View")
def diff(
    topic: str = typer.Argument(help="Topic or channel name", autocompletion=_complete_topics),
    watch: str | None = typer.Option(
        None,
        "--watch",
        help="Compare against this topic-watch's last run",
        autocompletion=_complete_topic_watch_names,
    ),
    days: int = typer.Option(
        7, "--days", "-d", help="Fallback comparison window when no topic-watch baseline exists"
    ),
    limit: int = typer.Option(10, "--limit", "-n", help="Max items to show per change section"),
    write: bool = typer.Option(
        True,
        "--write/--no-write",
        help="Write the latest topic diff to library/topics/<topic>/topic_diff.md",
    ),
):
    """Show what changed in a topic since the last watch run or a fallback window."""
    config = get_config()
    lib = Library(config)
    topic, _channel = _resolve_topic_for_channel(lib, topic, None)

    if topic not in lib.get_topics() and not config.topic_dir(topic).exists():
        console.print(f"[red]Topic not found: {topic}[/red]")
        raise typer.Exit(1)

    baseline, watch_name, query, cadence = _resolve_topic_diff_baseline(
        lib,
        topic,
        watch_name=watch,
        days=days,
    )
    details = _collect_topic_change_details(config, lib, topic, baseline)
    summary = str(details.get("summary", "no recent change detected"))
    generated_at = details.get("generated_at") or datetime.now()
    effective_baseline = details.get("effective_baseline") or (baseline or generated_at)
    rendered = _render_topic_diff_markdown(
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
        new_videos=list(details.get("new_videos", [])),
        new_pages=list(details.get("new_pages", [])),
        new_papers=list(details.get("new_papers", [])),
        refreshed_outputs=list(details.get("refreshed_outputs", [])),
        limit=limit,
    )

    console.print(Panel(f"[bold]Topic Diff: {topic}[/bold]", border_style="cyan"))
    _print_markdown_safely(console, rendered)

    if write:
        diff_path = _topic_diff_output_path(config, topic)
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        diff_path.write_text(rendered, encoding="utf-8")
        history_path = _append_topic_change_history(
            config,
            topic=topic,
            summary=summary,
            baseline=baseline,
            generated_at=generated_at,
            watch_name=watch_name,
            query=query,
            cadence=cadence,
            new_videos=list(details.get("new_videos", [])),
            new_pages=list(details.get("new_pages", [])),
            new_papers=list(details.get("new_papers", [])),
            refreshed_outputs=list(details.get("refreshed_outputs", [])),
        )
        console.print()
        console.print(f"  {_file_link(diff_path)}")
        console.print(f"  {_file_link(history_path)}")
        console.print(f"  [dim]distill findings {topic}  |  distill synthesis {topic}[/dim]")


@app.command(rich_help_panel="View")
def trends(
    topic: str = typer.Argument(help="Topic or channel name", autocompletion=_complete_topics),
    limit: int = typer.Option(
        8, "--limit", "-n", help="How many recent change windows to summarize"
    ),
    write: bool = typer.Option(
        True,
        "--write/--no-write",
        help="Write the latest topic trends to library/topics/<topic>/topic_trends.md",
    ),
):
    """Show recent topic momentum using recorded diff history."""
    config = get_config()
    lib = Library(config)
    topic, _channel = _resolve_topic_for_channel(lib, topic, None)

    if topic not in lib.get_topics() and not config.topic_dir(topic).exists():
        console.print(f"[red]Topic not found: {topic}[/red]")
        raise typer.Exit(1)

    records = _load_topic_change_history(config, topic)
    rendered = _render_topic_trends_markdown(
        config,
        topic=topic,
        records=records,
        generated_at=datetime.now(),
        limit=limit,
    )

    console.print(Panel(f"[bold]Topic Trends: {topic}[/bold]", border_style="magenta"))
    _print_markdown_safely(console, rendered)

    if write:
        trends_path = _topic_trends_output_path(config, topic)
        trends_path.parent.mkdir(parents=True, exist_ok=True)
        trends_path.write_text(rendered, encoding="utf-8")
        console.print()
        console.print(f"  {_file_link(trends_path)}")
        console.print(f"  {_file_link(_topic_change_history_path(config, topic))}")
        console.print(f"  [dim]distill diff {topic}  |  distill findings {topic}[/dim]")


# ─── Processing ────────────────────────────────────────────────────────


@app.command(rich_help_panel="Process")
def run(
    topic: str = typer.Argument(None, help="Topic or channel name"),
    channel: str | None = typer.Option(None, "--channel", "-c", help="Process only this channel"),
    months: int = typer.Option(None, "--months", "-m", help="Lookback window in months"),
    refresh: bool = typer.Option(
        False, "--refresh", "-r", help="Only process new videos since last run"
    ),
    all_topics: bool = typer.Option(False, "--all", help="Process all topics"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be processed"),
    limit: int | None = typer.Option(
        None, "--limit", "-n", help="Max videos to process per channel"
    ),
    shorts: bool = typer.Option(False, "--shorts", help="Also include YouTube Shorts (<60s)"),
):
    """Process videos -- discover, transcribe, and analyze."""
    config = get_config()
    lib = Library(config)
    if topic:
        topic, channel = _resolve_topic_for_channel(lib, topic, channel)
    lookback = months or config.distill_default_months

    if not topic and not all_topics:
        console.print("[red]Specify a topic or use --all[/red]")
        raise typer.Exit(1)

    topics = lib.get_topics() if all_topics else [topic]

    tracker = CostTracker()
    summary = RunSummary(command="run")
    total_new = 0
    total_analyzed = 0

    for t in topics:
        channels = lib.get_channels(t)
        if channel:
            channels = [ch for ch in channels if ch.name == channel]

        if not channels:
            console.print(f"[yellow]No channels found for topic '{t}'[/yellow]")
            continue

        console.print(f"\n[bold]Topic: {t}[/bold]")

        for ch in channels:
            console.print(f"\n[bold cyan]Channel: {ch.name}[/bold cyan]")

            # Discover videos
            console.print(f"  Discovering videos (past {lookback} months)...")
            videos = discover_videos(ch.url, lookback, include_shorts=shorts)
            console.print(f"  [green]Found {len(videos)} videos[/green]")

            # Filter already processed
            state_file = config.channel_dir(t, ch.name) / "state.json"
            state = ChannelState(state_file)

            if refresh:
                videos = [v for v in videos if not state.is_processed(v.video_id)]
                console.print(f"  [dim]{len(videos)} new since last refresh[/dim]")

            if limit:
                videos = videos[:limit]
                console.print(f"  [dim]Limited to {limit} videos[/dim]")

            if not videos:
                console.print("  [dim]Nothing new to process[/dim]")
                continue

            if dry_run:
                new_videos = [v for v in videos if not state.is_processed(v.video_id)]
                for v in videos:
                    status = "SKIP" if state.is_processed(v.video_id) else "NEW"
                    is_s = v.duration <= SHORTS_THRESHOLD
                    kind = " [dim](Short)[/dim]" if is_s else ""
                    console.print(
                        f"  [{status}] {_format_date(v.upload_date)} | {v.title} ({_duration_str(v.duration)}){kind}"
                    )
                full = sum(1 for v in new_videos if v.duration > SHORTS_THRESHOLD)
                short = sum(1 for v in new_videos if v.duration <= SHORTS_THRESHOLD)
                if new_videos:
                    console.print(f"\n  {estimate_run_cost(full, short)}")
                total_new += len(new_videos)
                continue

            # Pre-run estimate
            new_to_process = [v for v in videos if not state.is_processed(v.video_id)]
            if new_to_process:
                full_count = sum(1 for v in new_to_process if v.duration > SHORTS_THRESHOLD)
                short_count = sum(1 for v in new_to_process if v.duration <= SHORTS_THRESHOLD)
                display_estimate(full_count, short_count, console=console)

            # Generate channel context if we don't have one
            ctx_file = config.channel_dir(t, ch.name) / "channel_context.md"
            ctx_file.parent.mkdir(parents=True, exist_ok=True)
            if not ctx_file.exists():
                console.print("  Generating channel context...")
                ctx = generate_channel_context(
                    ch.name, [v.title for v in videos], config, tracker=tracker
                )
                ctx_file.write_text(ctx, encoding="utf-8")
                console.print("  [green]Saved channel context[/green]")

            # Process each video
            run_eta = ETATracker(total=len(new_to_process)) if new_to_process else None
            for i, video in enumerate(videos, 1):
                if state.is_processed(video.video_id):
                    console.print(
                        f"  [{i}/{len(videos)}] [dim]Already processed: {video.title[:60]}[/dim]"
                    )
                    continue

                vid_start = run_eta.start() if run_eta else 0
                run_eta_hint = (
                    f"  [dim]{run_eta.eta_str}[/dim]" if run_eta and run_eta.eta_str else ""
                )
                console.print(f"\n  [{i}/{len(videos)}] [bold]{video.title}[/bold]")
                console.print(
                    f"  [dim]{_format_date(video.upload_date)} | {_duration_str(video.duration)}[/dim]{run_eta_hint}"
                )

                vid_dir = config.video_dir_slug(t, ch.name, video.title, video.video_id)
                vid_dir.mkdir(parents=True, exist_ok=True)

                # Save metadata
                meta = {
                    "video_id": video.video_id,
                    "title": video.title,
                    "upload_date": video.upload_date,
                    "duration": video.duration,
                    "url": video.url,
                }
                (vid_dir / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

                # Get transcript
                transcript_file = vid_dir / "transcript.txt"
                if transcript_file.exists():
                    console.print("    [dim]Transcript already exists[/dim]")
                else:
                    console.print("    Getting transcript...")
                    success = get_transcript(video.url, video.video_id, transcript_file, config)
                    if not success:
                        console.print("    [red]Failed to get transcript, skipping[/red]")
                        summary.add_result(
                            VideoResult(
                                video.video_id,
                                video.title,
                                False,
                                error="No transcript",
                            )
                        )
                        if run_eta:
                            run_eta.tick(vid_start)
                        continue
                    console.print(
                        f"    [green]Transcript saved ({transcript_file.stat().st_size:,} bytes)[/green]"
                    )

                # Analyze
                transcript = transcript_file.read_text(encoding="utf-8")
                if not transcript.strip():
                    console.print("    [red]Empty transcript, skipping analysis[/red]")
                    summary.add_result(
                        VideoResult(video.video_id, video.title, False, error="Empty transcript")
                    )
                    if run_eta:
                        run_eta.tick(vid_start)
                    continue

                is_short = video.duration <= SHORTS_THRESHOLD
                label = "Quick insight (Short)" if is_short else "Analyzing"
                console.print(f"    {label}...")
                try:
                    if is_short:
                        insights = analyze_short(
                            video.title,
                            video.upload_date,
                            ch.name,
                            transcript,
                            config,
                            tracker=tracker,
                        )
                    else:
                        insights = analyze_video(
                            video.title,
                            video.upload_date,
                            ch.name,
                            transcript,
                            config,
                            tracker=tracker,
                        )
                    insights_file = vid_dir / "insights.md"
                    insights_file.write_text(insights, encoding="utf-8")
                    console.print("    [green]Insights saved[/green]")

                    state.mark_processed(video.video_id, video.title, video.upload_date)
                    summary.add_result(
                        VideoResult(
                            video.video_id,
                            video.title,
                            True,
                            is_short=is_short,
                            duration=video.duration,
                        )
                    )
                    total_analyzed += 1
                    if run_eta:
                        run_eta.tick(vid_start)
                except Exception as e:
                    console.print(f"    [red]Analysis failed: {e}[/red]")
                    console.print(
                        "    [dim]Transcript saved — will retry analysis on next run[/dim]"
                    )
                    summary.add_result(
                        VideoResult(
                            video.video_id,
                            video.title,
                            False,
                            is_short=is_short,
                            error=str(e),
                        )
                    )
                    if run_eta:
                        run_eta.tick(vid_start)
                    continue  # Channel synthesis
            console.print(f"\n  Synthesizing channel: {ch.name}...")
            try:
                synthesize_channel(t, ch.name, config, tracker=tracker)
                synth_file = config.channel_dir(t, ch.name) / "synthesis.md"
                cli_shared.record_output_or_issue(
                    summary,
                    synth_file,
                    stage="channel-synthesis",
                    context=f"{t}/{ch.name}",
                    details={"topic": t, "channel": ch.name},
                    missing_message="No synthesis output written",
                )
            except Exception as e:
                console.print(f"  [red]Channel synthesis failed: {e}[/red]")
                cli_shared.record_exception_issue(
                    summary,
                    stage="channel-synthesis",
                    exc=e,
                    context=f"{t}/{ch.name}",
                    details={"topic": t, "channel": ch.name},
                )

        # Topic synthesis (only if multiple channels)
        try:
            synthesize_topic(t, config, tracker=tracker)
            topic_synth = config.topic_dir(t) / "topic_synthesis.md"
            cli_shared.record_output_or_issue(
                summary,
                topic_synth,
                stage="topic-synthesis",
                context=t,
                details={"topic": t},
                missing_message="No topic synthesis output written",
            )
        except Exception as e:
            console.print(f"  [red]Topic synthesis failed: {e}[/red]")
            cli_shared.record_exception_issue(
                summary,
                stage="topic-synthesis",
                exc=e,
                context=t,
                details={"topic": t},
            )

    if dry_run:
        console.print(f"\n[bold]Dry run: {total_new} videos would be processed[/bold]")
    else:
        display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
        t_name = topics[0]
        console.print("\n  [dim]What's next:[/dim]")
        console.print(
            f"  [dim]  distill show {t_name}                       View video insights[/dim]"
        )
        console.print(
            f"  [dim]  distill synthesis {t_name}                  Read the synthesis[/dim]"
        )
        console.print(
            f"  [dim]  distill report {t_name}                     Deep research report[/dim]"
        )


# ─── Report Generation ─────────────────────────────────────────────────


@app.command(rich_help_panel="Reports")
def report(
    topic: str = typer.Argument(None, help="Topic or channel name"),
    channel: str | None = typer.Option(None, "--channel", "-c", help="Report on a single channel"),
    all_topics: bool = typer.Option(False, "--all", help="Report on entire library"),
    focus: str | None = typer.Option(None, "--focus", "-f", help="Custom research focus"),
    test: bool = typer.Option(False, "--test", "-t", help="Test mode (cheaper, faster)"),
    legacy: bool = typer.Option(
        False, "--legacy", help="Use single-shot Deep Research (no section writing)"
    ),
    research_only: bool = typer.Option(
        False,
        "--research-only",
        help="Run Phase 1 only (raw research, no section writing)",
    ),
    sections_filter: str | None = typer.Option(
        None, "--sections", "-s", help="Comma-separated section IDs to write"
    ),
    no_qa: bool = typer.Option(False, "--no-qa", help="Skip QA review phase"),
):
    """Generate a strategic intelligence report.

    Default: 4-phase (research + section writing + assembly + QA review).
    Use --legacy for single-shot Deep Research.
    Use --research-only to run only Phase 1.
    Use --no-qa to skip the QA review.
    """
    config = get_config()
    if topic:
        lib = Library(config)
        topic, channel = _resolve_topic_for_channel(lib, topic, channel)

    if not config.gemini_api_key:
        console.print("[red]GEMINI_API_KEY required for deep research[/red]")
        console.print("[dim]Get one at: https://aistudio.google.com/apikey[/dim]")
        raise typer.Exit(1)

    if not topic and not all_topics:
        console.print("[red]Specify a topic or use --all[/red]")
        raise typer.Exit(1)

    scope = "all" if all_topics else ("channel" if channel else "topic")
    scope_label = (
        "entire library"
        if all_topics
        else (f"channel: {channel}" if channel else f"topic: {topic}")
    )
    method = "Legacy (single-shot)" if legacy else "Accordion (3-phase)"

    tracker = CostTracker()
    summary = RunSummary(command="report")
    if topic:
        summary.set_metadata(topic=topic, workflow="report")
    elif all_topics:
        summary.set_metadata(topic="all", workflow="report")

    console.print(f"\n[bold]Report: {scope_label}[/bold]")
    console.print(f"[dim]Method: {method}[/dim]")
    if test:
        console.print("[yellow]Test mode -- truncated corpus, faster/cheaper[/yellow]")
    if focus:
        console.print(f"[dim]Focus: {focus}[/dim]")

    if legacy:
        # Original single-shot deep research
        result = run_deep_research(
            topic=topic or "all",
            config=config,
            scope=scope,
            channel_name=channel,
            focus=focus,
            test=test,
        )
    else:
        # Accordion method
        from distill.accordion import run_accordion_research

        filter_list = [s.strip() for s in sections_filter.split(",")] if sections_filter else None

        result = run_accordion_research(
            topic=topic or "all",
            config=config,
            scope=scope,
            channel_name=channel,
            focus=focus,
            test=test,
            dossier_only=research_only,
            sections=filter_list,
            tracker=tracker,
            skip_qa=no_qa,
        )

    if result:
        console.print("\n[bold green]Report complete![/bold green]")
        console.print(
            f"[dim]Output: {len(result):,} characters ({len(result.split()):,} words)[/dim]"
        )

        # Export both MD and DOCX to output/
        import shutil

        from distill.research import _get_report_path

        md_source = _get_report_path(topic or "all", config, scope, channel)
        summary.add_output(md_source)

        if md_source.exists() and not research_only:
            # Build output filename with channel if scoped
            name_parts = [topic or "all"]
            if channel:
                name_parts.append(channel)
            base_name = "-".join(name_parts)

            # Copy markdown to output/
            md_out = _output_path(config, f"report-{base_name}.md")
            shutil.copy2(md_source, md_out)
            console.print(f"[green]Markdown: {md_out}[/green]")
            summary.add_output(md_out)

            # Export DOCX to output/
            try:
                from distill.docx_export import export_report

                docx_path = _output_path(config, f"report-{base_name}.docx")
                export_report(
                    md_source,
                    docx_path=docx_path,
                    title=f"Strategic Intelligence: {(topic or 'all').upper()}",
                )
                console.print(f"[green]DOCX:     {docx_path}[/green]")
                summary.add_output(docx_path)
            except Exception:
                try:
                    docx_path = _output_path(config, f"report-{base_name}.docx")
                    markdown_to_docx(
                        md_source,
                        docx_path=docx_path,
                        title=f"Strategic Intelligence: {topic or 'all'}",
                    )
                    console.print(f"[green]DOCX (basic): {docx_path}[/green]")
                    summary.add_output(docx_path)
                except Exception as e2:
                    console.print(f"[yellow]DOCX export failed: {e2}[/yellow]")

    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)

    if result:
        ch_flag = f" -c {channel}" if channel else ""
        console.print("\n  [dim]What's next:[/dim]")
        console.print(
            f"  [dim]  distill findings {topic or 'all'}{ch_flag}              Read the report in terminal[/dim]"
        )
        console.print(
            f"  [dim]  distill export {topic or 'all'}{ch_flag}                Export to DOCX[/dim]"
        )
        console.print(
            f"  [dim]  distill open {topic or 'all'}                          Open output folder[/dim]"
        )

    if not result:
        summary.add_issue(
            "report",
            "Research did not produce results",
            context=topic or "all",
            details={"scope": scope, "channel": channel or "", "research_only": research_only},
        )
        raise typer.Exit(1)


@app.command(rich_help_panel="Reports")
def export(
    topic: str = typer.Argument(help="Topic or channel name", autocompletion=_complete_topics),
    what: str = typer.Option(
        "report", "--what", "-w", help="What to export: report, synthesis, bundle"
    ),
    channel: str | None = typer.Option(None, "--channel", "-c", help="Specific channel"),
    bundle_format: str = typer.Option(
        "bundle", "--format", help="Bundle format for --what bundle: bundle or deepr"
    ),
):
    """Export reports, syntheses, or a portable topic corpus bundle."""
    config = get_config()
    lib = Library(config)
    topic, channel = _resolve_topic_for_channel(lib, topic, channel)

    if what == "bundle":
        topic_dir = config.topic_dir(topic)
        if not topic_dir.exists():
            console.print(f"[yellow]Topic not found: {topic}[/yellow]")
            raise typer.Exit(1)
        files = _collect_topic_bundle_files(config, topic)
        if not files:
            console.print(f"[yellow]No exportable corpus files found for topic: {topic}[/yellow]")
            raise typer.Exit(1)
        zip_path = _export_topic_bundle(config, topic, bundle_format)
        console.print(f"[green]Exported bundle: {zip_path}[/green]")
        console.print(f"[dim]{zip_path.stat().st_size / 1024:.1f} KB[/dim]")
        console.print(f"\n  [dim]distill open {topic}  to inspect the source corpus[/dim]")
        return

    if what == "report":
        if channel:
            md_path = config.channel_dir(topic, channel) / "report.md"
            title = f"Report: {channel}"
        else:
            md_path = config.topic_dir(topic) / "report.md"
            title = f"Strategic Intelligence: {topic}"
    elif what == "synthesis":
        if channel:
            md_path = config.channel_dir(topic, channel) / "synthesis.md"
            title = f"Channel Synthesis: {channel}"
        else:
            md_path = config.topic_dir(topic) / "topic_synthesis.md"
            title = f"Topic Synthesis: {topic}"
    else:
        console.print(f"[red]Unknown export type: {what}. Use: report, synthesis, bundle[/red]")
        raise typer.Exit(1)

    if not md_path.exists():
        console.print(f"[yellow]File not found: {md_path}[/yellow]")
        console.print("[dim]Run the appropriate command first to generate it.[/dim]")
        raise typer.Exit(1)

    # Build output filename from what + topic/channel
    out_name = f"{what}-{topic}-{channel}.docx" if channel else f"{what}-{topic}.docx"
    docx_path = _output_path(config, out_name)

    markdown_to_docx(md_path, docx_path=docx_path, title=title)
    console.print(f"[green]Exported: {docx_path}[/green]")
    console.print(f"[dim]{docx_path.stat().st_size / 1024:.1f} KB[/dim]")
    console.print(f"\n  [dim]distill open {topic}  to open the output folder[/dim]")


@app.command(name="open", rich_help_panel="Maintain")
def open_cmd(
    topic: str = typer.Argument(None, help="Topic or channel name"),
    channel: str | None = typer.Option(None, "--channel", "-c", help="Specific channel"),
    what: str = typer.Option(
        "output",
        "--what",
        "-w",
        help="What to open: output, library, report, synthesis",
    ),
):
    """Open output files or directories in your file explorer.

    Examples:
      distill open                    # Open the output/ directory
      distill open ai                 # Open the ai topic directory
      distill open NateBJones         # Open channel directory (auto-resolves topic)
      distill open --what report ai   # Open the report
    """
    import subprocess

    config = get_config()
    if topic:
        lib = Library(config)
        topic, channel = _resolve_topic_for_channel(lib, topic, channel)

    if what == "output" and not topic:
        target = config.library_dir.parent / "output"
    elif what == "output" and topic:
        target = config.topic_dir(topic)
    elif what == "library":
        target = config.library_dir
    elif what == "report" and topic:
        from distill.research import _get_report_path

        scope = "channel" if channel else "topic"
        target = _get_report_path(topic, config, scope, channel)
    elif what == "synthesis" and topic and channel:
        target = config.channel_dir(topic, channel) / "synthesis.md"
    elif what == "synthesis" and topic:
        target = config.topic_dir(topic) / "topic_synthesis.md"
    else:
        target = config.library_dir.parent / "output"

    if channel and what == "output":
        target = config.channel_dir(topic, channel)

    if not target.exists():
        console.print(f"[yellow]Not found: {target}[/yellow]")
        raise typer.Exit(1)

    console.print(f"Opening [bold]{target}[/bold]")
    if os.name == "nt":
        os.startfile(target)
    else:
        subprocess.run(["open" if os.uname().sysname == "Darwin" else "xdg-open", str(target)])


@app.command(rich_help_panel="Maintain")
def dashboard(
    web: bool = typer.Option(False, "--web", help="Render the dashboard as a local HTML page"),
    open_browser: bool = typer.Option(
        True, "--open/--no-open", help="Open the generated HTML dashboard in your browser"
    ),
):
    """Show the dashboard in terminal or generate a lightweight local web view."""
    config = get_config()
    if not web:
        show_banner(console)
        _show_dashboard()
        return

    snapshot = _dashboard_snapshot(config)
    version = _get_version()
    html = _render_dashboard_html(version, snapshot)
    html_path = _output_path(config, "dashboard.html")
    html_path.write_text(html, encoding="utf-8")
    console.print(f"[green]Dashboard written: {html_path}[/green]")
    if open_browser:
        webbrowser.open(html_path.resolve().as_uri())
        console.print("[dim]Opened in your default browser[/dim]")
    else:
        console.print("[dim]Use --open to launch it in your browser[/dim]")


@app.command(rich_help_panel="View")
def serve(
    port: int = typer.Option(8899, "--port", "-p", help="Port to serve on"),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind to"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open browser on start"),
):
    """Launch a local web dashboard for browsing your library."""
    from distill.web.server import run_server

    run_server(get_config(), host=host, port=port, open_browser=open_browser)


@app.command(rich_help_panel="Maintain")
def costs(
    last: int = typer.Option(10, "--last", "-n", help="Number of recent runs to show"),
):
    """Show cost history from past runs.

    Displays actual vs estimated costs, token usage breakdown, and per-run timing.
    """
    config = get_config()
    log_file = config.library_dir / "cost_log.jsonl"

    if not log_file.exists():
        console.print("[dim]No cost history yet. Costs are logged after each run.[/dim]")
        return

    import json as _json

    entries = []
    for line in log_file.read_text(encoding="utf-8").strip().split("\n"):
        if line.strip():
            try:
                entries.append(_json.loads(line))
            except _json.JSONDecodeError:
                continue

    if not entries:
        console.print("[dim]No cost entries found.[/dim]")
        return

    recent = entries[-last:]

    table = Table(title="Cost History", box=box.ROUNDED, show_header=True)
    table.add_column("Date", style="dim")
    table.add_column("Command")
    table.add_column("Videos", justify="right")
    table.add_column("Shorts", justify="right")
    table.add_column("Actual", justify="right", style="green")
    table.add_column("Tokens (in/out)", justify="right", style="dim")
    table.add_column("Time", justify="right")

    total_cost = 0.0
    for e in recent:
        ts = e.get("timestamp", "")[:10]
        cmd = e.get("command", "?")
        fv = str(e.get("full_videos", 0))
        sh = str(e.get("shorts", 0))
        actual = e.get("actual_cost", 0)
        total_cost += actual
        cost_str = f"${actual:.4f}" if actual < 0.01 else f"${actual:.2f}"
        tokens = f"{e.get('total_input_tokens', 0):,} / {e.get('total_output_tokens', 0):,}"
        elapsed = e.get("elapsed_seconds", 0)
        if elapsed > 60:
            time_str = f"{int(elapsed // 60)}m {int(elapsed % 60)}s"
        else:
            time_str = f"{elapsed:.0f}s"
        table.add_row(ts, cmd, fv, sh, cost_str, tokens, time_str)

    console.print(table)
    console.print(f"\n[bold]Total across {len(recent)} runs: ${total_cost:.4f}[/bold]")

    # Per-call-type breakdown from most recent run
    if recent:
        latest = recent[-1]
        by_type = latest.get("by_call_type", {})
        if by_type:
            console.print("\n[dim]Latest run breakdown:[/dim]")
            for ct, data in sorted(by_type.items()):
                console.print(
                    f"  [dim]{ct}: {data['calls']} calls, {data['input_tokens']:,} in / {data['output_tokens']:,} out[/dim]"
                )


# ─── Status & Doctor ──────────────────────────────────────────────────


@app.command(rich_help_panel="Maintain")
def status(
    online: bool = typer.Option(False, "--online", help="Check YouTube for new videos (slow)"),
):
    """Show library status -- channels, videos, artifacts."""
    config = get_config()
    lib = Library(config)
    _ACCENT = "rgb(100,149,237)"

    topics = lib.get_topics()
    if not topics:
        console.print("[dim]Library is empty[/dim]")
        return

    total_videos = 0
    total_channels = 0

    # ── Show everything instantly (local data only) ───────────
    # Collect channel info for potential online check later
    all_channels: list[tuple[str, object, ChannelState, int]] = []

    for topic in topics:
        channels = lib.get_channels(topic)
        total_channels += len(channels)

        topic_videos = 0
        for ch in channels:
            state = ChannelState(config.channel_dir(topic, ch.name) / "state.json")
            count = state.get_processed_count()
            topic_videos += count
            total_videos += count
            all_channels.append((topic, ch, state, count))

        # Topic header
        ch_count = len(channels)
        ch_label = f"{ch_count} channel{'s' if ch_count != 1 else ''}"
        console.print(
            f"\n  [bold]{topic}[/bold]"
            f"    [dim]{ch_label},"
            f" [{_ACCENT}]{topic_videos}[/{_ACCENT}]"
            f" analyzed[/dim]"
        )

        # Per-channel details
        max_name_len = min(
            max(len(ch.name) for ch in channels) if channels else 0,
            28,
        )
        for ch in channels:
            state = ChannelState(config.channel_dir(topic, ch.name) / "state.json")
            count = state.get_processed_count()
            last = state.get_last_refresh()

            # Artifacts
            ch_dir = config.channel_dir(topic, ch.name)
            artifacts = []
            for a_name, a_file in [
                ("context", "channel_context.md"),
                ("synthesis", "synthesis.md"),
                ("report", "report.md"),
            ]:
                if (ch_dir / a_file).exists():
                    artifacts.append(a_name)

            if last:
                try:
                    dt = datetime.fromisoformat(last)
                    last_str = dt.strftime("%b %d")
                except (ValueError, TypeError):
                    last_str = "?"
            else:
                last_str = "never"

            display_name = (
                ch.name if len(ch.name) <= max_name_len else ch.name[: max_name_len - 2] + ".."
            )
            padding = " " * (max_name_len - len(display_name) + 2)
            art_str = f"  [dim]{', '.join(artifacts)}[/dim]" if artifacts else ""
            console.print(
                f"    {display_name}{padding}"
                f"[{_ACCENT}]{count}[/{_ACCENT}] analyzed"
                f"  [dim]{last_str}[/dim]"
                f"{art_str}"
            )

        # Topic-level outputs with dates
        topic_dir = config.topic_dir(topic)
        topic_outs = []
        for label, fname in [
            ("synthesis", "topic_synthesis.md"),
            ("brief", "brief.md"),
            ("report", "report.md"),
        ]:
            path = topic_dir / fname
            if path.exists():
                mtime = datetime.fromtimestamp(path.stat().st_mtime)
                topic_outs.append(f"{label} ({mtime.strftime('%b %d')})")
        if topic_outs:
            console.print(f"    [dim]{', '.join(topic_outs)}[/dim]")

    # Watch list
    watchlist = lib.get_watchlist()
    if watchlist:
        watched_names = [e.name for e in watchlist]
        console.print(f"\n  [bold]watching[/bold]  [dim]{', '.join(watched_names)}[/dim]")

    # Footer
    console.print(
        f"\n  {total_channels} channel{'s' if total_channels != 1 else ''},"
        f" {total_videos} videos analyzed"
    )

    # ── Optional online check ─────────────────────────────────
    if online:
        console.print()
        lookback = config.distill_default_months
        total_new = 0
        for _topic, ch, state, _count in all_channels:
            with console.status(
                f"  [dim]checking {ch.name}[/dim]",
                spinner="dots",
            ):
                try:
                    available = discover_videos(
                        ch.url,
                        lookback,
                        include_shorts=False,
                        quiet=True,
                    )
                    new_vids = [v for v in available if not state.is_processed(v.video_id)]
                    new_count = len(new_vids)
                except Exception:
                    new_count = -1

            if new_count > 0:
                console.print(f"  [{_ACCENT}]{ch.name}[/{_ACCENT}]  {new_count} new")
                total_new += new_count
            elif new_count == 0:
                console.print(f"  {ch.name}  [dim]up to date[/dim]")

        if total_new == 0:
            console.print("  [dim]all up to date[/dim]")

    console.print()


@app.command(rich_help_panel="Maintain")
def doctor():
    """Check API keys, tools, and library health."""
    _ACCENT = "rgb(100,149,237)"
    config = get_config()

    console.print()
    console.print("  [bold]API Keys[/bold]")
    console.print(f"  [dim]{'-' * 50}[/dim]")

    # XAI/Grok -- required
    if config.xai_api_key:
        try:
            from openai import OpenAI

            client = OpenAI(api_key=config.xai_api_key, base_url="https://api.x.ai/v1")
            client.chat.completions.create(
                model=config.xai_model_for("analysis"),
                messages=[{"role": "user", "content": "hi"}],
                max_completion_tokens=5,
            )
            console.print(
                f"  [green]OK[/green]  XAI_API_KEY       [dim]{config.xai_model_for('analysis')}[/dim]"
            )
        except Exception as e:
            console.print(f"  [red]XX[/red]  XAI_API_KEY       [red]{e!s:.60}[/red]")
    else:
        console.print("  [red]XX[/red]  XAI_API_KEY       [red]NOT SET (required)[/red]")

    # Gemini -- needed for reports
    if config.gemini_api_key:
        try:
            from google import genai

            client = genai.Client(api_key=config.gemini_api_key)
            client.models.generate_content(model="gemini-2.5-flash", contents="hi")
            console.print("  [green]OK[/green]  GEMINI_API_KEY    [dim]Deep Research[/dim]")
        except Exception as e:
            err = str(e)[:60]
            console.print(f"  [red]XX[/red]  GEMINI_API_KEY    [red]{err}[/red]")
    else:
        console.print(
            "  [yellow]--[/yellow]  GEMINI_API_KEY    [dim]not set (needed for reports)[/dim]"
        )

    # OpenAI -- optional
    if config.openai_api_key:
        try:
            from openai import OpenAI

            client = OpenAI(api_key=config.openai_api_key)
            client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=5,
            )
            console.print("  [green]OK[/green]  OPENAI_API_KEY    [dim]optional[/dim]")
        except Exception as e:
            err = str(e)[:60]
            console.print(f"  [red]XX[/red]  OPENAI_API_KEY    [red]{err}[/red]")
    else:
        console.print("  [dim]--  OPENAI_API_KEY    not set (optional)[/dim]")

    # Tools
    console.print()
    console.print("  [bold]Tools[/bold]")
    console.print(f"  [dim]{'-' * 50}[/dim]")

    try:
        import yt_dlp

        console.print(
            f"  [green]OK[/green]  yt-dlp            [dim]v{yt_dlp.version.__version__}[/dim]"
        )
    except Exception:
        console.print("  [red]XX[/red]  yt-dlp            [red]not found[/red]")

    # Playwright
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        console.print("  [green]OK[/green]  playwright        [dim]browser search[/dim]")
    except Exception:
        console.print(
            "  [yellow]--[/yellow]  playwright        [dim]not available (fallback search used)[/dim]"
        )

    # Scribe
    if config.scribe_path and Path(config.scribe_path).exists():
        console.print(f"  [green]OK[/green]  scribe            [dim]{config.scribe_path}[/dim]")
    elif config.scribe_path:
        console.print(
            f"  [red]XX[/red]  scribe            [red]not found at {config.scribe_path}[/red]"
        )
    else:
        console.print("  [dim]--  scribe            not set (optional transcript fallback)[/dim]")

    # Library
    console.print()
    console.print("  [bold]Library[/bold]")
    console.print(f"  [dim]{'-' * 50}[/dim]")

    lib = Library(config)
    topics = lib.get_topics()
    total_ch = sum(len(lib.get_channels(t)) for t in topics)
    watchlist = lib.get_watchlist()
    topic_watchlist = lib.get_topic_watchlist()

    total_vids = 0
    scan_vids = 0
    for t in topics:
        for ch in lib.get_channels(t):
            state_file = config.channel_dir(t, ch.name) / "state.json"
            state = ChannelState(state_file)
            total_vids += state.get_processed_count()
            # Count scan-mode videos
            for vid_id in state._data.get("processed_videos", {}):
                if state.get_analysis_mode(vid_id) == "scan":
                    scan_vids += 1

    console.print(f"  Topics:     [{_ACCENT}]{len(topics)}[/{_ACCENT}]")
    console.print(f"  Channels:   [{_ACCENT}]{total_ch}[/{_ACCENT}]")
    vid_detail = f"[{_ACCENT}]{total_vids}[/{_ACCENT}]"
    if scan_vids:
        vid_detail += f"  [dim]({scan_vids} scan, {total_vids - scan_vids} full)[/dim]"
    console.print(f"  Videos:     {vid_detail}")
    if watchlist:
        w_with_instr = sum(1 for e in watchlist if e.instructions)
        watch_detail = f"[{_ACCENT}]{len(watchlist)}[/{_ACCENT}]"
        if w_with_instr:
            watch_detail += f"  [dim]({w_with_instr} with custom instructions)[/dim]"
        console.print(f"  Watching:   {watch_detail}")
    if topic_watchlist:
        console.print(f"  TopicWatch: [{_ACCENT}]{len(topic_watchlist)}[/{_ACCENT}]")

    # Disk usage
    lib_dir = config.library_dir
    if lib_dir.exists():
        total_size = sum(f.stat().st_size for f in lib_dir.rglob("*") if f.is_file())
        if total_size > 1024 * 1024:
            console.print(f"  Disk:       [dim]{total_size / 1024 / 1024:.1f} MB[/dim]")
        else:
            console.print(f"  Disk:       [dim]{total_size / 1024:.0f} KB[/dim]")

    # Config
    console.print()
    console.print("  [bold]Config[/bold]")
    console.print(f"  [dim]{'-' * 50}[/dim]")
    console.print(
        f"  Lookback:   [dim]{config.distill_default_months} month{'s' if config.distill_default_months != 1 else ''}[/dim]"
    )
    console.print(f"  Library:    [dim]{config.library_dir}[/dim]")
    console.print(f"  Version:    [dim]v{_get_version()}[/dim]")
    console.print()


@app.command(rich_help_panel="Maintain")
def health(
    topic: str = typer.Argument(
        "all",
        help="Topic to audit, or 'all' for the full library",
        autocompletion=_complete_topics,
    ),
):
    """Audit corpus quality signals like stale syntheses and thin artifacts."""
    config = get_config()
    lib = Library(config)
    topics = lib.get_topics() if topic == "all" else [topic]
    warnings = _collect_corpus_health_warnings(config, lib, topics, limit=50)

    console.print()
    console.print("[bold]Corpus Health[/bold]")
    console.print(f"  [dim]scope: {topic}[/dim]")
    console.print()

    if not topics:
        console.print("  [yellow]No topics found to audit[/yellow]")
        return

    if not warnings:
        console.print("  [green]No obvious corpus health issues detected[/green]")
        return

    for item in warnings:
        console.print(f"  [yellow]-[/yellow] {item}")

    console.print()
    console.print(
        "  [dim]Use distill reanalyze / distill resynthesize / distill topic-watch run to refresh weak artifacts[/dim]"
    )


# ─── Cleanup ────────────────────────────────────────────────────────


@app.command(rich_help_panel="Maintain")
def cleanup():
    """List and delete orphaned Gemini File Search stores.

    Stores are normally cleaned up automatically after each report run.
    Use this if a run was interrupted or cleanup failed.
    """
    config = get_config()

    if not config.gemini_api_key:
        console.print("[red]GEMINI_API_KEY required[/red]")
        raise typer.Exit(1)

    from google import genai

    from distill.file_search import cleanup_stores, list_stores

    client = genai.Client(api_key=config.gemini_api_key)

    stores = list_stores(client)
    distill_stores = [s for s in stores if s["display_name"].startswith("distill")]

    if not distill_stores:
        console.print("[green]No orphaned stores found[/green]")
        all_stores = [s for s in stores if not s["display_name"].startswith("distill")]
        if all_stores:
            console.print(f"[dim]({len(all_stores)} non-distill stores exist)[/dim]")
        return

    console.print(f"[bold]Found {len(distill_stores)} distill stores:[/bold]")
    for s in distill_stores:
        console.print(f"  {s['display_name']}  [dim]{s['name']}[/dim]")

    console.print()
    deleted = cleanup_stores(client)
    console.print(f"[green]Deleted {deleted} store(s)[/green]")


# ─── Migration ───────────────────────────────────────────────────────


@app.command(rich_help_panel="Maintain")
def migrate(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Rename video directories from IDs to human-readable slugs.

    Renames directories like 'abc123xyz' to 'gpt-5-4-production-db-safety_abc123xy'.
    Safe to run multiple times -- already-migrated directories are skipped.
    """
    from distill.config import slugify_title

    config = get_config()
    lib = Library(config)
    topics = lib.get_topics()

    if not topics:
        console.print("[dim]Library is empty, nothing to migrate[/dim]")
        return

    # Scan for directories that need migration
    to_rename = []
    for topic in topics:
        for ch in lib.get_channels(topic):
            videos_dir = config.videos_dir(topic, ch.name)
            if not videos_dir.exists():
                continue
            for vid_dir in sorted(videos_dir.iterdir()):
                if not vid_dir.is_dir():
                    continue
                meta_file = vid_dir / "metadata.json"
                if not meta_file.exists():
                    continue
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                video_id = meta.get("video_id", "")
                title = meta.get("title", "")
                if not title or not video_id:
                    continue
                new_name = slugify_title(title, video_id)
                if vid_dir.name != new_name:
                    to_rename.append((vid_dir, vid_dir.parent / new_name, title))

    if not to_rename:
        console.print("[green]All video directories already use readable names[/green]")
        return

    console.print(f"[bold]Found {len(to_rename)} directories to rename:[/bold]\n")
    for old, new, title in to_rename[:10]:
        console.print(f"  [dim]{old.name}[/dim]")
        console.print(f"  [green]->[/green] [bold]{new.name}[/bold]  ({title[:60]})")
        console.print()
    if len(to_rename) > 10:
        console.print(f"  [dim]... and {len(to_rename) - 10} more[/dim]\n")

    if not yes and not typer.confirm(f"Rename {len(to_rename)} directories?"):
        raise typer.Abort()

    renamed = 0
    errors = 0
    for old, new, _title in to_rename:
        try:
            if new.exists():
                console.print(f"  [yellow]Skipping {old.name} -- target already exists[/yellow]")
                continue
            old.rename(new)
            renamed += 1
        except Exception as e:
            console.print(f"  [red]Failed to rename {old.name}: {e}[/red]")
            errors += 1

    console.print(f"\n[bold green]Migrated {renamed} directories[/bold green]")
    if errors:
        console.print(f"[red]{errors} errors[/red]")


# ─── Topic Watch ────────────────────────────────────────────────────

topic_watch_app = typer.Typer(
    help="Manage your recurring topic watches",
    invoke_without_command=True,
    rich_markup_mode="rich",
)
app.add_typer(topic_watch_app, name="topic-watch")


def _topic_watch_name(query: str, topic: str | None, name: str | None) -> str:
    if name:
        return name
    base = topic or _topic_from_query(query)
    return slugify_title(base, max_len=30)


_TOPIC_WATCH_RANKING_ALIASES = {
    "freshness": "freshness",
    "freshness-first": "freshness",
    "fresh": "freshness",
    "balanced": "balanced",
    "balanced-mix": "balanced",
    "popularity": "popularity",
    "popularity-biased": "popularity",
    "popular": "popularity",
}


def _normalize_topic_watch_ranking_mode(value: str) -> str:
    normalized = _TOPIC_WATCH_RANKING_ALIASES.get(value.lower().strip())
    if not normalized:
        allowed = ", ".join(["freshness", "balanced", "popularity"])
        raise typer.BadParameter(f"ranking mode must be one of: {allowed}")
    return normalized


def _topic_watch_ranking_strategy(ranking_mode: str) -> dict[str, object]:
    mode = _normalize_topic_watch_ranking_mode(ranking_mode)
    if mode == "freshness":
        return {"mode": mode, "sort": "date", "rerank": False, "label": "freshness-first"}
    if mode == "popularity":
        return {"mode": mode, "sort": "relevance", "rerank": False, "label": "popularity-biased"}
    return {"mode": "balanced", "sort": "date", "rerank": True, "label": "balanced mix"}


@topic_watch_app.callback()
def topic_watch_default(ctx: typer.Context):
    """Show your topic-watch list."""
    if ctx.invoked_subcommand is not None:
        return
    config = get_config()
    lib = Library(config)
    watchlist = lib.get_topic_watchlist()

    if not watchlist:
        console.print()
        console.print("  [dim]No recurring topics configured[/dim]")
        console.print()
        console.print(
            '    distill topic-watch add "Microsoft AI news" --topic microsoft-news --cadence daily'
        )
        console.print()
        return

    console.print()
    max_name = min(max(len(e.name) for e in watchlist), 24)
    for e in watchlist:
        display_name = e.name if len(e.name) <= max_name else e.name[: max_name - 2] + ".."
        padding = " " * (max_name - len(display_name) + 2)
        mode = "report" if e.report else "learn"
        ranking_label = _topic_watch_ranking_strategy(e.ranking_mode)["label"]
        trend_label = _topic_trend_label(config, e.topic)
        trend_suffix = f" / {trend_label}" if trend_label else ""
        console.print(
            f"  [{_ACCENT}]{display_name}[/{_ACCENT}]{padding}[dim]{e.topic} / {e.cadence} / {e.days}d / {e.limit} picks / {ranking_label} / {mode}{trend_suffix}[/dim]"
        )
        console.print(f"  {' ' * max_name}  [dim]{e.query}[/dim]")

    console.print()
    console.print(f"  [dim]{len(watchlist)} recurring topics  ·  distill topic-watch run[/dim]")
    console.print()


@topic_watch_app.command("add")
def topic_watch_add(
    query: str = typer.Argument(help="Topic query to monitor"),
    name: str | None = typer.Option(None, "--name", help="Stable name for this topic watch"),
    topic: str | None = typer.Option(None, "--topic", "-t", help="Topic to file under"),
    cadence: str = typer.Option("weekly", "--cadence", help="Run cadence: daily or weekly"),
    days: int = typer.Option(7, "--days", "-d", help="Lookback window in days"),
    limit: int = typer.Option(10, "--limit", "-n", help="How many best-pick videos to process"),
    sort: str = typer.Option("date", "--sort", help="Candidate search order: relevance or date"),
    per_channel_cap: int = typer.Option(3, "--channel-cap", help="Max final picks per channel"),
    ranking: str = typer.Option(
        "balanced", "--ranking", help="Ranking mode: freshness, balanced, or popularity"
    ),
    report: bool = typer.Option(
        False, "--report", help="Also generate a full topic report when this watch runs"
    ),
    max_run_cost: float = typer.Option(
        0.0, "--max-run-cost", help="Pause this watch if projected run cost exceeds this amount"
    ),
    monthly_budget: float = typer.Option(
        0.0,
        "--monthly-budget",
        help="Pause this watch if projected 30-day spend exceeds this amount",
    ),
):
    """Add a recurring topic watch for stay-current workflows."""
    if cadence not in {"daily", "weekly"}:
        raise typer.BadParameter("--cadence must be 'daily' or 'weekly'")
    ranking_mode = _normalize_topic_watch_ranking_mode(ranking)
    _validate_learning_options(sort, limit, days, per_channel_cap)

    config = get_config()
    lib = Library(config)
    topic_name = topic or _topic_from_query(query)
    watch_name = _topic_watch_name(query, topic_name, name)
    ranking_strategy = _topic_watch_ranking_strategy(ranking_mode)

    if lib.add_to_topic_watchlist(
        watch_name,
        query,
        topic=topic_name,
        cadence=cadence,
        days=days,
        limit=limit,
        sort=sort,
        channel_cap=per_channel_cap,
        ranking_mode=ranking_mode,
        report=report,
        max_run_cost=max_run_cost,
        monthly_budget=monthly_budget,
    ):
        budget_bits = []
        if max_run_cost:
            budget_bits.append(f"max ${max_run_cost:.2f}/run")
        if monthly_budget:
            budget_bits.append(f"${monthly_budget:.2f}/30d")
        budget_suffix = f" / {', '.join(budget_bits)}" if budget_bits else ""
        console.print(
            f"  Watching topic [{_ACCENT}]{watch_name}[/{_ACCENT}]  [dim]{topic_name} / {cadence} / {days}d / {limit} picks / {ranking_strategy['label']}{budget_suffix}[/dim]"
        )
        console.print(f"  [dim]{query}[/dim]")
        console.print()
        console.print(f"  [dim]distill topic-watch run {watch_name}[/dim]")
    else:
        console.print(f"  [dim]{watch_name} already exists[/dim]")


@topic_watch_app.command("remove")
def topic_watch_remove(
    name: str = typer.Argument(help="Topic-watch name", autocompletion=_complete_topic_watch_names),
):
    """Remove a recurring topic watch."""
    config = get_config()
    lib = Library(config)
    if lib.remove_from_topic_watchlist(name):
        console.print(f"  Removed topic watch {name}")
    else:
        console.print(f"  [red]{name} not found on topic-watch list[/red]")


@topic_watch_app.command("days")
def topic_watch_days(
    name: str = typer.Argument(help="Topic-watch name", autocompletion=_complete_topic_watch_names),
    days: int = typer.Argument(help="Lookback days for this topic watch"),
):
    """Set how far back a topic watch looks."""
    config = get_config()
    lib = Library(config)
    if lib.update_topic_watch_days(name, days):
        console.print(f"  [{_ACCENT}]{name}[/{_ACCENT}]  [dim]{days}d lookback[/dim]")
    else:
        console.print(f"  [red]{name} not found on topic-watch list[/red]")


@topic_watch_app.command("cadence")
def topic_watch_cadence(
    name: str = typer.Argument(help="Topic-watch name", autocompletion=_complete_topic_watch_names),
    cadence: str = typer.Argument(help="daily or weekly"),
):
    """Set cadence for a topic watch."""
    if cadence not in {"daily", "weekly"}:
        raise typer.BadParameter("cadence must be 'daily' or 'weekly'")
    config = get_config()
    lib = Library(config)
    if lib.update_topic_watch_cadence(name, cadence):
        console.print(f"  [{_ACCENT}]{name}[/{_ACCENT}]  [dim]{cadence} cadence[/dim]")
    else:
        console.print(f"  [red]{name} not found on topic-watch list[/red]")


@topic_watch_app.command("ranking")
def topic_watch_ranking(
    name: str = typer.Argument(help="Topic-watch name", autocompletion=_complete_topic_watch_names),
    ranking: str = typer.Argument(help="freshness, balanced, or popularity"),
):
    """Set ranking mode for a topic watch."""
    ranking_mode = _normalize_topic_watch_ranking_mode(ranking)
    ranking_strategy = _topic_watch_ranking_strategy(ranking_mode)
    config = get_config()
    lib = Library(config)
    if lib.update_topic_watch_ranking_mode(name, ranking_mode):
        console.print(f"  [{_ACCENT}]{name}[/{_ACCENT}]  [dim]{ranking_strategy['label']}[/dim]")
    else:
        console.print(f"  [red]{name} not found on topic-watch list[/red]")


@topic_watch_app.command("budget")
def topic_watch_budget(
    name: str = typer.Argument(help="Topic-watch name", autocompletion=_complete_topic_watch_names),
    max_run_cost: float | None = typer.Option(
        None, "--max-run-cost", help="Maximum allowed projected cost for a single run"
    ),
    monthly_budget: float | None = typer.Option(
        None, "--monthly-budget", help="Maximum allowed rolling 30-day spend for this topic"
    ),
):
    """Set budget guardrails for a topic watch."""
    if max_run_cost is None and monthly_budget is None:
        raise typer.BadParameter("Provide --max-run-cost and/or --monthly-budget")
    config = get_config()
    lib = Library(config)
    if lib.update_topic_watch_budget(
        name, max_run_cost=max_run_cost, monthly_budget=monthly_budget
    ):
        parts = []
        if max_run_cost is not None:
            parts.append(f"max-run ${max_run_cost:.2f}")
        if monthly_budget is not None:
            parts.append(f"monthly ${monthly_budget:.2f}")
        console.print(f"  [{_ACCENT}]{name}[/{_ACCENT}]  [dim]{' / '.join(parts)}[/dim]")
    else:
        console.print(f"  [red]{name} not found on topic-watch list[/red]")


@topic_watch_app.command("pause")
def topic_watch_pause(
    name: str = typer.Argument(help="Topic-watch name", autocompletion=_complete_topic_watch_names),
):
    """Pause a topic watch without removing it."""
    config = get_config()
    lib = Library(config)
    if lib.set_topic_watch_paused(name, True):
        console.print(f"  Paused {name}")
    else:
        console.print(f"  [red]{name} not found on topic-watch list[/red]")


@topic_watch_app.command("resume")
def topic_watch_resume(
    name: str = typer.Argument(help="Topic-watch name", autocompletion=_complete_topic_watch_names),
):
    """Resume a paused topic watch."""
    config = get_config()
    lib = Library(config)
    if lib.set_topic_watch_paused(name, False):
        console.print(f"  Resumed {name}")
    else:
        console.print(f"  [red]{name} not found on topic-watch list[/red]")


@topic_watch_app.command("run")
def topic_watch_run(
    name: str | None = typer.Argument(
        None, help="Topic-watch name to run", autocompletion=_complete_topic_watch_names
    ),
    topic: str | None = typer.Option(
        None,
        "--topic",
        "-t",
        help="Only run topic watches in this topic",
        autocompletion=_complete_topics,
    ),
    preview: bool = typer.Option(
        False, "--preview", help="Preview the selected best-pick videos without processing"
    ),
    ignore_budget: bool = typer.Option(
        False, "--ignore-budget", help="Run even if budget guardrails would skip the watch"
    ),
):
    """Run recurring topic watches using the existing topic-learning pipeline."""
    config = get_config()
    _require_api_key(config.xai_api_key, "XAI_API_KEY required")
    lib = Library(config)
    watchlist = lib.get_topic_watchlist()

    if not watchlist:
        console.print("  [dim]Topic-watch list is empty. Add topics with:[/dim]")
        console.print(
            '    distill topic-watch add "Microsoft AI news" --topic microsoft-news --cadence daily'
        )
        return

    if name:
        match = [e for e in watchlist if e.name.lower() == name.lower()]
        if not match:
            console.print(f"  [red]{name} not on topic-watch list[/red]")
            return
        watchlist = match

    if topic:
        watchlist = [e for e in watchlist if e.topic.lower() == topic.lower()]
        if not watchlist:
            console.print(f"  [red]No watched topics in topic '{topic}'[/red]")
            return

    all_cost_entries = _load_all_cost_runs(config.library_dir / "cost_log.jsonl")
    generated_alerts: list[str] = []
    alert_generated_at = datetime.now()

    for entry in watchlist:
        ranking = _topic_watch_ranking_strategy(entry.ranking_mode)
        console.print()
        console.print(
            f"[bold]Topic Watch: {entry.name}[/bold] [dim]({entry.topic} / {entry.cadence} / {entry.days}d / {entry.limit} picks / {ranking['label']})[/dim]"
        )
        if entry.paused:
            console.print(
                "  [yellow]Paused[/yellow] [dim]resume with: distill topic-watch resume "
                f"{entry.name}[/dim]"
            )
            continue
        budget_messages = _topic_watch_budget_messages(entry, all_cost_entries)
        if budget_messages and not ignore_budget:
            console.print(f"  [yellow]Budget guardrail[/yellow] {budget_messages[0]}")
            console.print(f"  [dim]distill topic-watch run {entry.name} --ignore-budget[/dim]")
            continue
        if preview:
            _preview_learning_selection(
                entry.query,
                days=entry.days,
                limit=entry.limit,
                sort=str(ranking["sort"]),
                per_channel_cap=entry.channel_cap,
                shorts=False,
                rerank=bool(ranking["rerank"]),
                header=f"Topic Watch Preview: {entry.name}",
                table_title=f"Selected Learning Set: {entry.name}",
            )
            continue

        previous_run_at = _parse_run_datetime(entry.last_run_at)
        _run_learning_command(
            entry.query,
            topic=entry.topic,
            days=entry.days,
            limit=entry.limit,
            sort=str(ranking["sort"]),
            per_channel_cap=entry.channel_cap,
            shorts=False,
            rerank=bool(ranking["rerank"]),
            save=True,
            report=entry.report,
            test=False,
            generate_brief=False,
            header=f"Topic Watch: {entry.name}",
        )
        change_details = _collect_topic_change_details(
            config,
            lib,
            entry.topic,
            previous_run_at,
        )
        change_summary = str(change_details.get("summary", "no recent change detected"))
        briefing_path = _write_topic_change_briefing(
            config,
            watch_name=entry.name,
            topic=entry.topic,
            query=entry.query,
            cadence=entry.cadence,
            baseline=previous_run_at,
            summary=change_summary,
            change_details=change_details,
        )
        trend_label = _topic_trend_label(config, entry.topic)
        alert_lines = _topic_watch_alert_lines(
            watch_name=entry.name,
            topic=entry.topic,
            ranking_label=str(ranking["label"]),
            summary=change_summary,
            change_details=change_details,
            trend_label=trend_label,
        )
        if alert_lines:
            generated_alerts.extend(alert_lines)
        console.print(f"  [cyan]Update[/cyan] {change_summary}")
        if trend_label:
            console.print(f"  [dim]{trend_label}[/dim]")
        console.print(f"  [dim]{briefing_path}[/dim]")
        lib.mark_topic_watch_run(entry.name, datetime.now().isoformat())

    alerts_path = _write_watch_alert_digest(
        config,
        generated_at=alert_generated_at,
        alert_lines=generated_alerts,
    )
    if generated_alerts:
        console.print()
        console.print("[bold yellow]Watch Alerts[/bold yellow]")
        for line in generated_alerts[:8]:
            console.print(f"  {line}")
        if len(generated_alerts) > 8:
            console.print(f"  [dim]...and {len(generated_alerts) - 8} more[/dim]")
    else:
        console.print()
        console.print("[dim]No notable watch alerts in this run.[/dim]")
    console.print(f"  [dim]{alerts_path}[/dim]")


@app.command(name="monitor", rich_help_panel="Discover")
def monitor(
    query: str = typer.Argument(help="Topic query to monitor on a recurring cadence"),
    topic: str = typer.Option("", "--topic", "-t", help="Topic to file under"),
    name: str = typer.Option("", "--name", help="Explicit watch name"),
    cadence: str = typer.Option("daily", "--cadence", help="Run cadence: daily or weekly"),
    days: int = typer.Option(1, "--days", "-d", help="Lookback window in days"),
    limit: int = typer.Option(10, "--limit", "-n", help="How many best-pick videos to process"),
    sort: str = typer.Option("date", "--sort", help="Candidate search order: relevance or date"),
    per_channel_cap: int = typer.Option(3, "--channel-cap", help="Max final picks per channel"),
    ranking: str = typer.Option(
        "balanced", "--ranking", help="Ranking mode: freshness, balanced, or popularity"
    ),
    report: bool = typer.Option(
        False, "--report", help="Also generate a full topic report when this watch runs"
    ),
    max_run_cost: float = typer.Option(
        0.0, "--max-run-cost", help="Pause this watch if projected run cost exceeds this amount"
    ),
    monthly_budget: float = typer.Option(
        0.0,
        "--monthly-budget",
        help="Pause this watch if projected 30-day spend exceeds this amount",
    ),
    now: bool = typer.Option(False, "--now", help="Run the watch immediately after creating it"),
    preview: bool = typer.Option(
        False, "--preview", help="Preview the selected best-pick videos instead of processing"
    ),
):
    """Create a recurring topic monitor with optional immediate run."""
    if cadence not in {"daily", "weekly"}:
        raise typer.BadParameter("--cadence must be 'daily' or 'weekly'")
    ranking_mode = _normalize_topic_watch_ranking_mode(ranking)
    _validate_learning_options(sort, limit, days, per_channel_cap)

    config = get_config()
    lib = Library(config)
    topic_name = topic or _topic_from_query(query)
    watch_name = _topic_watch_name(query, topic_name, name or None)
    ranking_strategy = _topic_watch_ranking_strategy(ranking_mode)

    created = lib.add_to_topic_watchlist(
        watch_name,
        query,
        topic=topic_name,
        cadence=cadence,
        days=days,
        limit=limit,
        sort=sort,
        channel_cap=per_channel_cap,
        ranking_mode=ranking_mode,
        report=report,
        max_run_cost=max_run_cost,
        monthly_budget=monthly_budget,
    )
    if created:
        console.print(
            f"  Monitoring [{_ACCENT}]{watch_name}[/{_ACCENT}]  [dim]{topic_name} / {cadence} / {days}d / {limit} picks / {ranking_strategy['label']}[/dim]"
        )
        console.print(f"  [dim]{query}[/dim]")
    else:
        console.print(f"  [dim]{watch_name} already exists; using existing watch[/dim]")

    if preview:
        _preview_learning_selection(
            query,
            days=days,
            limit=limit,
            sort=str(ranking_strategy["sort"]),
            per_channel_cap=per_channel_cap,
            shorts=False,
            rerank=bool(ranking_strategy["rerank"]),
            header=f"Monitor Preview: {watch_name}",
            table_title=f"Selected Learning Set: {watch_name}",
        )
        return

    if now:
        topic_watch_run(name=watch_name, preview=False, topic=None, ignore_budget=False)
    else:
        console.print()
        console.print(f"  [dim]distill topic-watch run {watch_name}[/dim]")


@app.command(name="ramp-up", rich_help_panel="Discover")
def ramp_up(
    target: str = typer.Argument(help="YouTube query, website URL, or website seed file"),
    topic: str = typer.Option("", "--topic", "-t", help="Topic to file under"),
    source: str = typer.Option("auto", "--source", help="auto, youtube, or website"),
    report: bool = typer.Option(False, "--report", help="Generate a report after processing"),
    days: int = typer.Option(14, "--days", "-d", help="YouTube lookback window in days"),
    limit: int = typer.Option(10, "--limit", "-n", help="YouTube best-pick count"),
    seed_only: bool = typer.Option(
        True, "--seed-only/--crawl", help="For websites, keep to exact seed URLs by default"
    ),
    scrape_only: bool = typer.Option(
        False, "--scrape-only", help="For websites, save raw artifacts only"
    ),
    ingest_attachments: bool = typer.Option(
        False,
        "--ingest-attachments",
        help="For websites, pull PDF text and supported embedded video transcripts into the page corpus",
    ),
    test: bool = typer.Option(False, "--test", help="Pass --test through to report generation"),
):
    """Intent-first entry point for learning a source set quickly."""
    resolved_source = source
    if source == "auto":
        resolved_source = _detect_ramp_source(target)
    elif source == "youtube":
        resolved_source = "youtube-query"
    elif source == "website":
        resolved_source = "website-batch" if Path(target).exists() else "website"
    elif source == "paper":
        resolved_source = "paper"
    else:
        raise typer.BadParameter("--source must be auto, youtube, website, or paper")

    if resolved_source in {"youtube-query", "youtube-url"}:
        _run_learning_command(
            target,
            topic=topic or _topic_from_query(target),
            days=days,
            limit=limit,
            sort="date",
            per_channel_cap=3,
            shorts=False,
            rerank=True,
            save=True,
            report=report,
            test=test,
            generate_brief=False,
            header="Ramp-Up",
        )
        return

    if resolved_source == "paper":
        if "arxiv.org" in target.lower() or re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", target):
            paper(target=target, topic=topic or "papers")
        else:
            papers(query=target, topic=topic or _topic_from_query(target), limit=limit)
        return

    if resolved_source == "website":
        site_cmd(
            url=target,
            topic=topic or "web",
            name="",
            max_depth=1,
            max_pages=8,
            same_section_only=False,
            scrape_only=scrape_only,
            seed_only=seed_only,
            ingest_attachments=ingest_attachments,
            report=report,
            test=test,
        )
        return

    site_batch_cmd(
        path=Path(target),
        topic=topic or "",
        scrape_only=scrape_only,
        seed_only=seed_only,
        same_section_only=False,
        ingest_attachments=ingest_attachments,
        report=report,
        test=test,
    )


# ─── Watch List ──────────────────────────────────────────────────────

watch_app = typer.Typer(
    help="Manage your channel watch list",
    invoke_without_command=True,
    rich_markup_mode="rich",
)
app.add_typer(watch_app, name="watch")

_ACCENT = "rgb(100,149,237)"


@watch_app.callback()
def watch_default(ctx: typer.Context):
    """Show your watch list."""
    if ctx.invoked_subcommand is not None:
        return
    config = get_config()
    lib = Library(config)
    watchlist = lib.get_watchlist()

    if not watchlist:
        console.print()
        console.print("  [dim]No channels on your watch list[/dim]")
        console.print()
        console.print("    distill watch add <url>")
        console.print("    distill watch add <url> --topic ai")
        console.print('    distill watch add <url> --instructions "Extract the best deals..."')
        console.print()
        return

    console.print()
    max_name = min(max(len(e.name) for e in watchlist), 28)
    for e in watchlist:
        display_name = e.name if len(e.name) <= max_name else e.name[: max_name - 2] + ".."
        padding = " " * (max_name - len(display_name) + 2)
        console.print(
            f"  [{_ACCENT}]{display_name}[/{_ACCENT}]{padding}[dim]{e.topic} / {e.days}d[/dim]"
        )
        if e.instructions:
            # Show first 60 chars of instructions
            preview = e.instructions[:57] + "..." if len(e.instructions) > 60 else e.instructions
            console.print(f"  {' ' * max_name}  [dim]{preview}[/dim]")

    console.print()
    console.print(f"  [dim]{len(watchlist)} watched  ·  distill catch-up to refresh[/dim]")
    console.print()


@watch_app.command("add")
def watch_add(
    url: str = typer.Argument(help="YouTube channel URL"),
    topic: str = typer.Option("watch", "--topic", "-t", help="Topic to file under"),
    days_opt: int = typer.Option(
        14, "--days", "-d", help="Lookback days for catch-up (default 14)"
    ),
    instructions: str = typer.Option(
        "",
        "--instructions",
        "-i",
        help="Custom analysis instructions for this channel",
    ),
):
    """Add a channel to your watch list.

    Examples:
      distill watch add https://www.youtube.com/@NateBJones
      distill watch add https://www.youtube.com/@Smokemon07 --days 2 --instructions "Extract top deals"
    """
    config = get_config()
    lib = Library(config)
    name = resolve_channel_name(url)

    # Auto-generate smart instructions if none provided
    if not instructions and config.xai_api_key:
        with console.status(
            f"  {name}  [dim]generating analysis focus[/dim]",
            spinner="dots",
        ):
            try:
                vids = discover_videos(url, months=1, quiet=True)
                if vids:
                    titles = [v.title for v in vids[:15]]
                    from distill.analysis import (
                        generate_watch_instructions,
                    )

                    auto = generate_watch_instructions(name, titles, config)
                    if auto and auto.strip():
                        instructions = auto.strip()
            except Exception:
                pass  # Fall through with no instructions

    if lib.add_to_watchlist(url, name, topic=topic, instructions=instructions, days=days_opt):
        console.print(f"  Watching [{_ACCENT}]{name}[/{_ACCENT}]  [dim]{topic} / {days_opt}d[/dim]")
        if instructions:
            console.print(f"  [dim]Focus: {instructions[:100]}[/dim]")
        console.print()
        console.print(
            f"  [dim]distill catch-up {name}                    Scan for new videos now[/dim]"
        )
        console.print(
            f'  [dim]distill watch instructions {name} "..."    Change analysis focus[/dim]'
        )
        console.print(
            f"  [dim]distill watch days {name} {days_opt}                  Change lookback window[/dim]"
        )
    else:
        console.print(f"  [dim]{name} already on watch list[/dim]")


@watch_app.command("remove")
def watch_remove(
    name: str = typer.Argument(
        help="Channel name to remove", autocompletion=_complete_watched_channels
    ),
):
    """Remove a channel from your watch list."""
    config = get_config()
    lib = Library(config)
    if lib.remove_from_watchlist(name):
        console.print(f"  Removed {name} from watch list")
    else:
        console.print(f"  [red]{name} not found on watch list[/red]")


@watch_app.command("instructions")
def watch_instructions(
    name: str = typer.Argument(help="Channel name", autocompletion=_complete_watched_channels),
    instructions: str = typer.Argument(help="New custom instructions (use quotes)"),
):
    """Set or update custom analysis instructions for a watched channel.

    Examples:
      distill watch instructions Smokemon07 "Extract top 10 deals with prices, links, and why each is a good deal"
    """
    config = get_config()
    lib = Library(config)
    if lib.update_watch_instructions(name, instructions):
        console.print(f"  Updated instructions for [{_ACCENT}]{name}[/{_ACCENT}]")
        console.print(f"  [dim]{instructions[:80]}[/dim]")
    else:
        console.print(f"  [red]{name} not found on watch list[/red]")


@watch_app.command("days")
def watch_days(
    name: str = typer.Argument(help="Channel name", autocompletion=_complete_watched_channels),
    days: int = typer.Argument(help="Lookback days for catch-up"),
):
    """Set how far back catch-up looks for a channel.

    Examples:
      distill watch days Smokemon07 2
      distill watch days "Guy in a Cube" 14
    """
    config = get_config()
    lib = Library(config)
    if lib.update_watch_days(name, days):
        console.print(f"  [{_ACCENT}]{name}[/{_ACCENT}]  [dim]{days}d lookback[/dim]")
    else:
        console.print(f"  [red]{name} not found on watch list[/red]")


# ─── Catch-Up ────────────────────────────────────────────────────────


@app.command(name="catch-up", rich_help_panel="Watch")
def catch_up(
    channel: str | None = typer.Argument(
        None,
        help="Channel name to refresh (default: all)",
        autocompletion=_complete_watched_channels,
    ),
    topic: str | None = typer.Option(
        None,
        "--topic",
        "-t",
        help="Only refresh channels in this topic",
        autocompletion=_complete_topics,
    ),
    days_override: int | None = typer.Option(None, "--days", "-d", help="Override lookback days"),
    limit: int | None = typer.Option(None, "--limit", "-n", help="Max videos per channel"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without processing"),
    shorts: bool = typer.Option(True, "--shorts/--no-shorts", help="Include Shorts"),
):
    """Refresh watched channels with lightweight scan analysis.

    Run with no arguments to refresh all watched channels.
    Filter by channel name or topic.

    Examples:
      distill catch-up
      distill catch-up Smokemon07
      distill catch-up --topic ai
      distill catch-up --topic deals --days 1
      distill catch-up --dry-run
    """
    config = get_config()
    _require_api_key(config.xai_api_key, "XAI_API_KEY required")
    lib = Library(config)
    watchlist = lib.get_watchlist()

    if not watchlist:
        console.print("  [dim]Watch list is empty. Add channels with:[/dim]")
        console.print("    distill watch add <url>")
        return

    # Filter by channel name
    if channel:
        match = [e for e in watchlist if e.name.lower() == channel.lower()]
        if not match:
            console.print(f"  [red]{channel} not on watch list[/red]")
            console.print("  [dim]distill watch to see your list[/dim]")
            return
        watchlist = match

    # Filter by topic
    if topic:
        watchlist = [e for e in watchlist if e.topic.lower() == topic.lower()]
        if not watchlist:
            console.print(f"  [red]No watched channels in topic '{topic}'[/red]")
            return
    tracker = CostTracker()
    summary = RunSummary(command="catch-up")

    # Discover + process per channel (live updates)
    console.print()
    topics_touched: set[str] = set()

    for entry in watchlist:
        ch_days = days_override if days_override is not None else entry.days

        # ── Discovery ─────────────────────────────────────────
        videos = None
        with console.status(
            f"  {entry.name}  [dim]checking past {ch_days}d[/dim]",
            spinner="dots",
        ):
            try:
                videos = discover_videos(
                    entry.url,
                    days=ch_days,
                    include_shorts=shorts,
                    quiet=True,
                )
            except Exception as exc:
                console.print(
                    f"  [{_ACCENT}]{entry.name}[/{_ACCENT}]  [red]discovery failed: {exc}[/red]"
                )

        if videos is None:
            continue

        state = ChannelState(config.channel_dir(entry.topic, entry.name) / "state.json")
        new_vids = [v for v in videos if not state.is_processed(v.video_id)]
        if limit:
            new_vids = new_vids[:limit]

        if not new_vids:
            total = len(videos)
            console.print(
                f"  [{_ACCENT}]{entry.name}[/{_ACCENT}]  [dim]up to date"
                f"  ({total} checked, past {ch_days}d)[/dim]"
            )
            # Single-channel catch-up: show latest insights inline
            if channel:
                _show_latest_insights(config, entry.topic, entry.name, limit=3)
            continue

        # ── Show what we found ────────────────────────────────
        console.print(f"  [{_ACCENT}]{entry.name}[/{_ACCENT}]  {len(new_vids)} new")
        for v in new_vids[:5]:
            console.print(f"    [dim]{v.title[:65]}[/dim]")
        if len(new_vids) > 5:
            console.print(f"    [dim]...and {len(new_vids) - 5} more[/dim]")

        if dry_run:
            scan_count = sum(1 for v in new_vids if v.duration > SHORTS_THRESHOLD)
            short_count = sum(1 for v in new_vids if v.duration <= SHORTS_THRESHOLD)
            display_estimate(
                scan_videos=scan_count,
                shorts=short_count,
                console=console,
            )
            continue

        # ── Process each video ────────────────────────────────
        _ensure_channel_context(entry.topic, entry.name, new_vids, config, tracker)
        eta = ETATracker(total=len(new_vids))

        for i, vid in enumerate(new_vids, 1):
            title = vid.title[:55] if len(vid.title) > 55 else vid.title
            eta_hint = f"  [dim]{eta.eta_str}[/dim]" if eta.eta_str else ""
            console.print(
                f"    [{i}/{len(new_vids)}] {title}"
                f"  [dim]{_duration_str(vid.duration)}[/dim]{eta_hint}"
            )
            _process_video(
                entry.topic,
                entry.name,
                vid,
                config,
                tracker,
                summary,
                state=state,
                analysis_mode="scan",
                custom_instructions=entry.instructions,
                eta=eta,
            )

        # ── Synthesize ────────────────────────────────────────
        with console.status(
            f"    [dim]synthesizing {entry.name}[/dim]",
            spinner="dots",
        ):
            try:
                synthesize_channel(entry.topic, entry.name, config, tracker=tracker)
                synth_file = config.channel_dir(entry.topic, entry.name) / "synthesis.md"
                cli_shared.record_output_or_issue(
                    summary,
                    synth_file,
                    stage="channel-synthesis",
                    context=f"{entry.topic}/{entry.name}",
                    details={"topic": entry.topic, "channel": entry.name},
                    missing_message="No synthesis output written",
                )
            except Exception as e:
                console.print(f"    [red]synthesis failed: {e}[/red]")
                cli_shared.record_exception_issue(
                    summary,
                    stage="channel-synthesis",
                    exc=e,
                    context=f"{entry.topic}/{entry.name}",
                    details={"topic": entry.topic, "channel": entry.name},
                )

        topics_touched.add(entry.topic)

    # Synthesize each topic
    for topic in topics_touched:
        with console.status(
            f"  [dim]synthesizing topic '{topic}'[/dim]",
            spinner="dots",
        ):
            try:
                synthesize_topic(topic, config, tracker=tracker)
                topic_synth = config.topic_dir(topic) / "topic_synthesis.md"
                cli_shared.record_output_or_issue(
                    summary,
                    topic_synth,
                    stage="topic-synthesis",
                    context=topic,
                    details={"topic": topic},
                    missing_message="No topic synthesis output written",
                )
            except Exception as e:
                console.print(f"  [red]topic synthesis failed: {e}[/red]")
                cli_shared.record_exception_issue(
                    summary,
                    stage="topic-synthesis",
                    exc=e,
                    context=topic,
                    details={"topic": topic},
                )

    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)

    # Single-channel catch-up with new videos: show the new insights inline
    if channel and topics_touched:
        entry_match = [e for e in lib.get_watchlist() if e.name.lower() == channel.lower()]
        if entry_match:
            _show_latest_insights(config, entry_match[0].topic, entry_match[0].name, limit=5)
    elif topics_touched:
        t_example = next(iter(topics_touched))
        console.print("\n  [dim]What's next:[/dim]")
        console.print(
            f"  [dim]  distill show {t_example}                       View video insights[/dim]"
        )
        console.print(
            f"  [dim]  distill synthesis {t_example}                  Read the synthesis[/dim]"
        )
        console.print("  [dim]  distill costs                               Review spending[/dim]")


@app.command(rich_help_panel="Maintain")
def resynthesize(
    topic: str = typer.Argument(help="Topic or channel name", autocompletion=_complete_topics),
    channel: str | None = typer.Option(None, "--channel", "-c", help="Limit to one channel"),
):
    """Regenerate synthesis from existing insights -- no re-analysis.

    Rebuilds channel synthesis and topic synthesis from the insights.md files
    already on disk. Fast and cheap -- useful after manual edits or to refresh
    synthesis with updated prompts.

    Examples:
      distill resynthesize ai
      distill resynthesize NateBJones
    """
    config = get_config()
    _require_api_key(config.xai_api_key, "XAI_API_KEY required")
    lib = Library(config)
    topic, channel = _resolve_topic_for_channel(lib, topic, channel)

    channels = lib.get_channels(topic)
    if not channels:
        console.print(f"[red]No channels found for topic '{topic}'[/red]")
        raise typer.Exit(1)
    if channel:
        channels = [ch for ch in channels if ch.name == channel]
        if not channels:
            console.print(f"[red]Channel '{channel}' not found in topic '{topic}'[/red]")
            raise typer.Exit(1)

    # synthesis_calls = 1 per channel + 1 for topic
    num_calls = len(channels) + 1
    display_estimate(synthesis_calls=num_calls, console=console)

    tracker = CostTracker()
    summary = RunSummary(command="resynthesize")

    for ch in channels:
        console.print(f"  Synthesizing [bold]{ch.name}[/bold]...")
        try:
            synthesize_channel(topic, ch.name, config, tracker=tracker)
            synth_file = config.channel_dir(topic, ch.name) / "synthesis.md"
            ok = cli_shared.record_output_or_issue(
                summary,
                synth_file,
                stage="channel-synthesis",
                context=f"{topic}/{ch.name}",
                details={"topic": topic, "channel": ch.name},
                missing_message="No synthesis output written",
            )
            console.print("  [dim]done[/dim]" if ok else "  [yellow]no synthesis output[/yellow]")
        except Exception as e:
            console.print(f"  [red]Failed: {e}[/red]")
            cli_shared.record_exception_issue(
                summary,
                stage="channel-synthesis",
                exc=e,
                context=f"{topic}/{ch.name}",
                details={"topic": topic, "channel": ch.name},
            )

    console.print(f"  Synthesizing topic [bold]{topic}[/bold]...")
    try:
        synthesize_topic(topic, config, tracker=tracker)
        topic_synth = config.topic_dir(topic) / "topic_synthesis.md"
        ok = cli_shared.record_output_or_issue(
            summary,
            topic_synth,
            stage="topic-synthesis",
            context=topic,
            details={"topic": topic},
            missing_message="No topic synthesis output written",
        )
        console.print("  [dim]done[/dim]" if ok else "  [yellow]no topic synthesis output[/yellow]")
    except Exception as e:
        console.print(f"  [red]Topic synthesis failed: {e}[/red]")
        cli_shared.record_exception_issue(
            summary,
            stage="topic-synthesis",
            exc=e,
            context=topic,
            details={"topic": topic},
        )

    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)


@app.command(rich_help_panel="Maintain")
def reanalyze(
    topic: str = typer.Argument(help="Topic or channel name", autocompletion=_complete_topics),
    channel: str | None = typer.Option(None, "--channel", "-c", help="Limit to one channel"),
    deep: bool = typer.Option(
        False, "--deep", help="Only upgrade scan-analyzed videos to full 2-pass"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be reanalyzed"),
):
    """Re-run Grok analysis on existing transcripts -- skip re-downloading.

    Walks all video directories that have a transcript.txt, re-runs the
    2-pass (full) or 1-pass (Short) analysis, overwrites insights.md,
    then resynthesizes channel and topic.

    Use --deep to upgrade only scan-analyzed videos to full 2-pass analysis.

    Examples:
      distill reanalyze ai
      distill reanalyze NateBJones --deep
      distill reanalyze ai --dry-run
    """
    config = get_config()
    _require_api_key(config.xai_api_key, "XAI_API_KEY required")
    lib = Library(config)
    topic, channel = _resolve_topic_for_channel(lib, topic, channel)

    channels = lib.get_channels(topic)
    if not channels:
        console.print(f"[red]No channels found for topic '{topic}'[/red]")
        raise typer.Exit(1)
    if channel:
        channels = [ch for ch in channels if ch.name == channel]
        if not channels:
            console.print(f"[red]Channel '{channel}' not found in topic '{topic}'[/red]")
            raise typer.Exit(1)

    # Scan for videos with transcripts
    all_videos = []  # (channel_name, vid_dir, metadata, is_short)
    for ch in channels:
        vdir = config.videos_dir(topic, ch.name)
        if not vdir.exists():
            continue
        for d in sorted(vdir.iterdir()):
            if not d.is_dir():
                continue
            transcript = d / "transcript.txt"
            meta_file = d / "metadata.json"
            if not transcript.exists() or transcript.stat().st_size == 0:
                continue
            meta = {}
            if meta_file.exists():
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            duration = meta.get("duration", 0)
            is_short = duration <= SHORTS_THRESHOLD
            all_videos.append((ch.name, d, meta, is_short))

    # --deep: only upgrade scan-analyzed videos to full 2-pass
    if deep:
        all_videos = [
            (ch_name, d, meta, is_s)
            for ch_name, d, meta, is_s in all_videos
            if meta.get("analysis_mode") == "scan" and not is_s
        ]

    if not all_videos:
        msg = "No scan-analyzed videos to upgrade" if deep else "No videos with transcripts found"
        console.print(f"[dim]{msg}[/dim]")
        return

    full_count = sum(1 for _, _, _, s in all_videos if not s)
    short_count = sum(1 for _, _, _, s in all_videos if s)

    if dry_run:
        console.print()
        for _ch_name, vid_dir, meta, is_short in all_videos:
            title = meta.get("title", vid_dir.name)[:65]
            kind = "[dim](Short)[/dim]" if is_short else ""
            date = _format_date(meta.get("upload_date", ""))
            console.print(f"  {date}  {title} {kind}")
        console.print()
        console.print(
            f"  [{full_count} full + {short_count} Shorts]  ·  "
            f"[dim]{estimate_run_cost(full_count, short_count)}[/dim]"
        )
        return

    display_estimate(full_count, short_count, console=console)

    tracker = CostTracker()
    summary = RunSummary(command="reanalyze")
    current_channel = None

    for ch_name, vid_dir, meta, is_short in all_videos:
        if ch_name != current_channel:
            current_channel = ch_name
            console.print(f"\n  [bold]{ch_name}[/bold]")

        title = meta.get("title", vid_dir.name)
        upload_date = meta.get("upload_date", "")
        transcript = (vid_dir / "transcript.txt").read_text(encoding="utf-8")

        label = "Short" if is_short else "Analyzing"
        console.print(f"    {label}: {title[:60]}...")

        try:
            if is_short:
                insights = analyze_short(
                    title, upload_date, ch_name, transcript, config, tracker=tracker
                )
            else:
                insights = analyze_video(
                    title, upload_date, ch_name, transcript, config, tracker=tracker
                )
            (vid_dir / "insights.md").write_text(insights, encoding="utf-8")
            summary.add_result(
                VideoResult(
                    meta.get("video_id", vid_dir.name),
                    title,
                    True,
                    is_short=is_short,
                )
            )
        except Exception as e:
            console.print(f"    [red]Failed: {e}[/red]")
            summary.add_result(
                VideoResult(
                    meta.get("video_id", vid_dir.name),
                    title,
                    False,
                    is_short=is_short,
                    error=str(e),
                )
            )

    # Resynthesize after all analysis
    for ch in channels:
        console.print(f"\n  Synthesizing {ch.name}...")
        try:
            synthesize_channel(topic, ch.name, config, tracker=tracker)
            synth_file = config.channel_dir(topic, ch.name) / "synthesis.md"
            cli_shared.record_output_or_issue(
                summary,
                synth_file,
                stage="channel-synthesis",
                context=f"{topic}/{ch.name}",
                details={"topic": topic, "channel": ch.name},
                missing_message="No synthesis output written",
            )
        except Exception as e:
            console.print(f"  [red]Synthesis failed: {e}[/red]")
            cli_shared.record_exception_issue(
                summary,
                stage="channel-synthesis",
                exc=e,
                context=f"{topic}/{ch.name}",
                details={"topic": topic, "channel": ch.name},
            )

    console.print(f"\n  Synthesizing topic '{topic}'...")
    try:
        synthesize_topic(topic, config, tracker=tracker)
        topic_synth = config.topic_dir(topic) / "topic_synthesis.md"
        cli_shared.record_output_or_issue(
            summary,
            topic_synth,
            stage="topic-synthesis",
            context=topic,
            details={"topic": topic},
            missing_message="No topic synthesis output written",
        )
    except Exception as e:
        console.print(f"  [red]Topic synthesis failed: {e}[/red]")
        cli_shared.record_exception_issue(
            summary,
            stage="topic-synthesis",
            exc=e,
            context=topic,
            details={"topic": topic},
        )

    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)


def _process_site_seed(
    seed: SiteSeed,
    config: DistillConfig,
    tracker: CostTracker,
    summary: RunSummary,
    scrape_only: bool = False,
    ingest_attachments: bool = False,
) -> tuple[str, int]:
    site_name = seed.resolved_site_name()
    mode_label = "scrape-only" if scrape_only else "full"
    console.print(f"\n[bold]Site: {site_name}[/bold]")
    console.print(
        f"[dim]Seed: {seed.url} | max_pages={seed.max_pages} depth={seed.max_depth} mode={mode_label} | attachments={'on' if ingest_attachments else 'inventory-only'}[/dim]"
    )

    pages = crawl_site(seed)
    if not pages:
        summary.add_issue(
            "site-crawl",
            "No pages were extracted from the site.",
            context=seed.url,
            details={"site": site_name, "topic": seed.topic, "scrape_only": scrape_only},
        )
        return site_name, 0

    site_dir = config.site_dir(seed.topic, site_name)
    pages_dir = config.site_pages_dir(seed.topic, site_name)
    pages_dir.mkdir(parents=True, exist_ok=True)
    site_manifest_path = site_dir / "site.json"
    previous_manifest = _load_site_manifest(site_manifest_path)
    crawled_at = datetime.now().isoformat(timespec="seconds")
    section_state = _build_site_section_state(pages)
    for section in section_state:
        section["last_crawled_at"] = crawled_at
    section_changes = _site_section_change_summary(previous_manifest, section_state)
    manifest = {
        "seed_url": seed.url,
        "site_name": site_name,
        "page_count": len(pages),
        "max_depth": seed.max_depth,
        "max_pages": seed.max_pages,
        "scrape_only": scrape_only,
        "ingest_attachments": ingest_attachments,
        "generated_at": crawled_at,
        "sections": section_state,
        "section_changes": section_changes,
    }
    site_manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    summary.add_output(site_manifest_path)
    if section_changes:
        update_path = site_dir / "site_update.md"
        update_lines = [
            f"# Site Update: {site_name}",
            "",
            f"- Seed: {seed.url}",
            f"- Generated: {crawled_at}",
            "",
            "## Section Changes",
        ]
        update_lines.extend(f"- {item}" for item in section_changes)
        update_path.write_text("\n".join(update_lines) + "\n", encoding="utf-8")
        summary.add_output(update_path)

    analyzed_pages = 0
    skipped_pages = 0
    for index, page_obj in enumerate(pages, 1):
        console.print(f"  [{index}/{len(pages)}] [bold]{page_obj.title}[/bold]")
        page_dir = config.site_page_dir(seed.topic, site_name, page_obj.title, page_obj.page_id)
        page_dir.mkdir(parents=True, exist_ok=True)
        attachments = []
        if ingest_attachments:
            attachments, attachment_context = ingest_page_attachments(page_obj, page_dir, config)
            if attachment_context:
                page_obj.attachment_context = attachment_context
        else:
            attachments = collect_page_attachments(page_obj)
        if not attachments:
            attachments = collect_page_attachments(page_obj)
        attachment_manifest = write_attachment_manifest(page_dir, attachments)
        if attachment_manifest:
            summary.add_output(attachment_manifest)
            for item in attachments:
                if item.text_path:
                    attachment_text_path = page_dir / "attachments" / item.text_path
                    summary.add_output(attachment_text_path)
        page_document = build_page_document(page_obj)
        content_hash = _content_hash(page_document)
        previous_metadata = {}
        metadata_path = page_dir / "metadata.json"
        if metadata_path.exists():
            try:
                previous_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                previous_metadata = {}
        page_meta = page_obj.metadata()
        page_meta["content_hash"] = content_hash
        metadata_path = page_dir / "metadata.json"
        metadata_path.write_text(json.dumps(page_meta, indent=2), encoding="utf-8")
        summary.add_output(metadata_path)
        content_path = page_dir / "content.md"
        content_path.write_text(page_document, encoding="utf-8")
        summary.add_output(content_path)
        if page_obj.transcript.strip():
            transcript_path = page_dir / "transcript.txt"
            transcript_path.write_text(page_obj.transcript, encoding="utf-8")
            summary.add_output(transcript_path)
        if scrape_only:
            continue
        insights_path = page_dir / "insights.md"
        if previous_metadata.get("content_hash") == content_hash and insights_path.exists():
            skipped_pages += 1
            summary.add_output(insights_path)
            console.print("    [dim]unchanged page — reusing existing insights[/dim]")
            continue
        try:
            insights = analyze_site_page(page_obj, config, tracker=tracker)
            insights_path.write_text(insights, encoding="utf-8")
            summary.add_output(insights_path)
            analyzed_pages += 1
        except Exception as exc:
            console.print(f"  [red]Insight extraction failed: {exc}[/red]")
            cli_shared.record_exception_issue(
                summary,
                stage="site-page-analysis",
                exc=exc,
                context=page_obj.url,
                details={"site": site_name, "topic": seed.topic, "title": page_obj.title},
            )

    if scrape_only:
        return site_name, len(pages)

    manifest["analyzed_pages"] = analyzed_pages
    manifest["skipped_pages"] = skipped_pages
    site_manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    try:
        synthesis = synthesize_site(seed.topic, site_name, config, tracker=tracker)
        if synthesis:
            summary.add_output(config.site_dir(seed.topic, site_name) / "synthesis.md")
    except Exception as exc:
        cli_shared.record_exception_issue(
            summary,
            stage="site-synthesis",
            exc=exc,
            context=seed.url,
            details={"site": site_name, "topic": seed.topic},
        )

    return site_name, len(pages)


def _write_paper_artifacts(
    topic: str,
    paper: PaperRecord,
    config: DistillConfig,
    insights: str,
    document: str | None = None,
) -> Path:
    paper_dir = config.paper_dir(topic, paper.title, paper.paper_id)
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "metadata.json").write_text(
        json.dumps(paper.metadata(), indent=2),
        encoding="utf-8",
    )
    paper_doc = document if document is not None else build_paper_document(paper)
    (paper_dir / "paper.md").write_text(paper_doc, encoding="utf-8")
    (paper_dir / "insights.md").write_text(insights, encoding="utf-8")
    return paper_dir


@app.command(rich_help_panel="Discover")
def paper(
    target: str = typer.Argument(help="arXiv paper URL or paper ID"),
    topic: str = typer.Option("papers", "--topic", "-t", help="Topic to file under"),
):
    """Ingest and analyze a single arXiv paper."""
    config = get_config()
    _require_api_key(config.xai_api_key, "XAI_API_KEY required for paper analysis")
    tracker = CostTracker()
    summary = RunSummary(command="paper")
    summary.set_metadata(topic=topic, workflow="paper", source_type="paper")

    paper_record = fetch_arxiv_paper(target)
    if not paper_record:
        summary.add_issue("paper-fetch", "Could not fetch paper metadata", context=target)
        display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
        raise typer.Exit(1)

    console.print(f"\n[bold]{paper_record.title}[/bold]")
    if paper_record.authors:
        console.print(f"[dim]{', '.join(paper_record.authors[:6])}[/dim]")
    insights, document = analyze_paper(paper_record, config, tracker=tracker)
    paper_dir = _write_paper_artifacts(topic, paper_record, config, insights, document)
    summary.add_output(paper_dir / "paper.md")
    summary.add_output(paper_dir / "insights.md")
    synthesis = synthesize_papers(topic, config, tracker=tracker)
    if synthesis:
        summary.add_output(config.topic_dir(topic) / "paper_synthesis.md")
    corpus_synth = synthesize_corpus(topic, config, tracker=tracker)
    if corpus_synth:
        summary.add_output(config.topic_dir(topic) / "corpus_synthesis.md")
    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)


@app.command(rich_help_panel="Maintain")
def corpus(
    topic: str = typer.Argument(
        help="Topic to synthesize as a mixed-source corpus", autocompletion=_complete_topics
    ),
):
    """Build a mixed-source corpus synthesis for a topic."""
    config = get_config()
    _require_api_key(config.xai_api_key, "XAI_API_KEY required")
    tracker = CostTracker()
    summary = RunSummary(command="corpus")
    summary.set_metadata(topic=topic, workflow="corpus", source_type="mixed")

    result = synthesize_corpus(topic, config, tracker=tracker)
    if not result:
        summary.add_issue(
            "corpus-synthesis", "No source material found for corpus synthesis", context=topic
        )
        display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
        raise typer.Exit(1)

    summary.add_output(config.topic_dir(topic) / "corpus_synthesis.md")
    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)


@app.command(rich_help_panel="Discover")
def papers(
    query: str = typer.Argument(help="Paper topic query for arXiv discovery"),
    topic: str = typer.Option("", "--topic", "-t", help="Topic to file under"),
    limit: int = typer.Option(10, "--limit", "-n", help="How many papers to analyze"),
    sort: str = typer.Option(
        "relevance",
        "--sort",
        help="Candidate order from arXiv: relevance or date",
    ),
    expand: bool = typer.Option(
        True,
        "--expand/--no-expand",
        help="Expand the query into multiple arXiv searches (default: on)",
    ),
    rerank: bool = typer.Option(
        True,
        "--rerank/--no-rerank",
        help="Use LLM reranking to pick the best papers (default: on)",
    ),
    preview: bool = typer.Option(
        False,
        "--preview",
        help="Preview the selected set without processing it",
    ),
):
    """Search arXiv and ingest a paper set into the topic corpus."""
    if sort not in {"relevance", "date"}:
        console.print("[red]--sort must be 'relevance' or 'date'[/red]")
        raise typer.Exit(1)

    config = get_config()
    _require_api_key(config.xai_api_key, "XAI_API_KEY required for paper analysis")
    tracker = CostTracker()
    topic_name = topic or _topic_from_query(query)
    summary = RunSummary(command="papers")
    summary.set_metadata(topic=topic_name, workflow="papers", source_type="paper")

    console.print(f"\n[bold]Papers: {query}[/bold]")
    console.print(
        f"[dim]Topic: {topic_name} | Sort: {sort} | Expand: {'on' if expand else 'off'} "
        f"| Rerank: {'on' if rerank else 'off'} | Limit: {limit}[/dim]\n"
    )

    queries = _expand_paper_queries(query, config=config, tracker=tracker, expand=expand)
    if not queries:
        queries = [query]
    for idx, variant in enumerate(queries, 1):
        console.print(f"[dim]Candidate search {idx}/{len(queries)}: {variant}[/dim]")

    # Pull 2x limit per query so reranking has meaningful candidate pool, but
    # cap per-query to keep arXiv requests polite.
    per_query_cap = max(limit, 10)
    if len(queries) > 1:
        candidates = search_arxiv_multi(queries, limit_per_query=per_query_cap, sort=sort)
    else:
        candidates = search_arxiv_papers(queries[0], limit=per_query_cap, sort=sort)

    if not candidates:
        summary.add_issue("paper-search", "No papers found for query", context=query)
        display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
        raise typer.Exit(1)

    console.print(
        f"[dim]Found {len(candidates)} candidate paper(s) across {len(queries)} search(es)[/dim]\n"
    )

    ranked = rerank_papers(
        query,
        candidates,
        config,
        tracker=tracker,
        top_n=limit,
        use_llm=rerank,
    )
    if rerank and not config.xai_api_key:
        console.print("[yellow]XAI_API_KEY missing; used deterministic ranking fallback[/yellow]")

    if preview:
        _display_ranked_papers(ranked, title="Paper Best-Pick Learning Set")
        console.print("\n[dim]Run without `--preview` to process this set.[/dim]")
        display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
        return

    _display_ranked_papers(ranked, title="Selected Papers")
    console.print()

    records = [item.paper for item in ranked]
    console.print(f"[dim]Analyzing {len(records)} paper(s)[/dim]\n")
    for idx, record in enumerate(records, 1):
        console.print(f"  [{idx}/{len(records)}] [bold]{record.title}[/bold]")
        insights, document = analyze_paper(record, config, tracker=tracker)
        paper_dir = _write_paper_artifacts(topic_name, record, config, insights, document)
        summary.add_output(paper_dir / "paper.md")
        summary.add_output(paper_dir / "insights.md")

    synthesis = synthesize_papers(topic_name, config, tracker=tracker)
    if synthesis:
        summary.add_output(config.topic_dir(topic_name) / "paper_synthesis.md")
    corpus_synth = synthesize_corpus(topic_name, config, tracker=tracker)
    if corpus_synth:
        summary.add_output(config.topic_dir(topic_name) / "corpus_synthesis.md")
    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)


@dataclass
class _RankedDiscoverItem:
    kind: str  # "paper" or "video"
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


def _discover_generate_queries(
    goal: str,
    config: DistillConfig,
    tracker: CostTracker | None,
    *,
    paper_count: int,
    video_count: int,
) -> tuple[list[str], list[str]]:
    """Ask Grok for paper + video search queries that serve the goal."""
    client = OpenAI(api_key=config.xai_api_key, base_url=XAI_BASE_URL)
    model = config.xai_model_for("rerank")
    prompt = discover_query_generation_prompt(
        goal, paper_count=paper_count, video_count=video_count
    )
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=768,
        timeout=120,
    )
    if tracker and response.usage:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.usage.prompt_tokens or 0,
                completion_tokens=response.usage.completion_tokens or 0,
                model=model,
                call_type="discover_plan",
            )
        )
    content = response.choices[0].message.content if response.choices else ""
    text = (content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    if not text:
        return [], []
    data = json.loads(text)
    paper_qs = data.get("paper_queries", []) if isinstance(data, dict) else []
    video_qs = data.get("video_queries", []) if isinstance(data, dict) else []
    paper_qs = _dedupe_query_strings([q for q in paper_qs if isinstance(q, str)])
    video_qs = _dedupe_query_strings([q for q in video_qs if isinstance(q, str)])
    return paper_qs, video_qs


def _discover_fetch_videos(
    queries: list[str],
    effective_days: int,
    candidate_cap: int,
    shorts: bool,
) -> list[VideoInfo]:
    raw: list[VideoInfo] = []
    for idx, q in enumerate(queries, 1):
        console.print(f"[dim]Video search {idx}/{len(queries)}: {q}[/dim]")
        raw.extend(search_youtube_results(q, days=effective_days, hours=None, limit=candidate_cap))
    raw = _dedupe_candidates(raw)
    if not raw:
        return []
    if not shorts:
        raw = [v for v in raw if v.duration > SHORTS_THRESHOLD]
    if not raw:
        return []
    enriched = enrich_videos(raw, max_videos=min(len(raw), 20))
    return _filter_recent_candidates(enriched, effective_days, hours=None)


def _discover_rerank(
    goal: str,
    papers: list[PaperRecord],
    videos: list[VideoInfo],
    config: DistillConfig,
    tracker: CostTracker | None,
) -> list[_RankedDiscoverItem]:
    candidates: list[dict] = []
    paper_by_id = {p.paper_id: p for p in papers}
    video_by_id = {v.video_id: v for v in videos}
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
    if not candidates:
        return []

    client = OpenAI(api_key=config.xai_api_key, base_url=XAI_BASE_URL)
    model = config.xai_model_for("rerank")
    prompt = discover_rerank_prompt(goal, candidates)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=8192,
        timeout=240,
    )
    if tracker and response.usage:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.usage.prompt_tokens or 0,
                completion_tokens=response.usage.completion_tokens or 0,
                model=model,
                call_type="discover_rerank",
            )
        )
    content = response.choices[0].message.content if response.choices else ""
    text = (content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    if not text:
        return []
    data = json.loads(text)
    items = data.get("ranked_items", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []

    ranked: list[_RankedDiscoverItem] = []
    for entry in items:
        kind = str(entry.get("kind", "")).strip()
        identifier = str(entry.get("identifier", "")).strip()
        if kind == "paper":
            paper = paper_by_id.get(identifier)
            if not paper:
                continue
            ranked.append(
                _RankedDiscoverItem(
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
                _RankedDiscoverItem(
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
    return sorted(ranked, key=lambda x: x.final_score, reverse=True)


def _display_ranked_discover(items: list[_RankedDiscoverItem], title: str) -> None:
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


@app.command(rich_help_panel="Discover")
def discover(
    goal: str = typer.Argument(
        "",
        help='Research goal, e.g. "help an AI compose great music". Omit if using --goal-file.',
    ),
    goal_file: Path | None = typer.Option(
        None,
        "--goal-file",
        help="Path to a markdown file whose contents become the goal. Enables reusable, "
        "goal-driven topic refreshes. Overrides the positional argument if both are provided.",
    ),
    topic: str = typer.Option("", "--topic", "-t", help="Topic to file under"),
    paper_limit: int = typer.Option(10, "--paper-limit", help="Max papers to ingest (default: 10)"),
    video_limit: int = typer.Option(10, "--video-limit", help="Max videos to ingest (default: 10)"),
    days: int = typer.Option(
        365, "--days", "-d", help="YouTube recency window in days (default: 365)"
    ),
    shorts: bool = typer.Option(
        False, "--shorts/--no-shorts", help="Include short-form videos under 3 minutes"
    ),
    preview: bool = typer.Option(
        False, "--preview", help="Show the goal-ranked plan without ingesting"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the interactive confirmation prompt"),
):
    """Goal-aware cross-source discovery: papers + videos, reranked against a goal."""
    if goal_file is not None:
        if not goal_file.exists():
            console.print(f"[red]Goal file not found: {goal_file}[/red]")
            raise typer.Exit(1)
        goal = goal_file.read_text(encoding="utf-8").strip()
    if not goal.strip():
        console.print("[red]Goal is empty. Provide a goal argument or --goal-file path.[/red]")
        raise typer.Exit(1)

    config = get_config()
    _require_api_key(config.xai_api_key, "XAI_API_KEY required for goal-aware discovery")
    tracker = CostTracker()
    topic_name = topic or _topic_from_query(goal[:80])
    summary = RunSummary(command="discover")
    summary.set_metadata(topic=topic_name, workflow="discover", source_type="mixed")

    # Goal files can be multi-line; keep console header compact.
    goal_headline = goal.splitlines()[0][:120] if goal else ""
    console.print(f"\n[bold]Discover: {goal_headline}[/bold]")
    if goal_file is not None:
        console.print(f"[dim]Goal loaded from {goal_file}[/dim]")
    console.print(
        f"[dim]Topic: {topic_name} | Papers: {paper_limit} | Videos: {video_limit} "
        f"| Days: {days}[/dim]\n"
    )

    paper_queries, video_queries = _discover_generate_queries(
        goal, config, tracker, paper_count=5, video_count=5
    )
    if not paper_queries and not video_queries:
        console.print("[red]Query generation produced no queries. Try a more concrete goal.[/red]")
        raise typer.Exit(1)

    if paper_queries:
        console.print(
            f"[dim]Paper queries ({len(paper_queries)}): {', '.join(paper_queries)}[/dim]"
        )
    if video_queries:
        console.print(
            f"[dim]Video queries ({len(video_queries)}): {', '.join(video_queries)}[/dim]"
        )
    console.print()

    papers: list[PaperRecord] = []
    if paper_queries:
        per_query_cap = max(paper_limit, 8)
        papers = search_arxiv_multi(paper_queries, limit_per_query=per_query_cap, sort="relevance")
        console.print(
            f"[dim]Found {len(papers)} unique papers across {len(paper_queries)} search(es)[/dim]"
        )

    videos: list[VideoInfo] = []
    if video_queries:
        videos = _discover_fetch_videos(
            video_queries, effective_days=days, candidate_cap=20, shorts=shorts
        )
        console.print(
            f"[dim]Found {len(videos)} unique videos across {len(video_queries)} search(es)[/dim]"
        )

    if not papers and not videos:
        console.print("[red]No candidates found. Broaden the goal or widen --days.[/red]")
        raise typer.Exit(1)

    console.print("\n[dim]Reranking against goal...[/dim]")
    ranked = _discover_rerank(goal, papers, videos, config, tracker)
    if not ranked:
        console.print("[red]Rerank produced no ranked items.[/red]")
        raise typer.Exit(1)

    # Apply per-source limits after ranking
    ranked_papers = [r for r in ranked if r.kind == "paper"][:paper_limit]
    ranked_videos = [r for r in ranked if r.kind == "video"][:video_limit]
    shortlist = sorted(ranked_papers + ranked_videos, key=lambda x: x.final_score, reverse=True)

    _display_ranked_discover(shortlist, title=f"Goal-Ranked Corpus Plan ({len(shortlist)} items)")

    if preview:
        console.print("\n[dim]Run without `--preview` to ingest this set.[/dim]")
        display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
        return

    if not yes:
        proceed = typer.confirm(
            f"\nIngest {len(ranked_papers)} paper(s) and {len(ranked_videos)} video(s) into topic '{topic_name}'?",
            default=False,
        )
        if not proceed:
            console.print("[yellow]Aborted by user.[/yellow]")
            display_summary(
                summary, cost_tracker=tracker, console=console, log_dir=config.library_dir
            )
            return

    # Ingest papers
    if ranked_papers:
        console.print(f"\n[bold]Ingesting {len(ranked_papers)} paper(s)[/bold]")
        for idx, item in enumerate(ranked_papers, 1):
            paper = item.paper
            if paper is None:
                continue
            console.print(f"  [{idx}/{len(ranked_papers)}] [bold]{paper.title}[/bold]")
            insights, document = analyze_paper(paper, config, tracker=tracker)
            paper_dir = _write_paper_artifacts(topic_name, paper, config, insights, document)
            summary.add_output(paper_dir / "paper.md")
            summary.add_output(paper_dir / "insights.md")
        synth = synthesize_papers(topic_name, config, tracker=tracker)
        if synth:
            summary.add_output(config.topic_dir(topic_name) / "paper_synthesis.md")

    # Ingest videos (reuse the learning pipeline)
    if ranked_videos:
        console.print(f"\n[bold]Ingesting {len(ranked_videos)} video(s)[/bold]")
        video_items = [
            SimpleNamespace(video=r.video, final_score=r.final_score, rationale=r.rationale)
            for r in ranked_videos
            if r.video is not None
        ]
        _process_learning_selection(
            topic_name,
            config,
            tracker,
            video_items,
            save=True,
            report=False,
            test=False,
            generate_brief=False,
        )

    corpus = synthesize_corpus(topic_name, config, tracker=tracker)
    if corpus:
        summary.add_output(config.topic_dir(topic_name) / "corpus_synthesis.md")
    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)


@app.command(name="site", rich_help_panel="Discover")
def site_cmd(
    url: str = typer.Argument(help="Website URL to crawl and distill"),
    topic: str = typer.Option("web", "--topic", "-t", help="Topic to file under"),
    name: str = typer.Option("", "--name", help="Optional site name override"),
    max_pages: int = typer.Option(8, "--max-pages", help="Max pages to crawl from this seed"),
    max_depth: int = typer.Option(
        1, "--max-depth", help="How many link hops to follow from the seed"
    ),
    scrape_only: bool = typer.Option(
        False,
        "--scrape-only",
        help="Only save raw page artifacts; skip insights, synthesis, and reports",
    ),
    seed_only: bool = typer.Option(
        False, "--seed-only", help="Only scrape the exact seed URL; do not follow links"
    ),
    same_section_only: bool = typer.Option(
        False,
        "--same-section-only",
        help="When crawling, stay within the seed URL's top-level section (for example /topic, /partner, /lab, /docs)",
    ),
    ingest_attachments: bool = typer.Option(
        False,
        "--ingest-attachments",
        help="Pull PDF text and supported embedded video transcripts into the page corpus",
    ),
    report: bool = typer.Option(
        False, "--report", help="Run Deep Research report after processing"
    ),
    test: bool = typer.Option(False, "--test", help="Pass --test through to report generation"),
):
    """Crawl a website, extract page insights, synthesize, and optionally report."""
    config = get_config()
    if report and scrape_only:
        raise typer.BadParameter("--report cannot be used with --scrape-only")
    if not scrape_only:
        _require_api_key(config.xai_api_key, "XAI_API_KEY required for website analysis")
    tracker = CostTracker()
    summary = RunSummary(command="site")
    summary.set_metadata(topic=topic, workflow="site", source_type="website")
    seed = SiteSeed(
        url=url,
        topic=topic,
        site_name=name or site_name_from_url(url),
        max_depth=0 if seed_only else max_depth,
        max_pages=1 if seed_only else max_pages,
        same_section_only=same_section_only,
    )
    _process_site_seed(
        seed,
        config,
        tracker,
        summary,
        scrape_only=scrape_only,
        ingest_attachments=ingest_attachments,
    )

    if not scrape_only:
        try:
            topic_synth = synthesize_site_topic(topic, config, tracker=tracker)
            if topic_synth:
                summary.add_output(config.topic_dir(topic) / "topic_synthesis.md")
            corpus_synth = synthesize_corpus(topic, config, tracker=tracker)
            if corpus_synth:
                summary.add_output(config.topic_dir(topic) / "corpus_synthesis.md")
        except Exception as exc:
            cli_shared.record_exception_issue(
                summary,
                stage="site-topic-synthesis",
                exc=exc,
                context=topic,
                details={"topic": topic},
            )

    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
    if report:
        _run_scope_report(topic, config, tracker, scope="topic", test=test, summary=summary)


@app.command(name="site-batch", rich_help_panel="Discover")
def site_batch_cmd(
    path: Path = typer.Argument(help="JSON or TXT file containing website URLs/seeds"),
    topic: str = typer.Option("", "--topic", "-t", help="Optional topic override"),
    scrape_only: bool = typer.Option(
        False,
        "--scrape-only",
        help="Only save raw page artifacts; skip insights, synthesis, and reports",
    ),
    seed_only: bool = typer.Option(
        False, "--seed-only", help="Only scrape the exact seed URLs; do not follow links"
    ),
    same_section_only: bool = typer.Option(
        False,
        "--same-section-only",
        help="When crawling, stay within the seed URL's top-level section (for example /topic, /partner, /lab, /docs)",
    ),
    ingest_attachments: bool = typer.Option(
        False,
        "--ingest-attachments",
        help="Pull PDF text and supported embedded video transcripts into the page corpus",
    ),
    report: bool = typer.Option(
        False, "--report", help="Run Deep Research report after processing"
    ),
    test: bool = typer.Option(False, "--test", help="Pass --test through to report generation"),
):
    """Process a simple list or JSON config of websites."""
    config = get_config()
    if report and scrape_only:
        raise typer.BadParameter("--report cannot be used with --scrape-only")
    if not scrape_only:
        _require_api_key(config.xai_api_key, "XAI_API_KEY required for website analysis")
    batch = load_site_batch(path, topic_override=topic)
    tracker = CostTracker()
    summary = RunSummary(command="site-batch")
    summary.set_metadata(topic=topic, workflow="site-batch", source_type="website")

    for seed in batch.seeds:
        adjusted_seed = SiteSeed(
            url=seed.url,
            topic=seed.topic,
            site_name=seed.site_name,
            label=seed.label,
            max_depth=0 if seed_only else seed.max_depth,
            max_pages=1 if seed_only else seed.max_pages,
            same_section_only=same_section_only or seed.same_section_only,
        )
        _process_site_seed(
            adjusted_seed,
            config,
            tracker,
            summary,
            scrape_only=scrape_only,
            ingest_attachments=ingest_attachments,
        )

    target_topic = topic or batch.topic
    if not scrape_only:
        try:
            topic_synth = synthesize_site_topic(target_topic, config, tracker=tracker)
            if topic_synth:
                summary.add_output(config.topic_dir(target_topic) / "topic_synthesis.md")
            corpus_synth = synthesize_corpus(target_topic, config, tracker=tracker)
            if corpus_synth:
                summary.add_output(config.topic_dir(target_topic) / "corpus_synthesis.md")
        except Exception as exc:
            cli_shared.record_exception_issue(
                summary,
                stage="site-topic-synthesis",
                exc=exc,
                context=target_topic,
                details={"topic": target_topic},
            )

    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
    if report:
        _run_scope_report(target_topic, config, tracker, scope="topic", test=test, summary=summary)


def main():
    """Entry point for the `distill` CLI command."""
    app()


if __name__ == "__main__":
    main()
