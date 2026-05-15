"""Concept and entity extraction prompt for the 0.8 playbook layer.

One prompt, called once per insight file. The LLM returns a JSON array
of structured mentions (no prose) that the merge layer projects into
``MergedConcept`` records.

Design notes:

- **JSON-only output.** No prose, no commentary, no markdown wrapping
  beyond what ``extract_json`` already tolerates. This is structured-
  output classification, not generation -- the prompt is explicit about
  this so models like Qwen don't add thinking traces.
- **Per-insight, not per-corpus.** Even with 1M-context cloud models,
  per-insight extraction gives free provenance (each mention is
  attributable to one source) and free idempotence (re-running over an
  unchanged insight produces the same mentions). The cross-source merge
  step lives downstream in pure Python.
- **Constrained kinds.** The model must classify each mention into one
  of seven fixed kinds. Strict vocabulary keeps the merge step from
  having to handle freeform kind strings.
- **Polarity is grounded.** The model must pick from a fixed three:
  helpful (the source advocates or builds on this concept), harmful
  (the source contradicts or argues against), neutral (the source
  mentions in passing without taking a position). Polarity drives the
  credal-interval evidence bounds.
"""

from __future__ import annotations

from distill.prompts.shared import ANTI_HALLUCINATION_RULES, FORMATTING_RULES

__all__ = ["EXTRACTION_PROMPT_ID", "concept_extraction_prompt"]


EXTRACTION_PROMPT_ID = "concepts.extract.v1"


def concept_extraction_prompt(insight_content: str, topic: str) -> str:
    """Build the extraction prompt for one ``_Insights.md`` file.

    Args:
        insight_content: the full content of the source insight,
            frontmatter included. The model needs the frontmatter for
            context (title, source_id, source type) but should not
            extract concepts *from* the frontmatter -- only from the
            body.
        topic: the corpus topic the insight belongs to. Helps the model
            distinguish "this concept is generic vocabulary" from
            "this concept is topical and worth playbook-tracking."

    Returns the full prompt string ready to pass to ``llm_call``.
    """
    return f"""You are extracting concept and entity mentions from a single research-insight document for a structured knowledge base.

TOPIC: {topic}

YOUR TASK:
Identify every named technique, architecture, dataset, metric, person, organization, or vendor that the insight discusses substantively. For each, classify the kind and the source's stance, and pull a short verbatim claim from the insight that grounds your stance assignment.

OUTPUT FORMAT:
A single JSON array of objects. No prose before or after. No markdown wrapping. The schema for each object is:

{{
  "name": "surface form of the concept as it appears in the insight",
  "normalized_name": "lowercase canonical form, e.g. 'rotational embeddings'",
  "kind": "technique" | "architecture" | "dataset" | "metric" | "person" | "organization" | "vendor",
  "polarity": "helpful" | "harmful" | "neutral",
  "claim_excerpt": "10-25 word verbatim or near-verbatim quote from the insight grounding your polarity assignment",
  "evidence_type": "empirical_result" | "methodology" | "citation" | "comparison" | "limitation" | "background"
}}

POLARITY GUIDANCE:
- "helpful": the insight advocates for, builds on, reports positive results from, or recommends this concept/entity.
- "harmful": the insight contradicts, argues against, reports negative results from, or critiques this concept/entity.
- "neutral": the insight mentions in passing, as background, or as a citation -- WITHOUT taking a position.
  When unsure between helpful and harmful, choose neutral. The downstream merge step uses neutrals to widen the
  ambiguity margin -- they are *not* a lesser kind of evidence, they are an honest "I cannot tell."

KIND GUIDANCE:
- "technique": a method, algorithm, or procedure (e.g. "rotational embeddings", "contrastive learning").
- "architecture": a model family or structural design (e.g. "transformer", "MoE", "RNN").
- "dataset": a named corpus or benchmark (e.g. "ICEWS05-15", "GLUE", "ImageNet").
- "metric": a named evaluation measure (e.g. "MRR", "F1", "perplexity").
- "person": an individual researcher or author (NOT generic roles).
- "organization": a research lab, university, or non-commercial body (e.g. "DeepMind", "Stanford NLP").
- "vendor": a commercial company shipping a product (e.g. "OpenAI", "Microsoft", "Nvidia").

QUALITY RULES:
- Only extract concepts the insight discusses *substantively*. Skip passing mentions in references.
- Extract at most one mention per concept per insight. If the insight discusses "transformers" in three places,
  emit ONE mention with the most informative claim_excerpt.
- The normalized_name must be lowercase, singular where natural English allows ("rotational embedding"
  not "rotational embeddings"), and stripped of trailing punctuation.
- {ANTI_HALLUCINATION_RULES}
- {FORMATTING_RULES}
- If the insight contains no named concepts or entities (rare), return an empty array: [].

INSIGHT TO EXTRACT FROM:

{insight_content}

OUTPUT THE JSON ARRAY ONLY:"""
