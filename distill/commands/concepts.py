# pyright: strict
"""``distill concepts`` subcommands: build + the recovery surface (log/diff/rollback).

This module owns the ``concepts_app`` group plus the commands attached to it.
``build`` extracts and merges concept notes; ``log``, ``diff``, and
``rollback`` operate over the ``.history/`` snapshots ``build`` writes on every
overwrite.

All logic lives in ``distill.concepts.*``; these functions are the thin Typer +
rich presentation layer over it.
"""

from __future__ import annotations

from pathlib import Path

import typer

from distill._console import console
from distill.commands._helpers import (
    _complete_topics,
    budgeted_cost_tracker,
    get_config,
    save_command_cost,
    tty_confirm,
)
from distill.commands._json import ExitCode, emit_json, json_mode_active
from distill.concepts import recovery
from distill.concepts.records import utcnow_iso

__all__ = [
    "concept_diff_cmd",
    "concept_log_cmd",
    "concept_rollback_cmd",
    "concepts_app",
    "concepts_build",
    "register",
]


concepts_app = typer.Typer(
    help=(
        "Concept and entity playbook for a topic.\n\n"
        "  distill concepts build <topic>            extract + merge playbook notes\n"
        "  distill concepts log <topic> <slug>       list a note's history snapshots\n"
        "  distill concepts diff <topic> <slug>      diff a note against its history\n"
        "  distill concepts rollback <topic> <slug> <timestamp>   restore a snapshot\n"
    ),
    rich_markup_mode="rich",
    no_args_is_help=True,
)


