"""Claim-extraction and claim-aware synthesis prompts for the 0.9 claim layer.

Two prompts:

- ``claim_extraction_prompt`` -- called once per insight file. The LLM returns
  a JSON array of structured claim rows (no prose) that the pipeline parses
  into ``Claim`` records and appends to ``claims.jsonl``. This mirrors the 0.8
  concept-extraction contract: structured-output classification, JSON only,
  per-insight provenance, granularity chosen per claim.

- ``claim_synthesis_prompt`` -- the second pass. Given the full claim set for
  a topic, the LLM clusters claims by what they assert, names contradictions
  between sources, and writes the narrative with explicit per-claim citations.
  Low-``role_confidence`` claims are surfaced rather than dropped.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from distill.prompts.shared import (
    ANTI_HALLUCINATION_RULES,
    DERIVED_CONTENT_RULES,
    FORMATTING_RULES,
    REGISTER_RULES,
)

if TYPE_CHECKING:
    from distill.claims.records import Claim

__all__ = [
    "CLAIM_EXTRACTION_PROMPT_ID",
    "CLAIM_SYNTHESIS_PROMPT_ID",
    "claim_extraction_prompt",
    "claim_synthesis_prompt",
    "claims_receipt",
]


CLAIM_EXTRACTION_PROMPT_ID = "claims.extract.v1"
CLAIM_SYNTHESIS_PROMPT_ID = "claims.synthesis.v3"


def claim_extraction_prompt(insight_content: str, topic: str) -> str:
    """Build the claim-extraction prompt for one ``_Insights.md`` file.

    Args:
        insight_content: full content of the source insight, frontmatter
            included for context. Extract claims from the body, not the
            frontmatter.
        topic: the corpus topic, to help the model judge what is a topical
            claim worth tracking versus generic background.
    """
    return f"""You are extracting atomic claims from a single research-insight document for a structured knowledge base.

TOPIC: {topic}

A CLAIM is one self-contained assertion the source makes: a finding, a method description, a stated limitation, a conclusion, or load-bearing background. Each claim must stand on its own when read in isolation.

YOUR TASK:
Extract every substantive claim the insight asserts. For each, classify its rhetorical role, optionally decompose it into a subject-predicate-object triple, capture any dataset or metric it concerns, and rate your confidence in the role assignment.

OUTPUT FORMAT:
A single JSON array of objects. No prose before or after. No markdown wrapping. The schema for each object is:

{{
  "claim_text": "the assertion in 1-2 sentences, self-contained and readable in isolation",
  "rhetorical_role": "background" | "method" | "result" | "limitation" | "conclusion",
  "subject": "the agent/entity the claim is about (optional, empty string if narrative)",
  "predicate": "the action/relation (optional)",
  "object": "what the predicate acts on (optional)",
  "dataset": "named dataset/benchmark the claim concerns, if any (optional)",
  "metric": "named evaluation metric the claim concerns, if any (optional)",
  "evidence_type": "empirical_result" | "methodology" | "citation" | "comparison" | "limitation" | "background",
  "role_confidence": 0.0 to 1.0
}}

ROLE GUIDANCE:
- "background": established prior knowledge the source builds on, not its own contribution.
- "method": a description of how something is done -- an approach, procedure, or design choice.
- "result": an empirical finding, measurement, or observed outcome.
- "limitation": a stated weakness, failure mode, scope boundary, or caveat.
- "conclusion": a takeaway, recommendation, or claim the source draws from its results.

GRANULARITY:
- Choose the natural granularity per claim: clause-level for dense technical text, sentence- or span-level for narrative text. Do NOT force one granularity across the whole document.
- Decompose into subject/predicate/object ONLY when the claim has a clean agent-action-object structure. Leave the triple empty and rely on claim_text for narrative claims.

CONFIDENCE:
- role_confidence is your honest certainty about the rhetorical_role. Use lower values (below 0.5) when a claim straddles roles (e.g. a result stated as a conclusion). Downstream synthesis surfaces low-confidence claims rather than dropping them, so an honest low score is more useful than false certainty.

QUALITY RULES:
- Extract claims the insight asserts substantively. Skip passing citations and pure restatement of others' work unless the source takes a position on it.
- Each claim_text must be self-contained: resolve pronouns and "this/that" references to their referents so the claim is readable without the surrounding text.
- {ANTI_HALLUCINATION_RULES}
- {FORMATTING_RULES}
- If the insight asserts no substantive claims (rare), return an empty array: [].

SECURITY: {DERIVED_CONTENT_RULES}

INSIGHT TO EXTRACT FROM:

{insight_content}

