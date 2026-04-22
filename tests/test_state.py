"""Tests for distill.state."""

import json

from distill.state import ChannelState


class TestChannelStateInit:
    def test_creates_empty_state(self, tmp_path):
        """State initializes with empty data when no file exists."""
        state = ChannelState(tmp_path / "state.json")
        assert state.get_processed_count() == 0
        assert state.get_last_refresh() is None

    def test_loads_existing_state(self, tmp_path):
        """State loads from existing file."""
        state_file = tmp_path / "state.json"
        state_file.write_text(
            json.dumps(
                {
                    "processed_videos": {
                        "vid1": {
                            "title": "T",
                            "upload_date": "20250101",
                            "processed_at": "2025-01-01T00:00:00",
                        }
                    },
                    "last_refresh": "2025-01-01T00:00:00",
                }
            ),
            encoding="utf-8",
        )
        state = ChannelState(state_file)
        assert state.get_processed_count() == 1
        assert state.is_processed("vid1")

    def test_handles_corrupted_json(self, tmp_path):
        """State recovers from corrupted file."""
        state_file = tmp_path / "state.json"
        state_file.write_text("{broken json", encoding="utf-8")
        state = ChannelState(state_file)
        assert state.get_processed_count() == 0
        # Backup should exist
        assert (tmp_path / "state.json.bak").exists()

    def test_handles_missing_keys(self, tmp_path):
        """State handles file missing required keys."""
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({"some_other_key": True}), encoding="utf-8")
        state = ChannelState(state_file)
        assert state.get_processed_count() == 0
        assert state.get_last_refresh() is None

    def test_handles_invalid_processed_videos_type(self, tmp_path):
        """State handles processed_videos being wrong type."""
        state_file = tmp_path / "state.json"
        state_file.write_text(
            json.dumps(
                {
                    "processed_videos": "not a dict",
                    "last_refresh": None,
                }
            ),
            encoding="utf-8",
        )
        state = ChannelState(state_file)
        assert state.get_processed_count() == 0


class TestMarkProcessed:
    def test_mark_processed(self, tmp_path):
        """Marking a video as processed works."""
        state = ChannelState(tmp_path / "state.json")
        state.mark_processed("vid1", "Title 1", "20250101")
        assert state.is_processed("vid1")
        assert state.get_processed_count() == 1
        assert state.get_last_refresh() is not None

    def test_mark_multiple_videos(self, tmp_path):
        """Marking multiple videos works."""
        state = ChannelState(tmp_path / "state.json")
        state.mark_processed("vid1", "Title 1", "20250101")
        state.mark_processed("vid2", "Title 2", "20250102")
        state.mark_processed("vid3", "Title 3", "20250103")
        assert state.get_processed_count() == 3
        assert state.is_processed("vid1")
        assert state.is_processed("vid2")
        assert state.is_processed("vid3")

    def test_mark_same_video_twice(self, tmp_path):
        """Marking the same video twice overwrites (no duplicate)."""
        state = ChannelState(tmp_path / "state.json")
        state.mark_processed("vid1", "Title 1", "20250101")
        state.mark_processed("vid1", "Title 1 Updated", "20250101")
        assert state.get_processed_count() == 1

    def test_persists_to_disk(self, tmp_path):
        """State changes are written to disk."""
        state_file = tmp_path / "state.json"
        state = ChannelState(state_file)
        state.mark_processed("vid1", "Title 1", "20250101")

        # Load fresh from disk
        state2 = ChannelState(state_file)
        assert state2.is_processed("vid1")
        assert state2.get_processed_count() == 1

    def test_creates_parent_dirs(self, tmp_path):
        """Saving creates parent directories if needed."""
        deep_path = tmp_path / "a" / "b" / "c" / "state.json"
        state = ChannelState(deep_path)
        state.mark_processed("vid1", "Title 1", "20250101")
        assert deep_path.exists()


class TestIsProcessed:
    def test_unprocessed_video(self, tmp_path):
        """Checking an unprocessed video returns False."""
        state = ChannelState(tmp_path / "state.json")
        assert state.is_processed("nonexistent") is False

    def test_processed_video(self, tmp_path):
        """Checking a processed video returns True."""
        state = ChannelState(tmp_path / "state.json")
        state.mark_processed("vid1", "T", "20250101")
        assert state.is_processed("vid1") is True


class TestGetLastRefresh:
    def test_no_refresh(self, tmp_path):
        """Last refresh is None when nothing processed."""
        state = ChannelState(tmp_path / "state.json")
        assert state.get_last_refresh() is None

    def test_refresh_updates(self, tmp_path):
        """Last refresh updates when a video is marked."""
        state = ChannelState(tmp_path / "state.json")
        state.mark_processed("vid1", "T", "20250101")
        refresh = state.get_last_refresh()
        assert refresh is not None
        assert "T" in refresh  # ISO format contains T separator


class TestGetAnalysisMode:
    def test_returns_mode_for_processed_video(self, tmp_path):
        state = ChannelState(tmp_path / "state.json")
        state.mark_processed("vid1", "Title", "20250101", analysis_mode="scan")
        assert state.get_analysis_mode("vid1") == "scan"

    def test_returns_full_for_legacy_video(self, tmp_path):
        """Videos processed before analysis_mode was tracked default to 'full'."""
        state_file = tmp_path / "state.json"
        state_file.write_text(
            json.dumps(
                {
                    "processed_videos": {
                        "vid1": {
                            "title": "T",
                            "upload_date": "20250101",
                            "processed_at": "2025-01-01T00:00:00",
                        }
                    },
                    "last_refresh": "2025-01-01T00:00:00",
                }
            ),
            encoding="utf-8",
        )
        state = ChannelState(state_file)
        assert state.get_analysis_mode("vid1") == "full"

    def test_returns_full_for_unknown_video(self, tmp_path):
        state = ChannelState(tmp_path / "state.json")
        assert state.get_analysis_mode("nonexistent") == "full"


class TestCorruptedStateRecovery:
    def test_empty_file_recovers(self, tmp_path):
        """An empty state file is treated as corrupted."""
        state_file = tmp_path / "state.json"
        state_file.write_text("", encoding="utf-8")
        state = ChannelState(state_file)
        assert state.get_processed_count() == 0

    def test_partial_json_recovers(self, tmp_path):
        state_file = tmp_path / "state.json"
        state_file.write_text('{"processed_videos": {', encoding="utf-8")
        state = ChannelState(state_file)
        assert state.get_processed_count() == 0
        assert (tmp_path / "state.json.bak").exists()

    def test_can_save_after_recovery(self, tmp_path):
        """After recovering from corruption, new data can be saved."""
        state_file = tmp_path / "state.json"
        state_file.write_text("BROKEN", encoding="utf-8")
        state = ChannelState(state_file)
        state.mark_processed("vid1", "Title", "20250101")
        state2 = ChannelState(state_file)
        assert state2.is_processed("vid1")
