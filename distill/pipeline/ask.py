"""Corpus-grounded question answering with verify-gated promotion.

Design: ``docs/design/ask-loop.md``. Retrieval reuses the shipped lexical
rank (`search_corpus`), the answer is grounded-only with mandatory citations,
the write-time verify hook grounds its numbers against the retrieved bodies,
and ``save=True`` promotes a *clean* answer into the corpus as a first-class
insight -- invariant 8 ("verification gates re-ingestion") enforced in code:
any unsupported load-bearing claim refuses the promotion, never silently.
"""

# pyright: strict

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from distill._console import console
from distill.config import DistillConfig
from distill.library.paths import (
    ProvenanceFields,
    base_frontmatter,
    slugify_title,
    strip_frontmatter,
    tags_for,
    write_markdown_artifact,
)
from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.pipeline.search import search_corpus
from distill.prompts.ask import ask_prompt
from distill.prompts.registry import PROMPT_IDS

__all__ = ["AskResult", "ask_corpus"]

PROMPT_ID = PROMPT_IDS["ask"]
_TOP_K = 6
_MAX_SOURCE_CHARS = 6_000
_SOURCE_CITATION_RE = re.compile(r"\[([A-Za-z0-9][A-Za-z0-9_.-]*)\]")
_NON_SOURCE_BRACKET_LABELS = frozenset(
    {"Analysis", "Confirmed", "Estimated", "Reported", "Speculated"}
)


@dataclass(slots=True)
class AskResult:
    """Everything one ask run produced."""

    question: str
    answer_path: Path | None
    answer_text: str
    sources: list[str] = field(  # pyright: ignore[reportUnknownVariableType] -- default_factory=list reads as list[Unknown] under strict; the annotation is the real element type
        default_factory=list
    )  # artifact stems, cited order
    saved_insight_path: Path | None = None
    save_refused_reason: str = ""
    no_coverage: bool = False


def _stem(rel_path: str) -> str:
    return Path(rel_path).stem


def _gather_sources(config: DistillConfig, topic: str, question: str) -> tuple[list[str], str, str]:
    """Retrieve top-K artifacts; return (stems, prompt block, concatenated receipt)."""
    results = search_corpus(config, topic, question, limit=_TOP_K)
    stems: list[str] = []
    blocks: list[str] = []
    receipt_parts: list[str] = []
    for r in results:
        full = config.library_dir / r.path
        try:
            body = strip_frontmatter(full.read_text(encoding="utf-8"))
        except OSError:
            continue
        body = body[:_MAX_SOURCE_CHARS]
        stem = _stem(r.path)
        stems.append(stem)
        blocks.append(f"[{stem}]\n{body}")
        receipt_parts.append(body)
    return stems, "\n\n---\n\n".join(blocks), "\n\n".join(receipt_parts)


