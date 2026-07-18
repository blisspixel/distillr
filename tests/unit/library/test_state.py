"""Tests for distill.library."""

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from distill.library import ChannelInfo, Library


class TestLibraryInit:
    def test_creates_empty_library(self, config):
        """Library initializes with empty data when no file exists."""
        lib = Library(config)
        assert lib.get_topics() == []
        assert lib.get_all_channels() == []

    def test_loads_existing_library(self, config):
        """Library loads from existing library.json."""
        lib_file = config.library_dir / "library.json"
        lib_file.parent.mkdir(parents=True, exist_ok=True)
        lib_file.write_text(
            json.dumps(
                {"topics": {"ai": {"channels": [{"url": "http://example.com", "name": "Ex"}]}}}
            ),
            encoding="utf-8",
        )

        lib = Library(config)
        assert lib.get_topics() == ["ai"]

    def test_handles_corrupted_json(self, config):
        """Library recovers from corrupted library.json."""
        lib_file = config.library_dir / "library.json"
        lib_file.parent.mkdir(parents=True, exist_ok=True)
        lib_file.write_text("not valid json {{{", encoding="utf-8")

        lib = Library(config)
        assert lib.get_topics() == []
        # Backup should exist
        assert (lib_file.with_suffix(".json.bak")).exists()

    def test_handles_invalid_utf8_and_reports_backup(self, config, caplog):
        lib_file = config.library_dir / "library.json"
        lib_file.parent.mkdir(parents=True, exist_ok=True)
        lib_file.write_bytes(b"\xff")

        with caplog.at_level(logging.WARNING, logger="distill.library.state"):
            lib = Library(config)

        backup = lib_file.with_suffix(".json.bak")
        assert lib.get_topics() == []
        assert backup.read_bytes() == b"\xff"
        assert str(backup) in caplog.text

    def test_repeated_corruption_preserves_each_backup(self, config):
        lib_file = config.library_dir / "library.json"
        lib_file.parent.mkdir(parents=True, exist_ok=True)
        lib_file.write_text("first broken", encoding="utf-8")
        Library(config)
        lib_file.write_text("second broken", encoding="utf-8")
        Library(config)

        assert lib_file.with_suffix(".json.bak").read_text(encoding="utf-8") == "first broken"
        assert lib_file.with_name("library.json.bak.1").read_text(encoding="utf-8") == (
            "second broken"
        )

    def test_oversized_state_is_quarantined_without_full_read(self, config, monkeypatch):
        from distill.library import state as state_module

        lib_file = config.library_dir / "library.json"
        lib_file.parent.mkdir(parents=True, exist_ok=True)
        lib_file.write_bytes(b"{}x")
        monkeypatch.setattr(state_module, "_MAX_STATE_BYTES", 2)

        lib = Library(config)

        assert lib.get_topics() == []
        assert lib_file.with_suffix(".json.bak").read_bytes() == b"{}x"

    def test_mutation_quarantines_corruption_created_after_initial_load(self, config, caplog):
        lib = Library(config)
        assert lib.add_channel("first", "https://example.com/first", "First") is True
        lib.library_file.write_bytes(b"\xff")

        with caplog.at_level(logging.WARNING, logger="distill.library.state"):
            added = lib.add_channel("second", "https://example.com/second", "Second")

        assert added is True
        assert lib.get_topics() == ["second"]
        assert lib.library_file.with_name("library.json.bak").read_bytes() == b"\xff"
        assert str(lib.library_file) in caplog.text

    def test_state_load_raises_when_corruption_cannot_be_quarantined(
        self, config, monkeypatch, caplog
    ):
        config.library_dir.mkdir(parents=True, exist_ok=True)
        lib_file = config.library_dir / "library.json"
        lib_file.write_text("not-json", encoding="utf-8")

        def fail_rename(_self, _target):
            raise OSError("backup unavailable")

        monkeypatch.setattr(Path, "rename", fail_rename)

        with (
            caplog.at_level(logging.ERROR, logger="distill.library.state"),
            pytest.raises(ValueError, match="Expecting value"),
        ):
            Library(config)

        assert "Cannot quarantine corrupt state" in caplog.text
        assert "backup unavailable" in caplog.text

    def test_handles_missing_topics_key(self, config):
        """Library handles JSON with missing 'topics' key."""
        lib_file = config.library_dir / "library.json"
        lib_file.parent.mkdir(parents=True, exist_ok=True)
        lib_file.write_text(json.dumps({"version": 1}), encoding="utf-8")

        lib = Library(config)
        assert lib.get_topics() == []

    def test_corpus_inventory_discovers_filesystem_without_registering(self, config):
        direct_videos = config.videos_dir("direct-topic", "Direct Channel")
        direct_videos.mkdir(parents=True)
        hidden_topic = config.topics_dir() / ".internal"
        hidden_topic.mkdir(parents=True)
        lib = Library(config)

        assert lib.get_corpus_topics() == ["direct-topic"]
        assert lib.get_corpus_channel_names("direct-topic") == ["Direct Channel"]
        assert lib.get_topics() == []
        assert lib.get_channels("direct-topic") == []

    def test_corpus_inventory_preserves_registered_order_and_adds_disk_entries(self, config):
        lib = Library(config)
        lib.add_channel("ai", "https://youtube.com/@Registered", "Registered")
        config.videos_dir("ai", "Direct").mkdir(parents=True)

        assert lib.get_corpus_topics() == ["ai"]
        assert lib.get_corpus_channel_names("ai") == ["Registered", "Direct"]


