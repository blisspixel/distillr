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

from distill.prompts.shared import ANTI_HALLUCINATION_RULES, FORMATTING_RULES, REGISTER_RULES

if TYPE_CHECKING:
    from distill.claims.records import Claim

__all__ = [
    "CLAIM_EXTRACTION_PROMPT_ID",
    "CLAIM_SYNTHESIS_PROMPT_ID",
    "claim_extraction_prompt",
    "claim_synthesis_prompt",
]


CLAIM_EXTRACTION_PROMPT_ID = "claims.extract.v1"
CLAIM_SYNTHESIS_PROMPT_ID = "claims.synthesis.v1"


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

INSIGHT TO EXTRACT FROM:

{insight_content}

OUTPUT THE JSON ARRAY ONLY:"""


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

    claim_block = "\n".join(_format_claim_for_synthesis(c, i) for i, c in enumerate(claims, 1))
    return f"""You are writing a cross-source synthesis for the topic "{topic}" from a structured set of extracted claims.

Each claim below is tagged with a handle [C<n>], its rhetorical role, a confidence score for that role, and its source. Synthesize ACROSS sources -- do not summarize source by source.

CLAIM SET:

{claim_block}

YOUR TASK:
Write a synthesis that:
1. CLUSTERS claims by what they assert. Group method claims with related method claims, result claims with comparable result claims. Lead each cluster with what the corpus collectively establishes.
2. NAMES contradictions explicitly. When two sources make claims that conflict (opposing results on the same dataset/metric, a method one source advocates and another critiques), state the disagreement, cite both claims by handle, and -- where the claims provide enough to judge -- say which is better supported and why. Do not paper over conflicts.
3. CITES per claim. Every assertion in your synthesis must cite the claim handle(s) it rests on, e.g. "(C3, C7)". A reader must be able to trace each statement back to its source claims.
4. SURFACES uncertainty. Claims with low role_confidence, single-source results, and stated limitations are signal, not noise. Flag them as the corpus's soft spots rather than dropping them or presenting them as settled.

CONTRACT:
- Cross-source claims and comparisons, an explicit comparison of competing results where the claims support one, named disagreements, and the corpus's shared blind spots. Honor this at a PhD-reviewer level of rigor.
- {ANTI_HALLUCINATION_RULES}
- {REGISTER_RULES}{_emphasis_block(style)}
- {FORMATTING_RULES}

Write the synthesis in Markdown. Begin with the synthesis itself -- no preamble."""
