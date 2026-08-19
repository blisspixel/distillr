import json
import sys
from datetime import datetime
from pathlib import Path

from distill import preflight


class _RecordingConsole:
    def __init__(self):
        self.lines = []

    def print(self, *args, **kwargs):
        self.lines.append(" ".join(str(a) for a in args))


def test_parse_ytdlp_release_date_handles_standard_format():
    assert preflight.parse_ytdlp_release_date("2026.3.17") == datetime(2026, 3, 17)


def test_parse_ytdlp_release_date_returns_none_for_garbage():
    assert preflight.parse_ytdlp_release_date(None) is None
    assert preflight.parse_ytdlp_release_date("") is None
    assert preflight.parse_ytdlp_release_date("not.a.version") is None
    assert preflight.parse_ytdlp_release_date("2026") is None


def test_parse_ytdlp_release_date_strips_trailing_qualifiers():
    assert preflight.parse_ytdlp_release_date("2026.3.17+local") == datetime(2026, 3, 17)
    assert preflight.parse_ytdlp_release_date("2026.3.17-rc1") == datetime(2026, 3, 17)


def test_ytdlp_age_days_uses_release_date(monkeypatch):
    monkeypatch.setattr(preflight, "get_ytdlp_version", lambda: "2026.3.17")
    age = preflight.ytdlp_age_days(now=datetime(2026, 4, 1))
    assert age == 15


def test_ytdlp_age_days_returns_none_when_unparseable(monkeypatch):
    monkeypatch.setattr(preflight, "get_ytdlp_version", lambda: None)
    assert preflight.ytdlp_age_days() is None


def test_preflight_ytdlp_warns_when_stale(monkeypatch, tmp_path):
    monkeypatch.delenv("DISTILL_NO_PREFLIGHT", raising=False)
    monkeypatch.setattr(preflight, "get_ytdlp_version", lambda: "2026.1.1")
    monkeypatch.setattr(preflight, "ytdlp_age_days", lambda now=None: 30)
    console = _RecordingConsole()
    preflight.preflight_ytdlp(console, library_dir=tmp_path)

    assert any("yt-dlp" in line and "30 days" in line for line in console.lines)
    # Banner must use ASCII marker, not U+26A0, so cp1252 consoles don't crash.
    for line in console.lines:
        assert "⚠" not in line
    cache = json.loads((tmp_path / preflight.PREFLIGHT_CACHE_NAME).read_text())
    assert cache["yt-dlp"]["warned_age_days"] == 30


def test_preflight_ytdlp_silent_when_fresh(monkeypatch, tmp_path):
    monkeypatch.delenv("DISTILL_NO_PREFLIGHT", raising=False)
    monkeypatch.setattr(preflight, "get_ytdlp_version", lambda: "2026.4.20")
    monkeypatch.setattr(preflight, "ytdlp_age_days", lambda now=None: 3)
    console = _RecordingConsole()
    preflight.preflight_ytdlp(console, library_dir=tmp_path)

    assert console.lines == []


def test_preflight_ytdlp_respects_env_opt_out(monkeypatch, tmp_path):
    monkeypatch.setenv("DISTILL_NO_PREFLIGHT", "1")
    monkeypatch.setattr(preflight, "ytdlp_age_days", lambda now=None: 99)
    console = _RecordingConsole()
    preflight.preflight_ytdlp(console, library_dir=tmp_path)

    assert console.lines == []
    assert not (tmp_path / preflight.PREFLIGHT_CACHE_NAME).exists()


def test_preflight_ytdlp_uses_cache_to_skip_recheck(monkeypatch, tmp_path):
    monkeypatch.delenv("DISTILL_NO_PREFLIGHT", raising=False)
    cache_path = tmp_path / preflight.PREFLIGHT_CACHE_NAME
    fresh_ts = datetime.now().isoformat(timespec="seconds")
    cache_path.write_text(
        json.dumps(
            {"yt-dlp": {"version": "2026.1.1", "checked_at": fresh_ts, "warned_age_days": 3}}
        )
    )

    calls = []

    def fake_age(now=None):
        calls.append(now)
        return 99

    monkeypatch.setattr(preflight, "get_ytdlp_version", lambda: "2026.1.1")
    monkeypatch.setattr(preflight, "ytdlp_age_days", fake_age)

    console = _RecordingConsole()
    preflight.preflight_ytdlp(console, library_dir=tmp_path)

    assert calls == []  # cached, no recompute
    assert console.lines == []  # warned_age_days was 3 (fresh), no warn


