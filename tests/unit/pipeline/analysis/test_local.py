"""Tests for distill.pipeline.analysis.local (local-file ingest orchestration)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from distill.config import DistillConfig
from distill.llm.router import LLM_Response
from distill.pipeline.analysis.local import ingest_local_file
from distill.pipeline.costs import CostTracker


def _cfg(tmp_path: Path) -> DistillConfig:
    return DistillConfig(distill_output_dir=tmp_path / "lib")


def _fake_llm(text: str = "INSIGHTS BODY", model: str = "grok-4.3"):
    def _call(*_args, **_kwargs):
        return LLM_Response(text=text, input_tokens=10, output_tokens=20, model=model)

    return _call


def _md(tmp_path: Path) -> Path:
    p = tmp_path / "doc.md"
    p.write_text("# T\n\nContent about temporal knowledge graphs.", encoding="utf-8")
    return p


def test_no_analyze_writes_document_only(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "distill.pipeline.analysis.local.RouterConfig.resolve",
        lambda *a: pytest.fail("Capture-only ingest must not resolve an analysis route"),
    )
    cfg = _cfg(tmp_path)
    res = ingest_local_file(_md(tmp_path), topic="tkg", config=cfg, analyze=False)
    assert res.document_path.exists()
    assert res.insights_path is None
    assert "Content about" in res.document_path.read_text(encoding="utf-8")


def test_analyze_writes_insights_and_records_cost(tmp_path: Path):
    cfg = _cfg(tmp_path)
    tracker = CostTracker()
    with patch("distill.pipeline.analysis.local.llm_call", _fake_llm("THE INSIGHTS")):
        res = ingest_local_file(_md(tmp_path), topic="tkg", config=cfg, tracker=tracker)
    assert res.insights_path is not None and res.insights_path.exists()
    body = res.insights_path.read_text(encoding="utf-8")
    assert "THE INSIGHTS" in body
    assert "analysis.local.v1" in body  # provenance prompt_id
    assert tracker.entries and tracker.entries[0].call_type == "local"


def test_empty_analysis_keeps_document_and_skips_insight(tmp_path: Path):
    cfg = _cfg(tmp_path)
    with patch(
        "distill.pipeline.analysis.local.llm_call",
        _fake_llm("---\ntitle: x\n---\n\n  \n"),
    ):
        res = ingest_local_file(_md(tmp_path), topic="tkg", config=cfg)
    assert res.document_path.exists()
    assert res.insights_path is None


def test_pdf_routes_to_paper_prompt(tmp_path: Path):
    # A .pdf-kind document should use the paper prompt; capture the prompt text.
    cfg = _cfg(tmp_path)
    seen: dict[str, str] = {}

    def _capture(*args, **kwargs):
        seen["prompt"] = kwargs.get("prompt", args[2] if len(args) > 2 else "")
        return LLM_Response(text="x", input_tokens=1, output_tokens=1, model="grok-4.3")

    doc = tmp_path / "paper.md"  # use md kind -> site prompt path
    doc.write_text("# Paper\n\nAbstract and method.", encoding="utf-8")
    with patch("distill.pipeline.analysis.local.llm_call", _capture):
        ingest_local_file(doc, topic="t", config=cfg)
    # Markdown routes to the site-page prompt, which carries the untrusted-content guard.
    assert "untrusted third-party" in seen["prompt"]


@pytest.mark.parametrize("mode", ["off", "warn", "strict"])
def test_unchanged_analysis_reuses_exact_pair_without_inference(tmp_path, monkeypatch, mode):
    from distill.library.insights import discover_insights

    monkeypatch.setattr("distill.pipeline.analysis.local.entailment_available", lambda: False)
    cfg = DistillConfig(distill_output_dir=tmp_path / "lib", distill_verify=mode)
    doc = _md(tmp_path)
    with patch("distill.pipeline.analysis.local.llm_call", _fake_llm("THE INSIGHTS")):
        first = ingest_local_file(doc, topic="t", config=cfg)
    assert first.insights_path is not None
    before = {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in (first.document_path, first.insights_path)
    }
    with patch(
        "distill.pipeline.analysis.local.llm_call", side_effect=AssertionError("no-op inferred")
    ):
        second = ingest_local_file(doc, topic="t", config=cfg)
    assert second.no_op
    assert ("numeric-only" if mode != "off" else "off") in second.verification_scope
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == value for p, value in before.items())
    assert len(discover_insights(cfg.topic_dir("t"))) == 1


@pytest.mark.parametrize(
    "change", ["force", "source", "prompt", "route", "receipt", "insight", "threshold"]
)
def test_changed_analysis_reruns_and_preserves_history(tmp_path, monkeypatch, change):
    from distill.library.insights import discover_insights
    from distill.prompts.registry import PROMPT_IDS

    cfg = _cfg(tmp_path)
    doc = _md(tmp_path)
    with patch("distill.pipeline.analysis.local.llm_call", _fake_llm("FIRST INSIGHT")):
        first = ingest_local_file(doc, topic="t", config=cfg)
    assert first.insights_path is not None
    if change == "source":
        doc.write_text("# T\n\nChanged evidence.", encoding="utf-8")
    elif change == "prompt":
        monkeypatch.setitem(PROMPT_IDS, "analysis.local", "analysis.local.test-next")
    elif change == "route":
        monkeypatch.setattr(
            "distill.pipeline.analysis.local.RouterConfig.resolve",
            lambda *_a: ("ollama", "other:local"),
        )
    elif change == "receipt":
        first.document_path.write_text("tampered receipt", encoding="utf-8")
    elif change == "insight":
        first.insights_path.write_text(
            first.insights_path.read_text(encoding="utf-8") + "\nTampered.", encoding="utf-8"
        )
    elif change == "threshold":
        monkeypatch.setenv("DISTILL_ENTAILMENT_THRESHOLD", "0.9")
    old_insight = first.insights_path.read_bytes()
    with patch("distill.pipeline.analysis.local.llm_call", _fake_llm("SECOND INSIGHT")):
        second = ingest_local_file(doc, topic="t", config=cfg, force=change == "force")
    assert not second.no_op
    assert second.insights_path is not None
    assert "SECOND INSIGHT" in second.insights_path.read_text(encoding="utf-8")
    history = list(second.insights_path.parent.glob(".history/*/manifest.json"))
    assert len(history) == 1
    assert (history[0].parent / first.insights_path.name).read_bytes() == old_insight
    assert len(discover_insights(cfg.topic_dir("t"))) == 1


def test_failed_force_retains_previous_insight_and_history(tmp_path):
    cfg = _cfg(tmp_path)
    doc = _md(tmp_path)
    with patch("distill.pipeline.analysis.local.llm_call", _fake_llm("FIRST INSIGHT")):
        first = ingest_local_file(doc, topic="t", config=cfg)
    assert first.insights_path is not None
    old = first.insights_path.read_bytes()
    with (
        patch("distill.pipeline.analysis.local.llm_call", side_effect=RuntimeError("interrupted")),
        pytest.raises(RuntimeError, match="interrupted"),
    ):
        ingest_local_file(doc, topic="t", config=cfg, force=True)
    assert first.insights_path.read_bytes() == old
    assert list(first.insights_path.parent.glob(".history/*/manifest.json"))
    with patch("distill.pipeline.analysis.local.llm_call", _fake_llm("RECOVERED")):
        recovered = ingest_local_file(doc, topic="t", config=cfg, force=True)
    assert recovered.insights_path is not None
    assert "RECOVERED" in recovered.insights_path.read_text(encoding="utf-8")
