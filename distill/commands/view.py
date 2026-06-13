"""Corpus-browsing / view commands, extracted from the `_logic` monolith.

First command-group slice of the decomposition (how-we-build.md remediation #1).
Registered onto the app via :func:`register` from ``distill.cli`` (mirroring
ask / audit / update), so `_logic` no longer owns these commands. Pure
relocation -- no behavior change.
"""

from __future__ import annotations

import json

import typer
from rich import box
from rich.panel import Panel
from rich.table import Table

from distill._console import console
from distill.commands._helpers import _resolve_topic_for_channel, get_config
from distill.commands._helpers import duration_str as _duration_str
from distill.commands._helpers import format_date as _format_date
from distill.commands._json import emit_json as _emit_json
from distill.commands._json import json_mode_active as _json_mode_active

# `_complete_topics` (shell-completion helper) still lives in `_logic`. Imported
# one-way here (no cycle: `_logic` does not import this module). Extracting the
# completion helpers to `_helpers` is a later decomposition step.
from distill.commands._logic import _complete_topics
from distill.library import Library
from distill.library.paths import artifact_exists
from distill.library.state import ChannelState

__all__ = ["library_cmd", "register", "videos"]


def _library_payload(config, lib, topics: list[str]) -> dict:
    """Structured library inventory for ``--json`` (topics -> channels + artifacts)."""
    result = []
    for topic in topics:
        channels = []
        for ch in lib.get_channels(topic):
            channel_dir = config.channel_dir(topic, ch.name)
            state = ChannelState(channel_dir / "state.json")
            artifacts = [
                name
                for name, present in (
                    (
                        "synthesis",
                        artifact_exists(channel_dir, "synthesis", identity=f"{topic}_{ch.name}"),
                    ),
                    (
                        "report",
                        artifact_exists(channel_dir, "report", identity=f"{topic}_{ch.name}"),
                    ),
                )
                if present
            ]
            channels.append(
                {
                    "name": ch.name,
                    "videos": state.get_processed_count(),
                    "last_refresh": state.get_last_refresh() or None,
                    "artifacts": artifacts,
                }
            )
        topic_dir = config.topic_dir(topic)
        topic_artifacts = [
            name
            for name, present in (
                ("topic_synthesis", artifact_exists(topic_dir, "topic_synthesis", identity=topic)),
                ("report", artifact_exists(topic_dir, "report", identity=topic)),
            )
            if present
        ]
        result.append({"topic": topic, "channels": channels, "topic_artifacts": topic_artifacts})
    return {"topics": result, "count": len(result)}


def library_cmd():
    """Show what's in your library."""
    config = get_config()
    lib = Library(config)

    topics = lib.get_topics()
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
            channel_dir = config.channel_dir(topic, ch.name)
            if artifact_exists(channel_dir, "synthesis", identity=f"{topic}_{ch.name}"):
                artifacts.append("synthesis")
            if artifact_exists(channel_dir, "report", identity=f"{topic}_{ch.name}"):
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
        topic_dir = config.topic_dir(topic)
        if artifact_exists(topic_dir, "topic_synthesis", identity=topic):
            topic_artifacts.append("topic synthesis")
        if artifact_exists(topic_dir, "report", identity=topic):
            topic_artifacts.append("report")
        if topic_artifacts:
            console.print(f"  [dim]Topic files: {', '.join(topic_artifacts)}[/dim]")

        # Actionable hints per topic
        console.print(
            f"  [dim]distill videos {topic}  |  "
            f"distill synthesis {topic}  |  "
            f"distill run {topic} --refresh[/dim]"
        )
        console.print()


def _videos_payload(config, channels, topic: str, limit: int) -> dict:
    """Structured per-channel video inventory for ``--json``."""
    out_channels = []
    for ch in channels:
        videos_dir = config.videos_dir(topic, ch.name)
        if not videos_dir.exists():
            continue
        vids = []
        for vid_dir in sorted(videos_dir.iterdir()):
            if not vid_dir.is_dir():
                continue
            meta_file = vid_dir / "metadata.json"
            if not meta_file.exists():
                continue
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            vids.append(
                {
                    "video_id": meta.get("video_id"),
                    "title": meta.get("title"),
                    "upload_date": meta.get("upload_date"),
                    "duration": meta.get("duration"),
                    "url": meta.get("url"),
                    "has_transcript": artifact_exists(vid_dir, "transcript", extension="txt"),
                    "has_insights": artifact_exists(vid_dir, "insights"),
                }
            )
        vids.sort(key=lambda v: v.get("upload_date") or "", reverse=True)
        out_channels.append({"channel": ch.name, "total": len(vids), "videos": vids[:limit]})
    return {"topic": topic, "channels": out_channels, "count": len(out_channels)}


def videos(  # noqa: C901 — legacy, will refactor
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
        if _json_mode_active():
            _emit_json({"topic": topic, "channels": [], "count": 0})
            return
        console.print(f"[yellow]No channels found for topic '{topic}'[/yellow]")
        return

    if _json_mode_active():
        _emit_json(_videos_payload(config, channels, topic, limit))
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
                meta["_has_transcript"] = artifact_exists(
                    vid_dir,
                    "transcript",
                    extension="txt",
                )
                meta["_has_insights"] = artifact_exists(vid_dir, "insights")
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


def register(app: typer.Typer) -> None:
    """Attach the view commands to the app (called from distill.cli)."""
    app.command(name="library", rich_help_panel="Library")(library_cmd)
    app.command(rich_help_panel="Library")(videos)
