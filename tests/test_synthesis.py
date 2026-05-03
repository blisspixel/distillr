"""Tests for distill.synthesis."""

from unittest.mock import patch

from distill.artifacts import find_artifact, strip_frontmatter
from distill.config import DistillConfig
from distill.costs import CostTracker
from distill.llm.router import LLM_Response
from distill.synthesis import synthesize_channel, synthesize_topic


def _fake_llm_call(text: str = "body", model: str = "grok-4.3"):
    """Return a mock llm_call that returns a fixed LLM_Response."""

    def _call(config, workload_tag, prompt, **kwargs):
        return LLM_Response(text=text, input_tokens=10, output_tokens=20, model=model)

    return _call


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


def test_synthesize_channel_saves_output(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    channel_dir = config.channel_dir("ai", "Creator")
    (channel_dir / "videos" / "video-1").mkdir(parents=True, exist_ok=True)
    (channel_dir / "videos" / "video-1" / "insights.md").write_text("# Insight", encoding="utf-8")
    (channel_dir / "channel_context.md").write_text("# Context", encoding="utf-8")

    with patch("distill.synthesis.llm_call", _fake_llm_call("channel synthesis")):
        result = synthesize_channel("ai", "Creator", config)

    assert result == "channel synthesis"
    output = find_artifact(channel_dir, "synthesis", identity="ai_Creator")
    assert output.name == "ai_Creator_Synthesis.md"
    assert strip_frontmatter(output.read_text(encoding="utf-8")) == "channel synthesis"


def test_synthesize_topic_skips_with_single_channel(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    channel_dir = config.channel_dir("ai", "CreatorOne")
    channel_dir.mkdir(parents=True, exist_ok=True)
    (channel_dir / "synthesis.md").write_text("# Synth", encoding="utf-8")

    result = synthesize_topic("ai", config)

    assert result == ""


def test_synthesize_topic_saves_output(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    for name in ["CreatorOne", "CreatorTwo"]:
        channel_dir = config.channel_dir("ai", name)
        channel_dir.mkdir(parents=True, exist_ok=True)
        (channel_dir / "synthesis.md").write_text(f"# {name}", encoding="utf-8")

    with patch("distill.synthesis.llm_call", _fake_llm_call("topic synthesis")):
        result = synthesize_topic("ai", config)

    assert result == "topic synthesis"
    output = find_artifact(config.topic_dir("ai"), "topic_synthesis", identity="ai")
    assert output.name == "ai_Topic_Synthesis.md"
    assert strip_frontmatter(output.read_text(encoding="utf-8")) == "topic synthesis"


def test_synthesize_topic_handles_api_exception(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    for name in ["CreatorOne", "CreatorTwo"]:
        channel_dir = config.channel_dir("ai", name)
        channel_dir.mkdir(parents=True, exist_ok=True)
        (channel_dir / "synthesis.md").write_text(f"# {name}", encoding="utf-8")

    def _raise(*args, **kwargs):
        raise Exception("boom")

    with patch("distill.synthesis.llm_call", _raise):
        result = synthesize_topic("ai", config)

    assert result == ""


def test_synthesize_channel_handles_api_exception(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    channel_dir = config.channel_dir("ai", "Creator")
    (channel_dir / "videos" / "video-1").mkdir(parents=True, exist_ok=True)
    (channel_dir / "videos" / "video-1" / "insights.md").write_text("# Insight", encoding="utf-8")

    def _raise(*args, **kwargs):
        raise Exception("boom")

    with patch("distill.synthesis.llm_call", _raise):
        assert synthesize_channel("ai", "Creator", config) == ""


def test_synthesize_topic_returns_empty_without_channels_dir(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")

    assert synthesize_topic("ai", config) == ""


def test_synthesize_channel_records_tracker(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    tracker = CostTracker()
    channel_dir = config.channel_dir("ai", "Creator")
    (channel_dir / "videos" / "video-1").mkdir(parents=True, exist_ok=True)
    (channel_dir / "videos" / "video-1" / "insights.md").write_text("# Insight", encoding="utf-8")

    with patch("distill.synthesis.llm_call", _fake_llm_call("synthesis")):
        synthesize_channel("ai", "Creator", config, tracker=tracker)

    assert len(tracker.entries) == 1
    assert tracker.entries[0].call_type == "channel_synthesis"
