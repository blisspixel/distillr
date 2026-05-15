"""Integration test: end-to-end concept playbook pipeline against a fixture corpus.

Drives the full pipeline (extract -> normalize -> merge -> render ->
export -> contradictions) with a mocked LLM, verifying the on-disk
artifacts end up shaped the way agents and `distill health` expect.

This is the test that catches surface-level regressions: file paths,
markdown structure, jsonl row keys, frontmatter content. Unit tests
cover the layers individually; this one wires them together.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from distill.concepts.contradictions import find_contested
from distill.concepts.pipeline import run_concepts
from distill.llm import RouterConfig


class _StubResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.model = "stub-fixture-model"
        self.input_tokens = 100
        self.output_tokens = 50


def _write_paper_insight(topic_dir: Path, paper_id: str, slug: str, title: str) -> None:
    path = topic_dir / "papers" / slug / f"{slug}_Insights.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        f'---\npaper_id: {paper_id}\ntitle: "{title}"\n---\n\n# {title}\n\nBody.\n',
        encoding="utf-8",
    )


@pytest.fixture
def fixture_corpus(tmp_path: Path) -> Path:
    """Seed a 5-paper TKG corpus."""
    topic_dir = tmp_path / "library" / "topics" / "tkg"
    _write_paper_insight(topic_dir, "2604.11544", "romem", "RoMem")
    _write_paper_insight(topic_dir, "2602.12389", "est", "EST")
    _write_paper_insight(topic_dir, "2607.00001", "cid_tkg", "CID-TKG")
    _write_paper_insight(topic_dir, "2509.99001", "skeptic", "Production-Scale Skeptic")
    _write_paper_insight(topic_dir, "2510.05050", "context", "Context Paper")
    return topic_dir


def _fixture_llm_responses() -> list:
    """Hand-crafted LLM responses simulating realistic extraction."""
    return [
        # RoMem: helpful for rotational embeddings + neutral mention of TKG
        [
            {
                "name": "Rotational Embeddings",
                "normalized_name": "rotational embeddings",
                "kind": "technique",
                "polarity": "helpful",
                "claim_excerpt": "Continuous functional rotation beats discrete timestamps.",
                "evidence_type": "empirical_result",
            },
            {
                "name": "Temporal Knowledge Graphs",
                "normalized_name": "temporal knowledge graphs",
                "kind": "architecture",
                "polarity": "neutral",
                "claim_excerpt": "Background: TKGs encode facts with time.",
                "evidence_type": "background",
            },
        ],
        # EST: helpful for rotational embeddings + TKG
        [
            {
                "name": "Rotational Embeddings",
                "normalized_name": "rotational embeddings",
                "kind": "technique",
                "polarity": "helpful",
                "claim_excerpt": "Energy-barrier gate over rotation yields 6.2 MRR gain.",
                "evidence_type": "empirical_result",
            },
            {
                "name": "Temporal Knowledge Graphs",
                "normalized_name": "temporal knowledge graphs",
                "kind": "architecture",
                "polarity": "helpful",
                "claim_excerpt": "TKG modeling is the right framing.",
            },
        ],
        # CID-TKG: helpful for rotational embeddings + TKG
        [
            {
                "name": "Rotational Embeddings",
                "normalized_name": "rotational embeddings",
                "kind": "technique",
                "polarity": "helpful",
                "claim_excerpt": "Rotation-based encodings improve interpolation.",
            },
            {
                "name": "Temporal Knowledge Graphs",
                "normalized_name": "temporal knowledge graphs",
                "kind": "architecture",
                "polarity": "helpful",
            },
        ],
        # Skeptic: harmful for TKG
        [
            {
                "name": "Temporal Knowledge Graphs",
                "normalized_name": "temporal knowledge graphs",
                "kind": "architecture",
                "polarity": "harmful",
                "claim_excerpt": "TKGs fail at production scale; static remains dominant.",
                "evidence_type": "limitation",
            }
        ],
        # Context paper: mentions DeepMind
        [
            {
                "name": "DeepMind",
                "normalized_name": "deepmind",
                "kind": "organization",
                "polarity": "neutral",
                "claim_excerpt": "DeepMind published prior work on this area.",
            }
        ],
    ]


def test_end_to_end_pipeline_produces_expected_artifacts(fixture_corpus: Path) -> None:
    """Drive run_concepts over a 5-paper corpus; assert the playbook shape."""
    queue = list(_fixture_llm_responses())

    def _llm_stub(*_args, **_kwargs):
        return _StubResponse(json.dumps(queue.pop(0) if queue else []))

    with patch("distill.concepts.extract.llm_call", side_effect=_llm_stub):
        summary = run_concepts(
            "tkg",
            fixture_corpus,
            rc=RouterConfig(),
            threshold=3,
            now_iso="2026-05-15T10:00:00Z",
        )

    # 5 insights scanned + extracted; 5 papers yielded mentions
    assert summary.insights_scanned == 5
    assert summary.insights_extracted == 5
    # Rotational embeddings (3 sources) crosses threshold
    # TKG (4 sources: 3 helpful + 1 harmful) crosses threshold and is contested
    # DeepMind (1 source) below threshold -> filtered out
    assert summary.concepts_written == 2  # rotational embedding + TKG
    assert summary.entities_written == 0  # deepmind filtered (only 1 source)

    # On-disk artifacts
    assert (fixture_corpus / "concepts" / "rotational_embedding.md").exists()
    assert (fixture_corpus / "concepts" / "temporal_knowledge_graph.md").exists()
    assert not (fixture_corpus / "entities" / "deepmind.md").exists()

    # JSONL exports
    concepts_rows = [
        json.loads(line)
        for line in (fixture_corpus / "concepts.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(concepts_rows) == 2
    names = {r["name"] for r in concepts_rows}
    assert "Rotational Embeddings" in names
    assert "Temporal Knowledge Graphs" in names

    # TKG is contested (3 helpful + 1 harmful = both polarities present)
    tkg_row = next(r for r in concepts_rows if r["name"] == "Temporal Knowledge Graphs")
    assert tkg_row["contested"] is True
    assert tkg_row["helpful_count"] >= 3
    assert tkg_row["harmful_count"] >= 1

    # Rotational embeddings: 3 helpful, no harmful, no contested
    rot_row = next(r for r in concepts_rows if r["name"] == "Rotational Embeddings")
    assert rot_row["contested"] is False
    assert rot_row["helpful_count"] == 3

    # mentions.jsonl audit log
    mentions = (fixture_corpus / ".concepts" / "mentions.jsonl").read_text(encoding="utf-8")
    assert mentions.count("\n") >= 7  # at least 7 mention rows across 5 papers


def test_contradiction_surfacing_finds_contested_concept(fixture_corpus: Path) -> None:
    """After the pipeline, find_contested returns the contested TKG concept."""
    queue = list(_fixture_llm_responses())

    def _llm_stub(*_args, **_kwargs):
        return _StubResponse(json.dumps(queue.pop(0) if queue else []))

    with patch("distill.concepts.extract.llm_call", side_effect=_llm_stub):
        run_concepts(
            "tkg",
            fixture_corpus,
            rc=RouterConfig(),
            threshold=3,
            now_iso="2026-05-15T10:00:00Z",
        )

    contested = find_contested(fixture_corpus)
    assert len(contested) == 1
    assert contested[0].name == "Temporal Knowledge Graphs"
    assert contested[0].helpful_count >= 3
    assert contested[0].harmful_count >= 1


def test_idempotent_no_op_second_run(fixture_corpus: Path) -> None:
    """Second run with no new insights does zero LLM calls and zero writes."""
    queue = list(_fixture_llm_responses())

    def _llm_stub(*_args, **_kwargs):
        return _StubResponse(json.dumps(queue.pop(0) if queue else []))

    with patch("distill.concepts.extract.llm_call", side_effect=_llm_stub):
        run_concepts(
            "tkg",
            fixture_corpus,
            rc=RouterConfig(),
            threshold=3,
            now_iso="2026-05-15T10:00:00Z",
        )

    # Snapshot the concept directory state
    concept_md = (fixture_corpus / "concepts" / "rotational_embedding.md").read_text(
        encoding="utf-8"
    )

    with patch("distill.concepts.extract.llm_call") as mock_llm:
        summary = run_concepts(
            "tkg",
            fixture_corpus,
            rc=RouterConfig(),
            threshold=3,
            now_iso="2026-05-16T10:00:00Z",
        )

    assert mock_llm.call_count == 0
    assert summary.insights_extracted == 0
    assert summary.mentions_added == 0
    # No history entry written
    assert not (fixture_corpus / ".history").exists()
    # File unchanged byte-for-byte
    assert (fixture_corpus / "concepts" / "rotational_embedding.md").read_text(
        encoding="utf-8"
    ) == concept_md


def test_refresh_re_extracts_and_snapshots_unchanged_files(fixture_corpus: Path) -> None:
    """--refresh re-runs extraction; unchanged outputs don't snapshot."""
    queue = list(_fixture_llm_responses())

    def _llm_stub(*_args, **_kwargs):
        return _StubResponse(json.dumps(queue.pop(0) if queue else []))

    with patch("distill.concepts.extract.llm_call", side_effect=_llm_stub):
        run_concepts(
            "tkg",
            fixture_corpus,
            rc=RouterConfig(),
            threshold=3,
            now_iso="2026-05-15T10:00:00Z",
        )

    # Re-run with refresh -- same LLM responses, same merged result
    queue2 = list(_fixture_llm_responses())

    def _llm_stub2(*_args, **_kwargs):
        return _StubResponse(json.dumps(queue2.pop(0) if queue2 else []))

    with patch("distill.concepts.extract.llm_call", side_effect=_llm_stub2) as mock_llm:
        run_concepts(
            "tkg",
            fixture_corpus,
            rc=RouterConfig(),
            threshold=3,
            refresh=True,
            now_iso="2026-05-15T10:00:00Z",  # same timestamp -> identical content
        )

    # Refresh re-extracted all 5
    assert mock_llm.call_count == 5
    # But the content is identical, so no .history snapshots
    assert not (fixture_corpus / ".history").exists()
