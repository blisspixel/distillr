"""Tests for --rigor on papers/latest and the shared _apply_source_rigor helper."""

from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from distill import _cli_impl, cli
from distill.commands import papers as _papers
from distill.config import DistillConfig
from distill.ingestors.papers.arxiv import PaperRecord
from distill.pipeline.ranking import RankedPaper

runner = CliRunner()


@pytest.fixture
def mock_config(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "library")
    monkeypatch.setattr(_cli_impl, "get_config", lambda: config)
    monkeypatch.setattr(_papers, "get_config", lambda: config)
    return config


def _scored(*scores):
    return [SimpleNamespace(final_score=s) for s in scores]


# ---- _apply_source_rigor (shared helper) -----------------------------------


def test_apply_rigor_off_is_passthrough():
    items = _scored(0.9, 0.1)
    out = _cli_impl._apply_source_rigor(
        items, source="paper", rigor="off", rerank_on=True, limit=10
    )
    assert out == items


def test_apply_rigor_filters_below_threshold():
    # paper strict bar is 0.65 -> drop 0.5 and 0.2, keep 0.9 and 0.7.
    items = _scored(0.9, 0.7, 0.5, 0.2)
    out = _cli_impl._apply_source_rigor(
        items, source="paper", rigor="strict", rerank_on=True, limit=10
    )
    assert [i.final_score for i in out] == [0.9, 0.7]


def test_apply_rigor_caps_at_limit():
    items = _scored(0.9, 0.8, 0.7)
    out = _cli_impl._apply_source_rigor(
        items, source="paper", rigor="loose", rerank_on=True, limit=2
    )
    assert len(out) == 2


def test_apply_rigor_ignored_without_rerank():
    items = _scored(0.9, 0.1)
    out = _cli_impl._apply_source_rigor(
        items, source="video", rigor="strict", rerank_on=False, limit=10
    )
    # Heuristic scores aren't on the rerank scale -> passthrough (a warning is printed).
    assert out == items


# ---- papers --rigor end-to-end (preview path) ------------------------------


def test_papers_rigor_drops_subthreshold_candidates(mock_config, monkeypatch):
    def fake_rerank(query, candidates, config, *, tracker=None, top_n=5, use_llm=True):
        return [
            RankedPaper(
                paper=PaperRecord(paper_id=f"id{i}", title=f"T{i}", abstract="a"),
                final_score=score,
                relevance_score=score,
                depth_score=score,
                novelty_score=score,
                credibility_score=score,
                rationale="r",
                selected_by="llm",
            )
            for i, score in enumerate([0.9, 0.6, 0.4])
        ]

    captured = {}
    monkeypatch.setattr(_papers, "_expand_paper_queries", lambda *a, **k: ["q"])
    monkeypatch.setattr(
        _papers, "search_arxiv_papers", lambda *a, **k: [object(), object(), object()]
    )
    monkeypatch.setattr(_papers, "rerank_papers", fake_rerank)
    monkeypatch.setattr(
        _papers,
        "_display_ranked_papers",
        lambda ranked, **k: captured.__setitem__("ranked", ranked),
    )

    # strict paper bar = 0.65 -> only the 0.9 paper survives.
    result = runner.invoke(
        cli.app,
        ["papers", "q", "--topic", "t", "--no-expand", "--rigor", "strict", "--preview"],
    )
    assert result.exit_code == 0, result.output
    assert [r.final_score for r in captured["ranked"]] == [0.9]
    assert "kept 1/3" in result.output


def test_papers_rejects_unknown_rigor(mock_config):
    result = runner.invoke(cli.app, ["papers", "q", "--rigor", "bogus", "--preview"])
    assert result.exit_code == 1
    assert "Unknown --rigor" in result.output
