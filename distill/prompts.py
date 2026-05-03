"""Prompt templates for Distill analysis pipeline."""


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


def deep_research_prompt(topic: str, corpus_summary: str, focus: str | None = None) -> str:
    """Prompt for Gemini Deep Research.

    When corpus_summary is empty, assumes File Search grounding is active
    and instructs the model to use the attached documents.
    """
    focus_text = ""
    if focus:
        focus_text = f"\n\nSPECIFIC RESEARCH FOCUS: {focus}"

    corpus_section = ""
    if corpus_summary:
        # Legacy inline mode (small corpora or test mode)
        corpus_section = f"""
CORPUS SUMMARY:
{corpus_summary}
"""
    else:
        corpus_section = """
Your attached documents contain per-video insights, channel syntheses, and channel context profiles from YouTube creators covering this topic. Use the File Search tool to find relevant content across all documents. Cross-reference creator claims against public web sources.
"""

    return f"""You are a strategic intelligence analyst. You have been given a corpus of insights extracted from YouTube channels covering {topic}. Your job is to produce a comprehensive research report that validates, contextualizes, and extends these findings using current external sources.
{corpus_section}{focus_text}

YOUR RESEARCH MANDATE:

1. **VALIDATE CLAIMS** — For every major announcement or claim in the corpus, verify it against official sources, documentation, press releases, and industry reporting. Flag anything that's been walked back, delayed, or contradicted.

1a. **TRACE ORIGINS** — Distinguish between claims that are independently corroborated versus claims that are simply repeated across the corpus. If several sources appear to rely on the same originating post, repo, screenshot, newsletter, or announcement, say that explicitly.

2. **FILL GAPS** — What important developments are missing from the corpus? What happened that these creators didn't cover? Search for recent news, product launches, and industry reports.

3. **COMPETITIVE ANALYSIS** — Map the current competitive landscape across Microsoft/Azure, Google Cloud, AWS, and NVIDIA. Where does each vendor have real advantages vs marketing claims?

4. **PRICING & ECONOMICS** — What's the current state of AI pricing, compute costs, and ROI realities? Are the economic claims in the corpus accurate?

5. **CUSTOMER REALITY** — What are enterprises actually doing with AI right now? What's in production vs proof-of-concept? Where are the real success stories and failures?

6. **PREDICTIONS & TIMELINE** — Based on current trajectories, what's likely to happen in the next 3-6 months? What should enterprises be preparing for?

7. **ACTIONABLE RECOMMENDATIONS** — For a pre-sales architect advising enterprise customers: What should they be recommending right now? What should they be cautioning against?

OUTPUT FORMAT:

# Strategic Intelligence Report: {topic}
*Generated from YouTube channel analysis + deep research validation*

## Executive Summary
3-5 bullet points of the most important findings.

## Validated Findings
Claims from the corpus confirmed by external sources. Note whether they were independently corroborated or just widely repeated before validation.

## Corrections & Nuances
Claims that need qualification, correction, origin tracing, or context.

## Competitive Landscape
Current state of play across major vendors.

## What's Actually Happening in Enterprise AI
Real adoption patterns, not vendor marketing.

## 90-Day Outlook
What's coming and what to prepare for.

## Recommendations for Customer Conversations
Specific, actionable guidance for pre-sales architects.

## Sources
Key sources referenced in this analysis.

Be thorough, specific, and honest. If something is uncertain, say so. If vendors are overpromising, call it out. The reader needs ground truth, not hype."""


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

TRANSCRIPT:
{transcript}"""


def search_query_expansion_prompt(query: str, *, skeptical: bool = False) -> str:
    """Prompt for generating a small set of YouTube search intents for a topic."""
    skepticism_guidance = ""
    if skeptical:
        skepticism_guidance = """
This topic may be rumor-heavy, prank-prone, or noisy. Include search intents that help distinguish raw claims from evidence, validation, rebuttals, and post-mortems. Prefer concrete artifact terms when relevant.
"""

    return f"""You are designing YouTube search intents for a rapid intelligence workflow.

QUERY: {query}
{skepticism_guidance}
Generate 4-6 short YouTube search queries that maximize recall without drifting off-topic.

Rules:
- Keep each query under 12 words.
- Preserve the original topic.
- Mix direct phrasing, concrete evidence terms, and validation / rebuttal framing when useful.
- Avoid quotes, operators, or site-specific syntax.
- Favor queries likely to surface independent creators covering the same event from different angles.

Return ONLY valid JSON in this shape:
{{
  "queries": ["...", "..."]
}}
"""


def search_rerank_prompt(query: str, videos: list, *, skeptical: bool = False) -> str:
    """Prompt for selecting the best learning set from recent YouTube candidates."""
    items = []
    for video in videos:
        description = (getattr(video, "description", "") or "").replace("\n", " ").strip()
        if len(description) > 280:
            description = description[:277] + "..."
        items.append(
            f"""
