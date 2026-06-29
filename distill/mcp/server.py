# pyright: strict
"""Distill MCP Server -- transport, registration, and lifecycle.

Run with:  distill-mcp          (stdio transport, for Claude Desktop / IDE integrations)

This module creates the FastMCP instance and wires all tools, resources,
and prompts from their respective submodules.  No business logic lives here.
"""

from __future__ import annotations

import functools
import inspect
import json
from collections.abc import Awaitable, Callable, Mapping
from importlib import import_module
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import ParamSpec, TypeVar, cast
from urllib.parse import urlparse

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from distill.config import DistillConfig
from distill.library import Library
from distill.pipeline.costs import BudgetExceededError, CostTracker
from distill.pipeline.gaps import (
    TopicInventory,
    VideoMetadata,
    topic_gap_summary,
)
from distill.pipeline.gaps import (
    topic_source_inventory as _pipeline_topic_source_inventory,
)
from distill.pipeline.gaps import (
    video_list as _pipeline_video_list,
)

__all__ = [
    "capped_tracker",
    "cost_summary",
    "library",
    "load_config",
    "main",
    "mcp",
    "read_markdown_resource",
    "refuse_if_host_not_allowed",
    "resolve_within_library",
    "strip_frontmatter",
    "topic_source_inventory",
    "video_list",
    "write_tool",
]

P = ParamSpec("P")
R = TypeVar("R", str, Awaitable[str])

mcp = FastMCP(
    "Distill",
    instructions=(
        "Source-to-intelligence platform for local Markdown corpora. "
        "Use list_topics first, then search or summarize topic-scoped evidence."
    ),
)


# ── Shared helpers (used by tools, resources, prompts) ───────────────


def _config() -> DistillConfig:
    load_dotenv()
    return DistillConfig()


def load_config() -> DistillConfig:
    """Load MCP server configuration with environment files applied."""
    return _config()


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


def capped_tracker() -> CostTracker:
    """A run tracker carrying the per-call MCP spend cap, when one is set.

    ``DISTILL_MCP_MAX_SPEND_PER_CALL`` caps each tool call's *recorded* spend:
    the call that crosses completes (its spend already happened and stays on
    the ledger), then the run raises ``BudgetExceededError``, which
    :func:`write_tool` turns into a structured response. Enforcement on actual
    spend, never on an estimate.
    """
    cap = _config().distill_mcp_max_spend_per_call
    return CostTracker(budget=cap if cap > 0 else None)


def _budget_response(action: str, exc: BudgetExceededError) -> str:
    return json.dumps(
        {
            "status": "budget_exceeded",
            "error": f"'{action}' stopped: {exc}. Artifacts written before the "
            "stop are durable and verify-gated; re-running converges (already-"
            "ingested sources are skipped). Raise DISTILL_MCP_MAX_SPEND_PER_CALL "
            "or run the action via the distill CLI.",
            "spent": round(exc.spent, 6),
            "cap": exc.budget,
        },
        indent=2,
    )


def _write_tool_read_only_refusal(
    action: str,
    *,
    allow_preview: bool,
    kwargs: Mapping[str, object],
) -> str | None:
    if allow_preview and kwargs.get("preview") is True:
        return None
    return _refuse_if_read_only(action)


