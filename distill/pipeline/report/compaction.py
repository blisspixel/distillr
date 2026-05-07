# pyright: strict
"""Report phase compaction for context window management.

Compacts report phase output for the next phase using high-recall summarization.
Applied universally (cloud and local) to reduce token costs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from distill.llm.router import RouterConfig, call
from distill.pipeline.analysis.chunking import estimate_tokens

__all__ = [
    "CompactionResult",
    "compact_between_phases",
    "compact_phase_output",
    "extract_named_entities",
]


@dataclass(frozen=True)
class CompactionResult:
    """Result of compacting a report phase output."""

    compacted_text: str
    original_length: int
    compacted_length: int
    entities_preserved: list[str]


def extract_named_entities(text: str) -> set[str]:
    """Extract named entities for preservation verification.

    Uses regex-based extraction of:
    - Proper nouns (capitalized multi-word sequences)
    - Numbers and percentages
    - Dates (various formats)
    - Quoted terms
    """
    entities: set[str] = set()

    # Proper nouns: capitalized words not at sentence start (2+ word sequences)
    # Match sequences of capitalized words (e.g., "Machine Learning", "GPT-4")
    proper_nouns = re.findall(r"\b([A-Z][a-zA-Z\-]*(?:\s+[A-Z][a-zA-Z\-]*)+)\b", text)
    entities.update(proper_nouns)

    # Single capitalized words that look like proper nouns (not common English words)
    # Exclude words at the very start of sentences
    single_caps = re.findall(r"(?<=[.!?]\s)([A-Z][a-z]{2,})\b", text)
    entities.update(single_caps)

    # Acronyms (2+ uppercase letters, optionally with numbers)
    acronyms = re.findall(r"\b([A-Z][A-Z0-9]{1,}(?:-[A-Z0-9]+)*)\b", text)
    entities.update(acronyms)

    # Numbers with units or percentages
    numbers = re.findall(r"\b(\d+(?:\.\d+)?(?:\s*%|x|X|GB|MB|TB|K|M|B)?)\b", text)
    entities.update(numbers)

    # Dates: YYYY-MM-DD, Month YYYY, etc.
    dates_iso = re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    entities.update(dates_iso)
    dates_month = re.findall(
        r"\b((?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{4})\b",
        text,
    )
    entities.update(dates_month)

    # Quoted terms (single or double quotes)
    quoted = re.findall(r'["\u201c]([^"\u201d]{2,50})["\u201d]', text)
    entities.update(quoted)
    single_quoted = re.findall(r"['\u2018]([^'\u2019]{2,50})['\u2019]", text)
    entities.update(single_quoted)

    # Filter out empty strings and very short matches
    return {e.strip() for e in entities if e.strip() and len(e.strip()) >= 2}


def _build_compaction_prompt(text: str, target_words: int) -> str:
    """Build the compaction prompt for the LLM."""
    return (
        "Summarize the following text, preserving ALL named entities, quantitative claims, "
        "causal relationships, and key conclusions. "
        f"Target length: approximately {target_words} words.\n"
        "Do not omit any proper nouns, numbers, or specific claims.\n\n"
        f"Text:\n{text}"
    )


def compact_phase_output(
    phase_output: str,
    config: RouterConfig,
    context_window: int,
    *,
    target_ratio: float = 0.25,
) -> CompactionResult:
    """High-recall summary preserving key facts, entities, and conclusions.

    If first pass (25%) still exceeds window with next phase prompt,
    applies precision pass reducing to 10%.

    Args:
        phase_output: The full text output from a report phase.
        config: Router configuration for LLM calls.
        context_window: Available context window tokens for the next phase.
        target_ratio: Target compression ratio (default 0.25 = 25% of original).

    Returns:
        CompactionResult with the compacted text and metadata.
    """
    original_length = len(phase_output)

    if original_length == 0:
        return CompactionResult(
            compacted_text="",
            original_length=0,
            compacted_length=0,
            entities_preserved=[],
        )

    # Extract entities from original for verification
    original_entities = extract_named_entities(phase_output)

    # First pass: high-recall at target_ratio (default 25%)
    original_words = len(phase_output.split())
    target_words = max(1, int(original_words * target_ratio))

    prompt = _build_compaction_prompt(phase_output, target_words)
    response = call(
        config,
        workload_tag="report",
        prompt=prompt,
        call_type="compaction_high_recall",
    )
    compacted = response.text.strip()

    # Check if compacted text fits within context window
    compacted_tokens = estimate_tokens(compacted)
    if compacted_tokens > context_window:
        # Second pass: precision at 10%
        precision_target_words = max(1, int(original_words * 0.10))
        precision_prompt = _build_compaction_prompt(compacted, precision_target_words)
        precision_response = call(
            config,
            workload_tag="report",
            prompt=precision_prompt,
            call_type="compaction_precision",
        )
        compacted = precision_response.text.strip()

    # Verify entity preservation
    compacted_entities = extract_named_entities(compacted)
    preserved = sorted(original_entities & compacted_entities)

    return CompactionResult(
        compacted_text=compacted,
        original_length=original_length,
        compacted_length=len(compacted),
        entities_preserved=preserved,
    )


def compact_between_phases(
    phase_output: str,
    config: RouterConfig,
    context_window: int,
    *,
    target_ratio: float = 0.25,
) -> str:
    """Compact prior-phase output for use as context in the next phase.

    Convenience wrapper around compact_phase_output that returns just the
    compacted text. Applied universally (cloud and local) to reduce token costs.

    Integration points in the report pipeline:
    - Between Phase 1 (Research/Dossier) and Phase 2 (Section Writing):
      Compact the dossier before passing it as context to section prompts.
    - Between Phase 2 (Section Writing) and Phase 3 (Assembly):
      Compact previously written sections before assembly.
    - Between Phase 3 (Assembly) and Phase 4 (QA):
      Compact the assembled report before QA review.

    Usage example in accordion.py:
        from distill.pipeline.report.compaction import compact_between_phases

        # Before Phase 2, compact the dossier for section context
        compacted_dossier = compact_between_phases(
            dossier, rc, context_window
        )

    Args:
        phase_output: Full text output from the previous phase.
        config: Router configuration for LLM calls.
        context_window: Available context window tokens for the next phase.
        target_ratio: Target compression ratio (default 0.25).

    Returns:
        Compacted text string ready for use as context in the next phase.
    """
    if not phase_output:
        return ""

    result = compact_phase_output(
        phase_output,
        config,
        context_window,
        target_ratio=target_ratio,
    )
    return result.compacted_text
