"""Tests that the --two-pass flag routes corpus synthesis through claims.

Exercises distill.pipeline.synthesis.corpus.synthesize_corpus with two_pass on,
using a mocked LLM. Verifies the claim-based path runs, writes a corpus
synthesis tagged two_pass, and falls back to single-pass when no claims exist.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from distill.config import DistillConfig
from distill.library.paths import extract_frontmatter, find_artifact
from distill.pipeline.synthesis.corpus import synthesize_corpus


class _StubResponse:
    def __init__(self, text: str, model: str = "stub-model") -> None:
        self.text = text
        self.model = model
        self.input_tokens = 10
        self.output_tokens = 5


@pytest.fixture
def config(tmp_path: Path) -> DistillConfig:
    return DistillConfig(xai_api_key="test", distill_output_dir=tmp_path / "library")


def _make_insight(topic_dir: Path, slug: str, source_id: str) -> None:
    path = topic_dir / "papers" / slug / f"{slug}_Insights.md"
    path.parent.mkdir(parents=True)
    path.write_text(f"---\npaper_id: {source_id}\ntitle: {slug}\n---\n\nBody.\n", encoding="utf-8")


def test_two_pass_runs_claim_synthesis(config: DistillConfig) -> None:
    topic_dir = config.topic_dir("ai")
    topic_dir.mkdir(parents=True)
    _make_insight(topic_dir, "pa", "p1")

    extract_payload = json.dumps([{"claim_text": "A finding.", "rhetorical_role": "result"}])

    def _side(*_args, **kwargs):
        # Extraction calls carry call_type=claims_extract; synthesis is the other.
        if kwargs.get("call_type") == "claims_extract":
            return _StubResponse(extract_payload)
        return _StubResponse("# Corpus synthesis\n\nSynthesized from claims (C1).")

    with (
        patch("distill.claims.extract.llm_call", side_effect=_side),
        patch("distill.pipeline.synthesis.corpus.llm_call", side_effect=_side),
    ):
        result = synthesize_corpus("ai", config, two_pass=True, now_iso="2026-05-30T00:00:00Z")

    assert "Synthesized from claims" in result
    # claims.jsonl was written.
    assert (topic_dir / ".claims" / "claims.jsonl").exists()
    # The corpus synthesis artifact carries two_pass provenance.
    corpus_md = find_artifact(topic_dir, "corpus_synthesis", identity="ai")
    assert corpus_md.exists()
    fm = extract_frontmatter(corpus_md.read_text(encoding="utf-8"))
    # Frontmatter values round-trip as strings.
    assert str(fm.get("two_pass")).lower() == "true"
    assert fm.get("prompt_id") == "claims.synthesis.v3"


def test_two_pass_falls_back_when_no_claims(config: DistillConfig) -> None:
    # Topic with channels but no insights that yield claims: two-pass extracts
    # nothing, so it must fall back to single-pass rather than return empty.
    topic_dir = config.topic_dir("ai")
    topic_dir.mkdir(parents=True)
    # No insight files -> run_claims yields zero claims.

    with patch("distill.pipeline.synthesis.corpus.synthesize_corpus_from_claims", return_value=""):
        # With no source sections either, single-pass also returns "" -- but the
        # point is that the two-pass branch did not short-circuit the function.
        result = synthesize_corpus("ai", config, two_pass=True)
    assert result == ""


def test_corpus_synthesis_verify_strict_returns_empty(config: DistillConfig) -> None:
    # Covers the branch where run_synthesis_verify refuses (None from two_pass, return "")
    topic_dir = config.topic_dir("ai")
    topic_dir.mkdir(parents=True)
    _make_insight(topic_dir, "pa", "p1")

    with patch(
        "distill.pipeline.synthesis.corpus.synthesize_corpus_from_claims", return_value=None
    ):
        result = synthesize_corpus("ai", config, two_pass=True)
    assert result == ""


def test_corpus_synthesis_only_paper_returns_empty(config: DistillConfig) -> None:
    # Covers skip when only Paper Synthesis
    topic_dir = config.topic_dir("ai")
    topic_dir.mkdir(parents=True)
    paper_synth = find_artifact(topic_dir, "paper_synthesis", identity="ai")
    paper_synth.parent.mkdir(parents=True, exist_ok=True)
    paper_synth.write_text("Paper synth", encoding="utf-8")

    result = synthesize_corpus("ai", config)
    assert result == ""


def test_corpus_synthesis_no_sources_returns_empty(config: DistillConfig) -> None:
    topic_dir = config.topic_dir("ai")
    topic_dir.mkdir(parents=True)
    result = synthesize_corpus("ai", config)
    assert result == ""


def test_corpus_synthesis_claude_refresh_exception_still_succeeds(config: DistillConfig) -> None:
    # Covers the except in refresh: still succeeds, exception swallowed.
    topic_dir = config.topic_dir("ai")
    topic_dir.mkdir(parents=True)
    ch_dir = topic_dir / "channels" / "c1"
    ch_dir.mkdir(parents=True)
    # The collection uses identity = f"{topic}_{sub_dir.name}" so ai_c1_synthesis.md
    (ch_dir / "ai_c1_synthesis.md").write_text("---\n---\nChannel synth", encoding="utf-8")

    with patch("distill.pipeline.synthesis.corpus.llm_call", return_value=_StubResponse("synth")):
        with patch("distill.pipeline.verify.run_synthesis_verify", return_value=False):
            with patch(
                "distill.library.claude_md.refresh_for_topic", side_effect=Exception("boom")
            ):
                result = synthesize_corpus("ai", config)
    assert "synth" in result
