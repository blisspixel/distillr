"""Distill MCP Server -- transport, registration, and lifecycle.

Run with:  distill-mcp          (stdio transport, for Claude Desktop / IDE integrations)

This module creates the FastMCP instance and wires all tools, resources,
and prompts from their respective submodules.  No business logic lives here.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from distill.config import DistillConfig
from distill.library import Library
from distill.pipeline.costs import CostTracker
from distill.pipeline.gaps import topic_gap_summary, topic_source_inventory, video_list

__all__ = ["main", "mcp"]

mcp = FastMCP(
    "Distill",
    instructions=(
        "YouTube channels to strategic intelligence. "
        "Discover, transcribe, analyze, and synthesize YouTube content."
    ),
)


# ── Shared helpers (used by tools, resources, prompts) ───────────────


def _config() -> DistillConfig:
    load_dotenv()
    return DistillConfig()


def _refuse_if_read_only(action: str) -> str | None:
    """Gate for write-side tools: spend, ingest, or corpus mutation.

    With ``DISTILL_MCP_READ_ONLY`` set, any connected agent gets the full read
    surface but cannot burn budget or poison the corpus by tool call -- the
    recommended posture for agent-facing deployments (ingest happens via the
    CLI by a named operator). Returns the refusal JSON, or ``None`` to
    proceed.
    """
    if not _config().distill_mcp_read_only:
        return None
    import json

    return json.dumps(
        {
            "status": "read_only",
            "error": f"This MCP server is read-only (DISTILL_MCP_READ_ONLY); "
            f"'{action}' spends money or mutates the corpus and is disabled. "
            "Use the read tools (find_insights, read_insight, find_concepts, "
            "research_gaps, ...) or run the action via the distill CLI.",
        },
        indent=2,
    )


def write_tool(action: str):
    """Decorator marking an MCP tool as write-side (spend, ingest, or mutation).

    Stacks *under* ``@mcp.tool()`` so the registered callable carries the
    read-only gate. ``functools.wraps`` preserves the signature FastMCP
    introspects for the schema.
    """
    import functools
    import inspect

    def deco(fn):
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                refusal = _refuse_if_read_only(action)
                if refusal is not None:
                    return refusal
                return await fn(*args, **kwargs)

            return async_wrapper

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            refusal = _refuse_if_read_only(action)
            if refusal is not None:
                return refusal
            return fn(*args, **kwargs)

        return wrapper

    return deco


def _lib(config: DistillConfig | None = None) -> Library:
    return Library(config or _config())


# Coverage/gap helpers were lifted to distill.pipeline.gaps so the discover
# command can share them without a commands -> mcp import. Re-exported here under
# their original private names for resources.py / tools/gaps.py.
_video_list = video_list


def _cost_summary(tracker: CostTracker) -> dict:
    return {
        "total_cost": round(tracker.total_cost, 6),
        "total_input_tokens": tracker.total_input_tokens,
        "total_output_tokens": tracker.total_output_tokens,
        "calls": len(tracker.entries),
    }


def _strip_frontmatter(content: str) -> str:
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return content


def _read_markdown_resource(path: Path, missing_message: str) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return missing_message


_topic_source_inventory = topic_source_inventory


_topic_gap_summary = topic_gap_summary


# ── Wire tools, resources, and prompts from submodules ───────────────

# Import submodules so their @mcp decorators register on the shared instance.
# The submodules import ``mcp`` from this module and decorate their handlers.
import distill.mcp.prompts as _prompts  # noqa: E402, F401, I001
import distill.mcp.resources as _resources  # noqa: E402, F401
import distill.mcp.tools.ask as _tools_ask  # noqa: E402, F401
import distill.mcp.tools.concepts as _tools_concepts  # noqa: E402, F401
import distill.mcp.tools.costs as _tools_costs  # noqa: E402, F401
import distill.mcp.tools.discover as _tools_discover  # noqa: E402, F401
import distill.mcp.tools.doctor as _tools_doctor  # noqa: E402, F401
import distill.mcp.tools.find as _tools_find  # noqa: E402, F401
import distill.mcp.tools.gaps as _tools_gaps  # noqa: E402, F401
import distill.mcp.tools.papers as _tools_papers  # noqa: E402, F401
import distill.mcp.tools.reports as _tools_reports  # noqa: E402, F401
import distill.mcp.tools.sites as _tools_sites  # noqa: E402, F401
import distill.mcp.tools.synthesis as _tools_synthesis  # noqa: E402, F401
import distill.mcp.tools.topics as _tools_topics  # noqa: E402, F401
import distill.mcp.tools.watch as _tools_watch  # noqa: E402, F401


# ── Entry point ──────────────────────────────────────────────────────


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
