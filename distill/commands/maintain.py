"""Maintenance command group, extracted from the ``_logic`` monolith.

Holds the "Maintain" panel utilities: cost history, store cleanup, open, watch
alerts, status, library migration, and the mixed-source corpus synthesis. The
larger doctor/health and eval commands live in their own modules. Registered via
:func:`register` from ``distill.cli`` (mirroring view / update / init).
"""

from __future__ import annotations

import json
import os
import webbrowser
from datetime import datetime
from pathlib import Path

import typer
from rich import box
from rich.table import Table

from distill._console import console
from distill.banner import show_banner
from distill.cli_shared import output_path as _output_path
from distill.cli_shared import require_model as _require_model
from distill.commands._helpers import _resolve_topic_for_channel, get_config
from distill.commands._helpers import tty_confirm as _tty_confirm

# Completion helper and version probe stay in _logic; the dashboard renderers
# live in commands/dashboard.py (the bare `distill` home screen uses them too).
from distill.commands._logic import _complete_topics, _get_version
from distill.commands.dashboard import (
    _dashboard_snapshot,
    _render_dashboard_html,
    _show_dashboard,
)
from distill.config import DistillConfig
from distill.ingestors.youtube.discovery import discover_videos
from distill.library import Library
from distill.library.paths import find_artifact
from distill.library.state import ChannelState
from distill.pipeline.costs import CostTracker
from distill.pipeline.summary import RunSummary, display_summary
from distill.pipeline.synthesis.corpus import synthesize_corpus

__all__ = [
    "alerts",
    "cleanup",
    "corpus",
    "costs",
    "dashboard",
    "migrate",
    "open_cmd",
    "register",
    "serve",
    "status",
]


