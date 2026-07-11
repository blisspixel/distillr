# pyright: strict
"""Pure telemetry parsing helpers for maintenance cost views."""

from __future__ import annotations

import json
import math
from typing import Any, cast

from distill.config import DistillConfig


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


def compute_local_cloud_stats(config: DistillConfig) -> dict[str, float | int]:
    """Compute local/cloud inference stats from telemetry.jsonl for JSON output."""
    telemetry_path = config.library_dir / ".distill" / "telemetry.jsonl"
    if not telemetry_path.exists():
        return {}

    local_total_seconds = 0.0
    local_total_tokens = 0
    local_records_count = 0
    total_tps_sum = 0.0

    try:
        lines = telemetry_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = dict_or_empty(json.loads(line))
            if not data or data.get("provider_type") != "local":
                continue
            local_records_count += 1
            local_total_seconds += float(data.get("elapsed_seconds", 0))
            local_total_tokens += int(data.get("output_tokens", 0)) + int(
                data.get("input_tokens", 0)
            )
            tokens_per_second = float(data.get("tokens_per_second", 0))
            if tokens_per_second > 0:
                total_tps_sum += tokens_per_second
        except (ValueError, TypeError, json.JSONDecodeError):
            continue

    avg_tps = round(total_tps_sum / local_records_count, 1) if local_records_count else 0
    return {
        "local_total_seconds": round(local_total_seconds, 1),
        "local_total_tokens": local_total_tokens,
        "avg_tokens_per_second": avg_tps,
    }
