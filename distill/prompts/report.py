"""Report prompt templates -- deep research, accordion, topic brief."""

__all__ = [
    "POSITION_GUIDANCE",
    "REPORT_SECTIONS",
    "SINGLE_CHANNEL_REPLACEMENT",
    "VOICE_GUIDANCE",
    "deep_research_prompt",
    "dossier_prompt",
    "fix_prompt",
    "get_active_sections",
    "qa_prompt",
    "section_prompt",
    "topic_brief_prompt",
]


# ─── Report Section Definitions ──────────────────────────────────────

# Sections tagged "multi_channel_only" are skipped when scope is a single channel.
# Sections tagged "voice" control tone: "reference", "analytical", "actionable".

REPORT_SECTIONS = [
    {
        "id": "executive_briefing",
        "title": "Executive Briefing",
        "position": "opening",
        "voice": "actionable",
        "multi_channel_only": False,
        "instructions": (
            "Lead with the 3-5 most consequential findings from this research period. "
            "Write for a time-pressed executive who needs the 'so what' immediately. "
            "Each finding should be 2-3 sentences: what happened, why it matters, what to do. "
            "Use bullet points or numbered findings, not dense paragraphs. "
            "Do NOT summarize the report structure -- deliver intelligence."
        ),
        "dossier_focus": None,
    },
    {
        "id": "validated_landscape",
        "title": "The Validated Technology Landscape",
        "position": "middle",
        "voice": "reference",
        "multi_channel_only": False,
        "instructions": (
            "Map every major product launch, GA release, preview announcement, and capability update "
            "from the research period. This is a REFERENCE section, not a sales pitch. "
            "Use a consistent format for each entry: Product/Feature, Vendor, Date, Status, Pricing. "
            "Use markdown tables for vendor comparisons where helpful. "
            "Group by vendor: Microsoft/Azure, Google Cloud, AWS, NVIDIA, OpenAI, Anthropic, others. "
            "Be exhaustive and factual. Let the data speak -- no 'pitch this tomorrow' language here."
        ),
        "dossier_focus": ["validated_announcements", "market_data"],
    },
    {
        "id": "vendor_battleground",
        "title": "Vendor Competitive Battleground",
        "position": "middle",
        "voice": "analytical",
        "multi_channel_only": False,
        "instructions": (
            "Analyze the competitive dynamics across Microsoft/Azure, Google Cloud, AWS, and NVIDIA. "
            "For each vendor: current strategic posture, recent wins/losses, where they're investing, "
            "what they're de-emphasizing. Identify the 2-3 most significant competitive shifts. "
            "Include specific evidence: partnership announcements, pricing moves, customer wins. "
            "Call out vendor marketing claims that don't match reality. "
            "Use a summary table at the end comparing vendor strengths/weaknesses."
        ),
        "dossier_focus": ["competitive_positioning", "market_data"],
    },
    {
        "id": "enterprise_reality",
        "title": "Enterprise Adoption Reality Check",
        "position": "middle",
        "voice": "analytical",
        "multi_channel_only": False,
        "instructions": (
            "What are enterprises ACTUALLY doing with AI right now? Separate production deployments "
            "from POCs from vaporware. Cover: which use cases are generating real ROI, what's failing, "
            "where the gap is between vendor promises and customer reality. "
            "Include specific adoption data, case studies, and earnings call mentions. "
            "Address pricing/economics: what does it actually cost to run AI workloads? "
            "What's the real TCO story?"
        ),
        "dossier_focus": ["enterprise_adoption", "pricing_economics"],
    },
    {
        "id": "corrections_nuances",
        "title": "Corrections, Nuances, and Hype Check",
        "position": "middle",
        "voice": "analytical",
        "multi_channel_only": False,
        "instructions": (
            "This is the truth-telling section. Use a structured format for each correction: "
            "**Claim**: What the creator said. **Reality**: What the evidence shows. **Source**: Where verified. "
            "Also flag claims that are technically true but misleading. "
            "Be specific about which creator said what and what the actual situation is. "
            "This section builds credibility for the entire report. "
            "Keep tone neutral and factual -- present corrections as clarifications, not attacks."
        ),
        "dossier_focus": ["corrections_contradictions"],
    },
    {
        "id": "creator_consensus",
        "title": "Creator Consensus and Contrarian Views",
        "position": "middle",
        "voice": "analytical",
        "multi_channel_only": False,
        "instructions": (
            "Analyze where the YouTube creators agree and disagree. Points of consensus across "
            "independent creators are stronger signals. Points of disagreement reveal uncertainty. "
            "For each major theme: who agrees, who disagrees, and what evidence supports each position. "
            "Identify the creators who have been most accurate historically vs those who tend toward hype. "
            "Use the channel synthesis data heavily here."
        ),
        "dossier_focus": ["gaps_coverage"],
    },
    {
        "id": "gaps_blindspots",
        "title": "Coverage Gaps and Blind Spots",
        "position": "middle",
        "voice": "reference",
        "multi_channel_only": False,
        "instructions": (
            "What important developments happened that the creators did NOT cover? What topics are "
            "systematically under-covered? Consider: regulatory changes, enterprise-specific developments, "
            "infrastructure/ops issues, security concerns, international developments. "
            "For each gap: what happened, why it matters, and where to find more information. "
            "Use bullet points or a table. This is a reference section -- factual, not salesy."
        ),
        "dossier_focus": ["gaps_coverage", "forward_signals"],
    },
    {
        "id": "predictions_timeline",
        "title": "Predictions and 90-Day Outlook",
        "position": "middle",
        "voice": "analytical",
        "multi_channel_only": False,
        "instructions": (
            "Based on everything gathered: what's coming in the next 90 days? "
            "Use a structured format: one subsection per prediction with "
            "Confidence (High/Medium/Low), Evidence, What to Watch. "
            "Also evaluate the creators' predictions: which are likely right, which are wishful thinking? "
            "End with a summary table of predictions ranked by confidence."
        ),
        "dossier_focus": ["forward_signals"],
    },
    {
        "id": "customer_playbook",
        "title": "Customer Conversation Playbook",
        "position": "closing",
        "voice": "actionable",
        "multi_channel_only": False,
        "instructions": (
            "For a pre-sales architect who takes customer calls daily: what should they be saying? "
            "Structure as 3-5 specific scenarios with clear headers. For each: "
            "the customer question, the key response points (bulleted), and one closing line. "
            "Keep each scenario tight -- 150-200 words max. "
            "Reference specific data from earlier sections by name, don't re-state the full stat. "
            "This is the most directly actionable section -- make it concrete and scannable."
        ),
        "dossier_focus": None,
    },
    {
        "id": "strategic_synthesis",
        "title": "Strategic Synthesis",
        "position": "closing",
        "voice": "actionable",
        "multi_channel_only": False,
        "instructions": (
            "Tie everything together. What are the 3-5 meta-themes that emerge from this entire analysis? "
            "What should a pre-sales architect internalize from this research period? "
            "Connect the dots across vendors, enterprise adoption, creator insights, and market data. "
            "End with the single most important takeaway -- the one thing that changes how you approach "
            "customer conversations for the next 90 days. Be bold but evidence-based."
        ),
        "dossier_focus": None,
    },
]


