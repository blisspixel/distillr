"""Unit tests for the eval suite runner."""

from __future__ import annotations

from pathlib import Path

from tests.eval.runner import (
    QUALITY_THRESHOLD,
    EvalReport,
    QualityDimension,
    _extract_key_concepts,
    evaluate_paper_analysis,
)


class TestQualityDimension:
    """Tests for QualityDimension dataclass."""

    def test_creation(self) -> None:
        dim = QualityDimension(name="Structure", score=0.75, passed=False, details="3/4")
        assert dim.name == "Structure"
        assert dim.score == 0.75
        assert dim.passed is False
        assert dim.details == "3/4"

    def test_default_details(self) -> None:
        dim = QualityDimension(name="Test", score=1.0, passed=True)
        assert dim.details == ""


class TestEvalReport:
    """Tests for EvalReport dataclass."""

    def test_summary_pass(self) -> None:
        report = EvalReport(
            model="gemma4:26b",
            workload="analysis",
            overall_score=0.90,
            passed=True,
            dimensions=[
                QualityDimension(name="Structure", score=1.0, passed=True, details="4/4"),
                QualityDimension(name="Depth", score=0.80, passed=True, details="160 words"),
            ],
        )
        summary = report.summary()
        assert "PASS" in summary
        assert "90%" in summary
        assert "✓ Structure" in summary
        assert "✓ Depth" in summary

    def test_summary_fail(self) -> None:
        report = EvalReport(
            model="tiny-model",
            workload="analysis",
            overall_score=0.40,
            passed=False,
            dimensions=[
                QualityDimension(name="Structure", score=0.25, passed=False, details="1/4"),
            ],
        )
        summary = report.summary()
        assert "FAIL" in summary
        assert "✗ Structure" in summary


class TestStructuralCompleteness:
    """Tests for the structural completeness dimension."""

    def test_all_sections_present(self) -> None:
        output = (
            "## Key Findings\nSome findings here.\n"
            "## Methods\nSome methods here.\n"
            "## Limits\nSome limits here.\n"
            "## Open Questions\nSome questions here.\n"
        )
        report = evaluate_paper_analysis(output)
        struct_dim = next(d for d in report.dimensions if d.name == "Structure")
        assert struct_dim.score == 1.0
        assert struct_dim.passed is True

    def test_no_sections_present(self) -> None:
        output = "This is just a plain paragraph with no relevant section keywords."
        report = evaluate_paper_analysis(output)
        struct_dim = next(d for d in report.dimensions if d.name == "Structure")
        assert struct_dim.score == 0.0
        assert struct_dim.passed is False

    def test_partial_sections(self) -> None:
        output = "## Key Findings\nSome findings.\n## Methods\nSome methods."
        report = evaluate_paper_analysis(output)
        struct_dim = next(d for d in report.dimensions if d.name == "Structure")
        assert struct_dim.score == 0.5
        assert struct_dim.passed is False


class TestContentDepth:
    """Tests for the content depth dimension."""

    def test_sufficient_depth(self) -> None:
        # 200+ words should score 1.0
        output = " ".join(["word"] * 250)
        report = evaluate_paper_analysis(output)
        depth_dim = next(d for d in report.dimensions if d.name == "Depth")
        assert depth_dim.score == 1.0
        assert depth_dim.passed is True

    def test_insufficient_depth(self) -> None:
        # 50 words = 50/200 = 0.25
        output = " ".join(["word"] * 50)
        report = evaluate_paper_analysis(output)
        depth_dim = next(d for d in report.dimensions if d.name == "Depth")
        assert depth_dim.score == 0.25
        assert depth_dim.passed is False

    def test_exactly_threshold(self) -> None:
        # 160 words = 160/200 = 0.80 = threshold
        output = " ".join(["word"] * 160)
        report = evaluate_paper_analysis(output)
        depth_dim = next(d for d in report.dimensions if d.name == "Depth")
        assert depth_dim.score == 0.80
        assert depth_dim.passed is True


