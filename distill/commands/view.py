# pyright: strict
"""Corpus-browsing and view commands."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import typer
from rich import box
from rich.panel import Panel
from rich.table import Table

from distill._console import console
from distill.cli_shared import output_path as _output_path
from distill.cli_shared import print_markdown_safely as _print_markdown_safely
from distill.cli_shared import tty_confirm as _tty_confirm
from distill.commands._helpers import (
    _complete_topic_watch_names,
    _complete_topics,
    _complete_watched_channels,
    budgeted_cost_tracker,
    enforce_projected_workflow_budget,
    get_config,
    save_synthesis_command_cost,
    set_command_cost_metadata,
)
from distill.commands._helpers import duration_str as _duration_str
from distill.commands._helpers import file_link as _file_link
from distill.commands._helpers import format_date as _format_date
from distill.commands._json import emit_json as _emit_json
from distill.commands._json import json_mode_active as _json_mode_active
from distill.commands._topic_changes import (
    append_topic_change_history,
    collect_topic_change_details,
    load_topic_change_history,
    render_topic_diff_markdown,
    render_topic_trends_markdown,
    resolve_topic_diff_baseline,
    topic_change_history_path,
)
from distill.commands._topic_resolution import (
    resolve_required_topic_for_channel as _resolve_required_topic_for_channel,
)
from distill.commands._view_data import (
    bool_field as _bool_field,
)
from distill.commands._view_data import (
    channel_video_count as _channel_video_count,
)
from distill.commands._view_data import (
    int_field as _int_field,
)
from distill.commands._view_data import (
    library_action_hints as _library_action_hints,
)
from distill.commands._view_data import (
    library_payload as _library_payload,
)
from distill.commands._view_data import (
    path_field as _path_field,
)
from distill.commands._view_data import (
    read_json_object as _read_json_object,
)
from distill.commands._view_data import (
    text_field as _text_field,
)
from distill.commands._view_data import (
    topic_artifact_labels as _topic_artifact_labels,
)
from distill.commands._view_data import (
    video_metadata as _video_metadata,
)
from distill.config import DistillConfig
from distill.ingestors.youtube.discovery import resolve_channel_name
from distill.library import Library
from distill.library.paths import (
    artifact_exists,
    base_frontmatter,
    find_artifact,
    tags_for,
    write_markdown_artifact,
)
from distill.library.state import ChannelState
from distill.llm.router import RouterConfig
from distill.parsing import parse_ascii_uint
from distill.pipeline.costs import BudgetExceededError, estimate_synthesis_workflow_cost
from distill.pipeline.dashboard_records import JsonObject
from distill.pipeline.synthesis.topic import synthesize_channel, synthesize_topic

__all__ = [
    "add",
    "diff",
    "findings",
    "library_cmd",
    "package_latest",
    "register",
    "remove",
    "show",
    "synthesis",
    "trends",
    "videos",
]


def library_cmd() -> None:
    """Show what's in your library."""
    config = get_config()
    lib = Library(config)

    topics = lib.get_corpus_topics()
    if _json_mode_active():
        _emit_json(_library_payload(config, lib, topics))
        return
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
        channel_names = lib.get_corpus_channel_names(topic)
        registered = {channel.name.casefold() for channel in lib.get_channels(topic)}
        table = Table(
            title=f"Topic: {topic}",
            show_header=True,
            box=box.ROUNDED,
            title_style="bold cyan",
        )
        table.add_column("Channel", style="bold")
        table.add_column("Source", style="dim")
        table.add_column("Videos", justify="right", style="green")
        table.add_column("Last Refresh", style="dim")
        table.add_column("Artifacts", style="dim")

        for channel_name in channel_names:
            state_file = config.channel_dir(topic, channel_name) / "state.json"
            state = ChannelState(state_file)

            artifacts: list[str] = []
            channel_dir = config.channel_dir(topic, channel_name)
            if artifact_exists(channel_dir, "synthesis", identity=f"{topic}_{channel_name}"):
                artifacts.append("synthesis")
            if artifact_exists(channel_dir, "report", identity=f"{topic}_{channel_name}"):
                artifacts.append("report")

            table.add_row(
                channel_name,
                "registered" if channel_name.casefold() in registered else "direct",
                str(_channel_video_count(config, topic, channel_name)),
                _format_date(state.get_last_refresh() or ""),
                ", ".join(artifacts) if artifacts else "-",
            )

        console.print(table)

        # Topic-level artifacts
        topic_dir = config.topic_dir(topic)
        topic_artifacts = _topic_artifact_labels(topic_dir, topic)
        if topic_artifacts:
            console.print(f"  [dim]Topic files: {', '.join(topic_artifacts)}[/dim]")

        # Actionable hints per topic
        console.print(f"  [dim]{_library_action_hints(topic, bool(registered))}[/dim]")
        console.print()


