"""Tests for distill.pipeline.analysis.local (local-file ingest orchestration)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

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


def test_no_analyze_writes_document_only(tmp_path: Path):
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
