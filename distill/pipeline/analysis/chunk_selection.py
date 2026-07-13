# pyright: strict
"""Chunk selection for multi-pass analysis.

Chunking boundaries and token budgets are rule-owned. Heading-based section
matching uses captured heading metadata only (structural ground truth). Semantic
relevance ("which chunks matter for this focus?") uses at most one batched
model call per document when structural selection leaves gaps. Positional spread
is the honest no-model order. Keyword overlap is tier-4 fallback only for
legacy insight category names that have a keyword table.

See docs/design/agentic-balance.md and model-judgment-vs-brittle-fallbacks.md.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, cast

from distill.llm.availability import model_available
from distill.llm.cost_policy import CostPolicyError
from distill.llm.errors import ProviderBusyTimeoutError
from distill.llm.json_extract import extract_json
from distill.llm.router import LLM_Response, RouterConfig, call
from distill.pipeline.analysis.chunking import Chunk, estimate_tokens
from distill.pipeline.analysis.reranker import (
    ScoredChunk,
    keyword_fallback_available,
    rerank_for_category,
)
from distill.pipeline.costs import BudgetExceededError, CostTracker, TokenUsage

logger = logging.getLogger(__name__)

ChunkSelectionMode = Literal[
    "model",
    "model_batch",
    "structural",
    "positional_order",
    "keyword_fallback",
]

__all__ = [
    "ChunkSelectionMode",
    "ChunkSelectionPlan",
    "PassSelectionSpec",
    "build_chunk_selection_plan",
    "format_selection_modes",
    "parse_section_blocks",
    "select_chunks_for_category",
]

_PREVIEW_CHARS = 400
_BATCH_MODEL_SECTION_THRESHOLD = 2


def _empty_by_section() -> dict[str, list[ScoredChunk]]:
    return {}


def _empty_modes() -> dict[str, ChunkSelectionMode]:
    return {}


@dataclass(frozen=True)
class PassSelectionSpec:
    """One multipass section's structural selection hints."""

    section: str
    focus: str = ""
    heading_patterns: tuple[str, ...] = ()


@dataclass
class ChunkSelectionPlan:
    """Per-section chunk picks for one multipass document."""

    by_section: dict[str, list[ScoredChunk]] = field(default_factory=_empty_by_section)
    modes: dict[str, ChunkSelectionMode] = field(default_factory=_empty_modes)


def build_chunk_selection_plan(
    chunks: list[Chunk],
    passes: tuple[PassSelectionSpec, ...],
    context_window: int,
    config: RouterConfig,
    *,
    tracker: CostTracker | None = None,
) -> ChunkSelectionPlan:
    """Build chunk picks for every pass with minimal model spend.

    1. Structural heading match from captured heading metadata (free).
    2. One batched model assignment when passes still lack chunks and a rerank
       route exists.
    3. Honest degradation when no model judgment is available: positional spread
       for all passes; keyword overlap only for legacy category names with a
       keyword table, never presented as semantic ranking.
    """
    plan = ChunkSelectionPlan()
    if not chunks:
        return plan

    unresolved: list[PassSelectionSpec] = []
    for spec in passes:
        selected, mode = _select_structural(
            chunks,
            spec.section,
            context_window,
            heading_patterns=spec.heading_patterns,
        )
        if selected:
            plan.by_section[spec.section] = selected
            plan.modes[spec.section] = mode
        else:
            unresolved.append(spec)

    if unresolved and model_available("rerank"):
        batched = _batch_select_with_model(
            chunks,
            unresolved,
            context_window,
            config,
            tracker=tracker,
        )
        model_mode: ChunkSelectionMode = (
            "model" if len(unresolved) < _BATCH_MODEL_SECTION_THRESHOLD else "model_batch"
        )
        for section, selected in batched.items():
            if section not in plan.by_section and selected:
                plan.by_section[section] = selected
                plan.modes[section] = model_mode
                unresolved = [spec for spec in unresolved if spec.section != section]

    for spec in unresolved:
        if spec.section in plan.by_section:
            continue
        selected, mode = _select_honest_fallback(
            chunks,
            spec.section,
            context_window,
        )
        if selected:
            plan.by_section[spec.section] = selected
            plan.modes[spec.section] = mode

    return plan


def format_selection_modes(modes: dict[str, ChunkSelectionMode]) -> str:
    """Serialize per-pass chunk selection modes for artifact frontmatter."""
    return "; ".join(f"{section}:{mode}" for section, mode in sorted(modes.items()))


