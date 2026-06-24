"""Tests for distill.synthesis."""

import json
from unittest.mock import patch

from distill.config import DistillConfig
from distill.library.paths import find_artifact, strip_frontmatter
from distill.llm.router import LLM_Response
from distill.pipeline.costs import CostTracker
from distill.pipeline.synthesis.topic import synthesize_channel, synthesize_topic


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
    vdir = channel_dir / "videos" / "video-1"
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "insights.md").write_text("# Insight", encoding="utf-8")
    (channel_dir / "channel_context.md").write_text("# Context", encoding="utf-8")
    # metadata to hit json/dict branch in _video_link_header
    (vdir / "metadata.json").write_text(
        '{"title": "My Video", "video_id": "vid1"}', encoding="utf-8"
    )

    with patch("distill.pipeline.synthesis.topic.llm_call", _fake_llm_call("channel synthesis")):
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

    with patch("distill.pipeline.synthesis.topic.llm_call", _fake_llm_call("topic synthesis")):
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

    with patch("distill.pipeline.synthesis.topic.llm_call", _raise):
        result = synthesize_topic("ai", config)

    assert result == ""


def test_synthesize_channel_handles_api_exception(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    channel_dir = config.channel_dir("ai", "Creator")
    (channel_dir / "videos" / "video-1").mkdir(parents=True, exist_ok=True)
    (channel_dir / "videos" / "video-1" / "insights.md").write_text("# Insight", encoding="utf-8")

    def _raise(*args, **kwargs):
        raise Exception("boom")

    with patch("distill.pipeline.synthesis.topic.llm_call", _raise):
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

    with patch("distill.pipeline.synthesis.topic.llm_call", _fake_llm_call("synthesis")):
        synthesize_channel("ai", "Creator", config, tracker=tracker)

    assert len(tracker.entries) == 1
    assert tracker.entries[0].call_type == "channel_synthesis"


def test_synthesize_channel_writes_verify_sidecar(tmp_path):
    """0.13.1: channel synthesis is verified against its per-video insights."""
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    channel_dir = config.channel_dir("ai", "Creator")
    (channel_dir / "videos" / "v1").mkdir(parents=True, exist_ok=True)
    (channel_dir / "videos" / "v1" / "insights.md").write_text(
        "# Insight\nThe reported figure was 50.", encoding="utf-8"
    )

    with patch(
        "distill.pipeline.synthesis.topic.llm_call",
        _fake_llm_call("Synthesis claims 91.7, found in no source."),
    ):
        result = synthesize_channel("ai", "Creator", config)

    assert result  # warn mode writes anyway
    sidecar = channel_dir / "ai_Creator_Verify.json"
    assert sidecar.exists()


def test_synthesize_channel_strict_refuses_and_writes_sidecar(tmp_path):
    """Covers verify strict refuse path in synthesize_channel."""
    config = DistillConfig(
        xai_api_key="test-key", distill_output_dir=tmp_path / "lib", distill_verify="strict"
    )
    channel_dir = config.channel_dir("ai", "Creator")
    (channel_dir / "videos" / "v1").mkdir(parents=True, exist_ok=True)
    (channel_dir / "videos" / "v1" / "insights.md").write_text(
        "# Insight\nThe reported figure was 50.", encoding="utf-8"
    )

    with patch(
        "distill.pipeline.synthesis.topic.llm_call",
        _fake_llm_call("Synthesis claims 91.7, found in no source."),
    ):
        result = synthesize_channel("ai", "Creator", config)

    assert result == ""
    # synthesis not written
    synth_path = find_artifact(channel_dir, "synthesis", identity="ai_Creator")
    assert (
        not synth_path.exists() or strip_frontmatter(synth_path.read_text(encoding="utf-8")) == ""
    )
    # sidecar written
    sidecar = channel_dir / "ai_Creator_Verify.json"
    assert sidecar.exists()
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert any(c["token"] == "91.7" for c in data["unsupported"])


def test_synthesize_topic_writes_verify_sidecar(tmp_path):
    """0.13.1: topic synthesis is verified against its channel syntheses, under a
    distinct sidecar identity so the three topic-level syntheses can't collide."""
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    for name in ["CreatorOne", "CreatorTwo"]:
        channel_dir = config.channel_dir("ai", name)
        channel_dir.mkdir(parents=True, exist_ok=True)
        (channel_dir / "synthesis.md").write_text("Baseline of 40 here.", encoding="utf-8")

    with patch(
        "distill.pipeline.synthesis.topic.llm_call",
        _fake_llm_call("Topic synthesis asserts 88.8, unsupported."),
    ):
        result = synthesize_topic("ai", config)

    assert result
    sidecar = config.topic_dir("ai") / "ai_topic_synthesis_Verify.json"
    assert sidecar.exists()
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert any(c["token"] == "88.8" for c in data["unsupported"])


def test_synthesize_topic_strict_refuses_flagged_write(tmp_path):
    """strict mode refuses the write and keeps any prior synthesis in place."""
    config = DistillConfig(
        xai_api_key="test-key", distill_output_dir=tmp_path / "lib", distill_verify="strict"
    )
    for name in ["CreatorOne", "CreatorTwo"]:
        channel_dir = config.channel_dir("ai", name)
        channel_dir.mkdir(parents=True, exist_ok=True)
        (channel_dir / "synthesis.md").write_text("No numbers worth claiming.", encoding="utf-8")

    with patch(
        "distill.pipeline.synthesis.topic.llm_call",
        _fake_llm_call("A synthesis with an invented 77.7 metric."),
    ):
        result = synthesize_topic("ai", config)

    assert result == ""
    assert not find_artifact(config.topic_dir("ai"), "topic_synthesis", identity="ai").exists()