SINGLE_CHANNEL_REPLACEMENT = {
    "id": "creator_accuracy",
    "title": "Creator Signal vs. Noise",
    "position": "middle",
    "voice": "analytical",
    "instructions": (
        "Evaluate this creator's track record across their coverage. "
        "Where were they right? Where were they wrong? Where were they early on a real trend? "
        "Identify their systematic biases (e.g., hype-prone, vendor-friendly, doom-oriented). "
        "Rate their reliability by topic area: which subjects should readers trust them on, "
        "and which should they cross-reference? "
        "This replaces the multi-creator consensus section for single-channel reports."
    ),
    "dossier_focus": ["corrections_contradictions", "gaps_coverage"],
}


def get_active_sections(scope: str = "topic", channel_count: int = 1) -> list[dict]:
    """Return the section list adapted to the report scope."""
    is_single = scope == "channel" or channel_count <= 1
    active = []
    for section in REPORT_SECTIONS:
        if section["id"] == "creator_consensus" and is_single:
            active.append(dict(SINGLE_CHANNEL_REPLACEMENT))
            continue
        active.append(dict(section))
    return active


# ─── Position + Voice Guidance ──────────────────────────────────────

POSITION_GUIDANCE = {
    "opening": (
        "This is the OPENING section. Set the strategic frame immediately. "
        "Lead with impact -- the reader should know within 2 sentences why this report matters. "
        "Do not waste words on methodology or structure descriptions."
    ),
    "middle": (
        "This is section {section_number} of {total_sections}. "
        "Build on previous sections -- reference earlier findings where relevant, don't repeat them. "
        "Every paragraph should either inform a decision or change a perspective."
    ),
    "closing": (
        "This is a CLOSING section. Synthesize and drive toward action. "
        "Reference insights from earlier sections to demonstrate how themes connect. "
        "The reader should finish this section knowing exactly what to do differently."
    ),
}

