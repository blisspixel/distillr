"""Observe source-complete production selection without judging mocked prose.

The old omitted-source counterexamples now require bounded reconciliation.
The tests exercise selection within one synthetic paper, not cross-source
discovery or deduplication. Only acquisition, metadata discovery and model
transport are replaced. Prompt inclusion does not establish final faithfulness.
"""

import hashlib
import json

import pytest

from distill.config import DistillConfig
from distill.ingestors.papers.arxiv import PaperRecord
from distill.library.paths import extract_frontmatter, find_artifact, strip_frontmatter
from distill.llm.metadata import ProviderMetadata
from distill.llm.router import LLM_Response
from distill.pipeline.analysis.chunking import chunk_content, estimate_tokens
from distill.pipeline.analysis.multipass import PAPER_CANONICAL_SECTIONS
from distill.pipeline.analysis.paper import analyze_paper

_MEASUREMENT = "The incidents-to-PR ratio rose 242.7% between adoption periods."
_CAVEAT = (
    "One PR may have several incidents. This ratio is not incident probability; "
    "the observational comparison does not establish causation."
)


def _input_evidence(insights):
    return json.loads(extract_frontmatter(insights)["paper_input_evidence"])


def _paper():
    return PaperRecord(
        paper_id="synthetic-selection-v1",
        title="Synthetic evidence selection challenge",
        abstract="Authored fixture, not an independent source or live paper.",
        authors=["Fixture"],
        abs_url="https://example.invalid/paper",
    )


@pytest.fixture
def capture_analysis(monkeypatch, tmp_path):
    """Run the real paper/chunk/selection/prompt path with inert responses."""
    prompts = []
    response_body = None

    def respond(config, *, prompt, call_type, **kwargs):
        prompts.append((call_type, prompt))
        return LLM_Response(
            text=(
                response_body(call_type, prompt)
                if response_body is not None
                else "\n\n".join(
                    f"## {heading}\nNot judged." for heading in PAPER_CANONICAL_SECTIONS
                )
                if call_type == "paper_source_reconciliation"
                else "Transport stub, not a research answer."
            ),
            model="offline-stub",
            input_tokens=0,
            output_tokens=0,
        )

    def unexpected_ranking(*args, **kwargs):
        pytest.fail("All passes have structural matches; ranking should not run")

    monkeypatch.setattr("distill.pipeline.analysis.paper.llm_call", respond)
    monkeypatch.setattr("distill.pipeline.analysis.multipass.call", respond)
    monkeypatch.setattr("distill.pipeline.analysis.chunk_selection.call", unexpected_ranking)
    monkeypatch.setattr("distill.pipeline.analysis.chunk_selection.model_available", lambda _: True)

    def run(document, window, *, transport_response=None):
        nonlocal response_body
        response_body = transport_response
        prompts.clear()
        monkeypatch.setattr(
            "distill.pipeline.analysis.paper.fetch_paper_pdf_text", lambda _: document
        )
        monkeypatch.setattr(
            "distill.pipeline.analysis.paper.resolve_metadata_for_router",
            lambda *args: ProviderMetadata(
                context_window=window, provider_type="local", provider_name="ollama"
            ),
        )
        insights, receipt = analyze_paper(
            _paper(), DistillConfig(distill_output_dir=tmp_path / "library")
        )
        return insights, receipt, list(prompts)

    return run


def _document(caveat_heading):
    return (
        "## Introduction\nA study of adoption periods.\n\n"
        f"## Results\n{_MEASUREMENT}\n\n"
        "## Discussion\nThe result warrants further research.\n\n"
        "## Appendix\n" + "Unrelated apparatus detail. " * 180 + "\n\n"
        f"## {caveat_heading}\n{_CAVEAT}\n"
    )


@pytest.mark.parametrize("heading", ["Erratum", "Population Notes", "Limitations"])
def test_production_selection_reconciles_late_caveats_regardless_of_heading(
    capture_analysis, heading
):
    insights, receipt, prompts = capture_analysis(_document(heading), 1024)
    assert _MEASUREMENT in receipt
    assert _CAVEAT in receipt
    assert "source_mode: chunked_multipass" in insights
    assert len(prompts) >= 3
    evidence_prompt = next(
        prompt for kind, prompt in prompts if kind.endswith("methods_and_evidence")
    )
    assert _MEASUREMENT in evidence_prompt
    # Focused methods still omit this caveat, but source reconciliation must
    # actually receive it. These transport stubs do not judge final prose.
    assert _CAVEAT not in evidence_prompt
    selected_anywhere = any(_CAVEAT in prompt for _, prompt in prompts)
    assert selected_anywhere
    evidence = _input_evidence(insights)
    chunks = chunk_content(receipt, 1024)
    caveat_chunk = next(chunk for chunk in chunks if _CAVEAT in chunk.text)
    assert caveat_chunk.index in evidence["selected_chunk_indices"]
    assert evidence["omitted_chunk_indices"] == []
    assert evidence["prompt_chunk_coverage"] == "all_supplied_chunks"
    assert evidence["semantic_sufficiency"] == "not_assessed"
    assert evidence["document_sha256"] == hashlib.sha256(receipt.encode()).hexdigest()
    for row, (call_type, prompt) in zip(evidence["passes"], prompts, strict=True):
        for index in row["chunk_indices"]:
            if call_type == "paper_source_reconciliation":
                assert f"SOURCE CHUNK {index}:\n" in prompt
            else:
                assert chunks[index].text in prompt


