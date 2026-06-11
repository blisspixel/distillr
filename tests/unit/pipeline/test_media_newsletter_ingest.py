"""Tests for the 0.11 finishers: local media files and newsletter feeds."""

from __future__ import annotations

import pytest

from distill.config import DistillConfig
from distill.ingestors.podcasts.feed import PodcastEpisode, PodcastFeed, parse_feed
from distill.llm.router import LLM_Response
from distill.pipeline.analysis import media as media_mod
from distill.pipeline.analysis import newsletter as nl_mod
from distill.pipeline.analysis.media import is_media_file
from distill.pipeline.analysis.newsletter import feed_is_newsletter


@pytest.fixture
def config(tmp_path):
    return DistillConfig(xai_api_key="t", distill_output_dir=tmp_path / "library")


def _llm(monkeypatch, mod, text="## Summary\nThe talk reports 72.6 accuracy."):
    monkeypatch.setattr(
        mod,
        "llm_call",
        lambda rc, **kwargs: LLM_Response(
            text=text, input_tokens=5, output_tokens=5, model="grok-4.3"
        ),
    )


# ---- media ------------------------------------------------------------------


class _Transcription:
    text = "Speaker: we reached 72.6 accuracy on the benchmark."
    provider = "local"
    model = "large-v3"


class TestMediaIngest:
    @pytest.mark.parametrize("name", ["talk.mp3", "Talk.M4A", "demo.mp4", "memo.wav"])
    def test_media_extensions_detected(self, tmp_path, name):
        f = tmp_path / name
        f.write_bytes(b"x")
        assert is_media_file(f)

    def test_non_media_not_detected(self, tmp_path):
        f = tmp_path / "notes.pdf"
        f.write_bytes(b"x")
        assert not is_media_file(f)

    def test_ingest_transcribes_analyzes_and_verifies(self, tmp_path, config, monkeypatch):
        audio = tmp_path / "conference-talk_2026.mp3"
        audio.write_bytes(b"x")
        seen = {}

        def fake_transcribe(path, cfg, *, vocabulary_hint="", **kwargs):
            seen["hint"] = vocabulary_hint
            return _Transcription()

        monkeypatch.setattr(media_mod, "transcribe_media", fake_transcribe)
        _llm(monkeypatch, media_mod)

        result = media_mod.ingest_media_file(audio, topic="talks", config=config)

        assert "conference talk 2026" in seen["hint"]  # filename-derived vocabulary
        assert result.transcript_path is not None and result.transcript_path.exists()
        assert result.insights_path is not None
        insight = result.insights_path.read_text(encoding="utf-8")
        assert 'prompt_id: "analysis.media.v1"' in insight
        assert list(result.transcript_path.parent.glob("*_Verify.json"))

    def test_strict_refusal(self, tmp_path, config, monkeypatch):
        audio = tmp_path / "talk.mp3"
        audio.write_bytes(b"x")
        monkeypatch.setattr(media_mod, "transcribe_media", lambda *a, **k: _Transcription())
        _llm(monkeypatch, media_mod, text="## Summary\nClaims 99.99 accuracy.")
        config.distill_verify = "strict"

        result = media_mod.ingest_media_file(audio, topic="talks", config=config)

        assert result.insights_path is None
        assert any("refused" in r for r in result.skipped_reasons)
        assert result.transcript_path is not None  # receipt kept

    def test_transcription_failure_degrades_cleanly(self, tmp_path, config, monkeypatch):
        from distill.ingestors.transcribe import TranscriptionError

        audio = tmp_path / "talk.mp3"
        audio.write_bytes(b"x")

        def boom(*a, **k):
            raise TranscriptionError("no provider")

        monkeypatch.setattr(media_mod, "transcribe_media", boom)

        result = media_mod.ingest_media_file(audio, topic="talks", config=config)
        assert result.insights_path is None
        assert any("transcription failed" in r for r in result.skipped_reasons)


# ---- newsletter ---------------------------------------------------------------

_SUBSTACK_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>One Useful Letter</title>
    <link>https://example.substack.com</link>
    <description>Essays</description>
    <item>
      <title>On benchmarks</title>
      <guid>https://example.substack.com/p/on-benchmarks</guid>
      <link>https://example.substack.com/p/on-benchmarks</link>
      <pubDate>Tue, 10 Jun 2026 08:00:00 +0000</pubDate>
      <description>teaser</description>
      <content:encoded><![CDATA[<h2>Benchmarks</h2><p>The model reached <b>72.6</b> accuracy.</p><script>evil()</script><p>PADDING</p>]]></content:encoded>
    </item>
  </channel>