VOICE_GUIDANCE = {
    "reference": (
        "VOICE: This is a REFERENCE section. Write like a research analyst, not a salesperson. "
        "Be factual, structured, and comprehensive. Use tables and bullet points. "
        "No calls to action, no 'pitch this tomorrow,' no urgency language. "
        "Let the data speak for itself."
    ),
    "analytical": (
        "VOICE: This is an ANALYTICAL section. Write like a thoughtful strategist. "
        "Provide insight and interpretation, but ground every claim in evidence. "
        "You can note implications for enterprise buyers, but don't hard-sell. "
        "Balance between informing and advising."
    ),
    "actionable": (
        "VOICE: This is an ACTIONABLE section. Write for someone who will use this "
        "in customer meetings tomorrow. Be direct, specific, and concrete. "
        "Include specific recommendations, but make them earned by the evidence, "
        "not hype-driven."
    ),
}


# ─── Dossier Prompt ──────────────────────────────────────────────────


def dossier_prompt(topic: str, corpus: str, focus: str | None = None) -> str:
    """Phase 1: Ask Deep Research to gather raw facts, NOT write a report."""
    focus_text = ""
    if focus:
        focus_text = f"\n\nSPECIFIC RESEARCH FOCUS: {focus}"

    corpus_section = ""
    if corpus:
        corpus_section = f"""
CORPUS OF YOUTUBE INTELLIGENCE:
{corpus}
"""

    return f"""You are a Lead Research Analyst compiling a RESEARCH DOSSIER on the topic of "{topic}" based on a corpus of YouTube channel intelligence.

I do NOT want a polished report. I want raw, structured research notes -- a fact-sheet that will be used as source material for a detailed analytical report written later.

Your attached documents contain per-video insights, channel syntheses, and channel context profiles from YouTube creators covering this topic. Use the File Search tool to find relevant content across all documents. Cross-reference creator claims against public web sources.
{corpus_section}{focus_text}

COMPILE THE FOLLOWING RESEARCH CATEGORIES:

## 1. VALIDATED ANNOUNCEMENTS
For every major product launch, feature release, pricing change, partnership, or acquisition mentioned in the corpus:
- Verify against official sources (press releases, documentation, blog posts)
- State: Product/Feature, Vendor, Date, Status (GA/Preview/Announced/Rumored), Source URL if found
- Flag anything walked back, delayed, or contradicted since the creator covered it
- Include specific version numbers, pricing, and availability details

## 2. MARKET DATA
Current market figures relevant to topics in the corpus:
- Market sizes, growth rates, investment figures, funding rounds
- Verify any numbers cited by creators against official filings/reporting
- Include earnings call data points, analyst estimates
- Note where creator-cited numbers are wrong or outdated

## 3. COMPETITIVE POSITIONING
For Microsoft/Azure, Google Cloud, AWS, NVIDIA, OpenAI, Anthropic:
- Official strategic statements and positioning
- Product roadmap items (confirmed vs announced)
- Recent customer wins, partnerships, competitive moves
- What each vendor is emphasizing vs de-emphasizing

## 4. ENTERPRISE ADOPTION SIGNALS
- Real deployment case studies (not vendor marketing)
- Earnings call mentions of AI adoption
- Analyst reports on enterprise AI patterns
- Specific industries/use cases showing real traction
- Failures, pullbacks, or disappointments

## 5. PRICING AND ECONOMICS
- Current API pricing across major providers
- Compute cost benchmarks and trends
- TCO analysis data points
- Consumption-based vs seat-based economics evidence
- Real customer spend data if available

## 6. CORRECTIONS AND CONTRADICTIONS
For every major claim from the YouTube creators that is:
- Factually wrong: State the claim, state the truth, cite the source
- Outdated: What changed since they said it
- Exaggerated: What the real numbers/situation is
- Missing context: What important nuance they left out

## 7. GAPS IN COVERAGE
Important developments from the time period that the creators did NOT cover:
- Regulatory/policy changes
- Enterprise-specific announcements
- Infrastructure/security developments
- International market moves
- Anything a pre-sales architect needs to know that wasn't in the corpus

## 8. FORWARD-LOOKING SIGNALS
- Confirmed upcoming releases and dates
- Earnings guidance relevant to AI
- Analyst forecasts and predictions
- Announced but unreleased products
- Regulatory proceedings that could impact the market
- Pattern-based predictions (what trends suggest is coming)

FORMAT RULES:
- Every fact MUST have a source citation or confidence level [Confirmed/Reported/Estimated/Speculated]
- For source citations, use descriptive references to PRIMARY sources: (per OpenAI blog, Oct 2025), (per Anthropic press release, Sep 2025), (per NVIDIA 10-K filing), (per Reuters, Feb 2026). Do NOT cite Wikipedia as a primary source; find the underlying source Wikipedia references. Do NOT use numbered citations like [cite: 1].
- Use specific numbers, dates, version numbers -- no rounding, no approximations
- Mark creator claims with the creator's name: "NateBJones claims..." not "Industry experts believe..."
- Creator estimates and projections must be labeled [Estimated] or [Speculated], not [Confirmed]. A creator saying "50 agents outproduce 500 humans" is their estimate, not a confirmed fact, even if it sounds precise.
- Do NOT write polished prose. Use bullet points, short notes, structured data.
- This is RAW RESEARCH MATERIAL. Comprehensiveness matters more than readability.
- Aim for maximum density of verifiable facts.
- Never use em-dashes or en-dashes. Use commas, semicolons, colons, or hyphens instead."""


