"""Deterministic quality scoring for the model eval.

Pure functions, no IO, no LLM. Scores an analysis output on four dimensions
against a fixture's golden expectations. The recommendation is computed from
these scores (see ``report``); the rubric LLM judge (``judge``) is a separate,
reference-guided pairwise signal that affects *confidence*, so "LLM proposes,
Python decides" holds (``docs/invariants.md``).

**Scope caveat — this is a noisy proxy, not a quality oracle.** These dimensions
are cheap *string/length heuristics*: "concept coverage" is substring matching
(it misses paraphrase), "depth" is a word count, "structure"/"formatting" are
substring `##`/`- `. They are gameable by padding and keyword-stuffing and blind
to faithfulness and meaning — a rule impersonating a semantic judgment, the
"brittle proxy metrics" failure mode in ``docs/design/agentic-balance.md``. Their
job is to be a reproducible, key-free *offline guardrail* (the golden gate in CI)
and a weak prior fed to the rubric judge, NOT to be the last word on quality.
Depth is verbosity-resistant — full credit once substantive, then decays for
padding — so length alone can't win, but that only blunts one known bias.
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


@dataclass(frozen=True)
class DimensionScore:
    name: str
    score: float  # 0.0 - 1.0
    detail: str = ""


@dataclass(frozen=True)
class QualityScore:
    """Per-output deterministic quality. ``composite`` == mean of the dimensions."""

    dimensions: list[DimensionScore] = field(default_factory=list)
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
    """Verbosity-resistant: full credit in a sane band, decay for padding.

    Ramps linearly to 1.0 at ``min_words``, holds full credit up to a generous
    ceiling (4x), then decays toward a 0.6 floor so a padded answer cannot beat a
    tight one. Length is a sufficiency signal, not a quality multiplier.
    """
    words = len(output.split())
    target = max(1, min_words)
    if words <= target:
        score = words / target
        return DimensionScore("Depth", score, f"{words} words (<= target)")
    ceiling = 4 * target
    if words <= ceiling:
        return DimensionScore("Depth", 1.0, f"{words} words")
    # Beyond 4x target: decay 1.0 -> 0.6 over the next 4x, then floor.
    over = min(1.0, (words - ceiling) / (4 * target))
    return DimensionScore("Depth", 1.0 - 0.4 * over, f"{words} words (padded)")


def _coverage_score(output: str, golden_concepts: Sequence[str]) -> DimensionScore:
    golden = {c.lower() for c in golden_concepts}
    if not golden:
        return DimensionScore("Concept coverage", 1.0, "no golden concepts")
    found_terms = {c.lower() for c in extract_key_concepts(output)}
    output_lower = output.lower()
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
) -> QualityScore:
    """Score one analysis output. Composite = mean of the four dimensions."""
    dims = [
        _structure_score(output, expected_sections),
        _depth_score(output, min_words),
        _coverage_score(output, golden_concepts),
        _formatting_score(output),
    ]
    composite = sum(d.score for d in dims) / len(dims)
    return QualityScore(dimensions=dims, composite=composite)
