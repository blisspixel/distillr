"""Tests for distill.transcripts."""

import os
import sys
from unittest.mock import patch

import pytest

import distill.ingestors.youtube.transcripts as transcripts
from distill.config import DistillConfig
from distill.ingestors.youtube.transcripts import (
    _try_scribe,
    _try_youtube_captions,
    _vtt_to_text,
    get_transcript,
)


class TestVttToText:
    def test_basic_vtt(self):
        """Parses basic VTT content."""
        vtt = """WEBVTT

00:00:01.000 --> 00:00:05.000
Hello world

00:00:05.000 --> 00:00:10.000
This is a test
"""
        result = _vtt_to_text(vtt)
        assert "Hello world" in result
        assert "This is a test" in result

    def test_strips_timestamps(self):
        """Timestamps are removed from output."""
        vtt = """WEBVTT

00:00:01.000 --> 00:00:05.000
Hello world
"""
        result = _vtt_to_text(vtt)
        assert "-->" not in result

    def test_strips_webvtt_header(self):
        """WEBVTT header is removed."""
        vtt = "WEBVTT\n\nHello"
        result = _vtt_to_text(vtt)
        assert "WEBVTT" not in result
        assert "Hello" in result

    def test_strips_kind_language_headers(self):
        """Kind: and Language: headers are stripped."""
        vtt = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:05.000
Hello
"""
        result = _vtt_to_text(vtt)
        assert "Kind" not in result
        assert "Language" not in result
        assert "Hello" in result

    def test_strips_note_lines(self):
        """NOTE lines are stripped."""
        vtt = """WEBVTT

NOTE This is a comment

00:00:01.000 --> 00:00:05.000
Hello
"""
        result = _vtt_to_text(vtt)
        assert "NOTE" not in result

    def test_strips_html_tags(self):
        """HTML/VTT formatting tags are removed."""
        vtt = """WEBVTT

00:00:01.000 --> 00:00:05.000
<c.colorCCCCCC>Hello</c> <b>world</b>
"""
        result = _vtt_to_text(vtt)
        assert "<" not in result
        assert ">" not in result
        assert "Hello" in result
        assert "world" in result

    def test_deduplicates_lines(self):
        """Duplicate lines (common in auto-captions) are removed."""
        vtt = """WEBVTT

00:00:01.000 --> 00:00:05.000
Hello world

00:00:03.000 --> 00:00:07.000
Hello world

00:00:05.000 --> 00:00:10.000
Goodbye
"""
        result = _vtt_to_text(vtt)
        assert result.count("Hello world") == 1

    def test_strips_numeric_cue_ids(self):
        """Numeric cue IDs (SRT-style) are stripped."""
        vtt = """WEBVTT

1
00:00:01.000 --> 00:00:05.000
Hello

2
00:00:05.000 --> 00:00:10.000
World
"""
        result = _vtt_to_text(vtt)
        # Should not contain lone digits
        words = result.split()
        assert "1" not in words
        assert "2" not in words

    def test_empty_vtt(self):
        """Empty VTT returns empty string."""
        result = _vtt_to_text("WEBVTT\n\n")
        assert result == ""

    def test_vtt_only_timestamps(self):
        """VTT with timestamps but no text returns empty."""
        vtt = """WEBVTT

00:00:01.000 --> 00:00:05.000

00:00:05.000 --> 00:00:10.000
"""
        result = _vtt_to_text(vtt)
        assert result == ""

    def test_unicode_content(self):
        """Handles Unicode content."""
        vtt = """WEBVTT

00:00:01.000 --> 00:00:05.000
Bonjour le monde

00:00:05.000 --> 00:00:10.000
Hola mundo
"""
        result = _vtt_to_text(vtt)
        assert "Bonjour" in result
        assert "Hola" in result

    def test_joins_lines_with_spaces(self):
        """Output lines are joined with spaces."""
        vtt = """WEBVTT

00:00:01.000 --> 00:00:05.000
First line

