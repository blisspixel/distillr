"""Tests for distill.analysis."""

from types import SimpleNamespace

import pytest

from distill.analysis import (
    _call_grok,
    analyze_scan,
    analyze_short,
    analyze_video,
    generate_channel_context,
    generate_watch_instructions,
)
from distill.config import DistillConfig
from distill.costs import CostTracker


class FakeCompletions:
    def __init__(self, responses):
        self._responses = list(responses)

    def create(self, **kwargs):
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=FakeCompletions(responses))


def _response(content: str, prompt_tokens: int = 10, completion_tokens: int = 20):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


def test_call_grok_tracks_usage():
    tracker = CostTracker()
    client = FakeClient([_response("analysis")])

    result = _call_grok(
        client, "prompt", model="grok-4-1-fast-reasoning", tracker=tracker, call_type="pass1"
    )

    assert result == "analysis"
    assert len(tracker.entries) == 1
    assert tracker.entries[0].call_type == "pass1"


def test_call_grok_retries_then_succeeds(monkeypatch):
    waits = []
    monkeypatch.setattr("distill.analysis.time.sleep", lambda seconds: waits.append(seconds))
    client = FakeClient([Exception("rate limit"), _response("recovered")])

    result = _call_grok(client, "prompt", model="grok-4-1-fast-reasoning", retries=1)

    assert result == "recovered"
    assert waits == [5]


def test_call_grok_raises_after_final_failure(monkeypatch):
    monkeypatch.setattr("distill.analysis.time.sleep", lambda seconds: None)
    client = FakeClient([Exception("boom"), Exception("boom")])

    with pytest.raises(Exception, match="boom"):
        _call_grok(client, "prompt", model="grok-4-1-fast-reasoning", retries=1)


def test_analyze_video_builds_frontmatter(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    tracker = CostTracker()
    responses = iter(["pass1 body", "pass2 body"])
    monkeypatch.setattr("distill.analysis._get_client", lambda config: object())
    monkeypatch.setattr(
        "distill.analysis._call_grok",
        lambda client, prompt, model="", tracker=None, call_type="", max_tokens=8192, retries=2: (
            next(responses)
        ),
    )

    result = analyze_video(
        'A "quoted" title', "20260312", "Creator", "transcript", config, tracker=tracker
    )

    assert 'video_title: "A \\"quoted\\" title"' in result
    assert "channel: Creator" in result
    assert result.rstrip().endswith("pass2 body")


def test_analyze_short_marks_content_type(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    monkeypatch.setattr("distill.analysis._get_client", lambda config: object())
    monkeypatch.setattr(
        "distill.analysis._call_grok",
        lambda client, prompt, model="", tracker=None, call_type="", max_tokens=8192, retries=2: (
            "short body"
        ),
    )

    result = analyze_short("Short title", "20260312", "Creator", "transcript", config)

    assert "content_type: short" in result
    assert result.rstrip().endswith("short body")


def test_generate_channel_context_delegates_to_grok(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    monkeypatch.setattr("distill.analysis._get_client", lambda config: object())
    monkeypatch.setattr(
        "distill.analysis._call_grok",
        lambda client, prompt, model="", tracker=None, call_type="", max_tokens=8192, retries=2: (
            "channel context"
        ),
    )

    result = generate_channel_context("Creator", ["One", "Two"], config)

    assert result == "channel context"


def test_analyze_scan_marks_scan_mode(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    monkeypatch.setattr("distill.analysis._get_client", lambda config: object())
    monkeypatch.setattr(
        "distill.analysis._call_grok",
        lambda client, prompt, model="", tracker=None, call_type="", max_tokens=8192, retries=2: (
            "scan body"
        ),
    )

    result = analyze_scan("Scan title", "20260312", "Creator", "transcript", config)

    assert "analysis_mode: scan" in result
    assert result.rstrip().endswith("scan body")


def test_generate_watch_instructions_delegates_to_grok(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    monkeypatch.setattr("distill.analysis._get_client", lambda config: object())
    monkeypatch.setattr(
        "distill.analysis._call_grok",
        lambda client, prompt, model="", tracker=None, call_type="", max_tokens=8192, retries=2: (
            "watch instructions"
        ),
    )

    result = generate_watch_instructions("Creator", ["One", "Two"], config)

    assert result == "watch instructions"


def test_call_grok_returns_empty_when_no_choices():
    client = FakeClient([SimpleNamespace(choices=[], usage=None)])

    assert _call_grok(client, "prompt", model="grok-4-1-fast-reasoning") == ""
