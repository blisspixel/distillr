"""Watchlist routes — channel and topic watches."""

from fastapi import APIRouter, Request

from distill.dashboard_data import (
    collect_stale_topic_watches,
    estimate_topic_watch_cost,
)
from distill.library import Library

router = APIRouter()


@router.get("/watchlist")
async def watchlist_page(request: Request):
    config = request.app.state.config
    templates = request.app.state.templates
    lib = Library(config)

    channel_watches = lib.get_watchlist()
    topic_watches = lib.get_topic_watchlist()
    stale = collect_stale_topic_watches(topic_watches)

    # Enrich topic watches with projected cost
    enriched_topic_watches = []
    for entry in topic_watches:
        enriched_topic_watches.append(
            {
                "entry": entry,
                "projected_cost": estimate_topic_watch_cost(entry),
            }
        )

    return templates.TemplateResponse(
        "watchlist.html",
        {
            "request": request,
            "channel_watches": channel_watches,
            "topic_watches": enriched_topic_watches,
            "stale": stale,
        },
    )
