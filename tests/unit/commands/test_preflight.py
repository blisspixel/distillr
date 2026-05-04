import json
from datetime import datetime

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
