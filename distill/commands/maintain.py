"""Maintenance command group, extracted from the ``_logic`` monolith.

Holds the lighter "Maintain" panel utilities (cost history, store cleanup).
Registered via :func:`register` from ``distill.cli`` (mirroring view / update /
init). Larger Maintain commands (doctor, migrate) move in their own slices.
Pure relocation: no behavior change.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich import box
from rich.table import Table

from distill._console import console
from distill.commands._helpers import get_config
from distill.config import DistillConfig

__all__ = ["cleanup", "costs", "register"]


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


def register(app: typer.Typer) -> None:
    """Attach the maintenance commands to the app (called from distill.cli)."""
    app.command(rich_help_panel="Maintain")(costs)
    app.command(rich_help_panel="Maintain")(cleanup)
