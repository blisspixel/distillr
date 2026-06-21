"""Tests for distill.paper_analysis."""

from unittest.mock import patch

from distill.config import DistillConfig
from distill.ingestors.papers.arxiv import PaperRecord
from distill.library.paths import find_artifact, strip_frontmatter
from distill.llm.router import LLM_Response
from distill.pipeline.analysis.paper import analyze_paper, synthesize_papers
from distill.pipeline.costs import CostTracker


def _fake_llm_call(text: str = "body", model: str = "grok-4.3"):
    def _call(config, workload_tag, prompt, **kwargs):
        return LLM_Response(text=text, input_tokens=10, output_tokens=20, model=model)

    return _call


def _paper() -> PaperRecord:
    return PaperRecord(
        paper_id="2602.12670v1",
        title='Agent "Memory"',
        abstract="A paper about memory systems.",
        authors=["Alice", "Bob"],
        abs_url="https://arxiv.org/abs/2602.12670v1",
    )


def test_analyze_paper_builds_frontmatter(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    tracker = CostTracker()

    with patch("distill.pipeline.analysis.paper.llm_call", _fake_llm_call("paper body")):
        insights, document = analyze_paper(_paper(), config, tracker=tracker)

    assert 'paper_title: "Agent \\"Memory\\""' in insights
    assert "paper_id: 2602.12670v1" in insights
    assert "analyzed_by: grok-4.3" in insights
    assert "source_mode: abstract_only" in insights
    assert insights.rstrip().endswith("paper body")
    assert "## Abstract" in document
    assert len(tracker.entries) == 1
    assert tracker.entries[0].call_type == "paper"


def test_synthesize_papers_writes_output(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    paper_dir = config.paper_dir("papers", "Agent Memory Systems", "2602.12670")
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "insights.md").write_text("# Insight", encoding="utf-8")

    with patch("distill.pipeline.analysis.paper.llm_call", _fake_llm_call("paper synthesis")):
        result = synthesize_papers("papers", config)

    assert result == "paper synthesis"
    output = find_artifact(config.topic_dir("papers"), "paper_synthesis", identity="papers")
    assert output.name == "papers_Paper_Synthesis.md"
    assert strip_frontmatter(output.read_text(encoding="utf-8")) == "paper synthesis"
    assert 'type: "paper-synthesis"' in output.read_text(encoding="utf-8")


def test_synthesize_papers_writes_verify_sidecar(tmp_path):
    """0.13.0: the synthesis is verified against its own inputs (the per-paper
    insights), with a distinct sidecar identity so the three topic-level
    syntheses can't collide."""
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    paper_dir = config.paper_dir("papers", "Agent Memory Systems", "2602.12670")
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "insights.md").write_text("# Insight\nMRR reached 72.6 here.", encoding="utf-8")

    with patch(
        "distill.pipeline.analysis.paper.llm_call",
        _fake_llm_call("The synthesis claims an MRR of 99.9 nowhere in sources."),
    ):
        result = synthesize_papers("papers", config)

    assert result  # warn mode: flagged but written
    sidecar = config.topic_dir("papers") / "papers_paper_synthesis_Verify.json"
    assert sidecar.exists()
    import json as _json

    data = _json.loads(sidecar.read_text(encoding="utf-8"))
    assert any(c["token"] == "99.9" for c in data["unsupported"])


def test_synthesize_papers_refreshes_orientation(tmp_path):
    """Paper-only flows must leave the topic agent-visible.

    The dogfood library caught this: topics built by `distill papers` /
    discover's paper branch had a fresh _Paper_Synthesis.md but no
    CLAUDE.md/AGENTS.md and never appeared in the library index.
    """
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    paper_dir = config.paper_dir("papers", "Agent Memory Systems", "2602.12670")
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "insights.md").write_text("# Insight", encoding="utf-8")

    with patch("distill.pipeline.analysis.paper.llm_call", _fake_llm_call("paper synthesis")):
        synthesize_papers("papers", config)

    topic_dir = config.topic_dir("papers")
    assert (topic_dir / "CLAUDE.md").exists()
    assert (topic_dir / "AGENTS.md").exists()
    library_index = config.library_dir / "CLAUDE.md"
    assert library_index.exists()
    assert "[[papers]]" in library_index.read_text(encoding="utf-8")


