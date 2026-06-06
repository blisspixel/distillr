# pyright: strict
"""Multi-pass analysis assembly for small-window local models.

Orchestrates per-category passes over chunked content and merges results
into a unified insight matching the same structure as single-pass cloud analysis.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from distill.llm.metadata import ProviderMetadata
from distill.llm.router import LLM_Response, RouterConfig, call
from distill.pipeline.analysis.chunking import Chunk
from distill.pipeline.analysis.reranker import (
    INSIGHT_CATEGORIES,
    rerank_for_category,
)
from distill.prompts.shared import UNTRUSTED_CONTENT_RULES

logger = logging.getLogger(__name__)

__all__ = [
    "PassResult",
    "merge_pass_results",
    "multi_pass_analysis",
]

# Descriptions for focused analysis prompts
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


@dataclass
class PassResult:
    """Result from a single focused analysis pass."""

    category: str
    insights: str
    chunks_used: int


def _build_focused_prompt(category: str, chunk_texts: list[str]) -> str:
    """Build a focused analysis prompt for a specific category."""
    description = CATEGORY_DESCRIPTIONS.get(category, category)
    combined_content = "\n\n---\n\n".join(chunk_texts)

    return (
        f"Analyze the following content and extract {category} insights.\n"
        f"Focus specifically on: {description}\n\n"
        f"Provide a concise, well-structured summary of the {category} "
        f"found in this content. Use bullet points or short paragraphs.\n\n"
        f"SECURITY: {UNTRUSTED_CONTENT_RULES}\n\n"
        f"Content:\n{combined_content}"
    )


def multi_pass_analysis(
    chunks: list[Chunk],
    config: RouterConfig,
    metadata: ProviderMetadata,
) -> list[PassResult]:
    """Assemble insights from focused per-category passes.

    For each category:
    1. Rerank chunks and select top-k fitting within context window.
    2. Run analysis prompt focused on that category.
    3. Collect results.

    Args:
        chunks: Content chunks to analyze.
        config: Router configuration for LLM calls.
        metadata: Provider metadata with context window info.

    Returns:
        List of PassResult, one per category that had relevant chunks.
    """
    results: list[PassResult] = []
    # Reserve 20% for prompt template and output
    available_window = int(metadata.context_window * 0.80)

    for category in INSIGHT_CATEGORIES:
        # Rerank chunks for this category
        scored_chunks = rerank_for_category(chunks, category, available_window)

        if not scored_chunks:
            logger.info(
                "Skipping category '%s': all chunks below relevance threshold",
                category,
            )
            continue

        # Extract texts from selected chunks
        chunk_texts = [sc.chunk.text for sc in scored_chunks]

        # Build focused prompt
        prompt = _build_focused_prompt(category, chunk_texts)

        # Call LLM with analysis workload
        response: LLM_Response = call(
            config,
            workload_tag="analysis",
            prompt=prompt,
            call_type=f"multipass_{category.lower().replace(' ', '_')}",
        )

        results.append(
            PassResult(
                category=category,
                insights=response.text.strip(),
                chunks_used=len(scored_chunks),
            )
        )

        logger.debug(
            "Multi-pass category '%s': used %d chunks, produced %d chars",
            category,
            len(scored_chunks),
            len(response.text),
        )

    logger.info(
        "Multi-pass analysis complete: %d/%d categories produced",
        len(results),
        len(INSIGHT_CATEGORIES),
    )
    return results


def merge_pass_results(
    results: list[PassResult],
    paper_title: str,
    paper_id: str,
    model: str,
) -> str:
    """Merge per-category results into a single structured insight.

    Output matches the same YAML frontmatter and section structure
    as single-pass cloud analysis. Deduplicates overlapping content
    by keeping the version from the more specific category.

    Args:
        results: List of per-category pass results.
        paper_title: Title of the paper being analyzed.
        paper_id: Identifier of the paper (e.g., arXiv ID).
        model: Model name used for analysis.

    Returns:
        Complete markdown string with YAML frontmatter and sections.
    """
    safe_title = paper_title.replace('"', '\\"')

    # Build frontmatter
    frontmatter = (
        "---\n"
        f'paper_title: "{safe_title}"\n'
        f"paper_id: {paper_id}\n"
        "source: arxiv\n"
        f"analyzed_by: {model}\n"
        "source_mode: chunked_local\n"
        "---\n"
    )

    # Build sections — use results if available, otherwise empty
    sections: list[str] = []
    result_map = {r.category: r.insights for r in results}

    for category in INSIGHT_CATEGORIES:
        content = result_map.get(category, "")
        if content:
            # Deduplicate: remove lines that appear in a more specific category
            content = _deduplicate_content(content, category, result_map)
        sections.append(f"\n### {category}\n\n{content}\n" if content else f"\n### {category}\n\n")

    return frontmatter + "".join(sections)


def _deduplicate_content(
    content: str,
    current_category: str,
    result_map: dict[str, str],
) -> str:
    """Remove lines from content that appear verbatim in a more specific category.

    Category specificity order (most specific first):
    Methods > Limits > Open Questions > Key Findings

    If a line appears in both "Key Findings" and "Methods", keep it in "Methods".
    """
    # Specificity ranking: lower index = more specific
    specificity = ["Methods", "Limits", "Open Questions", "Key Findings"]

    current_rank = specificity.index(current_category) if current_category in specificity else 999

    # Check if any more-specific category contains the same lines
    lines = content.split("\n")
    deduplicated: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            deduplicated.append(line)
            continue

        # Check if this line appears in a more specific category
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
