"""Tests for distill.state."""

import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from distill.library.state import ChannelState


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

    def test_invalid_video_id_is_refused_before_state_mutation(self, tmp_path):
        state_file = tmp_path / "state.json"
        state = ChannelState(state_file)

        with pytest.raises(ValueError, match="invalid YouTube video id") as exc_info:
            state.mark_processed("bad?token=STATE-CANARY", "Title", "20250101")

        assert "STATE-CANARY" not in str(exc_info.value)
        assert state.get_processed_count() == 0
        assert not state_file.exists()

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

    def test_stale_instances_merge_distinct_video_receipts(self, tmp_path):
        state_file = tmp_path / "state.json"
        first = ChannelState(state_file)
        second = ChannelState(state_file)

        first.mark_processed("vid1", "Title 1", "20250101")
        second.mark_processed("vid2", "Title 2", "20250102")

        persisted = ChannelState(state_file)
        assert persisted.processed_video_ids() == ["vid1", "vid2"]
        assert second.processed_video_ids() == ["vid1", "vid2"]

    def test_concurrent_instances_preserve_every_video_receipt(self, tmp_path):
        state_file = tmp_path / "state.json"
        writers = 12
        barrier = threading.Barrier(writers)
        states = [ChannelState(state_file) for _ in range(writers)]

        def mark(index: int) -> None:
            barrier.wait(timeout=10)
            states[index].mark_processed(f"vid{index}", f"Title {index}", "20250101")

        with ThreadPoolExecutor(max_workers=writers) as executor:
            list(executor.map(mark, range(writers)))

        assert set(ChannelState(state_file).processed_video_ids()) == {
            f"vid{index}" for index in range(writers)
        }

    def test_cross_process_instances_preserve_every_video_receipt(self, tmp_path):
        state_file = tmp_path / "state.json"
        start_file = tmp_path / "start"
        script = "\n".join(
            [
                "import sys, time",
                "from pathlib import Path",
                "from distill.library.state import ChannelState",
                "state_file = Path(sys.argv[1])",
                "start_file = Path(sys.argv[2])",
                "index = int(sys.argv[3])",
                "deadline = time.monotonic() + 10",
                "while not start_file.exists():",
                "    if time.monotonic() >= deadline:",
                "        raise TimeoutError('start barrier timed out')",
                "    time.sleep(0.01)",
                "ChannelState(state_file).mark_processed(",
                "    f'vid{index}', f'Title {index}', '20250101'",
                ")",
            ]
        )
        writers = 8
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", script, str(state_file), str(start_file), str(index)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for index in range(writers)
        ]
        start_file.touch()

        failures: list[str] = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=20)
            if process.returncode:
                failures.append(f"exit={process.returncode} stdout={stdout!r} stderr={stderr!r}")

        assert failures == []
        assert set(ChannelState(state_file).processed_video_ids()) == {
            f"vid{index}" for index in range(writers)
        }

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

    def test_invalid_utf8_recovers(self, tmp_path):
        state_file = tmp_path / "state.json"
        state_file.write_bytes(b"\xff")

        state = ChannelState(state_file)

        assert state.get_processed_count() == 0
        assert state_file.with_suffix(".json.bak").read_bytes() == b"\xff"

    def test_mutation_recovers_corruption_created_after_load(self, tmp_path):
        state_file = tmp_path / "state.json"
        state = ChannelState(state_file)
        state.mark_processed("first", "First", "20260718")
        state_file.write_text("not-json", encoding="utf-8")

        state.mark_processed("second", "Second", "20260718")

        assert state.processed_video_ids() == ["second"]
        assert state_file.with_name("state.json.bak").read_text(encoding="utf-8") == "not-json"