def concepts_build(
    topic: str = typer.Argument(
        ..., help="Topic name (existing or new)", autocompletion=_complete_topics
    ),
    refresh: bool = typer.Option(
        False,
        "--refresh",
        help="Re-extract over every insight, ignoring the existing mentions.jsonl log",
    ),
    threshold: int = typer.Option(
        3,
        "--threshold",
        "-t",
        help="Minimum distinct sources to emit a concept note (default 3, the noise floor)",
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit a machine-readable summary envelope"),
):
    """Extract and merge concept / entity playbook notes for a topic.

    Walks library/topics/<topic>/{papers,videos,sites}/**/*_Insights.md,
    runs the concept-extraction LLM pass over any insight not already
    in mentions.jsonl, then merges and writes:

      library/topics/<topic>/concepts/<slug>.md      (techniques, etc.)
      library/topics/<topic>/entities/<slug>.md      (people, orgs, vendors)
      library/topics/<topic>/concepts.jsonl          (rollup)
      library/topics/<topic>/entities.jsonl          (rollup)

    Idempotent: re-running without --refresh skips already-extracted
    insights and only re-writes notes whose merged content actually
    changed.
    """
    from distill.concepts import run_concepts
    from distill.llm import RouterConfig

    config = get_config()
    topic_dir = config.topic_dir(topic)
    if not topic_dir.exists():
        console.print(f"[red]Topic directory does not exist: {topic_dir}[/red]")
        raise typer.Exit(ExitCode.NOT_FOUND)

    rc = RouterConfig()
    tracker = budgeted_cost_tracker(config, "concepts")
    try:
        summary = run_concepts(
            topic=topic,
            topic_dir=topic_dir,
            rc=rc,
            threshold=threshold,
            refresh=refresh,
            tracker=tracker,
        )

        if json_out or json_mode_active():
            payload = summary.to_dict()
            payload["cost"] = tracker.format_cost()
            emit_json(payload)
            return

        console.print()
        console.print(f"[bold]Concept playbook -- {topic}[/bold]")
        console.print(f"  Insights scanned:    {summary.insights_scanned}")
        console.print(f"  Insights extracted:  {summary.insights_extracted}")
        console.print(f"  Mentions added:      {summary.mentions_added}")
        console.print(
            f"  Concept notes:       {summary.concepts_written} written, "
            f"{summary.concepts_unchanged} unchanged"
        )
        console.print(f"  Entity notes:        {summary.entities_written} written")
        console.print(f"  Cost:                {tracker.format_cost()}")
        console.print()
        if summary.insights_extracted == 0 and summary.mentions_added == 0:
            console.print(
                "  [dim]No new insights to extract. Use --refresh to re-extract over all "
                "sources.[/dim]"
            )
    finally:
        save_command_cost(
            config,
            "concepts",
            tracker,
            metadata={"topic": topic, "workflow": "concepts", "source_type": "mixed"},
        )


def _resolve_topic_dir(topic: str) -> Path:
    """Return the topic directory, erroring out cleanly if it's missing."""
    config = get_config()
    topic_dir = config.topic_dir(topic)
    if not topic_dir.exists():
        console.print(f"[red]Topic directory does not exist: {topic_dir}[/red]")
        raise typer.Exit(ExitCode.NOT_FOUND)
    return topic_dir


def concept_log_cmd(
    topic: str = typer.Argument(..., help="Topic name", autocompletion=_complete_topics),
    slug: str = typer.Argument(..., help="Concept/entity slug (filename stem of the note)"),
):
    """List a note's history snapshots, newest first, with per-step change summaries."""
    topic_dir = _resolve_topic_dir(topic)
    if recovery.note_path_for_slug(topic_dir, slug) is None and not recovery.list_snapshots(
        topic_dir, slug
    ):
        console.print(
            f"[red]No concept or entity note found for slug '{slug}' in topic '{topic}'.[/red]"
        )
        raise typer.Exit(ExitCode.NOT_FOUND)

    snapshots = recovery.list_snapshots(topic_dir, slug)
    live_path = recovery.note_path_for_slug(topic_dir, slug)
    live_content = live_path.read_text(encoding="utf-8") if live_path else None

    console.print()
    console.print(f"[bold]Concept playbook history -- {slug}[/bold]  [dim](topic: {topic})[/dim]")
    if not snapshots:
        console.print(
            "  [dim]No history snapshots: the note has not been overwritten since creation.[/dim]"
        )
        console.print()
        return

    console.print(f"  [dim]{len(snapshots)} snapshot(s), newest first[/dim]")
    console.print()

    # Walk newest -> oldest. Each snapshot is the content that was live
    # until it was replaced by the *next newer* state, so the summary on
    # each row describes that forward transition.
    newer_label = "current"
    newer_fields = recovery.parse_note_fields(live_content) if live_content is not None else None
    for snap in reversed(snapshots):
        snap_fields = recovery.parse_note_fields(snap.path.read_text(encoding="utf-8"))
        if newer_fields is not None:
            summary = recovery.summarize_transition(snap_fields, newer_fields)
            console.print(f"  [cyan]{snap.iso}[/cyan]  ->  {newer_label:<22}  [dim]{summary}[/dim]")
        else:
            console.print(f"  [cyan]{snap.iso}[/cyan]  [dim](no live note)[/dim]")
        newer_label = snap.iso
        newer_fields = snap_fields
    console.print()
    console.print(f"  [dim]Inspect: distill concepts diff {topic} {slug} <timestamp>[/dim]")
    console.print(f"  [dim]Restore: distill concepts rollback {topic} {slug} <timestamp>[/dim]")
    console.print()


def _diff_line_style(line: str) -> str:
    if line.startswith("+") and not line.startswith("+++"):
        return "green"
    if line.startswith("-") and not line.startswith("---"):
        return "red"
    if line.startswith("@@"):
        return "cyan"
    return "dim"


def _render_frontmatter_changes(diff: recovery.NoteDiff) -> None:
    console.print("  [bold]Frontmatter changes[/bold]")
    for sid in diff.sources_added:
        console.print(f"    [green]+ source[/green] {sid}")
    for sid in diff.sources_removed:
        console.print(f"    [red]- source[/red] {sid}")
    for sid, old_pol, new_pol in diff.sources_repolarized:
        console.print(f"    [yellow]~ source[/yellow] {sid}  {old_pol} -> {new_pol}")
    for change in diff.field_changes:
        console.print(f"    [yellow]{change.field}[/yellow]: {change.old} -> {change.new}")
    console.print()


def _render_diff(diff: recovery.NoteDiff) -> None:
    console.print(f"  [cyan]{diff.old_label}[/cyan]  ->  [cyan]{diff.new_label}[/cyan]")
    console.print()

    if diff.is_empty:
        console.print("  [green]No differences.[/green]")
        console.print()
        return

    if diff.has_frontmatter_changes:
        _render_frontmatter_changes(diff)

    if diff.body_diff.strip():
        console.print("  [bold]Body changes[/bold]")
        for line in diff.body_diff.splitlines():
            console.print(f"    [{_diff_line_style(line)}]{line}[/{_diff_line_style(line)}]")
        console.print()


def concept_diff_cmd(
    topic: str = typer.Argument(..., help="Topic name", autocompletion=_complete_topics),
    slug: str = typer.Argument(..., help="Concept/entity slug (filename stem of the note)"),
    ts_a: str = typer.Argument(
        "",
        help="Older timestamp. Omit to diff the most recent snapshot against the live note.",
    ),
    ts_b: str = typer.Argument(
        "",
        help="Newer timestamp. Omit to use the live note as the newer side.",
    ),
):
    """Diff a concept note against its history.

    No timestamps: most recent snapshot vs the live note.
    One timestamp:  that snapshot vs the live note.
    Two timestamps: the first snapshot vs the second.
    """
    topic_dir = _resolve_topic_dir(topic)
    live_path = recovery.note_path_for_slug(topic_dir, slug)
    snapshots = recovery.list_snapshots(topic_dir, slug)

    if live_path is None and not snapshots:
        console.print(
            f"[red]No concept or entity note found for slug '{slug}' in topic '{topic}'.[/red]"
        )
        raise typer.Exit(ExitCode.NOT_FOUND)

    def _snapshot_or_exit(ts: str) -> recovery.Snapshot:
        snap = recovery.resolve_snapshot(topic_dir, slug, ts)
        if snap is None:
            console.print(
                f"[red]No snapshot for '{slug}' matching '{ts}'.[/red] "
                f"Run: distill concepts log {topic} {slug}"
            )
            raise typer.Exit(ExitCode.NOT_FOUND)
        return snap

    console.print()
    console.print(f"[bold]Diff -- {slug}[/bold]  [dim](topic: {topic})[/dim]")

    if ts_a and ts_b:
        a, b = _snapshot_or_exit(ts_a), _snapshot_or_exit(ts_b)
        diff = recovery.diff_notes(
            a.path.read_text(encoding="utf-8"),
            b.path.read_text(encoding="utf-8"),
            old_label=a.iso,
            new_label=b.iso,
        )
    else:
        if live_path is None:
            console.print("[red]No live note to diff against; pass two timestamps.[/red]")
            raise typer.Exit(ExitCode.NOT_FOUND)
        if ts_a:
            old = _snapshot_or_exit(ts_a)
        elif snapshots:
            old = snapshots[-1]
        else:
            console.print("  [dim]No history snapshots yet; nothing to diff.[/dim]")
            console.print()
            return
        diff = recovery.diff_notes(
            old.path.read_text(encoding="utf-8"),
            live_path.read_text(encoding="utf-8"),
            old_label=old.iso,
            new_label="current",
        )

    _render_diff(diff)


def concept_rollback_cmd(
    topic: str = typer.Argument(..., help="Topic name", autocompletion=_complete_topics),
    slug: str = typer.Argument(..., help="Concept/entity slug (filename stem of the note)"),
    timestamp: str = typer.Argument(..., help="Snapshot timestamp to restore (see `concepts log`)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt"),
):
    """Restore a note to a prior snapshot, rewriting its rollup row to match.

    Reversible: the current content is snapshot into ``.history`` before
    the restore, so the rollback can itself be rolled back.
    """
    topic_dir = _resolve_topic_dir(topic)

    snap = recovery.resolve_snapshot(topic_dir, slug, timestamp)
    if snap is None:
        console.print(
            f"[red]No snapshot for '{slug}' matching '{timestamp}'.[/red] "
            f"Run: distill concepts log {topic} {slug}"
        )
        raise typer.Exit(ExitCode.NOT_FOUND)

    if not yes and not tty_confirm(
        f"Restore '{slug}' to its {snap.iso} snapshot? The current version is backed up first."
    ):
        console.print("[yellow]Aborted.[/yellow]")
        raise typer.Exit(1)

    result = recovery.rollback(topic_dir, slug, timestamp, now_iso=utcnow_iso())

    console.print()
    if result.rollup_path is None:
        console.print(
            f"  [green]Live note already matches the {result.restored_from} snapshot; "
            "nothing to do.[/green]"
        )
        console.print()
        return

    rel = result.note_path.relative_to(topic_dir)
    console.print(f"  [green]Restored[/green] {rel} to {result.restored_from}")
    if result.backup_path is not None:
        console.print(
            f"  [dim]Backed up previous version to "
            f"{result.backup_path.relative_to(topic_dir)}[/dim]"
        )
    console.print(f"  [dim]Updated rollup {result.rollup_path.relative_to(topic_dir)}[/dim]")
    console.print()


def register(concepts_app: typer.Typer) -> None:
    """Attach the build + recovery subcommands to the ``concepts`` group."""
    concepts_app.command(name="build", rich_help_panel="Library")(concepts_build)
    concepts_app.command(name="log", rich_help_panel="Library")(concept_log_cmd)
    concepts_app.command(name="diff", rich_help_panel="Library")(concept_diff_cmd)
    concepts_app.command(name="rollback", rich_help_panel="Library")(concept_rollback_cmd)