def test_preflight_ytdlp_revalidates_when_version_changed(monkeypatch, tmp_path):
    monkeypatch.delenv("DISTILL_NO_PREFLIGHT", raising=False)
    cache_path = tmp_path / preflight.PREFLIGHT_CACHE_NAME
    cache_path.write_text(
        json.dumps(
            {
                "yt-dlp": {
                    "version": "2026.1.1",
                    "checked_at": datetime.now().isoformat(timespec="seconds"),
                    "warned_age_days": 3,
                }
            }
        )
    )

    monkeypatch.setattr(preflight, "get_ytdlp_version", lambda: "2026.4.20")
    monkeypatch.setattr(preflight, "ytdlp_age_days", lambda now=None: 6)

    console = _RecordingConsole()
    preflight.preflight_ytdlp(console, library_dir=tmp_path)

    assert console.lines == []
    cache = json.loads(cache_path.read_text())
    assert cache["yt-dlp"]["version"] == "2026.4.20"
    assert cache["yt-dlp"]["warned_age_days"] == 6


def test_invalidate_preflight_cache_removes_file(tmp_path):
    cache_path = tmp_path / preflight.PREFLIGHT_CACHE_NAME
    cache_path.write_text("{}")
    preflight.invalidate_preflight_cache(tmp_path)
    assert not cache_path.exists()


def test_invalidate_preflight_cache_handles_missing(tmp_path):
    # Should not raise on a non-existent cache.
    preflight.invalidate_preflight_cache(tmp_path)
    preflight.invalidate_preflight_cache(None)


def test_update_ytdlp_returns_failure_on_pip_error(monkeypatch):
    class _Result:
        returncode = 1
        stderr = "pip exploded"
        stdout = ""

    def fake_run(*args, **kwargs):
        return _Result()

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)
    ok, detail, was_noop = preflight.update_ytdlp()
    assert ok is False
    assert "pip exploded" in detail
    assert was_noop is False


def test_update_ytdlp_runs_pip_from_trusted_cwd_with_sanitized_env(monkeypatch):
    class _Result:
        returncode = 0
        stderr = ""
        stdout = ""

    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _Result()

    monkeypatch.setenv("PYTHONPATH", ".")
    monkeypatch.setenv("PYTHONHOME", "bad")
    monkeypatch.setenv("XAI_API_KEY", "must-not-reach-pip")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-pip")
    monkeypatch.setenv("GEMINI_API_KEY", "must-not-reach-pip")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-reach-pip")
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-reach-pip")
    monkeypatch.setattr(preflight.subprocess, "run", fake_run)
    versions = iter(["2026.1.1", "2026.4.20"])
    monkeypatch.setattr(preflight, "get_ytdlp_version", lambda: next(versions))

    ok, detail, was_noop = preflight.update_ytdlp()

    assert ok is True
    assert detail == "2026.4.20"
    assert was_noop is False
    assert captured["args"] == [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "yt-dlp",
    ]
    assert captured["kwargs"]["cwd"] == str(Path(sys.executable).resolve().parent)
    assert "PYTHONPATH" not in captured["kwargs"]["env"]
    assert "PYTHONHOME" not in captured["kwargs"]["env"]
    assert "XAI_API_KEY" not in captured["kwargs"]["env"]
    assert "OPENAI_API_KEY" not in captured["kwargs"]["env"]
    assert "GEMINI_API_KEY" not in captured["kwargs"]["env"]
    assert "ANTHROPIC_API_KEY" not in captured["kwargs"]["env"]
    assert "GITHUB_TOKEN" not in captured["kwargs"]["env"]
    assert captured["kwargs"]["env"]["PYTHONSAFEPATH"] == "1"


def test_update_ytdlp_returns_success_on_pip_zero_exit(monkeypatch):
    class _Result:
        returncode = 0
        stderr = ""
        stdout = ""

    monkeypatch.setattr(preflight.subprocess, "run", lambda *a, **k: _Result())
    # Different before/after means a real upgrade happened.
    versions = iter(["2026.1.1", "2026.4.20"])
    monkeypatch.setattr(preflight, "get_ytdlp_version", lambda: next(versions))
    ok, detail, was_noop = preflight.update_ytdlp()
    assert ok is True
    assert detail == "2026.4.20"
    assert was_noop is False


def test_update_ytdlp_marks_noop_when_version_unchanged(monkeypatch):
    """pypi already has the latest release -- pip exits 0 but version doesn't change."""

    class _Result:
        returncode = 0
        stderr = ""
        stdout = "Requirement already satisfied: yt-dlp"

    monkeypatch.setattr(preflight.subprocess, "run", lambda *a, **k: _Result())
    monkeypatch.setattr(preflight, "get_ytdlp_version", lambda: "2026.3.17")
    ok, detail, was_noop = preflight.update_ytdlp()
    assert ok is True
    assert detail == "2026.3.17"
    assert was_noop is True


def test_update_ytdlp_returns_noop_false_when_pre_version_unknown(monkeypatch):
    """If we couldn't read the pre-upgrade version, can't claim no-op safely."""

    class _Result:
        returncode = 0
        stderr = ""
        stdout = ""

    monkeypatch.setattr(preflight.subprocess, "run", lambda *a, **k: _Result())
    versions = iter([None, "2026.4.20"])
    monkeypatch.setattr(preflight, "get_ytdlp_version", lambda: next(versions))
    ok, detail, was_noop = preflight.update_ytdlp()
    assert ok is True
    assert detail == "2026.4.20"
    assert was_noop is False


