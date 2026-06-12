"""Tests for the MCP read-only posture (DISTILL_MCP_READ_ONLY).

The June 2026 panel's enterprise finding: spend-and-ingest tools callable by
any connected agent are budget-burn and corpus-poisoning surface. Read-only
mode keeps the full read surface and refuses every write-side tool before its
body executes -- no keys, no network, no spend.
"""

from __future__ import annotations

import asyncio
import inspect
import json

import pytest


def _invoke(fn, *args, **kwargs):
    result = fn(*args, **kwargs)
    if inspect.iscoroutine(result):
        return asyncio.run(result)
    return result


# (module, tool name, minimal args) -- every write-side tool on the server.
WRITE_TOOLS = [
    ("distill.mcp.tools.ask", "ask", ("t", "q")),
    ("distill.mcp.tools.discover", "learn_topic", ("q",)),
    ("distill.mcp.tools.discover", "discover", ("goal",)),
    ("distill.mcp.tools.papers", "papers", ("t", "q")),
    ("distill.mcp.tools.sites", "site_batch", ("seeds.json",)),
    ("distill.mcp.tools.synthesis", "synthesize", ()),
    ("distill.mcp.tools.topics", "process_video_url", ("https://youtube.com/watch?v=x",)),
    ("distill.mcp.tools.reports", "generate_report", ("t",)),
    ("distill.mcp.tools.reports", "resynthesize_topic", ("t",)),
    ("distill.mcp.tools.watch", "catch_up", ()),
    ("distill.mcp.tools.watch", "watch_add", ("https://youtube.com/@chan",)),
    ("distill.mcp.tools.watch", "watch_remove", ("chan",)),
]


@pytest.mark.parametrize("module_name,tool_name,args", WRITE_TOOLS)
def test_write_tools_refuse_in_read_only(monkeypatch, module_name, tool_name, args):
    import importlib

    monkeypatch.setenv("DISTILL_MCP_READ_ONLY", "1")
    module = importlib.import_module(module_name)
    tool = getattr(module, tool_name)

    result = json.loads(_invoke(tool, *args))

    assert result["status"] == "read_only"
    assert tool_name in result["error"]
    assert "distill CLI" in result["error"]


def test_read_surface_stays_available_in_read_only(monkeypatch, tmp_path):
    """find_insights still answers (the whole point of the posture)."""
    from distill import _cli_impl  # noqa: F401 -- ensures config machinery imports
    from distill.config import DistillConfig
    from distill.mcp import server as _server
    from distill.mcp.tools.find import find_insights

    monkeypatch.setenv("DISTILL_MCP_READ_ONLY", "1")
    config = DistillConfig(xai_api_key="t", distill_output_dir=tmp_path / "library")
    monkeypatch.setattr(_server, "_config", lambda: config)
    d = config.topic_dir("t") / "papers" / "p1"
    d.mkdir(parents=True)
    (d / "p1_Insights.md").write_text("---\n---\n\nfindable text body", encoding="utf-8")

    result = json.loads(find_insights("t", "findable"))

    assert "results" in result
    assert result["count"] >= 1


def test_write_tools_proceed_when_not_read_only(monkeypatch):
    """Gate off: the wrapper falls through to the body (which then errors on
    its own preconditions, proving execution went past the gate)."""
    from pathlib import Path

    monkeypatch.delenv("DISTILL_MCP_READ_ONLY", raising=False)
    from distill.config import DistillConfig
    from distill.mcp import server as _server
    from distill.mcp.tools.ask import ask

    config = DistillConfig(xai_api_key="", distill_output_dir=Path("nonexistent-lib"))
    monkeypatch.setattr(_server, "_config", lambda: config)

    result = json.loads(ask("t", "q"))
    assert result.get("status") != "read_only"  # reached the body's own checks
