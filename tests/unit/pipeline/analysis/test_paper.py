"""Tests for distill.paper_analysis."""

from unittest.mock import patch

import pytest

from distill.config import DistillConfig
from distill.ingestors.papers.arxiv import PaperRecord
from distill.library.insights import insight_content_sha256
from distill.library.paths import extract_frontmatter, find_artifact, strip_frontmatter
from distill.llm.metadata import ProviderMetadata
from distill.llm.router import LLM_Response, RouterConfig
from distill.pipeline.analysis.chunking import chunk_content, estimate_tokens
from distill.pipeline.analysis.multipass import MultiPassAnalysisResult, PassResult
from distill.pipeline.analysis.paper import analyze_paper, synthesize_papers
from distill.pipeline.costs import CostTracker, TokenUsage


def _fake_llm_call(text: str = "body", model: str = "grok-4.3"):
    def _call(config, workload_tag, prompt, **kwargs):
        return LLM_Response(text=text, input_tokens=10, output_tokens=20, model=model)

    return _call


def _paper() -> PaperRecord:
    return PaperRecord(
        paper_id="2602.12670v1",
        title='Agent "Memory"',
        abstract="A paper about memory systems.",
        authors=["Alice", "Bob"],
        abs_url="https://arxiv.org/abs/2602.12670v1",
    )


