"""Tests for distill.pipeline.analysis.podcast (episode ingest orchestration)."""

from __future__ import annotations

import pytest

from distill.config import DistillConfig
from distill.ingestors.podcasts.feed import PodcastEpisode, PodcastFeed
from distill.llm.cost_policy import CostPolicyError
from distill.llm.router import LLM_Response
from distill.pipeline.analysis import podcast as pod_mod
from distill.pipeline.costs import CostTracker


def _episode(**overrides) -> PodcastEpisode:
    base = {
        "title": "Grounding numbers in audio",
        "guid": "ep-42",
        "published": "Tue, 10 Jun 2026 08:00:00 +0000",
        "audio_url": "https://example.com/ep42.mp3",
        "audio_type": "audio/mpeg",
        "duration_s": 1800,
        "description": "We discuss 72.6 MRR results.",
        "transcript_url": "",
        "transcript_type": "",
    }
    base.update(overrides)
    return PodcastEpisode(**base)


def _feed(*episodes: PodcastEpisode) -> PodcastFeed:
    return PodcastFeed(
        title="Research Pod",
        link="https://example.com/pod",
        description="d",
        episodes=list(episodes),
    )


@pytest.fixture
def config(tmp_path):
    return DistillConfig(xai_api_key="t", distill_output_dir=tmp_path / "library")


def _patch_llm(monkeypatch, text="## Summary\nThe guest reports 72.6 MRR."):
    monkeypatch.setattr(
        pod_mod,
        "llm_call",
        lambda rc, **kwargs: LLM_Response(
            text=text, input_tokens=10, output_tokens=5, model="grok-4.3"
        ),
    )


def test_publisher_transcript_preferred_over_audio(config, monkeypatch):
    """Free text beats paid audio: with a transcript URL, no download/transcribe."""
    ep = _episode(transcript_url="https://example.com/ep42.vtt", transcript_type="text/vtt")
    monkeypatch.setattr(pod_mod, "fetch_feed", lambda url: _feed(ep))
    monkeypatch.setattr(
        pod_mod, "fetch_transcript", lambda url, transcript_type="": "Guest: we hit 72.6 MRR."
    )
    monkeypatch.setattr(
        pod_mod, "download_audio", lambda *a, **k: pytest.fail("audio must not download")
    )
    monkeypatch.setattr(
        pod_mod, "transcribe_media", lambda *a, **k: pytest.fail("must not transcribe")
    )
    _patch_llm(monkeypatch)
    tracker = CostTracker()

    result = pod_mod.ingest_podcast(
        "https://example.com/pod.rss", topic="pods", config=config, tracker=tracker
    )

    assert len(result.episode_paths) == 1
    assert len(result.insight_paths) == 1
    receipt = result.episode_paths[0].read_text(encoding="utf-8")
    assert "publisher transcript" in receipt
    insight = result.insight_paths[0].read_text(encoding="utf-8")
    assert 'prompt_id: "analysis.podcast.v1"' in insight
    # Verify sidecar exists and the claim grounds in transcript+receipt.
    assert list(result.episode_paths[0].parent.glob("*_Verify.json"))
    assert tracker.entries[0].call_type == "podcast_analysis"


def test_empty_analysis_keeps_episode_receipt(config, monkeypatch):
    ep = _episode(transcript_url="https://example.com/ep42.vtt", transcript_type="text/vtt")
    monkeypatch.setattr(pod_mod, "fetch_feed", lambda url: _feed(ep))
    monkeypatch.setattr(
        pod_mod, "fetch_transcript", lambda url, transcript_type="": "Guest: we hit 72.6 MRR."
    )
    _patch_llm(monkeypatch, text="---\ntitle: x\n---\n\n")

    result = pod_mod.ingest_podcast(
        "https://example.com/pod.rss",
        topic="pods",
        config=config,
        tracker=CostTracker(),
    )

    assert result.episode_paths
    assert result.insight_paths == []
    assert result.skipped_reasons == ["Empty analysis"]


