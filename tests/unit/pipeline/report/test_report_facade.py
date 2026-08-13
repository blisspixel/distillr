"""Tests for the canonical report profile facade."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from distill.config import DistillConfig
from distill.pipeline.costs import CostTracker
from distill.pipeline.report.facade import run_report
from distill.pipeline.report.profiles import (
    ReportProfileName,
    parse_report_profile,
    profile_requires_gemini,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("corpus", ReportProfileName.CORPUS_REPORT),
        ("corpus_report", ReportProfileName.CORPUS_REPORT),
        ("accordion", ReportProfileName.ACCORDION),
        ("legacy", ReportProfileName.DEEP_RESEARCH),
        (ReportProfileName.DEEP_RESEARCH, ReportProfileName.DEEP_RESEARCH),
    ],
)
def test_parse_report_profile_aliases(value, expected):
    assert parse_report_profile(value) is expected


def test_parse_report_profile_rejects_unknown():
    with pytest.raises(ValueError, match="unknown report profile"):
        parse_report_profile("unknown")


def test_profile_requires_gemini():
    assert not profile_requires_gemini("corpus-report")
    assert profile_requires_gemini("accordion")
    assert profile_requires_gemini("deep-research")


def test_facade_dispatches_corpus(monkeypatch, tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    target = MagicMock(return_value="# corpus")
    monkeypatch.setattr("distill.pipeline.report.corpus.run_corpus_report", target)
    result = run_report("ai", config, tracker=CostTracker())
    assert result == "# corpus"
    target.assert_called_once()


def test_facade_dispatches_accordion(monkeypatch, tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    target = MagicMock(return_value="# accordion")
    monkeypatch.setattr("distill.pipeline.report.accordion.run_accordion_research", target)
    result = run_report(
        "ai",
        config,
        profile="accordion",
        research_only=True,
        tracker=CostTracker(),
    )
    assert result == "# accordion"
    assert target.call_args.kwargs["dossier_only"] is True


def test_facade_dispatches_deep_research(monkeypatch, tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    target = MagicMock(return_value="# deep")
    monkeypatch.setattr("distill.pipeline.report.deep_research.run_deep_research", target)
    result = run_report("ai", config, profile="deep-research", tracker=CostTracker())
    assert result == "# deep"
    target.assert_called_once()


def test_facade_rejects_corpus_research_only(tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    with pytest.raises(ValueError, match="accordion profile"):
        run_report("ai", config, research_only=True, tracker=CostTracker())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"research_only": True},
        {"sections": ["one"]},
        {"skip_qa": True},
    ],
)
def test_facade_rejects_sequential_options_for_deep_research(tmp_path, kwargs):
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    with pytest.raises(ValueError, match="sequential report profiles"):
        run_report(
            "ai",
            config,
            profile="deep-research",
            tracker=CostTracker(),
            **kwargs,
        )