def costs(  # noqa: C901 -- legacy, will refactor
    ctx: typer.Context,
    last: int = typer.Option(10, "--last", "-n", help="Number of recent runs to show"),
):
    """Show cost history from past runs.

    Displays actual vs estimated costs, token usage breakdown, and per-run timing.
    """
    import json as _json

    from distill.commands._json import JsonEnvelope

    config = get_config()
    # Check new location first, fall back to old
    ops_log = config.library_dir / ".distill" / "cost_log.jsonl"
    legacy_log = config.library_dir / "cost_log.jsonl"
    log_file = ops_log if ops_log.exists() else legacy_log
    json_mode = ctx.obj.get("json", False) if ctx.obj else False

    if not log_file.exists():
        if json_mode:
            envelope = JsonEnvelope.success(
                {"runs": [], "total_cost": 0, "message": "No cost history yet."}
            )
            import sys

            sys.stdout.write(envelope.to_json() + "\n")
        else:
            console.print("[dim]No cost history yet. Costs are logged after each run.[/dim]")
        return

    entries = []
    for line in log_file.read_text(encoding="utf-8").strip().split("\n"):
        if line.strip():
            try:
                entries.append(_json.loads(line))
            except _json.JSONDecodeError:
                continue

    if not entries:
        if json_mode:
            envelope = JsonEnvelope.success(
                {"runs": [], "total_cost": 0, "message": "No cost entries found."}
            )
            import sys

            sys.stdout.write(envelope.to_json() + "\n")
        else:
            console.print("[dim]No cost entries found.[/dim]")
        return

    # `entries[-0:]` is the whole list, so guard explicitly: --last 0 (or a
    # negative) shows nothing rather than every run.
    recent = entries[-last:] if last > 0 else []
    total_cost = sum(e.get("actual_cost", 0) for e in recent)

    from distill.pipeline.costs import estimator_accuracy

    accuracy = estimator_accuracy(entries)

    if json_mode:
        # Compute local/cloud split from telemetry
        local_cloud = _compute_local_cloud_stats(config)
        envelope = JsonEnvelope.success(
            {
                "runs": recent,
                "total_cost": round(total_cost, 4),
                "runs_shown": len(recent),
                "cloud_spend_usd": round(total_cost, 4),
                "local_inference_seconds": local_cloud.get("local_total_seconds", 0),
                "local_tokens_total": local_cloud.get("local_total_tokens", 0),
                "local_avg_tokens_per_second": local_cloud.get("avg_tokens_per_second", 0),
                "estimator_accuracy": accuracy,
            }
        )
        import sys

        sys.stdout.write(envelope.to_json() + "\n")
        return

    table = Table(title="Cost History", box=box.ROUNDED, show_header=True)
    table.add_column("Date", style="dim")
    table.add_column("Command")
    table.add_column("Topic", style="cyan")
    table.add_column("Sources", justify="right")
    table.add_column("Cost", justify="right", style="green")
    table.add_column("Tokens (in/out)", justify="right", style="dim")
    table.add_column("Time", justify="right")

    for e in recent:
        ts = e.get("timestamp", "")[:10]
        cmd = e.get("command", "?")
        # Topic from metadata
        metadata = e.get("metadata", {}) or {}
        topic = metadata.get("topic", "—")
        # Sources: combine video/paper/page counts
        source_parts: list[str] = []
        fv = e.get("full_videos", 0)
        if fv:
            source_parts.append(f"{fv}v")
        papers = metadata.get("papers", 0)
        if papers:
            source_parts.append(f"{papers}p")
        elif cmd == "papers":
            source_parts.append("papers")
        pages = metadata.get("pages", 0)
        if pages:
            source_parts.append(f"{pages}pg")
        sources_str = " ".join(source_parts) if source_parts else "—"
        # Cost
        actual = e.get("actual_cost", 0)
        cost_str = f"${actual:.4f}" if actual < 0.01 else f"${actual:.2f}"
        tokens = f"{e.get('total_input_tokens', 0):,} / {e.get('total_output_tokens', 0):,}"
        elapsed = e.get("elapsed_seconds", 0)
        if elapsed > 60:
            time_str = f"{int(elapsed // 60)}m {int(elapsed % 60)}s"
        else:
            time_str = f"{elapsed:.0f}s"
        table.add_row(ts, cmd, topic, sources_str, cost_str, tokens, time_str)

    console.print(table)
    console.print(f"\n[bold]Total across {len(recent)} runs: ${total_cost:.4f}[/bold]")

    # Estimator accountability: the estimator promises accuracy, not padding --
    # this line is what makes that promise checkable run over run.
    if accuracy:
        bias = accuracy["median_signed_pct_error"]
        direction = "overestimates" if bias > 0 else "underestimates"
        console.print(
            f"[bold]Estimator accuracy[/bold] ({accuracy['runs_compared']} runs with estimates): "
            f"median error {accuracy['median_abs_pct_error']:.0f}%, typically {direction} "
            f"by {abs(bias):.0f}% (last 10 runs: {accuracy['recent10_median_abs_pct_error']:.0f}%)"
        )

    # Local vs Cloud split from telemetry
    _costs_local_cloud_section(config)

    # Per-call-type breakdown for each run
    for e in recent:
        by_type = e.get("by_call_type", {})
        if by_type:
            console.print("\n[dim]Latest run breakdown:[/dim]")
            run_ts = e.get("timestamp", "")[:16]
            run_cmd = e.get("command", "?")
            breakdown_table = Table(
                title=f"Breakdown: {run_cmd} ({run_ts})",
                box=box.SIMPLE,
                show_header=True,
            )
            breakdown_table.add_column("Call Type", style="dim")
            breakdown_table.add_column("Calls", justify="right")
            breakdown_table.add_column("Input Tokens", justify="right")
            breakdown_table.add_column("Output Tokens", justify="right")
            for ct, data in sorted(by_type.items()):
                breakdown_table.add_row(
                    ct,
                    str(data["calls"]),
                    f"{data['input_tokens']:,}",
                    f"{data['output_tokens']:,}",
                )
            console.print(breakdown_table)


def _compute_local_cloud_stats(config: DistillConfig) -> dict:
    """Compute local/cloud inference stats from telemetry.jsonl for JSON output."""
    ops_dir = str(config.library_dir / ".distill")
    telemetry_path = Path(ops_dir) / "telemetry.jsonl"
    if not telemetry_path.exists():
        return {}

    local_total_seconds = 0.0
    local_total_tokens = 0
    local_records_count = 0
    total_tps_sum = 0.0

    try:
        import json as _json

        for line in telemetry_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = _json.loads(line)
                if data.get("provider_type") == "local":
                    local_records_count += 1
                    local_total_seconds += float(data.get("elapsed_seconds", 0))
                    local_total_tokens += int(data.get("output_tokens", 0)) + int(
                        data.get("input_tokens", 0)
                    )
                    tps = float(data.get("tokens_per_second", 0))
                    if tps > 0:
                        total_tps_sum += tps
            except (ValueError, TypeError, _json.JSONDecodeError):
                continue
    except OSError:
        return {}

    avg_tps = round(total_tps_sum / local_records_count, 1) if local_records_count > 0 else 0
    return {
        "local_total_seconds": round(local_total_seconds, 1),
        "local_total_tokens": local_total_tokens,
        "avg_tokens_per_second": avg_tps,
    }


