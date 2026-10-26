# pyright: strict
"""Bounded source reconciliation for chunks omitted by focused paper passes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from distill.llm.metadata import ProviderMetadata
from distill.llm.router import LLM_Response, RouterConfig, call
from distill.pipeline.analysis.chunk_selection import parse_section_blocks
from distill.pipeline.analysis.chunking import Chunk, chunk_content, estimate_tokens
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.lenses import focus_directive
from distill.prompts.shared import UNTRUSTED_CONTENT_RULES

if TYPE_CHECKING:
    from distill.pipeline.analysis.multipass import PassResult

_MAX_REVIEW_CALLS = 16
RECONCILIATION_SECTION = "source reconciliation"


@dataclass(frozen=True)
class PaperReviewResult:
    chunks: list[Chunk]
    passes: list[PassResult]


@dataclass
class _ReviewInputs:
    inventory: list[Chunk]
    pending: list[Chunk]
    next_index: int


def _review_prompt(body: str, chunks: list[Chunk], *, goal: str, lens: str) -> str:
    from distill.pipeline.analysis.multipass import PAPER_CANONICAL_SECTIONS

    evidence = "\n\n".join(f"SOURCE CHUNK {chunk.index}:\n{chunk.text}" for chunk in chunks)
    headings = "\n".join(f"## {heading}" for heading in PAPER_CANONICAL_SECTIONS)
    return (
        "Reconcile the entire paper insight with the new source evidence.\n"
        + focus_directive(goal=goal, lens=lens)
        + "Prior insight is provisional interpretation, not corroboration. "
        "Correct all affected sections, including Summary; keep supported unaffected findings. "
        "Preserve metric type, denominator, population, causal scope, qualifications, uncertainty "
        "and disagreement. Repeated text is not independent evidence. Never invent unseen evidence. "
        "Cite SOURCE CHUNK ids. Return one coherent complete insight under all six headings; "
        "state gaps explicitly.\n"
        f"{headings}\n\nSECURITY: {UNTRUSTED_CONTENT_RULES}\n\n"
        f"PROVISIONAL INSIGHT:\n{body}\n\nNEW PRIMARY EVIDENCE:\n{evidence}"
    )


def _refuse(reason: str) -> ValueError:
    return ValueError(f"Paper source reconciliation is incomplete: {reason}")


def _next_review_group(
    inputs: _ReviewInputs, body: str, prompt_limit: int, *, goal: str, lens: str
) -> list[Chunk]:
    group: list[Chunk] = []
    while inputs.pending:
        candidate = inputs.pending[0]
        prompt = _review_prompt(body, [*group, candidate], goal=goal, lens=lens)
        if estimate_tokens(prompt) <= prompt_limit:
            group.append(inputs.pending.pop(0))
            continue
        if group:
            break
        empty = Chunk("", candidate.heading_context, inputs.next_index, 0)
        room = (
            prompt_limit - estimate_tokens(_review_prompt(body, [empty], goal=goal, lens=lens)) - 2
        )
        if room <= 0:
            raise _refuse("the complete carried insight and review instructions do not fit")
        try:
            pieces = chunk_content(candidate.text, room, reserved_ratio=0.0)
        except ValueError as exc:
            raise _refuse(f"a source fragment cannot fit safely: {exc}") from exc
        if len(pieces) <= 1 or any(estimate_tokens(piece.text) > room for piece in pieces):
            raise _refuse("a source fragment cannot fit without dropping content")
        fragments = [
            Chunk(piece.text, candidate.heading_context, inputs.next_index + offset, 0)
            for offset, piece in enumerate(pieces)
        ]
        inputs.next_index += len(fragments)
        inputs.inventory = [chunk for chunk in inputs.inventory if chunk.index != candidate.index]
        inputs.inventory.extend(fragments)
        inputs.pending[:1] = fragments
    return group


def reconcile_paper_evidence(
    chunks: list[Chunk],
    results: list[PassResult],
    config: RouterConfig,
    metadata: ProviderMetadata,
    *,
    tracker: CostTracker | None = None,
    goal: str = "",
    lens: str = "",
    call_model: Callable[[str], LLM_Response] | None = None,
) -> PaperReviewResult:
    """Read every omitted source part and carry one coherent insight forward.

    Only previously unexecuted chunks may be split, and their actual fragments
    replace them in the supplied-input inventory. A partial fragment never
    claims the identity of the original whole chunk. No source prefix or prior
    insight is discarded to fit a request; insufficient capacity refuses.
    """
    from distill.pipeline.analysis.multipass import (
        PAPER_CANONICAL_SECTIONS,
        PassResult,
        merge_paper_pass_results,
    )

    executed = {index for result in results for index in result.chunk_indices}
    pending = [chunk for chunk in chunks if chunk.index not in executed]
    if not pending:
        return PaperReviewResult(list(chunks), list(results))
    if not any(result.insights.strip() for result in results):
        raise _refuse("focused passes produced no nonempty insight")
    body = merge_paper_pass_results([row for row in results if row.insights.strip()], body="")
    reviewed = list(results)
    prompt_limit = int(metadata.context_window * 0.80)
    inputs = _ReviewInputs(
        list(chunks), pending, max((chunk.index for chunk in chunks), default=-1) + 1
    )
    calls = 0
    while inputs.pending:
        if calls >= _MAX_REVIEW_CALLS:
            raise _refuse(f"more than {_MAX_REVIEW_CALLS} source review calls are required")
        group = _next_review_group(inputs, body, prompt_limit, goal=goal, lens=lens)
        prompt = _review_prompt(body, group, goal=goal, lens=lens)
        response = (
            call_model(prompt)
            if call_model is not None
            else call(
                config,
                workload_tag="analysis",
                prompt=prompt,
                call_type="paper_source_reconciliation",
                usage_tracker=tracker,
            )
        )
        if tracker is not None:
            tracker.record(TokenUsage.from_response(response, call_type="paper"))
        calls += 1
        if response.finish_reason.casefold() in {"length", "max_tokens", "max_output_tokens"}:
            raise _refuse("the provider reported truncated reconciliation output")
        candidate_body = response.text.strip()
        sections = parse_section_blocks(candidate_body)
        if any(not sections.get(heading, "").strip() for heading in PAPER_CANONICAL_SECTIONS):
            raise _refuse("the provider did not return all six nonempty insight sections")
        body = candidate_body
        reviewed.append(
            PassResult(
                category=RECONCILIATION_SECTION,
                insights=body,
                chunks_used=len(group),
                selection_mode="positional_order",
                model=response.model,
                chunk_indices=tuple(chunk.index for chunk in group),
            )
        )
    inventory = [
        Chunk(chunk.text, chunk.heading_context, chunk.index, len(inputs.inventory))
        for chunk in sorted(inputs.inventory, key=lambda chunk: chunk.index)
    ]
    return PaperReviewResult(inventory, reviewed)