# ─── Section Writing Prompt ──────────────────────────────────────────


def section_prompt(
    section: dict,
    topic: str,
    research_dossier: str,
    previous_sections: list[dict],
    section_index: int,
    total_sections: int,
    tagged_material: str | None = None,
) -> str:
    """Phase 2: Write a single report section with full context."""

    # Build position guidance
    position = section["position"]
    guidance = POSITION_GUIDANCE[position].format(
        section_number=section_index + 1,
        total_sections=total_sections,
    )

    # Build voice guidance
    voice = section.get("voice", "analytical")
    voice_text = VOICE_GUIDANCE.get(voice, VOICE_GUIDANCE["analytical"])

    # Build previous sections context using only the last 3 sections.
    prev_context = "This is the first section of the report."
    if previous_sections:
        prev_summaries = []
        recent_sections = previous_sections[-3:]
        for index, prev in enumerate(recent_sections):
            max_words = 500 if index == len(recent_sections) - 1 else 150
            words = prev["content"].split()[:max_words]
            excerpt = " ".join(words)
            if len(prev["content"].split()) > max_words:
                excerpt += "..."
            prev_summaries.append(f"**{prev['title']}** ({prev['word_count']} words):\n{excerpt}")
        prev_context = "\n\n---\n\n".join(prev_summaries)

    # Tagged material supplement
    tagged_text = ""
    if tagged_material:
        tagged_text = f"""

## SUPPLEMENTARY SOURCE MATERIAL
The following source material is particularly relevant to this section:
{tagged_material}
"""

    return f"""You are a senior pre-sales architect who advises enterprise customers on AI strategy across Microsoft, Google, AWS, and NVIDIA.

You are writing one section of a comprehensive Strategic Intelligence Report on "{topic}".

## POSITION IN REPORT
{guidance}

## VOICE
{voice_text}

## RESEARCH DOSSIER (verified facts from Deep Research)
{research_dossier}
{tagged_text}
## PREVIOUS SECTIONS (for continuity -- reference these, NEVER repeat their content)
{prev_context}

## YOUR TASK
Write the **{section["title"]}** section.

{section["instructions"]}

## WRITING STANDARDS

### Accuracy
- NEVER invent statistics, studies, analyst reports, or data points not found in the research dossier. If the dossier doesn't contain evidence for a claim, do NOT make it up. Omit it instead.
- Use descriptive source attributions to PRIMARY sources: (per OpenAI blog, Oct 2025) or (per NVIDIA 10-K filing). Do NOT cite Wikipedia as a source; cite what Wikipedia references. For creator claims, attribute directly: (per NateBJones). Do NOT use numbered citations like [cite: 1].
- Clearly distinguish between [Confirmed] facts, [Reported] claims, [Estimated] projections, and [Analysis] your own synthesis. Use these inline labels.
- Creator estimates and projections are NOT confirmed facts. "50 agents outproduce 500 coders" is [Estimated], even if stated confidently. Only use [Confirmed] for facts verified against official sources (press releases, filings, documentation).
- Use exact numbers from the dossier. Do not round $110B to "over $100B".
- **Bias check**: If the source creators share a systematic bias (e.g., uniformly bullish on agents, or focused on one vendor), note it. Present the creator's framing, but flag where counterevidence or skepticism exists.

### Readability
- Keep paragraphs SHORT: 3-4 sentences max, under 80 words each.
- Use bullet points, numbered lists, and markdown tables where they improve scannability.
- Use ### subheadings to break up the section into 2-4 logical parts.
- Leave whitespace. Dense walls of text are unreadable.

### No Repetition
- NEVER restate a fact that already appeared in a previous section. Instead, reference it: "the $11M figure noted in the Executive Briefing" or "as the Vendor Battleground detailed."
- If you find yourself writing a statistic for the second time, stop and cross-reference instead.

### Formatting
- Never use em-dashes or en-dashes. Use commas, semicolons, colons, or parentheses instead.
- Write 800-1500 words for this section. Go deep on fewer points rather than shallow on many.

Write the section now. Output ONLY the section content (no title heading -- that will be added during assembly).
Do NOT include word counts, section labels, or meta-commentary about the writing. Just the content."""


