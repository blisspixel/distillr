"""Eval suite runner — compares local model output against cloud baselines.

Usage:
    python -m tests.eval.runner --model gemma4:26b --workload analysis

Or via CLI:
    distill doctor --eval --model gemma4:26b
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

BASELINES_DIR = Path(__file__).parent / "baselines"
QUALITY_THRESHOLD = 0.80  # 80% of cloud baseline


@dataclass
class QualityDimension:
    """A single quality measurement."""

    name: str
    score: float  # 0.0 - 1.0
    passed: bool
    details: str = ""


@dataclass
class EvalReport:
    """Full eval report for a model-workload combination."""

    model: str
    workload: str
    overall_score: float
    passed: bool
    dimensions: list[QualityDimension] = field(default_factory=list)

    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        lines = [f"Eval: {self.model} / {self.workload} — {status} ({self.overall_score:.0%})"]
        for dim in self.dimensions:
            mark = "✓" if dim.passed else "✗"
            lines.append(f"  {mark} {dim.name}: {dim.score:.0%} {dim.details}")
        return "\n".join(lines)


def evaluate_paper_analysis(output: str, baseline_path: Path | None = None) -> EvalReport:
    """Evaluate a paper analysis output against quality dimensions.

    Dimensions:
    1. Structural completeness — has expected sections (Key Findings, Methods, Limits, etc.)
    2. Content depth — word count per section relative to baseline
    3. Key concept coverage — named entities and techniques mentioned
    4. Formatting — proper markdown structure
    """
    dimensions: list[QualityDimension] = []

    # Dimension 1: Structural completeness
    expected_sections = ["finding", "method", "limit", "question"]
    sections_found = sum(1 for s in expected_sections if s in output.lower())
    struct_score = sections_found / len(expected_sections)
    dimensions.append(
        QualityDimension(
            name="Structure",
            score=struct_score,
            passed=struct_score >= QUALITY_THRESHOLD,
            details=f"{sections_found}/{len(expected_sections)} sections",
        )
    )

    # Dimension 2: Content depth (word count)
    word_count = len(output.split())
    # A good paper analysis should be at least 200 words
    depth_score = min(1.0, word_count / 200)
    dimensions.append(
        QualityDimension(
            name="Depth",
            score=depth_score,
            passed=depth_score >= QUALITY_THRESHOLD,
            details=f"{word_count} words",
        )
    )

    # Dimension 3: Key concept coverage (if baseline provided)
    if baseline_path and baseline_path.exists():
        baseline = baseline_path.read_text(encoding="utf-8")
        baseline_concepts = _extract_key_concepts(baseline)
        output_concepts = _extract_key_concepts(output)
        if baseline_concepts:
            overlap = len(baseline_concepts & output_concepts) / len(baseline_concepts)
        else:
            overlap = 1.0
        dimensions.append(
            QualityDimension(
                name="Concept Coverage",
                score=overlap,
                passed=overlap >= QUALITY_THRESHOLD,
                details=f"{len(baseline_concepts & output_concepts)}/{len(baseline_concepts)} concepts",
            )
        )

    # Dimension 4: Formatting (markdown structure)
    has_headings = "##" in output or "###" in output
    has_bullets = "- " in output or "* " in output
    format_score = (1.0 if has_headings else 0.0) * 0.5 + (1.0 if has_bullets else 0.0) * 0.5
    dimensions.append(
        QualityDimension(
            name="Formatting",
            score=format_score,
            passed=format_score >= 0.5,
            details="headings" + (" + bullets" if has_bullets else ""),
        )
    )

    # Overall score
    overall = sum(d.score for d in dimensions) / len(dimensions) if dimensions else 0.0
    passed = overall >= QUALITY_THRESHOLD

    return EvalReport(
        model="local",
        workload="analysis",
        overall_score=overall,
        passed=passed,
        dimensions=dimensions,
    )


def _extract_key_concepts(text: str) -> set[str]:
    """Extract key concepts (capitalized terms, technical terms) from text."""
    concepts: set[str] = set()
    # Acronyms
    concepts.update(re.findall(r"\b[A-Z][A-Z0-9]{1,}(?:-[A-Z0-9]+)*\b", text))
    # Capitalized phrases (2+ words)
    concepts.update(re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", text))
    return {c for c in concepts if len(c) >= 3}
