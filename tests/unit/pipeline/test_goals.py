"""Tests for persisted topic goals (the goal-file watch hook)."""

from __future__ import annotations

from distill.pipeline.goals import goal_refresh_command, load_topic_goals, save_topic_goal


class TestGoalPersistence:
    def test_roundtrip(self, tmp_path):
        save_topic_goal(
            tmp_path,
            "music",
            "help an AI become a great composer",
            goal_file="private/goal.md",
            site_seeds="private/seeds.json",
            now_iso="2026-06-12T05:00:00",
        )
        goals = load_topic_goals(tmp_path)
        assert goals["music"]["goal"] == "help an AI become a great composer"
        assert goals["music"]["goal_file"] == "private/goal.md"

    def test_update_replaces_topic_entry(self, tmp_path):
        save_topic_goal(tmp_path, "t", "old goal")
        save_topic_goal(tmp_path, "t", "new goal")
        goals = load_topic_goals(tmp_path)
        assert goals["t"]["goal"] == "new goal"
        assert len(goals) == 1

    def test_empty_goal_or_topic_not_saved(self, tmp_path):
        save_topic_goal(tmp_path, "", "goal")
        save_topic_goal(tmp_path, "t", "   ")
        assert load_topic_goals(tmp_path) == {}

    def test_corrupt_file_reads_empty(self, tmp_path):
        path = tmp_path / ".distill" / "goals.json"
        path.parent.mkdir(parents=True)
        path.write_text("{broken", encoding="utf-8")
        assert load_topic_goals(tmp_path) == {}
        # And a save after corruption recovers cleanly.
        save_topic_goal(tmp_path, "t", "goal")
        assert load_topic_goals(tmp_path)["t"]["goal"] == "goal"


class TestRefreshCommand:
    def test_goal_file_form_with_seeds(self):
        cmd = goal_refresh_command(
            "music", {"goal_file": "private/goal.md", "site_seeds": "private/seeds.json"}
        )
        assert cmd == (
            "distill discover --goal-file private/goal.md --topic music --preview "
            "--site-seeds private/seeds.json"
        )

    def test_inline_goal_form_uses_headline(self):
        cmd = goal_refresh_command(
            "t", {"goal": 'multi "quoted" line one\nline two', "goal_file": ""}
        )
        assert cmd == "distill discover \"multi 'quoted' line one\" --topic t --preview"


def test_catch_up_surfaces_goal_refreshes(tmp_path, monkeypatch):
    from distill.commands import _logic
    from distill.config import DistillConfig

    config = DistillConfig(xai_api_key="t", distill_output_dir=tmp_path / "library")
    save_topic_goal(config.library_dir, "music", "goal text", goal_file="g.md")
    save_topic_goal(config.library_dir, "other", "another goal")

    lines = _logic._print_goal_refreshes(config)
    assert len(lines) == 2
    assert lines[0].startswith("distill discover")

    filtered = _logic._print_goal_refreshes(config, topic_filter="music")
    assert filtered == ["distill discover --goal-file g.md --topic music --preview"]