class TestStalenessIsAboutBeingBehindNotBeingOld:
    """Age alone cried wolf: yt-dlp can go weeks without publishing.

    Warning a user to update when nothing newer exists trains them to ignore
    the warning that guards this project's most fragile dependency.
    """

    @staticmethod
    def _console():
        from rich.console import Console

        return Console(record=True, width=200)

    def test_a_current_install_is_never_warned_about(self, tmp_path, monkeypatch):
        console = self._console()
        monkeypatch.setattr(preflight, "get_ytdlp_version", lambda: "2026.7.4")
        monkeypatch.setattr(preflight, "ytdlp_age_days", lambda now=None: 45)
        monkeypatch.setattr(preflight, "ytdlp_update_available", lambda installed: False)

        preflight.preflight_ytdlp(console, tmp_path)

        assert console.export_text().strip() == ""

    def test_a_genuinely_behind_install_is_warned(self, tmp_path, monkeypatch):
        console = self._console()
        monkeypatch.setattr(preflight, "get_ytdlp_version", lambda: "2026.5.1")
        monkeypatch.setattr(preflight, "ytdlp_age_days", lambda now=None: 100)
        monkeypatch.setattr(preflight, "ytdlp_update_available", lambda installed: True)

        preflight.preflight_ytdlp(console, tmp_path)

        output = console.export_text()
        assert "newer release is available" in output
        assert "distill doctor --update" in output

    def test_an_unreachable_index_says_so_rather_than_asserting_staleness(
        self, tmp_path, monkeypatch
    ):
        """ "No newer release" and "could not check" must not print the same thing."""
        console = self._console()
        monkeypatch.setattr(preflight, "get_ytdlp_version", lambda: "2026.5.1")
        monkeypatch.setattr(preflight, "ytdlp_age_days", lambda now=None: 100)
        monkeypatch.setattr(preflight, "ytdlp_update_available", lambda installed: None)

        preflight.preflight_ytdlp(console, tmp_path)

        output = console.export_text()
        assert "could not be reached" in output

    def test_a_recent_install_never_touches_the_network(self, tmp_path, monkeypatch):
        """Age is a free local pre-filter: a fresh install cannot be behind."""
        console = self._console()
        monkeypatch.setattr(preflight, "get_ytdlp_version", lambda: "2026.8.15")
        monkeypatch.setattr(preflight, "ytdlp_age_days", lambda now=None: 3)

        def forbidden(installed: str | None) -> bool:
            raise AssertionError("a fresh install must not be checked against PyPI")

        monkeypatch.setattr(preflight, "ytdlp_update_available", forbidden)

        preflight.preflight_ytdlp(console, tmp_path)

        assert console.export_text().strip() == ""

    def test_the_pypi_answer_is_cached_with_the_version(self, tmp_path, monkeypatch):
        import json

        console = self._console()
        monkeypatch.setattr(preflight, "get_ytdlp_version", lambda: "2026.5.1")
        monkeypatch.setattr(preflight, "ytdlp_age_days", lambda now=None: 100)
        calls: list[str | None] = []

        def once(installed: str | None) -> bool:
            calls.append(installed)
            return True

        monkeypatch.setattr(preflight, "ytdlp_update_available", once)

        preflight.preflight_ytdlp(console, tmp_path)
        preflight.preflight_ytdlp(console, tmp_path)

        assert len(calls) == 1  # second run served from the daily cache
        cached = json.loads((tmp_path / preflight.PREFLIGHT_CACHE_NAME).read_text(encoding="utf-8"))
        assert cached["yt-dlp"]["update_available"] is True


class TestFetchLatestYtdlp:
    def test_a_failed_fetch_returns_none_rather_than_raising(self, monkeypatch):
        """A freshness hint must never raise into a command."""
        import requests

        def boom(*args: object, **kwargs: object) -> None:
            raise requests.RequestException("offline")

        monkeypatch.setattr("requests.get", boom)

        assert preflight.fetch_latest_ytdlp_version() is None

    def test_an_unreachable_index_yields_an_unknown_verdict(self, monkeypatch):
        monkeypatch.setattr(preflight, "fetch_latest_ytdlp_version", lambda timeout=3.0: None)

        assert preflight.ytdlp_update_available("2026.5.1") is None

    def test_a_newer_published_version_is_detected(self, monkeypatch):
        monkeypatch.setattr(
            preflight, "fetch_latest_ytdlp_version", lambda timeout=3.0: "2026.8.15"
        )

        assert preflight.ytdlp_update_available("2026.5.1") is True

    def test_an_equal_version_is_not_an_update(self, monkeypatch):
        """The zero-padding difference (2026.07.04 vs 2026.7.4) must not mislead."""
        monkeypatch.setattr(preflight, "fetch_latest_ytdlp_version", lambda timeout=3.0: "2026.7.4")

        assert preflight.ytdlp_update_available("2026.07.04") is False
