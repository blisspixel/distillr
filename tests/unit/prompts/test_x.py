"""Tests for distill.prompts.x."""

from __future__ import annotations

from distill.prompts.x import tweet_insight_prompt


def _prompt(**overrides):
    defaults = {
        "author_name": "Alice",
        "author_handle": "@alice",
        "posted_at": "2026-05-16T12:00:00Z",
        "tweet_url": "https://x.com/alice/status/1",
        "tweet_text": "Anthropic just released a workshop",
    }
    defaults.update(overrides)
    return tweet_insight_prompt(**defaults)


def test_prompt_includes_required_sections() -> None:
    out = _prompt()
    assert "## Summary" in out
    assert "## Key Claims" in out
    assert "## Frameworks" in out
    assert "## Opinions" in out
    assert "## Underlying Sources Referenced" in out
    assert "## Signal Strength" in out


def test_prompt_embeds_metadata_verbatim() -> None:
    out = _prompt(
        author_name="Alice Smith", author_handle="@alice_s", tweet_url="https://x.com/x/status/9"
    )
    assert "Alice Smith" in out
    assert "@alice_s" in out
    assert "https://x.com/x/status/9" in out


def test_prompt_text_only_path_omits_transcript_block() -> None:
    out = _prompt(tweet_text="just the tweet")
    assert "ATTACHED VIDEO TRANSCRIPT" not in out
    assert "just the tweet" in out


def test_prompt_with_transcript_treats_video_as_primary() -> None:
    out = _prompt(transcript="speaker says X")
    assert "ATTACHED VIDEO TRANSCRIPT" in out
    assert "speaker says X" in out


def test_prompt_note_text_block_only_when_distinct() -> None:
    """If note_text equals tweet_text, don't duplicate it."""
    out_same = _prompt(tweet_text="same", note_text="same")
    out_diff = _prompt(tweet_text="short", note_text="much longer body text")
    assert "LONG-FORM BODY" not in out_same
    assert "LONG-FORM BODY" in out_diff
    assert "much longer body text" in out_diff


def test_prompt_media_summary_appended() -> None:
    out = _prompt(media_summary="video clip, 30s")
    assert "ATTACHED MEDIA:" in out
    assert "video clip, 30s" in out


def test_prompt_labels_link_preview_and_partial_capture() -> None:
    warning = "The full article body was not captured."
    preview = "- Type: X Article preview\n- Title: Durable agent queues"
    out = _prompt(
        tweet_text="https://t.co/article-only",
        link_preview=preview,
        capture_status="partial",
        capture_warning=warning,
    )

    assert "LINK PREVIEW" in out
    assert preview in out
    assert "[Link Preview]" in out
    assert "CAPTURE STATUS:" in out
    assert f"Partial: {warning}" in out
    assert "not the full linked page" in out
    assert "do not complete" in out


def test_prompt_complete_capture_without_preview_omits_optional_blocks() -> None:
    out = _prompt(capture_status="complete")
    assert "LINK PREVIEW (" not in out
    assert "CAPTURE STATUS:" not in out


def test_prompt_partial_capture_has_safe_fallback_warning() -> None:
    out = _prompt(capture_status="partial", capture_warning="")
    assert "Partial: The full source body was not captured." in out


def test_prompt_labels_quoted_post_as_distinct_attributed_source() -> None:
    quoted = (
        "- Author: François Chollet (@fchollet)\n"
        "- Post ID: 2032727335074722216\n\n"
        "Text:\nQuoted source text"
    )
    out = _prompt(quoted_post=quoted)

    assert "QUOTED POST (distinct source material" in out
    assert quoted in out
    assert "[Quoted Post]" in out
    assert "Attribute [Quoted Post] claims to the quoted author" in out
    assert "does not by\n  itself establish" in out
    assert "quoted-post text" in out


def test_prompt_emphasizes_no_invention_rule() -> None:
    out = _prompt()
    assert "CRITICAL RULES" in out
    assert "Do NOT" in out or "do NOT" in out
