"""Tests for distill.briefing."""

from types import SimpleNamespace

from distill.artifacts import find_artifact, strip_frontmatter
from distill.briefing import generate_topic_brief
from distill.config import DistillConfig
from distill.costs import CostTracker


def test_generate_topic_brief_returns_none_without_inputs(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")

    result = generate_topic_brief("fabric", config)

    assert result is None


def test_generate_topic_brief_writes_brief_and_tracks_usage(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    topic_dir = config.topic_dir("fabric")
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "topic_synthesis.md").write_text("# Synthesis", encoding="utf-8")

    for index in range(7):
        insight_dir = topic_dir / "channels" / f"Creator{index // 3}" / "videos" / f"video-{index}"
        insight_dir.mkdir(parents=True, exist_ok=True)
        (insight_dir / "insights.md").write_text(f"# Insight {index}", encoding="utf-8")

    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured["model"] = kwargs["model"]
            captured["prompt"] = kwargs["messages"][0]["content"]
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="# Brief"))],
                usage=SimpleNamespace(prompt_tokens=120, completion_tokens=80),
            )

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("distill.briefing.OpenAI", FakeClient)
    tracker = CostTracker()

    result = generate_topic_brief("fabric", config, tracker=tracker)

    assert result == find_artifact(topic_dir, "brief", identity="fabric")
    assert result.name == "fabric_Brief.md"
    assert strip_frontmatter(result.read_text(encoding="utf-8")) == "# Brief"
    assert len(tracker.entries) == 1
    assert tracker.total_input_tokens == 120
    assert tracker.total_output_tokens == 80
    assert tracker.entries[0].call_type == "topic_brief"
    assert captured["model"]
    assert "Topic Brief: fabric" in captured["prompt"]
    assert captured["prompt"].count("## Creator") == 6


def test_generate_topic_brief_returns_none_when_llm_returns_empty(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    topic_dir = config.topic_dir("fabric")
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "topic_synthesis.md").write_text("# Synthesis", encoding="utf-8")

    class FakeCompletions:
        def create(self, **kwargs):
            return SimpleNamespace(choices=[], usage=None)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("distill.briefing.OpenAI", FakeClient)

    result = generate_topic_brief("fabric", config)

    assert result is None
    assert not find_artifact(topic_dir, "brief", identity="fabric").exists()
