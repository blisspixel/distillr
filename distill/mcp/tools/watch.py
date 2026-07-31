# pyright: strict
"""MCP tools -- watch: catch_up, watch_add, watch_remove."""

from __future__ import annotations

import json
import logging

from distill.config import DistillConfig
from distill.library.state import ChannelState
from distill.llm.availability import model_available
from distill.mcp.server import (
    capped_tracker,
    cost_summary,
    host_not_on_ingest_allowlist,
    library,
    load_config,
    mcp,
    refuse_if_host_not_allowed,
    write_tool,
    write_tool_annotations,
)
from distill.pipeline.costs import BudgetExceededError

logger = logging.getLogger(__name__)

__all__: list[str] = []

type CatchUpRow = dict[str, object]
type ProcessedVideoRow = dict[str, str | bool]


def _suggest_watch_instructions(
    url: str,
    name: str,
    config: DistillConfig,
) -> tuple[str, str]:
    """Return an untrusted title-derived suggestion and any non-fatal warning."""

    from distill.ingestors.youtube.discovery import discover_videos
    from distill.pipeline.analysis.video import generate_watch_instructions

    try:
        videos = discover_videos(url, months=1, quiet=True)
        if not videos:
            return "", ""
        tracker = capped_tracker()
        suggestion = generate_watch_instructions(
            name,
            [video.title for video in videos[:15]],
            config,
            tracker=tracker,
        )
        return (suggestion.strip()[:2048] if suggestion and suggestion.strip() else "", "")
    except BudgetExceededError:
        raise
    except Exception as exc:
        logger.warning("watch_add auto-instructions skipped for %s: %s", name, exc)
        return "", f"Auto-instructions skipped: {exc}"


@mcp.tool(annotations=write_tool_annotations(destructive=False, idempotent=False, open_world=True))
@write_tool("catch_up", ledger_command="catch-up")
def catch_up(  # noqa: C901 - legacy, will refactor
    channel: str | None = None,
    topic: str | None = None,
    days: int | None = None,
) -> str:
    """Refresh watched channels; scan, transcribe, and analyze new videos.

    Stored watch URLs pass through DISTILL_MCP_INGEST_ALLOWLIST when that
    allowlist is set (same host gate as watch_add). Query-shaped discovery
    tools are out of this gate's scope.

    Args:
        channel: Single channel to refresh
        topic: Filter to this topic
        days: Override lookback window in days
    """
    from distill.cli_shared import ensure_channel_context, process_video
    from distill.ingestors.youtube.discovery import discover_videos
    from distill.pipeline.summary import ETATracker, RunSummary
    from distill.pipeline.synthesis.topic import synthesize_channel, synthesize_topic

    config = load_config()
    if not model_available():
        return "Error: No model configured (set a cloud key or DISTILL_PROVIDER=ollama)."

    lib = library(config)
    watchlist = lib.get_watchlist()
    if not watchlist:
        return "Watch list is empty. Use watch_add to start tracking channels."

    if channel:
        watchlist = [e for e in watchlist if e.name.lower() == channel.lower()]
        if not watchlist:
            return f"'{channel}' not on watch list."
    if topic:
        watchlist = [e for e in watchlist if e.topic.lower() == topic.lower()]
        if not watchlist:
            return f"No watched channels in topic '{topic}'."

    tracker = capped_tracker()
    summary = RunSummary(command="catch-up")
    results: list[CatchUpRow] = []
    topics_touched: set[str] = set()

    for entry in watchlist:
        # Per-item skip: do not mark the whole run refused (mixed lists).
        allowlist_error = host_not_on_ingest_allowlist(entry.url)
        if allowlist_error is not None:
            results.append(
                {
                    "channel": entry.name,
                    "status": "domain_not_allowed",
                    "error": allowlist_error,
                }
            )
            continue
        ch_days = days if days is not None else entry.days
        try:
            videos = discover_videos(entry.url, days=ch_days, include_shorts=True, quiet=True)
        except Exception as exc:
            results.append({"channel": entry.name, "status": "error", "error": str(exc)})
            continue

        state = ChannelState(config.channel_dir(entry.topic, entry.name) / "state.json")
        new_vids = [v for v in videos if not state.is_processed(v.video_id)]

        if not new_vids:
            results.append(
                {
                    "channel": entry.name,
                    "status": "up_to_date",
                    "checked": len(videos),
                    "days": ch_days,
                }
            )
            continue

        # Process new videos
        ensure_channel_context(entry.topic, entry.name, new_vids, config, tracker)
        eta = ETATracker(total=len(new_vids))
        processed: list[ProcessedVideoRow] = []
        for vid in new_vids:
            success = process_video(
                entry.topic,
                entry.name,
                vid,
                config,
                tracker,
                summary,
                state=state,
                analysis_mode="scan",
                custom_instructions=entry.active_instructions,
                eta=eta,
            )
            processed.append({"title": vid.title, "success": success})

        try:
            synthesize_channel(entry.topic, entry.name, config, tracker=tracker)
        except BudgetExceededError:
            raise  # the per-call spend cap is a hard stop; write_tool answers
        except Exception as exc:
            # Don't fail the whole catch-up over one channel's synthesis, but the
            # failure must be observable, not silently swallowed.
            logger.warning("catch_up channel synthesis failed for %s: %s", entry.name, exc)
        topics_touched.add(entry.topic)

        results.append(
            {
                "channel": entry.name,
                "status": "processed",
                "new_videos": len(new_vids),
                "videos": processed,
            }
        )

    for t in topics_touched:
        try:
            synthesize_topic(t, config, tracker=tracker)
        except BudgetExceededError:
            raise
        except Exception as exc:
            logger.warning("catch_up topic synthesis failed for %s: %s", t, exc)

    return json.dumps({"results": results, "cost": cost_summary(tracker)}, indent=2)