</rss>"""


class TestNewsletterIngest:
    def test_feed_routing_heuristic(self):
        newsletter = parse_feed(_SUBSTACK_RSS)
        assert feed_is_newsletter(newsletter)
        podcast = PodcastFeed(
            title="p",
            link="",
            description="",
            episodes=[
                PodcastEpisode(
                    title="e",
                    guid="g",
                    published="",
                    audio_url="https://x/a.mp3",
                    audio_type="audio/mpeg",
                    duration_s=1,
                    description="d",
                )
            ],
        )
        assert not feed_is_newsletter(podcast)

    def test_narrated_newsletter_routes_as_newsletter(self):
        """Substack attaches narration MP3s to text posts; text is the substance
        (live-validation catch: a narrated Substack mis-routed to the podcast
        path and tried to transcribe its own narration)."""
        narrated = PodcastFeed(
            title="n",
            link="",
            description="",
            episodes=[
                PodcastEpisode(
                    title="p",
                    guid="g",
                    published="",
                    audio_url="https://x/narration.mp3",
                    audio_type="audio/mpeg",
                    duration_s=60,
                    description="d",
                    content_html="<p>" + "substantial post body " * 60 + "</p>",
                )
            ],
        )
        assert feed_is_newsletter(narrated)

    def test_ingest_captures_post_and_verified_insight(self, config, monkeypatch):
        feed = parse_feed(_SUBSTACK_RSS)
        _llm(monkeypatch, nl_mod, text="## Summary\nThe post reports 72.6 accuracy.")

        result = nl_mod.ingest_newsletter(
            "https://example.substack.com/feed", topic="letters", config=config, feed=feed
        )

        assert len(result.content_paths) == 1
        content = result.content_paths[0].read_text(encoding="utf-8")
        assert "72.6" in content and "<b>" not in content and "evil()" not in content
        assert len(result.insight_paths) == 1
        insight = result.insight_paths[0].read_text(encoding="utf-8")
        assert 'prompt_id: "analysis.newsletter.v1"' in insight
        assert list(result.content_paths[0].parent.glob("*_Verify.json"))
        # URL-shaped guid slugifies via digest, not an "_https" tail.
        assert "_https" not in result.content_paths[0].parent.name

    def test_strict_refusal(self, config, monkeypatch):
        feed = parse_feed(_SUBSTACK_RSS)
        _llm(monkeypatch, nl_mod, text="## Summary\nClaims 99.99 accuracy.")
        config.distill_verify = "strict"

        result = nl_mod.ingest_newsletter(
            "https://example.substack.com/feed", topic="letters", config=config, feed=feed
        )

        assert result.insight_paths == []
        assert any("refused" in r for r in result.skipped_reasons)
        assert len(result.content_paths) == 1  # receipt kept


def test_dispatcher_routes_media_and_newsletter(config, monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from distill import cli
    from distill.commands import ingest as ingest_cmd_mod

    monkeypatch.setattr(ingest_cmd_mod, "get_config", lambda: config)

    # Media file route
    audio = tmp_path / "talk.mp3"
    audio.write_bytes(b"x")
    monkeypatch.setattr(media_mod, "transcribe_media", lambda *a, **k: _Transcription())
    _llm(monkeypatch, media_mod)
    r1 = CliRunner().invoke(cli.app, ["ingest", str(audio), "--topic", "talks"])
    assert r1.exit_code == 0, r1.output
    assert "Transcript" in r1.output

    # Newsletter feed route (no enclosures -> newsletter, not podcast)
    monkeypatch.setattr(ingest_cmd_mod, "fetch_feed", lambda url: parse_feed(_SUBSTACK_RSS))
    _llm(monkeypatch, nl_mod, text="## Summary\nThe post reports 72.6 accuracy.")
    r2 = CliRunner().invoke(
        cli.app, ["ingest", "https://example.substack.com/feed", "--topic", "letters"]
    )
    assert r2.exit_code == 0, r2.output
    assert "Publication" in r2.output