def test_analyze_paper_builds_frontmatter(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    tracker = CostTracker()

    with patch("distill.pipeline.analysis.paper.llm_call", _fake_llm_call("paper body")):
        insights, document = analyze_paper(_paper(), config, tracker=tracker)

    assert 'paper_title: "Agent \\"Memory\\""' in insights
    assert "paper_id: 2602.12670v1" in insights
    assert "analyzed_by: grok-4.3" in insights
    assert "source_mode: abstract_only" in insights
    assert insights.rstrip().endswith("paper body")
    assert "## Abstract" in document
    assert len(tracker.entries) == 1
    assert tracker.entries[0].call_type == "paper"


@pytest.mark.parametrize("text", ["", " \n\t"])
def test_empty_single_pass_refuses_but_keeps_successful_call_accounting(
    monkeypatch, tmp_path, text
):
    monkeypatch.setattr("distill.pipeline.analysis.paper.fetch_paper_pdf_text", lambda _: "")
    monkeypatch.setattr(
        "distill.pipeline.analysis.paper.resolve_metadata_for_router",
        lambda *args: ProviderMetadata(
            context_window=10_000, provider_type="cloud", provider_name="xai"
        ),
    )
    tracker = CostTracker()
    response = LLM_Response(text=text, input_tokens=17, output_tokens=2, model="grok-4.6")
    with (
        patch("distill.pipeline.analysis.paper.llm_call", return_value=response) as transport,
        pytest.raises(ValueError, match="analysis is incomplete"),
    ):
        analyze_paper(_paper(), DistillConfig(distill_output_dir=tmp_path / "lib"), tracker=tracker)
    transport.assert_called_once()
    assert len(tracker.entries) == 1
    usage = tracker.entries[0]
    assert usage.call_type == "paper"
    assert usage.model == "grok-4.6"
    assert usage.prompt_tokens == 17
    assert usage.completion_tokens == 2
    assert tracker.total_cost > 0


@pytest.mark.parametrize("model", ["", " \n\t"])
def test_single_pass_missing_response_identity_remains_unknown(monkeypatch, tmp_path, model):
    monkeypatch.setattr("distill.pipeline.analysis.paper.fetch_paper_pdf_text", lambda _: "")
    monkeypatch.setattr(
        "distill.pipeline.analysis.paper.resolve_metadata_for_router",
        lambda *args: ProviderMetadata(
            context_window=10_000, provider_type="cloud", provider_name="xai"
        ),
    )
    with patch("distill.pipeline.analysis.paper.llm_call", _fake_llm_call("Useful body.", model)):
        insights, _ = analyze_paper(_paper(), DistillConfig(distill_output_dir=tmp_path / "lib"))
    metadata = extract_frontmatter(insights)
    assert metadata["analyzed_by"] == "unknown"
    assert metadata["model"] == "unknown"
    assert '"model":"unknown"' in metadata["paper_input_evidence"]


def test_synthesize_papers_skips_unreadable_insight(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    good = config.paper_dir("papers", "Good Paper", "2602.12670")
    bad = config.paper_dir("papers", "Broken Paper", "2602.12671")
    good.mkdir(parents=True, exist_ok=True)
    bad.mkdir(parents=True, exist_ok=True)
    (good / "insights.md").write_text("# Insight", encoding="utf-8")
    (bad / "insights.md").write_bytes(b"\xff\xfe")

    with patch("distill.pipeline.analysis.paper.llm_call", _fake_llm_call("paper synthesis")):
        result = synthesize_papers("papers", config)

    assert result == "paper synthesis"


def test_synthesize_papers_writes_output(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    paper_dir = config.paper_dir("papers", "Agent Memory Systems", "2602.12670")
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "insights.md").write_text("# Insight", encoding="utf-8")

    with patch("distill.pipeline.analysis.paper.llm_call", _fake_llm_call("paper synthesis")):
        result = synthesize_papers("papers", config)

    assert result == "paper synthesis"
    output = find_artifact(config.topic_dir("papers"), "paper_synthesis", identity="papers")
    assert output.name == "papers_Paper_Synthesis.md"
    assert strip_frontmatter(output.read_text(encoding="utf-8")) == "paper synthesis"
    assert 'type: "paper-synthesis"' in output.read_text(encoding="utf-8")


def test_synthesize_papers_writes_verify_sidecar(tmp_path):
    """0.13.0: the synthesis is verified against its own inputs (the per-paper
    insights), with a distinct sidecar identity so the three topic-level
    syntheses can't collide."""
    config = DistillConfig(
        xai_api_key="test-key",
        distill_output_dir=tmp_path / "lib",
        distill_verify="warn",
    )
    paper_dir = config.paper_dir("papers", "Agent Memory Systems", "2602.12670")
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "insights.md").write_text("# Insight\nMRR reached 72.6 here.", encoding="utf-8")

    with patch(
        "distill.pipeline.analysis.paper.llm_call",
        _fake_llm_call("The synthesis claims an MRR of 99.9 nowhere in sources."),
    ):
        result = synthesize_papers("papers", config)

    assert result  # warn mode: flagged but written
    sidecar = config.topic_dir("papers") / "papers_paper_synthesis_Verify.json"
    assert sidecar.exists()
    import json as _json

    data = _json.loads(sidecar.read_text(encoding="utf-8"))
    assert any(c["token"] == "99.9" for c in data["unsupported"])
    output = find_artifact(config.topic_dir("papers"), "paper_synthesis", identity="papers")
    assert data["insight"] == output.name
    assert data["insight_sha256"] == insight_content_sha256(output.read_text(encoding="utf-8"))


def test_synthesize_papers_refreshes_orientation(tmp_path):
    """Paper-only flows must leave the topic agent-visible.

    The dogfood library caught this: topics built by `distill papers` /
    discover's paper branch had a fresh _Paper_Synthesis.md but no
    CLAUDE.md/AGENTS.md and never appeared in the library index.
    """
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    paper_dir = config.paper_dir("papers", "Agent Memory Systems", "2602.12670")
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "insights.md").write_text("# Insight", encoding="utf-8")

    with patch("distill.pipeline.analysis.paper.llm_call", _fake_llm_call("paper synthesis")):
        synthesize_papers("papers", config)

    topic_dir = config.topic_dir("papers")
    assert (topic_dir / "CLAUDE.md").exists()
    assert (topic_dir / "AGENTS.md").exists()
    library_index = config.library_dir / "CLAUDE.md"
    assert library_index.exists()
    assert "`topics/papers/`" in library_index.read_text(encoding="utf-8")


