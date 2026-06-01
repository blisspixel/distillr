"""Deterministic quality scoring for the model eval.

Pure functions, no IO, no LLM. Scores an analysis output on four dimensions
against a fixture's golden expectations, and blends in an optional *advisory*
LLM-judge score under a capped weight. The composite and any threshold decision
that consumes it are deterministic by construction (the judge only contributes a
bounded fraction) — consistent with the "LLM proposes, Python decides" invariant.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

__all__ = [
    "DimensionScore",
    "QualityScore",
    "extract_key_concepts",
    "score_output",
]

# Advisory LLM-judge weight in the composite. Capped well below 0.5 so the
# deterministic dimensions always dominate the decision.
JUDGE_WEIGHT: float = 0.30


@dataclass(frozen=True)
class DimensionScore:
    name: str
    score: float  # 0.0 - 1.0
    detail: str = ""


@dataclass(frozen=True)
class QualityScore:
    """Per-output quality: deterministic dimensions + optional advisory judge."""

    dimensions: list[DimensionScore] = field(default_factory=list)
    deterministic: float = 0.0
    judge: float | None = None
    composite: float = 0.0


def extract_key_concepts(text: str) -> set[str]:
    """Extract candidate key concepts — acronyms and capitalized multi-word terms."""
    concepts: set[str] = set()
    concepts.update(re.findall(r"\b[A-Z][A-Z0-9]{1,}(?:-[A-Z0-9]+)*\b", text))
    concepts.update(re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", text))
    return {c for c in concepts if len(c) >= 3}


def _structure_score(output: str, expected_sections: Sequence[str]) -> DimensionScore:
    if not expected_sections:
        return DimensionScore("Structure", 1.0, "no expected sections")
    lower = output.lower()
    found = sum(1 for s in expected_sections if s.lower() in lower)
    return DimensionScore(
        "Structure", found / len(expected_sections), f"{found}/{len(expected_sections)} sections"
    )


def _depth_score(output: str, min_words: int) -> DimensionScore:
    words = len(output.split())
    target = max(1, min_words)
    return DimensionScore("Depth", min(1.0, words / target), f"{words} words")


def _coverage_score(output: str, golden_concepts: Sequence[str]) -> DimensionScore:
    golden = {c.lower() for c in golden_concepts}
    if not golden:
        return DimensionScore("Concept coverage", 1.0, "no golden concepts")
    found_terms = {c.lower() for c in extract_key_concepts(output)}
    output_lower = output.lower()
    # A golden concept counts as covered if it appears as an extracted term or as a
    # substring of the output (tolerates phrasing the extractor misses).
    hits = sum(1 for g in golden if g in found_terms or g in output_lower)
    return DimensionScore("Concept coverage", hits / len(golden), f"{hits}/{len(golden)} concepts")


def _formatting_score(output: str) -> DimensionScore:
    has_headings = "##" in output
    has_bullets = "- " in output or "* " in output
    score = (0.5 if has_headings else 0.0) + (0.5 if has_bullets else 0.0)
    label = "headings" if has_headings else "no headings"
    if has_bullets:
        label += " + bullets"
    return DimensionScore("Formatting", score, label)


def score_output(
    output: str,
    *,
    expected_sections: Sequence[str] = (),
    golden_concepts: Sequence[str] = (),
    min_words: int = 200,
    judge: float | None = None,
) -> QualityScore:
    """Score one analysis output. ``judge`` is an optional 0-1 advisory score.

    Deterministic = mean of the four dimensions. Composite blends in the judge at
    ``JUDGE_WEIGHT`` when present, else equals the deterministic score.
    """
    dims = [
        _structure_score(output, expected_sections),
        _depth_score(output, min_words),
        _coverage_score(output, golden_concepts),
        _formatting_score(output),
    ]
    deterministic = sum(d.score for d in dims) / len(dims)
    if judge is None:
        composite = deterministic
    else:
        composite = (1.0 - JUDGE_WEIGHT) * deterministic + JUDGE_WEIGHT * judge
    return QualityScore(
        dimensions=dims,
        deterministic=deterministic,
        judge=judge,
        composite=composite,
    )
