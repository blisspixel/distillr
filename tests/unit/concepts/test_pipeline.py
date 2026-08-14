"""End-to-end pipeline tests for distill.concepts.pipeline.

Exercises the orchestrator against a synthetic on-disk insight corpus
with a mocked LLM. Confirms idempotence, refresh behavior, threshold
filtering, and .history snapshotting at the full-pipeline level.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

import distill.concepts.notes as notes_mod
import distill.concepts.pipeline as pipeline_mod
from distill.concepts.extract import ExtractionResult
from distill.concepts.pipeline import discover_insights, run_concepts
from distill.concepts.records import ConceptKind, ConceptMention, Polarity
from distill.jsonl import JsonlIntegrityError
from distill.library.insights import derive_source_id
from distill.library.source_ledger import MAX_SOURCE_ID_BYTES, SourceLedgerIntegrityError
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

Rotational Embeddings improve temporal reasoning.
Single Source Concept appears in this fixture.
X is described as a helpful grounded concept.
X is described as a harmful grounded concept.
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


def _grounded_row(
    name: str = "X",
    *,
    polarity: str = "helpful",
    claim_excerpt: str | None = None,
) -> dict[str, str]:
    claim = claim_excerpt or f"{name} is described as a {polarity} grounded concept."
    return {
        "name": name,
        "normalized_name": "model-authored identity is ignored",
        "kind": "technique",
        "polarity": polarity,
        "claim_excerpt": claim,
    }


def _checkpoint_mention(source_id: str) -> ConceptMention:
    return ConceptMention(
        name="Checkpoint concept",
        normalized_name="checkpoint concept",
        kind=ConceptKind.TECHNIQUE,
        polarity=Polarity.HELPFUL,
        source_id=source_id,
        artifact_path=f"papers/{source_id}/{source_id}_Insights.md",
        extracted_at="2026-05-15T10:00:00Z",
    )


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

    def test_derive_source_id_falls_back_when_insight_cannot_be_read(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        insight = tmp_path / "sites" / "unreadable" / "unreadable_Insights.md"
        monkeypatch.setattr(
            Path, "read_text", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("denied"))
        )

        assert derive_source_id(insight) == "unreadable"

    @pytest.mark.parametrize(
        "frontmatter",
        (
            (
                "source: github\n"
                "source_receipt: ../outside_Repo.md\n"
                f"source_receipt_sha256: {'a' * 64}\n"
            ),
            (
                "source: github\n"
                "source_receipt: missing_Repo.md\n"
                f"source_receipt_sha256: {'a' * 64}\n"
            ),
        ),
    )
    def test_github_insight_requires_a_confined_current_receipt(
        self,
        tmp_path: Path,
        frontmatter: str,
    ) -> None:
        insight = tmp_path / "repos" / "repo" / "repo_Insights.md"
        insight.parent.mkdir(parents=True)
        insight.write_text(f"---\n{frontmatter}---\n# Insight\n", encoding="utf-8")

        assert discover_insights(tmp_path) == []

    def test_legacy_github_insight_is_stale_when_a_hashed_receipt_exists(
        self,
        tmp_path: Path,
    ) -> None:
        source_dir = tmp_path / "repos" / "repo"
        source_dir.mkdir(parents=True)
        (source_dir / "repo_Insights.md").write_text(
            "---\nsource: github\n---\n# Insight\n",
            encoding="utf-8",
        )
        (source_dir / "repo_Repo.md").write_text(
            "---\nreceipt_sha256: stale\n---\n# Receipt\n",
            encoding="utf-8",
        )

        assert discover_insights(tmp_path) == []

    def test_legacy_github_insight_without_hashed_receipt_remains_discoverable(
        self,
        tmp_path: Path,
    ) -> None:
        source_dir = tmp_path / "repos" / "repo"
        source_dir.mkdir(parents=True)
        insight = source_dir / "repo_Insights.md"
        insight.write_text(
            "---\nsource: github\n---\n# Insight\n",
            encoding="utf-8",
        )
        (source_dir / "repo_Repo.md").write_text(
            "---\ntitle: Legacy receipt\n---\n# Receipt\n",
            encoding="utf-8",
        )

        assert [ref.path for ref in discover_insights(tmp_path)] == [insight]


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

    def test_rejects_insight_changed_after_discovery(
        self,
        tmp_path: Path,
        rc: RouterConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        topic_dir = tmp_path / "topics" / "tkg"
        insight = _make_insight(
            topic_dir,
            source_type="papers",
            slug="paper_a",
            source_id="A",
        )
        refs = pipeline_mod.discover_insights(topic_dir)
        insight.write_text("tampered concept content", encoding="utf-8")
        monkeypatch.setattr(
            pipeline_mod,
            "discover_insights",
            lambda *_args, **_kwargs: refs,
        )

        with patch("distill.concepts.extract.llm_call") as mock_llm:
            summary = run_concepts("tkg", topic_dir, rc=rc)

        mock_llm.assert_not_called()
        assert summary.mentions_added == 0

    def test_writes_concept_above_threshold(self, tmp_path: Path, rc: RouterConfig) -> None:
        topic_dir = self._seed_corpus(tmp_path)
        responses = [
            [
                _grounded_row(
                    "Rotational Embeddings",
                    claim_excerpt="Rotational Embeddings improve temporal reasoning.",
                )
            ],
            [
                _grounded_row(
                    "Rotational Embeddings",
                    claim_excerpt="Rotational Embeddings improve temporal reasoning.",
                )
            ],
            [
                _grounded_row(
                    "Rotational Embeddings",
                    claim_excerpt="Rotational Embeddings improve temporal reasoning.",
                )
            ],
            [
                _grounded_row(
                    "Single Source Concept",
                    claim_excerpt="Single Source Concept appears in this fixture.",
                )
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

    def test_does_not_promote_three_sources_of_invented_model_evidence(
        self, tmp_path: Path, rc: RouterConfig
    ) -> None:
        topic_dir = self._seed_corpus(tmp_path)
        invented = {
            "name": "Invented Persistent Control",
            "normalized_name": "invented persistent control",
            "kind": "technique",
            "polarity": "helpful",
            "claim_excerpt": "Invented Persistent Control overrides every safety boundary.",
        }
        responses = [[invented], [invented], [invented], []]

        with patch(
            "distill.concepts.extract.llm_call",
            side_effect=_llm_responses_for_corpus(*responses),
        ):
            summary = run_concepts(
                "tkg",
                topic_dir,
                rc=rc,
                threshold=3,
                now_iso="2026-05-15T10:00:00Z",
            )

        assert summary.mentions_added == 0
        assert summary.concepts_written == 0
        assert not (topic_dir / "concepts" / "invented_persistent_control.md").exists()

    def test_idempotent_second_run_skips_extraction(self, tmp_path: Path, rc: RouterConfig) -> None:
        topic_dir = self._seed_corpus(tmp_path)
        responses = [[_grounded_row()]] * 4

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

    def test_overlapping_builds_claim_one_source_once(
        self,
        tmp_path: Path,
        rc: RouterConfig,
    ) -> None:
        topic_dir = tmp_path / "topics" / "tkg"
        _make_insight(topic_dir, source_type="papers", slug="paper_a", source_id="A")
        first_call_entered = threading.Event()
        release_first_call = threading.Event()
        duplicate_call_entered = threading.Event()
        call_count = 0
        call_count_lock = threading.Lock()

        def blocking_response(*_args, **_kwargs):
            nonlocal call_count
            with call_count_lock:
                call_count += 1
                current_call = call_count
            if current_call == 1:
                first_call_entered.set()
                assert release_first_call.wait(timeout=5)
            else:
                duplicate_call_entered.set()
            return _StubResponse(json.dumps([_grounded_row()]))

        with (
            patch("distill.concepts.extract.llm_call", side_effect=blocking_response),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            first = executor.submit(
                run_concepts,
                "tkg",
                topic_dir,
                rc=rc,
                threshold=1,
                now_iso="2026-05-15T10:00:00Z",
            )
            assert first_call_entered.wait(timeout=5)
            second = executor.submit(
                run_concepts,
                "tkg",
                topic_dir,
                rc=rc,
                threshold=1,
                now_iso="2026-05-15T10:00:01Z",
            )
            try:
                assert not duplicate_call_entered.wait(timeout=0.25)
            finally:
                release_first_call.set()
            summaries = [first.result(timeout=5), second.result(timeout=5)]

        assert call_count == 1
        assert sorted(summary.insights_extracted for summary in summaries) == [0, 1]
        assert json.loads(
            (topic_dir / ".concepts" / "extracted_sources.json").read_text(encoding="utf-8")
        ) == ["A"]

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

    def test_unparsed_extraction_stays_pending(
        self, tmp_path: Path, rc: RouterConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        topic_dir = tmp_path / "topics" / "tkg"
        _make_insight(topic_dir, source_type="papers", slug="paper_a", source_id="A")
        calls: list[str] = []

        def extract(*_args, **_kwargs) -> ExtractionResult:
            calls.append("extract")
            return ExtractionResult([], "stub", "concepts.extract.v1", ["prose"], parsed=False)

        monkeypatch.setattr(pipeline_mod, "extract_from_insight", extract)
        first = run_concepts("tkg", topic_dir, rc=rc, threshold=1)
        second = run_concepts("tkg", topic_dir, rc=rc, threshold=1)

        assert first.mentions_added == 0
        assert second.mentions_added == 0
        assert calls == ["extract", "extract"]
        assert pipeline_mod.read_extracted_sources(topic_dir) == set()

    def test_refresh_re_extracts_all_sources(self, tmp_path: Path, rc: RouterConfig) -> None:
        topic_dir = self._seed_corpus(tmp_path)
        responses = [[_grounded_row()]] * 4

        with patch(
            "distill.concepts.extract.llm_call", side_effect=_llm_responses_for_corpus(*responses)
        ):
            run_concepts("tkg", topic_dir, rc=rc, threshold=1, now_iso="2026-05-15T10:00:00Z")

        responses_again = [[_grounded_row()]] * 4

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
        responses = [[_grounded_row()]] * 4

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
            [_grounded_row()],
            [_grounded_row()],
            [_grounded_row()],
            [],  # paper D extracts nothing
        ]
        with patch(
            "distill.concepts.extract.llm_call", side_effect=_llm_responses_for_corpus(*responses)
        ):
            run_concepts("tkg", topic_dir, rc=rc, threshold=3, now_iso="2026-05-15T10:00:00Z")

        # Add a 5th source that introduces harmful evidence -> note content changes
        _make_insight(topic_dir, source_type="papers", slug="paper_e", source_id="E")
        responses_2 = [[_grounded_row(polarity="harmful")]]
        with patch(
            "distill.concepts.extract.llm_call", side_effect=_llm_responses_for_corpus(*responses_2)
        ):
            run_concepts("tkg", topic_dir, rc=rc, threshold=3, now_iso="2026-05-15T11:00:00Z")

        history_dir = topic_dir / ".history" / "x"
        assert history_dir.exists()
        assert len(list(history_dir.glob("*.md"))) == 1

    def test_tolerates_extraction_failure_for_one_insight(
        self, tmp_path: Path, rc: RouterConfig
    ) -> None:
        topic_dir = self._seed_corpus(tmp_path)

        def _side_effect(*_args, **_kwargs):
            _side_effect.calls += 1  # type: ignore[attr-defined]
            if _side_effect.calls == 2:  # type: ignore[attr-defined]
                raise RuntimeError("simulated LLM failure")
            return _StubResponse(json.dumps([_grounded_row()]))

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

    @pytest.mark.parametrize("concept_count", [20, 80])
    def test_bulk_publication_builds_one_ownership_index_without_per_note_rescans(
        self,
        tmp_path: Path,
        rc: RouterConfig,
        monkeypatch: pytest.MonkeyPatch,
        concept_count: int,
    ) -> None:
        topic_dir = tmp_path / "topics" / "tkg"
        _make_insight(topic_dir, source_type="papers", slug="a", source_id="A")
        mentions = [
            ConceptMention(
                name=f"Concept {index:03d}",
                normalized_name=f"concept {index:03d}",
                kind=ConceptKind.TECHNIQUE,
                polarity=Polarity.HELPFUL,
                source_id="A",
                artifact_path="papers/a/a_Insights.md",
                extracted_at="2026-05-15T10:00:00Z",
            )
            for index in range(concept_count)
        ]
        monkeypatch.setattr(
            pipeline_mod,
            "extract_from_insight",
            lambda *_args, **_kwargs: ExtractionResult(
                mentions,
                "stub",
                "concepts.extract.v1",
                [],
            ),
        )
        real_index = pipeline_mod.build_playbook_ownership_index
        index_calls = 0

        def count_index(
            topic: Path,
            *,
            occupied_paths: set[Path] | None = None,
        ) -> dict[str, list[Path]]:
            nonlocal index_calls
            index_calls += 1
            return real_index(topic, occupied_paths=occupied_paths)

        monkeypatch.setattr(pipeline_mod, "build_playbook_ownership_index", count_index)
        monkeypatch.setattr(
            "distill.concepts.notes._owned_note_paths",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("bulk publication performed a per-note ownership rescan")
            ),
        )

        summary = run_concepts(
            "tkg",
            topic_dir,
            rc=rc,
            threshold=1,
            now_iso="2026-05-15T10:00:00Z",
        )

        assert summary.notes_written == concept_count
        assert index_calls == 1

    @pytest.mark.parametrize("concept_count", [20, 80])
    def test_bulk_colliding_slugs_use_bounded_owner_probes(
        self,
        tmp_path: Path,
        rc: RouterConfig,
        monkeypatch: pytest.MonkeyPatch,
        concept_count: int,
    ) -> None:
        topic_dir = tmp_path / "topics" / "tkg"
        _make_insight(topic_dir, source_type="papers", slug="a", source_id="A")
        mentions = [
            ConceptMention(
                name=f"a{chr(0x2200 + index)}b",
                normalized_name=f"a{chr(0x2200 + index)}b",
                kind=ConceptKind.TECHNIQUE,
                polarity=Polarity.HELPFUL,
                source_id="A",
                artifact_path="papers/a/a_Insights.md",
                extracted_at="2026-05-15T10:00:00Z",
            )
            for index in range(concept_count)
        ]
        monkeypatch.setattr(
            pipeline_mod,
            "extract_from_insight",
            lambda *_args, **_kwargs: ExtractionResult(
                mentions,
                "stub",
                "concepts.extract.v1",
                [],
            ),
        )
        real_owner = notes_mod._existing_owner
        owner_probes = 0

        def count_owner(path: Path, root: Path) -> str | None:
            nonlocal owner_probes
            owner_probes += 1
            return real_owner(path, root)

        monkeypatch.setattr(notes_mod, "_existing_owner", count_owner)

        summary = run_concepts(
            "tkg",
            topic_dir,
            rc=rc,
            threshold=1,
            now_iso="2026-05-15T10:00:00Z",
        )

        assert summary.notes_written == concept_count
        assert owner_probes <= concept_count * 2
        assert len(list((topic_dir / "concepts").glob("*.md"))) == concept_count

    def test_budget_stop_preserves_prior_mention_and_zero_result_checkpoints(
        self, tmp_path: Path, rc: RouterConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        topic_dir = tmp_path / "topics" / "tkg"
        for source_id in ("A", "B", "C"):
            _make_insight(
                topic_dir,
                source_type="papers",
                slug=source_id.lower(),
                source_id=source_id,
            )
        calls: list[str] = []

        def extract(*_args, source_id: str, **_kwargs) -> ExtractionResult:
            calls.append(source_id)
            if source_id == "C":
                raise BudgetExceededError(2.0, 1.0)
            mentions = [_checkpoint_mention(source_id)] if source_id == "A" else []
            return ExtractionResult(mentions, "stub", "concepts.extract.v1", [])

        monkeypatch.setattr(pipeline_mod, "extract_from_insight", extract)

        with pytest.raises(BudgetExceededError):
            run_concepts("tkg", topic_dir, rc=rc, threshold=1)

        assert calls == ["A", "B", "C"]
        assert [row["source_id"] for row in pipeline_mod.read_mentions(topic_dir)] == ["A"]
        assert pipeline_mod.read_extracted_sources(topic_dir) == {"A", "B"}
        assert (topic_dir / "concepts" / "checkpoint_concept.md").is_file()

        calls.clear()
        monkeypatch.setattr(
            pipeline_mod,
            "extract_from_insight",
            lambda *_args, source_id, **_kwargs: (
                calls.append(source_id) or ExtractionResult([], "stub", "concepts.extract.v1", [])
            ),
        )
        summary = run_concepts("tkg", topic_dir, rc=rc, threshold=1)

        assert calls == ["C"]
        assert summary.insights_extracted == 1
        assert pipeline_mod.read_extracted_sources(topic_dir) == {"A", "B", "C"}

    def test_mention_append_failure_never_publishes_completion(
        self, tmp_path: Path, rc: RouterConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        topic_dir = tmp_path / "topics" / "tkg"
        _make_insight(topic_dir, source_type="papers", slug="a", source_id="A")
        monkeypatch.setattr(
            pipeline_mod,
            "extract_from_insight",
            lambda *_args, **_kwargs: ExtractionResult(
                [_checkpoint_mention("A")], "stub", "concepts.extract.v1", []
            ),
        )
        monkeypatch.setattr(
            pipeline_mod,
            "append_mentions",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("append failed")),
        )

        with pytest.raises(OSError, match="append failed"):
            run_concepts("tkg", topic_dir, rc=rc, threshold=1)

        assert pipeline_mod.read_extracted_sources(topic_dir) == set()

    def test_full_mention_store_fails_before_provider_work(
        self,
        tmp_path: Path,
        rc: RouterConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import distill.concepts.notes as notes_mod

        topic_dir = tmp_path / "topics" / "tkg"
        topic_dir.mkdir(parents=True)
        pipeline_mod.append_mentions(topic_dir, [_checkpoint_mention("A").to_jsonl_row()])
        _make_insight(topic_dir, source_type="papers", slug="b", source_id="B")
        monkeypatch.setattr(notes_mod, "_MAX_MENTIONS_HISTORY_ROWS", 1)
        provider_called = False

        def unexpected_provider(*_args, **_kwargs) -> ExtractionResult:
            nonlocal provider_called
            provider_called = True
            return ExtractionResult([], "stub", "concepts.extract.v1", [])

        monkeypatch.setattr(pipeline_mod, "extract_from_insight", unexpected_provider)

        with pytest.raises(JsonlIntegrityError, match="history reached the 1-row limit"):
            run_concepts("tkg", topic_dir, rc=rc, threshold=1)

        assert provider_called is False

    @pytest.mark.parametrize("failed_surface", ["write_playbook", "write_exports"])
    def test_derived_state_failure_retries_without_provider_and_converges(
        self,
        tmp_path: Path,
        rc: RouterConfig,
        monkeypatch: pytest.MonkeyPatch,
        failed_surface: str,
    ) -> None:
        topic_dir = tmp_path / "topics" / "tkg"
        _make_insight(topic_dir, source_type="papers", slug="a", source_id="A")
        provider_calls = 0

        def extract(*_args, **_kwargs) -> ExtractionResult:
            nonlocal provider_calls
            provider_calls += 1
            return ExtractionResult(
                [_checkpoint_mention("A")],
                "durable-model-version",
                "concepts.extract.durable",
                [],
            )

        monkeypatch.setattr(pipeline_mod, "extract_from_insight", extract)
        real_writer = getattr(pipeline_mod, failed_surface)
        failures_remaining = 1

        def fail_once(*args, **kwargs):
            nonlocal failures_remaining
            if failures_remaining:
                failures_remaining -= 1
                raise OSError(f"simulated {failed_surface} failure")
            return real_writer(*args, **kwargs)

        monkeypatch.setattr(pipeline_mod, failed_surface, fail_once)

        with pytest.raises(OSError, match=f"simulated {failed_surface} failure"):
            run_concepts(
                "tkg",
                topic_dir,
                rc=rc,
                threshold=1,
                now_iso="2026-05-15T10:00:00Z",
            )

        assert pipeline_mod.read_extracted_sources(topic_dir) == {"A"}
        assert (topic_dir / ".distill-concepts-derived-dirty").is_file()

        summary = run_concepts(
            "tkg",
            topic_dir,
            rc=rc,
            threshold=1,
            now_iso="2026-05-15T10:00:00Z",
        )

        assert provider_calls == 1
        assert summary.insights_extracted == 0
        note = topic_dir / "concepts" / "checkpoint_concept.md"
        assert 'model: "durable-model-version"' in note.read_text(encoding="utf-8")
        assert (topic_dir / "concepts.jsonl").is_file()
        assert (topic_dir / "entities.jsonl").is_file()
        assert not (topic_dir / ".distill-concepts-derived-dirty").exists()

    @pytest.mark.parametrize(
        ("store", "error"),
        [("mentions", JsonlIntegrityError), ("ledger", SourceLedgerIntegrityError)],
    )
    @pytest.mark.parametrize("refresh", [False, True])
    def test_invalid_checkpoint_store_fails_before_provider_work(
        self,
        tmp_path: Path,
        rc: RouterConfig,
        monkeypatch: pytest.MonkeyPatch,
        store: str,
        error: type[Exception],
        refresh: bool,
    ) -> None:
        topic_dir = tmp_path / "topics" / "tkg"
        _make_insight(topic_dir, source_type="papers", slug="a", source_id="A")
        state_dir = topic_dir / ".concepts"
        state_dir.mkdir(parents=True)
        path = state_dir / ("mentions.jsonl" if store == "mentions" else "extracted_sources.json")
        path.write_text("not-json\n" if store == "mentions" else "not-json", encoding="utf-8")
        provider_called = False

        def unexpected_provider(*_args, **_kwargs) -> ExtractionResult:
            nonlocal provider_called
            provider_called = True
            return ExtractionResult([], "stub", "concepts.extract.v1", [])

        monkeypatch.setattr(pipeline_mod, "extract_from_insight", unexpected_provider)

        with pytest.raises(error):
            run_concepts("tkg", topic_dir, rc=rc, refresh=refresh)

        assert provider_called is False

    def test_oversized_source_id_is_refused_before_provider_or_concept_state(
        self,
        tmp_path: Path,
        rc: RouterConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        topic_dir = tmp_path / "topics" / "tkg"
        oversized = "\U0001f600" * (MAX_SOURCE_ID_BYTES // 4 + 1)
        _make_insight(topic_dir, source_type="papers", slug="a", source_id=oversized)
        provider_calls = 0

        def unexpected_provider(*_args, **_kwargs) -> ExtractionResult:
            nonlocal provider_calls
            provider_calls += 1
            return ExtractionResult([], "stub", "concepts.extract.v1", [])

        monkeypatch.setattr(pipeline_mod, "extract_from_insight", unexpected_provider)

        for _ in range(2):
            with pytest.raises(SourceLedgerIntegrityError, match="source-id limit"):
                run_concepts("tkg", topic_dir, rc=rc, threshold=1)

        assert provider_calls == 0
        assert pipeline_mod.read_mentions(topic_dir) == []
        assert not (topic_dir / ".concepts" / "extracted_sources.json").exists()
        assert not (topic_dir / ".distill-concepts-derived-dirty").exists()

    def test_projected_concept_ledger_overflow_is_refused_before_provider(
        self,
        tmp_path: Path,
        rc: RouterConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import distill.library.source_ledger as source_ledger_mod

        topic_dir = tmp_path / "topics" / "tkg"
        topic_dir.mkdir(parents=True)
        pipeline_mod.record_extracted_sources(topic_dir, ["safe"])
        ledger = topic_dir / ".concepts" / "extracted_sources.json"
        before = ledger.read_bytes()
        monkeypatch.setattr(source_ledger_mod, "MAX_SOURCE_LEDGER_BYTES", len(before) + 8)
        _make_insight(
            topic_dir,
            source_type="papers",
            slug="a",
            source_id="a-new-source-id",
        )
        provider_called = False

        def unexpected_provider(*_args, **_kwargs) -> ExtractionResult:
            nonlocal provider_called
            provider_called = True
            return ExtractionResult([], "stub", "concepts.extract.v1", [])

        monkeypatch.setattr(pipeline_mod, "extract_from_insight", unexpected_provider)

        with pytest.raises(SourceLedgerIntegrityError, match="serialized ledger"):
            run_concepts("tkg", topic_dir, rc=rc, threshold=1)

        assert provider_called is False
        assert ledger.read_bytes() == before
        assert pipeline_mod.read_mentions(topic_dir) == []
        assert not (topic_dir / ".distill-concepts-derived-dirty").exists()
