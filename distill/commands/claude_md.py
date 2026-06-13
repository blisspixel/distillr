"""``distill claude-md`` -- (re)generate agent-orientation CLAUDE.md files.

Thin Typer + rich presentation over :mod:`distill.library.claude_md`, which
does the templating. Registered onto the app from ``distill.cli`` (mirrors the
``ingest`` and ``concepts`` recovery modules).

The files are regenerated automatically on every topic refresh (the synthesis
writers call into the same library functions); this command is the manual
trigger, used mainly to backfill existing topics or refresh on demand.
"""

from __future__ import annotations

from datetime import UTC, datetime

import typer

from distill._console import console
from distill.commands import _logic
from distill.commands._logic import _complete_topics
from distill.library import claude_md

__all__ = ["claude_md_cmd", "register"]


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def claude_md_cmd(
    topic: str = typer.Argument(
        "",
        help="Topic to regenerate. Omit and pass --all for every topic.",
        autocompletion=_complete_topics,
    ),
    all_topics: bool = typer.Option(
        False,
        "--all",
        help="Regenerate CLAUDE.md + AGENTS.md for every topic in the library.",
    ),
):
    """Regenerate per-topic and library-root CLAUDE.md + AGENTS.md orientation files.

    Coding agents auto-load an orientation file when they enter a directory,
    but the convention split by vendor: Claude Code reads `CLAUDE.md`; Codex,
    Cursor, Gemini CLI and the cross-vendor AGENTS.md standard read
    `AGENTS.md`. distillr writes identical content under both names, per topic
    and at the library root, so any agent that `cd`s in gets oriented.
    """
    config = _logic.get_config()
    library_dir = config.library_dir
    now_iso = _now_iso()

    if all_topics:
        topics_dir = config.topics_dir()
        written = 0
        if topics_dir.is_dir():
            for child in sorted(topics_dir.iterdir(), key=lambda p: p.name.lower()):
                if (
                    child.is_dir()
                    and not child.name.startswith(".")
                    and claude_md.write_topic_claude_md(child, child.name, now_iso=now_iso)
                ):
                    written += 1
        lib = claude_md.write_library_claude_md(library_dir, now_iso=now_iso)
        console.print(
            f"[green]Regenerated {written} topic CLAUDE.md + AGENTS.md pair(s)[/green] "
            "+ the library index."
        )
        console.print(f"  [dim]Library index: {lib}[/dim]")
        return

    if not topic:
        console.print("[red]Provide a <topic>, or use --all to regenerate every topic.[/red]")
        raise typer.Exit(1)

    topic_dir = config.topic_dir(topic)
    if not topic_dir.exists():
        console.print(f"[red]Topic directory does not exist: {topic_dir}[/red]")
        raise typer.Exit(1)

    path = claude_md.write_topic_claude_md(topic_dir, topic, now_iso=now_iso)
    lib = claude_md.write_library_claude_md(library_dir, now_iso=now_iso)
    if path is None:
        console.print(
            f"[yellow]Topic '{topic}' has no synthesis or sources yet; "
            "per-topic CLAUDE.md skipped.[/yellow]"
        )
    else:
        console.print(f"[green]Wrote[/green] {path}")
    console.print(f"  [dim]Updated library index: {lib}[/dim]")


def register(app: typer.Typer) -> None:
    """Register ``claude-md`` on the given app."""
    app.command(name="claude-md", rich_help_panel="Library")(claude_md_cmd)