def _videos_payload(
    config: DistillConfig,
    channel_names: list[str],
    registered: set[str],
    topic: str,
    limit: int,
) -> dict[str, object]:
    """Structured per-channel video inventory for ``--json``."""
    out_channels: list[dict[str, object]] = []
    for channel_name in channel_names:
        videos_dir = config.videos_dir(topic, channel_name)
        if not videos_dir.exists():
            continue
        vids: list[dict[str, object]] = []
        for meta in _video_metadata(videos_dir):
            vids.append(
                {
                    "video_id": meta.get("video_id"),
                    "title": meta.get("title"),
                    "upload_date": meta.get("upload_date"),
                    "duration": meta.get("duration"),
                    "url": meta.get("url"),
                    "has_transcript": _bool_field(meta, "_has_transcript"),
                    "has_insights": _bool_field(meta, "_has_insights"),
                }
            )
        vids.sort(key=lambda v: str(v.get("upload_date") or ""), reverse=True)
        out_channels.append(
            {
                "channel": channel_name,
                "registered": channel_name.casefold() in registered,
                "total": len(vids),
                "videos": vids[:limit],
            }
        )
    return {"topic": topic, "channels": out_channels, "count": len(out_channels)}


def videos(  # noqa: C901 — legacy, will refactor
    topic: str = typer.Argument(help="Topic or channel name", autocompletion=_complete_topics),
    channel: str | None = typer.Option(
        None, "--channel", "-c", help="Specific channel (default: all in topic)"
    ),
    limit: int = typer.Option(20, "--limit", "-n", help="Max videos to show"),
) -> None:
    """List processed videos with metadata."""
    config = get_config()
    lib = Library(config)
    topic, channel = _resolve_required_topic_for_channel(lib, topic, channel)

    channel_names = lib.get_corpus_channel_names(topic)
    if channel:
        channel_names = [name for name in channel_names if name == channel]

    if not channel_names:
        if _json_mode_active():
            _emit_json({"topic": topic, "channels": [], "count": 0})
            return
        console.print(f"[yellow]No channels found for topic '{topic}'[/yellow]")
        return

    if _json_mode_active():
        registered = {item.name.casefold() for item in lib.get_channels(topic)}
        _emit_json(_videos_payload(config, channel_names, registered, topic, limit))
        return

    registered = {item.name.casefold() for item in lib.get_channels(topic)}
    for channel_name in channel_names:
        videos_dir = config.videos_dir(topic, channel_name)
        if not videos_dir.exists():
            continue

        # Collect all video metadata
        vid_list = _video_metadata(videos_dir)

        table = Table(
            title=(
                f"{channel_name} - {len(vid_list)} videos"
                + ("" if channel_name.casefold() in registered else " (direct ingest)")
            ),
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
            has_t = _bool_field(v, "_has_transcript")
            has_i = _bool_field(v, "_has_insights")

            if has_t and has_i:
                status = "[green]complete[/green]"
            elif has_t:
                status = "[yellow]transcript only[/yellow]"
            else:
                status = "[red]missing[/red]"

            table.add_row(
                str(i),
                _format_date(_text_field(v, "upload_date")),
                _text_field(v, "title", "Unknown")[:70],
                _duration_str(_int_field(v, "duration")),
                status,
            )

        console.print(table)

        if len(vid_list) > limit:
            console.print(
                f"  [dim]Showing {limit}/{len(vid_list)} -- use --limit to see more[/dim]"
            )

        # Next steps
        ch_flag = f" -c {channel_name}" if channel else ""
        console.print(
            f"  [dim]distill show {topic} 1{ch_flag}            View insights for video #1[/dim]"
        )
        console.print(
            f"  [dim]distill synthesis {topic}{ch_flag}          Read the synthesis[/dim]"
        )
        console.print()


def _show_payload(vid_dir: Path, video: JsonObject, what: str) -> dict[str, object]:
    """Structured payload for ``show --json`` (insights / transcript / metadata)."""
    meta = {k: v for k, v in video.items() if not k.startswith("_")}
    base: dict[str, object] = {"title": video.get("title"), "what": what, "metadata": meta}
    if what == "metadata":
        return {**base, "found": True, "content": None}
    if what == "transcript":
        path = find_artifact(vid_dir, "transcript", extension="txt")
    else:
        path = find_artifact(vid_dir, "insights")
    exists = path.exists()
    return {
        **base,
        "path": str(path),
        "found": exists,
        "content": path.read_text(encoding="utf-8") if exists else None,
    }


def _emit_content_json(label: str, file_path: Path) -> None:
    """Emit a read-artifact's content as a ``--json`` envelope (read-only: never
    triggers generation, so an agent querying with --json can't cause spend)."""
    exists = file_path.exists()
    _emit_json(
        {
            "label": label,
            "path": str(file_path),
            "found": exists,
            "content": file_path.read_text(encoding="utf-8") if exists else None,
        }
    )


def show(  # noqa: C901 — legacy, will refactor
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
) -> None:
    """Read insights or transcript for a specific video."""
    config = get_config()
    lib = Library(config)

    # Parse second arg: if it looks like an int, use as index; otherwise treat as channel
    index = 1
    parsed_index = parse_ascii_uint(index_or_channel)
    if parsed_index is not None:
        index = parsed_index
    else:
        # Treat as channel name (positional overrides -c flag)
        channel = index_or_channel

    topic, channel = _resolve_required_topic_for_channel(lib, topic, channel)
    channel_names = lib.get_corpus_channel_names(topic)
    if channel:
        channel_names = [name for name in channel_names if name == channel]
    if not channel_names:
        console.print("[yellow]No channels found[/yellow]")
        return

    channel_name = channel_names[0]
    videos_dir = config.videos_dir(topic, channel_name)

    if not videos_dir.exists():
        console.print(f"[yellow]No videos found for {channel_name}[/yellow]")
        return

    # Collect and sort videos
    vid_list = _video_metadata(videos_dir)

    if index < 1 or index > len(vid_list):
        console.print(f"[red]Video #{index} not found. Range: 1-{len(vid_list)}[/red]")
        return

    video = vid_list[index - 1]
    vid_dir = _path_field(video, "_dir")
    if vid_dir is None:
        console.print("[red]Video metadata is missing its library path[/red]")
        return

    if _json_mode_active():
        _emit_json(_show_payload(vid_dir, video, what))
        return

    title = _text_field(video, "title", "Unknown")
    date = _format_date(_text_field(video, "upload_date"))

    total = len(vid_list)
    ch_name = channel_name
    pos_label = f"[dim][{index}/{total}][/dim]"

    if what == "insights":
        file_path = find_artifact(vid_dir, "insights")
        if not file_path.exists():
            console.print("[red]No insights found for this video[/red]")
            console.print(f"[dim]Run: distill run {topic} -c {ch_name} --refresh[/dim]")
            return
        console.print(
            Panel(
                f"{pos_label}  [bold]{title}[/bold]\n"
                f"[dim]{date} | {_duration_str(_int_field(video, 'duration'))} | {ch_name}[/dim]\n"
                f"[dim]{_text_field(video, 'url')}[/dim]",
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
        nav: list[str] = []
        if index > 1:
            nav.append(f"[dim]<< distill show {ch_name} {index - 1}[/dim]")
        if index < total:
            nav.append(f"[dim]distill show {ch_name} {index + 1} >>[/dim]")
        if nav:
            console.print(f"  {'  |  '.join(nav)}")
        console.print(f"  [dim]-w transcript[/dim]  |  {_file_link(file_path)}")

    elif what == "transcript":
        file_path = find_artifact(vid_dir, "transcript", extension="txt")
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


def package_latest(  # noqa: C901 — legacy, will refactor
    topic: str = typer.Argument(help="Topic or channel name", autocompletion=_complete_topics),
    channel: str | None = typer.Option(
        None, "--channel", "-c", help="Specific channel", autocompletion=_complete_watched_channels
    ),
    limit: int = typer.Option(10, "--limit", "-n", help="Number of latest videos to include"),
    include_transcript: bool = typer.Option(
        False, "--transcript", "-t", help="Include full transcripts (can be large)"
    ),
) -> None:
    """Package the latest videos into a single markdown file with links, insights, and optionally transcripts."""
    config = get_config()
    lib = Library(config)
    topic, channel = _resolve_required_topic_for_channel(lib, topic, channel)

    channels = lib.get_channels(topic)
    if channel:
        channels = [ch for ch in channels if ch.name == channel]
    if not channels:
        console.print("[yellow]No channels found[/yellow]")
        return

    # Collect videos across selected channels
    all_videos: list[tuple[str, JsonObject, Path]] = []
    for ch in channels:
        videos_dir = config.videos_dir(topic, ch.name)
        if not videos_dir.exists():
            continue
        for vid_dir in videos_dir.iterdir():
            if not vid_dir.is_dir():
                continue
            meta_file = vid_dir / "metadata.json"
            if meta_file.exists():
                meta = _read_json_object(meta_file)
                if meta is None:
                    continue
                all_videos.append((ch.name, meta, vid_dir))

    all_videos.sort(key=lambda v: _text_field(v[1], "upload_date"), reverse=True)
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
        title = _text_field(meta, "title", "Unknown")
        date = _format_date(_text_field(meta, "upload_date"))
        duration = _duration_str(_int_field(meta, "duration"))
        url = _text_field(meta, "url")

        parts.append(f"---\n\n## {i}. {title}\n")
        parts.append(f"**Channel:** {ch_name}  ")
        parts.append(f"**Date:** {date}  ")
        parts.append(f"**Duration:** {duration}  ")
        if url:
            parts.append(f"**Link:** {url}\n")

        # Insights
        insights_file = find_artifact(vid_dir, "insights")
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
            transcript_file = find_artifact(vid_dir, "transcript", extension="txt")
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


def synthesis(  # noqa: C901 — legacy, will refactor
    topic: str = typer.Argument(help="Topic or channel name", autocompletion=_complete_topics),
    channel: str | None = typer.Option(
        None, "--channel", "-c", help="Channel synthesis (default: topic synthesis)"
    ),
) -> None:
    """Read the synthesis document for a channel or topic."""
    config = get_config()
    lib = Library(config)
    topic, channel = _resolve_required_topic_for_channel(lib, topic, channel)

    if channel:
        file_path = find_artifact(
            config.channel_dir(topic, channel),
            "synthesis",
            identity=f"{topic}_{channel}",
        )
        label = f"Channel Synthesis: {channel}"
    else:
        file_path = find_artifact(config.topic_dir(topic), "topic_synthesis", identity=topic)
        label = f"Topic Synthesis: {topic}"
        if not file_path.exists():
            lib = Library(config)
            channels = lib.get_channels(topic)
            if channels:
                file_path = find_artifact(
                    config.channel_dir(topic, channels[0].name),
                    "synthesis",
                    identity=f"{topic}_{channels[0].name}",
                )
                label = f"Channel Synthesis: {channels[0].name}"

    # --json is read-only: emit what exists, never auto-generate (that spends).
    if _json_mode_active():
        _emit_content_json(label, file_path)
        return

    if not file_path.exists():
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
            projected_cost = estimate_synthesis_workflow_cost(
                router_config=RouterConfig(),
            )
            enforce_projected_workflow_budget(config, "synthesis", projected_cost)
            tracker = budgeted_cost_tracker(config, "synthesis")
            set_command_cost_metadata(tracker, topic=topic)
            try:
                try:
                    if channel:
                        synthesize_channel(topic, channel, config, tracker=tracker)
                        console.print(f"[green]Synthesis generated for {channel}[/green]")
                        file_path = find_artifact(
                            config.channel_dir(topic, channel),
                            "synthesis",
                            identity=f"{topic}_{channel}",
                        )
                    else:
                        synthesize_topic(topic, config, tracker=tracker)
                        console.print(f"[green]Topic synthesis generated for {topic}[/green]")
                        file_path = find_artifact(
                            config.topic_dir(topic),
                            "topic_synthesis",
                            identity=topic,
                        )
                finally:
                    save_synthesis_command_cost(
                        config,
                        topic,
                        channel,
                        tracker,
                        estimated_cost=projected_cost,
                    )
            except BudgetExceededError:
                raise
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


def findings(
    topic: str = typer.Argument(help="Topic or channel name", autocompletion=_complete_topics),
    channel: str | None = typer.Option(
        None, "--channel", "-c", help="Channel report (default: topic report)"
    ),
) -> None:
    """Read the generated report."""
    config = get_config()
    lib = Library(config)
    topic, channel = _resolve_required_topic_for_channel(lib, topic, channel)

    if channel:
        file_path = find_artifact(
            config.channel_dir(topic, channel),
            "report",
            identity=f"{topic}_{channel}",
        )
        label = f"Report: {channel}"
    else:
        file_path = find_artifact(config.topic_dir(topic), "report", identity=topic)
        label = f"Report: {topic}"

    if _json_mode_active():
        _emit_content_json(label, file_path)
        return

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


def add(
    topic: str = typer.Argument(help="Topic to add channel to (e.g., 'ai', 'security')"),
    url: str = typer.Argument(help="YouTube channel URL"),
) -> None:
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


def remove(
    topic: str = typer.Argument(help="Topic", autocompletion=_complete_topics),
    url: str = typer.Argument(help="YouTube channel URL to remove"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Remove a channel from a topic."""
    config = get_config()
    lib = Library(config)

    if not yes and not _tty_confirm(
        f"Remove channel from '{topic}'? (library entry only, data stays on disk)"
    ):
        raise typer.Abort()

    if lib.remove_channel(topic, url):
        console.print(f"[green]Removed from {topic}[/green]")
    else:
        console.print(f"[yellow]Not found in {topic}[/yellow]")


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
        help="Write the latest topic diff as a slugged Markdown artifact",
    ),
) -> None:
    """Show what changed in a topic since the last watch run or a fallback window."""
    config = get_config()
    lib = Library(config)
    topic, _channel = _resolve_required_topic_for_channel(lib, topic, None)

    if topic not in lib.get_topics() and not config.topic_dir(topic).exists():
        console.print(f"[red]Topic not found: {topic}[/red]")
        raise typer.Exit(1)

    baseline, watch_name, query, cadence = resolve_topic_diff_baseline(
        lib,
        topic,
        watch_name=watch,
        days=days,
    )
    details = collect_topic_change_details(config, lib, topic, baseline)
    summary = details["summary"]
    generated_at = details["generated_at"]
    effective_baseline = details["effective_baseline"]
    new_videos = details["new_videos"]
    new_pages = details["new_pages"]
    new_papers = details["new_papers"]
    refreshed_outputs = details["refreshed_outputs"]
    rendered = render_topic_diff_markdown(
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
        limit=limit,
    )

    console.print(Panel(f"[bold]Topic Diff: {topic}[/bold]", border_style="cyan"))
    _print_markdown_safely(console, rendered)

    if write:
        diff_path = write_markdown_artifact(
            config.topic_dir(topic),
            "topic_diff",
            rendered,
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
        history_path = append_topic_change_history(
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
        console.print()
        console.print(f"  {_file_link(diff_path)}")
        console.print(f"  {_file_link(history_path)}")
        console.print(f"  [dim]distill findings {topic}  |  distill synthesis {topic}[/dim]")


def trends(
    topic: str = typer.Argument(help="Topic or channel name", autocompletion=_complete_topics),
    limit: int = typer.Option(
        8, "--limit", "-n", help="How many recent change windows to summarize"
    ),
    write: bool = typer.Option(
        True,
        "--write/--no-write",
        help="Write the latest topic trends as a slugged Markdown artifact",
    ),
) -> None:
    """Show recent topic momentum using recorded diff history."""
    config = get_config()
    lib = Library(config)
    topic, _channel = _resolve_required_topic_for_channel(lib, topic, None)

    if topic not in lib.get_topics() and not config.topic_dir(topic).exists():
        console.print(f"[red]Topic not found: {topic}[/red]")
        raise typer.Exit(1)

    records = load_topic_change_history(config, topic)
    rendered = render_topic_trends_markdown(
        config,
        topic=topic,
        records=records,
        generated_at=datetime.now(),
        limit=limit,
    )

    console.print(Panel(f"[bold]Topic Trends: {topic}[/bold]", border_style="magenta"))
    _print_markdown_safely(console, rendered)

    if write:
        trends_path = write_markdown_artifact(
            config.topic_dir(topic),
            "topic_trends",
            rendered,
            identity=topic,
            frontmatter=base_frontmatter(
                artifact_type="topic_trends",
                title=f"Topic Trends: {topic}",
                topic=topic,
                source="distill",
                tags=tags_for(topic, "trends"),
                synthesis_scope="operational",
                extra={"legacy_filename": "topic_trends.md"},
            ),
        )
        console.print()
        console.print(f"  {_file_link(trends_path)}")
        console.print(f"  {_file_link(topic_change_history_path(config, topic))}")
        console.print(f"  [dim]distill diff {topic}  |  distill findings {topic}[/dim]")


def register(app: typer.Typer) -> None:
    """Attach the view commands to the app (called from distill.cli)."""
    app.command(name="library", rich_help_panel="Library")(library_cmd)
    app.command(rich_help_panel="Library")(videos)
    app.command(rich_help_panel="View")(show)
    app.command(name="package-latest", rich_help_panel="View")(package_latest)
    app.command(rich_help_panel="View")(synthesis)
    app.command(rich_help_panel="View")(findings)
    app.command(rich_help_panel="Library")(add)
    app.command(rich_help_panel="Library")(remove)
    app.command(rich_help_panel="View")(diff)
    app.command(rich_help_panel="View")(trends)
