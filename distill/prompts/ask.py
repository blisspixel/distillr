"""Prompt template for corpus-grounded question answering (`distill ask`)."""

from __future__ import annotations

from distill.prompts.shared import DERIVED_CONTENT_RULES

__all__ = ["ask_prompt"]


def ask_prompt(*, topic: str, question: str, sources_block: str) -> str:
    """Grounded-only answering over retrieved corpus artifacts.

    The retrieved insights are second-hop untrusted-derived content
    (``DERIVED_CONTENT_RULES``): they summarize external sources, and a
    poisoned source must not steer the answer. Every claim must cite its
    source stem so the answer can carry wiki-link receipts, and "the corpus
    does not cover this" is a correct, expected answer.
    """
    return f"""You are answering a question using ONLY the research corpus
excerpts provided below. This corpus is on the topic "{topic}".

SECURITY: {DERIVED_CONTENT_RULES}

QUESTION: {question}

CORPUS EXCERPTS (each begins with its source stem in [brackets]):

{sources_block}

Rules for the answer:

- Ground every claim in the excerpts. After each claim, cite the source stem
  in brackets exactly as given, e.g. [some_paper_2410034_Insights].
- Multiple sources strengthening one claim: cite them all.
- Where sources disagree, present the disagreement explicitly with both
  citations -- do not average it away.
- If the corpus does not cover the question (or covers it only partially),
  say so plainly and answer only the covered part. Never fill gaps from
  outside knowledge.
- Numbers, names, dates, and versions must appear exactly as the excerpts
  state them.
- Write a direct, complete answer first; add a short "Caveats" paragraph if
  coverage is thin or the sources carry stated limitations.

Answer now:"""