def select_chunks_for_category(
    chunks: list[Chunk],
    category: str,
    context_window: int,
    config: RouterConfig,
    *,
    focus: str = "",
    heading_patterns: tuple[str, ...] = (),
    tracker: CostTracker | None = None,
) -> tuple[list[ScoredChunk], ChunkSelectionMode]:
    """Select chunks for one pass. Prefer the shared plan builder when possible."""
    plan = build_chunk_selection_plan(
        chunks,
        (PassSelectionSpec(section=category, focus=focus, heading_patterns=heading_patterns),),
        context_window,
        config,
        tracker=tracker,
    )
    selected = plan.by_section.get(category, [])
    mode = plan.modes.get(category, "positional_order")
    return selected, mode


def _select_honest_fallback(
    chunks: list[Chunk],
    category: str,
    context_window: int,
) -> tuple[list[ScoredChunk], ChunkSelectionMode]:
    """Tier-4 degradation: keyword table when defined, else positional order."""
    if keyword_fallback_available(category):
        selected = rerank_for_category(chunks, category, context_window)
        if selected:
            logger.info(
                "Chunk selection for '%s': keyword_fallback (tier-4, not semantic judgment)",
                category,
            )
            return selected, "keyword_fallback"

    selected = _select_positional_order(chunks, category, context_window)
    logger.info(
        "Chunk selection for '%s': positional_order (no model judgment available)",
        category,
    )
    return selected, "positional_order"


def _select_positional_order(
    chunks: list[Chunk],
    category: str,
    context_window: int,
) -> list[ScoredChunk]:
    selected: list[ScoredChunk] = []
    tokens_used = 0
    for chunk in _positional_spread(chunks):
        chunk_tokens = estimate_tokens(chunk.text)
        if tokens_used + chunk_tokens > context_window:
            continue
        selected.append(
            ScoredChunk(chunk=chunk, score=0.0, category=category),
        )
        tokens_used += chunk_tokens
    return selected


def _batch_select_with_model(
    chunks: list[Chunk],
    passes: Sequence[PassSelectionSpec],
    context_window: int,
    config: RouterConfig,
    *,
    tracker: CostTracker | None,
) -> dict[str, list[ScoredChunk]]:
    if len(passes) < _BATCH_MODEL_SECTION_THRESHOLD:
        result: dict[str, list[ScoredChunk]] = {}
        for spec in passes:
            selected = _select_with_model(
                chunks,
                spec.section,
                context_window,
                config,
                focus=spec.focus,
                tracker=tracker,
            )
            if selected:
                result[spec.section] = selected
        return result

    response = _call_chunk_rank(
        config,
        _build_batch_chunk_rank_prompt(chunks, passes),
        call_type="chunk_rank_batch",
        max_tokens=768,
        tracker=tracker,
        failure_context="Batched chunk ranking",
    )
    if response is None:
        return {}

    parsed = extract_json(response.text)
    if not isinstance(parsed, dict):
        return {}

    assignments_obj = parsed.get("assignments")
    if not isinstance(assignments_obj, dict):
        return {}
    assignments = cast(dict[str, object], assignments_obj)

    batched: dict[str, list[ScoredChunk]] = {}
    for spec in passes:
        raw_value = assignments.get(spec.section)
        if not isinstance(raw_value, list):
            continue
        raw_indices = cast(list[object], raw_value)
        selected = _indices_to_scored_chunks(
            chunks,
            raw_indices,
            spec.section,
            context_window,
        )
        if selected:
            batched[spec.section] = selected
    return batched


def _select_with_model(
    chunks: list[Chunk],
    category: str,
    context_window: int,
    config: RouterConfig,
    *,
    focus: str,
    tracker: CostTracker | None,
) -> list[ScoredChunk]:
    response = _call_chunk_rank(
        config,
        _build_chunk_rank_prompt(chunks, category, focus),
        call_type="chunk_rank",
        max_tokens=512,
        tracker=tracker,
        failure_context=f"Model chunk ranking for '{category}'",
    )
    if response is None:
        return []

    parsed = extract_json(response.text)
    if not isinstance(parsed, dict):
        return []

    raw_value = parsed.get("indices")
    if not isinstance(raw_value, list):
        return []

    raw_indices = cast(list[object], raw_value)
    return _indices_to_scored_chunks(chunks, raw_indices, category, context_window)


def _call_chunk_rank(
    config: RouterConfig,
    prompt: str,
    *,
    call_type: str,
    max_tokens: int,
    tracker: CostTracker | None,
    failure_context: str,
) -> LLM_Response | None:
    """Call the reranker, recording completed spend before any budget stop."""
    try:
        response = call(
            config,
            workload_tag="rerank",
            prompt=prompt,
            call_type=call_type,
            max_tokens=max_tokens,
            temperature=0.0,
            usage_tracker=tracker,
        )
        if tracker is not None:
            tracker.record(TokenUsage.from_response(response, call_type=call_type))
    except (BudgetExceededError, CostPolicyError, ProviderBusyTimeoutError):
        raise
    except Exception as exc:
        logger.debug("%s failed: %s", failure_context, exc)
        return None
    return response


