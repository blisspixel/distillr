"""Tests for the MCP ask tool wrapper."""

from __future__ import annotations

import json
from pathlib import Path

from distill.config import DistillConfig
from distill.pipeline.ask import AskResult

_FAKE_COST = {"total_cost": 0, "total_input_tokens": 0, "total_output_tokens": 0, "calls": 0}


def _config(tmp_path) -> DistillConfig:
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    config.library_dir.mkdir(parents=True, exist_ok=True)
    return config


def test_ask_no_model_returns_error(tmp_path, monkeypatch) -> None:
    from distill.mcp import server as _server
    from distill.mcp.tools.ask import ask

    config = _config(tmp_path)
    monkeypatch.setattr(_server, "_config", lambda: config)
    monkeypatch.setattr("distill.mcp.tools.ask.model_available", lambda workload: False)

    result = json.loads(ask("t", "q"))

    assert result["status"] == "error"
    assert "model" in result["error"].lower()


def test_ask_missing_topic_returns_error(tmp_path, monkeypatch) -> None:
    from distill.mcp import server as _server
    from distill.mcp.tools.ask import ask

    config = _config(tmp_path)
    monkeypatch.setattr(_server, "_config", lambda: config)
    monkeypatch.setattr("distill.mcp.tools.ask.model_available", lambda workload: True)

    result = json.loads(ask("missing", "q"))

    assert result["status"] == "error"
    assert "not found" in result["error"]


def test_ask_rejects_oversized_question_before_model_check(tmp_path, monkeypatch) -> None:
    from distill.mcp import server as _server
    from distill.mcp.tools.ask import ask

    config = _config(tmp_path)
    monkeypatch.setattr(_server, "_config", lambda: config)

    def unexpected_model_check(*_args, **_kwargs):
        raise AssertionError("oversized question reached model preflight")

    monkeypatch.setattr("distill.mcp.tools.ask.model_available", unexpected_model_check)

    result = json.loads(ask("t", "q" * 4_097))

    assert result["status"] == "error"
    assert "4096" in result["error"]


def test_ask_no_coverage_returns_status(tmp_path, monkeypatch) -> None:
    from distill.mcp import server as _server
    from distill.mcp.tools.ask import ask

    config = _config(tmp_path)
    config.topic_dir("t").mkdir(parents=True)
    monkeypatch.setattr(_server, "_config", lambda: config)
    monkeypatch.setattr("distill.mcp.tools.ask.model_available", lambda workload: True)
    monkeypatch.setattr(
        "distill.pipeline.ask.ask_corpus",
        lambda question, *, topic, config, save, tracker: AskResult(
            question=question,
            answer_path=None,
            answer_text="",
            no_coverage=True,
        ),
    )

    result = json.loads(ask("t", "q"))

    assert result["status"] == "no_coverage"
    assert "no matching artifacts" in result["message"]


def test_ask_refused_answer_returns_status(tmp_path, monkeypatch) -> None:
    from distill.mcp import server as _server
    from distill.mcp.tools.ask import ask

    config = _config(tmp_path)
    config.topic_dir("t").mkdir(parents=True)
    monkeypatch.setattr(_server, "_config", lambda: config)
    monkeypatch.setattr("distill.mcp.tools.ask.model_available", lambda workload: True)
    monkeypatch.setattr("distill.mcp.server._cost_summary", lambda tracker: _FAKE_COST)
    monkeypatch.setattr(
        "distill.pipeline.ask.ask_corpus",
        lambda question, *, topic, config, save, tracker: AskResult(
            question=question,
            answer_path=None,
            answer_text="Claim that cites a fabricated receipt [fabricated_Insights].",
            sources=[],
            answer_refused_reason="answer cites unknown source(s): fabricated_Insights",
        ),
    )

    result = json.loads(ask("t", "q"))

    assert result["status"] == "refused"
    assert "unknown source" in result["error"]
    assert result["answer"] == "Claim that cites a fabricated receipt [fabricated_Insights]."
    assert result["sources"] == []
    assert result["answer_path"] == ""
    assert result["cost"] == _FAKE_COST


def test_ask_happy_path_returns_answer_payload(tmp_path, monkeypatch) -> None:
    from distill.mcp import server as _server
    from distill.mcp.tools.ask import ask

    config = _config(tmp_path)
    config.topic_dir("t").mkdir(parents=True)
    answer_path = config.topic_dir("t") / "answers" / "q_Answer.md"
    monkeypatch.setattr(_server, "_config", lambda: config)
    monkeypatch.setattr("distill.mcp.tools.ask.model_available", lambda workload: True)
    monkeypatch.setattr("distill.mcp.server._cost_summary", lambda tracker: _FAKE_COST)
    monkeypatch.setattr(
        "distill.pipeline.ask.ask_corpus",
        lambda question, *, topic, config, save, tracker: AskResult(
            question=question,
            answer_path=answer_path,
            answer_text="Grounded answer [source].",
            sources=["source"],
        ),
    )

    result = json.loads(ask("t", "q"))

    assert result["answer"] == "Grounded answer [source]."
    assert result["sources"] == ["source"]
    assert Path(result["answer_path"]) == Path("topics/t/answers/q_Answer.md")
    assert result["cost"] == _FAKE_COST