@mcp.tool(annotations=write_tool_annotations(destructive=False, idempotent=True, open_world=True))
@write_tool("watch_add", ledger_command="watch-add")
def watch_add(
    url: str,
    topic: str = "watch",
    days: int = 14,
    instructions: str = "",
) -> str:
    """Add a YouTube channel to the watch list.

    Args:
        url: YouTube channel URL
        topic: Topic to file under
        days: Lookback window for catch-up
        instructions: Custom analysis instructions
    """
    from distill.ingestors.youtube.discovery import resolve_channel_name
    from distill.youtube_urls import normalize_youtube_channel_url

    normalized_url = normalize_youtube_channel_url(url)
    if not normalized_url:
        return json.dumps(
            {
                "status": "invalid_url",
                "error": "Expected a public HTTPS YouTube channel URL without credentials, query, or fragment.",
            },
            indent=2,
        )
    url = normalized_url
    refusal = refuse_if_host_not_allowed(url)
    if refusal is not None:
        return refusal
    config = load_config()
    lib = library(config)
    existing = next((entry for entry in lib.get_watchlist() if entry.url == url), None)
    if existing is not None:
        return json.dumps({"status": "already_watching", "name": existing.name})
    name = resolve_channel_name(url)
    # Public-title-derived text is returned only as a suggestion. A later
    # operator-authored watch update is required before it can steer analysis.
    suggested_instructions, instruction_warning = (
        _suggest_watch_instructions(url, name, config)
        if not instructions and model_available()
        else ("", "")
    )

    if lib.add_to_watchlist(url, name, topic=topic, instructions=instructions, days=days):
        response: dict[str, str | int] = {
            "status": "added",
            "name": name,
            "topic": topic,
            "days": days,
            "instructions": instructions if instructions else "(none)",
        }
        if suggested_instructions:
            response["suggested_instructions"] = suggested_instructions
        if instruction_warning:
            response["warning"] = instruction_warning
        return json.dumps(response, indent=2)
    return json.dumps({"status": "already_watching", "name": name})


@mcp.tool(annotations=write_tool_annotations(destructive=True, idempotent=True, open_world=False))
@write_tool("watch_remove")
def watch_remove(name: str) -> str:
    """Remove a channel from the watch list.

    Args:
        name: Channel name to remove
    """
    lib = library()
    if lib.remove_from_watchlist(name):
        return json.dumps({"status": "removed", "name": name})
    return json.dumps({"status": "not_found", "name": name})
