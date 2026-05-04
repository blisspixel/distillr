"""Synthesis prompt templates -- channel, topic, site, paper, corpus synthesis."""

__all__ = [
    "channel_synthesis_prompt",
    "corpus_synthesis_prompt",
    "paper_insight_prompt",
    "paper_topic_synthesis_prompt",
    "site_page_insight_prompt",
    "site_synthesis_prompt",
    "site_topic_synthesis_prompt",
    "topic_synthesis_prompt",
]


def channel_synthesis_prompt(channel_name: str, channel_context: str, all_insights: str) -> str:
    """Synthesize all video insights into a channel-level knowledge base."""
    return f"""You are synthesizing insights from multiple videos by the same YouTube creator into a channel-level knowledge base.

CHANNEL: {channel_name}

CHANNEL CONTEXT:
{channel_context}

ALL VIDEO INSIGHTS:
{all_insights}

Create a synthesis document with these sections:

## Recurring Themes
What topics does this creator keep coming back to? What are they tracking?

## Narrative Arc
How has the creator's perspective shifted over these videos? What were they saying 3 months ago vs now?

## Key Developments Timeline
Chronological list of the most important announcements, launches, and shifts covered.

## Consensus & Contrarian Views
Where does this creator align with mainstream opinion? Where do they diverge?

## Strongest Signals
The 5-10 most important takeaways from this channel's recent content. Rank by importance for someone advising enterprise AI customers.

## Watch List
What is this creator tracking that hasn't fully played out yet? What should we keep an eye on?

Be concrete and specific. Reference individual videos when making claims."""


def topic_synthesis_prompt(topic: str, channel_syntheses: dict[str, str]) -> str:
    """Cross-channel synthesis for a topic."""
    channels_text = ""
    for name, synthesis in channel_syntheses.items():
        channels_text += f"\n\n### {name}\n{synthesis}"

    return f"""You are synthesizing intelligence across multiple YouTube channels covering the same topic.

TOPIC: {topic}

CHANNEL SYNTHESES:
{channels_text}

Create a cross-channel synthesis:

## Where They Agree
Points of consensus across creators. Repetition alone is not proof of independence: distinguish between claims that are merely widely repeated and claims that appear independently corroborated by separate evidence, testing, or sourcing.

## Where They Disagree
Contradictions or different takes. Explain what each creator thinks and why they might differ.

## Combined Timeline
Merged chronological view of key developments from all channels.

## Strongest Cross-Channel Signals
The most important insights that emerge when you combine all these perspectives. What patterns are only visible across channels? Call out whether each strong signal looks independently corroborated, widely repeated from a likely shared origin, or still unresolved.

## Gaps
What topics aren't being covered? What questions aren't being answered?

Be specific about which creator said what. Attribution matters for credibility. If several creators seem to rely on the same originating claim, say that explicitly instead of treating the repetition as fresh confirmation."""


def site_page_insight_prompt(
    title: str,
    url: str,
    site_name: str,
    page_type: str,
    content: str,
) -> str:
    """Single-page website insight extraction prompt."""
    return f"""You are analyzing a scraped website page for strategic intelligence extraction.

TITLE: "{title}"
URL: {url}
SITE: {site_name}
PAGE TYPE: {page_type}

Extract a structured markdown insight document with these sections:

## Summary
2-4 sentences on what this page is about and why it matters.

## Key Signals
Bullet list of the most important concrete claims, announcements, or capabilities described on this page.

## Technical Details
Architecture, product details, workflows, implementation details, integrations, benchmarks, or operating model specifics.

## Business Relevance
Why this page matters for strategy, platform selection, operations, security, or customer conversations.

## Open Questions
What important details are implied but not actually confirmed by the page?

## Useful Follow-ups
Specific related pages, terms, or vendors worth researching next based on this page.

Rules:
- Use only the page content provided.
- Distinguish fact from interpretation.
- Be concrete and specific.
- Do not invent details not supported by the page.

PAGE CONTENT:
{content}"""


