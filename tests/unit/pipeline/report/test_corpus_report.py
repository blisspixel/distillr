"""Tests for corpus-first report material and orchestration."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from distill.config import DistillConfig
from distill.llm.cost_policy import CostPolicyError
from distill.pipeline.costs import CostTracker
from distill.pipeline.report import corpus
from distill.pipeline.report.corpus import build_corpus_dossier, run_corpus_report


def test_build_corpus_dossier_prioritizes_synthesis_and_focus():
    dossier = build_corpus_dossier(
        "ai",
        [
            ("z-insights", "detail"),
            ("topic-synthesis-ai", "summary"),
            ("blank", "  "),
        ],
        focus="risk",
    )
    assert "Research focus: risk" in dossier
    assert dossier.index("topic-synthesis-ai") < dossier.index("z-insights")


def test_build_corpus_dossier_empty_and_invalid_limit():
    assert build_corpus_dossier("ai", []) == ""
    with pytest.raises(ValueError, match="positive"):
        build_corpus_dossier("ai", [("a", "b")], max_chars=0)


def test_build_corpus_dossier_truncates_first_large_document():
    dossier = build_corpus_dossier("ai", [("one", "x" * 1_000)], max_chars=400)
    assert "Corpus material omitted" in dossier
    assert len(dossier) <= 400


def test_build_corpus_dossier_marks_later_omissions():
    dossier = build_corpus_dossier(
        "ai",
        [("topic-synthesis", "short"), ("details", "x" * 1_000)],
        max_chars=500,
    )
    assert "short" in dossier
    assert "Corpus material omitted" in dossier


def test_gather_corpus_dossier_delegates(monkeypatch, tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    gather = MagicMock(return_value=[("topic-synthesis-ai", "evidence")])
    monkeypatch.setattr(corpus, "gather_corpus_documents", gather)
    result = corpus.gather_corpus_dossier("ai", config, "topic", None, "focus")
    assert "evidence" in result
    gather.assert_called_once_with("ai", config, "topic", None)


def test_run_corpus_report_refuses_metered_route_under_no_metered(monkeypatch, tmp_path):
    monkeypatch.setenv("DISTILL_PROVIDER", "xai")
    config = DistillConfig(
        distill_output_dir=tmp_path / "library",
        distill_cost_mode="no-metered",
    )
    with pytest.raises(CostPolicyError):
        run_corpus_report("ai", config, tracker=CostTracker())


def test_run_corpus_report_returns_none_without_artifacts(monkeypatch, tmp_path):
    monkeypatch.setenv("DISTILL_PROVIDER", "xai")
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    monkeypatch.setattr(corpus, "gather_corpus_dossier", lambda *args, **kwargs: "")
    assert run_corpus_report("ai", config, tracker=CostTracker()) is None


def test_run_corpus_report_calls_ordered_writer(monkeypatch, tmp_path):
    monkeypatch.setenv("DISTILL_PROVIDER", "xai")
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    monkeypatch.setattr(corpus, "gather_corpus_dossier", lambda *args, **kwargs: "evidence")
    sequential = MagicMock(return_value="# report")
    monkeypatch.setattr("distill.pipeline.report.accordion.run_sequential_report", sequential)

    result = run_corpus_report(
        "ai",
        config,
        focus="risk",
        sections=["evidence_map"],
        tracker=CostTracker(),
        skip_qa=True,
    )

    assert result == "# report"
    call = sequential.call_args.kwargs
    assert call["section_profile"] == "corpus-research"
    assert call["dossier"] == "evidence"
    assert call["skip_qa"] is True
    assert call["report_title"] == "Research Report"
    assert call["writer_role"].startswith("a senior research analyst")
    assert call["show_video_coverage"] is False
