"""Tests for distill.synthesize module."""

from unittest.mock import patch

import pytest

from distill.config import DistillConfig
from distill.llm.router import LLM_Response
from distill.pipeline.costs import CostTracker
from distill.pipeline.report.synthesize import compose_synthesis_prompt, run_synthesis


@pytest.fixture(autouse=True)
def _model_available(monkeypatch):
    # The gate asks the router now (cloud key OR local provider), not
    # config.xai_api_key. Configure a keyless local provider so the real helper
    # returns True -- env-isolated (ollama needs no key). The no-model test
    # overrides the provider.
    monkeypatch.setenv("DISTILL_PROVIDER", "ollama")


def _fake_llm_call(text: str = "body", model: str = "grok-4.3"):
    def _call(config, workload_tag, prompt, **kwargs):
        return LLM_Response(text=text, input_tokens=10, output_tokens=20, model=model)

    return _call


def test_compose_synthesis_prompt_includes_context_and_sources():
    prompt = compose_synthesis_prompt("Focus on mechanisms", [("paper-1", "details here")])

    assert "Focus on mechanisms" in prompt
    assert "=== SOURCE: paper-1 ===" in prompt
    assert "=== END OF CORPUS ===" in prompt


def test_run_synthesis_returns_none_when_no_model_available(tmp_path, monkeypatch):
    # No usable model for the workload -> clean abort, not a crash. 'anthropic' is
    # configured-but-not-implemented, so the router reports no model regardless of
    # any ambient cloud key (deterministic, no env coupling).
    monkeypatch.setenv("DISTILL_PROVIDER", "anthropic")
    no_key = DistillConfig(distill_output_dir=tmp_path / "lib")
    assert run_synthesis(["ai"], "ctx", "demo", no_key) is None


def test_run_synthesis_handles_empty_corpus(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    with patch("distill.pipeline.report.synthesize.gather_topic_files", return_value=[]):
        assert run_synthesis(["ai"], "ctx", "demo", config) is None


def test_run_synthesis_handles_empty_response(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    with (
        patch(
            "distill.pipeline.report.synthesize.gather_topic_files", return_value=[("doc", "body")]
        ),
        patch("distill.pipeline.report.synthesize.llm_call", _fake_llm_call("")),
    ):
        assert run_synthesis(["ai"], "ctx", "demo", config) is None


def test_run_synthesis_success(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    tracker = CostTracker()
    with (
        patch(
            "distill.pipeline.report.synthesize.gather_topic_files", return_value=[("doc", "body")]
        ),
        patch("distill.pipeline.report.synthesize.llm_call", _fake_llm_call("final synthesis")),
    ):
        result = run_synthesis(["ai"], "ctx", "demo", config, tracker=tracker)

    assert result is not None
    assert result.read_text(encoding="utf-8") == "final synthesis"
    assert len(tracker.entries) == 1
    assert tracker.entries[0].call_type == "synthesis"