def test_analyze_paper_multipass_keeps_full_receipt(monkeypatch, tmp_path):
    from distill.pipeline.analysis.chunking import Chunk

    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    monkeypatch.setattr(
        "distill.pipeline.analysis.paper.fetch_paper_pdf_text", lambda url: "big pdf text"
    )
    monkeypatch.setattr(
        "distill.pipeline.analysis.paper.build_paper_document",
        lambda paper, pdf_text: "FULL DOCUMENT",
    )
    monkeypatch.setattr("distill.pipeline.analysis.paper.estimate_tokens", lambda text: 900_000)
    monkeypatch.setattr(
        "distill.pipeline.analysis.paper.resolve_metadata_for_router",
        lambda rc, workload: ProviderMetadata(
            context_window=1_000_000,
            provider_type="cloud",
            provider_name="xai",
        ),
    )
    monkeypatch.setattr(
        "distill.pipeline.analysis.paper.chunk_content",
        lambda content, window, reserved_ratio=0.20: [
            Chunk(text="FIRST CHUNK", heading_context="## Methods", index=0, total_chunks=2),
            Chunk(text="SECOND CHUNK", heading_context="## Results", index=1, total_chunks=2),
        ],
    )
    monkeypatch.setattr(
        "distill.pipeline.analysis.paper.multi_pass_analysis",
        lambda *args, **kwargs: MultiPassAnalysisResult(
            passes=[
                PassResult(
                    category="front matter",
                    insights="## Summary\n\nA multipass summary.\n\n## Core Contribution\n\nAdds X.",
                    chunks_used=1,
                    selection_mode="structural",
                ),
                PassResult(
                    category="methods and evidence",
                    insights="## Methods and Evidence\n\nMethods detail.",
                    chunks_used=1,
                    selection_mode="model",
                ),
            ],
            selection_modes="front matter:structural; methods and evidence:model",
        ),
    )

    insights, document = analyze_paper(_paper(), config)

    assert document == "FULL DOCUMENT"
    assert "source_mode: chunked_multipass" in insights
    assert "## Summary" in insights
    assert "A multipass summary." in insights
    assert 'prompt_id: "analysis.paper.v4"' in insights
    assert "chunk_selection_modes: front matter:structural; methods and evidence:model" in insights


@pytest.mark.parametrize(
    ("site_window", "analysis_window", "expected_workload"),
    [(10_000, 1024, "site"), (1024, 10_000, "analysis")],
)
def test_paper_context_belongs_to_the_route_that_receives_the_prompt(
    monkeypatch, tmp_path, site_window, analysis_window, expected_workload
):
    source = ("Evidence protocol details. " * 300).strip()
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    router = RouterConfig(site_model="site-choice", analysis_model="analysis-choice")
    metadata_calls = []
    transport_calls = []

    def metadata_for_route(rc, workload):
        assert rc is router
        metadata_calls.append(workload)
        return ProviderMetadata(
            context_window=site_window if workload == "site" else analysis_window,
            provider_type="cloud",
            provider_name="xai",
        )

    def respond(rc, *, workload_tag, prompt, **kwargs):
        assert rc is router
        transport_calls.append((workload_tag, rc.resolve(workload_tag)[1], prompt))
        return LLM_Response(
            text="## Summary\nActual transport fixture response.",
            input_tokens=1,
            output_tokens=1,
            model="actual-response-model",
        )

    monkeypatch.setattr("distill.pipeline.analysis.paper.fetch_paper_pdf_text", lambda _: source)
    monkeypatch.setattr(
        "distill.pipeline.analysis.paper.resolve_metadata_for_router", metadata_for_route
    )
    monkeypatch.setattr("distill.pipeline.analysis.paper.llm_call", respond)
    monkeypatch.setattr("distill.pipeline.analysis.multipass.call", respond)
    monkeypatch.setattr(
        "distill.pipeline.analysis.chunk_selection.model_available", lambda _: False
    )
    with patch("distill.pipeline.analysis.paper.chunk_content", wraps=chunk_content) as chunker:
        insights, receipt = analyze_paper(_paper(), config, router_config=router)

    assert source in receipt
    assert estimate_tokens(receipt) > int(min(site_window, analysis_window) * 0.8)
    assert estimate_tokens(receipt) < int(max(site_window, analysis_window) * 0.8)
    assert transport_calls
    assert {workload for workload, _, _ in transport_calls} == {expected_workload}
    assert {model for _, model, _ in transport_calls} == {f"{expected_workload}-choice"}
    assert "analyzed_by: actual-response-model\n" in insights
    if expected_workload == "site":
        assert metadata_calls == ["site"]
        assert len(transport_calls) == 1
        assert receipt in transport_calls[0][2]
        chunker.assert_not_called()
    else:
        assert metadata_calls == ["site", "analysis"]
        assert len(transport_calls) == 3
        assert chunker.call_args.args == (receipt, analysis_window)
        assert all(receipt in prompt for _, _, prompt in transport_calls)


