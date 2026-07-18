"""Cost routes — spending history and rollups."""

from fastapi import APIRouter, Request

from distill.llm.telemetry import top_n_by_tokens
from distill.pipeline.dashboard_data import (
    load_all_cost_runs,
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
    cost_log = ops_log if ops_log.exists() else legacy_log
    all_entries = load_all_cost_runs(cost_log)
    total_spend = sum_recent_cost(all_entries)
    recent_entries = all_entries[-20:]
    topic_rollups = topic_cost_rollups(all_entries, days=30, limit=10)
    source_rollups = source_cost_rollups(all_entries, days=30)
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
            "topic_rollups": topic_rollups,
            "source_rollups": source_rollups,
            "biggest_prompts": biggest_prompts,
            "cost_log_path": str(ops_log),
            "legacy_cost_log_path": str(legacy_log),
            "telemetry_path": str(config.library_dir / ".distill" / "telemetry.jsonl"),
        },
    )
