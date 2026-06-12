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

    def test_reanalysis_commands_route_by_source(self, tmp_path):
        from distill.pipeline.audit import reanalysis_commands

        lib = tmp_path
        # GitHub-sourced insight: exact ingest command.
        d1 = lib / "topics" / "t" / "repos" / "r"
        d1.mkdir(parents=True)
        (d1 / "r_Insights.md").write_text(
            '---\nsource: "github"\nurl: "https://github.com/o/r"\n'
            'prompt_id: "analysis.github_repo.v1"\n---\n\nbody',
            encoding="utf-8",
        )
        # arXiv-sourced insight: papers command with the id.
        d2 = lib / "topics" / "t" / "papers" / "p"
        d2.mkdir(parents=True)
        (d2 / "p_Insights.md").write_text(
            '---\nsource: "arxiv"\nurl: "https://arxiv.org/abs/2604.11544v1"\n---\n\nbody',
            encoding="utf-8",
        )
        # No URL: named with a fallback note.
        d3 = lib / "topics" / "t" / "media" / "m"
        d3.mkdir(parents=True)
        (d3 / "m_Insights.md").write_text('---\nsource: "media"\n---\n\nbody', encoding="utf-8")

        stale = [
            {"insight": "topics/t/repos/r/r_Insights.md", "recorded": "analysis.github_repo.v1"},
            {"insight": "topics/t/papers/p/p_Insights.md", "recorded": "synthesis.paper.v2"},
            {"insight": "topics/t/media/m/m_Insights.md", "recorded": "analysis.media.v1"},
        ]
        lines = reanalysis_commands(lib, "t", stale)

        assert lines[0] == (
            "distill ingest https://github.com/o/r --topic t  # was analysis.github_repo.v1"
        )
        assert lines[1].startswith('distill papers "2604.11544v1" --topic t --limit 1')
        assert lines[2].startswith("# topics/t/media/m/m_Insights.md")

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
