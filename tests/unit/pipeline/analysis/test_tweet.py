"""Tests for distill.pipeline.analysis.tweet."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from distill.config import DistillConfig
from distill.ingestors.x.syndication import TweetRecord
from distill.library.paths import extract_frontmatter
from distill.llm.router import LLM_Response
from distill.pipeline.analysis.tweet import (
    IngestedTweet,
    _expanded_vocabulary_hint,
    _media_summary,
    _source_text_hint,
    _tweet_markdown,
    _vocabulary_hint,
    _x_post_dir,
    analyze_tweet,
    ingest_tweet,
)


def _tweet(**overrides: Any) -> TweetRecord:
    defaults: dict[str, Any] = {
        "tweet_id": "12345",
        "url": "https://x.com/alice/status/12345",
        "author_name": "Alice",
        "author_handle": "alice",
        "author_verified": True,
        "created_at": "2026-05-16T12:00:00.000Z",
        "text": "Anthropic dropped a Claude workshop",
        "language": "en",
        "like_count": 100,
        "reply_count": 5,
    }
    defaults.update(overrides)
    return TweetRecord(**defaults)


def _fake_llm(text: str = "body", model: str = "grok-4.3"):
    def _call(config: Any, workload_tag: str, prompt: str, **kwargs: Any) -> LLM_Response:
        return LLM_Response(text=text, input_tokens=10, output_tokens=20, model=model)

    return _call


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------


def test_source_text_hint_includes_name_handle_text() -> None:
    hint = _source_text_hint(
        _tweet(author_name="Boris", author_handle="boris_c", text="Claude Code rocks")
    )
    assert "Boris" in hint
    assert "@boris_c" in hint
    assert "Claude Code rocks" in hint


def test_source_text_hint_appends_distinct_note_text() -> None:
    hint = _source_text_hint(_tweet(text="short", note_text="much longer body text"))
    assert "much longer body text" in hint


def test_source_text_hint_skips_duplicate_note() -> None:
    hint = _source_text_hint(_tweet(text="same", note_text="same"))
    assert hint.count("same") == 1


def test_source_text_hint_handles_missing_fields() -> None:
    hint = _source_text_hint(_tweet(author_name="", author_handle="", text=""))
    assert hint == ""


def test_expanded_vocabulary_hint_calls_llm() -> None:
    with patch(
        "distill.pipeline.analysis.tweet.llm_call",
        _fake_llm("Claude Code, CLAUDE.md, MCP, Sonnet, Haiku"),
    ):
        out = _expanded_vocabulary_hint(_tweet())
    assert "Claude Code" in out
    assert "MCP" in out


def test_expanded_vocabulary_hint_strips_known_prefixes() -> None:
    with patch(
        "distill.pipeline.analysis.tweet.llm_call",
        _fake_llm("Output: alpha, beta, gamma"),
    ):
        out = _expanded_vocabulary_hint(_tweet())
    assert not out.lower().startswith("output")
    assert "alpha, beta, gamma" in out


def test_expanded_vocabulary_hint_returns_empty_on_llm_failure() -> None:
    def _raise(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("boom")

    with patch("distill.pipeline.analysis.tweet.llm_call", _raise):
        out = _expanded_vocabulary_hint(_tweet())
    assert out == ""


def test_vocabulary_hint_combines_source_and_expanded() -> None:
    with patch(
        "distill.pipeline.analysis.tweet.llm_call",
        _fake_llm("Claude Code, CLAUDE.md, MCP"),
    ):
        out = _vocabulary_hint(_tweet(text="hi from author"))
    assert "hi from author" in out
    assert "Claude Code" in out


def test_vocabulary_hint_falls_back_to_source_only_when_expansion_fails() -> None:
    def _raise(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("llm down")

    with patch("distill.pipeline.analysis.tweet.llm_call", _raise):
        out = _vocabulary_hint(_tweet(text="source text"))
    assert "source text" in out


def test_media_summary_describes_video() -> None:
    s = _media_summary(_tweet(video_url="x", video_duration_ms=30000))
    assert "video clip" in s
    assert "30.0s" in s


def test_media_summary_counts_photos() -> None:
    s = _media_summary(_tweet(photo_urls=["a", "b"]))
    assert "2 photo" in s


def test_media_summary_combines_video_and_photos() -> None:
    s = _media_summary(_tweet(video_url="x", video_duration_ms=10000, photo_urls=["a"]))
    assert "video clip" in s and "1 photo" in s


def test_tweet_markdown_renders_text_only() -> None:
    md = _tweet_markdown(_tweet(text="hello world"), "")
    assert "## Tweet" in md
    assert "hello world" in md
    assert "## Attached video" not in md
    assert "## Video transcript" not in md


def test_tweet_markdown_includes_video_metadata() -> None:
    md = _tweet_markdown(
        _tweet(video_url="https://video.twimg.com/x.mp4", video_duration_ms=60000), ""
    )
    assert "## Attached video" in md
    assert "60.0s" in md
    assert "https://video.twimg.com/x.mp4" in md


def test_tweet_markdown_includes_transcript_when_present() -> None:
    md = _tweet_markdown(_tweet(video_url="x"), "transcript text body")
    assert "## Video transcript" in md
    assert "transcript text body" in md


def test_tweet_markdown_handles_note_body() -> None:
    md = _tweet_markdown(_tweet(text="hi", note_text="longer body"), "")
    assert "## Long-form body" in md
    assert "longer body" in md


def test_tweet_markdown_lists_photos() -> None:
    md = _tweet_markdown(_tweet(photo_urls=["https://x/a.jpg", "https://x/b.jpg"]), "")
    assert "## Attached photos" in md
    assert "https://x/a.jpg" in md


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def test_x_post_dir_uses_handle_and_slug(tmp_path: Path) -> None:
    config = DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")
    path = _x_post_dir(config, "topic-a", _tweet(author_handle="bob", tweet_id="999"))
    assert "x" in path.parts
    assert "bob" in path.parts
    assert "posts" in path.parts
    assert path.parts[-1].endswith("999")


def test_x_post_dir_handles_anonymous(tmp_path: Path) -> None:
    config = DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")
    path = _x_post_dir(config, "t", _tweet(author_handle="", tweet_id="1"))
    assert "anonymous" in path.parts


# ---------------------------------------------------------------------------
# analyze_tweet
# ---------------------------------------------------------------------------


def test_analyze_tweet_returns_frontmattered_markdown(tmp_path: Path) -> None:
    config = DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")
    with patch("distill.pipeline.analysis.tweet.llm_call", _fake_llm("analysis body")):
        out = analyze_tweet(_tweet(), config=config)
    fm = extract_frontmatter(out)
    assert fm["type"] == "insights"
    assert fm["source"] == "x"
    assert fm["source_id"] == "12345"
    assert fm["prompt_id"] == "analysis.x_tweet.v1"
    assert "analysis body" in out


def test_analyze_tweet_records_cost(tmp_path: Path) -> None:
    from distill.pipeline.costs import CostTracker

    config = DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")
    tracker = CostTracker()
    with patch("distill.pipeline.analysis.tweet.llm_call", _fake_llm()):
        analyze_tweet(_tweet(), config=config, tracker=tracker)
    assert len(tracker.entries) == 1
    assert tracker.entries[0].call_type == "x_tweet"


# ---------------------------------------------------------------------------
# ingest_tweet (mocking fetch + transcribe + LLM)
# ---------------------------------------------------------------------------


def test_ingest_tweet_text_only_writes_two_artifacts(tmp_path: Path) -> None:
    """Tweet without video: writes Tweet.md + Insights.md, no transcript."""
    config = DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")
    text_tweet = _tweet(text="text only post")

    with (
        patch("distill.pipeline.analysis.tweet.fetch_tweet", return_value=text_tweet),
        patch("distill.pipeline.analysis.tweet.llm_call", _fake_llm("insights body")),
    ):
        result = ingest_tweet("https://x.com/alice/status/12345", topic="t", config=config)

    assert isinstance(result, IngestedTweet)
    assert result.tweet_path.exists()
    assert result.transcript_path is None
    assert result.insights_path is not None and result.insights_path.exists()
    # Tweet.md frontmatter has source=x and the right id
    fm = extract_frontmatter(result.tweet_path.read_text(encoding="utf-8"))
    assert fm["source"] == "x"
    assert fm["source_id"] == "12345"


def test_ingest_tweet_skip_analyze(tmp_path: Path) -> None:
    config = DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")
    with patch("distill.pipeline.analysis.tweet.fetch_tweet", return_value=_tweet()):
        result = ingest_tweet(
            "https://x.com/alice/status/12345", topic="t", config=config, analyze=False
        )
    assert result.insights_path is None


def test_ingest_tweet_video_pipeline_with_mocks(tmp_path: Path) -> None:
    """Video tweet path: downloads + transcribes + analyzes (all mocked)."""
    from distill.ingestors.transcribe import TranscriptionResult

    config = DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")
    video_tweet = _tweet(video_url="https://video.twimg.com/test.mp4", video_duration_ms=30000)

    def _fake_download(url: str, dest: Path, **kwargs: Any) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake video bytes")
        return dest

    def _fake_transcribe(media_path: Path, config: Any, **kwargs: Any) -> TranscriptionResult:
        # Confirm vocab hint was threaded through (source-text portion at minimum)
        assert "Alice" in kwargs["vocabulary_hint"]
        return TranscriptionResult(
            text="speaker said something useful",
            provider="faster-whisper",
            model="large-v3",
        )

    with (
        patch("distill.pipeline.analysis.tweet.fetch_tweet", return_value=video_tweet),
        patch("distill.pipeline.analysis.tweet.download_video", side_effect=_fake_download),
        patch("distill.pipeline.analysis.tweet.transcribe_media", side_effect=_fake_transcribe),
        patch("distill.pipeline.analysis.tweet.llm_call", _fake_llm("v-insights")),
    ):
        result = ingest_tweet("https://x.com/alice/status/12345", topic="t", config=config)

    assert result.transcript_path is not None and result.transcript_path.exists()
    assert "speaker said something useful" in result.transcript_path.read_text(encoding="utf-8")
    assert result.media_path is not None and result.media_path.exists()
    assert result.transcript_text == "speaker said something useful"
    assert result.skipped_reasons == []


def test_ingest_tweet_reuses_cached_media(tmp_path: Path) -> None:
    from distill.ingestors.transcribe import TranscriptionResult

    config = DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")
    video_tweet = _tweet(video_url="https://video.twimg.com/test.mp4", video_duration_ms=1000)

    # Pre-create the media file so download is skipped
    expected_dir = _x_post_dir(config, "t", video_tweet)
    expected_dir.mkdir(parents=True, exist_ok=True)
    (expected_dir / "media.mp4").write_bytes(b"already here")

    download_called = {"n": 0}

    def _fake_download(*args: Any, **kwargs: Any) -> Any:
        download_called["n"] += 1
        return args[1]

    def _fake_transcribe(*args: Any, **kwargs: Any) -> TranscriptionResult:
        return TranscriptionResult(text="t", provider="faster-whisper", model="large-v3")

    with (
        patch("distill.pipeline.analysis.tweet.fetch_tweet", return_value=video_tweet),
        patch("distill.pipeline.analysis.tweet.download_video", side_effect=_fake_download),
        patch("distill.pipeline.analysis.tweet.transcribe_media", side_effect=_fake_transcribe),
        patch("distill.pipeline.analysis.tweet.llm_call", _fake_llm("ok")),
    ):
        ingest_tweet("https://x.com/alice/status/12345", topic="t", config=config)

    assert download_called["n"] == 0


def test_ingest_tweet_transcription_failure_is_recorded_and_does_not_crash(tmp_path: Path) -> None:
    from distill.ingestors.transcribe import TranscriptionError

    config = DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")
    video_tweet = _tweet(video_url="https://video.twimg.com/test.mp4", video_duration_ms=1000)

    def _fake_download(url: str, dest: Path, **kwargs: Any) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x")
        return dest

    def _raise(*args: Any, **kwargs: Any) -> Any:
        raise TranscriptionError("no provider available")

    with (
        patch("distill.pipeline.analysis.tweet.fetch_tweet", return_value=video_tweet),
        patch("distill.pipeline.analysis.tweet.download_video", side_effect=_fake_download),
        patch("distill.pipeline.analysis.tweet.transcribe_media", side_effect=_raise),
        patch("distill.pipeline.analysis.tweet.llm_call", _fake_llm("still analyzed")),
    ):
        result = ingest_tweet("https://x.com/alice/status/12345", topic="t", config=config)

    assert result.transcript_path is None
    assert len(result.skipped_reasons) == 1
    assert "no provider available" in result.skipped_reasons[0]
    # Insights still produced from tweet text alone
    assert result.insights_path is not None
