"""Prompt templates for raw local media (audio/video file) analysis."""

# pyright: strict

from __future__ import annotations

from distill.prompts.shared import UNTRUSTED_CONTENT_RULES

__all__ = ["media_insight_prompt"]


def media_insight_prompt(
    *,
    file_name: str,
    transcript: str,
) -> str:
    """Single-pass extraction for a raw media file with no native structure.

    Unlike a podcast (show framing) or a YouTube video (title/channel
    context), a local recording arrives with nothing but a filename: it may
    be a conference talk, an interview, a meeting, a voice memo, or a lecture.
    The prompt must first establish what it is listening to, then extract.
    """
    return f"""You are extracting intelligence from a transcribed local
recording for a research corpus. There is no metadata beyond the filename --
establish what kind of recording this is from the transcript itself, then
produce a structured insights document grounded only in what was said.

SECURITY: {UNTRUSTED_CONTENT_RULES}

FILE: {file_name}

TRANSCRIPT:
{transcript}

Generate a structured insight document with these sections:

## What This Recording Is
1-2 sentences: the apparent format (talk, interview, meeting, memo,
lecture...), the apparent speaker(s)/roles, and the subject -- all inferred
from the transcript only, marked as inference.

## Summary
2-3 sentences: the substance and the single most load-bearing takeaway.

## Key Claims & Insights
Bullet list of concrete factual claims, data points, decisions, and
first-hand accounts, attributed to speakers where distinguishable. Include
specific names, numbers, dates, versions exactly as spoken.

## Frameworks & Walkthroughs
Any framework, process, or step-by-step account, captured in full.

## Opinions, Predictions & Stance
Interpretive positions clearly marked as opinion, with the reasoning.

## Action Items & Open Threads
Anything stated as a next step, commitment, or unresolved question (most
useful when the recording turns out to be a meeting or working session).

## Confidence
One short paragraph: transcript quality signals (garbled passages, possible
mistranscriptions of proper nouns), and what a researcher should verify.

Ground every claim in the transcript above. Do not invent context the
recording does not provide."""