def site_synthesis_prompt(site_name: str, page_summaries: str) -> str:
    """Synthesize insights across multiple pages from a single site."""
    return f"""You are synthesizing intelligence across multiple pages from the same website.

SITE: {site_name}

PAGE INSIGHTS:
{page_summaries}

Create a synthesis document with these sections:

## What This Site Is Emphasizing
## Strongest Signals
## Product and Capability Map
## Repeated Themes and Positioning
## Gaps and Missing Details
## What To Watch Next

Be specific and cite the kinds of pages driving each conclusion."""


def site_topic_synthesis_prompt(topic: str, site_summaries: dict[str, str]) -> str:
    """Synthesize across site-level website summaries for one topic."""
    sites_text = ""
    for name, synthesis in site_summaries.items():
        sites_text += f"\n\n### {name}\n{synthesis}"

    return f"""You are synthesizing intelligence across website sources for a topic.

TOPIC: {topic}

SITE SYNTHESIS DOCUMENTS:
{sites_text}

Create a cross-site synthesis with these sections:

## Where The Sources Reinforce Each Other
## Where The Messaging or Evidence Differs
## Strongest Topic-Level Signals
## Capability and Vendor Landscape
## Gaps and Follow-Up Questions

Be concrete and keep attribution clear."""


def paper_insight_prompt(title: str, paper_id: str, content: str) -> str:
    """Analyze a technical paper using metadata and abstract content."""
    return f"""You are analyzing a technical paper for a fast-moving research corpus.

TITLE: {title}
PAPER ID: {paper_id}

Create a paper insight document with these sections:

## Summary
What the paper is about, in plain language.

## Core Contribution
What this paper appears to add relative to common approaches.

## Methods and Evidence
What methods, experiments, benchmarks, or evaluation signals are actually described.

## Practical Implications
Why this paper matters for builders, platform teams, product strategy, or enterprise adoption.

## Limits and Open Questions
What is unclear, unproven, or not covered based on the paper content provided.

## Follow-Up Research
What adjacent papers, implementations, or validation work would be worth reviewing next.

Rules:
- Use only the paper content provided.
- Distinguish fact from interpretation.
- Do not claim experimental outcomes that are not actually in the content.
- Be concrete and specific.

PAPER CONTENT:
{content}"""


def paper_topic_synthesis_prompt(topic: str, paper_summaries: dict[str, str]) -> str:
    """Synthesize across paper insights for one topic."""
    papers_text = ""
    for name, synthesis in paper_summaries.items():
        papers_text += f"\n\n### {name}\n{synthesis}"

    return f"""You are synthesizing intelligence across research papers for a topic.

TOPIC: {topic}

PAPER INSIGHTS:
{papers_text}

Create a synthesis document with these sections:

## Strongest Research Signals
## Shared Themes Across Papers
## Methods and Evaluation Patterns
## Practical Implications for Builders
## Gaps, Disagreements, and Open Questions
## What To Read Next

Be specific and keep attribution clear."""


def corpus_synthesis_prompt(topic: str, source_sections: dict[str, str]) -> str:
    """Synthesize across all source types for a topic corpus."""
    body = ""
    for label, content in source_sections.items():
        body += f"\n\n## {label}\n{content}"

    return f"""You are synthesizing a mixed-source topic corpus.

TOPIC: {topic}

SOURCE MATERIAL:
{body}

Create a synthesis document with these sections:

## Cross-Source Consensus
## Where Sources Disagree or Emphasize Different Things
## Strongest Signals Across The Corpus
## Research, Vendor, and Creator Takeaways
## Gaps and Follow-Up Questions
## What Changed In The Overall Topic Story

Evidence handling rules:
- Be explicit about which source types are driving each conclusion.
- Do not treat the same claim repeated across creators, websites, or papers as independent confirmation unless the sources appear to rely on different underlying evidence.
- When evidence is echoed but origin is unclear, describe it as widely repeated rather than independently corroborated.
- When separate source types point to the same conclusion for different reasons, say why that looks like real corroboration."""
