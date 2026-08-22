# pyright: strict
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
from distill._version import get_version as _get_version
from distill.banner import show_banner
from distill.cli_shared import output_path as _output_path
from distill.cli_shared import require_model as _require_model
from distill.commands._cost_data import (
    biggest_prompt_rows as _biggest_prompt_rows,
)
from distill.commands._cost_data import (
    compute_local_cloud_stats as _compute_local_cloud_stats,
)
from distill.commands._cost_data import (
    cost_warnings_for_config as _cost_warnings_for_config,
)
from distill.commands._cost_data import (
    dict_or_empty as _dict_or_empty,
)
from distill.commands._cost_data import (
    performance_evidence as _performance_evidence,
)
from distill.commands._cost_data import (
    provider_telemetry_json as _provider_telemetry_json,
)
from distill.commands._cost_data import (
    safe_float as _safe_float,
)
from distill.commands._cost_data import (
    safe_int as _safe_int,
)
from distill.commands._costs_sections import (
    costs_biggest_prompts_section as _costs_biggest_prompts_section,
)
from distill.commands._costs_sections import (
    costs_local_cloud_section as _costs_local_cloud_section,
)
from distill.commands._helpers import (
    _complete_topics,
    budgeted_cost_tracker,
    enforce_projected_workflow_budget,
    get_config,
)
from distill.commands._helpers import tty_confirm as _tty_confirm
from distill.commands._json import ExitCode
from distill.commands._performance_view import (
    render_cost_history_integrity as _render_cost_history_integrity,
)
from distill.commands._performance_view import (
    render_performance_evidence as _render_performance_evidence,
)
from distill.commands._topic_resolution import (
    resolve_required_topic_for_channel as _resolve_required_topic_for_channel,
)

