# pyright: strict
"""Exact supplied-input evidence, separate from semantic research sufficiency."""

from __future__ import annotations

import hashlib

from distill.library.insights import receipt_body_sha256
from distill.library.paths import render_markdown_artifact
from distill.pipeline.analysis.chunking import Chunk, estimate_tokens
from distill.pipeline.analysis.multipass import PassResult


def paper_input_evidence(
    document: str,
    chunks: list[Chunk],
    results: list[PassResult],
    *,
    context_window: int,
    source_capture: str,
    single_pass: bool = False,
) -> dict[str, object]:
    """Bind actual prompt picks to supplied chunks without judging their meaning.

    Older result objects omit chunk indices. Such results cannot establish an
    omitted set, even when their chunk count happens to equal the input count.
    Chunk hashes cover transformed prompt text, not source byte ranges.
    """
    chunk_ids = {chunk.index for chunk in chunks}
    identities_valid = len(chunk_ids) == len(chunks)
    known = bool(chunks) and bool(results) and identities_valid
    selected: set[int] = set()
    pass_rows: list[dict[str, object]] = []
    for result in results:
        indices = result.chunk_indices
        reliable = (
            identities_valid
            and result.chunks_used > 0
            and len(indices) == result.chunks_used
            and len(set(indices)) == len(indices)
            and set(indices) <= chunk_ids
        )
        known = known and reliable
        if reliable:
            selected.update(indices)
        pass_rows.append(
            {
                "section": result.category,
                "chunk_indices": list(indices) if reliable else None,
                "model": result.model.strip() or "unknown",
                "selection_mode": "single_pass" if single_pass else result.selection_mode,
                "output_present": bool(result.insights.strip()),
            }
        )

    chunk_rows: list[dict[str, object]] = [
        {
            "index": chunk.index,
            "heading": chunk.heading_context,
            "sha256": hashlib.sha256(chunk.text.encode("utf-8")).hexdigest(),
            "estimated_tokens": estimate_tokens(chunk.text),
        }
        for chunk in chunks
    ]
    return {
        "schema": "paper-input-evidence.v1",
        "document_sha256": hashlib.sha256(document.encode("utf-8")).hexdigest(),
        "published_receipt_body_sha256": receipt_body_sha256(
            render_markdown_artifact("paper", document)
        ),
        "source_capture": source_capture,
        "original_source_completeness": "not_established",
        "execution_mode": "single_pass" if single_pass else "multipass",
        "workload_tag": "site" if single_pass else "analysis",
        "context_window_tokens": context_window,
        "context_window_basis": "requested_workload_metadata",
        "selection_budget_estimated_tokens": int(context_window * 0.80),
        "token_estimator": "characters_div_4",
        "prompt_chunk_coverage": (
            "unknown"
            if not known
            else "all_supplied_chunks"
            if selected == chunk_ids
            else "some_supplied_chunks"
        ),
        "semantic_sufficiency": "not_assessed",
        "chunks": chunk_rows,
        "passes": pass_rows,
        "selected_chunk_indices": sorted(selected),
        "omitted_chunk_indices": sorted(chunk_ids - selected) if known else None,
    }
