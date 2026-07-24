# pyright: strict
"""Cost-report console sections for the ``costs`` maintenance command.

Extracted from ``distill.commands.maintain`` to keep that module under the
module-size cap. Holds the "Biggest Prompts" and "Inference Split" (local vs
cloud) renderers, which ``maintain.costs`` calls and re-exports.
"""

from __future__ import annotations

from rich import box
from rich.table import Table

from distill._console import console
from distill.commands._cost_data import (
    biggest_prompt_rows as _biggest_prompt_rows,
)
from distill.commands._cost_data import (
    compute_local_cloud_stats as _compute_local_cloud_stats,
)
from distill.commands._cost_data import (
    safe_float as _safe_float,
)
from distill.commands._cost_data import (
    safe_int as _safe_int,
)
from distill.config import DistillConfig


def costs_biggest_prompts_section(
    config: DistillConfig,
    biggest_prompts: list[dict[str, object]] | None = None,
) -> None:
    """Display the largest per-call prompt telemetry records."""
    rows = biggest_prompts if biggest_prompts is not None else _biggest_prompt_rows(config)
    if not rows:
        return

    console.print()
    table = Table(title="Biggest Prompts", box=box.SIMPLE, show_header=True)
    table.add_column("Date", style="dim")
    table.add_column("Workload")
    table.add_column("Call Type", style="dim")
    table.add_column("Model")
    table.add_column("Provider", style="dim")
    table.add_column("Tokens", justify="right")
    table.add_column("Time", justify="right")
    table.add_column("Outcome", style="dim")

    for row in rows[:10]:
        timestamp = str(row.get("timestamp") or "")[:16].replace("T", " ")
        provider = str(row.get("provider_name") or row.get("provider_type") or "-")
        elapsed_float = _safe_float(row.get("elapsed_seconds", 0))
        total_tokens_int = _safe_int(row.get("total_tokens", 0))
        table.add_row(
            timestamp or "-",
            str(row.get("workload_tag") or "-"),
            str(row.get("call_type") or "-"),
            str(row.get("model") or "-"),
            provider,
            f"{total_tokens_int:,}",
            f"{elapsed_float:.1f}s",
            str(row.get("outcome") or "-"),
        )

    console.print(table)


def costs_local_cloud_section(config: DistillConfig) -> None:
    """Display local vs cloud inference split from telemetry.jsonl."""
    telemetry_path = config.library_dir / ".distill" / "telemetry.jsonl"
    if not telemetry_path.exists():
        return

    stats = _compute_local_cloud_stats(config)
    local_records_count = _safe_int(stats.get("local_records_count", 0))
    cloud_records_count = _safe_int(stats.get("cloud_records_count", 0))
    malformed_records_count = _safe_int(stats.get("malformed_records_count", 0))
    read_error = bool(stats.get("telemetry_read_error", 0))
    if not any((local_records_count, cloud_records_count, malformed_records_count, read_error)):
        return

    console.print()
    console.print("[bold]Inference Split[/bold]")

    if read_error:
        console.print(
            f"  [yellow]Provider telemetry could not be read: {telemetry_path}[/yellow]",
            soft_wrap=True,
        )
    if malformed_records_count:
        suffix = "row" if malformed_records_count == 1 else "rows"
        console.print(
            f"  [yellow]Skipped {malformed_records_count:,} malformed provider telemetry "
            f"{suffix}: {telemetry_path}[/yellow]",
            soft_wrap=True,
        )

    if cloud_records_count > 0:
        console.print(f"  Cloud calls:       {cloud_records_count:,}")

    if local_records_count > 0:
        local_total_seconds = _safe_float(stats.get("local_total_seconds", 0))
        local_total_tokens = _safe_int(stats.get("local_total_tokens", 0))
        avg_tps = _safe_float(stats.get("avg_tokens_per_second", 0))
        console.print(f"  Local calls:       {local_records_count:,}")
        console.print(f"  Local time:        {local_total_seconds:.1f}s")
        console.print(f"  Local tokens:      {local_total_tokens:,}")
        if avg_tps > 0:
            console.print(f"  Avg tokens/sec:    {avg_tps:.1f}")
