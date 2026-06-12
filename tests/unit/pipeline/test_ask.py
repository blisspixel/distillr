"""Tests for distill.pipeline.ask (grounded answering + verify-gated promotion)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from distill.config import DistillConfig
from distill.llm.router import LLM_Response
from distill.pipeline import ask as ask_mod


@pytest.fixture
def config(tmp_path):
    return DistillConfig(xai_api_key="t", distill_output_dir=tmp_path / "library")


def _seed_corpus(config, topic: str = "t") -> None:
    d = config.topic_dir(topic) / "papers" / "checker-paper"
    d.mkdir(parents=True, exist_ok=True)
    (d / "checker_paper_Insights.md").write_text(
        '---\nsource_id: "p1"\n---\n\n## Core\n'
        "- HHEM reaches 0.878 ROC-AUC on grounding verification benchmarks.\n"
        "- The checker runs on CPU with 110 million parameters.\n",
        encoding="utf-8",
    )


def _llm(monkeypatch, text: str):
    monkeypatch.setattr(
        ask_mod,
        "llm_call",
        lambda rc, **kwargs: LLM_Response(
            text=text, input_tokens=10, output_tokens=10, model="grok-4.3"
        ),
    )


GROUNDED = (
    "HHEM reaches 0.878 ROC-AUC and runs on CPU [checker_paper_Insights].\n\n"
    "Caveats: single-source coverage."
)


class TestAsk:
    def test_answer_artifact_with_citations_and_sidecar(self, config, monkeypatch):
        _seed_corpus(config)
        _llm(monkeypatch, GROUNDED)

        result = ask_mod.ask_corpus("which checker?", topic="t", config=config)

        assert result.answer_path is not None and result.answer_path.exists()
        body = result.answer_path.read_text(encoding="utf-8")
        assert "[[checker_paper_Insights]]" in body
        assert 'prompt_id: "ask.v1"' in body
        assert result.sources == ["checker_paper_Insights"]
        sidecars = list(result.answer_path.parent.glob("*_Verify.json"))
        assert len(sidecars) == 1
        assert json.loads(sidecars[0].read_text(encoding="utf-8"))["unsupported"] == []

    def test_no_coverage_topic(self, config):
        result = ask_mod.ask_corpus("anything?", topic="empty", config=config)
        assert result.no_coverage
        assert result.answer_path is None

    def test_save_promotes_clean_answer(self, config, monkeypatch):
        _seed_corpus(config)
        _llm(monkeypatch, GROUNDED)

        result = ask_mod.ask_corpus("which checker?", topic="t", config=config, save=True)

        assert result.saved_insight_path is not None
        insight = result.saved_insight_path.read_text(encoding="utf-8")
        assert 'synthesis_scope: "derived-answer"' in insight
        assert 'source: "distill-answer"' in insight
        # The promoted insight carries its own verification record.
        assert list(result.saved_insight_path.parent.glob("*_Verify.json"))
        # And the corpus walkers will see it (it lives outside dot/derived dirs).
        from distill.library.insights import discover_insights

        stems = [Path(r.artifact_path).stem for r in discover_insights(config.topic_dir("t"))]
        assert any("which-checker" in s or "which_checker" in s for s in stems)

    def test_save_refused_on_unsupported_claim(self, config, monkeypatch):
        _seed_corpus(config)
        _llm(
            monkeypatch,
            "HHEM reaches 0.999 ROC-AUC [checker_paper_Insights].",
        )

        result = ask_mod.ask_corpus("which checker?", topic="t", config=config, save=True)

        assert result.saved_insight_path is None
        assert "refused" in result.save_refused_reason
        # The Answer.md + sidecar still exist so the refusal is inspectable.
        assert result.answer_path is not None and result.answer_path.exists()
        sidecar = json.loads(
            next(result.answer_path.parent.glob("*_Verify.json")).read_text(encoding="utf-8")
        )
        assert sidecar["unsupported"][0]["token"] == "0.999"

    def test_save_refused_on_no_coverage_answer(self, config, monkeypatch):
        """Retrieval can hit lexically while the model correctly answers that the
        corpus doesn't actually cover the question -- that answer must not promote."""
        _seed_corpus(config)
        _llm(monkeypatch, "The corpus does not cover this question.")

        result = ask_mod.ask_corpus("which checker?", topic="t", config=config, save=True)

        assert result.saved_insight_path is None
        assert "does not cover" in result.save_refused_reason


def test_ask_command_wiring(config, monkeypatch):
    from typer.testing import CliRunner

    from distill import _cli_impl, cli

    _seed_corpus(config)
    monkeypatch.setattr(_cli_impl, "get_config", lambda: config)
    _llm(monkeypatch, GROUNDED)

    result = CliRunner().invoke(cli.app, ["ask", "which checker?", "--topic", "t"])

    assert result.exit_code == 0, result.output
    assert "0.878" in result.output
    assert "Answer" in result.output
