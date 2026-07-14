"""CLI tests for the `distill concepts` group (build + recovery surface)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from distill import cli
from distill.commands import concepts as concepts_cmd
from distill.concepts import recovery
from distill.config import DistillConfig

runner = CliRunner()


def _seed_topic(library_dir: Path, topic: str = "tkg") -> Path:
    topic_dir = library_dir / "topics" / topic
    for slug, sid in (("a", "A"), ("b", "B"), ("c", "C")):
        d = topic_dir / "papers" / slug
        d.mkdir(parents=True)
        (d / f"{slug}_Insights.md").write_text(
            f"---\npaper_id: {sid}\n---\n# {slug}\nX is grounded in this insight.\n",
            encoding="utf-8",
        )
    return topic_dir


@pytest.fixture
def fixture_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DistillConfig:
    cfg = DistillConfig(xai_api_key=SecretStr("test"), distill_output_dir=tmp_path / "library")
    monkeypatch.setattr("distill.commands.concepts.get_config", lambda: cfg)
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


def _grounded_x_row() -> dict[str, str]:
    return {
        "name": "X",
        "kind": "technique",
        "polarity": "helpful",
        "claim_excerpt": "X is grounded in this insight.",
    }


class TestConceptsCommand:
    def test_help_describes_purpose(self) -> None:
        result = runner.invoke(cli.app, ["concepts", "--help"])
        assert result.exit_code == 0
        assert "playbook" in result.output.lower()

    def test_rejects_missing_topic_dir(self, fixture_config: DistillConfig) -> None:
        result = runner.invoke(cli.app, ["concepts", "build", "ghost-topic"])
        assert result.exit_code == 1
        assert "does not exist" in result.output.lower()

    def test_build_reports_when_no_new_insights(
        self, fixture_config: DistillConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fixture_config.topic_dir("tkg").mkdir(parents=True)
        summary = SimpleNamespace(
            insights_scanned=3,
            insights_extracted=0,
            mentions_added=0,
            concepts_written=0,
            concepts_unchanged=2,
            entities_written=0,
        )

        def run_concepts(topic, topic_dir, rc, threshold, refresh, tracker):
            assert topic == "tkg"
            assert topic_dir == fixture_config.topic_dir("tkg")
            assert threshold == 3
            assert refresh is False
            return summary

        monkeypatch.setattr("distill.concepts.run_concepts", run_concepts)

        result = runner.invoke(cli.app, ["concepts", "build", "tkg"])

        assert result.exit_code == 0, result.output
        assert "No new insights to extract" in result.output
        assert not (fixture_config.library_dir / ".distill" / "cost_log.jsonl").exists()

    def test_build_persists_recorded_usage_when_concept_extraction_fails(
        self, fixture_config: DistillConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from distill.pipeline.costs import TokenUsage

        fixture_config.topic_dir("tkg").mkdir(parents=True)

        def run_concepts(*_args, tracker, **_kwargs):
            tracker.record(
                TokenUsage(
                    prompt_tokens=20,
                    completion_tokens=10,
                    model="grok-4.3",
                    call_type="concepts_extract",
                    provider_name="xai",
                    provider_type="cloud",
                )
            )
            raise RuntimeError("extraction failed")

        monkeypatch.setattr("distill.concepts.run_concepts", run_concepts)

        result = runner.invoke(cli.app, ["concepts", "build", "tkg"])

        assert result.exit_code == 1
        rows = [
            json.loads(line)
            for line in (fixture_config.library_dir / ".distill" / "cost_log.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert rows[-1]["command"] == "concepts"
        assert rows[-1]["grok_calls"] == 1
        assert rows[-1]["metadata"]["topic"] == "tkg"

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

    def test_post_ingest_helper_skips_missing_topic_dir(
        self, fixture_config: DistillConfig, monkeypatch
    ) -> None:
        from distill.commands import _concept_ingest

        calls = []
        monkeypatch.setattr(_concept_ingest, "get_config", lambda: fixture_config)
        monkeypatch.setattr("distill.concepts.run_concepts", lambda *a, **k: calls.append(a))

        _concept_ingest.run_concepts_after_ingest("ghost")

        assert calls == []

    def test_post_ingest_helper_treats_extraction_failure_as_best_effort(
        self, fixture_config: DistillConfig, monkeypatch
    ) -> None:
        from distill.commands import _concept_ingest

        _seed_topic(fixture_config.library_dir)
        calls = []
        monkeypatch.setattr(_concept_ingest, "get_config", lambda: fixture_config)

        def fail_concepts(*_args, **_kwargs):
            calls.append("run")
            raise RuntimeError("model unavailable")

        monkeypatch.setattr("distill.concepts.run_concepts", fail_concepts)

        _concept_ingest.run_concepts_after_ingest("tkg")

        assert calls == ["run"]

    def test_runs_end_to_end(self, fixture_config: DistillConfig) -> None:
        _seed_topic(fixture_config.library_dir)
        rows = [[_grounded_x_row()], [_grounded_x_row()], [_grounded_x_row()]]
        with patch("distill.concepts.extract.llm_call", side_effect=_stub_llm(rows)):
            result = runner.invoke(cli.app, ["concepts", "build", "tkg", "--threshold", "3"])
        assert result.exit_code == 0
        assert "Concept playbook" in result.output
        assert "Insights scanned:" in result.output
        # Verify the on-disk artifacts
        topic_dir = fixture_config.topic_dir("tkg")
        assert (topic_dir / "concepts" / "x.md").exists()
        assert (topic_dir / "concepts.jsonl").exists()
        rows = [
            json.loads(line)
            for line in (fixture_config.library_dir / ".distill" / "cost_log.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert rows[-1]["command"] == "concepts"
        assert rows[-1]["grok_calls"] == 3

    def test_json_output(self, fixture_config: DistillConfig) -> None:
        _seed_topic(fixture_config.library_dir)
        rows = [[_grounded_x_row()]] * 3
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
        rows = [[_grounded_x_row()]] * 3
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
        rows = [[_grounded_x_row()]] * 3
        with patch("distill.concepts.extract.llm_call", side_effect=_stub_llm(rows)) as mock_llm:
            runner.invoke(cli.app, ["concepts", "build", "tkg", "--threshold", "3"])
        assert mock_llm.call_count == 3

        rows_2 = [[_grounded_x_row()]] * 3
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


def _file_state(root: Path) -> dict[str, bytes]:
    """Capture every persisted file so refusal and no-op tests detect writes."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class TestConceptsRecoveryCommands:
    def test_recovery_rejects_missing_topic(self, fixture_config: DistillConfig) -> None:
        result = runner.invoke(cli.app, ["concepts", "log", "ghost", "missing"])
        assert result.exit_code == 1
        assert "topic directory does not exist" in result.output.lower()

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

    def test_diff_missing_slug_errors(self, fixture_config: DistillConfig) -> None:
        fixture_config.topic_dir("tkg").mkdir(parents=True)
        result = runner.invoke(cli.app, ["concepts", "diff", "tkg", "ghost"])
        assert result.exit_code == 1
        assert "no concept or entity note" in result.output.lower()

    def test_log_live_note_without_history(self, fixture_config: DistillConfig) -> None:
        note = fixture_config.topic_dir("tkg") / "concepts" / "lone.md"
        note.parent.mkdir(parents=True)
        note.write_text("# Lone concept\n", encoding="utf-8")

        result = runner.invoke(cli.app, ["concepts", "log", "tkg", "lone"])

        assert result.exit_code == 0, result.output
        assert "No history snapshots" in result.output

    def test_log_snapshot_without_live_note(self, fixture_config: DistillConfig) -> None:
        topic_dir = fixture_config.topic_dir("tkg")
        _build_history(topic_dir)
        (topic_dir / "concepts" / "rotational_embedding.md").unlink()

        result = runner.invoke(cli.app, ["concepts", "log", "tkg", "rotational_embedding"])

        assert result.exit_code == 0, result.output
        assert "no live note" in result.output.lower()
        assert "1 snapshot(s)" in result.output
        assert "2026-05-29T08:10:31Z" in result.output

    def test_render_diff_covers_structural_and_body_changes(self, capsys) -> None:
        diff = recovery.NoteDiff(
            old_label="old",
            new_label="new",
            sources_added=["added"],
            sources_removed=["removed"],
            sources_repolarized=[("changed", "helpful", "harmful")],
            field_changes=[recovery.FieldChange("source_count", 1, 2)],
            body_diff="--- old\n+++ new\n@@ -1 +1 @@\n-old\n+new\n context",
        )

        concepts_cmd._render_diff(diff)
        output = capsys.readouterr().out
        normalized = " ".join(output.split())

        assert "+ source added" in output
        assert "- source removed" in output
        assert "~ source changed helpful -> harmful" in normalized
        assert "source_count: 1 -> 2" in output
        assert "@@ -1 +1 @@" in output
        assert "-old" in output
        assert "+new" in output

    def test_render_empty_diff(self, capsys) -> None:
        concepts_cmd._render_diff(recovery.NoteDiff(old_label="same", new_label="same"))
        assert "No differences" in capsys.readouterr().out

    def test_render_frontmatter_only_diff(self, capsys) -> None:
        diff = recovery.NoteDiff(
            old_label="old",
            new_label="new",
            sources_added=["added"],
        )
        concepts_cmd._render_diff(diff)
        output = capsys.readouterr().out
        assert "+ source added" in output
        assert "Body changes" not in output

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

    def test_diff_two_snapshots_without_live_note(self, fixture_config: DistillConfig) -> None:
        topic_dir = fixture_config.topic_dir("tkg")
        history = recovery.history_dir_for_slug(topic_dir, "standalone")
        history.mkdir(parents=True)
        (history / "2026-05-01T00-00-00Z.md").write_text("# Old\n", encoding="utf-8")
        (history / "2026-05-02T00-00-00Z.md").write_text("# New\n", encoding="utf-8")

        result = runner.invoke(
            cli.app,
            [
                "concepts",
                "diff",
                "tkg",
                "standalone",
                "2026-05-01T00:00:00Z",
                "2026-05-02T00:00:00Z",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "2026-05-01T00:00:00Z" in result.output
        assert "2026-05-02T00:00:00Z" in result.output
        assert "-# Old" in result.output
        assert "+# New" in result.output

    def test_diff_requires_two_timestamps_without_live_note(
        self, fixture_config: DistillConfig
    ) -> None:
        topic_dir = fixture_config.topic_dir("tkg")
        history = recovery.history_dir_for_slug(topic_dir, "standalone")
        history.mkdir(parents=True)
        (history / "2026-05-01T00-00-00Z.md").write_text("# Old\n", encoding="utf-8")

        result = runner.invoke(
            cli.app,
            ["concepts", "diff", "tkg", "standalone", "2026-05-01T00:00:00Z"],
        )

        assert result.exit_code == 1
        assert "No live note to diff against" in result.output

    def test_diff_live_note_without_history_is_a_no_op(self, fixture_config: DistillConfig) -> None:
        note = fixture_config.topic_dir("tkg") / "concepts" / "lone.md"
        note.parent.mkdir(parents=True)
        note.write_text("# Lone concept\n", encoding="utf-8")

        result = runner.invoke(cli.app, ["concepts", "diff", "tkg", "lone"])

        assert result.exit_code == 0, result.output
        assert "No history snapshots yet" in result.output

    def test_rollback_missing_snapshot_errors(self, fixture_config: DistillConfig) -> None:
        fixture_config.topic_dir("tkg").mkdir(parents=True)

        result = runner.invoke(
            cli.app,
            ["concepts", "rollback", "tkg", "ghost", "2026-01-01", "--yes"],
        )

        assert result.exit_code == 1
        assert "No snapshot" in result.output

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
        assert result.exit_code == 0, result.output
        normalized_output = " ".join(result.output.replace("\\", "/").split())
        assert "Restored" in result.output
        assert "Backed up previous version to .history/rotational_embedding/" in normalized_output
        assert "Updated rollup concepts.jsonl" in result.output
        # Live note rolled back to v1: 2 sources.
        note = (topic_dir / "concepts" / "rotational_embedding.md").read_text(encoding="utf-8")
        assert "source_count: 2" in note
        row = json.loads((topic_dir / "concepts.jsonl").read_text(encoding="utf-8").splitlines()[0])
        assert row["source_count"] == 2

    def test_rollback_aborts_without_confirmation(self, fixture_config: DistillConfig) -> None:
        topic_dir = fixture_config.topic_dir("tkg")
        _build_history(topic_dir)
        before = _file_state(topic_dir)

        result = runner.invoke(
            cli.app,
            ["concepts", "rollback", "tkg", "rotational_embedding", "2026-05-29T08:10:31Z"],
            input="n\n",
        )
        assert result.exit_code == 1
        assert "aborted" in result.output.lower()
        assert _file_state(topic_dir) == before

    def test_rollback_already_matching_snapshot_is_a_no_op(
        self, fixture_config: DistillConfig
    ) -> None:
        topic_dir = fixture_config.topic_dir("tkg")
        timestamp = _build_history(topic_dir)[0]
        setup = recovery.rollback(
            topic_dir,
            "rotational_embedding",
            timestamp,
            now_iso="2026-05-30T00:00:00Z",
        )
        assert setup.changed
        before = _file_state(topic_dir)

        result = runner.invoke(
            cli.app,
            ["concepts", "rollback", "tkg", "rotational_embedding", timestamp, "--yes"],
        )

        assert result.exit_code == 0, result.output
        assert "already matches" in result.output
        assert _file_state(topic_dir) == before

    def test_rollback_recreates_deleted_note_without_backup(
        self, fixture_config: DistillConfig
    ) -> None:
        topic_dir = fixture_config.topic_dir("tkg")
        timestamp = _build_history(topic_dir)[0]
        note = topic_dir / "concepts" / "rotational_embedding.md"
        note.unlink()

        result = runner.invoke(
            cli.app,
            ["concepts", "rollback", "tkg", "rotational_embedding", timestamp, "--yes"],
        )

        assert result.exit_code == 0, result.output
        assert "Restored" in result.output
        assert "Backed up" not in result.output
        assert "Updated rollup concepts.jsonl" in result.output
        assert "source_count: 2" in note.read_text(encoding="utf-8")
        assert len(recovery.list_snapshots(topic_dir, "rotational_embedding")) == 1