00:00:05.000 --> 00:00:10.000
Second line
"""
        result = _vtt_to_text(vtt)
        assert result == "First line Second line"


class TestGetTranscript:
    @patch("distill.ingestors.youtube.transcripts._try_youtube_captions")
    def test_uses_youtube_captions_first(self, mock_captions, tmp_path):
        """Tries YouTube captions first."""
        mock_captions.return_value = "Hello world transcript"
        config = DistillConfig(distill_output_dir=tmp_path / "lib")
        output = tmp_path / "transcript.txt"

        result = get_transcript("https://youtube.com/watch?v=abc", "abc", output, config)
        assert result is True
        assert output.read_text(encoding="utf-8") == "Hello world transcript"

    @patch("distill.ingestors.youtube.transcripts._try_whisper_ladder")
    @patch("distill.ingestors.youtube.transcripts._try_youtube_captions")
    def test_falls_back_to_whisper_ladder(self, mock_captions, mock_ladder, tmp_path):
        """Captionless videos route through the local-first Whisper ladder."""
        mock_captions.return_value = None
        mock_ladder.return_value = True
        config = DistillConfig(distill_output_dir=tmp_path / "lib")

        result = get_transcript(
            "https://youtube.com/watch?v=abc", "abc", tmp_path / "t.txt", config
        )
        assert result is True
        assert mock_ladder.called

    @patch("distill.ingestors.youtube.transcripts._try_scribe")
    @patch("distill.ingestors.youtube.transcripts._try_whisper_ladder")
    @patch("distill.ingestors.youtube.transcripts._try_youtube_captions")
    def test_scribe_is_last_resort_only_when_configured(
        self, mock_captions, mock_ladder, mock_scribe, tmp_path
    ):
        mock_captions.return_value = None
        mock_ladder.return_value = False
        mock_scribe.return_value = True
        output = tmp_path / "t.txt"

        # No scribe configured: ladder failure is the end of the line.
        config = DistillConfig(distill_output_dir=tmp_path / "lib", scribe_path="")
        assert get_transcript("https://youtube.com/watch?v=abc", "abc", output, config) is False
        assert not mock_scribe.called

        # Scribe configured: it gets its shot after the ladder.
        config = DistillConfig(distill_output_dir=tmp_path / "lib", scribe_path=str(tmp_path))
        assert get_transcript("https://youtube.com/watch?v=abc", "abc", output, config) is True
        assert mock_scribe.called

    @patch("distill.ingestors.youtube.transcripts._try_whisper_ladder")
    @patch("distill.ingestors.youtube.transcripts._try_youtube_captions")
    def test_all_paths_fail(self, mock_captions, mock_ladder, tmp_path):
        """Returns False when every method fails."""
        mock_captions.return_value = None
        mock_ladder.return_value = False
        config = DistillConfig(distill_output_dir=tmp_path / "lib", scribe_path="")

        result = get_transcript(
            "https://youtube.com/watch?v=abc", "abc", tmp_path / "t.txt", config
        )
        assert result is False


class TestYoutubeCaptionsFallback:
    @pytest.fixture(autouse=True)
    def _fast_retries(self, monkeypatch):
        monkeypatch.setattr(transcripts, "_sleep", lambda s: None)

    @patch("distill.ingestors.youtube.transcripts.yt_dlp.YoutubeDL")
    def test_transient_error_retried_then_gives_up(self, mock_ydl):
        mock_ydl.return_value.__enter__.return_value.download.side_effect = Exception("boom")

        result = _try_youtube_captions("https://youtube.com/watch?v=abc", "abc")

        assert result is None
        # One initial attempt + one per backoff slot.
        assert mock_ydl.call_count == len(transcripts._RETRY_DELAYS) + 1

    @patch("distill.ingestors.youtube.transcripts.yt_dlp.YoutubeDL")
    def test_no_vtt_is_permanent_no_retry(self, mock_ydl):
        """A clean download with no subtitle file means captionless -- retrying
        cannot change that, so the budget is one attempt."""
        mock_ydl.return_value.__enter__.return_value.download.return_value = None

        result = _try_youtube_captions("https://youtube.com/watch?v=abc", "abc")

        assert result is None
        assert mock_ydl.call_count == 1

    @patch("distill.ingestors.youtube.transcripts.tempfile.TemporaryDirectory")
    @patch("distill.ingestors.youtube.transcripts.yt_dlp.YoutubeDL")
    def test_retry_recovers_from_transient_failure(self, mock_ydl, mock_tmpdir, tmp_path):
        temp_dir = tmp_path / "captions"
        temp_dir.mkdir()
        mock_tmpdir.return_value.__enter__.return_value = str(temp_dir)
        mock_tmpdir.return_value.__exit__.return_value = False

        calls = {"n": 0}

        def flaky_download(urls):
            calls["n"] += 1
            if calls["n"] == 1:
                raise Exception("HTTP 429")
            (temp_dir / "abc.en.vtt").write_text(
                "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello\n",
                encoding="utf-8",
            )

        mock_ydl.return_value.__enter__.return_value.download.side_effect = flaky_download

        result = _try_youtube_captions("https://youtube.com/watch?v=abc", "abc")

        assert result == "Hello"
        assert calls["n"] == 2

    @patch("distill.ingestors.youtube.transcripts.tempfile.TemporaryDirectory")
    @patch("distill.ingestors.youtube.transcripts.yt_dlp.YoutubeDL")
    def test_try_youtube_captions_parses_downloaded_vtt(self, mock_ydl, mock_tmpdir, tmp_path):
        temp_dir = tmp_path / "captions"
        temp_dir.mkdir()
        mock_tmpdir.return_value.__enter__.return_value = str(temp_dir)
        mock_tmpdir.return_value.__exit__.return_value = False

        def fake_download(urls):
            (temp_dir / "abc.en.vtt").write_text(
                "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello\n",
                encoding="utf-8",
            )

        mock_ydl.return_value.__enter__.return_value.download.side_effect = fake_download

        result = _try_youtube_captions("https://youtube.com/watch?v=abc", "abc")

        assert result == "Hello"


class TestWhisperLadderFallback:
    @pytest.mark.parametrize(
        ("raw_duration", "expected_duration"),
        [(87, 87.0), ("unknown", 0.0), (-5, 0.0), (float("inf"), 0.0)],
    )
    def test_download_audio_returns_largest_file_and_safe_duration(
        self, tmp_path, monkeypatch, raw_duration, expected_duration
    ):
        (tmp_path / "small.m4a").write_bytes(b"a")
        large = tmp_path / "large.m4a"
        large.write_bytes(b"larger")

        class FakeYDL:
            def __init__(self, _options):
                self.options = _options

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def extract_info(self, _url, *, download):
                assert download is True
                return {
                    "title": "Video Title",
                    "uploader": "Uploader",
                    "duration": raw_duration,
                }

        monkeypatch.setattr(transcripts.yt_dlp, "YoutubeDL", FakeYDL)

        audio, hint, duration_s = transcripts._download_audio(
            "https://youtube.com/watch?v=abc", "abc", tmp_path
        )

        assert audio == large
        assert hint == "Video Title - Uploader"
        assert duration_s == expected_duration

    def test_download_audio_handles_fetch_failure(self, tmp_path, monkeypatch):
        class FailingYDL:
            def __init__(self, _options):
                self.options = _options

            def __enter__(self):
                raise RuntimeError("network unavailable")

            def __exit__(self, *_args):
                return False

        monkeypatch.setattr(transcripts.yt_dlp, "YoutubeDL", FailingYDL)

        assert transcripts._download_audio("https://youtube.com/watch?v=abc", "abc", tmp_path) == (
            None,
            "",
            0.0,
        )

    def test_download_audio_requires_a_nonempty_output_file(self, tmp_path, monkeypatch):
        class FakeYDL:
            def __init__(self, _options):
                self.options = _options

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def extract_info(self, _url, *, download):
                return {"duration": 10}

        monkeypatch.setattr(transcripts.yt_dlp, "YoutubeDL", FakeYDL)

        assert transcripts._download_audio("https://youtube.com/watch?v=abc", "abc", tmp_path) == (
            None,
            "",
            0.0,
        )

    @patch("distill.ingestors.youtube.transcripts._download_audio")
    def test_ladder_writes_transcript_and_records_spend(self, mock_dl, tmp_path, monkeypatch):
        from types import SimpleNamespace

        audio = tmp_path / "abc.m4a"
        audio.write_bytes(b"fake audio")
        mock_dl.return_value = (audio, "Video Title - Uploader", 42.0)

        fake_result = SimpleNamespace(
            text="ladder transcript", provider="faster-whisper", duration_s=42.0, model="large-v3"
        )
        import distill.ingestors.transcribe as transcribe_mod
        from distill.pipeline.costs import CostTracker

        config = DistillConfig(distill_output_dir=tmp_path / "lib")
        output = tmp_path / "t.txt"
        tracker = CostTracker()
        seen = {}

        def fake_transcribe(*args, **kwargs):
            seen.update(kwargs)
            return fake_result

        monkeypatch.setattr(transcribe_mod, "transcribe_media", fake_transcribe)

        ok = transcripts._try_whisper_ladder(
            "https://youtube.com/watch?v=abc", "abc", output, config, tracker=tracker
        )

        assert ok is True
        assert output.read_text(encoding="utf-8") == "ladder transcript"
        assert seen["tracker"] is tracker
        assert seen["duration_hint_s"] == 42.0

    @patch("distill.ingestors.youtube.transcripts._download_audio")
    def test_ladder_fails_cleanly_when_download_fails(self, mock_dl, tmp_path):
        mock_dl.return_value = (None, "", 0.0)
        config = DistillConfig(distill_output_dir=tmp_path / "lib")

        ok = transcripts._try_whisper_ladder(
            "https://youtube.com/watch?v=abc", "abc", tmp_path / "t.txt", config
        )
        assert ok is False

    @patch("distill.ingestors.youtube.transcripts._download_audio")
    def test_ladder_propagates_budget_stop(self, mock_dl, tmp_path, monkeypatch):
        from distill.pipeline.costs import BudgetExceededError, CostTracker

        audio = tmp_path / "abc.m4a"
        audio.write_bytes(b"fake audio")
        mock_dl.return_value = (audio, "Video Title", 42.0)

        def refuse(*_args, **_kwargs):
            raise BudgetExceededError(2.0, 1.0)

        import distill.ingestors.transcribe as transcribe_mod

        monkeypatch.setattr(transcribe_mod, "transcribe_media", refuse)

        with pytest.raises(BudgetExceededError):
            transcripts._try_whisper_ladder(
                "https://youtube.com/watch?v=abc",
                "abc",
                tmp_path / "t.txt",
                DistillConfig(distill_output_dir=tmp_path / "lib"),
                tracker=CostTracker(),
            )


class TestScribeFallback:
    def test_try_scribe_requires_configured_path(self, tmp_path):
        config = DistillConfig(distill_output_dir=tmp_path / "lib", scribe_path="")

        result = _try_scribe("https://youtube.com/watch?v=abc", tmp_path / "out.txt", config)

        assert result is False

    def test_try_scribe_requires_existing_path(self, tmp_path):
        config = DistillConfig(
            distill_output_dir=tmp_path / "lib",
            scribe_path=str(tmp_path / "missing-scribe"),
        )

        result = _try_scribe("https://youtube.com/watch?v=abc", tmp_path / "out.txt", config)

        assert result is False

    @patch("distill.ingestors.youtube.transcripts.subprocess.run")
    def test_try_scribe_returns_false_on_nonzero_exit(self, mock_run, tmp_path):
        scribe_dir = tmp_path / "scribe"
        scribe_dir.mkdir()
        config = DistillConfig(
            distill_output_dir=tmp_path / "lib",
            scribe_path=str(scribe_dir),
        )
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "bad things"

        result = _try_scribe("https://youtube.com/watch?v=abc", tmp_path / "out.txt", config)

        assert result is False

    @patch("distill.ingestors.youtube.transcripts.subprocess.run")
    def test_try_scribe_returns_false_when_output_missing(self, mock_run, tmp_path):
        scribe_dir = tmp_path / "scribe"
        scribe_dir.mkdir()
        config = DistillConfig(
            distill_output_dir=tmp_path / "lib",
            scribe_path=str(scribe_dir),
        )
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = ""

        result = _try_scribe("https://youtube.com/watch?v=abc", tmp_path / "out.txt", config)

        assert result is False

    @patch("distill.ingestors.youtube.transcripts.subprocess.run")
    def test_try_scribe_copies_latest_output(self, mock_run, tmp_path):
        scribe_dir = tmp_path / "scribe"
        output_dir = scribe_dir / "output"
        output_dir.mkdir(parents=True)
        old_file = output_dir / "old.txt"
        new_file = output_dir / "new.txt"
        old_file.write_text("old", encoding="utf-8")
        new_file.write_text("new", encoding="utf-8")
        # Set explicit, distinct mtimes so "latest output" is unambiguous.
        # Back-to-back touch() calls can land on the same mtime tick on
        # coarse-resolution filesystems (notably in CI), making the
        # tie-break arbitrary and the test flaky.
        os.utime(old_file, (1_000_000, 1_000_000))
        os.utime(new_file, (2_000_000, 2_000_000))
        config = DistillConfig(
            distill_output_dir=tmp_path / "lib",
            scribe_path=str(scribe_dir),
        )
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = ""
        target = tmp_path / "transcript.txt"

        result = _try_scribe("https://youtube.com/watch?v=abc", target, config)

        assert result is True
        command = mock_run.call_args.args[0]
        assert command[:3] == [sys.executable, "-m", "scribe"]
        assert target.read_text(encoding="utf-8") == "new"

    @patch("distill.ingestors.youtube.transcripts.subprocess.run", side_effect=TimeoutError())
    def test_try_scribe_handles_generic_exception(self, mock_run, tmp_path):
        scribe_dir = tmp_path / "scribe"
        scribe_dir.mkdir()
        config = DistillConfig(
            distill_output_dir=tmp_path / "lib",
            scribe_path=str(scribe_dir),
        )

        result = _try_scribe("https://youtube.com/watch?v=abc", tmp_path / "out.txt", config)

        assert result is False

    @patch(
        "distill.ingestors.youtube.transcripts.subprocess.run",
        side_effect=__import__("subprocess").TimeoutExpired(cmd="scribe", timeout=600),
    )
    def test_try_scribe_handles_timeout(self, mock_run, tmp_path):
        scribe_dir = tmp_path / "scribe"
        scribe_dir.mkdir()
        config = DistillConfig(
            distill_output_dir=tmp_path / "lib",
            scribe_path=str(scribe_dir),
        )

        result = _try_scribe("https://youtube.com/watch?v=abc", tmp_path / "out.txt", config)

        assert result is False