def test_broad_context_control_preserves_the_late_qualification(capture_analysis):
    insights, receipt, prompts = capture_analysis(_document("Erratum"), 32768)
    assert "source_mode: full_pdf" in insights
    assert len(prompts) == 1
    assert receipt in prompts[0][1]
    assert _MEASUREMENT in prompts[0][1]
    assert _CAVEAT in prompts[0][1]
    evidence = _input_evidence(insights)
    assert evidence["prompt_chunk_coverage"] == "all_supplied_chunks"
    assert evidence["selected_chunk_indices"] == [0]
    assert evidence["omitted_chunk_indices"] == []
    assert evidence["workload_tag"] == "site"
    assert evidence["chunks"][0]["sha256"] == hashlib.sha256(receipt.encode()).hexdigest()


def test_multipass_control_preserves_matched_measurement_and_qualification(capture_analysis):
    # Keep the whole paper too long for passthrough while its relevant sections
    # fit each focused pass. Multipass itself is not a quality failure.
    document = (
        _document("Methods and Limitations")
        + "\n\n## Appendix detail\n"
        + "Unrelated apparatus detail. " * 1000
    )
    insights, receipt, prompts = capture_analysis(document, 4096)
    assert "source_mode: chunked_multipass" in insights
    assert estimate_tokens(receipt) >= int(4096 * 0.8)
    assert len(prompts) >= 3
    evidence_prompt = next(
        prompt for kind, prompt in prompts if kind.endswith("methods_and_evidence")
    )
    assert _MEASUREMENT in evidence_prompt
    assert _CAVEAT in evidence_prompt
    evidence = _input_evidence(insights)
    assert evidence["workload_tag"] == "analysis"
    chunks = chunk_content(receipt, 4096)
    caveat_chunk = next(chunk for chunk in chunks if _CAVEAT in chunk.text)
    assert caveat_chunk.index in evidence["selected_chunk_indices"]
    assert caveat_chunk.index not in evidence["omitted_chunk_indices"]


@pytest.mark.parametrize("copies", [1, 16])
def test_reconciliation_recovers_primary_results_crowded_out_by_recaps(capture_analysis, copies):
    # All sections belong to one synthetic paper. This tests within-paper
    # budget pressure, not source-pool deduplication or independent evidence.
    # Repeat count is a stress input, never a source-quality score.
    derivative = (
        "## Results recap\nFixture-authored derivative summary: "
        + "The reported result looks promising. " * 24
        + "\n\n"
    )
    document = (
        "## Introduction\nStudy background.\n\n"
        + derivative * copies
        + f"## Results\n{_MEASUREMENT}\n{_CAVEAT}\n"
        + "Primary measurement protocol. " * 25
        + "\n\n"
        + "## Discussion\nFurther research is needed.\n\n"
        + "## Appendix\n"
        + "Unrelated apparatus detail. " * 180
    )
    insights, receipt, prompts = capture_analysis(document, 1024)
    assert _MEASUREMENT in receipt and _CAVEAT in receipt
    evidence_prompt = next(
        prompt for kind, prompt in prompts if kind.endswith("methods_and_evidence")
    )
    assert "Fixture-authored derivative summary" in evidence_prompt
    assert (_MEASUREMENT in evidence_prompt) is (copies == 1)
    assert (_CAVEAT in evidence_prompt) is (copies == 1)
    assert any(_MEASUREMENT in prompt for _, prompt in prompts)
    assert any(_CAVEAT in prompt for _, prompt in prompts)
    evidence = _input_evidence(insights)
    chunks = chunk_content(receipt, 1024)
    primary = next(chunk for chunk in chunks if _MEASUREMENT in chunk.text)
    assert primary.index in evidence["selected_chunk_indices"]
    assert evidence["omitted_chunk_indices"] == []
    # Keeping the same returned receipt with a broader window restores access.
    _, broad_receipt, broad_prompts = capture_analysis(document, 32768)
    assert broad_receipt == receipt
    assert len(broad_prompts) == 1
    assert _CAVEAT in broad_prompts[0][1]


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_real_token_estimate_routes_at_eighty_percent(capture_analysis, offset):
    # Obtain the actual built receipt, including paper metadata, rather than
    # replacing the token estimator or chunker at the boundary under test.
    document = _document("Erratum")
    _, receipt, _ = capture_analysis(document, 32768)
    tokens = estimate_tokens(receipt)
    window = next(value for value in range(tokens, tokens * 2) if int(value * 0.8) == tokens)
    # Exact four-character padding changes the production estimate by one.
    if offset < 0:
        document = document[:-4]
    elif offset > 0:
        document += "xxxx"
    insights, actual_receipt, prompts = capture_analysis(document, window)
    assert estimate_tokens(actual_receipt) == tokens + offset
    multipass = offset >= 0
    assert ("source_mode: chunked_multipass" in insights) is multipass
    assert (len(prompts) >= 3) if multipass else (len(prompts) == 1)