# Dashboard renderers live in commands/dashboard.py.
from distill.commands.dashboard import (
    dashboard_snapshot,
    render_dashboard_html,
    show_dashboard,
)
from distill.ingestors.youtube.discovery import discover_videos
from distill.library import Library
from distill.library.insights import discover_insights
from distill.library.paths import atomic_write_text, find_artifact
from distill.library.state import ChannelInfo, ChannelState
from distill.llm.cost_policy import require_route_allowed
from distill.llm.router import RouterConfig
from distill.pipeline.cost_history import (
    CostLogScan,
    scan_confined_cost_log,
    select_cost_log_path,
)
from distill.pipeline.costs import estimate_synthesis_workflow_cost, projected_next_run_cost
from distill.pipeline.dashboard_data import sum_recent_cost
from distill.pipeline.summary import RunSummary, display_summary
from distill.pipeline.synthesis.corpus import has_corpus_synthesis_inputs, synthesize_corpus

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
    from distill.commands._json import JsonEnvelope

    config = get_config()
    # Check new location first, fall back to old
    ops_log = config.library_dir / ".distill" / "cost_log.jsonl"
    log_file = select_cost_log_path(config.library_dir) or ops_log
    json_mode = ctx.obj.get("json", False) if ctx.obj else False
    biggest_prompts = _biggest_prompt_rows(config)
    performance = _performance_evidence(
        config,
        cost_log_path=log_file,
        limit=max(0, last),
    )

    if not log_file.exists():
        if json_mode:
            local_cloud = _compute_local_cloud_stats(config)
            envelope = JsonEnvelope.success(
                {
                    "runs": [],
                    "total_cost": 0,
                    "message": "No cost history yet.",
                    "cloud_spend_usd": 0,
                    "local_inference_seconds": local_cloud.get("local_total_seconds", 0),
                    "local_tokens_total": local_cloud.get("local_total_tokens", 0),
                    "local_avg_tokens_per_second": local_cloud.get("avg_tokens_per_second", 0),
                    "provider_telemetry": _provider_telemetry_json(local_cloud),
                    "biggest_prompts": biggest_prompts,
                    "projected_next_run_cost": 0.0,
                    "cost_warnings": [],
                    "cost_history": CostLogScan().coverage(),
                    "performance": performance,
                }
            )
            import sys

            sys.stdout.write(envelope.to_json() + "\n")
        else:
            console.print(
                "[dim]No cost history yet. Costs are logged after each model run to "
                "library/.distill/cost_log.jsonl "
                "(preview with --preview before spending).[/dim]"
            )
            console.print(
                "[dim]Inspect: distill costs · distill --json costs · "
                "distill --cost-mode no-metered doctor[/dim]"
            )
            _render_performance_evidence(performance, console)
            _costs_local_cloud_section(config)
            _costs_biggest_prompts_section(config, biggest_prompts)
        return

    cost_scan = scan_confined_cost_log(log_file, config.library_dir)
    entries = list(cost_scan.rows)

    if not entries:
        if json_mode:
            local_cloud = _compute_local_cloud_stats(config)
            envelope = JsonEnvelope.success(
                {
                    "runs": [],
                    "total_cost": 0,
                    "message": (
                        "Cost history is incomplete; no valid retained entries were found."
                        if not cost_scan.complete
                        else "No cost entries found."
                    ),
                    "cloud_spend_usd": 0,
                    "local_inference_seconds": local_cloud.get("local_total_seconds", 0),
                    "local_tokens_total": local_cloud.get("local_total_tokens", 0),
                    "local_avg_tokens_per_second": local_cloud.get("avg_tokens_per_second", 0),
                    "provider_telemetry": _provider_telemetry_json(local_cloud),
                    "biggest_prompts": biggest_prompts,
                    "projected_next_run_cost": None if not cost_scan.complete else 0.0,
                    "cost_warnings": [],
                    "cost_history": cost_scan.coverage(),
                    "performance": performance,
                }
            )
            import sys

            sys.stdout.write(envelope.to_json() + "\n")
        else:
            _render_cost_history_integrity(log_file, cost_scan, console)
            if cost_scan.complete:
                console.print(
                    "[dim]No cost entries found in the library cost ledger "
                    "(library/.distill/cost_log.jsonl).[/dim]"
                )
            console.print(
                "[dim]Inspect: distill --json costs · distill --cost-mode no-metered doctor[/dim]"
            )
            _render_performance_evidence(performance, console)
            _costs_local_cloud_section(config)
            _costs_biggest_prompts_section(config, biggest_prompts)
        return

    # `entries[-0:]` is the whole list, so guard explicitly: --last 0 (or a
    # negative) shows nothing rather than every run.
    recent = entries[-last:] if last > 0 else []
    total_cost = sum_recent_cost(recent)
    external_cost_unavailable = any(
        entry.get("external_cost_status") == "unavailable" for entry in recent
    )

    from distill.pipeline.costs import estimator_accuracy

    accuracy = estimator_accuracy(entries) if cost_scan.complete else None
    projected = (
        projected_next_run_cost(entries)
        if cost_scan.complete and not external_cost_unavailable
        else None
    )
    cost_warnings = (
        _cost_warnings_for_config(config, entries)
        if cost_scan.complete and total_cost is not None
        else []
    )

    if json_mode:
        # Compute local/cloud split from telemetry
        local_cloud = _compute_local_cloud_stats(config)
        envelope = JsonEnvelope.success(
            {
                "runs": recent,
                "total_cost": round(total_cost, 4) if total_cost is not None else None,
                "total_cost_scope": (
                    "distill-direct-charges"
                    if external_cost_unavailable
                    else "known-provider-charges"
                ),
                "external_cost_status": (
                    "unavailable" if external_cost_unavailable else "complete"
                ),
                "projected_next_run_cost": round(projected, 4) if projected is not None else None,
                "runs_shown": len(recent),
                "cloud_spend_usd": round(total_cost, 4) if total_cost is not None else None,
                "local_inference_seconds": local_cloud.get("local_total_seconds", 0),
                "local_tokens_total": local_cloud.get("local_total_tokens", 0),
                "local_avg_tokens_per_second": local_cloud.get("avg_tokens_per_second", 0),
                "provider_telemetry": _provider_telemetry_json(local_cloud),
                "estimator_accuracy": accuracy,
                "biggest_prompts": biggest_prompts,
                "cost_warnings": cost_warnings,
                "cost_history": cost_scan.coverage(),
                "performance": performance,
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
        ts = str(e.get("timestamp", ""))[:10]
        cmd = str(e.get("command", "?"))
        # Topic from metadata
        metadata = _dict_or_empty(e.get("metadata", {}))
        topic = str(metadata.get("topic", "-") or "-")
        # Sources: combine video/paper/page counts
        source_parts: list[str] = []
        fv = _safe_int(e.get("full_videos", 0))
        if fv:
            source_parts.append(f"{fv}v")
        papers = _safe_int(metadata.get("papers", 0))
        if papers:
            source_parts.append(f"{papers}p")
        elif cmd == "papers":
            source_parts.append("papers")
        pages = _safe_int(metadata.get("pages", 0))
        if pages:
            source_parts.append(f"{pages}pg")
        sources_str = " ".join(source_parts) if source_parts else "-"
        # Cost
        actual = _safe_float(e.get("actual_cost", 0))
        direct_cost = f"${actual:.4f}" if actual < 0.01 else f"${actual:.2f}"
        cost_str = (
            (f"{direct_cost} + unknown" if actual else "external unknown")
            if e.get("external_cost_status") == "unavailable"
            else direct_cost
        )
        tokens = (
            f"{_safe_int(e.get('total_input_tokens', 0)):,} / "
            f"{_safe_int(e.get('total_output_tokens', 0)):,}"
        )
        elapsed = _safe_float(e.get("elapsed_seconds", 0))
        if elapsed > 60:
            time_str = f"{int(elapsed // 60)}m {int(elapsed % 60)}s"
        else:
            time_str = f"{elapsed:.0f}s"
        table.add_row(ts, cmd, topic, sources_str, cost_str, tokens, time_str)

    console.print(table)
    if total_cost is None:
        console.print(
            f"\n[yellow]Total across {len(recent)} runs: unavailable because the cost "
            "values exceed the supported aggregate range.[/yellow]"
        )
    elif external_cost_unavailable:
        console.print(
            f"\n[bold]Known direct total across {len(recent)} runs: ${total_cost:.4f}[/bold]"
        )
        console.print(
            "[yellow]External provider cost is unavailable for one or more runs.[/yellow]"
        )
    else:
        console.print(f"\n[bold]Total across {len(recent)} runs: ${total_cost:.4f}[/bold]")
    _render_cost_history_integrity(log_file, cost_scan, console)

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

    if projected is not None and projected > 0:
        console.print(
            f"[bold]Projected for next similar run[/bold] (avg last up to 5): ${projected:.4f}"
        )

    if cost_warnings:
        console.print("\n[bold yellow]Cost warnings[/bold yellow]")
        for warning in cost_warnings:
            console.print(f"  [yellow]{warning['message']}[/yellow]")

    _render_performance_evidence(performance, console)

    # Local vs Cloud split from telemetry
    _costs_local_cloud_section(config)

    _costs_biggest_prompts_section(config, biggest_prompts)

    # Per-call-type breakdown for the latest run that carries structured
    # details. Older detailed rows stay visible in JSON output.
    latest_detailed = next(
        (
            e
            for e in reversed(recent)
            if isinstance(e.get("by_call_type"), dict) and e.get("by_call_type")
        ),
        None,
    )
    if latest_detailed is not None:
        by_type = _dict_or_empty(latest_detailed.get("by_call_type"))
        console.print("\n[dim]Latest run breakdown:[/dim]")
        run_ts = str(latest_detailed.get("timestamp", ""))[:16]
        run_cmd = str(latest_detailed.get("command", "?"))
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
            row = _dict_or_empty(data)
            if not row:
                continue
            breakdown_table.add_row(
                str(ct),
                str(_safe_int(row.get("calls", 0))),
                f"{_safe_int(row.get('input_tokens', 0)):,}",
                f"{_safe_int(row.get('output_tokens', 0)):,}",
            )
        console.print(breakdown_table)


def cleanup():
    """List and delete orphaned Gemini File Search stores.

    Stores are normally cleaned up automatically after each report run.
    Use this if a run was interrupted or cleanup failed.
    """
    config = get_config()
    require_route_allowed(
        cost_mode=config.distill_cost_mode,
        provider="gemini",
        workload="file-search-cleanup",
    )

    if not config.gemini_api_key:
        console.print("[red]GEMINI_API_KEY required[/red]")
        raise typer.Exit(code=ExitCode.CONFIG_ERROR)

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

    from distill.process_security import package_install_context, resolve_executable

    config = get_config()

    # --- Vault mode ---
    if vault:
        library_dir = config.library_dir
        if not library_dir.exists():
            console.print(f"[red]Error: library directory does not exist: {library_dir}[/red]")
            raise typer.Exit(code=ExitCode.NOT_FOUND)

        library_root = library_dir.resolve()
        target = library_root
        if path:
            target = (library_root / path).resolve()
            try:
                target.relative_to(library_root)
            except ValueError:
                console.print(f"[red]Error: path escapes library directory: {path}[/red]")
                raise typer.Exit(code=ExitCode.USAGE_ERROR) from None
            if not target.exists() or not target.is_dir():
                console.print(f"[red]Error: subdirectory not found: {target}[/red]")
                # List available subdirectories
                available = [
                    d.relative_to(library_root) for d in library_root.iterdir() if d.is_dir()
                ]
                if available:
                    console.print("\n  Available subdirectories:")
                    for d in sorted(available):
                        console.print(f"    • {d}")
                raise typer.Exit(code=ExitCode.NOT_FOUND)

        # Check for DISTILL_VAULT_EDITOR env var
        vault_editor = os.environ.get("DISTILL_VAULT_EDITOR")
        if vault_editor:
            editor_path = resolve_executable(vault_editor)
            if not editor_path:
                console.print(
                    f"[red]Error: DISTILL_VAULT_EDITOR program not found: {vault_editor}[/red]\n"
                    f"  Ensure the program is installed and in your PATH."
                )
                raise typer.Exit(code=ExitCode.CONFIG_ERROR)
            console.print(f"Opening [bold]{target}[/bold] with {vault_editor}")
            trusted_cwd, child_env = package_install_context()
            subprocess.run(
                [editor_path, str(target)],
                cwd=trusted_cwd,
                env=child_env,
                check=False,
            )
        else:
            console.print(f"Opening [bold]{target}[/bold]")
            webbrowser.open(str(target))
        return

    # --- Original open logic ---
    allowed_targets = {"output", "library", "report", "synthesis"}
    if what not in allowed_targets:
        console.print(
            f"[red]Unknown --what '{what}'. Use: output, library, report, synthesis[/red]"
        )
        raise typer.Exit(code=ExitCode.USAGE_ERROR)
    if what in {"report", "synthesis"} and not topic:
        console.print(f"[red]--what {what} requires a topic or channel argument[/red]")
        raise typer.Exit(code=ExitCode.USAGE_ERROR)

    if topic:
        lib = Library(config)
        topic, channel = _resolve_required_topic_for_channel(lib, topic, channel)

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
        console.print(f"[red]Internal error: validated open target is not handled: {what}[/red]")
        raise typer.Exit(code=ExitCode.RUNTIME_ERROR)

    if channel and what == "output":
        target = config.channel_dir(topic, channel)

    if not target.exists():
        console.print(f"[yellow]Not found: {target}[/yellow]")
        raise typer.Exit(code=ExitCode.NOT_FOUND)

    console.print(f"Opening [bold]{target}[/bold]")
    startfile = getattr(os, "startfile", None)
    if startfile is not None:
        startfile(target)
    else:
        opener_name = "open" if os.uname().sysname == "Darwin" else "xdg-open"
        opener_path = resolve_executable(opener_name)
        if opener_path:
            trusted_cwd, child_env = package_install_context()
            subprocess.run(
                [opener_path, str(target)],
                cwd=trusted_cwd,
                env=child_env,
                check=False,
            )
        else:
            webbrowser.open(str(target))


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

    topics = lib.get_corpus_topics()
    if not topics:
        console.print("[dim]Library is empty.[/dim]")
        console.print("[dim]Setup:[/dim]")
        console.print("  [dim]distill --cost-mode no-metered init[/dim]", soft_wrap=True)
        console.print("  [dim]distill --cost-mode no-metered doctor[/dim]", soft_wrap=True)
        console.print(
            '  [dim]distill --cost-mode no-metered papers "topic" -n 5 --preview[/dim]',
            soft_wrap=True,
        )
        return

    total_videos = 0
    total_channels = 0
    total_source_insights = 0

    # ── Show everything instantly (local data only) ───────────
    # Collect channel info for potential online check later
    all_channels: list[tuple[str, ChannelInfo, ChannelState, int]] = []

    for topic in topics:
        channels = lib.get_channels(topic)
        total_channels += len(channels)
        topic_dir = config.topic_dir(topic)
        source_insight_count = len(discover_insights(topic_dir))
        total_source_insights += source_insight_count

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
        insight_label = (
            f"{source_insight_count} source insight{'s' if source_insight_count != 1 else ''}"
        )
        console.print(
            f"\n  [bold]{topic}[/bold]"
            f"    [dim]{ch_label},"
            f" [{_ACCENT}]{topic_videos}[/{_ACCENT}]"
            f" analyzed, {insight_label}[/dim]"
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
            artifacts: list[str] = []
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
        topic_outs: list[str] = []
        for label, path in [
            ("synthesis", find_artifact(topic_dir, "topic_synthesis", identity=topic)),
            (
                "corpus synthesis",
                find_artifact(topic_dir, "corpus_synthesis", identity=topic),
            ),
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
        f" {total_videos} videos analyzed,"
        f" {total_source_insights} source "
        f"insight{'s' if total_source_insights != 1 else ''}"
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
                        raise_on_error=True,
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
    to_rename: list[tuple[Path, Path, str]] = []
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
                try:
                    meta = _dict_or_empty(json.loads(meta_file.read_text(encoding="utf-8")))
                except (OSError, RecursionError, UnicodeError, ValueError):
                    continue
                video_id = meta.get("video_id", "")
                title = meta.get("title", "")
                if not isinstance(title, str) or not isinstance(video_id, str):
                    continue
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
    projected_cost = 0.0
    has_inputs = has_corpus_synthesis_inputs(topic, config)
    if has_inputs:
        projected_cost = estimate_synthesis_workflow_cost(
            router_config=RouterConfig(),
        )
        enforce_projected_workflow_budget(config, "corpus", projected_cost)
    _require_model()
    tracker = budgeted_cost_tracker(config, "corpus")
    summary = RunSummary(command="corpus")
    summary.set_metadata(topic=topic, workflow="corpus", source_type="mixed")
    summary.estimated_cost = projected_cost if has_inputs else None

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
        from distill.commands._json import json_mode_active

        if not json_mode_active():
            show_banner(console)
        show_dashboard()
        return

    snapshot = dashboard_snapshot(config)
    version = _get_version()
    html = render_dashboard_html(version, snapshot)
    html_path = _output_path(config, "dashboard.html")
    atomic_write_text(html_path, html)
    console.print(f"[green]Dashboard written: {html_path}[/green]")
    if open_browser:
        webbrowser.open(html_path.resolve().as_uri())
        console.print("[dim]Opened in your default browser[/dim]")
    else:
        console.print("[dim]Use --open to launch it in your browser[/dim]")


def serve(
    port: int = typer.Option(8899, "--port", "-p", help="Port to serve on"),
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        help="Bind address. Default 127.0.0.1 is loopback-only; non-loopback binds expose the local corpus.",
    ),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open browser on start"),
):
    """Launch a local read-only web dashboard for browsing your library.

    Binds to loopback by default (127.0.0.1). The dashboard renders untrusted
    ingested content with sanitization and Host checks that accept only loopback
    Host headers. Prefer the default bind unless you intentionally operate a
    trusted local network and understand the exposure.
    """
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
