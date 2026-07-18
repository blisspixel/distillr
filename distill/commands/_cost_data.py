# pyright: strict
"""Pure telemetry parsing helpers for maintenance cost views."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, cast

from distill.config import DistillConfig
from distill.pipeline.performance_history import PerformanceEvidence, load_performance_evidence


def dict_or_empty(value: object) -> dict[str, Any]:
    """Return a dict for runtime log fields, or empty for malformed rows."""
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def safe_float(value: object, default: float = 0.0) -> float:
    if not isinstance(value, str | int | float):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def safe_int(value: object, default: int = 0) -> int:
    if not isinstance(value, str | int | float):
        return default
    try:
        return int(value)
    except (OverflowError, TypeError, ValueError):
        return default


def biggest_prompt_rows(config: DistillConfig, limit: int = 10) -> list[dict[str, object]]:
    """Return largest per-call prompt telemetry records for cost surfaces."""
    from distill.llm.telemetry import top_n_by_tokens

    ops_dir = str(config.library_dir / ".distill")
    rows: list[dict[str, object]] = []
    for record in top_n_by_tokens(ops_dir, n=limit):
        rows.append(
            {
                "timestamp": record.timestamp,
                "workload_tag": record.workload_tag,
                "call_type": record.call_type,
                "model": record.model,
                "provider_name": record.provider_name,
                "provider_type": record.provider_type,
                "input_tokens": record.input_tokens,
                "output_tokens": record.output_tokens,
                "total_tokens": record.input_tokens + record.output_tokens,
                "elapsed_seconds": record.elapsed_seconds,
                "outcome": record.outcome,
                "run_id": record.run_id,
            }
        )
    return rows


def performance_evidence(
    config: DistillConfig,
    *,
    cost_log_path: Path | None = None,
    limit: int = 10,
) -> PerformanceEvidence:
    """Return exact-ID command, provider, and cost correlation evidence."""
    return load_performance_evidence(
        config.library_dir / ".distill",
        cost_log_path=cost_log_path,
        limit=limit,
    )


def compute_local_cloud_stats(config: DistillConfig) -> dict[str, float | int]:
    """Compute local/cloud inference stats from telemetry.jsonl for JSON output."""
    telemetry_path = config.library_dir / ".distill" / "telemetry.jsonl"
    if not telemetry_path.exists():
        return {}

    from distill.llm.telemetry import scan_telemetry

    scan = scan_telemetry(telemetry_path.parent, n=0)
    avg_tps = (
        round(scan.total_tokens_per_second / scan.local_records_count, 1)
        if scan.local_records_count
        else 0
    )
    return {
        "local_total_seconds": round(scan.local_total_seconds, 1),
        "local_total_tokens": scan.local_total_tokens,
        "avg_tokens_per_second": avg_tps,
        "local_records_count": scan.local_records_count,
        "cloud_records_count": scan.cloud_records_count,
        "malformed_records_count": scan.malformed_rows,
        "telemetry_read_error": int(scan.unreadable),
    }
