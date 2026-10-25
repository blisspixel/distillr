"""Identity and honest unknown-state checks, not semantic quality scoring."""

import hashlib

import pytest

from distill.pipeline.analysis.chunking import Chunk
from distill.pipeline.analysis.multipass import PassResult
from distill.pipeline.analysis.paper_evidence import paper_input_evidence


def _chunks():
    return [
        Chunk("A measurement.", "## Results", 0, 2),
        Chunk("A late qualification.", "## Erratum", 1, 2),
    ]


def _evidence(results, chunks=None, *, single_pass=False):
    return paper_input_evidence(
        "Full receipt including both source sections.",
        _chunks() if chunks is None else chunks,
        results,
        context_window=1024,
        source_capture="abstract_only",
        single_pass=single_pass,
    )


def test_omitted_chunk_is_exactly_identified_without_a_quality_verdict():
    result = PassResult("evidence", "An answer", 1, model="actual-model", chunk_indices=(0,))
    evidence = _evidence([result])
    assert evidence["schema"] == "paper-input-evidence.v1"
    assert evidence["prompt_chunk_coverage"] == "some_supplied_chunks"
    assert evidence["semantic_sufficiency"] == "not_assessed"
    assert evidence["source_capture"] == "abstract_only"
    assert evidence["original_source_completeness"] == "not_established"
    assert evidence["selected_chunk_indices"] == [0]
    assert evidence["omitted_chunk_indices"] == [1]
    assert evidence["selection_budget_estimated_tokens"] == 819
    assert (
        evidence["document_sha256"]
        == hashlib.sha256(b"Full receipt including both source sections.").hexdigest()
    )
    assert evidence["chunks"] == [
        {
            "index": chunk.index,
            "heading": chunk.heading_context,
            "sha256": hashlib.sha256(chunk.text.encode()).hexdigest(),
            "estimated_tokens": len(chunk.text) // 4,
        }
        for chunk in _chunks()
    ]


def test_shared_chunk_counts_once_and_executed_order_is_preserved():
    evidence = _evidence(
        [
            PassResult("first", "body", 2, model="m1", chunk_indices=(1, 0)),
            PassResult("second", "body", 1, model="m2", chunk_indices=(1,)),
        ]
    )
    assert evidence["prompt_chunk_coverage"] == "all_supplied_chunks"
    assert evidence["selected_chunk_indices"] == [0, 1]
    assert evidence["omitted_chunk_indices"] == []
    assert evidence["passes"] == [
        {
            "section": "first",
            "chunk_indices": [1, 0],
            "model": "m1",
            "selection_mode": "structural",
            "output_present": True,
        },
        {
            "section": "second",
            "chunk_indices": [1],
            "model": "m2",
            "selection_mode": "structural",
            "output_present": True,
        },
    ]


@pytest.mark.parametrize(
    "results",
    [
        [],
        [PassResult("legacy", "body", 2)],
        [PassResult("unknown", "body", 1, chunk_indices=(99,))],
        [PassResult("repeated", "body", 2, chunk_indices=(0, 0))],
        [PassResult("count mismatch", "body", 1, chunk_indices=(0, 1))],
        [PassResult("empty selection", "body", 0)],
    ],
)
def test_unreliable_picks_leave_omissions_unknown(results):
    evidence = _evidence(results)
    assert evidence["prompt_chunk_coverage"] == "unknown"
    assert evidence["omitted_chunk_indices"] is None


def test_duplicate_supplied_ids_cannot_certify_coverage():
    chunks = [*_chunks(), Chunk("Different text with reused ID", "", 0, 3)]
    evidence = _evidence([PassResult("pass", "body", 2, chunk_indices=(0, 1))], chunks)
    assert evidence["prompt_chunk_coverage"] == "unknown"
    assert evidence["omitted_chunk_indices"] is None


def test_empty_response_retains_actual_inputs_but_does_not_claim_an_answer():
    evidence = _evidence([PassResult("empty", " \n", 1, chunk_indices=(0,))])
    assert evidence["prompt_chunk_coverage"] == "some_supplied_chunks"
    assert evidence["passes"] == [
        {
            "section": "empty",
            "chunk_indices": [0],
            "model": "unknown",
            "selection_mode": "structural",
            "output_present": False,
        }
    ]


def test_single_pass_can_cover_all_of_an_abstract_without_proving_full_pdf_capture():
    evidence = _evidence(
        [PassResult("single pass", "body", 1, model="actual", chunk_indices=(0,))],
        [Chunk("Only the captured abstract.", "", 0, 1)],
        single_pass=True,
    )
    assert evidence["execution_mode"] == "single_pass"
    assert evidence["prompt_chunk_coverage"] == "all_supplied_chunks"
    assert evidence["source_capture"] == "abstract_only"
    assert evidence["semantic_sufficiency"] == "not_assessed"


def test_published_source_identity_is_separate_from_analyzer_input():
    document = "**## Source heading**\nOriginal source text.\n"
    evidence = paper_input_evidence(
        document,
        [Chunk(document, "", 0, 1)],
        [PassResult("single pass", "body", 1, model=" \t", chunk_indices=(0,))],
        context_window=4096,
        source_capture="full_pdf",
        single_pass=True,
    )
    assert evidence["document_sha256"] == hashlib.sha256(document.encode()).hexdigest()
    assert (
        evidence["published_receipt_body_sha256"]
        == hashlib.sha256(b"## Source heading\nOriginal source text.").hexdigest()
    )
    assert evidence["context_window_basis"] == "requested_workload_metadata"
    assert evidence["passes"] == [
        {
            "section": "single pass",
            "chunk_indices": [0],
            "model": "unknown",
            "selection_mode": "single_pass",
            "output_present": True,
        }
    ]


def test_missing_supplied_chunks_cannot_certify_coverage():
    evidence = _evidence([PassResult("pass", "body", 1, chunk_indices=(0,))], [])
    assert evidence["prompt_chunk_coverage"] == "unknown"
    assert evidence["omitted_chunk_indices"] is None
