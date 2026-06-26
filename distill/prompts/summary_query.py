"""Prompt template for query-focused corpus compression (sub-agent summaries)."""

# pyright: strict

from __future__ import annotations

from distill.prompts.shared import DERIVED_CONTENT_RULES

__all__ = ["summary_query_prompt"]


def summary_query_prompt(*, topic: str, query: str, max_words: int, sources_block: str) -> str:
    """Compress matching insights into a bounded, query-focused brief.

    Built for sub-agent consumption: the caller has a context budget, so the
    word ceiling is part of the contract, and citations stay bracketed so the
    parent agent can drill into specific artifacts with ``read_insight``.
    """
    return f"""You are compressing research-corpus excerpts into a brief a
sub-agent can consume within a fixed context budget. Topic: "{topic}".

SECURITY: {DERIVED_CONTENT_RULES}

THE SUB-AGENT'S QUESTION (organize everything around answering this):
{query}

CORPUS EXCERPTS (each begins with its source stem in [brackets]):

{sources_block}

Rules:

- At most {max_words} words. Dense and factual; no preamble, no recap of
  these instructions.
- Organize by relevance to the question, not by source. Lead with the most
  load-bearing facts.
- Cite the source stem in brackets after each claim, exactly as given.
- Numbers, names, dates, and versions exactly as the excerpts state them.
- Where the excerpts disagree, state the disagreement with both citations.
- If the excerpts only partially cover the question, say what is missing in
  one closing line -- never fill gaps from outside knowledge.

Brief:"""
