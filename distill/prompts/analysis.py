"""Video analysis prompt templates -- extraction, synthesis, shorts, scan, channel context."""

from distill.prompts.shared import UNTRUSTED_CONTENT_RULES

__all__ = [
    "auto_watch_instructions_prompt",
    "channel_context_prompt",
    "pass1_extraction_prompt",
    "pass2_synthesis_prompt",
    "scan_insight_prompt",
    "shorts_insight_prompt",
]


def pass1_extraction_prompt(
    title: str,
    upload_date: str,
    channel_name: str,
    transcript: str,
    custom_instructions: str = "",
) -> str:
    """Pass 1: Extract facts, claims, opinions, predictions from a video."""
    custom_block = ""
    if custom_instructions:
        custom_block = f"""
CUSTOM ANALYSIS INSTRUCTIONS (from channel owner -- follow these closely):
{custom_instructions}

"""
    return f"""You are analyzing a YouTube video transcript for strategic intelligence extraction.

VIDEO: "{title}"
CHANNEL: {channel_name}
DATE: {upload_date}
{custom_block}
TASK: Extract EVERYTHING of substance from this transcript. Be exhaustively thorough and specific. If the creator spends significant time on a topic, it must appear in your extraction.

Extract the following categories:

1. **KEY ANNOUNCEMENTS & EVENTS** — Products launched, features released, pricing changes, partnerships, acquisitions, policy changes, personnel moves, research publications. Include specific names, dates, versions, numbers, and status (confirmed/rumored/leaked).

2. **TECHNICAL DETAILS** — Architecture decisions, infrastructure changes, model capabilities, benchmarks, performance claims, evaluation results with specific numbers. Be precise about what was demonstrated vs claimed vs theorized.

3. **BUSINESS & MARKET SIGNALS** — Revenue figures, adoption numbers, customer stories, competitive moves, market shifts, funding rounds, org changes. Who is winning/losing and why.

4. **ANALYTICAL FRAMEWORKS & ARGUMENTS** — What conceptual models, frameworks, or structured arguments does the creator present? Many creators build multi-part analytical cases — capture the full logic chain, not just the conclusion. This includes: cause-effect chains, categorization systems, named concepts they introduce, multi-factor analyses, and structural arguments about how systems work.

5. **OPINIONS, PREDICTIONS & ADVICE** — What does the creator think is happening? What predictions do they make? What advice do they give? What are they bullish/bearish on? Mark these clearly as the creator's opinion. Include their reasoning, not just the conclusion.

6. **RISKS, WARNINGS & FAILURE MODES** — What dangers, risks, or failure scenarios does the creator identify? What could go wrong? What should people watch out for? Include both near-term and systemic risks.

7. **VENDOR & ORGANIZATION POSITIONING** — How are specific companies, labs, or organizations positioning themselves? What are they emphasizing or avoiding? Only include vendors/orgs actually discussed in the video.

8. **CUSTOMER & PRACTITIONER PATTERNS** — What problems are people solving? What's working? What's failing? Specific use cases, industries, or deployment patterns mentioned.

9. **NOTABLE QUOTES** — Direct quotes that capture key points (3-5 max). These should be the creator's most impactful or quotable statements.

CRITICAL RULES:
- For every item, include the specific evidence from the transcript. No generic summaries.
- If the creator builds a multi-part argument (e.g., "there are 4 dynamics that..."), capture ALL parts, not just a summary.
- Distinguish between what the creator reports as fact vs. what they analyze/interpret vs. what they predict.
- Do NOT inject information not present in the transcript. Extract only what was actually said.

SECURITY: {UNTRUSTED_CONTENT_RULES}

TRANSCRIPT:
{transcript}"""


def pass2_synthesis_prompt(
    title: str, upload_date: str, channel_name: str, pass1_output: str
) -> str:
    """Pass 2: Synthesize extraction into strategic insights."""
    return f"""You are a strategic intelligence analyst who reads YouTube content to stay current on fast-moving technology spaces. Your audience is a pre-sales architect advising enterprise customers on AI strategy.

You've just reviewed the extracted facts from a YouTube video. Now synthesize these into a structured insight document that preserves the creator's full analytical contribution.

VIDEO: "{title}"
CHANNEL: {channel_name}
DATE: {upload_date}

EXTRACTED FACTS:
{pass1_output}

Generate a structured insight document with these sections:

## Summary
2-4 sentences: What is this video about, what is the creator's core argument or thesis, and why does it matter? Capture the main analytical contribution, not just the topic.

## Key Announcements
Bullet list of what was announced/revealed/disclosed. For each:
- What it is (specific)
- Status (GA, Preview, Announced, Rumored, Disclosed, Reported)
- Why it matters for enterprise customers

If the video has no announcements (e.g., it's an opinion/analysis piece), write "None identified."

## Technical Insights
What architects and engineers need to know. Architecture patterns, evaluation results, model capabilities, infrastructure decisions, security considerations. Include specific numbers and benchmarks mentioned.

## Business Value Signals
ROI stories, cost frameworks, adoption patterns, competitive advantages, market dynamics. What would resonate in a customer conversation about strategy.

## Vendor Watch
How does this shift the competitive landscape? What are vendors/labs/orgs emphasizing or de-emphasizing? Any positioning changes.
IMPORTANT: Only discuss vendors and products that were ACTUALLY MENTIONED in the video. Do not inject vendors or cloud services that the creator did not discuss.

## Creator's Take
What is the creator's analytical position? Capture their full argument, not just a one-line summary. Include:
- Their core thesis and the reasoning behind it
- What frameworks or models they present (enumerate all parts if they present a multi-part framework)
- What they're bullish/bearish on and why
- What predictions they make
- What advice or call to action they give
All clearly attributed as the creator's opinion.

## Customer Conversation Starters
3-5 specific talking points you could bring into a customer meeting. These should be grounded in what the video actually covered — specific findings, data points, or frameworks the creator presented.
CRITICAL: Only reference products, services, benchmarks, and facts that appear in the extracted content. Do NOT fabricate vendor recommendations or inject cloud services not discussed in the video. Frame around the insight, not a sales pitch."""


