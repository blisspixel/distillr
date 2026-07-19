# pyright: strict
"""MCP tools -- sub-agent surface: list_topics and bounded summaries.

The bounded half of the JIT read layer (roadmap 0.12 "Sub-agent-friendly MCP
surface"): `find_insights` returns ranked paths for drill-down; these return
*content sized to a budget*. `find_insights_summary` spends one compression
call (cached by corpus revision, so repeats are free) and is therefore gated in
read-only mode. `list_topics` and `list_topic_summary` are deterministic and
free, for a sub-agent choosing which topic to query at all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from distill.library.claude_md import count_topic_sources, topic_summary_line
from distill.library.confined import read_confined_text_prefix, validate_confined_path
from distill.library.paths import strip_frontmatter
from distill.llm.availability import model_available
from distill.mcp.server import capped_tracker, cost_summary, load_config, mcp, write_tool

__all__: list[str] = []

_MAX_SYNTHESIS_FILE_BYTES = 4 * 1024 * 1024
_MAX_SYNTHESIS_PREFIX_CHARS = 128 * 1024
_MAX_TOPIC_SUMMARY_CHARS = 1200
_SYNTHESIS_PATTERNS = (
    "*_Corpus_Synthesis.md",
    "*_Topic_Synthesis.md",
    "*_Paper_Synthesis.md",
)


@dataclass(frozen=True, slots=True)
class _SynthesisCandidate:
    path: Path
    mtime_ns: int
    state: str


def _synthesis_candidates(topic_dir: Path, library_dir: Path) -> list[_SynthesisCandidate]:
    candidates: list[_SynthesisCandidate] = []
    seen: set[Path] = set()
    for pattern in _SYNTHESIS_PATTERNS:
        for path in topic_dir.glob(pattern):
            if path in seen:
                continue
            seen.add(path)
            try:
                initial = path.lstat()
            except FileNotFoundError:
                continue
            except OSError:
                candidates.append(_SynthesisCandidate(path=path, mtime_ns=-1, state="unreadable"))
                continue
            validated = validate_confined_path(path, library_dir, expect_directory=False)
            if validated is None or validated[1].st_nlink != 1:
                state = "unsafe"
            elif validated[1].st_size > _MAX_SYNTHESIS_FILE_BYTES:
                state = "oversized"
            else:
                state = "available"
            candidates.append(
                _SynthesisCandidate(
                    path=path,
                    mtime_ns=initial.st_mtime_ns,
                    state=state,
                )
            )
    return sorted(candidates, key=lambda item: (-item.mtime_ns, item.path.name.casefold()))


def _summary_paragraph(prefix: str) -> str:
    normalized = prefix.replace("\r\n", "\n").replace("\r", "\n")
    body = strip_frontmatter(normalized)
    for block in body.split("\n\n"):
        stripped = block.strip()
        if stripped and not stripped.startswith("#"):
            return " ".join(stripped.split())[:_MAX_TOPIC_SUMMARY_CHARS]
    return ""


def _has_synthesis(topic_dir: Path) -> bool:
    return any(any(topic_dir.glob(pattern)) for pattern in _SYNTHESIS_PATTERNS)


@mcp.tool()
def list_topics(limit: int = 50) -> str:
    """List available corpus topics (free, no model call).

    Use this before topic-scoped tools such as find_insights,
    list_topic_summary, research_gaps, or ask. Returned paths are relative to
    the library root.

    Args:
        limit: Maximum topics to return, sorted by name. Clamped to 1..200.
    """
    config = load_config()
    topics_dir = config.topics_dir()
    limit = max(1, min(int(limit), 200))
    if not topics_dir.is_dir():
        return json.dumps(
            {
                "topics": [],
                "count": 0,
                "message": "No topics directory found. Ingest sources first or set DISTILL_OUTPUT_DIR to the corpus library.",
            },
            indent=2,
        )

    rows: list[dict[str, object]] = []
    for topic_dir in sorted(
        (p for p in topics_dir.iterdir() if p.is_dir() and not p.name.startswith(".")),
        key=lambda p: p.name.lower(),
    ):
        counts = count_topic_sources(topic_dir)
        has_synthesis = _has_synthesis(topic_dir)
        if counts["total"] == 0 and not has_synthesis:
            continue
        rows.append(
            {
                "topic": topic_dir.name,
                "path": f"topics/{topic_dir.name}",
                "sources": counts,
                "has_synthesis": has_synthesis,
                "summary": topic_summary_line(topic_dir, topic_dir.name),
            }
        )
        if len(rows) >= limit:
            break

    response: dict[str, object] = {"topics": rows, "count": len(rows)}
    if not rows:
        response["message"] = (
            "No populated topics found. Ingest sources first or set DISTILL_OUTPUT_DIR to the corpus library."
        )
    return json.dumps(response, indent=2)


@mcp.tool()
@write_tool("find_insights_summary", ledger_command="summary-query")
def find_insights_summary(topic: str, query: str, max_tokens: int = 4000) -> str:
    """Summarize a topic's best-matching insights, focused on a query, within a token budget.

    Built for sub-agents: one bounded brief with bracketed source-stem
    citations (drill into any stem with read_insight). Cached by corpus
    revision -- repeated calls cost nothing until the matching artifacts
    change.

    Args:
        topic: Topic whose corpus to summarize from.
        query: The question the brief should be organized around.
        max_tokens: Approximate context budget for the brief (default 4000).
    """
    from distill.pipeline.summary_query import summarize_query

    config = load_config()
    if not model_available():
        return json.dumps(
            {
                "status": "error",
                "error": "No model configured (set a cloud key or DISTILL_PROVIDER).",
            },
            indent=2,
        )
    if not config.topic_dir(topic).exists():
        return json.dumps({"status": "error", "error": f"Topic '{topic}' not found."}, indent=2)
    max_tokens = max(500, min(int(max_tokens), 16_000))

    tracker = capped_tracker()
    result = summarize_query(config, topic, query, max_tokens=max_tokens, tracker=tracker)
    if result is None:
        return json.dumps(
            {"status": "no_matches", "message": f"Nothing in '{topic}' matches this query."},
            indent=2,
        )
    if result.refused_reason:
        return json.dumps(
            {
                "status": "refused",
                "error": result.refused_reason,
                "summary": result.summary,
                "sources": result.sources,
                "cached": result.cached,
                "model": result.model,
                "cost": cost_summary(tracker),
            },
            indent=2,
        )
    return json.dumps(
        {
            "summary": result.summary,
            "sources": result.sources,
            "cached": result.cached,
            "model": result.model,
            "cost": cost_summary(tracker),
        },
        indent=2,
    )


@mcp.tool()
def list_topic_summary(topic: str) -> str:  # noqa: C901 - bounded candidate fallback states
    """One-paragraph orientation for a topic (free, no model call).

    Pulled from the topic's newest synthesis artifact; used when a sub-agent
    is choosing which topic to query before spending on retrieval.

    Args:
        topic: Topic to summarize.
    """
    config = load_config()
    topic_dir = config.topic_dir(topic)
    try:
        topic_dir.lstat()
    except FileNotFoundError:
        return json.dumps({"status": "error", "error": f"Topic '{topic}' not found."}, indent=2)
    except OSError:
        return json.dumps(
            {"status": "error", "error": f"Topic '{topic}' is unavailable."}, indent=2
        )
    if validate_confined_path(topic_dir, config.library_dir, expect_directory=True) is None:
        return json.dumps(
            {"status": "error", "error": f"Topic '{topic}' is unavailable."}, indent=2
        )

    candidates = _synthesis_candidates(topic_dir, config.library_dir)
    insight_count = sum(1 for _ in topic_dir.rglob("*_Insights.md"))
    if not candidates:
        return json.dumps(
            {
                "topic": topic,
                "summary": (
                    f"No synthesis artifact yet; the topic holds {insight_count} insight "
                    "artifact(s). Run distill synthesize to produce an overview."
                ),
                "from": "",
                "insights": insight_count,
                "status": "unavailable",
                "evidence": {
                    "status": "absent",
                    "newest": "",
                    "selected": "",
                    "reason": "no_synthesis",
                },
            },
            indent=2,
        )

    newest = candidates[0]
    first_failure = ""
    for candidate in candidates:
        reason = candidate.state
        paragraph = ""
        if reason == "available":
            prefix = read_confined_text_prefix(
                candidate.path,
                config.library_dir,
                max_file_bytes=_MAX_SYNTHESIS_FILE_BYTES,
                max_chars=_MAX_SYNTHESIS_PREFIX_CHARS,
            )
            if prefix is None:
                reason = "unreadable"
            else:
                paragraph = _summary_paragraph(prefix)
                if not paragraph:
                    reason = "no_summary_text"
        if paragraph:
            degraded = bool(first_failure)
            return json.dumps(
                {
                    "topic": topic,
                    "summary": paragraph,
                    "from": candidate.path.name,
                    "insights": insight_count,
                    "status": "degraded" if degraded else "ok",
                    "evidence": {
                        "status": "degraded" if degraded else "available",
                        "newest": newest.path.name,
                        "selected": candidate.path.name,
                        **({"reason": first_failure} if degraded else {}),
                    },
                },
                indent=2,
            )
        if not first_failure:
            first_failure = reason

    if first_failure == "no_summary_text":
        paragraph = (
            "Synthesis artifact contains no substantive prose; the topic holds "
            f"{insight_count} insight artifact(s)."
        )
    else:
        paragraph = (
            f"Synthesis evidence is unavailable ({first_failure}); the topic holds "
            f"{insight_count} insight artifact(s)."
        )
    return json.dumps(
        {
            "topic": topic,
            "summary": paragraph,
            "from": "",
            "insights": insight_count,
            "status": "unavailable",
            "evidence": {
                "status": "unavailable",
                "newest": newest.path.name,
                "selected": "",
                "reason": first_failure,
            },
        },
        indent=2,
    )
