"""Tests for distill.analysis."""

from unittest.mock import patch

from distill.config import DistillConfig
from distill.llm.router import LLM_Response
from distill.pipeline.analysis.video import (
    analyze_scan,
    analyze_short,
    analyze_video,
    generate_channel_context,
    generate_watch_instructions,
)
from distill.pipeline.costs import CostTracker


def _fake_llm_call(text: str = "body", model: str = "grok-4.3"):
    """Return a mock llm_call that returns a fixed LLM_Response."""

    def _call(config, workload_tag, prompt, **kwargs):
        return LLM_Response(
            text=text,
            input_tokens=10,
            output_tokens=20,
            model=model,
        )

    return _call


def _fake_llm_call_sequence(texts: list[str], model: str = "grok-4.3"):
    """Return a mock llm_call that returns different texts in sequence."""
    it = iter(texts)

    def _call(config, workload_tag, prompt, **kwargs):
        return LLM_Response(
            text=next(it),
            input_tokens=10,
            output_tokens=20,
            model=model,
        )

    return _call


def test_analyze_video_builds_frontmatter(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    tracker = CostTracker()

    with patch(
        "distill.pipeline.analysis.video.llm_call",
        _fake_llm_call_sequence(["pass1 body", "pass2 body"]),
    ):
        result = analyze_video(
            'A "quoted" title', "20260312", "Creator", "transcript", config, tracker=tracker
        )

    assert 'video_title: "A \\"quoted\\" title"' in result
    assert "channel: Creator" in result
    assert result.rstrip().endswith("pass2 body")
    # Tracker should have 2 entries (pass1 + pass2)
    assert len(tracker.entries) == 2
    assert tracker.entries[0].call_type == "pass1"
    assert tracker.entries[1].call_type == "pass2"


def test_analyze_short_marks_content_type(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")

    with patch("distill.pipeline.analysis.video.llm_call", _fake_llm_call("short body")):
        result = analyze_short("Short title", "20260312", "Creator", "transcript", config)

    assert "content_type: short" in result
    assert result.rstrip().endswith("short body")


def test_generate_channel_context_delegates_to_router(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")

    with patch("distill.pipeline.analysis.video.llm_call", _fake_llm_call("channel context")):
        result = generate_channel_context("Creator", ["One", "Two"], config)

    assert result == "channel context"


def test_analyze_scan_marks_scan_mode(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")

    with patch("distill.pipeline.analysis.video.llm_call", _fake_llm_call("scan body")):
        result = analyze_scan("Scan title", "20260312", "Creator", "transcript", config)

    assert "analysis_mode: scan" in result
    assert result.rstrip().endswith("scan body")


def test_generate_watch_instructions_delegates_to_router(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")

    with patch("distill.pipeline.analysis.video.llm_call", _fake_llm_call("watch instructions")):
        result = generate_watch_instructions("Creator", ["One", "Two"], config)

    assert result == "watch instructions"


def test_analyze_video_tracker_records_tokens(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    tracker = CostTracker()

    with patch("distill.pipeline.analysis.video.llm_call", _fake_llm_call_sequence(["p1", "p2"])):
        analyze_video("Title", "20260312", "Creator", "transcript", config, tracker=tracker)

    assert tracker.total_input_tokens == 20  # 10 + 10
    assert tracker.total_output_tokens == 40  # 20 + 20
