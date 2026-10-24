# pyright: strict
"""Local think control stays boolean and does not invent effort levels."""

from __future__ import annotations

import pytest

from distill.llm.local_reasoning import (
    LocalReasoningConfigError,
    confirm_effective,
    local_think_override,
    plan_ollama_think,
)
from distill.llm.providers._ollama_metadata import build_chat_payload


def test_unset_local_think_keeps_the_current_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISTILL_ANALYSIS_LOCAL_THINK", raising=False)
    assert local_think_override("ollama", "analysis") is None


def test_explicit_false_is_boolean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISTILL_PAPER_LOCAL_THINK", "off")
    assert local_think_override("ollama", "paper") is False


def test_effort_label_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISTILL_ANALYSIS_LOCAL_THINK", "medium")
    with pytest.raises(LocalReasoningConfigError, match="true or false"):
        local_think_override("ollama", "analysis")


def test_level_strings_do_not_change_the_sent_control() -> None:
    payload = build_chat_payload(
        "gemma4:e2b",
        "ping",
        max_tokens=16,
        num_ctx=2048,
        temperature=0,
        supports_thinking=True,
        reasoning_effort="high",
    )
    assert payload["think"] is True
    plan = plan_ollama_think(
        explicit_think=None,
        reasoning_effort="high",
        supports_thinking=True,
        name_suggests_thinking=True,
        structured_json=False,
    )
    assert plan.sent == "think=true"
    assert plan.status == "effort_unsupported"
    assert "not an Ollama control" in plan.support


def test_explicit_think_on_a_non_thinking_model_fails() -> None:
    with pytest.raises(LocalReasoningConfigError, match="no verified thinking"):
        build_chat_payload(
            "llama3:8b",
            "ping",
            max_tokens=16,
            num_ctx=2048,
            temperature=None,
            supports_thinking=False,
            local_think=True,
        )


def test_structured_json_withholds_requested_thinking() -> None:
    payload = build_chat_payload(
        "qwen3.5:27b",
        "return json",
        max_tokens=16,
        num_ctx=2048,
        temperature=None,
        call_type="search_rerank",
        supports_thinking=True,
        local_think=True,
    )
    assert payload["format"] == "json"
    assert payload["think"] is False
    plan = plan_ollama_think(
        explicit_think=True,
        reasoning_effort=None,
        supports_thinking=True,
        name_suggests_thinking=True,
        structured_json=True,
    )
    assert plan.status == "withheld_for_json"
    assert confirm_effective(plan, trace_present=True) == "unknown"


def test_trace_presence_confirms_only_a_boolean_think_request() -> None:
    plan = plan_ollama_think(
        explicit_think=True,
        reasoning_effort=None,
        supports_thinking=True,
        name_suggests_thinking=True,
        structured_json=False,
    )
    assert confirm_effective(plan, trace_present=True) == "trace_present"
    assert confirm_effective(plan, trace_present=False) == "unknown"


def test_explicit_false_omits_think_when_the_model_cannot_think() -> None:
    payload = build_chat_payload(
        "llama3:8b",
        "ping",
        max_tokens=16,
        num_ctx=2048,
        temperature=None,
        supports_thinking=False,
        local_think=False,
    )
    assert "think" not in payload


def test_name_guess_stays_unknown_until_a_trace_exists() -> None:
    plan = plan_ollama_think(
        explicit_think=True,
        reasoning_effort=None,
        supports_thinking=None,
        name_suggests_thinking=True,
        structured_json=False,
    )
    assert plan.status == "name_guess"
    assert plan.sent == "think=true"
    assert confirm_effective(plan, trace_present=False) == "unknown"
    assert confirm_effective(plan, trace_present=True) == "trace_present"


def test_rejection_retry_omits_think() -> None:
    plan = plan_ollama_think(
        explicit_think=True,
        reasoning_effort=None,
        supports_thinking=False,
        name_suggests_thinking=True,
        structured_json=False,
        degraded=True,
    )
    assert plan.think is None
    assert plan.effective == "rejected_retried_without_think"