VIDEO_ID: {video.video_id}
TITLE: {video.title}
CHANNEL: {video.channel_name}
DATE: {video.upload_date}
DURATION_SECONDS: {video.duration}
VIEWS: {getattr(video, "view_count", 0) or 0}
LIKES: {getattr(video, "like_count", 0) or 0}
COMMENTS: {getattr(video, "comment_count", 0) or 0}
DESCRIPTION: {description or "[none]"}
""".strip()
        )
    candidates = "\n\n---\n\n".join(items)
    skeptical_block = ""
    if skeptical:
        skeptical_block = """
SKEPTICAL MODE:
- This topic may contain rumor amplification, satire, April Fools content, or copycat reactions.
- Down-rank prank framing, hype-only titles, and single-source assertions without concrete evidence terms.
- Up-rank videos that mention artifacts, source material, demos, logs, repos, timelines, rebuttals, or explicit validation.
- Prefer a mix of primary explainers and independent cross-checks over many near-duplicate reactions.
"""

    return f"""You are selecting the best YouTube videos for rapid topic learning.

QUERY: {query}
{skeptical_block}
You are given recent YouTube candidates. Pick the videos that are MOST worth watching for someone trying to get smart quickly on this topic.

Optimize for:
- relevance to the query
- practical depth and specificity
- likely enterprise usefulness
- freshness
- credibility / signal quality

Do NOT optimize just for views. Avoid fluff, generic news roundups, clickbait, and near-duplicates.
Prefer videos that sound like real implementation guidance, architectural analysis, or substantive best-practice coverage.

Score every selected video from 0.0 to 1.0 on:
- relevance_score
- depth_score
- practicality_score
- freshness_score
- credibility_score
- final_score

Return ONLY valid JSON in this shape:
{{
  "ranked_videos": [
    {{
      "video_id": "...",
      "relevance_score": 0.0,
      "depth_score": 0.0,
      "practicality_score": 0.0,
      "freshness_score": 0.0,
      "credibility_score": 0.0,
      "final_score": 0.0,
      "rationale": "short reason"
    }}
  ]
}}

Rank all strong candidates in best-first order. Keep rationales brief and concrete.

CANDIDATES:
{candidates}
"""


def topic_brief_prompt(topic: str, topic_synthesis: str, recent_insights: str) -> str:
    """Prompt for a lightweight topic brief built from the learned YouTube corpus."""
    return f"""You are writing a concise topic brief for someone who needs the latest signal from YouTube creators fast.

TOPIC: {topic}

TOPIC SYNTHESIS:
{topic_synthesis}

RECENT VIDEO INSIGHTS:
{recent_insights}

Write a sharp markdown brief with these sections:

# Topic Brief: {topic}

## What Matters Now
3-5 bullets on the most important current developments or patterns.

## Strongest Signals
The clearest recurring signals across the recent videos.

## What Practitioners Are Actually Doing
Specific implementation or operational patterns that seem useful in practice.

## Disagreements or Uncertainty
Where creators diverge, or where the picture is still unclear.

## What To Watch Next
3-5 forward-looking watch items for the next 30-90 days.

Rules:
- Be concise and high-signal.
- Ground everything in the provided synthesis/insights.
- Prefer specifics over generic summaries.
- Do not invent facts not present in the source material.
"""


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


def paper_query_expansion_prompt(query: str) -> str:
    """Prompt for generating alternative arXiv search phrasings for a topic."""
    return f"""You are designing arXiv search queries for a research intelligence workflow.

QUERY: {query}

Generate 4-6 alternative arXiv search phrasings that maximize recall of relevant papers without drifting off-topic. arXiv matches on title, abstract, and author fields.

Rules:
- Keep each query under 10 words.
- Preserve the core research topic.
- Use domain-specific vocabulary that appears in paper titles and abstracts (e.g., "transformer", "diffusion", "generative", "self-supervised", "representation learning").
- Prefer noun phrases over question forms.
- Avoid overly generic terms that would collide with unrelated subfields (e.g., "harmonization" alone matches image processing papers).
- Favor phrasings that distinguish the subfield you want from adjacent noise.

Return ONLY valid JSON in this shape:
{{
  "queries": ["...", "..."]
}}
"""


def discover_query_generation_prompt(
    goal: str, *, paper_count: int = 5, video_count: int = 5
) -> str:
    """Prompt for turning a research goal into candidate search queries for papers + videos."""
    return f"""You are planning a research corpus for a user-stated goal.

GOAL: {goal}

Generate two sets of search queries the user should run to build a corpus that serves this goal:

1. ARXIV QUERIES ({paper_count} queries) — optimized for arXiv title/abstract matching. Use domain-specific noun phrases ("transformer", "diffusion", "contrastive"), avoid generic terms that collide with unrelated subfields ("harmonization" alone hits image processing).

