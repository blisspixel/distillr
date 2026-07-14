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
import logging
import math
import string
from collections.abc import Awaitable, Callable, Generator, Mapping, Sequence
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, ParamSpec, TypeVar, cast
from urllib.parse import urlparse

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.types import ContentBlock

from distill.config import DistillConfig
from distill.library import Library
from distill.llm.run_context import mark_current_run_outcome, run_scope, update_current_run
from distill.pipeline.costs import BudgetExceededError, CostTracker, save_run_log
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
    "set_tracker_estimated_cost",
    "strip_frontmatter",
    "topic_source_inventory",
    "video_list",
    "write_tool",
]

P = ParamSpec("P")
R = TypeVar("R", str, Awaitable[str])
_SAFE_TOOL_NAME_CHARS = frozenset(string.ascii_letters + string.digits + "_.-")
_ACCOUNTING_FAILURE_NOTE = "MCP cost-ledger persistence failed; inspect local logs."
logger = logging.getLogger(__name__)


@dataclass
class _ToolCostState:
    command: str
    tracker: CostTracker | None = None
    library_dir: Path | None = None
    estimated_cost: float | None = None


_current_tool_cost_state: ContextVar[_ToolCostState | None] = ContextVar(
    "distill_mcp_tool_cost_state",
    default=None,
)


def _telemetry_tool_name(name: str) -> str:
    """Keep unvalidated protocol input out of local operational records."""
    if 1 <= len(name) <= 128 and all(char in _SAFE_TOOL_NAME_CHARS for char in name):
        return name
    return "unknown-tool"


class DistillFastMCP(FastMCP):
    """FastMCP server that correlates every tool call with local telemetry."""

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> Sequence[ContentBlock] | dict[str, Any]:
        with run_scope(
            invocation_type="mcp",
            command=_telemetry_tool_name(name),
        ):
            with suppress(Exception):
                update_current_run(ops_dir=_config().library_dir / ".distill")
            return await super().call_tool(name, arguments)


mcp = DistillFastMCP(
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
    config = _config()
    cap = config.distill_mcp_max_spend_per_call
    tracker = CostTracker(budget=cap if cap > 0 else None)
    state = _current_tool_cost_state.get()
    if state is not None:
        if state.tracker is not None:
            raise RuntimeError("an MCP tool call may own only one cost tracker")
        state.tracker = tracker
        state.library_dir = config.library_dir
    return tracker


def set_tracker_estimated_cost(tracker: CostTracker, estimated_cost: float) -> None:
    """Attach a finite workflow estimate to the current MCP ledger row."""
    state = _current_tool_cost_state.get()
    if state is None or state.tracker is not tracker:
        raise RuntimeError("tracker does not belong to the current MCP tool call")
    if not math.isfinite(estimated_cost) or estimated_cost < 0:
        raise ValueError("estimated cost must be finite and non-negative")
    state.estimated_cost = estimated_cost


def _persist_tool_cost(state: _ToolCostState) -> None:
    if state.tracker is None:
        return
    if state.library_dir is None:
        raise RuntimeError("tracked MCP tool has no ledger directory")
    save_run_log(
        state.library_dir,
        state.command,
        state.tracker,
        estimated_cost=state.estimated_cost,
    )


@contextmanager
def _tool_cost_scope(command: str) -> Generator[None]:
    """Persist one registered tracker before any tool result crosses MCP."""
    state = _ToolCostState(command=command)
    token = _current_tool_cost_state.set(state)
    active_error: BaseException | None = None
    try:
        yield
    except BaseException as exc:
        active_error = exc
        raise
    finally:
        try:
            _persist_tool_cost(state)
        except Exception:
            if active_error is None:
                raise
            active_error.add_note(_ACCOUNTING_FAILURE_NOTE)
            logger.exception(_ACCOUNTING_FAILURE_NOTE)
        finally:
            _current_tool_cost_state.reset(token)


def _budget_response(action: str, exc: BudgetExceededError) -> str:
    payload: dict[str, object] = {
        "status": "budget_exceeded",
        "error": f"'{action}' stopped: {exc}. Artifacts written before the "
        "stop are durable and verify-gated; re-running converges (already-"
        "ingested sources are skipped). Raise DISTILL_MCP_MAX_SPEND_PER_CALL "
        "or run the action via the distill CLI.",
        "spent": round(exc.spent, 6),
        "cap": exc.budget,
    }
    if _ACCOUNTING_FAILURE_NOTE in getattr(exc, "__notes__", ()):
        payload["accounting_status"] = "failed"
        payload["accounting_error"] = _ACCOUNTING_FAILURE_NOTE
    return json.dumps(payload, indent=2)


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
    ledger_command: str | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator marking an MCP tool as write-side (spend, ingest, or mutation).

    Stacks *under* ``@mcp.tool()`` so the registered callable carries the
    read-only gate and the per-call spend cap. The first
    ``capped_tracker()`` created inside the tool becomes the call's single
    ledger owner and is persisted before success, failure, cancellation, or a
    structured budget response crosses the MCP boundary. Tools can opt into
    read-only preview calls when ``preview=True`` is structurally
    non-mutating. ``functools.wraps`` preserves the signature FastMCP
    introspects for the schema.
    """

    def deco(fn: Callable[P, R]) -> Callable[P, R]:
        command = ledger_command or action
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
                    mark_current_run_outcome("refused")
                    return refusal
                try:
                    with _tool_cost_scope(command):
                        return await async_fn(*args, **kwargs)
                except BudgetExceededError as exc:
                    mark_current_run_outcome("budget_exceeded")
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
                mark_current_run_outcome("refused")
                return refusal
            try:
                with _tool_cost_scope(command):
                    return sync_fn(*args, **kwargs)
            except BudgetExceededError as exc:
                mark_current_run_outcome("budget_exceeded")
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

    mark_current_run_outcome("refused")
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