@pytest.mark.parametrize("window", [1024, 32768])
def test_paper_publication_retains_bound_input_receipt_without_prompt_bulk(
    capture_analysis, tmp_path, window
):
    from distill.commands._paper_artifacts import write_paper_artifacts

    # Exercise the existing source normalizer and quoted heading metadata. The
    # two hashes must distinguish analyzer input from the persisted source body.
    document = _document('Erratum "quoted" \\ detail') + "\n**## Source heading**\nSource detail.\n"
    insights, source, prompts = capture_analysis(document, window)
    internal = _input_evidence(insights)
    config = DistillConfig(distill_output_dir=tmp_path / "published", distill_verify="strict")
    directory = write_paper_artifacts("evidence", _paper(), config, insights, source)
    persisted = find_artifact(directory, "insights").read_text(encoding="utf-8")
    frontmatter = extract_frontmatter(persisted)
    assert "paper_input_evidence" not in frontmatter
    assert "chunk_indices" not in persisted
    receipt_file = directory / frontmatter["paper_input_evidence_file"]
    assert receipt_file.is_file()
    raw = receipt_file.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == frontmatter["paper_input_evidence_sha256"]
    receipt = json.loads(raw)
    assert receipt == {
        **internal,
        "insight_body_sha256": hashlib.sha256(strip_frontmatter(persisted).encode()).hexdigest(),
    }
    published_source = find_artifact(directory, "paper").read_text(encoding="utf-8")
    source_body_digest = hashlib.sha256(strip_frontmatter(published_source).encode()).hexdigest()
    assert receipt["published_receipt_body_sha256"] == source_body_digest
    assert frontmatter["paper_receipt_body_sha256"] == source_body_digest
    assert receipt["document_sha256"] != source_body_digest
    assert receipt["document_sha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert receipt["semantic_sufficiency"] == "not_assessed"
    assert (len(prompts) >= 3) if window == 1024 else (len(prompts) == 1)


def test_late_source_reconciliation_replaces_wrong_summary_before_actual_publication(
    capture_analysis, tmp_path
):
    from distill.commands._paper_artifacts import write_paper_artifacts

    wrong = "AI caused the incident probability to triple."
    unaffected = "The instrument remained calibrated."

    def body(summary):
        return "\n\n".join(
            f"## {heading}\n"
            + (
                summary
                if heading == "Summary"
                else unaffected
                if heading == "Core Contribution"
                else _MEASUREMENT
            )
            for heading in PAPER_CANONICAL_SECTIONS
        )

    prior = body(wrong)
    corrected = body(_MEASUREMENT + " " + _CAVEAT)

    def response(call_type, prompt):
        # A deterministic transport witness, not a semantic model judge. The
        # corrected output is admitted only after the actual caveat reaches a
        # reconciliation request; the earlier metadata/headline cannot do it.
        return (
            corrected if call_type == "paper_source_reconciliation" and _CAVEAT in prompt else prior
        )

    insights, source, prompts = capture_analysis(
        _document("Erratum") + "\n\n## Introduction calibration\n" + unaffected,
        1536,
        transport_response=response,
    )
    assert any(
        kind == "paper_source_reconciliation" and _CAVEAT in prompt for kind, prompt in prompts
    )
    config = DistillConfig(distill_output_dir=tmp_path / "reconciled", distill_verify="strict")
    directory = write_paper_artifacts("evidence", _paper(), config, insights, source)
    published = find_artifact(directory, "insights").read_text(encoding="utf-8")
    assert wrong not in strip_frontmatter(published)
    assert _MEASUREMENT in strip_frontmatter(published)
    assert _CAVEAT in strip_frontmatter(published)
    assert unaffected in strip_frontmatter(published)
    fields = extract_frontmatter(published)
    manifest = json.loads(
        (directory / fields["paper_input_evidence_file"]).read_text(encoding="utf-8")
    )
    assert manifest["prompt_chunk_coverage"] == "all_supplied_chunks"
    assert any(row["section"] == "source reconciliation" for row in manifest["passes"])