@pytest.mark.parametrize("blank_response", [None, "", " \n\t"])
def test_empty_multipass_refuses_instead_of_analyzing_only_the_lead(
    monkeypatch, tmp_path, blank_response
):
    monkeypatch.setattr(
        "distill.pipeline.analysis.paper.fetch_paper_pdf_text",
        lambda _: "Evidence protocol details. " * 300,
    )
    monkeypatch.setattr(
        "distill.pipeline.analysis.paper.resolve_metadata_for_router",
        lambda *args: ProviderMetadata(
            context_window=1024, provider_type="local", provider_name="ollama"
        ),
    )
    passes = (
        []
        if blank_response is None
        else [PassResult(category="front matter", insights=blank_response, chunks_used=1)]
    )
    monkeypatch.setattr(
        "distill.pipeline.analysis.paper.multi_pass_analysis",
        lambda *args, **kwargs: MultiPassAnalysisResult(passes=passes),
    )
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    with patch("distill.pipeline.analysis.paper.llm_call") as single_pass:
        with pytest.raises(ValueError, match=r"no nonempty sections.*analysis is incomplete"):
            analyze_paper(_paper(), config)
        single_pass.assert_not_called()


@pytest.mark.parametrize(
    ("models", "expected"),
    [
        (("actual-fallback-model",), "actual-fallback-model"),
        (("actual-first", "actual-first", "actual-second"), "actual-first, actual-second"),
        (("actual-first", "", " \t"), "actual-first, unknown"),
        (("",), "unknown"),
    ],
)
@pytest.mark.parametrize("prior_usage", [False, True])
def test_multipass_model_provenance_uses_only_current_response_identities(
    monkeypatch, tmp_path, models, expected, prior_usage
):
    monkeypatch.setattr(
        "distill.pipeline.analysis.paper.fetch_paper_pdf_text",
        lambda _: "Evidence protocol details. " * 300,
    )
    monkeypatch.setattr(
        "distill.pipeline.analysis.paper.resolve_metadata_for_router",
        lambda *args: ProviderMetadata(
            context_window=1024, provider_type="local", provider_name="ollama"
        ),
    )
    passes = [
        PassResult(
            category="front matter",
            insights=f"## Summary\nCurrent contribution {index}.",
            chunks_used=1,
            model=model,
        )
        for index, model in enumerate(models)
    ]
    passes.append(
        PassResult(category="front matter", insights=" \n", chunks_used=1, model="empty-response")
    )
    monkeypatch.setattr(
        "distill.pipeline.analysis.paper.multi_pass_analysis",
        lambda *args, **kwargs: MultiPassAnalysisResult(passes=passes),
    )
    tracker = None
    if prior_usage:
        tracker = CostTracker()
        tracker.record(
            TokenUsage.from_response(
                LLM_Response(
                    text="Earlier paper.",
                    input_tokens=1,
                    output_tokens=1,
                    model="stale-prior-paper-model",
                ),
                call_type="paper",
            )
        )
    insights, _ = analyze_paper(
        _paper(),
        DistillConfig(distill_output_dir=tmp_path / "lib"),
        tracker=tracker,
        router_config=RouterConfig(analysis_model="configured-unconfirmed-model"),
    )
    assert f"analyzed_by: {expected}\n" in insights
    assert f"model: {expected}\n" in insights
    assert "configured-unconfirmed-model" not in insights
    assert "stale-prior-paper-model" not in insights
    assert "empty-response" not in extract_frontmatter(insights)["analyzed_by"]


