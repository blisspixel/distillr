"""Tests for synthesis freshness: stale-vs-sources detection + shadowed legacy files.

The finding classes both come from the dogfood library review (2026-06-12):
syntheses generated weeks before sources that now sit under them, and
superseded legacy-named syntheses lingering beside their modern replacements.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from distill.pipeline.audit import (
    AuditReport,
    SynthesisFreshness,
    VerifyRollup,
    collect_synthesis_freshness,
    render_audit_md,
)


def _write(path: Path, generated_at: str | None, body: str = "body") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    front = f'---\ntitle: "x"\ngenerated_at: "{generated_at}"\n---\n' if generated_at else ""
    path.write_text(front + body, encoding="utf-8")


def _report(freshness: SynthesisFreshness) -> AuditReport:
    return AuditReport(
        topic="t",
        health_warnings=[],
        contested=[],
        broken_links=[],
        gaps=[],
        next_actions=[],
        verify=VerifyRollup(insights_total=0, checked=0, clean=0),
        freshness=freshness,
    )


class TestCollect:
    def test_fresh_synthesis_no_findings(self, tmp_path):
        _write(tmp_path / "papers" / "p1" / "p1_Insights.md", "2026-06-01T10:00:00")
        _write(tmp_path / "t_Paper_Synthesis.md", "2026-06-01T10:05:00")
        f = collect_synthesis_freshness(tmp_path, "t")
        assert f.checked == 1
        assert f.stale == []
        assert f.shadowed_legacy == []

    def test_synthesis_older_than_sources_is_stale(self, tmp_path):
        _write(tmp_path / "t_Corpus_Synthesis.md", "2026-04-20T09:00:00")
        _write(tmp_path / "papers" / "p1" / "p1_Insights.md", "2026-04-19T10:00:00")
        _write(tmp_path / "papers" / "p2" / "p2_Insights.md", "2026-06-11T20:00:00")
        _write(tmp_path / "papers" / "p3" / "p3_Insights.md", "2026-06-11T21:00:00")
        f = collect_synthesis_freshness(tmp_path, "t")
        assert len(f.stale) == 1
        item = f.stale[0]
        assert item["synthesis"] == "t_Corpus_Synthesis.md"
        assert item["behind"] == 2  # only the two insights newer than the synthesis
        assert item["gap_days"] == 52

    def test_same_run_ordering_tolerated(self, tmp_path):
        # Insights are written minutes before the synthesis in one run; and
        # cloud-sync can touch mtimes minutes apart. Neither is staleness.
        _write(tmp_path / "papers" / "p1" / "p1_Insights.md", "2026-06-01T10:30:00")
        _write(tmp_path / "t_Paper_Synthesis.md", "2026-06-01T10:00:00")
        f = collect_synthesis_freshness(tmp_path, "t")
        assert f.stale == []

    def test_shadowed_legacy_flagged(self, tmp_path):
        # kilo-tkg in the dogfood library: paper_synthesis.md (April) beside
        # kilo_tkg_Paper_Synthesis.md (June) -- two confident syntheses.
        _write(tmp_path / "t_Paper_Synthesis.md", "2026-06-11T20:00:00")
        _write(tmp_path / "paper_synthesis.md", "2026-04-20T09:00:00")
        f = collect_synthesis_freshness(tmp_path, "t")
        assert f.shadowed_legacy == [
            {"active": "t_Paper_Synthesis.md", "legacy": "paper_synthesis.md"}
        ]

    def test_no_synthesis_checked_zero(self, tmp_path):
        _write(tmp_path / "papers" / "p1" / "p1_Insights.md", "2026-06-01T10:00:00")
        f = collect_synthesis_freshness(tmp_path, "t")
        assert f.checked == 0
        assert f.stale == []

    def test_mtime_fallback_for_unstamped_files(self, tmp_path):
        # Legacy artifacts predate generated_at stamping; mtime is the fallback.
        synth = tmp_path / "corpus_synthesis.md"
        _write(synth, None)
        insight = tmp_path / "papers" / "p1" / "p1_Insights.md"
        _write(insight, None)
        old = time.time() - 60 * 86400
        os.utime(synth, (old, old))
        f = collect_synthesis_freshness(tmp_path, "t")
        assert len(f.stale) == 1
        assert f.stale[0]["gap_days"] >= 59

    def test_missing_topic_dir_is_empty(self, tmp_path):
        f = collect_synthesis_freshness(tmp_path / "nope", "t")
        assert f == SynthesisFreshness()

    def test_paper_synthesis_not_staled_by_newer_videos(self, tmp_path):
        # Caught live on the dogfood library: agentic-harness's paper synthesis
        # flagged because video insights landed hours later. Each synthesis kind
        # compares against the source subtree it actually synthesizes.
        _write(tmp_path / "papers" / "p1" / "p1_Insights.md", "2026-06-09T10:00:00")
        _write(tmp_path / "t_Paper_Synthesis.md", "2026-06-09T11:00:00")
        _write(
            tmp_path / "channels" / "c" / "videos" / "v1" / "v1_Insights.md", "2026-06-09T15:00:00"
        )
        f = collect_synthesis_freshness(tmp_path, "t")
        assert f.stale == []

    def test_site_topic_synthesis_tracks_only_site_sources(self, tmp_path):
        _write(tmp_path / "t_Site_Synthesis.md", "2026-06-09T11:00:00")
        _write(
            tmp_path / "sites" / "example.com" / "pages" / "p1" / "p1_Insights.md",
            "2026-06-11T15:00:00",
        )
        _write(
            tmp_path / "channels" / "c" / "videos" / "v1" / "v1_Insights.md",
            "2026-06-12T15:00:00",
        )

        f = collect_synthesis_freshness(tmp_path, "t")

        assert f.checked == 1
        assert f.stale == [{"synthesis": "t_Site_Synthesis.md", "behind": 1, "gap_days": 2}]

    def test_corpus_synthesis_staled_by_any_source(self, tmp_path):
        _write(tmp_path / "t_Corpus_Synthesis.md", "2026-06-09T11:00:00")
        _write(
            tmp_path / "channels" / "c" / "videos" / "v1" / "v1_Insights.md", "2026-06-11T15:00:00"
        )
        f = collect_synthesis_freshness(tmp_path, "t")
        assert len(f.stale) == 1
        assert f.stale[0]["synthesis"] == "t_Corpus_Synthesis.md"


class TestRenderAndCount:
    def test_stale_synthesis_counts_as_finding_and_renders(self):
        f = SynthesisFreshness(
            checked=1,
            stale=[{"synthesis": "t_Corpus_Synthesis.md", "behind": 3, "gap_days": 52}],
            shadowed_legacy=[{"active": "t_Paper_Synthesis.md", "legacy": "paper_synthesis.md"}],
        )
        report = _report(f)
        assert report.issue_count == 2
        md = render_audit_md(report, now_iso="2026-06-12T00:00:00Z")
        assert "## Synthesis freshness" in md
        assert "predates 3 newer source(s) by 52d" in md
        assert "distill corpus t" in md
        assert "`paper_synthesis.md` is superseded by `t_Paper_Synthesis.md`" in md

    def test_all_current_renders_clean_line(self):
        md = render_audit_md(_report(SynthesisFreshness(checked=2)), now_iso="x")
        assert "All 2 synthesis artifact(s) current" in md

    def test_no_synthesis_points_at_gaps(self):
        md = render_audit_md(_report(SynthesisFreshness()), now_iso="x")
        assert "No topic-level synthesis artifacts yet" in md


class TestSurfacing:
    def test_topic_claude_md_warns_on_stale_synthesis(self, tmp_path):
        # Agents auto-load CLAUDE.md; that is where the confident-but-stale
        # hazard has to be visible, not only in an audit nobody scheduled.
        from distill.library.claude_md import render_topic_claude_md

        _write(tmp_path / "t_Topic_Synthesis.md", "2026-04-20T09:00:00", body="Lede sentence.")
        _write(
            tmp_path / "channels" / "c" / "videos" / "v1" / "v1_Insights.md",
            "2026-06-11T20:00:00",
        )
        md = render_topic_claude_md(tmp_path, "t", now_iso="2026-06-12T00:00:00Z")
        assert "Warning -- stale synthesis" in md
        assert "predates 1 newer source(s) by 52d" in md
        assert "distill corpus t" in md

    def test_topic_claude_md_clean_when_fresh(self, tmp_path):
        from distill.library.claude_md import render_topic_claude_md

        _write(tmp_path / "papers" / "p1" / "p1_Insights.md", "2026-06-11T20:00:00")
        _write(tmp_path / "t_Topic_Synthesis.md", "2026-06-11T20:05:00", body="Lede sentence.")
        md = render_topic_claude_md(tmp_path, "t", now_iso="2026-06-12T00:00:00Z")
        assert "stale synthesis" not in md

    def test_dashboard_stale_synthesis_warnings(self, tmp_path):
        from distill.config import DistillConfig
        from distill.pipeline.dashboard_data import stale_synthesis_warnings

        config = DistillConfig(xai_api_key="t", distill_output_dir=tmp_path / "library")
        topic_dir = config.topic_dir("music")
        _write(topic_dir / "music_Corpus_Synthesis.md", "2026-04-21T09:00:00")
        _write(topic_dir / "papers" / "p1" / "p1_Insights.md", "2026-06-11T20:00:00")
        lines = stale_synthesis_warnings(config, ["music"])
        assert len(lines) == 1
        assert "music music_Corpus_Synthesis.md predates 1 newer source(s)" in lines[0]
        assert "distill corpus music" in lines[0]
