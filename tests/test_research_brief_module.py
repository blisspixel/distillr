import json
from pathlib import Path
from types import SimpleNamespace

from distill.config import DistillConfig
from distill.research_brief import (
    _bundle_insights,
    _upload_files,
    compose_prompt,
    gather_topic_files,
    run_research_brief,
)


def test_bundle_insights_splits_and_gather_topic_files(tmp_path, monkeypatch):
    config = DistillConfig(gemini_api_key="test-key", distill_output_dir=tmp_path / "lib")
    topic_dir = config.topic_dir("ai")
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "paper_synthesis.md").write_text("# Paper synthesis", encoding="utf-8")
    (topic_dir / "topic_synthesis.md").write_text("# Topic synthesis", encoding="utf-8")
    (topic_dir / "corpus_synthesis.md").write_text("# Corpus synthesis", encoding="utf-8")

    paper_dir = config.papers_dir("ai") / "paper-1"
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "insights.md").write_text("# Paper insight", encoding="utf-8")
    (paper_dir / "metadata.json").write_text(
        json.dumps({"title": "Paper One", "abs_url": "https://arxiv.org/abs/1"}),
        encoding="utf-8",
    )

    video_dir = config.channel_dir("ai", "Creator") / "videos" / "video-1"
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "insights.md").write_text("# Video insight", encoding="utf-8")
    (video_dir / "metadata.json").write_text(
        json.dumps({"title": "Video One", "url": "https://youtube.com/watch?v=1"}),
        encoding="utf-8",
    )

    page_dir = config.sites_dir("ai") / "example.com" / "pages" / "page-1"
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "insights.md").write_text("# Page insight", encoding="utf-8")
    (page_dir / "metadata.json").write_text(
        json.dumps({"title": "Page One", "url": "https://example.com/one"}),
        encoding="utf-8",
    )

    monkeypatch.setattr("distill.research_brief.MAX_DOC_CHARS", 40)
    bundles = _bundle_insights(config.papers_dir("ai"), "ai-papers", "ai", "paper")
    gathered = gather_topic_files(["missing", "ai"], config)

    assert len(bundles) == 1
    labels = {label for label, _ in gathered}
    assert "paper-synthesis-ai" in labels
    assert "topic-synthesis-ai" in labels
    assert "corpus-synthesis-ai" in labels
    assert any("ai-papers" in label for label in labels)
    assert any("Creator-videos" in label for label in labels)
    assert any("example.com-pages" in label for label in labels)
    assert "research briefing" in compose_prompt(" Focus here ").lower()


def test_upload_files_handles_success_and_failed_operations(monkeypatch):
    uploads = []

    class FakeFileStores:
        def upload_to_file_search_store(self, *, file, file_search_store_name, config):
            uploads.append((file, file_search_store_name, config["display_name"]))
            if config["display_name"] == "bad":
                raise RuntimeError("upload failed")
            return SimpleNamespace(name=f"op-{config['display_name']}")

    class FakeOperations:
        def __init__(self):
            self.calls = 0

        def get(self, op):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(done=False, name=op)
            return SimpleNamespace(done=True, name=op)

    client = SimpleNamespace(file_search_stores=FakeFileStores(), operations=FakeOperations())
    monkeypatch.setattr("distill.research_brief.time.sleep", lambda _seconds: None)

    uploaded = _upload_files(
        client,
        "store-1",
        [("good", "alpha"), ("bad", "beta")],
    )

    assert uploaded == 1
    assert uploads


def test_run_research_brief_handles_missing_inputs_and_success(tmp_path, monkeypatch):
    config = DistillConfig(gemini_api_key="test-key", distill_output_dir=tmp_path / "lib")
    deleted = []

    class FakeInteractions:
        def __init__(self, statuses):
            self._statuses = list(statuses)

        def create(self, **_kwargs):
            return SimpleNamespace(id="job-1")

        def get(self, _interaction_id):
            return self._statuses.pop(0)

    class FakeClient:
        def __init__(self, statuses, store_name="store-1"):
            self.file_search_stores = SimpleNamespace(
                create=lambda **_kwargs: SimpleNamespace(name=store_name)
            )
            self.interactions = FakeInteractions(statuses)

    monkeypatch.setattr("distill.research_brief._upload_files", lambda *_args, **_kwargs: 2)
    monkeypatch.setattr(
        "distill.research_brief.delete_store", lambda _client, name: deleted.append(name)
    )
    monkeypatch.setattr("distill.research_brief.time.sleep", lambda _seconds: None)

    no_key = DistillConfig(distill_output_dir=tmp_path / "empty")
    assert run_research_brief(["ai"], "ctx", "demo", no_key) is None

    monkeypatch.setattr("distill.research_brief.gather_topic_files", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        "distill.research_brief.genai.Client",
        lambda **_kwargs: FakeClient([SimpleNamespace(status="completed", outputs=[])]),
    )
    assert run_research_brief(["ai"], "ctx", "demo", config) is None

    monkeypatch.setattr(
        "distill.research_brief.gather_topic_files",
        lambda *_args, **_kwargs: [("doc", "body")],
    )
    monkeypatch.setattr(
        "distill.research_brief.genai.Client",
        lambda **_kwargs: FakeClient(
            [SimpleNamespace(status="completed", outputs=[])], store_name=""
        ),
    )
    assert run_research_brief(["ai"], "ctx", "demo", config) is None

    monkeypatch.setattr(
        "distill.research_brief.genai.Client",
        lambda **_kwargs: FakeClient([SimpleNamespace(status="failed", error="bad", outputs=[])]),
    )
    assert run_research_brief(["ai"], "ctx", "demo", config) is None

    monkeypatch.setattr(
        "distill.research_brief.genai.Client",
        lambda **_kwargs: FakeClient([SimpleNamespace(status="completed", outputs=[])]),
    )
    assert run_research_brief(["ai"], "ctx", "demo", config) is None

    monkeypatch.setattr(
        "distill.research_brief.genai.Client",
        lambda **_kwargs: FakeClient(
            [
                SimpleNamespace(status="running", outputs=[]),
                SimpleNamespace(status="completed", outputs=[SimpleNamespace(text="brief body")]),
            ]
        ),
    )
    result = run_research_brief(["ai"], "ctx", "demo", config)

    assert result == Path("output") / "briefing-demo.md"
    assert result.read_text(encoding="utf-8") == "brief body"
    assert deleted
