"""Tests for watchlist methods in distill.library."""

from distill.library import Library, WatchEntry


class TestAddToWatchlist:
    def test_happy_path_with_days(self, config):
        lib = Library(config)
        result = lib.add_to_watchlist(
            "https://youtube.com/@TestCh", "TestCh", topic="deals", days=7
        )
        assert result is True
        entries = lib.get_watchlist()
        assert len(entries) == 1
        assert entries[0].name == "TestCh"
        assert entries[0].days == 7
        assert entries[0].topic == "deals"

    def test_duplicate_returns_false(self, config):
        lib = Library(config)
        lib.add_to_watchlist("https://youtube.com/@TestCh", "TestCh")
        result = lib.add_to_watchlist("https://youtube.com/@TestCh", "TestCh")
        assert result is False

    def test_also_registers_channel(self, config):
        lib = Library(config)
        lib.add_to_watchlist("https://youtube.com/@TestCh", "TestCh", topic="ai")
        channels = lib.get_channels("ai")
        assert len(channels) == 1
        assert channels[0].name == "TestCh"

    def test_with_instructions(self, config):
        lib = Library(config)
        lib.add_to_watchlist(
            "https://youtube.com/@TestCh",
            "TestCh",
            instructions="Focus on deals",
        )
        entry = lib.get_watchlist()[0]
        assert entry.instructions == "Focus on deals"

    def test_persists_to_disk(self, config):
        lib = Library(config)
        lib.add_to_watchlist("https://youtube.com/@TestCh", "TestCh", days=3)
        lib2 = Library(config)
        assert len(lib2.get_watchlist()) == 1
        assert lib2.get_watchlist()[0].days == 3


class TestGetWatchlist:
    def test_empty_watchlist(self, config):
        lib = Library(config)
        assert lib.get_watchlist() == []

    def test_returns_watch_entry_objects(self, config):
        lib = Library(config)
        lib.add_to_watchlist("https://youtube.com/@A", "A", days=7)
        lib.add_to_watchlist("https://youtube.com/@B", "B", days=14)
        entries = lib.get_watchlist()
        assert len(entries) == 2
        assert all(isinstance(e, WatchEntry) for e in entries)
        assert entries[0].days == 7
        assert entries[1].days == 14


class TestRemoveFromWatchlist:
    def test_remove_by_name(self, config):
        lib = Library(config)
        lib.add_to_watchlist("https://youtube.com/@TestCh", "TestCh")
        result = lib.remove_from_watchlist("TestCh")
        assert result is True
        assert lib.get_watchlist() == []

    def test_case_insensitive(self, config):
        lib = Library(config)
        lib.add_to_watchlist("https://youtube.com/@TestCh", "TestCh")
        result = lib.remove_from_watchlist("testch")
        assert result is True
        assert lib.get_watchlist() == []

    def test_missing_returns_false(self, config):
        lib = Library(config)
        result = lib.remove_from_watchlist("NotHere")
        assert result is False


class TestGetWatchEntry:
    def test_found(self, config):
        lib = Library(config)
        lib.add_to_watchlist("https://youtube.com/@TestCh", "TestCh", days=5)
        entry = lib.get_watch_entry("TestCh")
        assert entry is not None
        assert entry.name == "TestCh"
        assert entry.days == 5

    def test_case_insensitive(self, config):
        lib = Library(config)
        lib.add_to_watchlist("https://youtube.com/@TestCh", "TestCh")
        assert lib.get_watch_entry("testch") is not None

    def test_not_found(self, config):
        lib = Library(config)
        assert lib.get_watch_entry("Missing") is None


class TestUpdateWatchDays:
    def test_success(self, config):
        lib = Library(config)
        lib.add_to_watchlist("https://youtube.com/@TestCh", "TestCh", days=14)
        result = lib.update_watch_days("TestCh", 3)
        assert result is True
        assert lib.get_watch_entry("TestCh").days == 3

    def test_missing_returns_false(self, config):
        lib = Library(config)
        result = lib.update_watch_days("Missing", 7)
        assert result is False

    def test_persists(self, config):
        lib = Library(config)
        lib.add_to_watchlist("https://youtube.com/@TestCh", "TestCh", days=14)
        lib.update_watch_days("TestCh", 2)
        lib2 = Library(config)
        assert lib2.get_watch_entry("TestCh").days == 2


class TestUpdateWatchInstructions:
    def test_success(self, config):
        lib = Library(config)
        lib.add_to_watchlist("https://youtube.com/@TestCh", "TestCh")
        result = lib.update_watch_instructions("TestCh", "Find deals")
        assert result is True
        assert lib.get_watch_entry("TestCh").instructions == "Find deals"

    def test_missing_returns_false(self, config):
        lib = Library(config)
        result = lib.update_watch_instructions("Missing", "instructions")
        assert result is False
