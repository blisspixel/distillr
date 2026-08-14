"""Tests for distill.pipeline.analysis.tweet."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from distill.config import DistillConfig
from distill.ingestors.x.syndication import TweetRecord
from distill.library.paths import apply_frontmatter, atomic_write_text, extract_frontmatter
from distill.llm.router import LLM_Response
from distill.pipeline.analysis.tweet import (
    IngestedTweet,
    _expanded_vocabulary_hint,
    _link_preview_context,
    _media_summary,
    _quoted_post_context,
    _source_text_hint,
    _tweet_markdown,
    _tweet_source_content_hash,
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


def test_source_content_hash_ignores_counts_but_detects_post_edits() -> None:
    original = _tweet(like_count=10, reply_count=2)
    new_counts = _tweet(like_count=999, reply_count=88)
    edited = _tweet(text="Edited source text", like_count=999, reply_count=88)

    assert _tweet_source_content_hash(original) == _tweet_source_content_hash(new_counts)
    assert _tweet_source_content_hash(original) != _tweet_source_content_hash(edited)


@pytest.mark.parametrize("url", ["http://[", "https://x.test:bad/a.mp4"])
def test_source_content_hash_omits_malformed_media_urls(url: str) -> None:
    malformed = _tweet(photo_urls=[url], video_url=url)
    absent = _tweet(photo_urls=[""], video_url="")

    assert _tweet_source_content_hash(malformed) == _tweet_source_content_hash(absent)


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


def test_expanded_vocabulary_hint_propagates_budget_stop() -> None:
    from distill.pipeline.costs import BudgetExceededError

    def _raise(*args: Any, **kwargs: Any) -> Any:
        raise BudgetExceededError(1.0, 0.0)

    with (
        patch("distill.pipeline.analysis.tweet.llm_call", _raise),
        pytest.raises(BudgetExceededError),
    ):
        _expanded_vocabulary_hint(_tweet())


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


def test_tweet_markdown_video_preserves_blank_line_structure() -> None:
    # A video tweet must keep its Markdown paragraph separators; a stray filter
    # used to strip every blank line, jamming the headers together.
    md = _tweet_markdown(
        _tweet(
            text="hello",
            video_url="https://video.twimg.com/x.mp4",
            video_duration_ms=60000,
        ),
        "",
    )
    assert "\n\n## Tweet\n" in md
    assert "\n\n## Attached video\n" in md
    # The title line must stand alone, not be glued to the Source line.
    assert "Source:" not in md.split("\n", 1)[0]


def test_tweet_markdown_includes_transcript_when_present() -> None:
    md = _tweet_markdown(_tweet(video_url="x"), "transcript text body")
    assert "## Video transcript" in md
    assert "transcript text body" in md


def test_tweet_markdown_handles_note_body() -> None:
    md = _tweet_markdown(_tweet(text="hi", note_text="longer body"), "")
    assert "## Long-form body" in md
    assert "longer body" in md


def test_tweet_markdown_renders_partial_capture_and_link_preview() -> None:
    tweet = _tweet(
        text="https://t.co/article-only",
        link_preview_type="x_article",
        link_preview_title="Designing durable agent queues",
        link_preview_description="A practical look at leases and retries.",
        link_preview_domain="x.com",
        link_preview_url="https://x.com/i/article/12345",
        capture_status="partial",
        capture_warning="The full article body was not captured.",
    )

    context = _link_preview_context(tweet)
    md = _tweet_markdown(tweet, "")

    assert "## Capture status" in md
    assert "Partial: The full article body was not captured." in md
    assert "## Link Preview" in md
    assert "not the full linked page" in md
    assert context in md
    assert "- Type: X Article preview" in context
    assert "- Title: Designing durable agent queues" in context


def test_tweet_markdown_renders_card_preview_without_partial_warning() -> None:
    md = _tweet_markdown(
        _tweet(
            link_preview_type="card",
            link_preview_title="A card title",
            link_preview_url="https://example.org/card",
        ),
        "",
    )

    assert "- Type: Card preview" in md
    assert "- URL: https://example.org/card" in md
    assert "## Capture status" not in md


def test_tweet_markdown_partial_capture_has_safe_fallback_warning() -> None:
    md = _tweet_markdown(_tweet(capture_status="partial", capture_warning=""), "")
    assert "Partial: The full source body was not captured." in md


def test_tweet_markdown_renders_complete_quoted_post_as_separate_receipt() -> None:
    tweet = _tweet(
        quoted_tweet_status="available",
        quoted_tweet_id="2032727335074722216",
        quoted_tweet_url="https://x.com/fchollet/status/2032727335074722216",
        quoted_tweet_author_name="François Chollet",
        quoted_tweet_author_handle="fchollet",
        quoted_tweet_text="A quoted post about reliable agent harnesses.",
    )

    context = _quoted_post_context(tweet)
    md = _tweet_markdown(tweet, "")

    assert "## Quoted Post" in md
    assert context in md
    assert "- Author: François Chollet (@fchollet)" in context
    assert "A quoted post about reliable agent harnesses." in context
    assert "not available" not in context
    assert "## Capture status" not in md


def test_tweet_markdown_makes_missing_quoted_text_explicit() -> None:
    tweet = _tweet(
        quoted_tweet_status="partial",
        quoted_tweet_id="91",
        quoted_tweet_url="https://x.com/i/status/91",
        capture_status="partial",
        capture_warning="The quoted-post text was not captured.",
    )

    context = _quoted_post_context(tweet)
    md = _tweet_markdown(tweet, "")

    assert "## Quoted Post" in md
    assert "(not available in the public syndication payload)" in context
    assert context in md


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


def test_x_analysis_uses_analysis_workload_model_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")
    monkeypatch.setenv("DISTILL_PROVIDER", "ollama")
    monkeypatch.setenv("DISTILL_ANALYSIS_MODEL", "qwen2.5:14b")
    monkeypatch.setenv("DISTILL_MODEL", "")
    monkeypatch.setenv("DISTILL_SITE_MODEL", "")
    resolved: list[tuple[str, str, str]] = []

    def fake_llm(rc: Any, workload_tag: str, prompt: str, **kwargs: Any) -> LLM_Response:
        provider, model = rc.resolve(workload_tag)
        resolved.append((workload_tag, provider, model))
        return LLM_Response(text="analysis", input_tokens=10, output_tokens=5, model=model)

    with patch("distill.pipeline.analysis.tweet.llm_call", fake_llm):
        analyze_tweet(_tweet(), config=config)
        _expanded_vocabulary_hint(_tweet(video_url="https://x/video.mp4"))

    assert resolved == [
        ("analysis", "ollama", "qwen2.5:14b"),
        ("analysis", "ollama", "qwen2.5:14b"),
    ]


def test_analyze_tweet_passes_rendered_preview_and_capture_warning_to_prompt(
    tmp_path: Path,
) -> None:
    config = DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")
    captured: dict[str, str] = {}
    tweet = _tweet(
        text="https://t.co/article-only",
        link_preview_type="x_article",
        link_preview_title="Designing durable agent queues",
        link_preview_description="A practical look at leases and retries.",
        capture_status="partial",
        capture_warning="The full article body was not captured.",
    )

    def fake_llm(config: Any, workload_tag: str, prompt: str, **kwargs: Any) -> LLM_Response:
        captured["prompt"] = prompt
        return LLM_Response(text="analysis", input_tokens=10, output_tokens=5, model="local")

    with patch("distill.pipeline.analysis.tweet.llm_call", fake_llm):
        analyze_tweet(tweet, config=config)

    receipt = _tweet_markdown(tweet, "")
    preview_context = _link_preview_context(tweet)
    assert preview_context in receipt
    assert preview_context in captured["prompt"]
    assert tweet.capture_warning in receipt
    assert tweet.capture_warning in captured["prompt"]
    assert "[Link Preview]" in captured["prompt"]


def test_analyze_tweet_passes_exact_quoted_post_receipt_to_prompt(tmp_path: Path) -> None:
    config = DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")
    captured: dict[str, str] = {}
    tweet = _tweet(
        quoted_tweet_status="available",
        quoted_tweet_id="2032727335074722216",
        quoted_tweet_url="https://x.com/fchollet/status/2032727335074722216",
        quoted_tweet_author_name="François Chollet",
        quoted_tweet_author_handle="fchollet",
        quoted_tweet_text="A quoted post about reliable agent harnesses.",
    )

    def fake_llm(config: Any, workload_tag: str, prompt: str, **kwargs: Any) -> LLM_Response:
        captured["prompt"] = prompt
        return LLM_Response(text="analysis", input_tokens=10, output_tokens=5, model="local")

    with patch("distill.pipeline.analysis.tweet.llm_call", fake_llm):
        analyze_tweet(tweet, config=config)

    receipt = _tweet_markdown(tweet, "")
    quoted_context = _quoted_post_context(tweet)
    assert quoted_context in receipt
    assert quoted_context in captured["prompt"]
    assert "[Quoted Post]" in captured["prompt"]


# ---------------------------------------------------------------------------
# ingest_tweet (mocking fetch + transcribe + LLM)
# ---------------------------------------------------------------------------


def test_ingest_tweet_text_only_writes_two_artifacts(tmp_path: Path, capsys) -> None:
    """Tweet without video: writes Tweet.md + Insights.md, no transcript."""
    config = DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")
    text_tweet = _tweet(text="text only post")

    raw_url = "https://x.com/alice/status/12345?access_token=BANNER-CANARY"
    with (
        patch("distill.pipeline.analysis.tweet.fetch_tweet", return_value=text_tweet) as fetch,
        patch("distill.pipeline.analysis.tweet.llm_call", _fake_llm("insights body")),
    ):
        result = ingest_tweet(raw_url, topic="t", config=config)

    assert isinstance(result, IngestedTweet)
    fetch.assert_called_once_with(raw_url)
    assert "BANNER-CANARY" not in capsys.readouterr().out
    assert result.tweet_path.exists()
    assert result.transcript_path is None
    assert result.insights_path is not None and result.insights_path.exists()
    # Tweet.md frontmatter has source=x and the right id
    fm = extract_frontmatter(result.tweet_path.read_text(encoding="utf-8"))
    assert fm["source"] == "x"
    assert fm["source_id"] == "12345"


def test_ingest_tweet_skips_receipt_when_frontmatter_read_fails(tmp_path: Path) -> None:
    config = DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")
    x_dir = config.topic_dir("t") / "x"
    x_dir.mkdir(parents=True, exist_ok=True)
    (x_dir / "other_Tweet.md").write_text("# other\n", encoding="utf-8")
    real_extract = extract_frontmatter
    seen = {"n": 0}

    def flaky_extract(content: str):
        seen["n"] += 1
        if seen["n"] == 1:
            raise OSError("unreadable")
        return real_extract(content)

    with (
        patch("distill.pipeline.analysis.tweet.fetch_tweet", return_value=_tweet()),
        patch("distill.pipeline.analysis.tweet.llm_call", _fake_llm("insights body")),
        patch("distill.pipeline.analysis.tweet.extract_frontmatter", side_effect=flaky_extract),
    ):
        result = ingest_tweet("https://x.com/alice/status/12345", topic="t", config=config)

    assert isinstance(result, IngestedTweet)
    assert result.tweet_path.exists()
    assert seen["n"] >= 1


def test_ingest_tweet_skips_unreadable_sibling_receipt(tmp_path: Path) -> None:
    config = DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")
    x_dir = config.topic_dir("t") / "x"
    x_dir.mkdir(parents=True, exist_ok=True)
    (x_dir / "garbage_Tweet.md").write_bytes(b"\xff\xfe")

    with (
        patch("distill.pipeline.analysis.tweet.fetch_tweet", return_value=_tweet()),
        patch("distill.pipeline.analysis.tweet.llm_call", _fake_llm("insights body")),
    ):
        result = ingest_tweet("https://x.com/alice/status/12345", topic="t", config=config)

    assert isinstance(result, IngestedTweet)
    assert result.tweet_path.exists()


def test_ingest_tweet_skip_analyze(tmp_path: Path) -> None:
    config = DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")
    with patch("distill.pipeline.analysis.tweet.fetch_tweet", return_value=_tweet()):
        result = ingest_tweet(
            "https://x.com/alice/status/12345", topic="t", config=config, analyze=False
        )
    assert result.insights_path is None


def test_raw_only_video_replay_reuses_transcript_and_force_retranscribes(
    tmp_path: Path,
) -> None:
    from distill.ingestors.transcribe import TranscriptionResult

    config = DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")
    tweet = _tweet(video_url="https://video.twimg.com/test.mp4", video_duration_ms=1000)

    def fake_download(url: str, dest: Path, **kwargs: Any) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"video")
        return dest

    transcription = TranscriptionResult(
        text="raw-only transcript",
        provider="faster-whisper",
        model="large-v3",
    )
    with (
        patch("distill.pipeline.analysis.tweet.fetch_tweet", return_value=tweet),
        patch("distill.pipeline.analysis.tweet.download_video", side_effect=fake_download),
        patch("distill.pipeline.analysis.tweet._vocabulary_hint", return_value="Alice"),
        patch("distill.pipeline.analysis.tweet.transcribe_media", return_value=transcription),
    ):
        first = ingest_tweet(tweet.url, topic="t", config=config, analyze=False)

    assert first.transcript_path is not None
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in (first.tweet_path, first.transcript_path)
    }
    with (
        patch("distill.pipeline.analysis.tweet.fetch_tweet", return_value=tweet),
        patch("distill.pipeline.analysis.tweet.download_video") as download,
        patch("distill.pipeline.analysis.tweet._vocabulary_hint") as vocabulary,
        patch("distill.pipeline.analysis.tweet.transcribe_media") as transcribe_media,
    ):
        replay = ingest_tweet(tweet.url, topic="t", config=config, analyze=False)

    assert replay.reused is True
    assert replay.insights_path is None
    assert replay.transcript_path == first.transcript_path
    download.assert_not_called()
    vocabulary.assert_not_called()
    transcribe_media.assert_not_called()
    assert {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in (first.tweet_path, first.transcript_path)
    } == before

    with (
        patch("distill.pipeline.analysis.tweet.fetch_tweet", return_value=tweet),
        patch("distill.pipeline.analysis.tweet.download_video") as forced_download,
        patch("distill.pipeline.analysis.tweet._vocabulary_hint", return_value="Alice"),
        patch(
            "distill.pipeline.analysis.tweet.transcribe_media",
            return_value=transcription,
        ) as forced_transcribe,
    ):
        forced = ingest_tweet(
            tweet.url,
            topic="t",
            config=config,
            analyze=False,
            force=True,
        )

    assert forced.reused is False
    forced_download.assert_not_called()
    forced_transcribe.assert_called_once()


def test_raw_only_replay_detects_edited_post_content(tmp_path: Path) -> None:
    config = DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")
    original = _tweet(text="original raw text")
    edited = _tweet(text="edited raw text")
    with patch(
        "distill.pipeline.analysis.tweet.fetch_tweet",
        side_effect=[original, edited],
    ):
        ingest_tweet(original.url, topic="t", config=config, analyze=False)
        refreshed = ingest_tweet(edited.url, topic="t", config=config, analyze=False)

    assert refreshed.reused is False
    assert "edited raw text" in refreshed.tweet_path.read_text(encoding="utf-8")
    assert extract_frontmatter(refreshed.tweet_path.read_text(encoding="utf-8"))[
        "content_hash"
    ] == _tweet_source_content_hash(edited)


def test_ingest_tweet_reanalyzes_when_same_post_id_has_edited_content(tmp_path: Path) -> None:
    config = DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")
    original = _tweet(text="Original source text")
    edited = _tweet(text="Edited source text")
    llm_calls = 0

    def fake_llm(config: Any, workload_tag: str, prompt: str, **kwargs: Any) -> LLM_Response:
        nonlocal llm_calls
        llm_calls += 1
        return LLM_Response(
            text=f"analysis {llm_calls}",
            input_tokens=10,
            output_tokens=5,
            model="local",
        )

    with (
        patch(
            "distill.pipeline.analysis.tweet.fetch_tweet",
            side_effect=[original, edited],
        ),
        patch("distill.pipeline.analysis.tweet.llm_call", fake_llm),
    ):
        first = ingest_tweet(original.url, topic="t", config=config)
        second = ingest_tweet(edited.url, topic="t", config=config)

    assert llm_calls == 2
    assert second.reused is False
    assert second.tweet_path == first.tweet_path
    assert "Edited source text" in second.tweet_path.read_text(encoding="utf-8")


def test_ingest_tweet_force_reanalyzes_unchanged_content(tmp_path: Path) -> None:
    config = DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")
    tweet = _tweet()
    llm_calls = 0

    def fake_llm(config: Any, workload_tag: str, prompt: str, **kwargs: Any) -> LLM_Response:
        nonlocal llm_calls
        llm_calls += 1
        return LLM_Response(text="analysis", input_tokens=10, output_tokens=5, model="local")

    with (
        patch("distill.pipeline.analysis.tweet.fetch_tweet", return_value=tweet),
        patch("distill.pipeline.analysis.tweet.llm_call", fake_llm),
    ):
        ingest_tweet(tweet.url, topic="t", config=config)
        result = ingest_tweet(tweet.url, topic="t", config=config, force=True)

    assert llm_calls == 2
    assert result.reused is False


def test_ingest_tweet_migrates_matching_legacy_pair_without_model_call(
    tmp_path: Path,
) -> None:
    config = DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")
    original = _tweet(like_count=10, reply_count=2)
    with (
        patch("distill.pipeline.analysis.tweet.fetch_tweet", return_value=original),
        patch("distill.pipeline.analysis.tweet.llm_call", _fake_llm("legacy insight")),
    ):
        first = ingest_tweet(original.url, topic="t", config=config)

    assert first.insights_path is not None
    for path in (first.tweet_path, first.insights_path):
        atomic_write_text(
            path,
            apply_frontmatter(path.read_text(encoding="utf-8"), {"content_hash": ""}),
        )
    changed_counts = _tweet(like_count=999, reply_count=88)

    with (
        patch("distill.pipeline.analysis.tweet.fetch_tweet", return_value=changed_counts),
        patch("distill.pipeline.analysis.tweet.llm_call") as model_call,
    ):
        migrated = ingest_tweet(changed_counts.url, topic="t", config=config)

    assert migrated.reused is True
    assert "legacy requested artifacts" in migrated.skipped_reasons[0]
    model_call.assert_not_called()
    receipt_hash = extract_frontmatter(migrated.tweet_path.read_text(encoding="utf-8"))[
        "content_hash"
    ]
    insight_hash = extract_frontmatter(migrated.insights_path.read_text(encoding="utf-8"))[
        "content_hash"
    ]
    assert receipt_hash == insight_hash == _tweet_source_content_hash(changed_counts)


def test_ingest_tweet_failed_analysis_clears_pair_commit_and_retries(
    tmp_path: Path,
) -> None:
    config = DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")
    tweet = _tweet()
    with (
        patch("distill.pipeline.analysis.tweet.fetch_tweet", return_value=tweet),
        patch("distill.pipeline.analysis.tweet.llm_call", _fake_llm("old insight")),
    ):
        first = ingest_tweet(tweet.url, topic="t", config=config)

    assert first.insights_path is not None
    # Reproduce the interrupted migration shape from the live run: the receipt
    # carries the new hash while its stale insight does not.
    atomic_write_text(
        first.insights_path,
        apply_frontmatter(
            first.insights_path.read_text(encoding="utf-8"),
            {"content_hash": ""},
        ),
    )

    with (
        patch("distill.pipeline.analysis.tweet.fetch_tweet", return_value=tweet),
        patch(
            "distill.pipeline.analysis.tweet.llm_call",
            side_effect=RuntimeError("model unavailable"),
        ) as failed_call,
        pytest.raises(RuntimeError, match="model unavailable"),
    ):
        ingest_tweet(tweet.url, topic="t", config=config)

    failed_call.assert_called_once()
    assert "content_hash" not in extract_frontmatter(first.tweet_path.read_text(encoding="utf-8"))
    assert "content_hash" not in extract_frontmatter(
        first.insights_path.read_text(encoding="utf-8")
    )

    with (
        patch("distill.pipeline.analysis.tweet.fetch_tweet", return_value=tweet),
        patch(
            "distill.pipeline.analysis.tweet.llm_call",
            side_effect=_fake_llm("recovered"),
        ) as retry,
    ):
        recovered = ingest_tweet(tweet.url, topic="t", config=config)

    assert recovered.reused is False
    retry.assert_called_once()
    recovered_hash = _tweet_source_content_hash(tweet)
    assert (
        extract_frontmatter(recovered.tweet_path.read_text(encoding="utf-8"))["content_hash"]
        == recovered_hash
    )
    assert recovered.insights_path is not None
    assert (
        extract_frontmatter(recovered.insights_path.read_text(encoding="utf-8"))["content_hash"]
        == recovered_hash
    )


def test_ingest_tweet_persists_partial_capture_status_in_receipt(tmp_path: Path) -> None:
    config = DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")
    article_tweet = _tweet(
        text="https://t.co/article-only",
        link_preview_type="x_article",
        link_preview_title="Designing durable agent queues",
        link_preview_description="A practical look at leases and retries.",
        capture_status="partial",
        capture_warning="The full article body was not captured.",
    )

    with patch("distill.pipeline.analysis.tweet.fetch_tweet", return_value=article_tweet):
        result = ingest_tweet(
            "https://x.com/alice/status/12345",
            topic="t",
            config=config,
            analyze=False,
        )

    receipt = result.tweet_path.read_text(encoding="utf-8")
    frontmatter = extract_frontmatter(receipt)
    assert frontmatter["capture_status"] == "partial"
    assert frontmatter["has_link_preview"] == "true"
    assert "## Link Preview" in receipt
    assert article_tweet.capture_warning in receipt


def test_ingest_tweet_strict_verify_grounds_link_preview_claims_against_receipt(
    tmp_path: Path,
) -> None:
    config = DistillConfig(
        xai_api_key="x",
        distill_output_dir=tmp_path / "lib",
        distill_verify="strict",
    )
    article_tweet = _tweet(
        text="https://t.co/article-only",
        link_preview_type="x_article",
        link_preview_title="Testing 99 verifier loops",
        capture_status="partial",
        capture_warning="The full article body was not captured.",
    )
    insight = "## Key Claims\n\n- [Link Preview] The preview describes 99 verifier loops."

    with (
        patch("distill.pipeline.analysis.tweet.fetch_tweet", return_value=article_tweet),
        patch("distill.pipeline.analysis.tweet.llm_call", _fake_llm(insight)),
    ):
        result = ingest_tweet(
            "https://x.com/alice/status/12345",
            topic="t",
            config=config,
        )

    assert result.insights_path is not None
    assert not any("refused" in reason for reason in result.skipped_reasons)


def test_ingest_tweet_persists_and_strictly_grounds_quoted_post(tmp_path: Path) -> None:
    config = DistillConfig(
        xai_api_key="x",
        distill_output_dir=tmp_path / "lib",
        distill_verify="strict",
    )
    quoted_tweet = _tweet(
        quoted_tweet_status="available",
        quoted_tweet_id="101",
        quoted_tweet_url="https://x.com/source/status/101",
        quoted_tweet_author_name="Source Author",
        quoted_tweet_author_handle="source",
        quoted_tweet_text="The harness completed 77 verifier loops.",
    )
    insight = "## Key Claims\n\n- [Quoted Post] The harness completed 77 verifier loops."

    with (
        patch("distill.pipeline.analysis.tweet.fetch_tweet", return_value=quoted_tweet),
        patch("distill.pipeline.analysis.tweet.llm_call", _fake_llm(insight)),
    ):
        result = ingest_tweet(
            "https://x.com/alice/status/12345",
            topic="t",
            config=config,
        )

    assert result.insights_path is not None
    receipt = result.tweet_path.read_text(encoding="utf-8")
    frontmatter = extract_frontmatter(receipt)
    assert frontmatter["quoted_post_status"] == "available"
    assert frontmatter["has_quoted_post"] == "true"
    assert frontmatter["quoted_post_id"] == "101"
    assert "## Quoted Post" in receipt
    assert not any("refused" in reason for reason in result.skipped_reasons)


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


def test_ingest_tweet_replaces_oversized_cached_media(tmp_path: Path, monkeypatch) -> None:
    from distill.ingestors.transcribe import TranscriptionResult
    from distill.ingestors.x import media as x_media

    monkeypatch.setattr(x_media, "_MAX_VIDEO_BYTES", 10)
    config = DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")
    video_tweet = _tweet(video_url="https://video.twimg.com/test.mp4", video_duration_ms=1000)
    expected_dir = _x_post_dir(config, "t", video_tweet)
    expected_dir.mkdir(parents=True, exist_ok=True)
    media_path = expected_dir / "media.mp4"
    media_path.write_bytes(b"x" * 11)
    download_calls = 0

    def _fake_download(_url: str, dest: Path, **_kwargs: Any) -> Path:
        nonlocal download_calls
        download_calls += 1
        assert not dest.exists()
        dest.write_bytes(b"valid")
        return dest

    with (
        patch("distill.pipeline.analysis.tweet.fetch_tweet", return_value=video_tweet),
        patch("distill.pipeline.analysis.tweet.download_video", side_effect=_fake_download),
        patch(
            "distill.pipeline.analysis.tweet.transcribe_media",
            return_value=TranscriptionResult(text="t", provider="faster-whisper", model="large-v3"),
        ),
        patch("distill.pipeline.analysis.tweet.llm_call", _fake_llm("ok")),
    ):
        ingest_tweet("https://x.com/alice/status/12345", topic="t", config=config)

    assert download_calls == 1
    assert media_path.read_bytes() == b"valid"


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


def test_ingest_tweet_budget_crossing_in_video_pipeline_stops_later_work(
    tmp_path: Path,
) -> None:
    import pytest

    from distill.pipeline.costs import BudgetExceededError, CostTracker

    config = DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")
    video_tweet = _tweet(video_url="https://video.twimg.com/test.mp4", video_duration_ms=1000)
    tracker = CostTracker(budget=0.0)

    def _fake_download(url: str, dest: Path, **kwargs: Any) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x")
        return dest

    def _cross_budget(*args: Any, **kwargs: Any) -> Any:
        kwargs["tracker"].record_transcription("openai", 3600.0)
        raise AssertionError("record_transcription should have raised")

    with (
        patch("distill.pipeline.analysis.tweet.fetch_tweet", return_value=video_tweet),
        patch("distill.pipeline.analysis.tweet.download_video", side_effect=_fake_download),
        patch("distill.pipeline.analysis.tweet._vocabulary_hint", return_value="Alice"),
        patch(
            "distill.pipeline.analysis.tweet.transcribe_media", side_effect=_cross_budget
        ) as mock_transcribe,
        patch("distill.pipeline.analysis.tweet.llm_call") as mock_analysis,
        pytest.raises(BudgetExceededError),
    ):
        ingest_tweet(
            "https://x.com/alice/status/12345",
            topic="t",
            config=config,
            tracker=tracker,
        )

    assert mock_transcribe.call_count == 1
    assert mock_analysis.call_count == 0
    assert len(tracker.transcriptions) == 1
