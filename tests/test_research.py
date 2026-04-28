"""Tests for distill.research."""

import json
from types import SimpleNamespace

from distill.artifacts import artifact_path, strip_frontmatter
from distill.config import DistillConfig
from distill.research import (
    _gather_corpus_condensed,
    _get_report_path,
    run_deep_research,
)


def test_get_report_path_respects_scope(tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")

    assert _get_report_path("ai", config, "topic", None) == artifact_path(
        config.topic_dir("ai"), "report", identity="ai"
    )
    assert _get_report_path("ai", config, "channel", "Creator") == artifact_path(
        config.channel_dir("ai", "Creator"), "report", identity="ai_Creator"
    )
    assert _get_report_path("all", config, "all", None) == artifact_path(
        config.library_dir, "report", identity="library"
    )


def test_gather_corpus_condensed_includes_context_synthesis_and_insights(tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    channel_dir = config.channel_dir("ai", "Creator")
    video_dir = channel_dir / "videos" / "video-1"
    video_dir.mkdir(parents=True, exist_ok=True)
    (channel_dir / "channel_context.md").write_text("# Context", encoding="utf-8")
    (channel_dir / "synthesis.md").write_text("# Synthesis", encoding="utf-8")
    (video_dir / "metadata.json").write_text(
        json.dumps({"title": "Video Title", "upload_date": "20260312"}),
        encoding="utf-8",
    )
    (video_dir / "insights.md").write_text(
        '---\nvideo_title: "Video Title"\n---\n\n# Insight body',
        encoding="utf-8",
    )
    (config.topic_dir("ai") / "topic_synthesis.md").write_text("# Topic Synth", encoding="utf-8")

    corpus = _gather_corpus_condensed("ai", config, "topic", None)

    assert "Channel: Creator" in corpus
    assert "Channel Synthesis" in corpus
    assert "[20260312] Video Title" in corpus
    assert "Insight body" in corpus
    assert "video_title:" not in corpus
    assert "Topic Synthesis: ai" in corpus


def test_run_deep_research_returns_none_when_no_files(tmp_path, monkeypatch):
    config = DistillConfig(gemini_api_key="test-key", distill_output_dir=tmp_path / "lib")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.interactions = SimpleNamespace()

    monkeypatch.setattr("distill.research.genai.Client", FakeClient)
    monkeypatch.setattr(
        "distill.research.create_research_store", lambda *args, **kwargs: ("store-1", 0)
    )
    deleted = []
    monkeypatch.setattr("distill.research.delete_store", lambda client, name: deleted.append(name))

    result = run_deep_research("ai", config)

    assert result is None
    assert deleted == ["store-1"]


def test_run_deep_research_saves_completed_output(tmp_path, monkeypatch):
    config = DistillConfig(gemini_api_key="test-key", distill_output_dir=tmp_path / "lib")

    interaction_states = [
        SimpleNamespace(status="running", outputs=[]),
        SimpleNamespace(status="completed", outputs=[SimpleNamespace(text="final report")]),
    ]

    class FakeInteractions:
        def create(self, **kwargs):
            return SimpleNamespace(id="job-1")

        def get(self, interaction_id):
            return interaction_states.pop(0)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.interactions = FakeInteractions()

    monkeypatch.setattr("distill.research.genai.Client", FakeClient)
    monkeypatch.setattr(
        "distill.research.create_research_store", lambda *args, **kwargs: ("store-1", 2)
    )
    deleted = []
    monkeypatch.setattr("distill.research.delete_store", lambda client, name: deleted.append(name))
    monkeypatch.setattr("distill.research.time.sleep", lambda seconds: None)

    result = run_deep_research("ai", config)

    assert result == "final report"
    report_path = artifact_path(config.topic_dir("ai"), "report", identity="ai")
    assert strip_frontmatter(report_path.read_text(encoding="utf-8")) == "final report"
    assert deleted == ["store-1"]


def test_run_deep_research_handles_failed_interaction(tmp_path, monkeypatch):
    config = DistillConfig(gemini_api_key="test-key", distill_output_dir=tmp_path / "lib")

    class FakeInteractions:
        def create(self, **kwargs):
            return SimpleNamespace(id="job-1")

        def get(self, interaction_id):
            return SimpleNamespace(status="failed", error="bad news", outputs=[])

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.interactions = FakeInteractions()

    monkeypatch.setattr("distill.research.genai.Client", FakeClient)
    monkeypatch.setattr(
        "distill.research.create_research_store", lambda *args, **kwargs: ("store-1", 2)
    )
    deleted = []
    monkeypatch.setattr("distill.research.delete_store", lambda client, name: deleted.append(name))

    result = run_deep_research("ai", config)

    assert result is None
    assert deleted == ["store-1", "store-1"]


def test_run_deep_research_returns_none_when_completed_without_output(tmp_path, monkeypatch):
    config = DistillConfig(gemini_api_key="test-key", distill_output_dir=tmp_path / "lib")

    class FakeInteractions:
        def create(self, **kwargs):
            return SimpleNamespace(id="job-1")

        def get(self, interaction_id):
            return SimpleNamespace(status="completed", outputs=[])

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.interactions = FakeInteractions()

    monkeypatch.setattr("distill.research.genai.Client", FakeClient)
    monkeypatch.setattr(
        "distill.research.create_research_store", lambda *args, **kwargs: ("store-1", 2)
    )
    deleted = []
    monkeypatch.setattr("distill.research.delete_store", lambda client, name: deleted.append(name))

    result = run_deep_research("ai", config)

    assert result is None
    assert deleted == ["store-1", "store-1"]


def test_gather_corpus_condensed_all_scope_collects_topic_syntheses(tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    for topic in ["ai", "security"]:
        channel_dir = config.channel_dir(topic, "Creator")
        video_dir = channel_dir / "videos" / "video-1"
        video_dir.mkdir(parents=True, exist_ok=True)
        (channel_dir / "channel_context.md").write_text("# Context", encoding="utf-8")
        (channel_dir / "synthesis.md").write_text("# Synthesis", encoding="utf-8")
        (video_dir / "metadata.json").write_text(
            json.dumps({"title": f"{topic} Video", "upload_date": "20260312"}),
            encoding="utf-8",
        )
        (video_dir / "insights.md").write_text("# Insight", encoding="utf-8")
        (config.topic_dir(topic) / "topic_synthesis.md").write_text(
            f"# {topic} topic", encoding="utf-8"
        )

    corpus = _gather_corpus_condensed("all", config, "all", None)

    assert "Topic Synthesis: ai" in corpus
    assert "Topic Synthesis: security" in corpus


def test_gather_corpus_condensed_channel_scope_and_missing_topic_dir(tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    channel_dir = config.channel_dir("ai", "Creator")
    (channel_dir / "videos" / "video-1").mkdir(parents=True, exist_ok=True)
    (channel_dir / "videos" / "video-1" / "insights.md").write_text("# Insight", encoding="utf-8")

    corpus = _gather_corpus_condensed("ai", config, "channel", "Creator")

    assert "Channel: Creator" not in corpus
    assert "Insight" in corpus
    assert _gather_corpus_condensed("missing", config, "topic", None) == ""


def test_run_deep_research_returns_none_on_interaction_exception(tmp_path, monkeypatch):
    config = DistillConfig(gemini_api_key="test-key", distill_output_dir=tmp_path / "lib")

    class FakeInteractions:
        def create(self, **kwargs):
            raise RuntimeError("boom")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.interactions = FakeInteractions()

    monkeypatch.setattr("distill.research.genai.Client", FakeClient)
    monkeypatch.setattr(
        "distill.research.create_research_store", lambda *args, **kwargs: ("store-1", 2)
    )
    deleted = []
    monkeypatch.setattr("distill.research.delete_store", lambda client, name: deleted.append(name))

    assert run_deep_research("ai", config) is None
    assert deleted == ["store-1"]


def test_run_deep_research_logs_long_running_status(tmp_path, monkeypatch):
    config = DistillConfig(gemini_api_key="test-key", distill_output_dir=tmp_path / "lib")

    interaction_states = [
        SimpleNamespace(status="running", outputs=[]),
        SimpleNamespace(status="running", outputs=[]),
        SimpleNamespace(status="running", outputs=[]),
        SimpleNamespace(status="running", outputs=[]),
        SimpleNamespace(status="completed", outputs=[SimpleNamespace(text="done")]),
    ]

    class FakeInteractions:
        def create(self, **kwargs):
            return SimpleNamespace(id="job-1")

        def get(self, interaction_id):
            return interaction_states.pop(0)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.interactions = FakeInteractions()

    monkeypatch.setattr("distill.research.genai.Client", FakeClient)
    monkeypatch.setattr(
        "distill.research.create_research_store", lambda *args, **kwargs: ("store-1", 2)
    )
    monkeypatch.setattr("distill.research.time.sleep", lambda seconds: None)
    deleted = []
    monkeypatch.setattr("distill.research.delete_store", lambda client, name: deleted.append(name))

    assert run_deep_research("ai", config) == "done"
    assert deleted == ["store-1"]


def test_gather_corpus_condensed_all_scope_skips_non_dirs(tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    topics_dir = config.topics_dir()
    topics_dir.mkdir(parents=True, exist_ok=True)
    (topics_dir / "README.txt").write_text("ignore", encoding="utf-8")
    topic_dir = config.topic_dir("ai")
    (topic_dir / "channels").mkdir(parents=True, exist_ok=True)
    (topic_dir / "channels" / "note.md").write_text("ignore", encoding="utf-8")
    (topic_dir / "topic_synthesis.md").write_text("# Topic", encoding="utf-8")

    corpus = _gather_corpus_condensed("all", config, "all", None)

    assert "Topic Synthesis: ai" in corpus


def test_gather_corpus_condensed_includes_site_artifacts(tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    site_dir = config.site_dir("ai", "example.com")
    page_dir = config.site_page_dir("ai", "example.com", "Agent Overview", "page1")
    page_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "synthesis.md").write_text("# Site synthesis", encoding="utf-8")
    (page_dir / "metadata.json").write_text(
        json.dumps(
            {"title": "Agent Overview", "url": "https://example.com/agent", "page_type": "article"}
        ),
        encoding="utf-8",
    )
    (page_dir / "insights.md").write_text("# Page insight", encoding="utf-8")

    corpus = _gather_corpus_condensed("ai", config, "topic", None)

    assert "Site Synthesis: example.com" in corpus
    assert "[article] Agent Overview" in corpus
    assert "https://example.com/agent" in corpus
    assert "Page insight" in corpus


def test_gather_corpus_condensed_includes_paper_and_corpus_synthesis(tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    topic_dir = config.topic_dir("ai")
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "paper_synthesis.md").write_text("# Paper synthesis", encoding="utf-8")
    (topic_dir / "corpus_synthesis.md").write_text("# Corpus synthesis", encoding="utf-8")

    paper_dir = config.paper_dir("ai", "Agent Memory Systems", "2602.12670v1")
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "metadata.json").write_text(
        json.dumps(
            {
                "title": "Agent Memory Systems",
                "abs_url": "https://arxiv.org/abs/2602.12670v1",
            }
        ),
        encoding="utf-8",
    )
    (paper_dir / "insights.md").write_text("# Paper insight", encoding="utf-8")

    corpus = _gather_corpus_condensed("ai", config, "topic", None)

    assert "Paper Synthesis: ai" in corpus
    assert "Corpus Synthesis: ai" in corpus
    assert "[paper] Agent Memory Systems" in corpus
    assert "https://arxiv.org/abs/2602.12670v1" in corpus
    assert "Paper insight" in corpus
