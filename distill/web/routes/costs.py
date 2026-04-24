"""Cost routes — spending history and rollups."""

from fastapi import APIRouter, Request

from distill.dashboard_data import (
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

    all_entries = load_all_cost_runs(config.library_dir / "cost_log.jsonl")
    total_spend = sum_recent_cost(all_entries)
    recent_entries = all_entries[-20:]
    topic_rollups = topic_cost_rollups(all_entries, days=30, limit=10)
    source_rollups = source_cost_rollups(all_entries, days=30)

    return templates.TemplateResponse(
        request,
        "costs.html",
        {
            "request": request,
            "entries": list(reversed(recent_entries)),
            "total_spend": total_spend,
            "topic_rollups": topic_rollups,
            "source_rollups": source_rollups,
        },
    )