# ─── QA Prompt ──────────────────────────────────────────────────────


def qa_prompt(topic: str, research: str, report: str) -> str:
    """Phase 4: QA review of the assembled report against the research."""
    return f"""You are a senior editor reviewing a Strategic Intelligence Report on "{topic}".

You have two documents:
1. The RESEARCH, raw validated facts gathered by Deep Research (the ground truth)
2. The REPORT, the final report written from that research

Your job: find problems. Be specific and ruthless.

## RESEARCH (ground truth)
{research}

## REPORT (under review)
{report}

## REVIEW EACH SECTION FOR:

1. **Hallucinated claims** -- Any statistic, study, analyst report, or data point in the report that does NOT appear in the research. This is the most critical check. LLMs fabricate plausible-sounding data. If you can't find the source in the research, flag it.

2. **Numbered citations** -- The report should use descriptive sources like "(per OpenAI blog)" not "[cite: 1]" or "[cite: 2]". Flag any numbered citation formats.

3. **Repetition across sections** -- Statistics or facts that appear in multiple sections instead of being cross-referenced. List the specific repeated items and which sections contain them.

4. **Wall-of-text paragraphs** -- Any paragraph over ~80 words or ~4 sentences. These need breaking up.

5. **Missing confidence labels** -- Major claims that lack [Confirmed], [Reported], or [Analysis] tags.

6. **Contradictions** -- Sections that say different things about the same topic, or claims that contradict the research.

7. **Voice problems** -- Reference sections that sound like sales pitches, or analytical sections with "book the audit tomorrow!" urgency language.

8. **Wikipedia as source** -- Any claim cited as "(per Wikipedia ...)" should be flagged. Wikipedia is not a primary source; the report should cite the underlying source (press release, filing, blog post).

9. **Creator opinions presented as facts** -- Creator estimates, projections, or opinions labeled [Confirmed] instead of [Estimated] or [Reported]. Example: a creator saying "50 agents outproduce 500 coders" is an estimate, not a confirmed fact.

10. **Inherited bias without counterweight** -- Sections that adopt a creator's bullish/bearish framing without noting it as one perspective. The report should flag systematic biases (e.g., uniformly pro-agent, vendor-friendly) rather than amplifying them uncritically.

## OUTPUT FORMAT

For each section, output exactly:

### [Section Title]
**Score**: PASS | FLAG | FAIL
**Issues**:
- [issue type]: [specific description with quotes from the report]

PASS = solid, no meaningful issues
FLAG = minor issues but usable (missing a few labels, slightly thin)
FAIL = needs rewrite (hallucinated claims, heavy repetition, unreadable density, wrong voice)

After all sections, output:

### OVERALL
**Sections to rewrite**: [comma-separated list of section titles that scored FAIL, or "None"]
**Top 3 issues**: [the 3 most important problems across the whole report]

Be concise. No praise, no softening. Just the problems."""