2. YOUTUBE QUERIES ({video_count} queries) — optimized for relevance-ordered YouTube search. Favor phrases creators actually use in titles. Mix deep-dive ("masterclass", "explained in depth") with practitioner angles ("tutorial", "how to").

Rules:
- Preserve the goal; do not drift.
- Keep each query under 10 words.
- Queries should complement each other — cover different angles of the goal, not the same angle phrased differently.

Return ONLY valid JSON in this shape:
{{
  "paper_queries": ["...", "..."],
  "video_queries": ["...", "..."]
}}
"""


def discover_rerank_prompt(goal: str, candidates: list) -> str:
    """Prompt for goal-aware cross-source rerank of mixed papers and videos.

    candidates is a list of dicts with keys: kind ("paper"|"video"|"site"),
    identifier, title, subtitle (authors, channel, or site), date, description
    (abstract, description, or seed hint).
    """
    items = []
    for c in candidates:
        desc = (c.get("description") or "").replace("\n", " ").strip()
        if len(desc) > 500:
            desc = desc[:497] + "..."
        items.append(
            f"""
KIND: {c.get("kind", "?")}
IDENTIFIER: {c.get("identifier", "")}
TITLE: {c.get("title", "")}
SUBTITLE: {c.get("subtitle", "")}
DATE: {c.get("date", "")}
CONTENT: {desc or "[none]"}
""".strip()
        )
    blob = "\n\n---\n\n".join(items)

    return f"""You are curating a research corpus against a user-stated goal.

GOAL: {goal}

You are given a mixed pool of arXiv papers, YouTube videos, and optionally curated website pages. Pick and rank the items that together best serve the GOAL as a corpus. Optimize for:

- goal_fit: how directly this item advances understanding of the goal
- depth: substantive content (experiments, frameworks, concrete methods) over surveys of surveys or hot takes
- complementarity: does this add an angle the other top picks do not — prefer a diverse shortlist over five items that say the same thing

Penalize clickbait framings, unrelated subfields that happen to share a keyword, and items whose content is too shallow for the goal.
For website pages, reward official documentation, architecture explainers, implementation guidance, and concrete reference material when they directly support the goal.

Score every item 0.0-1.0 on goal_fit, depth_score, complementarity_score, and final_score.

Return ONLY valid JSON in this shape:
{{
  "ranked_items": [
    {{
      "identifier": "...",
      "kind": "paper" | "video" | "site",
      "goal_fit": 0.0,
      "depth_score": 0.0,
      "complementarity_score": 0.0,
      "final_score": 0.0,
      "rationale": "short reason tied to the goal"
    }}
  ]
}}

Rank in best-first order by final_score. Keep rationales tied to the goal, not generic.

CANDIDATES:
{blob}
"""


def paper_rerank_prompt(query: str, papers: list) -> str:
    """Prompt for ranking arXiv candidates against a research goal."""
    items = []
    for paper in papers:
        abstract = (getattr(paper, "abstract", "") or "").replace("\n", " ").strip()
        if len(abstract) > 600:
            abstract = abstract[:597] + "..."
        authors = ", ".join(getattr(paper, "authors", []) or [])[:200] or "[unknown]"
        categories = ", ".join(getattr(paper, "categories", []) or []) or "[none]"
        items.append(
            f"""
PAPER_ID: {paper.paper_id}
TITLE: {paper.title}
AUTHORS: {authors}
CATEGORIES: {categories}
PUBLISHED: {getattr(paper, "published_at", "") or "[unknown]"}
ABSTRACT: {abstract or "[none]"}
""".strip()
        )
    candidates = "\n\n---\n\n".join(items)

    return f"""You are selecting the best arXiv papers for a research corpus.

QUERY: {query}

You are given arXiv candidates. Pick the papers MOST worth a deep read for someone building research intelligence on this topic.

Optimize for:
- relevance to the query (topical fit of title and abstract)
- depth and substance (concrete methods, experiments, ablations -- not just surveys of surveys)
- novelty (new approach, dataset, or result rather than minor variation)
- credibility (substantive abstract, multiple authors or plausible affiliation signals, appropriate arXiv categories)

Down-rank papers that only share a keyword but live in an unrelated subfield (e.g., "image harmonization" when the query is about music harmony). Down-rank papers whose abstracts are vague or promotional.

Score every paper from 0.0 to 1.0 on:
- relevance_score
- depth_score
- novelty_score
- credibility_score
- final_score

Return ONLY valid JSON in this shape:
{{
  "ranked_papers": [
    {{
      "paper_id": "...",
      "relevance_score": 0.0,
      "depth_score": 0.0,
      "novelty_score": 0.0,
      "credibility_score": 0.0,
      "final_score": 0.0,
      "rationale": "short reason"
    }}
  ]
}}

Rank all strong candidates in best-first order. Keep rationales brief and concrete.

CANDIDATES:
{candidates}
"""