def test_analyze_paper_without_tracker_does_not_crash(monkeypatch, tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    monkeypatch.setattr("distill.pipeline.analysis.paper.fetch_paper_pdf_text", lambda url: "")

    with patch("distill.pipeline.analysis.paper.llm_call", _fake_llm_call("body")):
        insights, _ = analyze_paper(_paper(), config)

    assert "source_mode: abstract_only" in insights


def test_synthesize_papers_missing_dir_returns_empty(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    assert synthesize_papers("never-ingested", config) == ""


@pytest.mark.parametrize("legacy_filename", [False, True])
@pytest.mark.parametrize("include_current", [False, True])
def test_paper_synthesis_uses_only_insights_bound_to_the_current_capture(
    tmp_path, legacy_filename, include_current
):
    from distill.library.insights import receipt_body_sha256
    from distill.library.paths import dump_frontmatter

    config = DistillConfig(distill_output_dir=tmp_path / "lib", distill_verify="off")
    candidates = [("stale", False)]
    if include_current:
        candidates.append(("current", True))
    for identity, current in candidates:
        paper_dir = config.paper_dir("receipt-bound", identity, identity)
        paper_dir.mkdir(parents=True)
        old_source = f"The {identity} source before refresh."
        source = old_source if current else "The replacement source changes the earlier finding."
        find_artifact(paper_dir, "paper").write_text(
            dump_frontmatter({"receipt_sha256": receipt_body_sha256(source)}) + "\n\n" + source,
            encoding="utf-8",
        )
        insight_path = (
            paper_dir / "insights.md" if legacy_filename else find_artifact(paper_dir, "insights")
        )
        insight_path.write_text(
            dump_frontmatter(
                {"paper_id": identity, "paper_receipt_body_sha256": receipt_body_sha256(old_source)}
            )
            + f"\n\n{identity.upper()}_EVIDENCE_MARKER",
            encoding="utf-8",
        )
    with patch(
        "distill.pipeline.analysis.paper.llm_call", side_effect=_fake_llm_call("Bound synthesis")
    ) as transport:
        result = synthesize_papers("receipt-bound", config)
    if include_current:
        assert result == "Bound synthesis"
        transport.assert_called_once()
        prompt = transport.call_args.kwargs["prompt"]
        assert "CURRENT_EVIDENCE_MARKER" in prompt
        assert "STALE_EVIDENCE_MARKER" not in prompt
    else:
        assert result == ""
        transport.assert_not_called()


def test_synthesize_papers_skips_nondir_and_missing_insights(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    papers_dir = config.papers_dir("papers")
    papers_dir.mkdir(parents=True, exist_ok=True)
    (papers_dir / "stray.txt").write_text("not a paper dir", encoding="utf-8")
    (papers_dir / "emptypaper").mkdir()  # a dir with no insights artifact

    assert synthesize_papers("papers", config) == ""


def test_synthesize_papers_records_spend(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    tracker = CostTracker()
    paper_dir = config.paper_dir("papers", "Agent Memory Systems", "2602.12670")
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "insights.md").write_text("# Insight", encoding="utf-8")

    with patch("distill.pipeline.analysis.paper.llm_call", _fake_llm_call("paper synthesis")):
        synthesize_papers("papers", config, tracker=tracker)

    assert len(tracker.entries) == 1
    assert tracker.entries[0].call_type == "paper_synthesis"


def test_synthesize_papers_strict_verify_refusal_does_not_write(monkeypatch, tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    paper_dir = config.paper_dir("papers", "Agent Memory Systems", "2602.12670")
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "insights.md").write_text("# Insight", encoding="utf-8")
    monkeypatch.setattr(
        "distill.pipeline.verify.run_synthesis_verify", lambda *args, **kwargs: True
    )

    with patch("distill.pipeline.analysis.paper.llm_call", _fake_llm_call("paper synthesis")):
        result = synthesize_papers("papers", config)

    assert result == ""
    output = find_artifact(config.topic_dir("papers"), "paper_synthesis", identity="papers")
    assert not output.exists()


def test_synthesize_papers_tolerates_orientation_refresh_failure(monkeypatch, tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    paper_dir = config.paper_dir("papers", "Agent Memory Systems", "2602.12670")
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "insights.md").write_text("# Insight", encoding="utf-8")

    def _boom(*args, **kwargs):
        raise RuntimeError("orientation refresh failed")

    monkeypatch.setattr("distill.library.claude_md.refresh_for_topic", _boom)

    with patch("distill.pipeline.analysis.paper.llm_call", _fake_llm_call("paper synthesis")):
        result = synthesize_papers("papers", config)

    # The synthesis still returns and is written despite the refresh failure.
    assert result == "paper synthesis"
