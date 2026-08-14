"""Tests for local paper citation export."""

import json

from distill.library.citations import (
    CitationRecord,
    collect_paper_citations,
    render_bibtex,
    render_citations,
    render_ris,
)
from distill.library.paths import write_markdown_artifact


def _seed_paper(config, topic="ai", title="Agent Memory Systems", paper_id="2602.12670v1"):
    paper_dir = config.paper_dir(topic, title, paper_id)
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "metadata.json").write_text(
        json.dumps(
            {
                "paper_id": paper_id,
                "title": title,
                "abstract": "A paper about memory systems.",
                "authors": ["Alice Example", "Bob Researcher"],
                "published_at": "2026-02-17T00:00:00Z",
                "updated_at": "2026-02-18T00:00:00Z",
                "categories": ["cs.AI"],
                "doi": "10.5555/agent-memory",
                "abs_url": f"https://arxiv.org/abs/{paper_id}",
                "pdf_url": f"https://arxiv.org/pdf/{paper_id}.pdf",
            }
        ),
        encoding="utf-8",
    )
    write_markdown_artifact(
        paper_dir,
        "paper",
        "# Agent Memory Systems\n",
        frontmatter={
            "title": title,
            "type": "paper",
            "topic": topic,
            "source": "arxiv",
            "source_id": paper_id,
            "paper_id": paper_id,
            "url": f"https://arxiv.org/abs/{paper_id}",
            "date": "2026-02-17T00:00:00Z",
            "authors": ["Alice Example", "Bob Researcher"],
            "categories": ["cs.AI"],
            "doi": "10.5555/agent-memory",
            "pdf_url": f"https://arxiv.org/pdf/{paper_id}.pdf",
        },
    )
    return paper_dir


def _record(path, title="Agent Memory Systems"):
    return CitationRecord(
        topic="ai",
        title=title,
        authors=("Alice Example",),
        year="2026",
        published_at="2026-02-17T00:00:00Z",
        updated_at="",
        paper_id="2602.12670v1",
        doi="10.5555/agent-memory",
        url="https://arxiv.org/abs/2602.12670v1",
        pdf_url="",
        categories=("cs.AI",),
        abstract="",
        path=path,
    )


def test_collect_paper_citations_reads_frontmatter_and_metadata(config):
    paper_dir = _seed_paper(config)

    records = collect_paper_citations(config, "ai")

    assert len(records) == 1
    record = records[0]
    assert record.title == "Agent Memory Systems"
    assert record.authors == ("Alice Example", "Bob Researcher")
    assert record.year == "2026"
    assert record.paper_id == "2602.12670v1"
    assert record.doi == "10.5555/agent-memory"
    assert record.categories == ("cs.AI",)
    assert record.abstract == "A paper about memory systems."
    assert record.path.parent == paper_dir


def test_collect_paper_citations_all_topics(config):
    _seed_paper(config, topic="ai")
    _seed_paper(config, topic="systems", title="Runtime Agents", paper_id="2603.00001v1")

    records = collect_paper_citations(config, "all")

    assert [record.topic for record in records] == ["ai", "systems"]


def test_render_bibtex_exports_arxiv_and_doi_fields(config):
    _seed_paper(config)
    bibtex = render_bibtex(collect_paper_citations(config, "ai"))

    assert "@misc{Example2026260212670v1," in bibtex
    assert "title = {Agent Memory Systems}" in bibtex
    assert "author = {Alice Example and Bob Researcher}" in bibtex
    assert "eprint = {2602.12670v1}" in bibtex
    assert "archivePrefix = {arXiv}" in bibtex
    assert "primaryClass = {cs.AI}" in bibtex
    assert "doi = {10.5555/agent-memory}" in bibtex


def test_render_ris_exports_zotero_readable_fields(config):
    _seed_paper(config)
    ris = render_ris(collect_paper_citations(config, "ai"))

    assert "TY  - JOUR" in ris
    assert "T1  - Agent Memory Systems" in ris
    assert "AU  - Alice Example" in ris
    assert "PY  - 2026" in ris
    assert "DO  - 10.5555/agent-memory" in ris
    assert "M3  - arXiv:2602.12670v1" in ris
    assert "KW  - cs.AI" in ris
    assert "ER  - " in ris


