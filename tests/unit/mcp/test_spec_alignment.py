# pyright: strict
"""MCP spec-alignment guards: annotations, ordering, identity, doc sync.

These tests hold the MCP surface to the behavior contracts the 2026-07-28
protocol work depends on: every tool carries complete behavior hints that
match the ``write_tool`` refusal boundary, ``tools/list`` order stays
deterministic for client-side caching, the server identifies itself with the
installed distillr version, and the documented tool count cannot drift from
the runtime registry.
"""

from __future__ import annotations

import asyncio
import re
from importlib.metadata import version
from pathlib import Path

from mcp.types import Tool

from distill.mcp.server import READ_TOOL_ANNOTATIONS, mcp, write_tool_names

_DOCS_MCP = Path(__file__).resolve().parents[3] / "docs" / "mcp.md"

#: The server sorts listings by name, so ``tools/list`` is deterministic
#: across runs and import orders (the 2026-07-28 spec asks for deterministic
#: listings so clients can cache them). Registration order is not stable:
#: importing a tool module before ``distill.mcp.server`` shifts it to the
#: end of the registry via the circular import. A new tool must update this
#: list deliberately.
_EXPECTED_TOOL_ORDER = [
    "ask",
    "catch_up",
    "concept_diff",
    "concept_history",
    "costs",
    "discover",
    "doctor",
    "find_concepts",
    "find_insights",
    "find_insights_summary",
    "generate_report",
    "learn_topic",
    "list_topic_summary",
    "list_topics",
    "okf_export",
    "okf_validate",
    "papers",
    "process_video_url",
    "read_concept",
    "read_insight",
    "research_gaps",
    "resynthesize_topic",
    "search_videos",
    "site_batch",
    "synthesize",
    "watch_add",
    "watch_remove",
]

#: Write tools that fetch public web sources as part of their job.
_OPEN_WORLD_TOOLS = frozenset(
    {
        "learn_topic",
        "search_videos",
        "discover",
        "papers",
        "generate_report",
        "site_batch",
        "process_video_url",
        "catch_up",
        "watch_add",
    }
)

#: Write tools whose purpose includes replacing or removing existing
#: artifacts or state: synthesis regeneration, in-place report regeneration,
#: OKF bundle replacement (the previous bundle backup is rotated away), and
#: watch-entry removal. Additive convergent ingestion is not flagged.
_DESTRUCTIVE_TOOLS = frozenset(
    {
        "synthesize",
        "resynthesize_topic",
        "watch_remove",
        "generate_report",
        "okf_export",
    }
)


def _tools() -> list[Tool]:
    return asyncio.run(mcp.list_tools())


def test_every_tool_has_complete_annotations() -> None:
    """All four behavior hints are set explicitly on every tool."""
    for tool in _tools():
        annotations = tool.annotations
        assert annotations is not None, tool.name
        assert annotations.read_only_hint is not None, tool.name
        assert annotations.destructive_hint is not None, tool.name
        assert annotations.idempotent_hint is not None, tool.name
        assert annotations.open_world_hint is not None, tool.name


def test_read_only_hint_matches_write_tool_registry() -> None:
    """Client-visible hints match the DISTILL_MCP_READ_ONLY refusal boundary."""
    registered_write_tools = write_tool_names()
    for tool in _tools():
        annotations = tool.annotations
        assert annotations is not None, tool.name
        is_write_tool = tool.name in registered_write_tools
        assert annotations.read_only_hint is (not is_write_tool), tool.name


def test_read_tools_share_the_read_annotation_profile() -> None:
    """Pure corpus reads are non-destructive, idempotent, closed-world."""
    registered_write_tools = write_tool_names()
    for tool in _tools():
        if tool.name in registered_write_tools:
            continue
        assert tool.annotations == READ_TOOL_ANNOTATIONS, tool.name


def test_write_tool_hints_follow_the_documented_policy() -> None:
    """Open-world and destructive hints match each tool's actual behavior."""
    registered_write_tools = write_tool_names()
    for tool in _tools():
        if tool.name not in registered_write_tools:
            continue
        annotations = tool.annotations
        assert annotations is not None, tool.name
        assert annotations.open_world_hint is (tool.name in _OPEN_WORLD_TOOLS), tool.name
        assert annotations.destructive_hint is (tool.name in _DESTRUCTIVE_TOOLS), tool.name


def test_tool_listing_order_is_deterministic() -> None:
    """tools/list order is frozen; a change here must be a reviewed decision."""
    assert [tool.name for tool in _tools()] == _EXPECTED_TOOL_ORDER


def test_write_tool_registry_matches_runtime_surface() -> None:
    """15 of the 27 live tools are write-side per the registry.

    Membership is checked per live tool because the registry records every
    ``write_tool``-decorated function, and other test modules legitimately
    decorate throwaway probes that never register as MCP tools.
    """
    tools = _tools()
    registered_write_tools = write_tool_names()
    write_tools = [tool.name for tool in tools if tool.name in registered_write_tools]
    assert len(write_tools) == 15
    assert len(tools) == 27


def test_server_reports_distillr_version() -> None:
    """The server identifies itself with the installed distillr version."""
    assert mcp.name == "Distill"
    assert mcp.version == version("distillr")


def test_docs_tool_count_matches_runtime() -> None:
    """The '<n> tools' claim in docs/mcp.md tracks the runtime registry."""
    text = _DOCS_MCP.read_text(encoding="utf-8")
    match = re.search(r"^(\d+) tools, grouped by role", text, flags=re.MULTILINE)
    assert match is not None, "docs/mcp.md no longer states the tool count"
    assert int(match.group(1)) == len(_tools())
