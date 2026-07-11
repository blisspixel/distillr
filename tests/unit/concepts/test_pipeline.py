"""End-to-end pipeline tests for distill.concepts.pipeline.

Exercises the orchestrator against a synthetic on-disk insight corpus
with a mocked LLM. Confirms idempotence, refresh behavior, threshold
filtering, and .history snapshotting at the full-pipeline level.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from distill.concepts.pipeline import discover_insights, run_concepts
from distill.llm import RouterConfig
from distill.pipeline.costs import BudgetExceededError, CostTracker


def _make_insight(
    topic_dir: Path,
    *,
    source_type: str,
    slug: str,
    source_id: str,
    title: str = "Sample",
    frontmatter_id_key: str = "paper_id",
) -> Path:
    """Write a fixture _Insights.md under topic_dir/<source_type>/<slug>/."""
    path = topic_dir / source_type / slug / f"{slug}_Insights.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        f"""---
{frontmatter_id_key}: {source_id}
title: "{title}"
---

# {title}

Body of the insight here.
""",
        encoding="utf-8",
    )
    return path


class _StubResponse:
    def __init__(self, text: str, model: str = "stub-model") -> None:
        self.text = text
        self.model = model
        self.input_tokens = 10
        self.output_tokens = 5


def _llm_responses_for_corpus(*responses):
    """Return a side_effect callable that yields the given JSON responses in order."""
    queue = list(responses)

    def _side_effect(*_args, **_kwargs):
        if not queue:
            return _StubResponse("[]")
        return _StubResponse(json.dumps(queue.pop(0)))

    return _side_effect


@pytest.fixture
def rc() -> RouterConfig:
    return RouterConfig()


class TestDiscoverInsights:
    def test_finds_papers_videos_sites(self, tmp_path: Path) -> None:
        _make_insight(tmp_path, source_type="papers", slug="paper_a", source_id="2604.11544")
        _make_insight(
            tmp_path,
            source_type="sites",
            slug="site_a",
            source_id="abc",
            frontmatter_id_key="page_id",
        )
        # Note: even if frontmatter says page_id, our discover walks _Insights.md regardless of dir
        refs = discover_insights(tmp_path)
        assert len(refs) == 2
        # Sorted by relative path
        assert all(r.path.exists() for r in refs)

    def test_returns_empty_for_nonexistent_topic(self, tmp_path: Path) -> None:
        assert discover_insights(tmp_path / "missing") == []

    def test_skips_concepts_history_dirs(self, tmp_path: Path) -> None:
        _make_insight(tmp_path, source_type="papers", slug="paper_a", source_id="A")
        # A concept "insights" wouldn't exist in practice, but defensive check anyway
        rogue = tmp_path / "concepts" / "test_Insights.md"
        rogue.parent.mkdir(parents=True)
        rogue.write_text("---\n---\n# rogue\n", encoding="utf-8")
        refs = discover_insights(tmp_path)
        assert len(refs) == 1
        assert "concepts" not in refs[0].artifact_path

    def test_derives_source_id_from_frontmatter(self, tmp_path: Path) -> None:
        _make_insight(
            tmp_path,
            source_type="papers",
            slug="long-slug-but-paper-id-wins",
            source_id="2604.11544",
        )
        refs = discover_insights(tmp_path)
        assert refs[0].source_id == "2604.11544"

    def test_falls_back_to_dir_name_when_no_frontmatter_id(self, tmp_path: Path) -> None:
        path = tmp_path / "papers" / "fallback_slug" / "fallback_slug_Insights.md"
        path.parent.mkdir(parents=True)
        path.write_text("---\ntitle: 'no id'\n---\n# body\n", encoding="utf-8")
        refs = discover_insights(tmp_path)
        assert refs[0].source_id == "fallback_slug"


class TestRunConcepts:
    def _seed_corpus(self, tmp_path: Path) -> Path:
        topic_dir = tmp_path / "topics" / "tkg"
        _make_insight(topic_dir, source_type="papers", slug="paper_a", source_id="A")
        _make_insight(topic_dir, source_type="papers", slug="paper_b", source_id="B")
        _make_insight(topic_dir, source_type="papers", slug="paper_c", source_id="C")
        _make_insight(topic_dir, source_type="papers", slug="paper_d", source_id="D")
        return topic_dir

    def test_empty_topic_returns_zero_summary(self, tmp_path: Path, rc: RouterConfig) -> None:
        summary = run_concepts("empty", tmp_path / "empty", rc=rc, now_iso="2026-05-15T10:00:00Z")
        assert summary.insights_scanned == 0
        assert summary.insights_extracted == 0

    def test_writes_concept_above_threshold(self, tmp_path: Path, rc: RouterConfig) -> None:
        topic_dir = self._seed_corpus(tmp_path)
        responses = [
            [
                {
                    "name": "Rotational Embeddings",
                    "normalized_name": "rotational embeddings",
                    "kind": "technique",
                    "polarity": "helpful",
                    "claim_excerpt": "...",
                }
            ],
            [
                {
                    "name": "Rotational Embeddings",
                    "normalized_name": "rotational embeddings",
                    "kind": "technique",
                    "polarity": "helpful",
                    "claim_excerpt": "...",
                }
            ],
            [
                {
                    "name": "Rotational Embeddings",
                    "normalized_name": "rotational embeddings",
                    "kind": "technique",
                    "polarity": "helpful",
                    "claim_excerpt": "...",
                }
            ],
            [
                {
                    "name": "Single Source Concept",
                    "normalized_name": "single source concept",
                    "kind": "technique",
                    "polarity": "helpful",
                    "claim_excerpt": "...",
                }
            ],
        ]
        with patch(
            "distill.concepts.extract.llm_call", side_effect=_llm_responses_for_corpus(*responses)
        ):
            summary = run_concepts("tkg", topic_dir, rc=rc, now_iso="2026-05-15T10:00:00Z")

        # 3 sources mention "rotational embeddings" -> above threshold of 3
        # 1 source mentions "single source concept" -> below threshold
        assert summary.insights_scanned == 4
        assert summary.insights_extracted == 4
        assert summary.mentions_added == 4
        assert summary.concepts_written == 1
        # Canonicalize strips trailing plural-s, so slug is singular
        assert (topic_dir / "concepts" / "rotational_embedding.md").exists()
        assert not (topic_dir / "concepts" / "single_source_concept.md").exists()

    def test_idempotent_second_run_skips_extraction(self, tmp_path: Path, rc: RouterConfig) -> None:
        topic_dir = self._seed_corpus(tmp_path)
        responses = [
            [{"name": "X", "normalized_name": "x", "kind": "technique", "polarity": "helpful"}]
        ] * 4

        # First run: 4 extractions
        with patch(
            "distill.concepts.extract.llm_call", side_effect=_llm_responses_for_corpus(*responses)
        ):
            first = run_concepts(
                "tkg", topic_dir, rc=rc, threshold=1, now_iso="2026-05-15T10:00:00Z"
            )
        assert first.insights_extracted == 4

        # Second run with no new insights -> zero extractions
        with patch("distill.concepts.extract.llm_call") as mock_llm:
            second = run_concepts(
                "tkg", topic_dir, rc=rc, threshold=1, now_iso="2026-05-15T11:00:00Z"
            )
        assert second.insights_extracted == 0
        assert mock_llm.call_count == 0
        # No notes were rewritten (content unchanged) so no .history entry
        assert not (topic_dir / ".history").exists()

    def test_empty_extractions_are_not_rebilled(self, tmp_path: Path, rc: RouterConfig) -> None:
        # A source whose extraction yields [] (no substantive concepts) writes no
        # mentions.jsonl row. Without the extracted-sources ledger it would be
        # re-extracted -- and re-billed -- on every subsequent run. The ledger
        # records it as processed so the second run does zero LLM calls.
        topic_dir = self._seed_corpus(tmp_path)

        # Empty queue -> _llm_responses_for_corpus returns "[]" for all 4 sources.
        with patch("distill.concepts.extract.llm_call", side_effect=_llm_responses_for_corpus()):
            first = run_concepts(
                "tkg", topic_dir, rc=rc, threshold=1, now_iso="2026-05-15T10:00:00Z"
            )
        assert first.insights_extracted == 4
        assert first.mentions_added == 0
        assert (topic_dir / ".concepts" / "extracted_sources.json").is_file()

        with patch("distill.concepts.extract.llm_call") as mock_llm:
            second = run_concepts(
                "tkg", topic_dir, rc=rc, threshold=1, now_iso="2026-05-15T11:00:00Z"
            )
        assert second.insights_extracted == 0
        assert mock_llm.call_count == 0

    def test_refresh_re_extracts_all_sources(self, tmp_path: Path, rc: RouterConfig) -> None:
        topic_dir = self._seed_corpus(tmp_path)
        responses = [
            [{"name": "X", "normalized_name": "x", "kind": "technique", "polarity": "helpful"}]
        ] * 4

        with patch(
            "distill.concepts.extract.llm_call", side_effect=_llm_responses_for_corpus(*responses)
        ):
            run_concepts("tkg", topic_dir, rc=rc, threshold=1, now_iso="2026-05-15T10:00:00Z")

        responses_again = [
            [{"name": "X", "normalized_name": "x", "kind": "technique", "polarity": "helpful"}]
        ] * 4

        with patch(
            "distill.concepts.extract.llm_call",
            side_effect=_llm_responses_for_corpus(*responses_again),
        ) as mock_llm:
            run_concepts(
                "tkg", topic_dir, rc=rc, threshold=1, refresh=True, now_iso="2026-05-15T11:00:00Z"
            )
        assert mock_llm.call_count == 4

    def test_writes_jsonl_exports(self, tmp_path: Path, rc: RouterConfig) -> None:
        topic_dir = self._seed_corpus(tmp_path)
        responses = [
            [{"name": "X", "normalized_name": "x", "kind": "technique", "polarity": "helpful"}]
        ] * 4

        with patch(
            "distill.concepts.extract.llm_call", side_effect=_llm_responses_for_corpus(*responses)
        ):
            run_concepts("tkg", topic_dir, rc=rc, threshold=1, now_iso="2026-05-15T10:00:00Z")

        c_jsonl = topic_dir / "concepts.jsonl"
        assert c_jsonl.exists()
        rows = [json.loads(line) for line in c_jsonl.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 1
        assert rows[0]["name"] == "X"

    def test_history_entry_on_content_change(self, tmp_path: Path, rc: RouterConfig) -> None:
        topic_dir = self._seed_corpus(tmp_path)

        # First run: 3 helpful mentions
        responses = [
            [{"name": "X", "normalized_name": "x", "kind": "technique", "polarity": "helpful"}],
            [{"name": "X", "normalized_name": "x", "kind": "technique", "polarity": "helpful"}],
            [{"name": "X", "normalized_name": "x", "kind": "technique", "polarity": "helpful"}],
            [],  # paper D extracts nothing
        ]
        with patch(
            "distill.concepts.extract.llm_call", side_effect=_llm_responses_for_corpus(*responses)
        ):
            run_concepts("tkg", topic_dir, rc=rc, threshold=3, now_iso="2026-05-15T10:00:00Z")

        # Add a 5th source that introduces harmful evidence -> note content changes
        _make_insight(topic_dir, source_type="papers", slug="paper_e", source_id="E")
        responses_2 = [
            [{"name": "X", "normalized_name": "x", "kind": "technique", "polarity": "harmful"}]
        ]
        with patch(
            "distill.concepts.extract.llm_call", side_effect=_llm_responses_for_corpus(*responses_2)
        ):
            run_concepts("tkg", topic_dir, rc=rc, threshold=3, now_iso="2026-05-15T11:00:00Z")

        history_dir = topic_dir / ".history" / "x"
        assert history_dir.exists()
        assert len(list(history_dir.iterdir())) == 1

    def test_tolerates_extraction_failure_for_one_insight(
        self, tmp_path: Path, rc: RouterConfig
    ) -> None:
        topic_dir = self._seed_corpus(tmp_path)

        def _side_effect(*_args, **_kwargs):
            _side_effect.calls += 1  # type: ignore[attr-defined]
            if _side_effect.calls == 2:  # type: ignore[attr-defined]
                raise RuntimeError("simulated LLM failure")
            return _StubResponse(
                json.dumps(
                    [
                        {
                            "name": "X",
                            "normalized_name": "x",
                            "kind": "technique",
                            "polarity": "helpful",
                        }
                    ]
                )
            )

        _side_effect.calls = 0  # type: ignore[attr-defined]
        with patch("distill.concepts.extract.llm_call", side_effect=_side_effect):
            summary = run_concepts(
                "tkg", topic_dir, rc=rc, threshold=1, now_iso="2026-05-15T10:00:00Z"
            )

        # 4 attempted, 1 failed -> 3 mentions logged
        assert summary.insights_extracted == 4  # tried all
        assert summary.mentions_added == 3

    def test_budget_crossing_stops_before_later_insights(
        self, tmp_path: Path, rc: RouterConfig
    ) -> None:
        topic_dir = self._seed_corpus(tmp_path)
        tracker = CostTracker(budget=0.0)

        with (
            patch(
                "distill.concepts.extract.llm_call",
                return_value=_StubResponse("[]", model="grok-4.3"),
            ) as mock_llm,
            pytest.raises(BudgetExceededError),
        ):
            run_concepts(
                "tkg",
                topic_dir,
                rc=rc,
                tracker=tracker,
                now_iso="2026-05-15T10:00:00Z",
            )

        assert mock_llm.call_count == 1
        assert len(tracker.entries) == 1
        assert not (topic_dir / ".concepts" / "extracted_sources.json").exists()