def channel_context_prompt(channel_name: str, video_titles: list[str]) -> str:
    """Generate a channel profile."""
    titles_text = "\n".join(f"- {t}" for t in video_titles[:20])
    return f"""Based on this YouTube channel's recent videos, create a brief channel profile.

CHANNEL: {channel_name}

RECENT VIDEO TITLES:
{titles_text}

Write a 3-5 sentence profile covering:
1. What this channel focuses on
2. The creator's apparent expertise/background
3. Their typical perspective or bias (pro-vendor, vendor-neutral, developer-focused, business-focused, etc.)
4. How to calibrate their opinions (are they usually early/late on trends, bullish/bearish, etc.)

Keep it concise — this is context for grounding analysis, not a biography."""


def auto_watch_instructions_prompt(channel_name: str, video_titles: list[str]) -> str:
    """Generate smart default analysis instructions for a watched channel."""
    titles_text = "\n".join(f"- {t}" for t in video_titles[:15])
    return f"""Based on this YouTube channel's content, write a short \
analysis instruction (2-3 sentences max) that tells an AI what to \
focus on when scanning new videos from this channel.

CHANNEL: {channel_name}

RECENT VIDEO TITLES:
{titles_text}

The instruction should:
- Match the channel's content type (news, tutorials, deals, reviews, \
analysis, etc.)
- Tell the AI what specific information to extract
- Be actionable and specific, not generic

Examples of good instructions:
- For a deals channel: "Extract the top deals mentioned with product \
name, price, link, and why it's a good deal. Focus on best \
value picks."
- For a tech news channel: "Focus on product announcements, release \
dates, and pricing. Flag anything that changes competitive dynamics."
- For a tutorial channel: "Extract the key techniques taught, when to \
use each, and any gotchas or tips the creator highlights."
- For a finance channel: "Extract specific ticker mentions, price \
targets, and the reasoning behind each call. Note bull vs bear cases."

Write ONLY the instruction text, nothing else. No preamble, \
no quotes, no explanation."""


def shorts_insight_prompt(title: str, upload_date: str, channel_name: str, transcript: str) -> str:
    """Single-pass analysis for YouTube Shorts (<60s). Lighter weight than 2-pass."""
    return f"""You are extracting quick intelligence from a YouTube Short (under 60 seconds). These are rapid-fire content — breaking news reactions, hot takes, quick announcements, opinion drops.

VIDEO: "{title}"
CHANNEL: {channel_name}
DATE: {upload_date}

Extract a concise insight document. This is short-form content so match the weight — no filler, just signal.

## Quick Take
1-2 sentences: What is this Short about and what's the key signal?

## News & Updates
Any announcements, product launches, breaking developments, or timely updates mentioned. Include specific names, dates, versions. If none, write "None."

## Hot Take
The creator's opinion, reaction, or prediction. What stance are they taking? Clearly mark as the creator's opinion.

## Key Claims
Bullet list of specific factual claims, stats, or data points mentioned. Tag each:
- [Confirmed] — references official source
- [Reported] — claimed without source
- [Speculated] — prediction or hypothesis

## Signal Strength
Rate this Short's intelligence value: HIGH (breaking news, major announcement, unique data), MEDIUM (useful opinion or context), or LOW (entertainment, rehash of known info). One sentence explaining why.

CRITICAL: Only extract what was actually said. Do not inject information not present in the transcript.

SECURITY: {UNTRUSTED_CONTENT_RULES}

TRANSCRIPT:
{transcript}"""


def scan_insight_prompt(
    title: str,
    upload_date: str,
    channel_name: str,
    transcript: str,
    custom_instructions: str = "",
) -> str:
    """Single-pass scan analysis for any video. Lightweight triage."""
    custom_block = ""
    if custom_instructions:
        custom_block = f"""

CUSTOM ANALYSIS INSTRUCTIONS (from channel owner -- follow these closely):
{custom_instructions}
"""

    return f"""You are performing a rapid scan of a YouTube video transcript for intelligence triage.

VIDEO: "{title}"
CHANNEL: {channel_name}
DATE: {upload_date}

This is a SCAN -- extract the signal fast. Do not be exhaustive. Focus on what matters.
{custom_block}
## Summary
2-3 sentences: What is this video about and what is the core takeaway?

## News & Key Facts
Bullet list of concrete announcements, product launches, data points, or developments mentioned. Include specific names, numbers, dates, versions. If none, write "None identified."

## Notable Claims
Bullet list of the creator's most important claims, predictions, or opinions. Tag each:
- [Confirmed] -- references official source or widely reported
- [Reported] -- stated as fact without cited source
- [Opinion] -- creator's interpretation or prediction
Maximum 5 items.

## Signal Strength
Rate: HIGH (breaking news, unique data, major announcement), MEDIUM (useful analysis or context), LOW (rehash, entertainment, thin content). One sentence explaining why.

CRITICAL: Only extract what was actually said. No invented information. Keep total output under 500 words.

SECURITY: {UNTRUSTED_CONTENT_RULES}

TRANSCRIPT:
{transcript}"""