class TestAddChannel:
    def test_add_channel_new_topic(self, config):
        """Adding a channel to a new topic creates the topic."""
        lib = Library(config)
        result = lib.add_channel("ai", "https://youtube.com/@Test", "Test")
        assert result is True
        assert "ai" in lib.get_topics()
        channels = lib.get_channels("ai")
        assert len(channels) == 1
        assert channels[0].name == "Test"
        assert channels[0].url == "https://youtube.com/@Test"
        assert channels[0].topic == "ai"

    def test_add_channel_existing_topic(self, config):
        """Adding a second channel to existing topic works."""
        lib = Library(config)
        lib.add_channel("ai", "https://youtube.com/@A", "A")
        lib.add_channel("ai", "https://youtube.com/@B", "B")
        assert len(lib.get_channels("ai")) == 2

    def test_add_duplicate_channel(self, config):
        """Adding the same URL twice returns False."""
        lib = Library(config)
        lib.add_channel("ai", "https://youtube.com/@Test", "Test")
        result = lib.add_channel("ai", "https://youtube.com/@Test", "Test")
        assert result is False
        assert len(lib.get_channels("ai")) == 1

    def test_add_same_url_different_topics(self, config):
        """Same URL can be added to different topics."""
        lib = Library(config)
        lib.add_channel("ai", "https://youtube.com/@Test", "Test")
        result = lib.add_channel("security", "https://youtube.com/@Test", "Test")
        assert result is True

    def test_add_channel_creates_directory(self, config):
        """Adding a channel creates the directory structure."""
        lib = Library(config)
        lib.add_channel("ai", "https://youtube.com/@Test", "Test")
        assert config.videos_dir("ai", "Test").exists()

    def test_add_channel_sanitizes_topic_before_writing(self, config):
        """Path-like topics stay under the configured library topics directory."""
        lib = Library(config)

        result = lib.add_channel("../outside", "https://youtube.com/@Test", "Test")

        assert result is True
        assert "outside" in lib.get_topics()
        assert config.videos_dir("outside", "Test").exists()
        assert not (config.library_dir.parent / "outside").exists()

    def test_add_channel_persists_to_disk(self, config):
        """Library changes are written to disk."""
        lib = Library(config)
        lib.add_channel("ai", "https://youtube.com/@Test", "Test")

        # Load fresh from disk
        lib2 = Library(config)
        assert len(lib2.get_channels("ai")) == 1

    def test_stale_instances_merge_distinct_channel_updates(self, config):
        first = Library(config)
        second = Library(config)

        assert first.add_channel("ai", "https://youtube.com/@A", "A") is True
        assert second.add_channel("ai", "https://youtube.com/@B", "B") is True

        assert [channel.name for channel in Library(config).get_channels("ai")] == ["A", "B"]
        assert [channel.name for channel in second.get_channels("ai")] == ["A", "B"]

    def test_concurrent_instances_preserve_every_channel(self, config):
        writers = 12
        barrier = threading.Barrier(writers)

        def add(index: int) -> None:
            library = Library(config)
            barrier.wait(timeout=10)
            assert library.add_channel(
                "ai",
                f"https://youtube.com/@channel-{index}",
                f"Channel {index}",
            )

        with ThreadPoolExecutor(max_workers=writers) as executor:
            list(executor.map(add, range(writers)))

        channels = Library(config).get_channels("ai")
        assert {channel.name for channel in channels} == {
            f"Channel {index}" for index in range(writers)
        }

    def test_failed_atomic_update_does_not_publish_in_memory(self, config, monkeypatch):
        from distill.library import paths

        library = Library(config)

        def fail_write(_path, _content):
            raise OSError("disk full")

        monkeypatch.setattr(paths, "_atomic_write_text_unlocked", fail_write)

        with pytest.raises(OSError, match="disk full"):
            library.add_channel("ai", "https://youtube.com/@A", "A")

        assert library.get_channels("ai") == []

    def test_add_channel_empty_name(self, config):
        """Adding a channel with empty name still works (edge case)."""
        lib = Library(config)
        result = lib.add_channel("ai", "https://youtube.com/@X", "")
        assert result is True


