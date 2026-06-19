"""CLI tests for the `distill concepts` group (build + recovery surface)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from distill import cli
from distill.config import DistillConfig

runner = CliRunner()


def _seed_topic(library_dir: Path, topic: str = "tkg") -> Path:
    topic_dir = library_dir / "topics" / topic
    for slug, sid in (("a", "A"), ("b", "B"), ("c", "C")):
        d = topic_dir / "papers" / slug
        d.mkdir(parents=True)
        (d / f"{slug}_Insights.md").write_text(
            f"---\npaper_id: {sid}\n---\n# {slug}\nbody\n", encoding="utf-8"
        )
    return topic_dir


@pytest.fixture
def fixture_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DistillConfig:
    cfg = DistillConfig(xai_api_key="test", distill_output_dir=tmp_path / "library")
    monkeypatch.setattr("distill.commands._logic.get_config", lambda: cfg)
    # `health` resolves get_config from its own module (commands/doctor.py) now.
    monkeypatch.setattr("distill.commands.doctor.get_config", lambda: cfg)
    return cfg


class _StubResponse:
    def __init__(self, payload: list) -> None:
        self.text = json.dumps(payload)
        self.model = "grok-4.3"
        self.input_tokens = 10
        self.output_tokens = 5


def _stub_llm(rows: list[list]):
    queue = list(rows)

    def _side(*_args, **_kwargs):
        return _StubResponse(queue.pop(0) if queue else [])

    return _side


class TestConceptsCommand:
    def test_help_describes_purpose(self) -> None:
        result = runner.invoke(cli.app, ["concepts", "--help"])
        assert result.exit_code == 0
        assert "playbook" in result.output.lower()

    def test_rejects_missing_topic_dir(self, fixture_config: DistillConfig) -> None:
        result = runner.invoke(cli.app, ["concepts", "build", "ghost-topic"])
        assert result.exit_code == 1
        assert "does not exist" in result.output.lower()

    def test_post_ingest_helper_runs_concepts(self, fixture_config: DistillConfig, monkeypatch):
        from distill.commands import _concept_ingest
        from distill.pipeline.costs import CostTracker

        _seed_topic(fixture_config.library_dir)
        tracker = CostTracker()
        calls = []

        def fake_run_concepts(topic, topic_dir, rc, tracker=None, **kwargs):
            calls.append((topic, topic_dir, tracker))
            return SimpleNamespace(
                insights_scanned=3,
                insights_extracted=2,
                mentions_added=2,
                notes_written=1,
                concepts_written=1,
                entities_written=0,
                concepts_unchanged=0,
            )

        monkeypatch.setattr(_concept_ingest, "get_config", lambda: fixture_config)
        monkeypatch.setattr("distill.concepts.run_concepts", fake_run_concepts)

        _concept_ingest.run_concepts_after_ingest("tkg", tracker=tracker)

        assert calls == [("tkg", fixture_config.topic_dir("tkg"), tracker)]

    def test_runs_end_to_end(self, fixture_config: DistillConfig) -> None:
        _seed_topic(fixture_config.library_dir)
        rows = [
            [{"name": "X", "normalized_name": "x", "kind": "technique", "polarity": "helpful"}],
            [{"name": "X", "normalized_name": "x", "kind": "technique", "polarity": "helpful"}],
            [{"name": "X", "normalized_name": "x", "kind": "technique", "polarity": "helpful"}],
        ]
        with patch("distill.concepts.extract.llm_call", side_effect=_stub_llm(rows)):
            result = runner.invoke(cli.app, ["concepts", "build", "tkg", "--threshold", "3"])
        assert result.exit_code == 0
        assert "Concept playbook" in result.output
        assert "Insights scanned:" in result.output
        # Verify the on-disk artifacts
        topic_dir = fixture_config.topic_dir("tkg")
        assert (topic_dir / "concepts" / "x.md").exists()
        assert (topic_dir / "concepts.jsonl").exists()

    def test_json_output(self, fixture_config: DistillConfig) -> None:
        _seed_topic(fixture_config.library_dir)
        rows = [
            [{"name": "X", "normalized_name": "x", "kind": "technique", "polarity": "helpful"}]
        ] * 3
        with patch("distill.concepts.extract.llm_call", side_effect=_stub_llm(rows)):
            result = runner.invoke(
                cli.app, ["concepts", "build", "tkg", "--threshold", "3", "--json"]
            )
        assert result.exit_code == 0
        json_blob = result.output[result.output.index("{") :]
        assert "topic" in json_blob
        assert "insights_scanned" in json_blob
        assert "success" in json_blob or "data" in json_blob

    def test_global_json_output(self, fixture_config: DistillConfig) -> None:
        _seed_topic(fixture_config.library_dir)
        rows = [
            [{"name": "X", "normalized_name": "x", "kind": "technique", "polarity": "helpful"}]
        ] * 3
        with patch("distill.concepts.extract.llm_call", side_effect=_stub_llm(rows)):
            result = runner.invoke(
                cli.app, ["--json", "concepts", "build", "tkg", "--threshold", "3"]
            )
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert parsed["data"]["topic"] == "tkg"
        assert parsed["data"]["insights_scanned"] == 3

    def test_health_surfaces_contested_concepts(self, fixture_config: DistillConfig) -> None:
        """distill health <topic> lifts contested concepts into its warnings."""
        # Seed a topic dir with a fake concepts.jsonl containing one contested row
        topic_dir = fixture_config.topic_dir("tkg")
        topic_dir.mkdir(parents=True)
        (topic_dir / "concepts.jsonl").write_text(
            json.dumps(
                {
                    "name": "Disputed Method",
                    "slug": "disputed_method",
                    "kind": "technique",
                    "topic": "tkg",
                    "source_count": 5,
                    "helpful_count": 3,
                    "harmful_count": 2,
                    "contested": True,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        # health needs a topic in Library; the simplest path is add_channel
        # which creates the topic entry as a side effect.
        from distill.library.state import Library

        lib = Library(fixture_config)
        lib.add_channel("tkg", "https://example.com", "TestChan")

        result = runner.invoke(cli.app, ["health", "tkg"])
        assert result.exit_code == 0
        assert "Contested concepts" in result.output
        assert "Disputed Method" in result.output

    def test_refresh_re_extracts(self, fixture_config: DistillConfig) -> None:
        _seed_topic(fixture_config.library_dir)
        rows = [
            [{"name": "X", "normalized_name": "x", "kind": "technique", "polarity": "helpful"}]
        ] * 3
        with patch("distill.concepts.extract.llm_call", side_effect=_stub_llm(rows)) as mock_llm:
            runner.invoke(cli.app, ["concepts", "build", "tkg", "--threshold", "3"])
        assert mock_llm.call_count == 3

        rows_2 = [
            [{"name": "X", "normalized_name": "x", "kind": "technique", "polarity": "helpful"}]
        ] * 3
        with patch("distill.concepts.extract.llm_call", side_effect=_stub_llm(rows_2)) as mock_llm:
            runner.invoke(cli.app, ["concepts", "build", "tkg", "--threshold", "3", "--refresh"])
        assert mock_llm.call_count == 3  # refresh re-extracts all


def _build_history(topic_dir: Path) -> list[str]:
    """Write two versions of a concept so one history snapshot exists.

    Returns the snapshot ISO timestamps (oldest first).
    """
    from distill.concepts.exports import write_exports
    from distill.concepts.notes import write_playbook
    from distill.concepts.records import (
        ConceptKind,
        EvidenceInterval,
        MergedConcept,
        Polarity,
        SourceEvidence,
    )

    def _c(sources: list[tuple[str, Polarity]], helpful: tuple[int, int], last_seen: str):
        srcs = tuple(
            SourceEvidence(source_id=s, artifact_path=f"papers/{s}/{s}_Insights.md", polarity=p)
            for s, p in sources
        )
        return MergedConcept(
            name="Rotational Embedding",
            normalized_name="rotational embedding",
            kind=ConceptKind.TECHNIQUE,
            topic="tkg",
            sources=srcs,
            helpful_evidence=EvidenceInterval(*helpful),
            harmful_evidence=EvidenceInterval(0, 0),
            first_seen="2026-05-01T00:00:00Z",
            last_seen=last_seen,
        )

    topic_dir.mkdir(parents=True, exist_ok=True)
    v1 = _c([("A", Polarity.HELPFUL), ("B", Polarity.HELPFUL)], (2, 2), "2026-05-28T07:00:00Z")
    write_playbook(topic_dir, v1, now_iso="2026-05-28T07:00:00Z")
    write_exports(topic_dir, [v1])
    v2 = _c(
        [("A", Polarity.HELPFUL), ("B", Polarity.HELPFUL), ("C", Polarity.HELPFUL)],
        (3, 3),
        "2026-05-29T08:10:31Z",
    )
    write_playbook(topic_dir, v2, now_iso="2026-05-29T08:10:31Z")
    write_exports(topic_dir, [v2])
    return ["2026-05-29T08:10:31Z"]  # the one snapshot (holds v1)


class TestConceptsRecoveryCommands:
    def test_log_lists_snapshots(self, fixture_config: DistillConfig) -> None:
        _build_history(fixture_config.topic_dir("tkg"))
        result = runner.invoke(cli.app, ["concepts", "log", "tkg", "rotational_embedding"])
        assert result.exit_code == 0
        assert "snapshot(s)" in result.output
        assert "2026-05-29T08:10:31Z" in result.output
        assert "+1 source" in result.output

    def test_log_missing_slug_errors(self, fixture_config: DistillConfig) -> None:
        fixture_config.topic_dir("tkg").mkdir(parents=True)
        result = runner.invoke(cli.app, ["concepts", "log", "tkg", "ghost"])
        assert result.exit_code == 1
        assert "no concept or entity note" in result.output.lower()

    def test_diff_snapshot_vs_current(self, fixture_config: DistillConfig) -> None:
        _build_history(fixture_config.topic_dir("tkg"))
        result = runner.invoke(cli.app, ["concepts", "diff", "tkg", "rotational_embedding"])
        assert result.exit_code == 0
        assert "Frontmatter changes" in result.output
        # v1 -> current adds source C
        assert "+ source" in result.output and "C" in result.output

    def test_diff_unknown_timestamp_errors(self, fixture_config: DistillConfig) -> None:
        _build_history(fixture_config.topic_dir("tkg"))
        result = runner.invoke(
            cli.app, ["concepts", "diff", "tkg", "rotational_embedding", "1999-01-01"]
        )
        assert result.exit_code == 1
        assert "no snapshot" in result.output.lower()

    def test_rollback_restores_and_updates_rollup(self, fixture_config: DistillConfig) -> None:
        topic_dir = fixture_config.topic_dir("tkg")
        _build_history(topic_dir)
        result = runner.invoke(
            cli.app,
            [
                "concepts",
                "rollback",
                "tkg",
                "rotational_embedding",
                "2026-05-29T08:10:31Z",
                "--yes",
            ],
        )
        assert result.exit_code == 0
        assert "Restored" in result.output
        # Live note rolled back to v1: 2 sources.
        note = (topic_dir / "concepts" / "rotational_embedding.md").read_text(encoding="utf-8")
        assert "source_count: 2" in note
        row = json.loads((topic_dir / "concepts.jsonl").read_text(encoding="utf-8").splitlines()[0])
        assert row["source_count"] == 2

    def test_rollback_aborts_without_confirmation(self, fixture_config: DistillConfig) -> None:
        _build_history(fixture_config.topic_dir("tkg"))
        result = runner.invoke(
            cli.app,
            ["concepts", "rollback", "tkg", "rotational_embedding", "2026-05-29T08:10:31Z"],
            input="n\n",
        )
        assert result.exit_code == 1
        assert "aborted" in result.output.lower()
