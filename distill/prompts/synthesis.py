"""Synthesis prompt templates -- channel, topic, site, paper, corpus synthesis."""

from distill.prompts.shared import REGISTER_RULES, UNTRUSTED_CONTENT_RULES

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

Be specific about which creator said what. Attribution matters for credibility. If several creators seem to rely on the same originating claim, say that explicitly instead of treating the repetition as fresh confirmation.

STYLE: {REGISTER_RULES}"""


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

SECURITY: {UNTRUSTED_CONTENT_RULES}

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

SECURITY: {UNTRUSTED_CONTENT_RULES}

PAPER CONTENT:
{content}"""


def paper_topic_synthesis_prompt(topic: str, paper_summaries: dict[str, str]) -> str:
    """Synthesize across paper insights for one topic.

    The output must be cross-paper analysis -- claims that are only true across
    multiple papers read together. Topic-clustered capsule summaries are an
    anti-pattern (the per-paper Insights files already do that job).
    """
    papers_text = ""
    for name, synthesis in paper_summaries.items():
        papers_text += f"\n\n### {name}\n{synthesis}"

    paper_count = len(paper_summaries)

    return f"""You are doing graduate-level synthesis across {paper_count} research papers on the topic "{topic}".

The goal is analysis that makes the reader smarter than reading any single paper would. The per-paper Insights files already capture single-paper content -- do not repeat that work. Your job is what only becomes visible across multiple papers.

PAPER INSIGHTS:
{papers_text}

================================================================
OUTPUT STRUCTURE -- every section has concrete requirements.
Do NOT produce paragraph summaries under topic headings.
================================================================

## Cross-Paper Claims

Claims that depend on 2+ papers read together. Each claim MUST:
- State what is specifically true and on what evidence
- Cite the 2+ papers it depends on by short tag + arXiv ID
- Explain why no single paper in the set establishes it alone

ANTI-PATTERN (do NOT produce): "Papers X, Y, Z all use Bayesian networks." That is enumeration, not synthesis.

VALID EXAMPLE: "Three papers (X 2002.0001, Y 2104.0002, Z 2207.0003) all report 90%+ accuracy on synthetic benchmarks with <=20 nodes, but none validates against real-world data. The 'consensus' on method M is therefore structurally fragile -- it survives only inside the shared evaluation regime."

Aim for 5-10 such claims. If you cannot find any, say so honestly in one sentence and move on. Do not fabricate.

## Concrete Disagreements

Where papers actually contradict each other on the same question. Each entry MUST name:
- The 2+ papers in conflict (with arXiv IDs)
- The specific point of disagreement (a metric, an assumption, a definition, a method choice)
- WHY they reach different conclusions (different datasets, different baseline definitions, different goals)
- Which side has stronger evidence as presented in the corpus, or "unresolved" if neither does

ANTI-PATTERN: "Paper X emphasizes accuracy; Paper Y emphasizes interpretability." That is different emphasis, not disagreement.

VALID: "Paper X claims method M beats M' by 4 points on benchmark B. Paper Y, on the same benchmark, claims M' beats M by 6 points. The difference traces to X using a 70/30 split where Y uses 50/50; neither reports cross-validation. Unresolved."

If there are no real disagreements, write one sentence saying so. Do not invent conflict.

## Comparison Matrix

A markdown table with one row per paper. Required columns:

| Paper (arXiv ID) | Core contribution | Method | Evaluation (data + metric) | Limitation noted by authors |

Fill every row. Use each paper's own framing. This is the structural backbone of the synthesis -- it is not optional and not skippable.

## Methodological Patterns and Shared Blind Spots

What does the corpus collectively assume, evaluate on, or skip? Identify 3-5 patterns. Each pattern MUST:
- Name the specific assumption, evaluation choice, or omission
- List the papers that share it (by arXiv ID, not "most papers")
- Say why it matters -- what does this shared blind spot mean for the strength of the corpus consensus?

VALID: "Twelve of fifteen papers evaluate only on synthetic networks with <=20 nodes (2002.0001, 2104.0002, ...). No paper tests at production scale. Any cross-paper claim about scalability inherits this blind spot."

## What This Corpus Says That No Single Paper Says

The actual synthesis pay-off. After reading all {paper_count} papers, what do you know that you would not know from reading any one of them? This is THE central section -- if it is empty or generic, the synthesis has failed.

If the corpus genuinely lacks a synthesis claim (e.g., the papers are too disjoint), write one honest sentence saying so. Do not pad with restated single-paper conclusions.

## Open Questions That Would Be Worth Settling

Specific testable questions raised by the cross-paper analysis. Each entry MUST:
- State the question concretely (not "future work should explore X")
- Specify what evidence would resolve it
- Note which paper(s), if any, are closest to answering it

VALID: "Whether method M generalizes beyond synthetic BNs is the open question raised by the corpus. A head-to-head benchmark of methods from 2002.0001 and 2104.0002 on a real-incident dataset like D would settle it. Paper 2207.0003 builds the closest evaluation harness but stops short of running it."

================================================================
HARD RULES
================================================================

- Every claim cites specific papers by arXiv ID. No bare assertions.
- "Be specific" means name the dataset, the metric, the number, the paper. Do not abstract.
- No section may be filled with paragraph summaries under a topic heading. Every section has structured output (claims with cites, table rows, disagreements with both sides, etc.).
- If a section has nothing honest to say at this corpus size, write one sentence saying so. Padding is worse than brevity.
- Reading another single paper should not produce the same output. If your output could plausibly come from reading any one of the papers in the corpus, the synthesis has failed.
- Do not invent papers, IDs, datasets, or numbers. If a paper Insights file does not contain the detail you need, omit the claim rather than fabricate it."""


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
- When separate source types point to the same conclusion for different reasons, say why that looks like real corroboration.

STYLE: {REGISTER_RULES}"""