def test_render_citations_rejects_unknown_format():
    try:
        render_citations([], "docx")
    except ValueError as exc:
        assert "bibtex or ris" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_render_bibtex_rejects_missing_record_path(tmp_path):
    missing_path = tmp_path / "missing_Insights.md"

    try:
        render_bibtex([_record(missing_path)])
    except ValueError as exc:
        assert "citation record path does not exist" in str(exc)
        assert str(missing_path) in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_render_ris_rejects_missing_record_path(tmp_path):
    missing_path = tmp_path / "missing_Insights.md"

    try:
        render_ris([_record(missing_path)])
    except ValueError as exc:
        assert "citation record path does not exist" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_collect_skips_topic_without_papers_dir(config):
    """A topic directory that exists but has no papers/ subdir yields no records."""
    config.topic_dir("empty").mkdir(parents=True, exist_ok=True)
    assert collect_paper_citations(config, "empty") == []


def test_collect_skips_empty_paper_dir(config):
    """A paper directory with neither a paper artifact nor metadata is skipped."""
    papers = config.topic_dir("ai") / "papers"
    (papers / "hollow").mkdir(parents=True)
    assert collect_paper_citations(config, "ai") == []


def test_collect_all_topics_missing_root_returns_empty(config):
    """Collecting 'all' with no populated topics returns no records rather than raising."""
    assert collect_paper_citations(config, "all") == []


def test_collect_handles_corrupt_metadata_json(config):
    """A corrupt metadata.json degrades to empty metadata; frontmatter still yields a record."""
    paper_dir = config.paper_dir("ai", "Corrupt", "2604.00001v1")
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "metadata.json").write_text("{not valid json", encoding="utf-8")
    write_markdown_artifact(
        paper_dir,
        "paper",
        "# Corrupt\n",
        frontmatter={
            "title": "Corrupt",
            "type": "paper",
            "paper_id": "2604.00001v1",
            "date": "2026-01-01",
        },
    )

    records = collect_paper_citations(config, "ai")
    assert [record.title for record in records] == ["Corrupt"]


def test_collect_skips_unreadable_paper_markdown(config):
    paper_dir = config.paper_dir("ai", "Broken", "2604.00002v1")
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "metadata.json").write_text(
        '{"title": "Readable Metadata", "paper_id": "2604.00002v1"}',
        encoding="utf-8",
    )
    (paper_dir / "paper.md").write_bytes(b"\xff\xfe")

    records = collect_paper_citations(config, "ai")
    assert [record.title for record in records] == ["Readable Metadata"]


def test_render_citations_dispatches_bibtex_and_ris(tmp_path):
    """render_citations routes to bibtex and ris by format name."""
    existing = tmp_path / "paper_Paper.md"
    existing.write_text("# Paper\n", encoding="utf-8")
    records = [_record(existing)]

    assert "@misc{" in render_citations(records, "bib")
    assert "TY  - JOUR" in render_citations(records, "ris")


def test_render_ris_omits_absent_optional_fields(tmp_path):
    """RIS rendering emits only the fields present on a sparse record."""
    existing = tmp_path / "paper_Paper.md"
    existing.write_text("# Paper\n", encoding="utf-8")
    sparse = CitationRecord(
        topic="ai",
        title="Sparse",
        authors=("Solo Author",),
        year="",
        published_at="",
        updated_at="",
        paper_id="",
        doi="",
        url="",
        pdf_url="",
        categories=(),
        abstract="",
        path=existing,
    )

    ris = render_ris([sparse])
    assert "T1  - Sparse" in ris
    assert "AU  - Solo Author" in ris
    for absent in ("PY  -", "Y1  -", "DO  -", "UR  -", "M3  -", "KW  -", "N2  -"):
        assert absent not in ris


def test_first_text_coerces_non_string_values():
    """_first_text stringifies non-str values and skips blank ones."""
    from distill.library.citations import _first_text

    assert _first_text(None, 123) == "123"
    assert _first_text(None, "", "  kept  ") == "kept"
    assert _first_text() == ""


def test_list_value_normalizes_varied_shapes():
    """_list_value coerces lists, JSON-list strings, plain strings, and scalars."""
    from distill.library.citations import _list_value

    assert _list_value(["a", " b ", ""]) == ["a", "b"]
    assert _list_value("   ") == []
    assert _list_value('["x", "y"]') == ["x", "y"]
    assert _list_value("[not valid json]") == ["[not valid json]"]
    assert _list_value("Alice Example") == ["Alice Example"]
    assert _list_value(123) == ["123"]
