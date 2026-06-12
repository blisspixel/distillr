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
