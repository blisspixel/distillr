"""MCP tools — watch: catch_up, watch_add, watch_remove."""

from __future__ import annotations

import json

from distill.library.state import ChannelState
from distill.mcp import server as _server
from distill.pipeline.costs import BudgetExceededError, save_run_log

__all__: list[str] = []


@_server.mcp.tool()
@_server.write_tool("catch_up")
def catch_up(  # noqa: C901 — legacy, will refactor
    channel: str | None = None,
    topic: str | None = None,
    days: int | None = None,
) -> str:
    """Refresh watched channels; scan, transcribe, and analyze new videos.

    Args:
        channel: Single channel to refresh
        topic: Filter to this topic
        days: Override lookback window in days
    """
    from distill.cli_shared import ensure_channel_context, process_video
    from distill.ingestors.youtube.discovery import discover_videos
    from distill.pipeline.summary import ETATracker, RunSummary
    from distill.pipeline.synthesis.topic import synthesize_channel, synthesize_topic

    config = _server._config()
    if not config.xai_api_key:
        return "Error: XAI_API_KEY not configured. Run: python scripts/setup.py"

    lib = _server._lib(config)
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

    tracker = _server.capped_tracker()
    summary = RunSummary(command="catch-up")
    results = []
    topics_touched: set[str] = set()

    for entry in watchlist:
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
        processed = []
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
                custom_instructions=entry.instructions,
                eta=eta,
            )
            processed.append({"title": vid.title, "success": success})

        try:
            synthesize_channel(entry.topic, entry.name, config, tracker=tracker)
        except BudgetExceededError:
            raise  # the per-call spend cap is a hard stop; write_tool answers
        except Exception:
            pass
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
        except Exception:
            pass

    save_run_log(config.library_dir, summary.command, tracker)
    return json.dumps({"results": results, "cost": _server._cost_summary(tracker)}, indent=2)


@_server.mcp.tool()
@_server.write_tool("watch_add")
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
    from distill.ingestors.youtube.discovery import discover_videos, resolve_channel_name

    refusal = _server.refuse_if_host_not_allowed(url)
    if refusal is not None:
        return refusal
    config = _server._config()
    lib = _server._lib(config)
    name = resolve_channel_name(url)

    # Auto-generate instructions if none provided
    if not instructions and config.xai_api_key:
        try:
            vids = discover_videos(url, months=1, quiet=True)
            if vids:
                from distill.pipeline.analysis.video import generate_watch_instructions

                auto = generate_watch_instructions(name, [v.title for v in vids[:15]], config)
                if auto and auto.strip():
                    instructions = auto.strip()
        except Exception:
            pass

    if lib.add_to_watchlist(url, name, topic=topic, instructions=instructions, days=days):
        return json.dumps(
            {
                "status": "added",
                "name": name,
                "topic": topic,
                "days": days,
                # Show the resolved instructions (user-provided or auto-generated),
                # else "(none)". The prior `a or b if a else c` form left the middle
                # branch unreachable; this is the behavior its test already pinned.
                "instructions": instructions if instructions else "(none)",
            },
            indent=2,
        )
    return json.dumps({"status": "already_watching", "name": name})


@_server.mcp.tool()
@_server.write_tool("watch_remove")
def watch_remove(name: str) -> str:
    """Remove a channel from the watch list.

    Args:
        name: Channel name to remove
    """
    lib = _server._lib()
    if lib.remove_from_watchlist(name):
        return json.dumps({"status": "removed", "name": name})
    return json.dumps({"status": "not_found", "name": name})
