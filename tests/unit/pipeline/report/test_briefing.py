"""Tests for distill.briefing."""

from unittest.mock import patch

from distill.config import DistillConfig
from distill.library.paths import find_artifact, strip_frontmatter
from distill.llm.router import LLM_Response
from distill.pipeline.costs import CostTracker
from distill.pipeline.report.briefing import generate_topic_brief


def _fake_llm_call(text: str = "body", model: str = "grok-4.3"):
    def _call(config, workload_tag, prompt, **kwargs):
        return LLM_Response(text=text, input_tokens=120, output_tokens=80, model=model)

    return _call


def test_generate_topic_brief_returns_none_without_inputs(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")

    result = generate_topic_brief("fabric", config)

    assert result is None


def test_generate_topic_brief_writes_brief_and_tracks_usage(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    topic_dir = config.topic_dir("fabric")
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "topic_synthesis.md").write_text("# Synthesis", encoding="utf-8")

    for index in range(7):
        insight_dir = topic_dir / "channels" / f"Creator{index // 3}" / "videos" / f"video-{index}"
        insight_dir.mkdir(parents=True, exist_ok=True)
        (insight_dir / "insights.md").write_text(f"# Insight {index}", encoding="utf-8")

    tracker = CostTracker()

    with patch("distill.pipeline.report.briefing.llm_call", _fake_llm_call("# Brief")):
        result = generate_topic_brief("fabric", config, tracker=tracker)

    assert result == find_artifact(topic_dir, "brief", identity="fabric")
    assert result.name == "fabric_Brief.md"
    assert strip_frontmatter(result.read_text(encoding="utf-8")) == "# Brief"
    assert len(tracker.entries) == 1
    assert tracker.total_input_tokens == 120
    assert tracker.total_output_tokens == 80
    assert tracker.entries[0].call_type == "topic_brief"


def test_generate_topic_brief_uses_video_metadata_in_source_link(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    topic_dir = config.topic_dir("fabric")
    insight_dir = topic_dir / "channels" / "Creator" / "videos" / "video-1"
    insight_dir.mkdir(parents=True, exist_ok=True)
    (insight_dir / "insights.md").write_text("# Insight", encoding="utf-8")
    (insight_dir / "metadata.json").write_text(
        '{"title": "Great Talk", "video_id": "abc123"}',
        encoding="utf-8",
    )
    captured: dict[str, str] = {}

    def _call(config, workload_tag, prompt, **kwargs):
        captured["prompt"] = prompt
        return LLM_Response(text="# Brief", input_tokens=120, output_tokens=80, model="grok-4.3")

    with patch("distill.pipeline.report.briefing.llm_call", _call):
        result = generate_topic_brief("fabric", config)

    assert result is not None
    assert "Great Talk" in captured["prompt"]


def test_generate_topic_brief_returns_none_when_llm_returns_empty(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    topic_dir = config.topic_dir("fabric")
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "topic_synthesis.md").write_text("# Synthesis", encoding="utf-8")

    with patch("distill.pipeline.report.briefing.llm_call", _fake_llm_call("")):
        result = generate_topic_brief("fabric", config)

    assert result is None
    assert not find_artifact(topic_dir, "brief", identity="fabric").exists()
