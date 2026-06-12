"""Tests for the prompt registry and the audit's staleness rollup."""

from __future__ import annotations

from pathlib import Path

from distill.pipeline.audit import StalenessRollup, collect_staleness
from distill.prompts.registry import PROMPT_IDS, current_version, parse_prompt_id


class TestRegistry:
    def test_parse_prompt_id(self):
        assert parse_prompt_id("analysis.podcast.v1") == ("analysis.podcast", 1)
        assert parse_prompt_id("synthesis.paper.v3") == ("synthesis.paper", 3)
        assert parse_prompt_id("ask.v1") == ("ask", 1)
        assert parse_prompt_id("not-a-prompt-id") is None
        assert parse_prompt_id("family.vX") is None

    def test_every_registry_entry_is_parseable_and_self_consistent(self):
        """The registry must never carry an id whose family key disagrees with
        the id itself -- that would silently break staleness comparison."""
        for family, prompt_id in PROMPT_IDS.items():
            parsed = parse_prompt_id(prompt_id)
            assert parsed is not None, f"unparseable registry entry: {prompt_id}"
            assert parsed[0] == family, f"family mismatch: {family} -> {prompt_id}"

    def test_current_version(self):
        assert current_version("synthesis.paper") == 3
        assert current_version("nonexistent.family") is None


def _insight(topic_dir: Path, name: str, prompt_id: str | None) -> None:
    d = topic_dir / "papers" / name
    d.mkdir(parents=True, exist_ok=True)
    fm = f'---\ntitle: "{name}"\n'
    if prompt_id is not None:
        fm += f'prompt_id: "{prompt_id}"\n'
    fm += "---\n\nbody\n"
    (d / f"{name}_Insights.md").write_text(fm, encoding="utf-8")


class TestCollectStaleness:
    def test_mixed_corpus(self, tmp_path):
        topic_dir = tmp_path / "t"
        _insight(topic_dir, "fresh", PROMPT_IDS["synthesis.paper"])  # current
        _insight(topic_dir, "old", "synthesis.paper.v1")  # stale (current is v3)
        _insight(topic_dir, "ancient", None)  # pre-provenance
        _insight(topic_dir, "orphan", "retired.family.v9")  # unknown family

        rollup = collect_staleness(topic_dir)

        assert rollup.current == 1
        assert len(rollup.stale) == 1
        assert rollup.stale[0]["recorded"] == "synthesis.paper.v1"
        assert rollup.stale[0]["current"] == PROMPT_IDS["synthesis.paper"]
        assert rollup.no_provenance == 1
        assert rollup.unknown_family == 1

    def test_empty_topic(self, tmp_path):
        rollup = collect_staleness(tmp_path / "empty")
        assert rollup == StalenessRollup()

    def test_stale_counts_in_audit_render(self, tmp_path):
        from distill.pipeline.audit import AuditReport, VerifyRollup, render_audit_md

        topic_dir = tmp_path / "t"
        _insight(topic_dir, "old", "synthesis.paper.v1")
        report = AuditReport(
            topic="t",
            health_warnings=[],
            contested=[],
            broken_links=[],
            gaps=[],
            next_actions=[],
            verify=VerifyRollup(insights_total=1, checked=0, clean=0),
            staleness=collect_staleness(topic_dir),
        )

        md = render_audit_md(report, now_iso="2026-06-12T00:00:00Z")

        assert "## Prompt staleness" in md
        assert "stale: 1" in md
        assert "synthesis.paper.v1" in md
        assert report.issue_count == 1  # the stale artifact counts as a finding