class TestConceptCoverage:
    """Tests for the concept coverage dimension with a baseline."""

    def test_full_coverage(self, tmp_path: Path) -> None:
        baseline_path = tmp_path / "baseline.md"
        baseline_path.write_text(
            "The GPT-4 model uses Transformer Architecture for NLP tasks.",
            encoding="utf-8",
        )
        output = "We tested GPT-4 with Transformer Architecture on NLP benchmarks."
        report = evaluate_paper_analysis(output, baseline_path=baseline_path)
        concept_dim = next(d for d in report.dimensions if d.name == "Concept Coverage")
        assert concept_dim.score == 1.0
        assert concept_dim.passed is True

    def test_partial_coverage(self, tmp_path: Path) -> None:
        baseline_path = tmp_path / "baseline.md"
        baseline_path.write_text(
            "The GPT-4 model uses BERT and Transformer Architecture for NLP.",
            encoding="utf-8",
        )
        # Only mention GPT-4 and NLP, not BERT or Transformer Architecture
        output = "We tested GPT-4 on NLP tasks with a custom model."
        report = evaluate_paper_analysis(output, baseline_path=baseline_path)
        concept_dim = next(d for d in report.dimensions if d.name == "Concept Coverage")
        assert concept_dim.score < 1.0

    def test_no_baseline_skips_coverage(self) -> None:
        output = "## Methods\nSome methods here."
        report = evaluate_paper_analysis(output, baseline_path=None)
        concept_names = [d.name for d in report.dimensions]
        assert "Concept Coverage" not in concept_names


class TestFormatting:
    """Tests for the formatting dimension."""

    def test_headings_and_bullets(self) -> None:
        output = "## Section\n- bullet point\n- another bullet"
        report = evaluate_paper_analysis(output)
        fmt_dim = next(d for d in report.dimensions if d.name == "Formatting")
        assert fmt_dim.score == 1.0
        assert fmt_dim.passed is True

    def test_headings_only(self) -> None:
        output = "## Section\nParagraph text without bullets."
        report = evaluate_paper_analysis(output)
        fmt_dim = next(d for d in report.dimensions if d.name == "Formatting")
        assert fmt_dim.score == 0.5
        assert fmt_dim.passed is True

    def test_no_formatting(self) -> None:
        output = "Plain text with no markdown formatting at all."
        report = evaluate_paper_analysis(output)
        fmt_dim = next(d for d in report.dimensions if d.name == "Formatting")
        assert fmt_dim.score == 0.0
        assert fmt_dim.passed is False


class TestOverallPassFail:
    """Tests for overall pass/fail threshold."""

    def test_high_quality_passes(self) -> None:
        output = (
            "## Key Findings\n- Important finding about the method.\n"
            "## Methods\n- Novel approach using deep learning.\n"
            "## Limits\n- Limited to English text only.\n"
            "## Open Questions\n- How does it scale?\n" + " ".join(["additional"] * 200)
        )
        report = evaluate_paper_analysis(output)
        assert report.passed is True
        assert report.overall_score >= QUALITY_THRESHOLD

    def test_low_quality_fails(self) -> None:
        output = "Short text."
        report = evaluate_paper_analysis(output)
        assert report.passed is False
        assert report.overall_score < QUALITY_THRESHOLD


class TestExtractKeyConcepts:
    """Tests for the _extract_key_concepts helper."""

    def test_extracts_acronyms(self) -> None:
        text = "The GPT-4 model uses NLP and BERT for processing."
        concepts = _extract_key_concepts(text)
        assert "NLP" in concepts
        assert "BERT" in concepts

    def test_extracts_capitalized_phrases(self) -> None:
        text = "We applied Transformer Architecture for Natural Language Processing tasks."
        concepts = _extract_key_concepts(text)
        assert "Transformer Architecture" in concepts
        assert "Natural Language Processing" in concepts

    def test_filters_short_concepts(self) -> None:
        text = "A B CD EF are too short."
        concepts = _extract_key_concepts(text)
        # Single letters and 2-char items should be filtered
        assert "A" not in concepts
        assert "B" not in concepts
        assert "CD" not in concepts
