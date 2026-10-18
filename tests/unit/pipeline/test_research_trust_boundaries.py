import json
from io import StringIO

from rich.console import Console

from distill.commands import _paper_search
from distill.config import DistillConfig
from distill.ingestors.papers.arxiv import PaperRecord
from distill.ingestors.papers.search_receipts import SearchReceipt
from distill.llm.router import LLM_Response
from distill.pipeline import ask, summary_query
from distill.pipeline.citation_refs import artifact_citation_handles, extract_source_citations
from distill.pipeline.paper_shortlist import load_topic_shortlist, save_paper_shortlist
from distill.pipeline.ranking import RankedPaper
from distill.pipeline.search import search_corpus
from distill.pipeline.summary import RunSummary


def _write(config, relative, text):
    path = config.topic_dir("t") / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_retrieval_keeps_source_and_derived_origin_and_excludes_operational_outputs(tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    _write(
        config, "local/note/note_Content.md", "---\ntype: content\n---\n\nTemporal entities source."
    )
    _write(
        config,
        "local/note/note_Insights.md",
        "---\ntype: insights\n---\n\nTemporal entities derived interpretation.",
    )
    _write(config, "local/legacy/insights.md", "Temporal entities legacy interpretation.")
    for relative, kind, source in (
        ("t_Audit.md", "audit", "distill"),
        ("answer.md", "answer", "distill-answer"),
        ("answers/promoted/promoted_Insights.md", "insights", "distill-answer"),
        ("other/moved_Insights.md", "insights", "distill-answer"),
        ("reports/report.md", "report", "distill"),
        ("AGENTS.md", "orientation", "distill"),
        ("local/note/.history/old_Insights.md", "insights", "local"),
    ):
        _write(
            config,
            relative,
            f"---\ntype: {kind}\nsource: {source}\n---\n\nTemporal entities operational content.",
        )
    results = search_corpus(config, "t", "Temporal entities")
    assert {r.path.rsplit("/", 1)[-1]: r.origin for r in results} == {
        "note_Content.md": "source",
        "note_Insights.md": "derived",
        "insights.md": "derived",
    }
    origins = {}
    _, block, _ = ask._gather_sources(config, "t", "Temporal entities", origins=origins)
    assert "Artifact: topics/t/local/note/note_Insights.md\nOrigin: derived" in block
    assert origins["note_Content"] == "source"
    assert "operational content" not in block


def test_legacy_basename_collisions_get_distinct_exact_artifact_handles(tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    _write(config, "local/one/insights.md", "Temporal first source.")
    _write(config, "local/two/insights.md", "Temporal second source.")
    paths = {}
    handles, block, _ = ask._gather_sources(config, "t", "Temporal", paths=paths)
    assert len(set(handles)) == 2
    assert all(handle.startswith("insights_") for handle in handles)
    assert set(paths.values()) == {
        "topics/t/local/one/insights.md",
        "topics/t/local/two/insights.md",
    }
    assert all(f"[{handle}]" in block for handle in handles)
    assert artifact_citation_handles(paths.values()) == {
        path: handle for handle, path in paths.items()
    }


def test_grouped_citations_keep_each_exact_source_and_deduplicate():
    assert extract_source_citations(
        "[source_a, source_b]. [source_a] [Analysis] [source_c,\nsource_b]"
    ) == ["source_a", "source_b", "source_c"]


def test_changed_receipt_during_answer_refuses_publication(tmp_path, monkeypatch):
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    source = _write(config, "local/note/note_Content.md", "Temporal entities evidence.")

    def change(*_a, **_k):
        source.write_text("Changed source.", encoding="utf-8")
        return LLM_Response("Temporal entities exist [note_Content].", 1, 1, "local")

    monkeypatch.setattr(ask, "llm_call", change)
    result = ask.ask_corpus("Temporal entities?", topic="t", config=config)
    assert result.answer_path is None
    assert "changed during" in result.answer_refused_reason
    assert not (config.topic_dir("t") / "answers").exists()


def test_changed_receipt_during_summary_refuses_cache_publication(tmp_path, monkeypatch):
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    source = _write(config, "local/note/note_Content.md", "Temporal entities evidence.")

    def change(*_a, **_k):
        source.write_text("Changed source.", encoding="utf-8")
        return LLM_Response("Temporal entities exist [note_Content].", 1, 1, "local")

    monkeypatch.setattr(summary_query, "llm_call", change)
    result = summary_query.summarize_query(config, "t", "Temporal entities")
    assert result is not None
    assert "changed during" in result.refused_reason
    assert not list(config.library_dir.rglob("summary_cache/*.json"))


def test_partial_discovery_survives_shortlist_and_summary_replay(tmp_path, monkeypatch):
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    config.library_dir.mkdir()
    receipts = (
        SearchReceipt.capture("failed", 0, error="DNS unavailable"),
        SearchReceipt.capture("useful", 1),
    )
    paper = PaperRecord(
        paper_id="2610.00001v2",
        title="Useful",
        abstract="Evidence",
        revision_status="update",
        captured_revisions=("2610.00001v1",),
    )
    ranked = RankedPaper(paper, 1, 1, 1, 1, 1, "useful", "heuristic")
    saved = save_paper_shortlist(
        config,
        topic="t",
        query="topic",
        expansion_queries=["failed", "useful"],
        model="local",
        ranked=[ranked],
        search_receipts=receipts,
    )
    loaded = load_topic_shortlist(config, "t", saved.id)
    assert loaded.search_receipts == receipts
    assert loaded.papers[0].paper_id == "2610.00001v2"
    assert loaded.papers[0].revision_status == "update"
    stream = StringIO()
    monkeypatch.setattr(_paper_search, "console", Console(file=stream, color_system=None, width=80))
    summary = RunSummary(command="papers")
    _paper_search.report_search_coverage(loaded.search_receipts, summary)
    assert json.loads(summary.metadata["search_receipts"])[0]["status"] == "failed"
    assert "Incomplete discovery" in stream.getvalue()
    assert "1/2 bounded queries" in stream.getvalue()
    assert len(summary.issues) == 1


def test_revision_report_distinguishes_publication_revision_and_capture_dates(
    tmp_path, monkeypatch
):
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    _write(
        config,
        "papers/p/p_Insights.md",
        "---\nsource: arxiv\npaper_id: 2610.00001v1\ntype: insights\n"
        "updated_at: 2026-10-02T00:00:00Z\ngenerated_at: 2026-10-03T00:00:00Z\n---\nReceipt",
    )
    stream = StringIO()
    monkeypatch.setattr(_paper_search, "console", Console(file=stream, width=200))
    paper = PaperRecord(
        paper_id="2610.00001v2",
        title="Revised",
        abstract="Evidence",
        revision_status="update",
        captured_revisions=("2610.00001v1",),
        published_at="2026-10-01T00:00:00Z",
        updated_at="2026-10-04T00:00:00Z",
    )
    assert _paper_search.report_revision_candidates([paper], topic_dir=config.topic_dir("t"))
    text = stream.getvalue()
    for date in ("2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"):
        assert date in text
    assert "Preview only" in text
