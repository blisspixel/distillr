# pyright: strict
"""Multi-pass analysis assembly for small-window and long-document paths.

Orchestrates per-section passes over chunked content and merges results into
the same artifact shape as single-pass analysis. Chunk relevance is resolved
through ``chunk_selection`` (structural first, one batched model fallback).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from distill.llm.metadata import ProviderMetadata
from distill.llm.router import LLM_Response, RouterConfig, call
from distill.pipeline.analysis.chunk_selection import (
    ChunkSelectionMode,
    PassSelectionSpec,
    build_chunk_selection_plan,
    format_selection_modes,
    parse_section_blocks,
    select_chunks_for_category,
)
from distill.pipeline.analysis.chunking import Chunk
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.lenses import focus_directive
from distill.prompts.shared import UNTRUSTED_CONTENT_RULES

logger = logging.getLogger(__name__)

__all__ = [
    "INSIGHT_CATEGORIES",
    "PAPER_ANALYSIS_PASSES",
    "PAPER_CANONICAL_SECTIONS",
    "AnalysisPass",
    "MultiPassAnalysisResult",
    "PassResult",
    "merge_paper_pass_results",
    "merge_pass_results",
    "multi_pass_analysis",
]

PAPER_CANONICAL_SECTIONS: tuple[str, ...] = (
    "Summary",
    "Core Contribution",
    "Methods and Evidence",
    "Practical Implications",
    "Limits and Open Questions",
    "Follow-Up Research",
)

INSIGHT_CATEGORIES: list[str] = [
    "Key Findings",
    "Methods",
    "Limits",
    "Open Questions",
]

CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "Key Findings": (
        "the main results, discoveries, contributions, and significant outcomes. "
        "Focus on what was achieved, demonstrated, or proven."
    ),
    "Methods": (
        "the approaches, algorithms, architectures, techniques, and implementation details. "
        "Focus on how things were done, what tools or frameworks were used."
    ),
    "Limits": (
        "the limitations, constraints, weaknesses, trade-offs, and challenges. "
        "Focus on what doesn't work well, what's missing, or what could be improved."
    ),
    "Open Questions": (
        "the unresolved questions, future directions, gaps in knowledge, and opportunities. "
        "Focus on what remains unknown or what could be explored next."
    ),
}


@dataclass(frozen=True)
class AnalysisPass:
    """One focused multi-pass call for paper analysis."""

    section: str
    focus: str
    heading_patterns: tuple[str, ...]
    output_sections: tuple[str, ...] = ()


PAPER_ANALYSIS_PASSES: tuple[AnalysisPass, ...] = (
    AnalysisPass(
        "front matter",
        "what the paper is about and what it adds relative to common approaches",
        ("abstract", "introduction", "overview", "contribution", "related work"),
        ("Summary", "Core Contribution"),
    ),
    AnalysisPass(
        "methods and evidence",
        "methods, experiments, benchmarks, and evaluation signals described",
        ("method", "experiment", "evaluation", "result", "benchmark"),
        ("Methods and Evidence",),
    ),
    AnalysisPass(
        "implications and follow-up",
        "practical implications, limits, open questions, and follow-up research",
        ("discussion", "limit", "conclusion", "future", "application", "implication", "related"),
        ("Practical Implications", "Limits and Open Questions", "Follow-Up Research"),
    ),
)


@dataclass
class PassResult:
    """Result from a single focused analysis pass."""

    category: str
    insights: str
    chunks_used: int
    selection_mode: ChunkSelectionMode = "structural"


@dataclass
class MultiPassAnalysisResult:
    """Multipass output plus honest chunk-selection labels."""

    passes: list[PassResult]
    selection_modes: str = ""


def _build_focused_prompt(
    category: str,
    chunk_texts: list[str],
    *,
    description: str,
    goal: str = "",
    lens: str = "",
    output_sections: tuple[str, ...] = (),
) -> str:
    directive = focus_directive(goal=goal, lens=lens)
    combined_content = "\n\n---\n\n".join(chunk_texts)
    section_block = (
        "Write these sections using exact ## headings:\n"
        + "\n".join(f"- ## {name}" for name in output_sections)
        + "\n\n"
        if output_sections
        else f"Extract insights for the section: ## {category}\n"
    )
    return (
        f"You are analyzing a technical paper for a fast-moving research corpus.\n\n"
        f"{directive}"
        f"{section_block}"
        f"Focus specifically on: {description}\n\n"
        "Rules:\n"
        "- Use only the content provided below.\n"
        "- Distinguish fact from interpretation.\n"
        "- Do not claim outcomes that are not in the content.\n"
        "- Be concrete and specific.\n\n"
        f"SECURITY: {UNTRUSTED_CONTENT_RULES}\n\n"
        f"CONTENT:\n{combined_content}"
    )


def multi_pass_analysis(
    chunks: list[Chunk],
    config: RouterConfig,
    metadata: ProviderMetadata,
    *,
    passes: tuple[AnalysisPass, ...] | None = None,
    tracker: CostTracker | None = None,
    goal: str = "",
    lens: str = "",
) -> MultiPassAnalysisResult:
    """Assemble insights from focused per-section passes."""
    results: list[PassResult] = []
    available_window = int(metadata.context_window * 0.80)

    if passes is None:
        legacy = _legacy_category_passes(
            chunks,
            config,
            available_window,
            tracker=tracker,
            goal=goal,
            lens=lens,
        )
        return MultiPassAnalysisResult(
            passes=legacy,
            selection_modes=format_selection_modes(
                {result.category: result.selection_mode for result in legacy}
            ),
        )

    selection_specs = tuple(
        PassSelectionSpec(
            section=analysis_pass.section,
            focus=analysis_pass.focus,
            heading_patterns=analysis_pass.heading_patterns,
        )
        for analysis_pass in passes
    )
    selection_plan = build_chunk_selection_plan(
        chunks,
        selection_specs,
        available_window,
        config,
    )

    for analysis_pass in passes:
        scored_chunks = selection_plan.by_section.get(analysis_pass.section, [])
        selection_mode = selection_plan.modes.get(analysis_pass.section, "structural")
        if not scored_chunks:
            logger.info(
                "Skipping pass '%s': no chunks selected",
                analysis_pass.section,
            )
            continue

        chunk_texts = [sc.chunk.text for sc in scored_chunks]
        prompt = _build_focused_prompt(
            analysis_pass.section,
            chunk_texts,
            description=analysis_pass.focus,
            goal=goal,
            lens=lens,
            output_sections=analysis_pass.output_sections,
        )
        response: LLM_Response = call(
            config,
            workload_tag="analysis",
            prompt=prompt,
            call_type=f"paper_multipass_{analysis_pass.section.lower().replace(' ', '_')}",
        )
        if tracker is not None:
            tracker.record(TokenUsage.from_response(response, call_type="paper"))

        results.append(
            PassResult(
                category=analysis_pass.section,
                insights=response.text.strip(),
                chunks_used=len(scored_chunks),
                selection_mode=selection_mode,
            )
        )
        logger.debug(
            "Multi-pass pass '%s': mode=%s chunks=%d chars=%d",
            analysis_pass.section,
            selection_mode,
            len(scored_chunks),
            len(response.text),
        )

    logger.info(
        "Multi-pass analysis complete: %d/%d passes produced",
        len(results),
        len(passes),
    )
    return MultiPassAnalysisResult(
        passes=results,
        selection_modes=format_selection_modes(selection_plan.modes),
    )


def _legacy_category_passes(
    chunks: list[Chunk],
    config: RouterConfig,
    available_window: int,
    *,
    tracker: CostTracker | None,
    goal: str,
    lens: str,
) -> list[PassResult]:
    """Backward-compatible generic category passes."""
    results: list[PassResult] = []
    for category in INSIGHT_CATEGORIES:
        scored_chunks, selection_mode = select_chunks_for_category(
            chunks,
            category,
            available_window,
            config,
            focus=CATEGORY_DESCRIPTIONS.get(category, category),
        )
        if not scored_chunks:
            logger.info(
                "Skipping category '%s': no chunks selected (%s)",
                category,
                selection_mode,
            )
            continue

        chunk_texts = [sc.chunk.text for sc in scored_chunks]
        prompt = _build_focused_prompt(
            category,
            chunk_texts,
            description=CATEGORY_DESCRIPTIONS.get(category, category),
            goal=goal,
            lens=lens,
        )
        response: LLM_Response = call(
            config,
            workload_tag="analysis",
            prompt=prompt,
            call_type=f"multipass_{category.lower().replace(' ', '_')}",
        )
        if tracker is not None:
            tracker.record(TokenUsage.from_response(response, call_type="paper"))

        results.append(
            PassResult(
                category=category,
                insights=response.text.strip(),
                chunks_used=len(scored_chunks),
                selection_mode=selection_mode,
            )
        )
    return results


def merge_paper_pass_results(
    results: list[PassResult],
    *,
    body: str,
) -> str:
    """Merge per-pass paper responses into canonical single-pass section headings."""
    if not results:
        return body

    section_map: dict[str, str] = {}
    for result in results:
        parsed = parse_section_blocks(result.insights)
        if parsed:
            section_map.update(parsed)
            continue
        for output_section in _output_sections_for_pass(result.category):
            section_map.setdefault(output_section, result.insights.strip())

    sections: list[str] = []
    for canonical in PAPER_CANONICAL_SECTIONS:
        content = section_map.get(canonical, "").strip()
        sections.append(f"## {canonical}\n\n{content}\n" if content else f"## {canonical}\n\n")

    return "\n".join(sections).strip() + "\n"


def _output_sections_for_pass(pass_name: str) -> tuple[str, ...]:
    for analysis_pass in PAPER_ANALYSIS_PASSES:
        if analysis_pass.section == pass_name:
            return analysis_pass.output_sections
    return ()


def merge_pass_results(
    results: list[PassResult],
    paper_title: str,
    paper_id: str,
    model: str,
) -> str:
    """Merge per-category results into legacy multipass markdown."""
    safe_title = paper_title.replace('"', '\\"')
    frontmatter = (
        "---\n"
        f'paper_title: "{safe_title}"\n'
        f"paper_id: {paper_id}\n"
        "source: arxiv\n"
        f"analyzed_by: {model}\n"
        "source_mode: chunked_local\n"
        "---\n"
    )

    sections: list[str] = []
    result_map = {r.category: r.insights for r in results}
    for category in INSIGHT_CATEGORIES:
        content = result_map.get(category, "")
        if content:
            content = _deduplicate_content(content, category, result_map)
        sections.append(f"\n### {category}\n\n{content}\n" if content else f"\n### {category}\n\n")

    return frontmatter + "".join(sections)


def _deduplicate_content(
    content: str,
    current_category: str,
    result_map: dict[str, str],
) -> str:
    specificity = ["Methods", "Limits", "Open Questions", "Key Findings"]
    current_rank = specificity.index(current_category) if current_category in specificity else 999

    lines = content.split("\n")
    deduplicated: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            deduplicated.append(line)
            continue

        found_in_more_specific = False
        for other_category, other_content in result_map.items():
            if other_category == current_category:
                continue
            other_rank = specificity.index(other_category) if other_category in specificity else 999
            if other_rank < current_rank and stripped in other_content:
                found_in_more_specific = True
                break

        if not found_in_more_specific:
            deduplicated.append(line)

    return "\n".join(deduplicated)