def test_analyze_paper_chunks_oversized_document(monkeypatch, tmp_path):
    from distill.pipeline.analysis.chunking import Chunk

    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    monkeypatch.setattr(
        "distill.pipeline.analysis.paper.fetch_paper_pdf_text", lambda url: "big pdf text"
    )
    monkeypatch.setattr(
        "distill.pipeline.analysis.paper.build_paper_document",
        lambda paper, pdf_text: "FULL DOCUMENT",
    )
    # Force the content over the 80%-of-window chunking threshold.
    monkeypatch.setattr("distill.pipeline.analysis.paper.estimate_tokens", lambda text: 900_000)
    monkeypatch.setattr(
        "distill.pipeline.analysis.paper.chunk_content",
        lambda content, window: [
            Chunk(text="FIRST CHUNK", heading_context="", index=0, total_chunks=2)
        ],
    )

    with patch("distill.pipeline.analysis.paper.llm_call", _fake_llm_call("body")):
        insights, document = analyze_paper(_paper(), config)

    # Only the first chunk is analyzed (multi-pass assembly is a later phase).
    assert document == "FIRST CHUNK"
    assert "source_mode: full_pdf" in insights  # pdf text was present


def test_analyze_paper_without_tracker_does_not_crash(monkeypatch, tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    monkeypatch.setattr("distill.pipeline.analysis.paper.fetch_paper_pdf_text", lambda url: "")

    with patch("distill.pipeline.analysis.paper.llm_call", _fake_llm_call("body")):
        insights, _ = analyze_paper(_paper(), config)

    assert "source_mode: abstract_only" in insights


def test_synthesize_papers_missing_dir_returns_empty(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    assert synthesize_papers("never-ingested", config) == ""


def test_synthesize_papers_skips_nondir_and_missing_insights(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    papers_dir = config.papers_dir("papers")
    papers_dir.mkdir(parents=True, exist_ok=True)
    (papers_dir / "stray.txt").write_text("not a paper dir", encoding="utf-8")
    (papers_dir / "emptypaper").mkdir()  # a dir with no insights artifact

    assert synthesize_papers("papers", config) == ""


def test_synthesize_papers_records_spend(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    tracker = CostTracker()
    paper_dir = config.paper_dir("papers", "Agent Memory Systems", "2602.12670")
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "insights.md").write_text("# Insight", encoding="utf-8")

    with patch("distill.pipeline.analysis.paper.llm_call", _fake_llm_call("paper synthesis")):
        synthesize_papers("papers", config, tracker=tracker)

    assert len(tracker.entries) == 1
    assert tracker.entries[0].call_type == "paper_synthesis"


def test_synthesize_papers_strict_verify_refusal_does_not_write(monkeypatch, tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    paper_dir = config.paper_dir("papers", "Agent Memory Systems", "2602.12670")
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "insights.md").write_text("# Insight", encoding="utf-8")
    monkeypatch.setattr(
        "distill.pipeline.verify.run_synthesis_verify", lambda *args, **kwargs: True
    )

    with patch("distill.pipeline.analysis.paper.llm_call", _fake_llm_call("paper synthesis")):
        result = synthesize_papers("papers", config)

    assert result == ""
    output = find_artifact(config.topic_dir("papers"), "paper_synthesis", identity="papers")
    assert not output.exists()


def test_synthesize_papers_tolerates_orientation_refresh_failure(monkeypatch, tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    paper_dir = config.paper_dir("papers", "Agent Memory Systems", "2602.12670")
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "insights.md").write_text("# Insight", encoding="utf-8")

    def _boom(*args, **kwargs):
        raise RuntimeError("orientation refresh failed")

    monkeypatch.setattr("distill.library.claude_md.refresh_for_topic", _boom)

    with patch("distill.pipeline.analysis.paper.llm_call", _fake_llm_call("paper synthesis")):
        result = synthesize_papers("papers", config)

    # The synthesis still returns and is written despite the refresh failure.
    assert result == "paper synthesis"
