"""Tests for distill.synthesis."""

from types import SimpleNamespace

from distill.config import DistillConfig
from distill.costs import CostTracker
from distill.synthesis import _call_with_retry, synthesize_channel, synthesize_topic


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


def test_call_with_retry_tracks_usage():
    tracker = CostTracker()
    client = FakeClient([_response("synthesis")])

    result = _call_with_retry(client, "prompt", tracker=tracker, call_type="topic_synthesis")

    assert result == "synthesis"
    assert len(tracker.entries) == 1
    assert tracker.entries[0].call_type == "topic_synthesis"


def test_synthesize_channel_returns_empty_without_videos(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")

    result = synthesize_channel("ai", "Creator", config)

    assert result == ""


def test_synthesize_channel_returns_empty_without_insights(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    videos_dir = config.channel_dir("ai", "Creator") / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)

    result = synthesize_channel("ai", "Creator", config)

    assert result == ""


def test_synthesize_channel_saves_output(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    channel_dir = config.channel_dir("ai", "Creator")
    (channel_dir / "videos" / "video-1").mkdir(parents=True, exist_ok=True)
    (channel_dir / "videos" / "video-1" / "insights.md").write_text("# Insight", encoding="utf-8")
    (channel_dir / "channel_context.md").write_text("# Context", encoding="utf-8")
    monkeypatch.setattr("distill.synthesis.OpenAI", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        "distill.synthesis._call_with_retry",
        lambda *args, **kwargs: "channel synthesis",
    )

    result = synthesize_channel("ai", "Creator", config)

    assert result == "channel synthesis"
    assert (channel_dir / "synthesis.md").read_text(encoding="utf-8") == "channel synthesis"


def test_synthesize_topic_skips_with_single_channel(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    channel_dir = config.channel_dir("ai", "CreatorOne")
    channel_dir.mkdir(parents=True, exist_ok=True)
    (channel_dir / "synthesis.md").write_text("# Synth", encoding="utf-8")

    result = synthesize_topic("ai", config)

    assert result == ""


def test_synthesize_topic_saves_output(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    for name in ["CreatorOne", "CreatorTwo"]:
        channel_dir = config.channel_dir("ai", name)
        channel_dir.mkdir(parents=True, exist_ok=True)
        (channel_dir / "synthesis.md").write_text(f"# {name}", encoding="utf-8")
    monkeypatch.setattr("distill.synthesis.OpenAI", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        "distill.synthesis._call_with_retry", lambda *args, **kwargs: "topic synthesis"
    )

    result = synthesize_topic("ai", config)

    assert result == "topic synthesis"
    assert (config.topic_dir("ai") / "topic_synthesis.md").read_text(
        encoding="utf-8"
    ) == "topic synthesis"


def test_call_with_retry_raises_after_final_failure(monkeypatch):
    monkeypatch.setattr("distill.synthesis.time.sleep", lambda seconds: None)
    client = FakeClient([Exception("boom"), Exception("boom")])

    import pytest

    with pytest.raises(Exception, match="boom"):
        _call_with_retry(client, "prompt", retries=1)


def test_synthesize_topic_handles_api_exception(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    for name in ["CreatorOne", "CreatorTwo"]:
        channel_dir = config.channel_dir("ai", name)
        channel_dir.mkdir(parents=True, exist_ok=True)
        (channel_dir / "synthesis.md").write_text(f"# {name}", encoding="utf-8")
    monkeypatch.setattr("distill.synthesis.OpenAI", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        "distill.synthesis._call_with_retry",
        lambda *args, **kwargs: (_ for _ in ()).throw(Exception("boom")),
    )

    result = synthesize_topic("ai", config)

    assert result == ""


def test_call_with_retry_returns_empty_when_no_choices():
    client = FakeClient([SimpleNamespace(choices=[], usage=None)])

    assert _call_with_retry(client, "prompt") == ""


def test_synthesize_channel_handles_api_exception(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    channel_dir = config.channel_dir("ai", "Creator")
    (channel_dir / "videos" / "video-1").mkdir(parents=True, exist_ok=True)
    (channel_dir / "videos" / "video-1" / "insights.md").write_text("# Insight", encoding="utf-8")
    monkeypatch.setattr("distill.synthesis.OpenAI", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        "distill.synthesis._call_with_retry",
        lambda *args, **kwargs: (_ for _ in ()).throw(Exception("boom")),
    )

    assert synthesize_channel("ai", "Creator", config) == ""


def test_synthesize_topic_returns_empty_without_channels_dir(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")

    assert synthesize_topic("ai", config) == ""