def write_tool(
    action: str,
    *,
    allow_preview: bool = False,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator marking an MCP tool as write-side (spend, ingest, or mutation).

    Stacks *under* ``@mcp.tool()`` so the registered callable carries the
    read-only gate and the per-call spend cap (a ``BudgetExceededError`` from
    the tool's ``capped_tracker()`` becomes a structured response instead of a
    protocol error). Tools can opt into read-only preview calls when
    ``preview=True`` is structurally non-mutating. ``functools.wraps`` preserves
    the signature FastMCP introspects for the schema.
    """

    def deco(fn: Callable[P, R]) -> Callable[P, R]:
        if inspect.iscoroutinefunction(fn):
            async_fn = cast("Callable[P, Awaitable[str]]", fn)

            @functools.wraps(fn)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> str:
                refusal = _write_tool_read_only_refusal(
                    action,
                    allow_preview=allow_preview,
                    kwargs=cast("Mapping[str, object]", kwargs),
                )
                if refusal is not None:
                    return refusal
                try:
                    return await async_fn(*args, **kwargs)
                except BudgetExceededError as exc:
                    return _budget_response(action, exc)

            return cast("Callable[P, R]", async_wrapper)

        sync_fn = cast("Callable[P, str]", fn)

        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> str:
            refusal = _write_tool_read_only_refusal(
                action,
                allow_preview=allow_preview,
                kwargs=cast("Mapping[str, object]", kwargs),
            )
            if refusal is not None:
                return refusal
            try:
                return sync_fn(*args, **kwargs)
            except BudgetExceededError as exc:
                return _budget_response(action, exc)

        return cast("Callable[P, R]", wrapper)

    return deco


def refuse_if_host_not_allowed(url: str) -> str | None:
    """Gate for URL-taking ingest tools: the ingest-domain allowlist.

    With ``DISTILL_MCP_INGEST_ALLOWLIST`` set (comma-separated hostnames), a
    URL whose host is not one of the entries or a subdomain of one is refused
    -- the corpus-poisoning guard for deployments that expose write tools.
    Returns the refusal JSON, or ``None`` to proceed.
    """
    allowlist = [
        h.strip().lower() for h in _config().distill_mcp_ingest_allowlist.split(",") if h.strip()
    ]
    if not allowlist:
        return None

    host = (urlparse(url).hostname or "").lower()
    if host and any(host == entry or host.endswith("." + entry) for entry in allowlist):
        return None

    return json.dumps(
        {
            "status": "domain_not_allowed",
            "error": f"Host '{host or url}' is not on DISTILL_MCP_INGEST_ALLOWLIST; "
            "this server only ingests from: " + ", ".join(allowlist) + ". "
            "Ask the operator to extend the allowlist or ingest via the distill CLI.",
        },
        indent=2,
    )


def _lib(config: DistillConfig | None = None) -> Library:
    return Library(config or _config())


def library(config: DistillConfig | None = None) -> Library:
    """Return a Library bound to MCP configuration or the supplied config."""
    return _lib(config)


# Coverage/gap helpers were lifted to distill.pipeline.gaps so the discover
# command can share them without a commands -> mcp import. Re-exported here under
# their original private names for resources.py / tools/gaps.py.
_video_list = _pipeline_video_list


def video_list(config: DistillConfig, topic: str, channel_name: str) -> list[VideoMetadata]:
    """Return sorted video metadata for an MCP topic/channel resource."""
    return _video_list(config, topic, channel_name)


def _cost_summary(tracker: CostTracker) -> dict[str, int | float]:
    return {
        "total_cost": round(tracker.total_cost, 6),
        "total_input_tokens": tracker.total_input_tokens,
        "total_output_tokens": tracker.total_output_tokens,
        "calls": len(tracker.entries),
    }


def cost_summary(tracker: CostTracker) -> dict[str, int | float]:
    """Return the JSON-serializable cost summary for an MCP call."""
    return _cost_summary(tracker)


def _strip_frontmatter(content: str) -> str:
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return content


def strip_frontmatter(content: str) -> str:
    """Return markdown content with a leading YAML frontmatter block removed."""
    return _strip_frontmatter(content)


def resolve_within_library(library_dir: Path, path: str) -> Path | None:
    """Resolve a library-relative path only when it stays inside the root."""
    if not path:
        return None
    windows_path = PureWindowsPath(path)
    if (
        PurePosixPath(path).is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or windows_path.root
    ):
        return None
    if "\x00" in path:
        return None
    try:
        root = library_dir.resolve(strict=False)
        candidate = (root / path).resolve(strict=False)
    except (OSError, ValueError):
        return None
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _read_markdown_resource(path: Path, missing_message: str) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return missing_message


def read_markdown_resource(path: Path, missing_message: str) -> str:
    """Read a markdown resource or return the supplied missing-resource text."""
    return _read_markdown_resource(path, missing_message)


_topic_source_inventory = _pipeline_topic_source_inventory


def topic_source_inventory(config: DistillConfig, topic: str) -> TopicInventory:
    """Return source inventory data for an MCP topic resource."""
    return _topic_source_inventory(config, topic)


_topic_gap_summary = topic_gap_summary


# ── Wire tools, resources, and prompts from submodules ───────────────

_REGISTRATION_MODULES = (
    "distill.mcp.prompts",
    "distill.mcp.resources",
    "distill.mcp.tools.ask",
    "distill.mcp.tools.concepts",
    "distill.mcp.tools.costs",
    "distill.mcp.tools.discover",
    "distill.mcp.tools.doctor",
    "distill.mcp.tools.find",
    "distill.mcp.tools.gaps",
    "distill.mcp.tools.okf",
    "distill.mcp.tools.papers",
    "distill.mcp.tools.reports",
    "distill.mcp.tools.sites",
    "distill.mcp.tools.summaries",
    "distill.mcp.tools.synthesis",
    "distill.mcp.tools.topics",
    "distill.mcp.tools.watch",
)


def _register_mcp_modules() -> None:
    """Import modules whose decorators register tools, resources, and prompts."""
    for module_name in _REGISTRATION_MODULES:
        import_module(module_name)


_register_mcp_modules()


# ── Entry point ──────────────────────────────────────────────────────


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