def _costs_local_cloud_section(config: DistillConfig) -> None:  # noqa: C901
    """Display local vs cloud inference split from telemetry.jsonl."""
    ops_dir = str(config.library_dir / ".distill")
    telemetry_path = Path(ops_dir) / "telemetry.jsonl"
    if not telemetry_path.exists():
        return

    # Parse all telemetry records
    local_total_seconds = 0.0
    local_total_tokens = 0
    local_records_count = 0
    cloud_records_count = 0
    total_tps_sum = 0.0

    try:
        import json as _json

        for line in telemetry_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = _json.loads(line)
                provider_type = data.get("provider_type", "cloud")
                if provider_type == "local":
                    local_records_count += 1
                    elapsed = float(data.get("elapsed_seconds", 0))
                    local_total_seconds += elapsed
                    out_tokens = int(data.get("output_tokens", 0))
                    in_tokens = int(data.get("input_tokens", 0))
                    local_total_tokens += out_tokens + in_tokens
                    tps = float(data.get("tokens_per_second", 0))
                    if tps > 0:
                        total_tps_sum += tps
                else:
                    cloud_records_count += 1
            except (ValueError, TypeError, _json.JSONDecodeError):
                continue
    except OSError:
        return

    if local_records_count == 0 and cloud_records_count == 0:
        return

    console.print()
    console.print("[bold]Inference Split[/bold]")

    if cloud_records_count > 0:
        console.print(f"  Cloud calls:       {cloud_records_count:,}")

    if local_records_count > 0:
        avg_tps = total_tps_sum / local_records_count if local_records_count > 0 else 0
        console.print(f"  Local calls:       {local_records_count:,}")
        console.print(f"  Local time:        {local_total_seconds:.1f}s")
        console.print(f"  Local tokens:      {local_total_tokens:,}")
        if avg_tps > 0:
            console.print(f"  Avg tokens/sec:    {avg_tps:.1f}")


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

    from distill.pipeline.report.file_search import cleanup_stores, list_stores

    client = genai.Client(api_key=config.gemini_api_key.get_secret_value())

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


def open_cmd(  # noqa: C901 -- legacy, will refactor
    topic: str = typer.Argument(None, help="Topic or channel name"),
    channel: str | None = typer.Option(None, "--channel", "-c", help="Specific channel"),
    what: str = typer.Option(
        "output",
        "--what",
        "-w",
        help="What to open: output, library, report, synthesis",
    ),
    vault: bool = typer.Option(
        False,
        "--vault",
        help="Open library directory as an Obsidian vault",
    ),
    path: str = typer.Option(
        "",
        "--path",
        help="Subdirectory within library/ to open (use with --vault)",
    ),
):
    """Open output files or directories in your file explorer.

    Examples:
      distill open                    # Open the output/ directory
      distill open ai                 # Open the ai topic directory
      distill open NateBJones         # Open channel directory (auto-resolves topic)
      distill open --what report ai   # Open the report
      distill open --vault            # Open library as Obsidian vault
      distill open --vault --path topics/ai-agents  # Open subdirectory
    """
    import subprocess

    config = get_config()

    # --- Vault mode ---
    if vault:
        library_dir = config.library_dir
        if not library_dir.exists():
            console.print(f"[red]Error: library directory does not exist: {library_dir}[/red]")
            raise typer.Exit(1)

        target = library_dir
        if path:
            target = library_dir / path
            if not target.exists():
                console.print(f"[red]Error: subdirectory not found: {target}[/red]")
                # List available subdirectories
                available = [
                    d.relative_to(library_dir) for d in library_dir.iterdir() if d.is_dir()
                ]
                if available:
                    console.print("\n  Available subdirectories:")
                    for d in sorted(available):
                        console.print(f"    • {d}")
                raise typer.Exit(1)

        # Check for DISTILL_VAULT_EDITOR env var
        vault_editor = os.environ.get("DISTILL_VAULT_EDITOR")
        if vault_editor:
            import shutil

            if not shutil.which(vault_editor):
                console.print(
                    f"[red]Error: DISTILL_VAULT_EDITOR program not found: {vault_editor}[/red]\n"
                    f"  Ensure the program is installed and in your PATH."
                )
                raise typer.Exit(1)
            console.print(f"Opening [bold]{target}[/bold] with {vault_editor}")
            subprocess.run([vault_editor, str(target)])
        else:
            console.print(f"Opening [bold]{target}[/bold]")
            webbrowser.open(str(target))
        return

    # --- Original open logic ---
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
        from distill.pipeline.report.deep_research import _get_report_path

        scope = "channel" if channel else "topic"
        target = _get_report_path(topic, config, scope, channel)
    elif what == "synthesis" and topic and channel:
        target = find_artifact(
            config.channel_dir(topic, channel),
            "synthesis",
            identity=f"{topic}_{channel}",
        )
    elif what == "synthesis" and topic:
        target = find_artifact(config.topic_dir(topic), "topic_synthesis", identity=topic)
    else:
        target = config.library_dir.parent / "output"

    if channel and what == "output":
        target = config.channel_dir(topic, channel)

    if not target.exists():
        console.print(f"[yellow]Not found: {target}[/yellow]")
        raise typer.Exit(1)

    console.print(f"Opening [bold]{target}[/bold]")
    startfile = getattr(os, "startfile", None)
    if startfile is not None:
        startfile(target)
    else:
        subprocess.run(["open" if os.uname().sysname == "Darwin" else "xdg-open", str(target)])


