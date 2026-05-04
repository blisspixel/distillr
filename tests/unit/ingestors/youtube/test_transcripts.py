"""Tests for distill.transcripts."""

from unittest.mock import patch

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

    @patch("distill.ingestors.youtube.transcripts._try_scribe")
    @patch("distill.ingestors.youtube.transcripts._try_youtube_captions")
    def test_falls_back_to_scribe(self, mock_captions, mock_scribe, tmp_path):
        """Falls back to scribe when captions fail."""
        mock_captions.return_value = None
        mock_scribe.return_value = True
        config = DistillConfig(distill_output_dir=tmp_path / "lib")
        output = tmp_path / "transcript.txt"

        get_transcript("https://youtube.com/watch?v=abc", "abc", output, config)
        assert mock_scribe.called

    @patch("distill.ingestors.youtube.transcripts._try_scribe")
    @patch("distill.ingestors.youtube.transcripts._try_youtube_captions")
    def test_both_fail(self, mock_captions, mock_scribe, tmp_path):
        """Returns False when both methods fail."""
        mock_captions.return_value = None
        mock_scribe.return_value = False
        config = DistillConfig(distill_output_dir=tmp_path / "lib")
        output = tmp_path / "transcript.txt"

        result = get_transcript("https://youtube.com/watch?v=abc", "abc", output, config)
        assert result is False


class TestYoutubeCaptionsFallback:
    @patch("distill.ingestors.youtube.transcripts.yt_dlp.YoutubeDL")
    def test_try_youtube_captions_returns_none_on_download_error(self, mock_ydl):
        mock_ydl.return_value.__enter__.return_value.download.side_effect = Exception("boom")

        result = _try_youtube_captions("https://youtube.com/watch?v=abc", "abc")

        assert result is None

    @patch("distill.ingestors.youtube.transcripts.yt_dlp.YoutubeDL")
    def test_try_youtube_captions_returns_none_when_no_vtt_found(self, mock_ydl):
        mock_ydl.return_value.__enter__.return_value.download.return_value = None

        result = _try_youtube_captions("https://youtube.com/watch?v=abc", "abc")

        assert result is None

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
        old_file.touch()
        new_file.touch()
        config = DistillConfig(
            distill_output_dir=tmp_path / "lib",
            scribe_path=str(scribe_dir),
        )
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = ""
        target = tmp_path / "transcript.txt"

        result = _try_scribe("https://youtube.com/watch?v=abc", target, config)

        assert result is True
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
