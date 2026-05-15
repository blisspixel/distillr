"""Tests for distill.library."""

import json

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

    def test_handles_missing_topics_key(self, config):
        """Library handles JSON with missing 'topics' key."""
        lib_file = config.library_dir / "library.json"
        lib_file.parent.mkdir(parents=True, exist_ok=True)
        lib_file.write_text(json.dumps({"version": 1}), encoding="utf-8")

        lib = Library(config)
        assert lib.get_topics() == []


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