def alerts(
    ctx: typer.Context,
) -> None:
    """Show the current watch-alert digest."""
    from distill.commands._json import JsonEnvelope
    from distill.library.paths import find_artifact

    config = get_config()
    alert_path = find_artifact(config.library_dir, "watch_alerts", identity="library")

    json_mode = ctx.obj.get("json", False) if ctx.obj else False

    if alert_path.exists():
        content = alert_path.read_text(encoding="utf-8")
        if json_mode:
            envelope = JsonEnvelope.success({"alerts": content})
            import sys

            sys.stdout.write(envelope.to_json() + "\n")
        else:
            from rich.markdown import Markdown

            console.print(Markdown(content))
    else:
        if json_mode:
            envelope = JsonEnvelope.success({"alerts": None, "message": "No watch alerts found."})
            import sys

            sys.stdout.write(envelope.to_json() + "\n")
        else:
            console.print("[dim]No watch alerts found.[/dim]")


def status(  # noqa: C901 — legacy, will refactor
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
            for a_name, path in [
                ("context", ch_dir / "channel_context.md"),
                ("synthesis", find_artifact(ch_dir, "synthesis", identity=f"{topic}_{ch.name}")),
                ("report", find_artifact(ch_dir, "report", identity=f"{topic}_{ch.name}")),
            ]:
                if path.exists():
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
        for label, path in [
            ("synthesis", find_artifact(topic_dir, "topic_synthesis", identity=topic)),
            ("brief", find_artifact(topic_dir, "brief", identity=topic)),
            ("report", find_artifact(topic_dir, "report", identity=topic)),
        ]:
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


def migrate(  # noqa: C901 — legacy, will refactor
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Rename video directories from IDs to human-readable slugs.

    Renames directories like 'abc123xyz' to 'gpt-5-4-production-db-safety_abc123xy'.
    Safe to run multiple times -- already-migrated directories are skipped.
    """
    from distill.library.paths import slugify_title

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

    if not yes and not _tty_confirm(f"Rename {len(to_rename)} directories?"):
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


def corpus(
    topic: str = typer.Argument(
        help="Topic to synthesize as a mixed-source corpus", autocompletion=_complete_topics
    ),
):
    """Build a mixed-source corpus synthesis for a topic."""
    config = get_config()
    _require_model()
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

    summary.add_output(find_artifact(config.topic_dir(topic), "corpus_synthesis", identity=topic))
    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)


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


def serve(
    port: int = typer.Option(8899, "--port", "-p", help="Port to serve on"),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind to"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open browser on start"),
):
    """Launch a local web dashboard for browsing your library."""
    from distill.web.server import run_server

    run_server(get_config(), host=host, port=port, open_browser=open_browser)


def register(app: typer.Typer) -> None:
    """Attach the maintenance commands to the app (called from distill.cli)."""
    app.command(rich_help_panel="Maintain")(costs)
    app.command(rich_help_panel="Maintain")(cleanup)
    app.command(name="open", rich_help_panel="Maintain")(open_cmd)
    app.command(rich_help_panel="Maintain")(alerts)
    app.command(rich_help_panel="Maintain")(status)
    app.command(rich_help_panel="Maintain")(migrate)
    app.command(rich_help_panel="Maintain")(corpus)
    app.command(rich_help_panel="Maintain")(dashboard)
    app.command(rich_help_panel="View")(serve)
