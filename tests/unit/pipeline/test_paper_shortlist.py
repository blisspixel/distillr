"""A saved paper preview reloads the same papers in the same order."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from distill.config import DistillConfig
from distill.ingestors.papers.arxiv import PaperRecord
from distill.pipeline.paper_shortlist import (
    PaperShortlistError,
    load_library_last,
    load_topic_latest,
    load_topic_shortlist,
    save_paper_shortlist,
)
from distill.pipeline.ranking import RankedPaper


def _config(tmp_path: Path) -> DistillConfig:
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    config.library_dir.mkdir(parents=True, exist_ok=True)
    return config


def _paper(paper_id: str, title: str) -> PaperRecord:
    return PaperRecord(
        paper_id=paper_id,
        title=title,
        abstract="abstract",
        authors=["Ada"],
        published_at="2026-01-01T00:00:00Z",
        categories=["cs.AI"],
        abs_url=f"https://arxiv.org/abs/{paper_id}",
    )


def _ranked(paper: PaperRecord, score: float) -> RankedPaper:
    return RankedPaper(
        paper=paper,
        final_score=score,
        relevance_score=score,
        depth_score=0.1,
        novelty_score=0.1,
        credibility_score=0.1,
        rationale="because",
        selected_by="llm",
    )


def test_round_trip_keeps_order_scores_and_pointers(tmp_path: Path) -> None:
    config = _config(tmp_path)
    first = _paper("2607.00001v1", "First")
    second = _paper("2607.00002v2", "Second")
    saved = save_paper_shortlist(
        config,
        topic="tkg",
        query="temporal",
        expansion_queries=["temporal", "graph"],
        model="ollama/gemma4:e4b",
        ranked=[_ranked(first, 0.2), _ranked(second, 0.9)],
    )
    assert len(saved.id) == 12
    loaded = load_topic_shortlist(config, "tkg", saved.id)
    assert [paper.paper_id for paper in loaded.papers] == [first.paper_id, second.paper_id]
    assert loaded.scores == (0.2, 0.9)
    assert load_topic_latest(config, "tkg").id == saved.id
    assert load_library_last(config).id == saved.id
    payload = json.loads(
        (config.topic_dir("tkg") / ".distill" / "shortlists" / f"{saved.id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["papers"][0]["version"] == "1"
    assert payload["papers"][1]["selected_by"] == "llm"


def test_stale_shortlist_refuses_until_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    saved = save_paper_shortlist(
        config,
        topic="tkg",
        query="temporal",
        expansion_queries=["temporal"],
        model="ollama/gemma",
        ranked=[_ranked(_paper("2607.00001v1", "First"), 1.0)],
    )
    path = config.topic_dir("tkg") / ".distill" / "shortlists" / f"{saved.id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["created_at"] = "2020-01-01T00:00:00Z"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PaperShortlistError, match="DISTILL_SHORTLIST_MAX_AGE_HOURS"):
        load_topic_shortlist(config, "tkg", saved.id)

    monkeypatch.setenv("DISTILL_SHORTLIST_ALLOW_STALE", "1")
    assert load_topic_shortlist(config, "tkg", saved.id).papers[0].title == "First"


def test_invalid_timestamp_and_age_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    saved = save_paper_shortlist(
        config,
        topic="tkg",
        query="temporal",
        expansion_queries=[],
        model="local",
        ranked=[_ranked(_paper("2607.00001v1", "First"), 1.0)],
    )
    path = config.topic_dir("tkg") / ".distill" / "shortlists" / f"{saved.id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["papers"][0]["score"] = True
    payload["created_at"] = "not-a-time"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PaperShortlistError, match="timestamp is invalid"):
        load_topic_shortlist(config, "tkg", saved.id)
    monkeypatch.setenv("DISTILL_SHORTLIST_ALLOW_STALE", "1")
    allowed = load_topic_latest(config, "tkg")
    assert allowed.id == saved.id
    assert allowed.scores == (0.0,)

    monkeypatch.delenv("DISTILL_SHORTLIST_ALLOW_STALE", raising=False)
    monkeypatch.setenv("DISTILL_SHORTLIST_MAX_AGE_HOURS", "nope")
    payload["created_at"] = "2020-01-01T00:00:00+00:00"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PaperShortlistError, match="older than"):
        load_topic_shortlist(config, "tkg", saved.id)
    monkeypatch.setenv("DISTILL_SHORTLIST_MAX_AGE_HOURS", "-5")
    with pytest.raises(PaperShortlistError, match="older than"):
        load_topic_shortlist(config, "tkg", saved.id)
    monkeypatch.setenv("DISTILL_SHORTLIST_MAX_AGE_HOURS", "100000")
    payload["created_at"] = "2026-10-01T00:00:00"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_topic_shortlist(config, "tkg", saved.id).id == saved.id


def test_malformed_shortlists_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path)
    saved = save_paper_shortlist(
        config,
        topic="tkg",
        query="temporal",
        expansion_queries=["temporal"],
        model="local",
        ranked=[_ranked(_paper("2607.00001v1", "First"), 0.4)],
    )
    directory = config.topic_dir("tkg") / ".distill" / "shortlists"
    path = directory / f"{saved.id}.json"

    with pytest.raises(PaperShortlistError, match="12 hex"):
        load_topic_shortlist(config, "tkg", "not-an-id")
    with pytest.raises(PaperShortlistError, match="No shortlist"):
        load_topic_shortlist(config, "tkg", "abc123abc123")

    original = path.read_text(encoding="utf-8")
    path.write_text("{", encoding="utf-8")
    with pytest.raises(PaperShortlistError, match="not valid JSON"):
        load_topic_shortlist(config, "tkg", saved.id)
    path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(PaperShortlistError, match="not an object"):
        load_topic_shortlist(config, "tkg", saved.id)

    payload = json.loads(original)
    payload["schema"] = 2
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PaperShortlistError, match="schema"):
        load_topic_shortlist(config, "tkg", saved.id)

    payload = json.loads(original)
    payload["id"] = "abc123abc123"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PaperShortlistError, match="does not match"):
        load_topic_shortlist(config, "tkg", saved.id)

    payload = json.loads(original)
    payload["papers"] = [{"title": "missing id"}]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PaperShortlistError, match="missing an id"):
        load_topic_shortlist(config, "tkg", saved.id)

    payload = json.loads(original)
    payload["papers"] = "nope"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PaperShortlistError, match="papers"):
        load_topic_shortlist(config, "tkg", saved.id)

    payload = json.loads(original)
    payload["papers"] = [{"paper_id": "1", "title": "T", "authors": [1]}]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PaperShortlistError, match="authors"):
        load_topic_shortlist(config, "tkg", saved.id)

    payload = json.loads(original)
    payload["expansion_queries"] = "temporal"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PaperShortlistError, match="expansion_queries"):
        load_topic_shortlist(config, "tkg", saved.id)

    payload = json.loads(original)
    payload["query"] = 3
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PaperShortlistError, match="query"):
        load_topic_shortlist(config, "tkg", saved.id)

    monkeypatch.setattr("distill.pipeline.paper_shortlist._MAX_FILE_BYTES", 4)
    path.write_text(original, encoding="utf-8")
    with pytest.raises(PaperShortlistError, match="too large"):
        load_topic_shortlist(config, "tkg", saved.id)

    monkeypatch.setattr("distill.pipeline.paper_shortlist._MAX_FILE_BYTES", 8_000_000)
    monkeypatch.setattr("distill.pipeline.paper_shortlist._MAX_PAPERS", 0)
    path.write_text(original, encoding="utf-8")
    with pytest.raises(PaperShortlistError, match="too long"):
        load_topic_shortlist(config, "tkg", saved.id)


def test_missing_pointers_explain_what_to_pass(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with pytest.raises(PaperShortlistError, match="no saved paper preview"):
        load_topic_latest(config, "tkg")
    with pytest.raises(PaperShortlistError, match="No saved paper preview"):
        load_library_last(config)
    pointer = config.library_dir / ".distill" / "last-paper-shortlist.json"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text("{}\n", encoding="utf-8")
    with pytest.raises(PaperShortlistError, match="incomplete"):
        load_library_last(config)