def fix_prompt(
    section: dict,
    topic: str,
    research: str,
    qa_feedback: str,
    original_content: str,
) -> str:
    """Rewrite a section that failed QA, incorporating specific feedback."""
    voice = section.get("voice", "analytical")
    voice_text = VOICE_GUIDANCE.get(voice, VOICE_GUIDANCE["analytical"])

    return f"""You are a senior pre-sales architect rewriting one section of a Strategic Intelligence Report on "{topic}".

This section FAILED quality review. You must fix the specific issues identified below.

## VOICE FOR THIS SECTION
{voice_text}

## RESEARCH (ground truth; every claim must trace back to this)
{research}

## QA FEEDBACK FOR THIS SECTION
{qa_feedback}

## ORIGINAL SECTION CONTENT
{original_content}

## YOUR TASK
Rewrite the **{section["title"]}** section, fixing every issue identified in the QA feedback.

Rules:
- Fix the specific problems called out. Don't just rephrase; actually address each issue.
- NEVER invent statistics or data not in the research. If you can't find it, omit it.
- Use descriptive source attributions like (per OpenAI blog, Oct 2025), NEVER numbered citations like [cite: 1].
- Every substantive claim must have a confidence label: [Confirmed], [Reported], or [Analysis].
- Use specific numbers, names, dates, products from the research. No vague language.
- Keep paragraphs under 80 words. Use bullet points, tables, and ### subheadings.
- Never use em-dashes or en-dashes. Use commas, semicolons, colons, or parentheses instead.
- NEVER repeat facts already stated in other sections. Cross-reference instead.
- Target 800-1500 words.

Output ONLY the rewritten section content (no title heading, no word counts, no meta-commentary)."""


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