def ask_corpus(
    question: str,
    *,
    topic: str,
    config: DistillConfig,
    save: bool = False,
    tracker: CostTracker | None = None,
) -> AskResult:
    """Answer *question* from *topic*'s corpus; optionally promote the answer."""
    stems, sources_block, receipt = _gather_sources(config, topic, question)
    if not stems:
        return AskResult(question=question, answer_path=None, answer_text="", no_coverage=True)

    rc = RouterConfig()
    response = llm_call(
        rc,
        workload_tag="qa",
        prompt=ask_prompt(topic=topic, question=question, sources_block=sources_block),
        call_type="ask",
    )
    if tracker is not None:
        tracker.record(TokenUsage.from_response(response, call_type="ask"))
    answer = response.text.strip()
    answer_citations = _extract_source_citations(answer)
    cited = [citation for citation in answer_citations if citation in stems]

    slug = slugify_title(question, source_id="ask")
    answers_dir = config.topic_dir(topic) / "answers"
    answer_md = "\n".join(
        [
            f"# {question}",
            "",
            answer,
            "",
            "## Sources",
            "",
            *(f"- [[{s}]]" for s in (cited or stems)),
            "",
        ]
    )
    answer_path = write_markdown_artifact(
        answers_dir,
        "answer",
        answer_md,
        identity=slug,
        frontmatter=base_frontmatter(
            artifact_type="answer",
            title=question,
            topic=topic,
            source="distill-answer",
            source_id=slug,
            tags=tags_for(topic, "answer"),
            extra={"question": question, "cited_sources": cited or stems},
            provenance=ProvenanceFields(
                model=response.model,
                model_version=response.model,
                temperature=0.0,
                prompt_id=PROMPT_ID,
            ),
        ),
    )
    result = AskResult(
        question=question, answer_path=answer_path, answer_text=answer, sources=cited or stems
    )

    # Verify the answer's numbers against the retrieved bodies (the receipts).
    from distill.pipeline.verify import run_verify_hook

    outcome = run_verify_hook(
        answers_dir,
        answer,
        receipt,
        mode="strict" if save else "warn",
        identity=slug,
        insight_name=answer_path.name,
        source_name="(retrieved corpus excerpts)",
    )
    if outcome is not None and not outcome.report.ok:
        style = "red" if save else "yellow"
        console.print(f"  [{style}]{outcome.summary_line}[/{style}]")

    if not save:
        return result

    # Promotion is strict by definition (invariant 8): any unsupported claim
    # refuses re-ingestion. The Answer.md and sidecar above still exist.
    if outcome is not None and outcome.refused:
        result.save_refused_reason = outcome.summary_line
        return result
    if _looks_like_no_coverage(answer):
        result.save_refused_reason = (
            "answer states the corpus does not cover the question; nothing to promote"
        )
        return result
    citation_refusal = _citation_refusal_reason(answer_citations, cited, stems)
    if citation_refusal:
        result.save_refused_reason = citation_refusal
        return result

    insight_dir = answers_dir / slug
    result.saved_insight_path = write_markdown_artifact(
        insight_dir,
        "insights",
        answer_md,
        identity=slug,
        frontmatter=base_frontmatter(
            artifact_type="insights",
            title=question,
            topic=topic,
            source="distill-answer",
            source_id=slug,
            tags=tags_for(topic, "answer"),
            synthesis_scope="derived-answer",
            extra={"question": question, "cited_sources": cited or stems},
            provenance=ProvenanceFields(
                model=response.model,
                model_version=response.model,
                temperature=0.0,
                prompt_id=PROMPT_ID,
            ),
        ),
    )
    # The promoted insight carries its own verification record for the audit.
    if outcome is not None:
        from distill.pipeline.verify import write_verify_sidecar

        write_verify_sidecar(
            insight_dir,
            outcome.report,
            identity=slug,
            insight_name=result.saved_insight_path.name,
            source_name="(retrieved corpus excerpts)",
        )
    return result


_NO_COVERAGE_RE = re.compile(
    r"corpus does not cover|corpus doesn'?t cover|not covered by (the|this) corpus", re.IGNORECASE
)


def _looks_like_no_coverage(answer: str) -> bool:
    """Cheap guard: don't promote an answer whose substance is 'no coverage'."""
    head = answer[:300]
    return bool(_NO_COVERAGE_RE.search(head))


def _extract_source_citations(answer: str) -> list[str]:
    """Return bracketed source stems from an answer, preserving first-use order."""
    citations: list[str] = []
    seen: set[str] = set()
    for match in _SOURCE_CITATION_RE.finditer(answer):
        citation = match.group(1)
        if citation in _NON_SOURCE_BRACKET_LABELS or citation in seen:
            continue
        seen.add(citation)
        citations.append(citation)
    return citations


def _citation_refusal_reason(
    answer_citations: list[str], cited: list[str], allowed_stems: list[str]
) -> str:
    """Structural promotion gate for source identity in bracket citations."""
    allowed = set(allowed_stems)
    unknown = [citation for citation in answer_citations if citation not in allowed]
    if unknown:
        sample = ", ".join(unknown[:5])
        extra = "" if len(unknown) <= 5 else f", +{len(unknown) - 5} more"
        return f"answer cites unknown source(s): {sample}{extra}"
    if not cited:
        return "answer includes no valid source citations; nothing to promote"
    return ""
