"""Source reconciliation mechanics, separate from model faithfulness judgments."""

from unittest.mock import patch

import pytest

from distill.llm.metadata import ProviderMetadata
from distill.llm.router import LLM_Response, RouterConfig
from distill.pipeline.analysis.chunking import Chunk, estimate_tokens
from distill.pipeline.analysis.multipass import (
    PAPER_CANONICAL_SECTIONS,
    PassResult,
    merge_paper_pass_results,
)
from distill.pipeline.analysis.paper_review import reconcile_paper_evidence
from distill.pipeline.costs import BudgetExceededError, CostTracker


def _body(summary="Provisional interpretation."):
    return "\n\n".join(
        f"## {heading}\n{summary if heading == 'Summary' else 'Not established.'}"
        for heading in PAPER_CANONICAL_SECTIONS
    )


def _inputs(missing="A late primary-source qualification."):
    return (
        [Chunk("A primary result.", "## Results", 0, 2), Chunk(missing, "## Erratum", 1, 2)],
        [PassResult("front matter", _body(), 1, model="focused-model", chunk_indices=(0,))],
    )


def _response(text=None, *, finish_reason=""):
    return LLM_Response(
        text=_body("Reconciled result.") if text is None else text,
        input_tokens=17,
        output_tokens=2,
        model="grok-4.6",
        finish_reason=finish_reason,
    )


def _review(chunks, results, *, window=4096, tracker=None, call_model=None):
    return reconcile_paper_evidence(
        chunks,
        results,
        RouterConfig(),
        ProviderMetadata(context_window=window, provider_type="cloud", provider_name="xai"),
        tracker=tracker,
        call_model=call_model,
    )


def test_no_omissions_require_no_additional_model_call():
    chunks, results = _inputs()
    results[0].chunk_indices = (0, 1)
    results[0].chunks_used = 2
    with patch("distill.pipeline.analysis.paper_review.call") as transport:
        reviewed = _review(chunks, results)
    assert reviewed.chunks == chunks
    assert reviewed.passes == results
    transport.assert_not_called()


def test_one_bounded_review_replaces_the_whole_provisional_insight_and_accounts_usage():
    chunks, results = _inputs()
    tracker = CostTracker()
    revised = _body(
        "The late qualification changes the provisional conclusion; calibration remains."
    )
    with patch(
        "distill.pipeline.analysis.paper_review.call", return_value=_response(revised)
    ) as transport:
        reviewed = _review(chunks, results, tracker=tracker)
    prompt = transport.call_args.kwargs["prompt"]
    assert merge_paper_pass_results(results, body="") in prompt
    assert "SOURCE CHUNK 1:\n" + chunks[1].text in prompt
    assert transport.call_args.kwargs["workload_tag"] == "analysis"
    assert transport.call_args.kwargs["usage_tracker"] is tracker
    assert reviewed.passes[-1].chunk_indices == (1,)
    assert reviewed.passes[-1].model == "grok-4.6"
    assert merge_paper_pass_results(reviewed.passes, body="") == revised + "\n"
    assert len(tracker.entries) == 1
    assert tracker.entries[0].prompt_tokens == 17
    assert tracker.total_cost > 0


def test_residual_fragment_inventory_binds_actual_parts_and_preserves_the_late_tail():
    words = [f"sourceword{index}" for index in range(600)]
    chunks, results = _inputs(" ".join(words))
    original = list(chunks)
    prompts = []

    def respond(prompt):
        prompts.append(prompt)
        return _response()

    reviewed = _review(chunks, results, window=1024, call_model=respond)
    assert chunks == original  # The caller's full original receipt inventory is not mutated.
    assert len(prompts) > 1
    assert all(estimate_tokens(prompt) <= int(1024 * 0.8) for prompt in prompts)
    assert 1 not in {chunk.index for chunk in reviewed.chunks}
    fragments = {chunk.index: chunk for chunk in reviewed.chunks if chunk.index != 0}
    assert fragments
    for result, prompt in zip(reviewed.passes[1:], prompts, strict=True):
        for index in result.chunk_indices:
            assert f"SOURCE CHUNK {index}:\n" + fragments[index].text in prompt
    assert all(any(word in prompt for prompt in prompts) for word in words)
    assert {index for result in reviewed.passes for index in result.chunk_indices} == {
        chunk.index for chunk in reviewed.chunks
    }
    assert all(chunk.total_chunks == len(reviewed.chunks) for chunk in reviewed.chunks)


@pytest.mark.parametrize(
    ("text", "finish_reason"),
    [("", ""), (" \n", ""), ("## Summary\nIncomplete.", ""), (_body(), "MAX_TOKENS")],
)
def test_unusable_or_truncated_review_refuses_after_retaining_incurred_usage(text, finish_reason):
    chunks, results = _inputs()
    tracker = CostTracker()
    with pytest.raises(ValueError, match="reconciliation is incomplete"):
        _review(
            chunks,
            results,
            tracker=tracker,
            call_model=lambda _: _response(text, finish_reason=finish_reason),
        )
    assert len(tracker.entries) == 1
    assert tracker.total_cost > 0


def test_carried_insight_is_never_prefix_truncated_to_force_a_review():
    chunks, results = _inputs()
    results[0].insights = _body("Long supported context. " * 1000)
    with patch("distill.pipeline.analysis.paper_review.call") as transport:
        with pytest.raises(ValueError, match="complete carried insight"):
            _review(chunks, results, window=1024)
        transport.assert_not_called()


def test_source_review_request_cap_refuses_before_an_extra_call(monkeypatch):
    chunks, results = _inputs(" ".join(f"sourceword{index}" for index in range(600)))
    monkeypatch.setattr("distill.pipeline.analysis.paper_review._MAX_REVIEW_CALLS", 1)
    tracker = CostTracker()
    with (
        patch("distill.pipeline.analysis.paper_review.call", return_value=_response()) as transport,
        pytest.raises(ValueError, match="more than 1 source review calls"),
    ):
        _review(chunks, results, window=1024, tracker=tracker)
    transport.assert_called_once()
    assert len(tracker.entries) == 1


def test_existing_cost_refusal_is_not_caught_or_retried():
    chunks, results = _inputs()
    with (
        patch(
            "distill.pipeline.analysis.paper_review.call", side_effect=BudgetExceededError(2, 1)
        ) as transport,
        pytest.raises(BudgetExceededError),
    ):
        _review(chunks, results)
    transport.assert_called_once()


def test_no_usable_focused_output_cannot_become_a_nominal_success():
    chunks, results = _inputs()
    results[0].insights = " \n"
    with pytest.raises(ValueError, match="focused passes produced no nonempty insight"):
        _review(chunks, results)


def test_unfit_source_heading_refuses_instead_of_claiming_partial_fragment_coverage():
    chunks, results = _inputs("## " + "UnbreakableHeading" * 1000 + "\nA source qualification.")
    with patch("distill.pipeline.analysis.paper_review.call") as transport:
        with pytest.raises(ValueError, match="source fragment cannot fit"):
            _review(chunks, results, window=1024)
        transport.assert_not_called()
