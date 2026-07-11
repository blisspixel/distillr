"""Prompt templates for X (Twitter) post analysis."""

# pyright: strict

from __future__ import annotations

from distill.prompts.shared import UNTRUSTED_CONTENT_RULES

__all__ = ["tweet_insight_prompt", "vocabulary_expansion_prompt"]


def vocabulary_expansion_prompt(
    *,
    author_name: str,
    author_handle: str,
    tweet_text: str,
    note_text: str = "",
    video_duration_s: float = 0.0,
) -> str:
    """Ask the LLM to predict proper nouns the attached video likely mentions.

    The raw tweet text is a thin signal for Whisper's ``initial_prompt`` —
    a tweet may say "Anthropic released X" without ever spelling out the
    specific product/people names that the video transcript will actually
    contain. This prompt asks the LLM to expand the tweet's surface
    vocabulary into the proper-noun set the video is likely to discuss,
    so Whisper's bias actually covers the words it needs to recognize.

    Output is a single line of comma-separated proper nouns — no headers,
    no explanations, no commentary. Designed to drop straight into
    Whisper's ``initial_prompt`` parameter (≤200 tokens budget).
    """
    note_block = ""
    if note_text and note_text.strip() != tweet_text.strip():
        note_block = f"\n\nLong-form body:\n{note_text}"
    duration_block = ""
    if video_duration_s:
        minutes = video_duration_s / 60.0
        duration_block = f"\n\nAttached video duration: {minutes:.1f} minutes"

    return f"""You are preparing a vocabulary hint for an audio-transcription
model (Whisper) so it spells proper nouns correctly.

SOURCE TWEET:
Author: {author_name} ({author_handle})
Text: {tweet_text}{note_block}{duration_block}

TASK: Predict the proper nouns, product names, technical terms, people
names, organization names, and domain-specific acronyms that the
attached video is likely to mention but that are NOT spelled out in the
tweet text above. Include obvious adjacent terms even if not explicitly
named in the tweet (for example: if the tweet mentions "Claude", a
video about Claude is likely to also discuss "Claude Code", "CLAUDE.md",
"MCP", "Sonnet", "Haiku", "Opus", "Anthropic", "system prompt",
"artifacts", etc.).

RULES:
- Output ONLY a single line of comma-separated terms.
- No headers, no preamble, no explanation, no commentary.
- Spell each term exactly as it should appear in the transcript.
- 30-60 terms is the right size. Stop well under 200 words total.
- Include both the tweet's own proper nouns AND likely adjacent ones.
- Skip generic words ("the", "good", "important") — only proper nouns,
  product names, acronyms, jargon, and technical terms.
- If the tweet text is non-English, still emit the proper nouns in
  their canonical English spelling (most tech proper nouns are
  English-derived even in non-English content).

Output now:"""


def tweet_insight_prompt(
    *,
    author_name: str,
    author_handle: str,
    posted_at: str,
    tweet_url: str,
    tweet_text: str,
    note_text: str = "",
    link_preview: str = "",
    capture_status: str = "complete",
    capture_warning: str = "",
    quoted_post: str = "",
    transcript: str = "",
    media_summary: str = "",
) -> str:
    """Single-pass extraction prompt for a tweet.

    Tweets are short-form, so use a single pass (matching the Shorts
    prompt shape, not the 2-pass long-form video prompt). When a video
    transcript is available it's treated as the primary substance; the
    tweet text is contextual framing.
    """
    transcript_block = ""
    if transcript:
        transcript_block = f"""

ATTACHED VIDEO TRANSCRIPT (this is the primary substance — the tweet text
above is just the poster's framing/headline):
{transcript}
"""

    note_block = ""
    if note_text and note_text.strip() != tweet_text.strip():
        note_block = f"""

LONG-FORM BODY (note_tweet):
{note_text}
"""

    link_preview_block = ""
    if link_preview:
        link_preview_block = f"""

LINK PREVIEW (public syndication metadata only, not the full linked page):
{link_preview}
"""

    capture_block = ""
    if capture_status == "partial":
        capture_block = f"""

CAPTURE STATUS:
Partial: {capture_warning or "The full source body was not captured."}
"""

    quoted_post_block = ""
    if quoted_post:
        quoted_post_block = f"""

QUOTED POST (distinct source material embedded by the outer post):
{quoted_post}
"""

    media_block = ""
    if media_summary:
        media_block = f"""

ATTACHED MEDIA:
{media_summary}
"""

    return f"""You are extracting intelligence from an X (Twitter) post for a
research corpus. Treat the post as primary source material and produce a
structured insights document grounded only in what was actually said.

SECURITY: {UNTRUSTED_CONTENT_RULES}

POST: {tweet_url}
AUTHOR: {author_name} ({author_handle})
POSTED: {posted_at}{capture_block}

TWEET TEXT:
{tweet_text}{quoted_post_block}{note_block}{link_preview_block}{media_block}{transcript_block}

Generate a structured insight document with these sections:

## Summary
2-3 sentences: What is this post about, what is the core claim or signal,
and why does it matter? If a video transcript is attached, the summary
should reflect the video's substance, not just the tweet's headline.

## Key Claims
Bullet list of the concrete factual claims, announcements, or data points
made. For each, tag the source within the post:
- [Tweet] — claim is in the tweet text itself
- [Video] — claim is in the attached video transcript
- [Note] — claim is in the long-form note_tweet body
- [Link Preview] - claim is present only in public link-preview metadata
- [Quoted Post] - claim is in the separately authored quoted-post text

Include specific names, numbers, dates, versions. If a claim is a
re-statement of someone else's work (e.g., "Anthropic just released X"),
note that explicitly and capture the underlying subject.

## Frameworks & Analytical Content
If the post (especially via video) presents a framework, model,
walkthrough, or multi-part argument, capture it in full. List every part
of any enumerated framework. Tutorial walkthroughs should preserve the
ordered steps.

## Opinions, Predictions & Stance
The author's interpretive position, predictions, recommendations, or
warnings — clearly marked as opinion. Include reasoning, not just the
conclusion.

## Underlying Sources Referenced
If the post points at other primary material (a workshop, paper, tool,
URL, repository, person, organization), list each one with whatever
identifying detail the post provided. This is what a downstream
researcher would chase to verify or expand.

## Signal Strength
Rate this post's intelligence value: HIGH (breaking news, unique data,
substantive walkthrough or framework), MEDIUM (useful synthesis or
opinion grounded in evidence), LOW (rehash, promotional, thin
commentary). One sentence explaining why.

CRITICAL RULES:
- Extract only what is actually present in the tweet text, note, attached
  transcript, link preview, or quoted-post text. Do NOT invent quotes,
  fabricate vendor positioning, or inject information not in the source.
- Treat [Link Preview] as preview metadata only. Do not imply that the linked
  page or full X Article body was captured or read.
- Attribute [Quoted Post] claims to the quoted author. Quoting does not by
  itself establish that the outer post's author endorses the quoted claim.
- If CAPTURE STATUS is Partial, state the limitation and do not complete,
  reconstruct, or infer missing note, article, or quoted-post text.
- If the substance is in the attached video and the tweet text is just a
  hype headline, say so in Summary and let the Key Claims be
  predominantly [Video]-tagged.
- If the post is genuinely thin (a one-line promotional pointer with no
  attached substance), mark Signal Strength as LOW and keep the document
  short — do not pad."""
