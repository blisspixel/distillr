"""Unit tests for retry_with_backoff integration in the accordion section-writing loop.

Tests verify:
- Retry-then-success resets the consecutive failure counter
- 3 consecutive failures stops the loop
- LLMCall logging on failure and retry-success
- Mock LLM calls to simulate transient/permanent failures
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from distill.llm.router import LLM_Response

# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def mock_config():
    """Create a mock DistillConfig."""
    config = MagicMock()
    config.xai_model_for.return_value = "grok-4.3"
    return config


@pytest.fixture
def section_defs():
    """Create a list of section definitions for testing."""
    return [
        {"id": "intro", "title": "Introduction", "voice": "analytical"},
        {"id": "analysis", "title": "Analysis", "voice": "analytical"},
        {"id": "conclusion", "title": "Conclusion", "voice": "analytical"},
        {"id": "appendix", "title": "Appendix", "voice": "reference"},
        {"id": "extra", "title": "Extra", "voice": "analytical"},
    ]


def _make_response(text: str = "Section content here") -> LLM_Response:
    """Create a mock LLM_Response."""
    return LLM_Response(
        text=text,
        input_tokens=100,
        output_tokens=50,
        model="grok-4.3",
    )


def _configure_router(mock_router_config: MagicMock) -> None:
    mock_router_config.return_value.resolve.return_value = ("xai", "grok-4.3")


# ─── Test: Retry-then-success resets counter ─────────────────────────


@patch("distill.pipeline.report.accordion.time.sleep", return_value=None)
@patch("distill.pipeline.report.accordion.RouterConfig")
@patch("distill.pipeline.report.accordion.llm_call")
@patch("distill.pipeline.report.accordion.section_prompt", return_value="test prompt")
def test_retry_then_success_resets_counter(
    mock_section_prompt,
    mock_llm_call,
    mock_router_config,
    mock_sleep,
    mock_config,
    section_defs,
):
    """When a section fails then succeeds on retry, consecutive_failures resets to 0."""
    from distill.pipeline.report.accordion import _write_sections

    _configure_router(mock_router_config)

    # Section 1: fails once then succeeds (retry success)
    # Section 2: succeeds immediately
    # Section 3: fails permanently (all retries exhausted)
    # Section 4: succeeds immediately
    # => consecutive_failures should be 1 after section 3, not 2
    #    because section 1's retry-success reset the counter

    call_counts = {"intro": 0, "analysis": 0, "conclusion": 0, "appendix": 0}

    def side_effect(*args, **kwargs):
        call_type = kwargs.get("call_type", "")
        if "Introduction" in call_type:
            call_counts["intro"] += 1
            if call_counts["intro"] == 1:
                raise RuntimeError("Transient error")
            return _make_response("Intro content")
        elif "Analysis" in call_type:
            return _make_response("Analysis content")
        elif "Conclusion" in call_type:
            raise RuntimeError("Permanent failure")
        elif "Appendix" in call_type:
            return _make_response("Appendix content")
        return _make_response("Default content")

    mock_llm_call.side_effect = side_effect

    result = _write_sections(
        topic="test-topic",
        config=mock_config,
        dossier="test dossier",
        scope="topic",
        channel_name=None,
        tagged_materials={},
        active_sections=section_defs[:4],
    )

    # Intro succeeded (after retry), Analysis succeeded, Conclusion failed, Appendix succeeded
    section_ids = [s["id"] for s in result]
    assert "intro" in section_ids
    assert "analysis" in section_ids
    assert "appendix" in section_ids
    assert "conclusion" not in section_ids


@patch("distill.pipeline.report.accordion.time.sleep", return_value=None)
@patch("distill.pipeline.report.accordion.RouterConfig")
@patch("distill.pipeline.report.accordion.llm_call")
@patch("distill.pipeline.report.accordion.section_prompt", return_value="test prompt")
def test_3_consecutive_failures_stops_loop(
    mock_section_prompt,
    mock_llm_call,
    mock_router_config,
    mock_sleep,
    mock_config,
    section_defs,
):
    """When 3 sections fail consecutively (after retries exhausted), the loop stops."""
    from distill.pipeline.report.accordion import _write_sections

    _configure_router(mock_router_config)

    # All calls fail
    mock_llm_call.side_effect = RuntimeError("API unavailable")

    result = _write_sections(
        topic="test-topic",
        config=mock_config,
        dossier="test dossier",
        scope="topic",
        channel_name=None,
        tagged_materials={},
        active_sections=section_defs,
    )

    # No sections written
    assert result == []
    # The loop should have stopped after 3 consecutive failures
    # Each section gets max_retries+1=4 attempts, but only 3 sections attempted
    # (loop breaks after 3rd consecutive failure)
    # 3 sections * 4 attempts each = 12 calls
    assert mock_llm_call.call_count == 12  # 3 sections * (1 initial + 3 retries)


@patch("distill.pipeline.report.accordion.time.sleep", return_value=None)
@patch("distill.pipeline.report.accordion.RouterConfig")
@patch("distill.pipeline.report.accordion.llm_call")
@patch("distill.pipeline.report.accordion.section_prompt", return_value="test prompt")
def test_success_after_failure_prevents_circuit_break(
    mock_section_prompt,
    mock_llm_call,
    mock_router_config,
    mock_sleep,
    mock_config,
    section_defs,
):
    """A success between failures prevents the 3-consecutive-failure circuit breaker."""
    from distill.pipeline.report.accordion import _write_sections

    _configure_router(mock_router_config)

    call_sequence = {
        "Introduction": "fail",  # fails all retries -> consecutive=1
        "Analysis": "succeed",  # succeeds -> consecutive=0
        "Conclusion": "fail",  # fails all retries -> consecutive=1
        "Appendix": "fail",  # fails all retries -> consecutive=2
        "Extra": "fail",  # fails all retries -> consecutive=3 -> STOP
    }

    def side_effect(*args, **kwargs):
        call_type = kwargs.get("call_type", "")
        for title, behavior in call_sequence.items():
            if title[:30] in call_type:
                if behavior == "fail":
                    raise RuntimeError(f"{title} failed")
                return _make_response(f"{title} content")
        return _make_response("Default")

    mock_llm_call.side_effect = side_effect

    result = _write_sections(
        topic="test-topic",
        config=mock_config,
        dossier="test dossier",
        scope="topic",
        channel_name=None,
        tagged_materials={},
        active_sections=section_defs,
    )

    # Only Analysis succeeded
    assert len(result) == 1
    assert result[0]["id"] == "analysis"


# ─── Test: LLMCall logging ───────────────────────────────────────────


@patch("distill.pipeline.report.accordion.time.sleep", return_value=None)
@patch("distill.pipeline.report.accordion.RouterConfig")
@patch("distill.pipeline.report.accordion.llm_call")
@patch("distill.pipeline.report.accordion.section_prompt", return_value="test prompt")
def test_llmcall_logged_on_failure(
    mock_section_prompt,
    mock_llm_call,
    mock_router_config,
    mock_sleep,
    mock_config,
    section_defs,
    caplog,
):
    """LLMCall records are logged when a section fails after all retries."""
    from distill.pipeline.report.accordion import _write_sections

    _configure_router(mock_router_config)

    mock_llm_call.side_effect = RuntimeError("API timeout")

    with caplog.at_level(logging.WARNING, logger="distill.pipeline.report.accordion"):
        _write_sections(
            topic="test-topic",
            config=mock_config,
            dossier="test dossier",
            scope="topic",
            channel_name=None,
            tagged_materials={},
            active_sections=section_defs[:1],  # Only one section
        )

    # Check that warning logs were emitted for retry attempts
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) >= 1
    # Each retry attempt should log a warning with llm_call extra
    for record in warning_records:
        assert hasattr(record, "llm_call")
        llm_call_data = record.llm_call
        assert "error_message" in llm_call_data
        assert llm_call_data["error_message"] == "API timeout"
        assert llm_call_data["model"] == "grok-4.3"


@patch("distill.pipeline.report.accordion.time.sleep", return_value=None)
@patch("distill.pipeline.report.accordion.RouterConfig")
@patch("distill.pipeline.report.accordion.llm_call")
@patch("distill.pipeline.report.accordion.section_prompt", return_value="test prompt")
def test_llmcall_logged_on_final_failure(
    mock_section_prompt,
    mock_llm_call,
    mock_router_config,
    mock_sleep,
    mock_config,
    section_defs,
    caplog,
):
    """An ERROR-level LLMCall record is logged when all retries are exhausted."""
    from distill.pipeline.report.accordion import _write_sections

    _configure_router(mock_router_config)

    mock_llm_call.side_effect = RuntimeError("Permanent failure")

    with caplog.at_level(logging.ERROR, logger="distill.pipeline.report.accordion"):
        _write_sections(
            topic="test-topic",
            config=mock_config,
            dossier="test dossier",
            scope="topic",
            channel_name=None,
            tagged_materials={},
            active_sections=section_defs[:1],
        )

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1
    record = error_records[0]
    assert hasattr(record, "llm_call")
    assert record.llm_call["error_message"] == "Permanent failure"
    assert record.llm_call["attempt"] >= 1


@patch("distill.pipeline.report.accordion.time.sleep", return_value=None)
@patch("distill.pipeline.report.accordion.RouterConfig")
@patch("distill.pipeline.report.accordion.llm_call")
@patch("distill.pipeline.report.accordion.section_prompt", return_value="test prompt")
def test_llmcall_logged_on_retry_success(
    mock_section_prompt,
    mock_llm_call,
    mock_router_config,
    mock_sleep,
    mock_config,
    section_defs,
    caplog,
):
    """When a call succeeds after retries, an INFO-level LLMCall is logged with attempt > 1."""
    from distill.pipeline.report.accordion import _write_sections

    _configure_router(mock_router_config)

    call_count = {"n": 0}

    def side_effect(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] <= 2:
            raise RuntimeError("Transient error")
        return _make_response("Success after retries")

    mock_llm_call.side_effect = side_effect

    with caplog.at_level(logging.INFO, logger="distill.pipeline.report.accordion"):
        result = _write_sections(
            topic="test-topic",
            config=mock_config,
            dossier="test dossier",
            scope="topic",
            channel_name=None,
            tagged_materials={},
            active_sections=section_defs[:1],
        )

    # Section should have been written successfully
    assert len(result) == 1

    # Check INFO log for retry-success
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info_records) >= 1
    success_record = info_records[0]
    assert hasattr(success_record, "llm_call")
    assert success_record.llm_call["attempt"] > 1
    assert success_record.llm_call["error_message"] == ""


# ─── Test: Empty content treated as failure ──────────────────────────


@patch("distill.pipeline.report.accordion.time.sleep", return_value=None)
@patch("distill.pipeline.report.accordion.RouterConfig")
@patch("distill.pipeline.report.accordion.llm_call")
@patch("distill.pipeline.report.accordion.section_prompt", return_value="test prompt")
def test_empty_response_counts_as_failure(
    mock_section_prompt,
    mock_llm_call,
    mock_router_config,
    mock_sleep,
    mock_config,
    section_defs,
):
    """An LLM call that returns empty text counts as a failure for the circuit breaker."""
    from distill.pipeline.report.accordion import _write_sections

    _configure_router(mock_router_config)

    # Return empty text (not an exception, but empty content)
    mock_llm_call.return_value = _make_response("")

    result = _write_sections(
        topic="test-topic",
        config=mock_config,
        dossier="test dossier",
        scope="topic",
        channel_name=None,
        tagged_materials={},
        active_sections=section_defs[:3],
    )

    # All sections return empty -> 3 consecutive failures -> loop stops
    assert result == []