def _indices_to_scored_chunks(
    chunks: list[Chunk],
    raw_indices: list[object],
    category: str,
    context_window: int,
) -> list[ScoredChunk]:
    ranked_indices: list[int] = []
    for item in raw_indices:
        if isinstance(item, int) and 0 <= item < len(chunks) and item not in ranked_indices:
            ranked_indices.append(item)

    selected: list[ScoredChunk] = []
    tokens_used = 0
    for rank, index in enumerate(ranked_indices):
        chunk = chunks[index]
        chunk_tokens = estimate_tokens(chunk.text)
        if tokens_used + chunk_tokens > context_window:
            continue
        score = float(len(ranked_indices) - rank)
        selected.append(ScoredChunk(chunk=chunk, score=score, category=category))
        tokens_used += chunk_tokens
    return selected


def _build_batch_chunk_rank_prompt(
    chunks: list[Chunk],
    passes: Sequence[PassSelectionSpec],
) -> str:
    section_lines = "\n".join(
        f'- "{spec.section}": {spec.focus or spec.section}' for spec in passes
    )
    catalog = "\n".join(_chunk_summary(chunk) for chunk in chunks)
    return (
        "Assign document chunks to analysis sections.\n"
        "Return JSON only:\n"
        '{"assignments": {"Section Name": [<chunk index ints>, ...], ...}}\n\n'
        "Use each chunk index at most once when possible. "
        "Omit sections with no relevant chunks.\n\n"
        f"Sections:\n{section_lines}\n\n"
        f"Chunks:\n{catalog}"
    )


def _build_chunk_rank_prompt(chunks: list[Chunk], category: str, focus: str) -> str:
    focus_line = f"Extract: {focus}\n" if focus else ""
    catalog = "\n".join(_chunk_summary(chunk) for chunk in chunks)
    return (
        "You are selecting document chunks for a focused analysis pass.\n"
        f"Focus area: {category}\n"
        f"{focus_line}\n"
        "Return JSON only with chunk indices ordered by relevance "
        "(most relevant first):\n"
        '{"indices": [<int>, ...]}\n\n'
        "Include only chunks with substantive content for this focus. "
        "Omit irrelevant chunks.\n\n"
        f"Chunks:\n{catalog}"
    )


def _chunk_summary(chunk: Chunk) -> str:
    preview = chunk.text[:_PREVIEW_CHARS].replace("\n", " ")
    heading = chunk.heading_context or "(no heading)"
    return f"[{chunk.index}] heading={heading!r} preview={preview!r}"


def _select_structural(
    chunks: list[Chunk],
    category: str,
    context_window: int,
    *,
    heading_patterns: tuple[str, ...],
) -> tuple[list[ScoredChunk], ChunkSelectionMode]:
    if heading_patterns:
        ranked = sorted(
            (chunk for chunk in chunks if _heading_pattern_hit(chunk, heading_patterns)),
            key=lambda chunk: chunk.index,
        )
        if not ranked:
            return [], "structural"
        mode: ChunkSelectionMode = "structural"
    else:
        ranked = _positional_spread(chunks)
        mode = "positional_order"

    selected: list[ScoredChunk] = []
    tokens_used = 0
    for chunk in ranked:
        chunk_tokens = estimate_tokens(chunk.text)
        if tokens_used + chunk_tokens > context_window:
            continue
        selected.append(
            ScoredChunk(
                chunk=chunk,
                score=float(_heading_pattern_hit(chunk, heading_patterns)),
                category=category,
            )
        )
        tokens_used += chunk_tokens
    return selected, mode


def _heading_pattern_hit(chunk: Chunk, patterns: tuple[str, ...]) -> int:
    """Match heading metadata only. Body text is not structural ground truth."""
    if not patterns:
        return 0
    haystack = (chunk.heading_context or "").lower()
    return int(any(pattern in haystack for pattern in patterns))


def _positional_spread(chunks: list[Chunk]) -> list[Chunk]:
    """Mitigate lost-in-the-middle with start, end, and spaced middle chunks."""
    count = len(chunks)
    if count <= 3:
        return list(chunks)

    indices = {0, count - 1}
    if count > 4:
        step = max(1, (count - 2) // 3)
        for index in range(step, count - 1, step):
            indices.add(index)
    return [chunks[index] for index in sorted(indices)]


_SECTION_HEADER_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def parse_section_blocks(text: str) -> dict[str, str]:
    """Parse ``## Section`` blocks from a multipass model response."""
    matches = list(_SECTION_HEADER_RE.finditer(text))
    if not matches:
        return {}

    blocks: dict[str, str] = {}
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            blocks[title] = body
    return blocks
