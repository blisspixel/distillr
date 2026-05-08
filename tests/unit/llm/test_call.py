"""Unit tests for the LLMCall dataclass."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from distill.llm.call import LLMCall


class TestLLMCallConstruction:
    """Test LLMCall construction with all fields and defaults."""

    def test_construction_with_required_fields(self) -> None:
        call = LLMCall(model="grok-4.3", prompt_hash="sha256:abc123")
        assert call.model == "grok-4.3"
        assert call.prompt_hash == "sha256:abc123"

    def test_default_values(self) -> None:
        call = LLMCall(model="grok-4.3", prompt_hash="sha256:abc123")
        assert call.prompt_text == ""
        assert call.temperature == 0.0
        assert call.max_tokens == 0
        assert call.response_text == ""
        assert call.response_tokens == 0
        assert call.latency_ms == 0
        assert call.error_message == ""
        assert call.attempt == 1
        # timestamp should be a valid ISO format string
        datetime.fromisoformat(call.timestamp)

    def test_construction_with_all_fields(self) -> None:
        ts = "2025-06-15T10:30:00+00:00"
        call = LLMCall(
            model="grok-4.3",
            prompt_hash="sha256:deadbeef",
            prompt_text="Summarize this article.",
            temperature=0.3,
            max_tokens=16384,
            response_text="## Executive Summary\n...",
            response_tokens=4200,
            latency_ms=3450,
            error_message="",
            timestamp=ts,
            attempt=2,
        )
        assert call.model == "grok-4.3"
        assert call.prompt_hash == "sha256:deadbeef"
        assert call.prompt_text == "Summarize this article."
        assert call.temperature == 0.3
        assert call.max_tokens == 16384
        assert call.response_text == "## Executive Summary\n..."
        assert call.response_tokens == 4200
        assert call.latency_ms == 3450
        assert call.error_message == ""
        assert call.timestamp == ts
        assert call.attempt == 2

    def test_timestamp_default_is_utc_iso(self) -> None:
        before = datetime.now(timezone.utc)
        call = LLMCall(model="test", prompt_hash="h")
        after = datetime.now(timezone.utc)
        ts = datetime.fromisoformat(call.timestamp)
        assert before <= ts <= after


class TestLLMCallSucceeded:
    """Test the succeeded property."""

    def test_succeeded_when_no_error(self) -> None:
        call = LLMCall(model="grok-4.3", prompt_hash="h", error_message="")
        assert call.succeeded is True

    def test_not_succeeded_when_error(self) -> None:
        call = LLMCall(model="grok-4.3", prompt_hash="h", error_message="timeout")
        assert call.succeeded is False

    def test_not_succeeded_with_detailed_error(self) -> None:
        call = LLMCall(
            model="grok-4.3",
            prompt_hash="h",
            error_message="HTTP 429: Rate limit exceeded",
        )
        assert call.succeeded is False


class TestLLMCallToDict:
    """Test to_dict() serialization for JSONL output."""

    def test_to_dict_returns_all_fields(self) -> None:
        call = LLMCall(
            model="grok-4.3",
            prompt_hash="sha256:abc",
            prompt_text="hello",
            temperature=0.7,
            max_tokens=1024,
            response_text="world",
            response_tokens=100,
            latency_ms=500,
            error_message="",
            timestamp="2025-01-01T00:00:00+00:00",
            attempt=1,
        )
        d = call.to_dict()
        assert d["model"] == "grok-4.3"
        assert d["prompt_hash"] == "sha256:abc"
        assert d["prompt_text"] == "hello"
        assert d["temperature"] == 0.7
        assert d["max_tokens"] == 1024
        assert d["response_text"] == "world"
        assert d["response_tokens"] == 100
        assert d["latency_ms"] == 500
        assert d["error_message"] == ""
        assert d["timestamp"] == "2025-01-01T00:00:00+00:00"
        assert d["attempt"] == 1

    def test_to_dict_is_json_serializable(self) -> None:
        call = LLMCall(model="test-model", prompt_hash="sha256:xyz")
        d = call.to_dict()
        # Should not raise
        serialized = json.dumps(d)
        assert isinstance(serialized, str)

    def test_to_dict_with_error(self) -> None:
        call = LLMCall(
            model="grok-4.3",
            prompt_hash="sha256:err",
            error_message="Connection refused",
            attempt=3,
        )
        d = call.to_dict()
        assert d["error_message"] == "Connection refused"
        assert d["attempt"] == 3
