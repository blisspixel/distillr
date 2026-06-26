"""Prompt templates for podcast episode analysis."""

# pyright: strict

from __future__ import annotations

from distill.prompts.shared import UNTRUSTED_CONTENT_RULES

__all__ = ["podcast_insight_prompt"]


def podcast_insight_prompt(
    *,
    show_title: str,
    episode_title: str,
    published: str,
    episode_url: str,
    description: str,
    transcript: str,
) -> str:
    """Single-pass extraction prompt tuned for interview/conversation audio.

    Podcasts differ from lecture-shaped video: substance arrives
    conversationally, claims are made by *speakers* (host vs guest matters),
    and the show notes are marketing framing rather than content. The
    transcript is the primary source; the description is context only.
    """
    return f"""You are extracting intelligence from a podcast episode for a
research corpus. Treat the transcript as the primary source material and
produce a structured insights document grounded only in what was actually
said.

SECURITY: {UNTRUSTED_CONTENT_RULES}

SHOW: {show_title}
EPISODE: {episode_title}
PUBLISHED: {published}
URL: {episode_url}

SHOW NOTES (publisher framing -- context only, not primary content):
{description}

TRANSCRIPT:
{transcript}

Generate a structured insight document with these sections:

## Summary
2-3 sentences: what this conversation is about, who is speaking (host/guest
roles as evident from the transcript), and the single most substantive
takeaway.

## Key Claims & Insights
Bullet list of concrete factual claims, announcements, data points, and
first-hand accounts. Attribute each to the speaker where the transcript
makes that evident ("[Guest]", "[Host]", or the name if stated). Include
specific names, numbers, dates, versions. Distinguish first-hand experience
("we did X at company Y") from secondhand reporting.

## Frameworks & Walkthroughs
Any framework, methodology, mental model, or step-by-step account presented
in the conversation, captured in full with every enumerated part.

## Opinions, Predictions & Stance
Interpretive positions, predictions, recommendations, and warnings --
clearly marked as opinion, with the speaker's reasoning, not just the
conclusion.

## Notable Quotes
Up to 5 short verbatim quotes that carry the conversation's substance
(claims, admissions, memorable formulations). Exact words only.

## Underlying Sources Referenced
Papers, tools, companies, people, books, or prior episodes the conversation
points at, each with whatever identifying detail was given.

## Confidence
One short paragraph: transcript quality (publisher transcript vs automated),
how much rests on a single speaker's claims, and what a researcher should
verify before citing.

Ground every claim in the transcript above. Do not import outside knowledge
about the show or its guests."""