class TestRemoveChannel:
    def test_remove_existing_channel(self, config):
        """Removing an existing channel works."""
        lib = Library(config)
        lib.add_channel("ai", "https://youtube.com/@Test", "Test")
        result = lib.remove_channel("ai", "https://youtube.com/@Test")
        assert result is True
        assert len(lib.get_channels("ai")) == 0

    def test_remove_nonexistent_channel(self, config):
        """Removing a non-existent URL returns False."""
        lib = Library(config)
        lib.add_channel("ai", "https://youtube.com/@Test", "Test")
        result = lib.remove_channel("ai", "https://youtube.com/@Other")
        assert result is False

    def test_remove_from_nonexistent_topic(self, config):
        """Removing from a non-existent topic returns False."""
        lib = Library(config)
        result = lib.remove_channel("nonexistent", "https://youtube.com/@Test")
        assert result is False

    def test_remove_persists(self, config):
        """Removal persists to disk."""
        lib = Library(config)
        lib.add_channel("ai", "https://youtube.com/@Test", "Test")
        lib.remove_channel("ai", "https://youtube.com/@Test")

        lib2 = Library(config)
        assert len(lib2.get_channels("ai")) == 0


class TestGetChannels:
    def test_get_channels_empty_topic(self, config):
        """Getting channels for non-existent topic returns empty list."""
        lib = Library(config)
        assert lib.get_channels("nonexistent") == []

    def test_get_channels_returns_channel_info(self, config):
        """get_channels returns ChannelInfo objects."""
        lib = Library(config)
        lib.add_channel("ai", "https://youtube.com/@Test", "Test")
        channels = lib.get_channels("ai")
        assert isinstance(channels[0], ChannelInfo)

    def test_get_all_channels(self, library_with_channels):
        """get_all_channels returns channels across all topics."""
        _config, lib = library_with_channels
        all_ch = lib.get_all_channels()
        assert len(all_ch) == 3

    def test_get_channel_by_name(self, config):
        """get_channel_by_name finds the right channel."""
        lib = Library(config)
        lib.add_channel("ai", "https://youtube.com/@A", "A")
        lib.add_channel("ai", "https://youtube.com/@B", "B")
        ch = lib.get_channel_by_name("ai", "B")
        assert ch is not None
        assert ch.name == "B"

    def test_get_channel_by_name_not_found(self, config):
        """get_channel_by_name returns None when not found."""
        lib = Library(config)
        assert lib.get_channel_by_name("ai", "Missing") is None
