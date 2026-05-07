"""Unit tests for distill.doctor.quality_gate — eval suite runner."""

from __future__ import annotations

import asyncio
from pathlib import Path

from distill.doctor.quality_gate import EvalResult, load_baselines, run_eval_suite


class TestEvalResult:
    """Tests for EvalResult dataclass."""

    def test_eval_result_creation(self) -> None:
        result = EvalResult(
            model="qwen3.5:27b",
            workload="analysis",
            score=0.85,
            passed=True,
            details={"key": "value"},
        )
        assert result.model == "qwen3.5:27b"
        assert result.workload == "analysis"
        assert result.score == 0.85
        assert result.passed is True
        assert result.details == {"key": "value"}

    def test_eval_result_default_details(self) -> None:
        result = EvalResult(model="test", workload="test", score=1.0, passed=True)
        assert result.details == {}


class TestLoadBaselines:
    """Tests for load_baselines function."""

    def test_loads_from_existing_directory(self, tmp_path: Path) -> None:
        (tmp_path / "paper_analysis_amem.md").write_text("# Baseline", encoding="utf-8")
        (tmp_path / "paper_analysis_other.md").write_text("# Other", encoding="utf-8")
        baselines = load_baselines(tmp_path)
        assert len(baselines) == 2
        assert "paper_analysis_amem" in baselines
        assert "paper_analysis_other" in baselines

    def test_returns_empty_for_missing_directory(self, tmp_path: Path) -> None:
        baselines = load_baselines(tmp_path / "nonexistent")
        assert baselines == {}

    def test_ignores_gitkeep(self, tmp_path: Path) -> None:
        (tmp_path / ".gitkeep").write_text("", encoding="utf-8")
        (tmp_path / "baseline.md").write_text("# Content", encoding="utf-8")
        baselines = load_baselines(tmp_path)
        assert len(baselines) == 1
        assert "baseline" in baselines


class TestRunEvalSuite:
    """Tests for the run_eval_suite function."""

    def test_with_high_quality_output(self, tmp_path: Path, monkeypatch) -> None:
        # Use a simple baseline so concept coverage doesn't drag score down
        baselines_dir = tmp_path / "baselines"
        baselines_dir.mkdir()
        (baselines_dir / "paper_analysis_simple.md").write_text(
            "## Key Findings\n- GPT-4 achieves SOTA on NLP benchmarks.\n"
            "## Methods\n- Uses deep learning.\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("distill.doctor.quality_gate.BASELINES_DIR", baselines_dir)
        output = (
            "## Key Findings\n- GPT-4 achieves SOTA on NLP benchmarks.\n"
            "## Methods\n- Novel approach using deep learning.\n"
            "## Limits\n- Limited to English text only.\n"
            "## Open Questions\n- How does it scale?\n" + " ".join(["additional"] * 200)
        )
        result = asyncio.run(run_eval_suite("qwen3.5:27b", "analysis", test_output=output))
        assert result.passed is True
        assert result.score >= 0.80
        assert result.model == "qwen3.5:27b"
        assert result.workload == "analysis"
        assert "dimensions" in result.details

    def test_with_low_quality_output(self) -> None:
        output = "Short text."
        result = asyncio.run(run_eval_suite("tiny-model", "analysis", test_output=output))
        assert result.passed is False
        assert result.score < 0.80

    def test_without_output_and_no_baselines(self, tmp_path: Path, monkeypatch) -> None:
        # Patch BASELINES_DIR to an empty directory
        monkeypatch.setattr("distill.doctor.quality_gate.BASELINES_DIR", tmp_path / "empty")
        result = asyncio.run(run_eval_suite("qwen3.5:27b", "analysis"))
        assert result.passed is True
        assert result.details["status"] == "no_baselines"

    def test_without_output_but_with_baselines(self, tmp_path: Path, monkeypatch) -> None:
        # Create a baselines directory with content
        baselines_dir = tmp_path / "baselines"
        baselines_dir.mkdir()
        (baselines_dir / "paper_analysis_amem.md").write_text("# Baseline", encoding="utf-8")
        monkeypatch.setattr("distill.doctor.quality_gate.BASELINES_DIR", baselines_dir)
        result = asyncio.run(run_eval_suite("qwen3.5:27b", "analysis"))
        assert result.passed is False
        assert result.details["status"] == "no_output"
        assert "baselines" in result.details
