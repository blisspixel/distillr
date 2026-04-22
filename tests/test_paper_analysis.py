from distill.config import DistillConfig
from distill.costs import CostTracker
from distill.paper_analysis import analyze_paper, synthesize_papers
from distill.paper_ingest import PaperRecord


def _paper() -> PaperRecord:
    return PaperRecord(
        paper_id="2602.12670v1",
        title='Agent "Memory"',
        abstract="A paper about memory systems.",
        authors=["Alice", "Bob"],
        abs_url="https://arxiv.org/abs/2602.12670v1",
    )


def test_analyze_paper_builds_frontmatter(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    tracker = CostTracker()
    monkeypatch.setattr("distill.paper_analysis._get_client", lambda config: object())
    monkeypatch.setattr(
        "distill.paper_analysis._call_grok",
        lambda client, prompt, model, tracker=None, call_type="", max_tokens=8192, retries=2: (
            "paper body"
        ),
    )

    insights, document = analyze_paper(_paper(), config, tracker=tracker)

    assert 'paper_title: "Agent \\"Memory\\""' in insights
    assert "paper_id: 2602.12670v1" in insights
    assert "analyzed_by: grok-4.20" in insights
    assert "source_mode: abstract_only" in insights
    assert insights.rstrip().endswith("paper body")
    assert "## Abstract" in document


def test_synthesize_papers_writes_output(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    paper_dir = config.paper_dir("papers", "Agent Memory Systems", "2602.12670")
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "insights.md").write_text("# Insight", encoding="utf-8")

    monkeypatch.setattr("distill.paper_analysis._get_client", lambda config: object())
    monkeypatch.setattr(
        "distill.paper_analysis._call_grok",
        lambda client, prompt, model, tracker=None, call_type="", max_tokens=8192, retries=2: (
            "paper synthesis"
        ),
    )

    result = synthesize_papers("papers", config)

    assert result == "paper synthesis"
    assert (config.topic_dir("papers") / "paper_synthesis.md").read_text(
        encoding="utf-8"
    ) == "paper synthesis"
