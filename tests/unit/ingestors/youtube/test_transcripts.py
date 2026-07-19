"""Tests for distill.transcripts."""

import io
import os
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

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
        mock_captions.assert_called_once_with("https://www.youtube.com/watch?v=abc", "abc")

    @patch("distill.ingestors.youtube.transcripts._try_youtube_captions")
    def test_atomic_caption_failure_preserves_prior_transcript(
        self, mock_captions, tmp_path, monkeypatch
    ):
        mock_captions.return_value = "replacement transcript"
        output = tmp_path / "transcript.txt"
        output.write_text("verified prior transcript", encoding="utf-8")

        def fail_replace(_source: Path, _target: Path) -> Path:
            raise OSError("simulated interrupted replacement")

        monkeypatch.setattr(Path, "replace", fail_replace)

        with pytest.raises(OSError, match="interrupted replacement"):
            get_transcript(
                "https://youtube.com/watch?v=abc",
                "abc",
                output,
                DistillConfig(distill_output_dir=tmp_path / "lib"),
            )

        assert output.read_text(encoding="utf-8") == "verified prior transcript"
        assert list(tmp_path.glob(".transcript.txt.*.tmp")) == []

    @patch("distill.ingestors.youtube.transcripts._try_youtube_captions")
    def test_rejects_noncanonical_or_mismatched_video_identity(self, mock_captions, tmp_path):
        config = DistillConfig(distill_output_dir=tmp_path / "lib")
        output = tmp_path / "transcript.txt"

        for url, video_id in (
            ("https://youtube.com/redirect?q=http://169.254.169.254/", "abc"),
            ("https://evil.youtube.com/watch?v=abc", "abc"),
            ("https://youtube.com/watch?v=abc", "different"),
            ("http://youtube.com/watch?v=abc", "abc"),
        ):
            assert get_transcript(url, video_id, output, config) is False

        mock_captions.assert_not_called()

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

    @patch("distill.ingestors.youtube.transcripts.SafeYoutubeDL")
    def test_transient_error_retried_then_gives_up(self, mock_ydl):
        mock_ydl.return_value.__enter__.return_value.download.side_effect = Exception("boom")

        result = _try_youtube_captions("https://youtube.com/watch?v=abc", "abc")

        assert result is None
        # One initial attempt + one per backoff slot.
        assert mock_ydl.call_count == len(transcripts._RETRY_DELAYS) + 1

    @patch("distill.ingestors.youtube.transcripts.SafeYoutubeDL")
    def test_no_vtt_is_permanent_no_retry(self, mock_ydl):
        """A clean download with no subtitle file means captionless -- retrying
        cannot change that, so the budget is one attempt."""
        mock_ydl.return_value.__enter__.return_value.download.return_value = None

        result = _try_youtube_captions("https://youtube.com/watch?v=abc", "abc")

        assert result is None
        assert mock_ydl.call_count == 1

    @patch("distill.ingestors.youtube.transcripts.tempfile.TemporaryDirectory")
    @patch("distill.ingestors.youtube.transcripts.SafeYoutubeDL")
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
        assert mock_ydl.call_args.args[0]["noprogress"] is True
        assert mock_ydl.call_args.kwargs == {
            "metadata_byte_limit": transcripts._MAX_CAPTION_BYTES,
            "total_byte_limit": transcripts.YTDLP_METADATA_TOTAL_BYTES,
        }
        assert calls["n"] == 2

    @patch("distill.ingestors.youtube.transcripts.tempfile.TemporaryDirectory")
    @patch("distill.ingestors.youtube.transcripts.SafeYoutubeDL")
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

    @patch("distill.ingestors.youtube.transcripts.tempfile.TemporaryDirectory")
    @patch("distill.ingestors.youtube.transcripts.SafeYoutubeDL")
    def test_caption_reader_rejects_oversized_vtt(
        self, mock_ydl, mock_tmpdir, tmp_path, monkeypatch
    ):
        temp_dir = tmp_path / "captions"
        temp_dir.mkdir()
        mock_tmpdir.return_value.__enter__.return_value = str(temp_dir)
        mock_tmpdir.return_value.__exit__.return_value = False
        monkeypatch.setattr(transcripts, "_MAX_CAPTION_BYTES", 10)

        def fake_download(_urls):
            (temp_dir / "abc.en.vtt").write_bytes(b"x" * 11)

        mock_ydl.return_value.__enter__.return_value.download.side_effect = fake_download

        assert (
            transcripts._fetch_captions_once("https://www.youtube.com/watch?v=abc", "abc") is None
        )