def test_audio_fallback_routes_through_transcribe(config, monkeypatch, tmp_path):
    ep = _episode()  # no transcript_url
    monkeypatch.setattr(pod_mod, "fetch_feed", lambda url: _feed(ep))
    audio_file = tmp_path / "ep.mp3"
    audio_file.write_bytes(b"fake")
    seen = {}

    def fake_download(url, dest_dir):
        seen["downloaded"] = url
        return audio_file

    class _Result:
        text = "Host: welcome. Guest: we hit 72.6 MRR."
        provider = "local"
        model = "large-v3"

    def fake_transcribe(path, cfg, *, vocabulary_hint="", **kwargs):
        seen["hint"] = vocabulary_hint
        return _Result()

    monkeypatch.setattr(pod_mod, "download_audio", fake_download)
    monkeypatch.setattr(pod_mod, "transcribe_media", fake_transcribe)
    _patch_llm(monkeypatch)

    result = pod_mod.ingest_podcast(
        "https://example.com/pod.rss", topic="pods", config=config, tracker=CostTracker()
    )

    assert seen["downloaded"] == ep.audio_url
    assert "Grounding numbers in audio" in seen["hint"]  # vocabulary from episode metadata
    assert len(result.insight_paths) == 1
    transcripts = list(result.episode_paths[0].parent.glob("*_Transcript.txt"))
    assert transcripts and "72.6" in transcripts[0].read_text(encoding="utf-8")


def test_no_transcript_no_audio_skips_analysis(config, monkeypatch):
    ep = _episode(audio_url="")
    monkeypatch.setattr(pod_mod, "fetch_feed", lambda url: _feed(ep))
    _patch_llm(monkeypatch)

    result = pod_mod.ingest_podcast(
        "https://example.com/pod.rss", topic="pods", config=config, tracker=CostTracker()
    )

    assert len(result.episode_paths) == 1  # receipt still captured
    assert result.insight_paths == []
    assert any("no audio enclosure" in r for r in result.skipped_reasons)


def test_analysis_refuses_provider_call_without_cost_tracker(config, monkeypatch):
    ep = _episode(transcript_url="https://example.com/ep42.txt")
    monkeypatch.setattr(pod_mod, "fetch_feed", lambda url: _feed(ep))
    monkeypatch.setattr(
        pod_mod, "fetch_transcript", lambda url, transcript_type="": "Grounded transcript."
    )
    monkeypatch.setattr(
        pod_mod, "llm_call", lambda *args, **kwargs: pytest.fail("must not call provider")
    )

    with pytest.raises(CostPolicyError, match="cost tracker is required"):
        pod_mod.ingest_podcast("https://example.com/pod.rss", topic="pods", config=config)


def test_empty_feed_fetch_records_no_episode_skip(config, monkeypatch):
    feed = PodcastFeed(title="", link="https://example.com/empty", description="", episodes=[])
    monkeypatch.setattr(pod_mod, "fetch_feed", lambda url: feed)

    result = pod_mod.ingest_podcast("https://example.com/empty.rss", topic="pods", config=config)

    assert result.feed_title == "https://example.com/empty.rss"
    assert result.episode_paths == []
    assert result.insight_paths == []
    assert result.skipped_reasons == ["Feed parsed but contains no episodes."]


def test_failed_publisher_transcript_falls_back_to_no_audio_skip(config, monkeypatch):
    ep = _episode(
        transcript_url="https://example.com/ep42.vtt",
        transcript_type="text/vtt",
        audio_url="",
    )
    monkeypatch.setattr(pod_mod, "fetch_feed", lambda url: _feed(ep))

    def fail_transcript(url, transcript_type=""):
        raise pod_mod.PodcastFetchError("transcript timeout")

    monkeypatch.setattr(pod_mod, "fetch_transcript", fail_transcript)
    _patch_llm(monkeypatch)

    result = pod_mod.ingest_podcast(
        "https://example.com/pod.rss", topic="pods", config=config, tracker=CostTracker()
    )

    assert len(result.episode_paths) == 1
    assert result.insight_paths == []
    assert any("publisher transcript failed" in r for r in result.skipped_reasons)
    assert any("no audio enclosure" in r for r in result.skipped_reasons)
    assert any("no transcript; analysis skipped" in r for r in result.skipped_reasons)


