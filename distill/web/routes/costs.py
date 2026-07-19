"""Cost routes — spending history and rollups."""

from fastapi import APIRouter, Request

from distill.llm.telemetry import top_n_by_tokens
from distill.pipeline.cost_history import (
    cost_history_integrity_message,
    scan_confined_cost_log,
    select_cost_log_path,
)
from distill.pipeline.dashboard_data import (
    source_cost_rollups,
    sum_recent_cost,
    topic_cost_rollups,
)

router = APIRouter()


@router.get("/costs")
async def costs_page(request: Request):
    config = request.app.state.config
    templates = request.app.state.templates

    # Check new location first, fall back to old
    ops_log = config.library_dir / ".distill" / "cost_log.jsonl"
    legacy_log = config.library_dir / "cost_log.jsonl"
    cost_log = select_cost_log_path(config.library_dir) or ops_log
    cost_scan = scan_confined_cost_log(cost_log, config.library_dir)
    all_entries = list(cost_scan.rows)
    total_spend = sum_recent_cost(all_entries) if cost_scan.complete else None
    aggregate_available = total_spend is not None
    recent_entries = all_entries[-20:]
    topic_rollups = (
        topic_cost_rollups(all_entries, days=30, limit=10) if aggregate_available else []
    )
    source_rollups = source_cost_rollups(all_entries, days=30) if aggregate_available else []
    biggest_prompts = [
        {
            "timestamp": record.timestamp,
            "workload_tag": record.workload_tag,
            "call_type": record.call_type,
            "model": record.model,
            "provider": record.provider_name or record.provider_type,
            "total_tokens": record.input_tokens + record.output_tokens,
            "tokens_label": f"{record.input_tokens + record.output_tokens:,}",
            "elapsed_seconds": record.elapsed_seconds,
        }
        for record in top_n_by_tokens(str(config.library_dir / ".distill"), n=10)
    ]

    return templates.TemplateResponse(
        request,
        "costs.html",
        {
            "request": request,
            "entries": list(reversed(recent_entries)),
            "total_spend": total_spend,
            "cost_aggregate_available": aggregate_available,
            "cost_history": cost_scan.coverage(),
            "cost_history_message": (
                cost_history_integrity_message(cost_log, cost_scan)
                if not cost_scan.complete
                else (
                    "Valid cost values exceed the supported aggregate range. "
                    "Retained runs remain visible, but totals and rollups are unavailable."
                    if not aggregate_available
                    else ""
                )
            ),
            "topic_rollups": topic_rollups,
            "source_rollups": source_rollups,
            "biggest_prompts": biggest_prompts,
            "cost_log_path": str(ops_log),
            "legacy_cost_log_path": str(legacy_log),
            "telemetry_path": str(config.library_dir / ".distill" / "telemetry.jsonl"),
        },
    )
