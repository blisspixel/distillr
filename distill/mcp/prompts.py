"""MCP prompts — prompt definitions for the Distill MCP server."""

from __future__ import annotations

from distill.mcp import server as _server

__all__: list[str] = []


@_server.mcp.prompt()
def daily_deals(channel: str) -> str:
    """Get today's deals from a watched channel.

    Catches up on new videos and shows the latest insights.
    """
    return (
        f"1. Call the catch_up tool for channel '{channel}' to scan for new videos.\n"
        f"2. Read the resource distill://topics/deals/channels/{channel}/insights/1 "
        f"to get the latest video insights.\n"
        f"3. Summarize the best deals with prices, vendors, and savings. "
        f"Format as a numbered list, sorted by best value.\n"
        f"4. If catch_up found new videos, also read insights/2 and insights/3 "
        f"to check for any additional deals from recent videos."
    )


@_server.mcp.prompt()
def morning_briefing() -> str:
    """Catch up on all watched channels and summarize what's new."""
    return (
        "1. Call the catch_up tool with no arguments to refresh all watched channels.\n"
        "2. Read distill://watch-alerts for the latest watch-level alerts if available.\n"
        "3. Read distill://topics to see what topics exist.\n"
        "4. For each topic that had new activity, read its synthesis "
        "(distill://topics/{topic}/synthesis).\n"
        "5. If available, also read distill://topics/{topic}/diff and "
        "distill://topics/{topic}/trends to capture what changed and whether momentum is rising or cooling.\n"
        "6. Create a concise morning briefing covering:\n"
        "   - What's new since last check\n"
        "   - Key developments or announcements\n"
        "   - Momentum or cooling signals\n"
        "   - Any actionable items or deals\n"
        "   Format with clear topic headers and bullet points."
    )


@_server.mcp.prompt()
def topic_gap_review(topic: str) -> str:
    """Review what a tracked topic is missing before triggering more work."""
    return (
        f"1. Call research_gaps for topic '{topic}'.\n"
        f"2. Summarize the main gaps in corpus coverage, missing artifacts, or stale recency.\n"
        f"3. Recommend the smallest next Distill action to close each gap, such as learn_topic, catch_up, resynthesize_topic, distill diff, distill trends, or generate_report.\n"
        f"4. If the corpus already looks healthy, say so explicitly and explain why additional ingestion is not yet necessary."
    )


@_server.mcp.prompt()
def topic_research(query: str) -> str:
    """Research a topic from YouTube content end-to-end."""
    return (
        f"1. Call search_videos with query '{query}' to preview the best videos.\n"
        f"2. Show the user the ranked results and ask if they want to proceed.\n"
        f"3. If yes, call learn_topic with query '{query}' to process the videos.\n"
        f"4. Read the topic synthesis to get the cross-video analysis.\n"
        f"5. Present a structured summary with:\n"
        f"   - Key findings and themes\n"
        f"   - Areas of consensus and disagreement\n"
        f"   - Actionable takeaways\n"
        f"   - Suggestions for deeper research if relevant"
    )
