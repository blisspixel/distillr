"""CLI wiring tests for corpus-aware dedup in discover and papers.

Searched candidates the topic already contains must be dropped before the
rerank (the dogfooded F5 failure: discover kept re-suggesting ingested
items), and an all-duplicates result is a clean converged no-op, not an
error. Only the external boundary (query-gen, search fan-out, rerank,
ingest) is mocked; the ingested-identity walk runs against real files.
"""

import pytest
from typer.testing import CliRunner

from distill import _cli_impl, cli
from distill.commands import papers as _papers
from distill.config import DistillConfig
from distill.ingestors.papers.arxiv import PaperRecord
from distill.ingestors.youtube.discovery import VideoInfo
from distill.pipeline.discovery import RankedDiscoverItem

runner = CliRunner()


@pytest.fixture
def mock_config(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "library")
    monkeypatch.setattr(_cli_impl, "get_config", lambda: config)
    monkeypatch.setattr(_papers, "get_config", lambda: config)
    return config


def _seed_ingested(config, topic: str, *, paper_id: str = "", video_id: str = ""):
    """Write minimal real _Insights.md files so the identity walk finds them."""
    topic_dir = config.topic_dir(topic)
    if paper_id:
        path = topic_dir / "papers" / "seeded_paper" / "seeded_Insights.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'---\npaper_id: "{paper_id}"\n---\n\nx\n', encoding="utf-8")
    if video_id:
        path = topic_dir / "channels" / "c" / "videos" / "v" / "seeded_Insights.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'---\nvideo_id: "{video_id}"\n---\n\nx\n', encoding="utf-8")


def _ranked_paper(paper: PaperRecord, score: float = 0.9) -> RankedDiscoverItem:
    return RankedDiscoverItem(
        kind="paper",
        identifier=paper.paper_id,
        title=paper.title,
        subtitle="A",
        date="2026-01-01",
        final_score=score,
        goal_fit=score,
        depth_score=score,
        complementarity_score=score,
        rationale="r",
        paper=paper,
    )


def test_discover_drops_already_ingested_candidates_before_rerank(mock_config, monkeypatch):
    _seed_ingested(mock_config, "t", paper_id="2601.00001v1", video_id="vOld")
    p_old = PaperRecord(paper_id="2601.00001v2", title="Old", abstract="a")  # v-bumped dup
    p_new = PaperRecord(paper_id="2601.00002v1", title="New", abstract="a")
    v_old = VideoInfo("vOld", "Old", "20260101", 600, "u")
    v_new = VideoInfo("vNew", "New", "20260102", 600, "u")

    monkeypatch.setattr(_cli_impl, "_discover_generate_queries", lambda *a, **k: (["q"], ["q"]))
    monkeypatch.setattr(_cli_impl, "search_arxiv_multi", lambda *a, **k: [p_old, p_new])
    monkeypatch.setattr(_cli_impl, "_discover_fetch_videos", lambda *a, **k: [v_old, v_new])
    rerank_seen = {}

    def fake_rerank(goal, papers, videos, sites, config, tracker):
        rerank_seen["papers"] = papers
        rerank_seen["videos"] = videos
        return [_ranked_paper(p) for p in papers]

    monkeypatch.setattr(_cli_impl, "_discover_rerank", fake_rerank)
    monkeypatch.setattr(_cli_impl, "_discover_ingest_set", lambda **k: None)

    result = runner.invoke(cli.app, ["discover", "goal", "--topic", "t", "--yes"])

    assert result.exit_code == 0, result.output
    assert "Excluded 2 candidate(s) already in 't'" in result.output
    # The rerank prompt never saw the duplicates: fewer tokens, no re-suggestion.
    assert [p.paper_id for p in rerank_seen["papers"]] == ["2601.00002v1"]
    assert [v.video_id for v in rerank_seen["videos"]] == ["vNew"]


def test_discover_all_duplicates_is_a_converged_noop_not_an_error(mock_config, monkeypatch):
    _seed_ingested(mock_config, "t", paper_id="2601.00001v1", video_id="vOld")

    monkeypatch.setattr(_cli_impl, "_discover_generate_queries", lambda *a, **k: (["q"], ["q"]))
    monkeypatch.setattr(
        _cli_impl,
        "search_arxiv_multi",
        lambda *a, **k: [PaperRecord(paper_id="2601.00001v1", title="Old", abstract="a")],
    )
    monkeypatch.setattr(
        _cli_impl,
        "_discover_fetch_videos",
        lambda *a, **k: [VideoInfo("vOld", "Old", "20260101", 600, "u")],
    )
    rerank_called = {"yes": False}
    monkeypatch.setattr(
        _cli_impl,
        "_discover_rerank",
        lambda *a, **k: rerank_called.__setitem__("yes", True) or [],
    )

    result = runner.invoke(cli.app, ["discover", "goal", "--topic", "t", "--yes"])

    assert result.exit_code == 0, result.output
    assert "Corpus is current" in result.output
    assert rerank_called["yes"] is False  # no rerank spend on a converged corpus


def test_papers_drops_already_ingested_before_rerank(mock_config, monkeypatch):
    from distill.pipeline.ranking import RankedPaper

    _seed_ingested(mock_config, "t", paper_id="2601.00001v1")
    p_old = PaperRecord(paper_id="2601.00001v1", title="Old", abstract="a")
    p_new = PaperRecord(paper_id="2601.00002v1", title="New", abstract="a")

    monkeypatch.setattr(_papers, "_expand_paper_queries", lambda q, **k: [q])
    monkeypatch.setattr(_papers, "search_arxiv_papers", lambda *a, **k: [p_old, p_new])
    rerank_seen = {}

    def fake_rerank_papers(query, candidates, config, **kwargs):
        rerank_seen["candidates"] = candidates
        return [
            RankedPaper(
                paper=p,
                final_score=0.9,
                relevance_score=0.9,
                depth_score=0.9,
                novelty_score=0.9,
                credibility_score=0.9,
                rationale="r",
                selected_by="llm",
            )
            for p in candidates
        ]

    monkeypatch.setattr(_papers, "rerank_papers", fake_rerank_papers)

    result = runner.invoke(
        cli.app, ["papers", "query", "--topic", "t", "--limit", "2", "--preview"]
    )

    assert result.exit_code == 0, result.output
    assert "Excluded 1 paper(s) already in 't'" in result.output
    assert [p.paper_id for p in rerank_seen["candidates"]] == ["2601.00002v1"]


def test_papers_all_duplicates_is_a_converged_noop(mock_config, monkeypatch):
    _seed_ingested(mock_config, "t", paper_id="2601.00001v1")

    monkeypatch.setattr(_papers, "_expand_paper_queries", lambda q, **k: [q])
    monkeypatch.setattr(
        _papers,
        "search_arxiv_papers",
        lambda *a, **k: [PaperRecord(paper_id="2601.00001v1", title="Old", abstract="a")],
    )
    rerank_called = {"yes": False}
    monkeypatch.setattr(
        _papers,
        "rerank_papers",
        lambda *a, **k: rerank_called.__setitem__("yes", True) or [],
    )

    result = runner.invoke(cli.app, ["papers", "query", "--topic", "t"])

    assert result.exit_code == 0, result.output
    assert "Corpus is current" in result.output
    assert rerank_called["yes"] is False
