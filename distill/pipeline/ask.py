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
    artifact_path,
    base_frontmatter,
    render_markdown_artifact,
    slugify_title,
    strip_frontmatter,
    tags_for,
    write_markdown_artifact,
)
from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
from distill.pipeline.citation_refs import (
    citation_refusal_reason,
    extract_source_citations,
)
from distill.pipeline.costs import CostTracker, TokenUsage, estimate_ask_workflow_cost
from distill.pipeline.search import read_search_result, search_corpus
from distill.pipeline.verify import (
    VerifyOutcome,
    entailment_checker_available,
    run_verify_hook,
    write_verified_artifact,
)
from distill.prompts.ask import ask_prompt
from distill.prompts.registry import PROMPT_IDS

__all__ = ["MAX_ASK_ANSWER_CHARS", "MAX_ASK_QUESTION_CHARS", "AskResult", "ask_corpus"]

PROMPT_ID = PROMPT_IDS["ask"]
_TOP_K = 6
_MAX_SOURCE_CHARS = 6_000
MAX_ASK_QUESTION_CHARS = 4_096
MAX_ASK_ANSWER_CHARS = 64_000
_SAVE_VERIFIER_REFUSAL = (
    "save requires semantic verification; install distillr[entailment] and ensure "
    "the pinned local checker can load"
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
    answer_refused_reason: str = ""
    saved_insight_path: Path | None = None
    save_refused_reason: str = ""
    no_coverage: bool = False
    estimated_cost: float | None = None


def _stem(rel_path: str) -> str:
    return Path(rel_path).stem


def _gather_sources(config: DistillConfig, topic: str, question: str) -> tuple[list[str], str, str]:
    """Retrieve top-K artifacts; return (stems, prompt block, concatenated receipt)."""
    results = search_corpus(config, topic, question, limit=_TOP_K)
    stems: list[str] = []
    blocks: list[str] = []
    receipt_parts: list[str] = []
    for r in results:
        content = read_search_result(config, r)
        if content is None:
            continue
        body = strip_frontmatter(content)
        body = body[:_MAX_SOURCE_CHARS]
        stem = _stem(r.path)
        stems.append(stem)
        blocks.append(f"[{stem}]\n{body}")
        receipt_parts.append(body)
    return stems, "\n\n---\n\n".join(blocks), "\n\n".join(receipt_parts)


def _ask_workflow_budget_usd(config: DistillConfig) -> float | None:
    return config.cost_workflow_budgets_usd.get("ask")


def _enforce_ask_projected_budget(
    config: DistillConfig,
    *,
    source_chars: int,
    question_chars: int,
    router_config: RouterConfig,
) -> float:
    from distill.pipeline.costs import ProjectedBudgetExceededError

    projected = estimate_ask_workflow_cost(
        source_chars,
        question_chars=question_chars,
        router_config=router_config,
    )
    budget = _ask_workflow_budget_usd(config)
    if budget is None:
        return projected
    if projected > budget:
        raise ProjectedBudgetExceededError(projected, budget)
    return projected


def _save_verifier_refusal(save: bool) -> str:
    if not save or entailment_checker_available():
        return ""
    return _SAVE_VERIFIER_REFUSAL


def _promote_verified_answer(
    result: AskResult,
    outcome: VerifyOutcome | None,
    *,
    insight_dir: Path,
    slug: str,
    answer_md: str,
    question: str,
    topic: str,
    model: str,
    cited_sources: list[str],
) -> None:
    """Promote one answer only after complete strict semantic verification.

    The verification sidecar is committed first. Corpus discovery can therefore
    never observe a newly promoted insight whose verification record failed to
    reach durable storage.
    """
    if outcome is None:
        result.save_refused_reason = "verify strict: required semantic verification did not run"
        return
    if outcome.refused:
        result.save_refused_reason = outcome.summary_line
        return
    insight_path = artifact_path(insight_dir, "insights", identity=slug)
    frontmatter = base_frontmatter(
        artifact_type="insights",
        title=question,
        topic=topic,
        source="distill-answer",
        source_id=slug,
        tags=tags_for(topic, "answer"),
        synthesis_scope="derived-answer",
        extra={
            "question": question,
            "cited_sources": cited_sources,
            "verification_required": True,
        },
        provenance=ProvenanceFields(
            model=model,
            model_version=model,
            temperature=0.0,
            prompt_id=PROMPT_ID,
        ),
    )
    promoted_content = render_markdown_artifact(
        "insights",
        answer_md,
        frontmatter=frontmatter,
    )
    write_verified_artifact(
        insight_dir,
        insight_path,
        promoted_content,
        outcome=outcome,
        verify_identity=slug,
        source_name="(retrieved corpus excerpts)",
    )
    result.saved_insight_path = insight_path


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
    projected_cost = _enforce_ask_projected_budget(
        config,
        source_chars=len(sources_block),
        question_chars=len(question),
        router_config=rc,
    )
    save_refusal = _save_verifier_refusal(save)
    if save_refusal:
        return AskResult(
            question=question,
            answer_path=None,
            answer_text="",
            save_refused_reason=save_refusal,
            estimated_cost=projected_cost,
        )
    response = llm_call(
        rc,
        workload_tag="qa",
        prompt=ask_prompt(topic=topic, question=question, sources_block=sources_block),
        call_type="ask",
        usage_tracker=tracker,
    )
    if tracker is not None:
        tracker.record(TokenUsage.from_response(response, call_type="ask"))
    answer = response.text.strip()
    if len(answer) > MAX_ASK_ANSWER_CHARS:
        refusal = f"answer exceeds the {MAX_ASK_ANSWER_CHARS}-character artifact limit"
        return AskResult(
            question=question,
            answer_path=None,
            answer_text=answer[:MAX_ASK_ANSWER_CHARS],
            answer_refused_reason=refusal,
            save_refused_reason=refusal if save else "",
            estimated_cost=projected_cost,
        )
    answer_citations = extract_source_citations(answer)
    cited = [citation for citation in answer_citations if citation in stems]
    if _looks_like_no_coverage(answer):
        refusal = "answer states the corpus does not cover the question; nothing to write"
        return AskResult(
            question=question,
            answer_path=None,
            answer_text=answer,
            sources=cited,
            answer_refused_reason=refusal,
            save_refused_reason=refusal if save else "",
            estimated_cost=projected_cost,
        )
    citation_refusal = citation_refusal_reason(
        answer_citations,
        cited,
        stems,
        subject="answer",
        action="write",
    )
    if citation_refusal:
        return AskResult(
            question=question,
            answer_path=None,
            answer_text=answer,
            sources=cited,
            answer_refused_reason=citation_refusal,
            save_refused_reason=citation_refusal if save else "",
            estimated_cost=projected_cost,
        )

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
        question=question,
        answer_path=answer_path,
        answer_text=answer,
        sources=cited or stems,
        estimated_cost=projected_cost,
    )

    # Verify the answer's numbers against the retrieved bodies (the receipts).
    outcome = run_verify_hook(
        answers_dir,
        answer,
        receipt,
        mode="strict" if save else "warn",
        identity=slug,
        insight_name=answer_path.name,
        source_name="(retrieved corpus excerpts)",
        require_entailment=save,
    )
    if outcome is not None and outcome.has_flags:
        style = "red" if save else "yellow"
        console.print(f"  [{style}]{outcome.summary_line}[/{style}]")

    if not save:
        return result

    # Promotion is strict by definition. The answer and its sidecar remain
    # inspectable when any numeric or semantic gate refuses re-ingestion.
    insight_dir = answers_dir / slug
    _promote_verified_answer(
        result,
        outcome,
        insight_dir=insight_dir,
        slug=slug,
        answer_md=answer_md,
        question=question,
        topic=topic,
        model=response.model,
        cited_sources=cited or stems,
    )
    return result


_NO_COVERAGE_RE = re.compile(
    r"corpus does not cover|corpus doesn'?t cover|not covered by (the|this) corpus",
    re.IGNORECASE,
)


def _looks_like_no_coverage(answer: str) -> bool:
    """Cheap guard: don't promote an answer whose substance is 'no coverage'."""
    head = answer[:300]
    return bool(_NO_COVERAGE_RE.search(head))
