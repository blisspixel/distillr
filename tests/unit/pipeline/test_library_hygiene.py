"""Tests for the library-level hygiene rollup (0.12.12).

The dev-library review found 11 of 53 topics were unlabeled test leftovers,
one a broken reparse point, and several real corpora invisible to agents --
all indistinguishable from production topics in every existing view. The
rollup ends every `audit all` run with the library-wide facts.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from distill.pipeline.audit import (
    LibraryHygiene,
    ProfileHealth,
    collect_library_hygiene,
    collect_profile_health,
    render_library_audit_md,
)
from distill.pipeline.profile_run import profile_run_state_path


def _topic(library: Path, name: str, *, sources: int = 0, orientation: bool = False) -> Path:
    d = library / "topics" / name
    d.mkdir(parents=True, exist_ok=True)
    for i in range(sources):
        p = d / "papers" / f"p{i}" / f"p{i}_Insights.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("---\n---\nbody", encoding="utf-8")
    if orientation:
        (d / "CLAUDE.md").write_text("# t", encoding="utf-8")
    return d


def _profile(
    library: Path,
    name: str,
    *,
    topic: str | None = None,
    cadence: str = "daily",
    stale_after: str = "P1D",
    with_goal: bool = True,
) -> Path:
    topic = topic or name
    if with_goal:
        goal = library / "goals" / f"{name}.md"
        goal.parent.mkdir(parents=True, exist_ok=True)
        goal.write_text("# Goal", encoding="utf-8")
    path = library / "profiles" / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "schema_version: research-profile.v1",
                f"name: {name}",
                f"topic: {topic}",
                f"goal_file: goals/{name}.md",
                "cost_mode: no-metered",
                "freshness:",
                f"  cadence: {cadence}",
                f"  stale_after: {stale_after}",
                "queries:",
                "  - agent loops",
                "limits:",
                "  max_metered_usd: 0",
            ]
        ),
        encoding="utf-8",
    )
    return path


class TestCollect:
    def test_classifies_topic_states(self, tmp_path):
        _topic(tmp_path, "healthy", sources=3, orientation=True)
        _topic(tmp_path, "empty-one")
        _topic(tmp_path, "invisible", sources=2, orientation=False)
        _topic(tmp_path, "wwt-raw-test", sources=1, orientation=True)

        h = collect_library_hygiene(tmp_path)

        assert h.healthy == 2  # healthy + the test-named one (which is indexed)
        assert h.empty == ["empty-one"]
        assert h.unindexed == ["invisible"]
        assert h.test_named == ["wwt-raw-test"]
        assert h.issue_count == 2  # empty + unindexed; test-named is informational

    def test_missing_library_is_empty(self, tmp_path):
        assert collect_library_hygiene(tmp_path / "nope") == LibraryHygiene()

    def test_dot_dirs_and_files_skipped(self, tmp_path):
        (tmp_path / "topics").mkdir()
        (tmp_path / "topics" / ".history").mkdir()
        (tmp_path / "topics" / "stray.md").write_text("x", encoding="utf-8")
        h = collect_library_hygiene(tmp_path)
        assert h == LibraryHygiene()

    def test_test_name_patterns(self, tmp_path):
        for name in ("validate090", "podcast-validation", "scratch", "wwt-live-test", "my-tests"):
            _topic(tmp_path, name, sources=1, orientation=True)
        _topic(tmp_path, "protest-history", sources=1, orientation=True)  # no false positive

        h = collect_library_hygiene(tmp_path)

        assert set(h.test_named) == {
            "validate090",
            "podcast-validation",
            "scratch",
            "wwt-live-test",
            "my-tests",
        }

    def test_profile_health_reports_stale_failures_and_thin_corpus(self, tmp_path):
        _profile(tmp_path, "agent-news", topic="agent-news", stale_after="P1D")
        state_path = profile_run_state_path(tmp_path, "agent-news")
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "schema_version": "profile-run-state.v1",
                    "last_run_at": "2026-06-17T00:00:00Z",
                    "last_failure": {"query:agent loops": {"status": "failed"}},
                }
            ),
            encoding="utf-8",
        )

        h = collect_profile_health(
            tmp_path,
            now=datetime(2026, 6, 19, 0, 0, tzinfo=UTC),
        )

        assert h.checked == 1
        assert h.issue_count == 3
        assert h.stale[0]["profile"] == "agent-news"
        assert h.last_failed[0]["failures"] == "1"
        assert h.thin_corpus[0]["topic"] == "agent-news"

    def test_profile_health_reports_invalid_and_missing_goal(self, tmp_path):
        _profile(tmp_path, "missing-goal", with_goal=False)
        bad = tmp_path / "profiles" / "bad.yaml"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("not: a valid profile", encoding="utf-8")

        h = collect_profile_health(tmp_path)

        assert h.checked == 1
        assert h.missing_goal[0]["profile"] == "missing-goal"
        assert h.invalid[0]["profile"] == "bad"


class TestRender:
    def test_sections_render_with_guidance(self):
        h = LibraryHygiene(
            healthy=40,
            empty=["tech"],
            unreadable=["broken"],
            unindexed=["kilo-x"],
            test_named=["wwt-raw-test"],
            profiles=ProfileHealth(
                checked=1,
                stale=[
                    {
                        "profile": "agent-news",
                        "last_run_at": "2026-06-17T00:00:00Z",
                        "stale_after": "P1D",
                    }
                ],
            ),
        )
        md = render_library_audit_md(h, now_iso="2026-06-12T00:00:00Z")
        assert "4 hygiene finding(s)" in md
        assert "Safe to delete" in md
        assert "`topics/tech/`" in md
        assert "distill claude-md --all" in md
        assert "informational" in md
        assert "Recurring profile health" in md
        assert "`agent-news`" in md

    def test_clean_library_renders_clean_line(self):
        md = render_library_audit_md(LibraryHygiene(healthy=5), now_iso="x")
        assert "readable, indexed, and non-empty" in md