def test_empty_publisher_transcript_can_skip_transcription(config, monkeypatch):
    ep = _episode(transcript_url="https://example.com/ep42.txt")
    monkeypatch.setattr(pod_mod, "fetch_feed", lambda url: _feed(ep))
    monkeypatch.setattr(pod_mod, "fetch_transcript", lambda url, transcript_type="": "   ")
    monkeypatch.setattr(
        pod_mod,
        "download_audio",
        lambda *args, **kwargs: pytest.fail("transcription was disabled"),
    )
    _patch_llm(monkeypatch)

    result = pod_mod.ingest_podcast(
        "https://example.com/pod.rss",
        topic="pods",
        config=config,
        transcribe=False,
    )

    assert len(result.episode_paths) == 1
    assert result.insight_paths == []
    assert any("--no-transcribe set" in r for r in result.skipped_reasons)
    assert any("no transcript; analysis skipped" in r for r in result.skipped_reasons)


def test_transcription_failure_skips_analysis(config, monkeypatch, tmp_path):
    ep = _episode()
    monkeypatch.setattr(pod_mod, "fetch_feed", lambda url: _feed(ep))
    audio_file = tmp_path / "ep.mp3"
    audio_file.write_bytes(b"fake")
    monkeypatch.setattr(pod_mod, "download_audio", lambda url, dest_dir: audio_file)

    def fail_transcribe(path, cfg, *, vocabulary_hint="", **kwargs):
        raise pod_mod.TranscriptionError("no provider available")

    monkeypatch.setattr(pod_mod, "transcribe_media", fail_transcribe)
    _patch_llm(monkeypatch)

    result = pod_mod.ingest_podcast("https://example.com/pod.rss", topic="pods", config=config)

    assert len(result.episode_paths) == 1
    assert result.insight_paths == []
    assert any("transcription failed" in r for r in result.skipped_reasons)
    assert any("no transcript; analysis skipped" in r for r in result.skipped_reasons)


def test_url_shaped_feed_and_episode_ids_use_stable_digest(config):
    guid = "https://pod.example.com/episodes/42"
    feed_url = "feed-without-netloc"
    ep = _episode(guid=guid, audio_url="", transcript_url="", duration_s=0)

    result = pod_mod.ingest_podcast(
        feed_url, topic="pods", config=config, analyze=False, feed=_feed(ep)
    )

    assert len(result.episode_paths) == 1
    path_parts = result.episode_paths[0].parts
    assert f"research-pod_{pod_mod._short_id(feed_url)}" in path_parts
    assert result.episode_paths[0].parent.name.endswith(f"_{pod_mod._short_id(guid)}")
    assert "unknown length" in result.episode_paths[0].read_text(encoding="utf-8")


def test_strict_refusal_on_unsupported_claim(config, monkeypatch):
    ep = _episode(transcript_url="https://example.com/t.txt")
    monkeypatch.setattr(pod_mod, "fetch_feed", lambda url: _feed(ep))
    monkeypatch.setattr(
        pod_mod, "fetch_transcript", lambda url, transcript_type="": "Guest: results were modest."
    )
    _patch_llm(monkeypatch, text="## Summary\nThe guest reports 99.99 MRR.")
    config.distill_verify = "strict"

    result = pod_mod.ingest_podcast(
        "https://example.com/pod.rss", topic="pods", config=config, tracker=CostTracker()
    )

    assert result.insight_paths == []
    assert any("refused" in r for r in result.skipped_reasons)


def test_episodes_limit_takes_latest_n(config, monkeypatch):
    eps = [
        _episode(title=f"Ep {i}", guid=f"g{i}", transcript_url="https://example.com/t.txt")
        for i in range(3)
    ]
    monkeypatch.setattr(pod_mod, "fetch_feed", lambda url: _feed(*eps))
    monkeypatch.setattr(
        pod_mod, "fetch_transcript", lambda url, transcript_type="": "Talk about 72.6 MRR."
    )
    _patch_llm(monkeypatch)

    result = pod_mod.ingest_podcast(
        "https://example.com/pod.rss",
        topic="pods",
        config=config,
        episodes=2,
        tracker=CostTracker(),
    )

    assert len(result.episode_paths) == 2
