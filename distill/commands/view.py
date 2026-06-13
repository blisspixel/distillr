"""Corpus-browsing / view commands, extracted from the `_logic` monolith.

First command-group slice of the decomposition (how-we-build.md remediation #1).
Registered onto the app via :func:`register` from ``distill.cli`` (mirroring
ask / audit / update), so `_logic` no longer owns these commands. Pure
relocation -- no behavior change.
"""

from __future__ import annotations

import typer
from rich import box
from rich.panel import Panel
from rich.table import Table

from distill._console import console
from distill.commands._helpers import format_date as _format_date
from distill.commands._helpers import get_config
from distill.commands._json import emit_json as _emit_json
from distill.commands._json import json_mode_active as _json_mode_active
from distill.library import Library
from distill.library.paths import artifact_exists
from distill.library.state import ChannelState

__all__ = ["library_cmd", "register"]


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


def register(app: typer.Typer) -> None:
    """Attach the view commands to the app (called from distill.cli)."""
    app.command(name="library", rich_help_panel="Library")(library_cmd)