class TestWhisperLadderFallback:
    @pytest.mark.parametrize(
        ("raw_duration", "expected_duration"),
        [
            (87, 87.0),
            ("unknown", 0.0),
            (-5, 0.0),
            (float("inf"), 0.0),
            (True, 0.0),
            (1.5, 0.0),
            (10**4000, 0.0),
        ],
    )
    def test_download_audio_returns_largest_file_and_safe_duration(
        self, tmp_path, monkeypatch, raw_duration, expected_duration
    ):
        (tmp_path / "small.m4a").write_bytes(b"a")
        large = tmp_path / "large.m4a"
        large.write_bytes(b"larger")

        class FakeYDL:
            def __init__(self, _options, **limits):
                self.options = _options
                assert limits == {
                    "metadata_byte_limit": transcripts.YTDLP_METADATA_RESPONSE_BYTES,
                    "media_byte_limit": transcripts._MAX_AUDIO_BYTES,
                    "total_byte_limit": (
                        transcripts._MAX_AUDIO_BYTES + transcripts.YTDLP_METADATA_TOTAL_BYTES
                    ),
                }

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

        monkeypatch.setattr(transcripts, "SafeYoutubeDL", FakeYDL)

        audio, hint, duration_s = transcripts._download_audio(
            "https://youtube.com/watch?v=abc", "abc", tmp_path
        )

        assert audio == large
        assert hint == "Video Title - Uploader"
        assert duration_s == expected_duration

    def test_download_audio_handles_fetch_failure(self, tmp_path, monkeypatch):
        class FailingYDL:
            def __init__(self, _options, **_limits):
                self.options = _options

            def __enter__(self):
                raise RuntimeError("network unavailable")

            def __exit__(self, *_args):
                return False

        monkeypatch.setattr(transcripts, "SafeYoutubeDL", FailingYDL)

        assert transcripts._download_audio("https://youtube.com/watch?v=abc", "abc", tmp_path) == (
            None,
            "",
            0.0,
        )

    def test_download_audio_aborts_unknown_length_transfer_over_cap(self, tmp_path, monkeypatch):
        monkeypatch.setattr(transcripts, "_MAX_AUDIO_BYTES", 10)

        class FakeYDL:
            def __init__(self, options, **_limits):
                self.options = options

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def extract_info(self, _url, *, download):
                assert download is True
                self.options["progress_hooks"][0]({"status": "downloading", "downloaded_bytes": 11})
                return {}

        monkeypatch.setattr(transcripts, "SafeYoutubeDL", FakeYDL)

        assert transcripts._download_audio("https://youtube.com/watch?v=abc", "abc", tmp_path) == (
            None,
            "",
            0.0,
        )

    def test_download_audio_rejects_oversized_resulting_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(transcripts, "_MAX_AUDIO_BYTES", 10)
        (tmp_path / "abc.m4a").write_bytes(b"x" * 11)

        class FakeYDL:
            def __init__(self, _options, **_limits):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def extract_info(self, _url, *, download):
                assert download is True
                return {"duration": 1}

        monkeypatch.setattr(transcripts, "SafeYoutubeDL", FakeYDL)

        assert transcripts._download_audio("https://youtube.com/watch?v=abc", "abc", tmp_path) == (
            None,
            "",
            0.0,
        )

    def test_download_audio_requires_a_nonempty_output_file(self, tmp_path, monkeypatch):
        class FakeYDL:
            def __init__(self, _options, **_limits):
                self.options = _options

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def extract_info(self, _url, *, download):
                return {"duration": 10}

        monkeypatch.setattr(transcripts, "SafeYoutubeDL", FakeYDL)

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
    def test_scribe_output_lock_rejects_symlink_without_touching_target(self, tmp_path):
        target = tmp_path / "target.txt"
        target.write_bytes(b"")
        lock_path = tmp_path / ".distill-scribe.lock"
        try:
            lock_path.symlink_to(target)
        except OSError as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")

        with (
            pytest.raises(ValueError, match="symbolic link"),
            transcripts._scribe_output_lock(tmp_path),
        ):
            pytest.fail("unsafe lock must not enter its protected section")

        assert target.read_bytes() == b""

    def test_scribe_output_lock_serializes_overlapping_runs(self, tmp_path):
        first_entered = threading.Event()
        release_first = threading.Event()
        second_entered = threading.Event()
        failures: list[BaseException] = []

        def first() -> None:
            try:
                with transcripts._scribe_output_lock(tmp_path):
                    first_entered.set()
                    assert release_first.wait(timeout=2)
            except BaseException as exc:
                failures.append(exc)

        def second() -> None:
            try:
                assert first_entered.wait(timeout=2)
                with transcripts._scribe_output_lock(tmp_path):
                    second_entered.set()
            except BaseException as exc:
                failures.append(exc)

        first_thread = threading.Thread(target=first)
        second_thread = threading.Thread(target=second)
        first_thread.start()
        second_thread.start()
        assert first_entered.wait(timeout=2)
        try:
            assert not second_entered.wait(timeout=0.1)
        finally:
            release_first.set()
            first_thread.join(timeout=2)
            second_thread.join(timeout=2)

        assert failures == []
        assert second_entered.is_set()
        assert not first_thread.is_alive()
        assert not second_thread.is_alive()

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

    @patch("distill.ingestors.youtube.transcripts._run_scribe_process")
    def test_try_scribe_returns_false_on_nonzero_exit(self, run_scribe, tmp_path):
        scribe_dir = tmp_path / "scribe"
        scribe_dir.mkdir()
        config = DistillConfig(
            distill_output_dir=tmp_path / "lib",
            scribe_path=str(scribe_dir),
        )
        run_scribe.return_value = (1, "bad things")

        result = _try_scribe("https://youtube.com/watch?v=abc", tmp_path / "out.txt", config)

        assert result is False

    @patch("distill.ingestors.youtube.transcripts._run_scribe_process")
    def test_try_scribe_returns_false_when_output_missing(self, run_scribe, tmp_path):
        scribe_dir = tmp_path / "scribe"
        scribe_dir.mkdir()
        config = DistillConfig(
            distill_output_dir=tmp_path / "lib",
            scribe_path=str(scribe_dir),
        )
        run_scribe.return_value = (0, "")

        result = _try_scribe("https://youtube.com/watch?v=abc", tmp_path / "out.txt", config)

        assert result is False

    @patch("distill.ingestors.youtube.transcripts._run_scribe_process")
    def test_try_scribe_copies_latest_output(self, run_scribe, tmp_path, monkeypatch):
        scribe_dir = tmp_path / "scribe"
        scribe_dir.mkdir()
        monkeypatch.setenv("XAI_API_KEY", "must-not-reach-scribe")
        monkeypatch.setenv("NODE_OPTIONS", "--require untrusted.js")
        config = DistillConfig(
            distill_output_dir=tmp_path / "lib",
            scribe_path=str(scribe_dir),
        )

        def create_output(command, cwd, env):
            new_file = cwd / "output" / "new.txt"
            new_file.write_text("new", encoding="utf-8")
            return 0, ""

        run_scribe.side_effect = create_output
        target = tmp_path / "transcript.txt"

        result = _try_scribe("https://youtube.com/watch?v=abc", target, config)

        assert result is True
        command, cwd, child_env = run_scribe.call_args.args
        assert command[:4] == [str(Path(sys.executable).resolve()), "-P", "-m", "scribe"]
        assert cwd != scribe_dir
        assert child_env["PYTHONPATH"] == str(scribe_dir.resolve())
        assert "XAI_API_KEY" not in child_env
        assert "NODE_OPTIONS" not in child_env
        assert target.read_text(encoding="utf-8") == "new"

    @pytest.mark.parametrize("unsafe_kind", ["hardlink", "multiple", "oversize", "utf8"])
    @patch("distill.ingestors.youtube.transcripts._run_scribe_process")
    def test_try_scribe_rejects_unsafe_scratch_output(
        self,
        run_scribe,
        tmp_path,
        monkeypatch,
        unsafe_kind,
    ):
        scribe_dir = tmp_path / "scribe"
        scribe_dir.mkdir()
        external = tmp_path / "external.txt"
        external.write_text("external", encoding="utf-8")
        if unsafe_kind == "oversize":
            monkeypatch.setattr(transcripts, "MAX_TRANSCRIPT_BYTES", 4)

        def create_unsafe_output(_command, cwd, _env):
            output_dir = cwd / "output"
            first = output_dir / "first.txt"
            if unsafe_kind == "hardlink":
                os.link(external, first)
            elif unsafe_kind == "multiple":
                first.write_text("first", encoding="utf-8")
                (output_dir / "second.txt").write_text("second", encoding="utf-8")
            elif unsafe_kind == "oversize":
                first.write_text("too large", encoding="utf-8")
            else:
                first.write_bytes(b"valid\xff")
            return 0, ""

        run_scribe.side_effect = create_unsafe_output
        target = tmp_path / "transcript.txt"
        config = DistillConfig(
            distill_output_dir=tmp_path / "lib",
            scribe_path=str(scribe_dir),
        )

        assert _try_scribe("https://youtube.com/watch?v=abc", target, config) is False
        assert not target.exists()

    @patch("distill.ingestors.youtube.transcripts._run_scribe_process")
    def test_try_scribe_does_not_reuse_stale_output(self, run_scribe, tmp_path):
        scribe_dir = tmp_path / "scribe"
        output_dir = scribe_dir / "output"
        output_dir.mkdir(parents=True)
        (output_dir / "stale.txt").write_text("old transcript", encoding="utf-8")
        config = DistillConfig(
            distill_output_dir=tmp_path / "lib",
            scribe_path=str(scribe_dir),
        )
        run_scribe.return_value = (0, "")
        target = tmp_path / "transcript.txt"

        assert _try_scribe("https://youtube.com/watch?v=abc", target, config) is False
        assert not target.exists()

    @patch(
        "distill.ingestors.youtube.transcripts._run_scribe_process",
        side_effect=TimeoutError(),
    )
    def test_try_scribe_handles_generic_exception(self, run_scribe, tmp_path):
        scribe_dir = tmp_path / "scribe"
        scribe_dir.mkdir()
        config = DistillConfig(
            distill_output_dir=tmp_path / "lib",
            scribe_path=str(scribe_dir),
        )

        result = _try_scribe("https://youtube.com/watch?v=abc", tmp_path / "out.txt", config)

        assert result is False

    @patch(
        "distill.ingestors.youtube.transcripts._run_scribe_process",
        side_effect=RuntimeError("Scribe exceeded its time budget"),
    )
    def test_try_scribe_handles_timeout(self, run_scribe, tmp_path):
        scribe_dir = tmp_path / "scribe"
        scribe_dir.mkdir()
        config = DistillConfig(
            distill_output_dir=tmp_path / "lib",
            scribe_path=str(scribe_dir),
        )

        result = _try_scribe("https://youtube.com/watch?v=abc", tmp_path / "out.txt", config)

        assert result is False

    def test_scribe_process_applies_budgets_and_cleans_isolated_tree(
        self,
        tmp_path,
        monkeypatch,
    ):
        process = type(
            "Process",
            (),
            {
                "pid": 123,
                "returncode": 0,
                "stderr": io.BytesIO(b"bounded diagnostic"),
            },
        )()
        popen_mock = MagicMock(return_value=process)
        monkeypatch.setattr(transcripts.subprocess, "Popen", popen_mock)
        cleaned = []
        jobs = []
        monkeypatch.setattr(transcripts, "assign_windows_memory_job", lambda *a, **k: 77)
        monkeypatch.setattr(transcripts, "wait_for_process_budget", lambda *a, **k: 0)
        monkeypatch.setattr(
            transcripts,
            "terminate_isolated_process_tree",
            lambda child: cleaned.append(child),
        )
        monkeypatch.setattr(transcripts, "close_windows_job", jobs.append)

        result = transcripts._run_scribe_process(
            [sys.executable, "-P", "-m", "scribe"],
            tmp_path,
            {"PYTHONSAFEPATH": "1"},
        )

        assert result == (0, "bounded diagnostic")
        assert cleaned == [process]
        assert jobs == [77]
        kwargs = popen_mock.call_args.kwargs
        assert kwargs["stdin"] is transcripts.subprocess.DEVNULL
        assert kwargs["stdout"] is transcripts.subprocess.DEVNULL
        assert kwargs["stderr"] is transcripts.subprocess.PIPE

    def test_scribe_process_terminates_after_budget_failure(self, tmp_path, monkeypatch):
        process = type(
            "Process",
            (),
            {
                "pid": 123,
                "returncode": None,
                "stderr": io.BytesIO(),
            },
        )()
        monkeypatch.setattr(transcripts.subprocess, "Popen", lambda *a, **k: process)
        monkeypatch.setattr(transcripts, "assign_windows_memory_job", lambda *a, **k: 81)
        monkeypatch.setattr(
            transcripts,
            "wait_for_process_budget",
            lambda *a, **k: (_ for _ in ()).throw(transcripts.ProcessBudgetExceeded("time", 1, 2)),
        )
        cleaned = []
        jobs = []
        monkeypatch.setattr(
            transcripts,
            "terminate_isolated_process_tree",
            lambda child: cleaned.append(child),
        )
        monkeypatch.setattr(transcripts, "close_windows_job", jobs.append)

        with pytest.raises(RuntimeError, match="time budget"):
            transcripts._run_scribe_process([sys.executable], tmp_path, {})

        assert cleaned == [process]
        assert jobs == [81]
