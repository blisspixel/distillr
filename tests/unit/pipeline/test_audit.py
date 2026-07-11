"""Tests for distill.pipeline.audit and the audit command (deterministic health surface)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from distill.library.links import BrokenLink
from distill.pipeline.audit import (
    AuditReport,
    ExactVideoDuplicateGroup,
    SynthesisFreshness,
    ThinTranscript,
    VerifyRollup,
    VideoOccurrence,
    build_next_action_plan,
    collect_exact_video_duplicates,
    collect_thin_video_transcripts,
    collect_verify_rollup,
    render_audit_md,
    write_audit_artifact,
)

NOW = "2026-06-11T20:00:00Z"
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "audit_next_actions"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _seed_insight(topic_dir: Path, rel: str, *, sidecar: dict | None = None) -> None:
    d = topic_dir / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{d.name}_Insights.md").write_text('---\nsource_id: "x"\n---\n\nbody', encoding="utf-8")
    if sidecar is not None:
        (d / f"{d.name}_Verify.json").write_text(json.dumps(sidecar), encoding="utf-8")


def _seed_video_metadata(topic_dir: Path, channel: str, slug: str, metadata: dict) -> None:
    d = topic_dir / "channels" / channel / "videos" / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")


def _seed_video_transcript(
    topic_dir: Path,
    channel: str,
    slug: str,
    *,
    metadata: dict,
    transcript: str,
) -> None:
    _seed_video_metadata(topic_dir, channel, slug, metadata)
    d = topic_dir / "channels" / channel / "videos" / slug
    (d / "transcript.txt").write_text(transcript, encoding="utf-8")


class TestVerifyRollup:
    def test_counts_clean_flagged_and_never_checked(self, tmp_path: Path):
        topic = tmp_path / "t"
        _seed_insight(topic, "papers/p1", sidecar={"checked": 3, "unsupported": []})
        _seed_insight(
            topic,
            "papers/p2",
            sidecar={
                "checked": 2,
                "unsupported": [{"token": "99.9", "kind": "decimal", "context": "line"}],
            },
        )
        _seed_insight(topic, "papers/p3")  # never checked

        rollup = collect_verify_rollup(topic)

        assert rollup.insights_total == 3
        assert rollup.checked == 2
        assert rollup.clean == 1
        assert rollup.never_checked == 1
        assert rollup.flagged[0]["token"] == "99.9"
        assert rollup.flagged[0]["insight"].endswith("p2_Insights.md")

    def test_corrupt_sidecar_counts_as_never_checked(self, tmp_path: Path):
        topic = tmp_path / "t"
        d = topic / "papers" / "p1"
        d.mkdir(parents=True)
        (d / "p1_Insights.md").write_text("body", encoding="utf-8")
        (d / "p1_Verify.json").write_text("{not json", encoding="utf-8")

        rollup = collect_verify_rollup(topic)
        assert rollup.checked == 0
        assert rollup.never_checked == 1

    def test_zero_checked_sidecar_is_unverified_not_clean(self, tmp_path: Path):
        topic = tmp_path / "t"
        _seed_insight(
            topic,
            "papers/p1",
            sidecar={"checked": 0, "supported": 0, "unsupported": []},
        )

        rollup = collect_verify_rollup(topic)

        assert rollup.checked == 0
        assert rollup.clean == 0
        assert rollup.unverified == 1
        assert rollup.never_checked == 1

    def test_entailment_checks_can_cover_zero_numeric_claims(self, tmp_path: Path):
        topic = tmp_path / "t"
        _seed_insight(
            topic,
            "papers/p1",
            sidecar={
                "checked": 0,
                "supported": 0,
                "unsupported": [],
                "entailment": {"checked": 2, "supported": 2, "flagged": []},
            },
        )

        rollup = collect_verify_rollup(topic)

        assert rollup.checked == 1
        assert rollup.clean == 1
        assert rollup.unverified == 0

    def test_missing_topic_dir(self, tmp_path: Path):
        rollup = collect_verify_rollup(tmp_path / "nope")
        assert rollup.insights_total == 0

    def test_synthesis_sidecars_counted_separately(self, tmp_path: Path):
        """0.13.1: synthesis artifacts are swept by their writer-stamped sidecar
        identity, counted apart from insights, and their flags join the list."""
        topic = tmp_path / "t"
        _seed_insight(topic, "papers/p1", sidecar={"checked": 1, "unsupported": []})

        # A clean paper synthesis (sidecar identity t-paper-synthesis -> file stem
        # t_paper_synthesis) and a flagged corpus synthesis.
        topic.mkdir(parents=True, exist_ok=True)
        (topic / "t_Paper_Synthesis.md").write_text("syn", encoding="utf-8")
        (topic / "t_paper_synthesis_Verify.json").write_text(
            json.dumps({"checked": 2, "unsupported": []}), encoding="utf-8"
        )
        (topic / "t_Corpus_Synthesis.md").write_text("syn", encoding="utf-8")
        (topic / "t_corpus_synthesis_Verify.json").write_text(
            json.dumps(
                {"checked": 1, "unsupported": [{"token": "9.9", "kind": "decimal", "context": "l"}]}
            ),
            encoding="utf-8",
        )
        # A topic synthesis with a zero-check sidecar (unverified, not clean).
        (topic / "t_Topic_Synthesis.md").write_text("syn", encoding="utf-8")
        (topic / "t_topic_synthesis_Verify.json").write_text(
            json.dumps({"checked": 0, "supported": 0, "unsupported": []}),
            encoding="utf-8",
        )

        rollup = collect_verify_rollup(topic)

        assert rollup.insights_total == 1
        assert rollup.synthesis_total == 3
        assert rollup.synthesis_checked == 2
        assert rollup.synthesis_clean == 1
        assert rollup.synthesis_never_checked == 1
        assert rollup.synthesis_unverified == 1
        # The corpus-synthesis flag is in the shared list, labelled by artifact.
        assert any(f["token"] == "9.9" for f in rollup.flagged)


class TestExactVideoDuplicates:
    def test_groups_same_video_id_across_artifact_dirs(self, tmp_path: Path):
        topic = tmp_path / "t"
        _seed_video_metadata(
            topic,
            "CreatorA",
            "old-title",
            {
                "video_id": "same123",
                "title": "Old Title",
                "url": "https://www.youtube.com/watch?v=same123",
            },
        )
        _seed_video_metadata(
            topic,
            "CreatorB",
            "new-title",
            {
                "video_id": "same123",
                "title": "New Title",
                "url": "https://youtu.be/same123",
            },
        )
        _seed_video_metadata(
            topic,
            "CreatorA",
            "other",
            {
                "video_id": "other456",
                "title": "Other",
                "url": "https://www.youtube.com/watch?v=other456",
            },
        )

        groups = collect_exact_video_duplicates(topic)

        assert len(groups) == 1
        assert groups[0].identity == "youtube:same123"
        assert groups[0].members == 2
        assert [item.path for item in groups[0].occurrences] == [
            "channels/CreatorA/videos/old-title",
            "channels/CreatorB/videos/new-title",
        ]

    def test_uses_youtube_url_identity_when_video_id_missing(self, tmp_path: Path):
        topic = tmp_path / "t"
        _seed_video_metadata(
            topic,
            "CreatorA",
            "watch",
            {"title": "Watch URL", "url": "https://www.youtube.com/watch?v=same123&t=30"},
        )
        _seed_video_metadata(
            topic,
            "CreatorB",
            "shorts",
            {"title": "Shorts URL", "url": "https://www.youtube.com/shorts/same123"},
        )
        _seed_video_metadata(
            topic,
            "CreatorC",
            "embed",
            {
                "title": "Embed URL",
                "url": "https://www.youtube-nocookie.com/embed/same123",
            },
        )
        broken = topic / "channels" / "CreatorC" / "videos" / "broken"
        broken.mkdir(parents=True, exist_ok=True)
        (broken / "metadata.json").write_text("{bad json", encoding="utf-8")

        groups = collect_exact_video_duplicates(topic)

        assert [group.identity for group in groups] == ["youtube:same123"]
        assert groups[0].members == 3


class TestThinVideoTranscripts:
    def test_flags_long_video_with_short_transcript(self, tmp_path: Path):
        topic = tmp_path / "t"
        _seed_video_transcript(
            topic,
            "Creator",
            "long-thin",
            metadata={"title": "Long Thin", "duration": 3600},
            transcript="too short",
        )
        _seed_video_transcript(
            topic,
            "Creator",
            "long-good",
            metadata={"title": "Long Good", "duration": 3600},
            transcript="x" * 500,
        )
        _seed_video_transcript(
            topic,
            "Creator",
            "short-thin",
            metadata={"title": "Short Thin", "duration": 300},
            transcript="short",
        )

        items = collect_thin_video_transcripts(topic)

        assert items == [
            ThinTranscript(
                path="channels/Creator/videos/long-thin",
                channel="Creator",
                title="Long Thin",
                duration_seconds=3600,
                transcript_chars=9,
            )
        ]

    def test_ignores_corrupt_metadata_and_missing_transcripts(self, tmp_path: Path):
        topic = tmp_path / "t"
        broken = topic / "channels" / "Creator" / "videos" / "broken"
        broken.mkdir(parents=True, exist_ok=True)
        (broken / "metadata.json").write_text("{bad json", encoding="utf-8")
        (broken / "transcript.txt").write_text("tiny", encoding="utf-8")
        _seed_video_metadata(
            topic,
            "Creator",
            "missing-transcript",
            {"title": "Missing Transcript", "duration": 3600},
        )

        assert collect_thin_video_transcripts(topic) == []


def _report(**overrides) -> AuditReport:
    base = {
        "topic": "t",
        "health_warnings": ["t: synthesis is 120 days old"],
        "contested": [{"name": "X", "kind": "concept", "helpful": 2, "harmful": 1, "sources": 3}],
        "broken_links": [],
        "gaps": ["Coverage is effectively single-source (papers)."],
        "next_actions": ["Add website or paper sources."],
        "verify": VerifyRollup(
            insights_total=3,
            checked=2,
            clean=1,
            flagged=[
                {
                    "insight": "papers/p2/p2_Insights.md",
                    "token": "99.9",
                    "kind": "decimal",
                    "context": "c",
                }
            ],
        ),
    }
    base.update(overrides)
    return AuditReport(**base)


class TestRenderAndWrite:
    def test_render_contains_all_sections_and_counts(self):
        out = render_audit_md(_report(), now_iso=NOW)
        assert "# Audit: t" in out
        assert "verified clean: 1" in out
        assert "unverified/no checked claims: 1" in out
        assert "zero checked claims is coverage metadata, not a passing result" in out
        assert "`99.9` (decimal)" in out
        assert "synthesis is 120 days old" in out
        assert "**X** (concept): 2 helpful / 1 harmful" in out
        assert "All wiki-links resolve." in out
        assert "single-source" in out
        assert "distill discover --from-gaps --topic t --preview" in out

    def test_issue_count(self):
        # 1 warning + 1 contested + 1 gap + 1 flagged + 1 unverified.
        assert _report().issue_count == 5

    def test_render_exact_duplicate_video_section(self):
        report = _report(
            exact_video_duplicates=[
                ExactVideoDuplicateGroup(
                    identity="youtube:same123",
                    occurrences=[
                        VideoOccurrence(
                            path="channels/A/videos/old",
                            channel="A",
                            title="Old",
                            url="https://youtube.com/watch?v=same123",
                        ),
                        VideoOccurrence(
                            path="channels/B/videos/new",
                            channel="B",
                            title="New",
                            url="https://youtu.be/same123",
                        ),
                    ],
                )
            ]
        )

        out = render_audit_md(report, now_iso=NOW)

        assert report.issue_count == 6
        assert "Exact duplicate videos" in out
        assert "`youtube:same123` appears in 2 artifact directories" in out
        assert "`channels/A/videos/old` - Old (A)" in out

    def test_render_thin_transcripts_section(self):
        report = _report(
            thin_transcripts=[
                ThinTranscript(
                    path="channels/A/videos/long",
                    channel="A",
                    title="Long Talk",
                    duration_seconds=3600,
                    transcript_chars=9,
                )
            ]
        )

        out = render_audit_md(report, now_iso=NOW)

        assert report.issue_count == 6
        assert "Thin video transcripts" in out
        assert "`channels/A/videos/long` - Long Talk (A): 9 chars for 1h00m" in out

    def test_write_artifact_with_frontmatter(self, tmp_path: Path):
        path = write_audit_artifact(tmp_path, _report(), now_iso=NOW)
        assert path.name == "t_Audit.md"
        text = path.read_text(encoding="utf-8")
        assert 'type: "audit"' in text
        assert "findings: 5" in text


class TestNextActionPlan:
    def test_empty_plan_matches_fixture(self, tmp_path: Path):
        library = tmp_path / "library"
        report = _report(
            topic="empty",
            health_warnings=[],
            contested=[],
            gaps=["No major research gaps detected from the local corpus heuristics."],
            next_actions=[],
            verify=VerifyRollup(insights_total=0, checked=0, clean=0),
        )

        data = build_next_action_plan(library, [report], topic="all", generated_at=NOW).to_dict()

        assert data == _load_fixture("empty_plan.json")

    def test_orientation_only_plan_matches_fixture(self, tmp_path: Path):
        library = tmp_path / "library"
        topic_dir = library / "topics" / "t"
        topic_dir.mkdir(parents=True)
        report = _report(
            health_warnings=[],
            contested=[],
            gaps=["No major research gaps detected from the local corpus heuristics."],
            next_actions=[],
            verify=VerifyRollup(insights_total=0, checked=0, clean=0),
        )

        data = build_next_action_plan(library, [report], topic="t", generated_at=NOW).to_dict()

        assert data == _load_fixture("orientation_only.json")

    def test_structural_findings_plan_matches_fixture(self, tmp_path: Path):
        library = tmp_path / "library"
        topic_dir = library / "topics" / "t"
        topic_dir.mkdir(parents=True)
        report = _report(
            health_warnings=[],
            contested=[],
            broken_links=[
                BrokenLink(
                    source_file=topic_dir / "notes.md",
                    line_number=3,
                    link_text="[[missing]]",
                    target_slug="missing",
                )
            ],
            gaps=[
                "Mixed-source corpus synthesis is missing for a multi-source topic.",
                "No topic diff is available yet.",
                "No topic trend summary is available yet.",
            ],
            next_actions=[],
            verify=VerifyRollup(insights_total=0, checked=0, clean=0),
            freshness=SynthesisFreshness(
                checked=1,
                stale=[{"synthesis": "t_Corpus_Synthesis.md", "behind": 1, "gap_days": 2}],
            ),
        )

        data = build_next_action_plan(library, [report], topic="t", generated_at=NOW).to_dict()

        assert data == _load_fixture("structural_findings.json")

    def test_builds_bounded_actions_from_structural_findings(self, tmp_path: Path):
        library = tmp_path / "library"
        topic_dir = library / "topics" / "t"
        topic_dir.mkdir(parents=True)
        report = _report(
            contested=[],
            gaps=[
                "Mixed-source corpus synthesis is missing for a multi-source topic.",
                "No topic diff is available yet.",
                "No topic trend summary is available yet.",
            ],
            next_actions=[],
            verify=VerifyRollup(insights_total=0, checked=0, clean=0),
            freshness=SynthesisFreshness(
                checked=1,
                stale=[{"synthesis": "t_Corpus_Synthesis.md", "behind": 1, "gap_days": 2}],
            ),
        )

        plan = build_next_action_plan(library, [report], topic="t", generated_at=NOW)
        data = plan.to_dict()

        assert data["schema_version"] == "next-actions.v1"
        assert data["topic"] == "t"
        kinds = [action["kind"] for action in data["actions"]]
        assert kinds[:3] == [
            "build_corpus_synthesis",
            "refresh_synthesis",
            "regenerate_orientation",
        ]
        assert "gap_discovery_preview" in kinds
        assert "write_diff" in kinds
        assert "write_trends" in kinds
        for action in data["actions"]:
            assert action["command"][0] == "distill"
            assert action["verifier"]["command"] == [
                "distill",
                "audit",
                "t",
                "--next-actions",
                "--json",
            ]
            assert action["loop"]["acceptance_metric"] == "verifier_passed"

    def test_emits_reexport_okf_when_bundle_predates_native_corpus(self, tmp_path: Path) -> None:
        library = tmp_path / "library"
        topic_dir = library / "topics" / "t"
        bundle_dir = tmp_path / "output" / "okf-t"
        topic_dir.mkdir(parents=True)
        (topic_dir / "fresh.md").write_text("# fresh\n", encoding="utf-8")
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "index.md").write_text("---\n---\n", encoding="utf-8")
        (bundle_dir / "log.md").write_text("---\n---\n", encoding="utf-8")
        old = time.time() - 100
        for path in (bundle_dir / "index.md", bundle_dir / "log.md"):
            os.utime(path, (old, old))

        report = _report(
            contested=[],
            gaps=["No major research gaps detected from the local corpus heuristics."],
            next_actions=[],
            verify=VerifyRollup(insights_total=0, checked=0, clean=0),
        )
        plan = build_next_action_plan(library, [report], topic="t", generated_at=NOW)
        kinds = [action.kind for action in plan.actions]
        assert "reexport_okf" in kinds
        okf_action = next(action for action in plan.actions if action.kind == "reexport_okf")
        assert okf_action.command == [
            "distill",
            "export",
            "t",
            "--what",
            "bundle",
            "--format",
            "okf",
        ]
        assert okf_action.estimated_cost_usd == 0.0


def test_audit_command_report_only(tmp_path, monkeypatch):
    """End-to-end command run over a seeded topic: report artifact lands, no prompt."""
    from typer.testing import CliRunner

    from distill import cli
    from distill.config import DistillConfig

    config = DistillConfig(xai_api_key="t", distill_output_dir=tmp_path / "library")
    monkeypatch.setattr("distill.commands.audit.get_config", lambda: config)
    topic_dir = config.topic_dir("t")
    _seed_insight(
        topic_dir,
        "papers/p1",
        sidecar={
            "checked": 1,
            "unsupported": [{"token": "5.5", "kind": "decimal", "context": "x"}],
        },
    )
    _seed_video_transcript(
        topic_dir,
        "Creator",
        "long-thin",
        metadata={"title": "Long Thin", "duration": 3600},
        transcript="too short",
    )

    result = CliRunner().invoke(cli.app, ["audit", "t", "--report-only"])

    assert result.exit_code == 0, result.output
    audit_path = topic_dir / "t_Audit.md"
    assert audit_path.exists()
    audit_text = audit_path.read_text(encoding="utf-8")
    assert "5.5" in audit_text
    assert "Thin video transcripts" in audit_text
    assert "Long Thin" in audit_text
    assert "finding(s)" in result.output


def test_audit_command_next_actions_json(tmp_path, monkeypatch):
    """Command-local JSON emits a clean next-action envelope for loop runners."""
    from typer.testing import CliRunner

    from distill import cli
    from distill.config import DistillConfig

    config = DistillConfig(xai_api_key="t", distill_output_dir=tmp_path / "library")
    monkeypatch.setattr("distill.commands.audit.get_config", lambda: config)
    topic_dir = config.topic_dir("t")
    _seed_insight(topic_dir, "papers/p1", sidecar={"checked": 1, "unsupported": []})

    result = CliRunner().invoke(cli.app, ["audit", "t", "--next-actions", "--json"])

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert parsed["status"] == "ok"
    data = parsed["data"]
    assert data["schema_version"] == "next-actions.v1"
    assert data["topic"] == "t"
    assert (topic_dir / "t_Audit.md").exists()
    assert any(action["kind"] == "regenerate_orientation" for action in data["actions"])
