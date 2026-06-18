"""Tests for distill.pipeline.audit and the audit command (deterministic health surface)."""

from __future__ import annotations

import json
from pathlib import Path

from distill.pipeline.audit import (
    AuditReport,
    SynthesisFreshness,
    VerifyRollup,
    build_next_action_plan,
    collect_verify_rollup,
    render_audit_md,
    write_audit_artifact,
)

NOW = "2026-06-11T20:00:00Z"


def _seed_insight(topic_dir: Path, rel: str, *, sidecar: dict | None = None) -> None:
    d = topic_dir / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{d.name}_Insights.md").write_text('---\nsource_id: "x"\n---\n\nbody', encoding="utf-8")
    if sidecar is not None:
        (d / f"{d.name}_Verify.json").write_text(json.dumps(sidecar), encoding="utf-8")


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
        # A topic synthesis with no sidecar (never checked).
        (topic / "t_Topic_Synthesis.md").write_text("syn", encoding="utf-8")

        rollup = collect_verify_rollup(topic)

        assert rollup.insights_total == 1
        assert rollup.synthesis_total == 3
        assert rollup.synthesis_checked == 2
        assert rollup.synthesis_clean == 1
        assert rollup.synthesis_never_checked == 1
        # The corpus-synthesis flag is in the shared list, labelled by artifact.
        assert any(f["token"] == "9.9" for f in rollup.flagged)


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
        assert "`99.9` (decimal)" in out
        assert "synthesis is 120 days old" in out
        assert "**X** (concept): 2 helpful / 1 harmful" in out
        assert "All wiki-links resolve." in out
        assert "single-source" in out
        assert "distill discover --from-gaps --topic t --preview" in out

    def test_issue_count(self):
        assert _report().issue_count == 4  # 1 warning + 1 contested + 1 gap + 1 flagged

    def test_write_artifact_with_frontmatter(self, tmp_path: Path):
        path = write_audit_artifact(tmp_path, _report(), now_iso=NOW)
        assert path.name == "t_Audit.md"
        text = path.read_text(encoding="utf-8")
        assert 'type: "audit"' in text
        assert "findings: 4" in text


class TestNextActionPlan:
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


def test_audit_command_report_only(tmp_path, monkeypatch):
    """End-to-end command run over a seeded topic: report artifact lands, no prompt."""
    from typer.testing import CliRunner

    from distill import _cli_impl, cli
    from distill.config import DistillConfig

    config = DistillConfig(xai_api_key="t", distill_output_dir=tmp_path / "library")
    monkeypatch.setattr(_cli_impl, "get_config", lambda: config)
    topic_dir = config.topic_dir("t")
    _seed_insight(
        topic_dir,
        "papers/p1",
        sidecar={
            "checked": 1,
            "unsupported": [{"token": "5.5", "kind": "decimal", "context": "x"}],
        },
    )

    result = CliRunner().invoke(cli.app, ["audit", "t", "--report-only"])

    assert result.exit_code == 0, result.output
    audit_path = topic_dir / "t_Audit.md"
    assert audit_path.exists()
    assert "5.5" in audit_path.read_text(encoding="utf-8")
    assert "finding(s)" in result.output


def test_audit_command_next_actions_json(tmp_path, monkeypatch):
    """Command-local JSON emits a clean next-action envelope for loop runners."""
    from typer.testing import CliRunner

    from distill import _cli_impl, cli
    from distill.config import DistillConfig

    config = DistillConfig(xai_api_key="t", distill_output_dir=tmp_path / "library")
    monkeypatch.setattr(_cli_impl, "get_config", lambda: config)
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