OUTPUT THE JSON ARRAY ONLY:"""


def claims_receipt(claims: Sequence[Claim]) -> str:
    """The claim set rendered exactly as the synthesis prompt embeds it.

    The verify hook grounds the two-pass synthesis against this text, so it
    must be the same evidence the model saw -- handles, roles, datasets,
    metrics, and source ids included.
    """
    return "\n".join(_format_claim_for_synthesis(c, i) for i, c in enumerate(claims, 1))


def _format_claim_for_synthesis(claim: Claim, index: int) -> str:
    """Render one claim as a compact, citable line for the synthesis prompt."""
    role = claim.rhetorical_role.value
    conf = f"{claim.role_confidence:.2f}"
    bits = [f"[C{index}] ({role}, conf {conf}) {claim.claim_text}"]
    meta: list[str] = []
    if claim.dataset:
        meta.append(f"dataset={claim.dataset}")
    if claim.metric:
        meta.append(f"metric={claim.metric}")
    meta.append(f"source={claim.source_id}")
    bits.append(f"    ({'; '.join(meta)})")
    return "\n".join(bits)


def claim_synthesis_prompt(topic: str, claims: Sequence[Claim], style: str = "") -> str:
    """Build the second-pass synthesis prompt over an extracted claim set.

    The claim set is rendered as a numbered, role-tagged list so the model can
    cluster by what is asserted, name contradictions between sources, and cite
    specific claims by their ``[C<n>]`` handle and source. Low-confidence
    claims carry their score so the model can surface rather than bury them.

    Args:
        topic: the corpus topic being synthesized.
        claims: the full extracted claim set for the topic (already read from
            ``claims.jsonl``). Ordering is the caller's responsibility; the
            prompt does not assume any particular order.
    """
    from distill.prompts.synthesis import _emphasis_block

    claim_block = claims_receipt(claims)
    source_count = len({c.source_id for c in claims})
    return f"""You are doing graduate-level synthesis for the topic "{topic}" over a structured set of {len(claims)} extracted claims drawn from {source_count} sources.

The goal is analysis that makes the reader smarter than reading any single source would. Each claim below is tagged with a handle [C<n>], its rhetorical role, a confidence score for that role, and its source. Synthesize ACROSS sources; do not summarize source by source.

SECURITY: {DERIVED_CONTENT_RULES}

CLAIM SET:

{claim_block}

================================================================
OUTPUT STRUCTURE: every section has concrete requirements.
Do NOT produce paragraph summaries under topic headings.
Cite the claim handle(s) every assertion rests on, e.g. "(C3, C7)".
================================================================

## Cross-Source Findings

What the corpus collectively establishes when claims are read together. Cluster related claims and lead each finding with the established point. Each finding MUST cite its handles and say whether it looks independently corroborated (separate sources, separate evidence), widely repeated from a likely shared origin, or single-source.

ANTI-PATTERN (do NOT produce): "C1, C5, and C9 all discuss context layers." That is enumeration, not synthesis.

VALID: "Three sources (C1, C8, C14) report the same failure mode under load but reach it from different stacks (SQL, graph, KV), so the pattern looks independently corroborated rather than echoed (C1, C8, C14)."

## Disagreements

Where claims actually conflict on the same question. Each entry MUST name the conflicting handles, the specific point of disagreement (a number, a method choice, a definition), WHY they differ (different data, goals, or assumptions), and which side is better supported as stated, or "unresolved".

ANTI-PATTERN: "C2 emphasizes speed; C6 emphasizes governance." That is different emphasis, not disagreement.

VALID: "C4 claims rules must stay in the system of record; C11 advocates a central context layer that re-encodes them. The conflict is real and traces to different scale assumptions (single-team vs cross-platform). Unresolved on the evidence here (C4, C11)."

Do not paper over contradictions; a named, unresolved contradiction is more useful than a smoothed-over consensus.

## Comparison Matrix

A markdown table with one row per distinct source. Required columns:

| Source | Position / approach | Evidence or basis (data, metric, demo) | Limitation or open edge |

Fill every row from that source's own claims. This is the structural backbone; it is not optional.

## What This Corpus Says That No Single Source Says

The synthesis payoff: second-order insights that follow only from combining clusters and are asserted by no single claim. After reading all {len(claims)} claims, what do you now know that no one source states? This is THE central section; if it is generic or just restates a cluster, the synthesis has failed. If the corpus is too disjoint to support such a claim, say so in one honest sentence.

## Thesis and White Space

The defensible position this corpus supports and the territory it leaves open. This is the top of the ladder; it must go beyond the section above.
- THESIS: one or two falsifiable claims the corpus as a whole supports (a position someone could disagree with and test, not a summary), each citing the handles it rests on.
- WHITE SPACE: what the corpus collectively does NOT address, assumes away, or never tests, stated as concrete unoccupied territory (a question no source asks, a regime no source evaluates, an approach no source tries). Name the absence and cite the handles that circle it.
- WHAT WOULD FALSIFY THE THESIS: the specific result or evidence that would overturn each thesis claim.

If the claim set is too thin or disjoint to support a defensible thesis, say so in one honest sentence rather than inventing one.

## Open Questions Worth Settling

Specific, testable questions raised by the cross-source analysis. Each entry MUST state the question concretely (not "more research is needed"), specify what evidence would resolve it, and note which source(s), if any, are closest to answering it.

VALID: "Whether graph or relational storage wins for agent memory at scale is open. A head-to-head latency/recall benchmark on one workload would settle it; C8 builds the closest harness but reports no numbers."

## Soft Spots

The corpus's weak foundations: low role_confidence claims, single-source results, and stated limitations. Surface them by handle as caveats on the findings above rather than dropping them or presenting them as settled.

================================================================
HARD RULES
================================================================

- Every assertion cites the handle(s) it rests on. No bare claims.
- "Be specific" means name the source, the number, the dataset, the metric. Do not abstract.
- No section may be filled with paragraph summaries under a heading. Every section has structured output (findings with cites, table rows, disagreements with both sides).
- If a section has nothing honest to say at this corpus size, write one sentence saying so. Padding is worse than brevity.
- If your output could plausibly come from reading any one source in the set, the synthesis has failed.
- {ANTI_HALLUCINATION_RULES} Do not invent handles, sources, datasets, or numbers not present in the claim set above.
- {REGISTER_RULES}{_emphasis_block(style)}
- {FORMATTING_RULES}

Write the synthesis in Markdown. Begin with the synthesis itself; no preamble."""
