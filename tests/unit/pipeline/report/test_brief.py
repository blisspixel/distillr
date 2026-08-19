import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from distill.config import DistillConfig
from distill.llm.cost_policy import CostPolicyError
from distill.pipeline.costs import CostTracker, UnboundedProviderCostError
from distill.pipeline.report.brief import (
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

    monkeypatch.setattr("distill.pipeline.report.brief.MAX_DOC_CHARS", 40)
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


def test_bundle_insights_ignores_non_string_metadata_fields(tmp_path):
    config = DistillConfig(gemini_api_key="test-key", distill_output_dir=tmp_path / "lib")
    paper_dir = config.papers_dir("ai") / "paper-1"
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "insights.md").write_text("# Paper insight", encoding="utf-8")
    (paper_dir / "metadata.json").write_text(
        json.dumps({"title": {"bad": "shape"}, "abs_url": 123, "paper_id": ["paper"]}),
        encoding="utf-8",
    )

    bundles = _bundle_insights(config.papers_dir("ai"), "ai-papers", "ai", "paper")

    content = bundles[0][1]
    assert "paper-1" in content
    assert "bad" not in content
    assert "123" not in content


def test_upload_files_handles_success_and_failed_operations(monkeypatch):
    uploads = []
    polled = []

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
            polled.append(op.name)
            if self.calls == 1:
                return SimpleNamespace(done=False, name=op.name)
            return SimpleNamespace(done=True, name=op.name)

    client = SimpleNamespace(file_search_stores=FakeFileStores(), operations=FakeOperations())
    monkeypatch.setattr("distill.pipeline.report.brief.time.sleep", lambda _seconds: None)

    uploaded = _upload_files(
        client,
        "store-1",
        [("good", "alpha"), ("bad", "beta")],
    )

    assert uploaded == 1
    assert uploads
    assert polled == ["op-good", "op-good"]


def test_run_research_brief_no_metered_refuses_before_client_or_gather(tmp_path, monkeypatch):
    config = DistillConfig(
        gemini_api_key="test-key",
        distill_cost_mode="no-metered",
        distill_output_dir=tmp_path / "lib",
    )
    client = MagicMock(side_effect=AssertionError("client constructed"))
    gather = MagicMock(side_effect=AssertionError("files gathered"))
    monkeypatch.setattr("distill.pipeline.report.brief.genai.Client", client)
    monkeypatch.setattr("distill.pipeline.report.brief.gather_topic_files", gather)

    with pytest.raises(CostPolicyError, match="Route blocked by no-metered cost policy"):
        run_research_brief(["ai"], "ctx", "demo", config)

    client.assert_not_called()
    gather.assert_not_called()


def test_run_research_brief_requires_tracker_before_client_or_gather(tmp_path, monkeypatch):
    config = DistillConfig(gemini_api_key="test-key", distill_output_dir=tmp_path / "lib")
    client = MagicMock(side_effect=AssertionError("client constructed without a ledger"))
    gather = MagicMock(side_effect=AssertionError("corpus gathered without a ledger"))
    monkeypatch.setattr("distill.pipeline.report.brief.genai.Client", client)
    monkeypatch.setattr("distill.pipeline.report.brief.gather_topic_files", gather)

    with pytest.raises(ValueError, match="CostTracker is required"):
        run_research_brief(["ai"], "ctx", "demo", config)

    client.assert_not_called()
    gather.assert_not_called()


def test_run_research_brief_hard_budget_refuses_before_client_or_gather(tmp_path, monkeypatch):
    config = DistillConfig(gemini_api_key="test-key", distill_output_dir=tmp_path / "lib")
    client = MagicMock(side_effect=AssertionError("client constructed"))
    gather = MagicMock(side_effect=AssertionError("files gathered"))
    monkeypatch.setattr("distill.pipeline.report.brief.genai.Client", client)
    monkeypatch.setattr("distill.pipeline.report.brief.gather_topic_files", gather)

    with pytest.raises(UnboundedProviderCostError, match="no request-side dollar ceiling"):
        run_research_brief(
            ["ai"],
            "ctx",
            "demo",
            config,
            tracker=CostTracker(budget=1_000.00),
        )

    client.assert_not_called()
    gather.assert_not_called()


def test_run_research_brief_refuses_when_no_documents_indexed(tmp_path, monkeypatch):
    config = DistillConfig(gemini_api_key="test-key", distill_output_dir=tmp_path / "lib")
    submit = MagicMock(side_effect=AssertionError("metered interaction submitted"))
    deleted: list[str] = []

    class FakeClient:
        def __init__(self):
            self.file_search_stores = SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(name="store-1")
            )
            self.interactions = SimpleNamespace(create=submit)

    monkeypatch.setattr(
        "distill.pipeline.report.brief.gather_topic_files",
        lambda *args, **kwargs: [("doc", "body")],
    )
    monkeypatch.setattr("distill.pipeline.report.brief._upload_files", lambda *args: 0)
    monkeypatch.setattr("distill.pipeline.report.brief.genai.Client", lambda **kwargs: FakeClient())
    monkeypatch.setattr(
        "distill.pipeline.report.brief.delete_store",
        lambda client, name: deleted.append(name),
    )

    result = run_research_brief(["ai"], "ctx", "demo", config, tracker=CostTracker())

    assert result is None
    submit.assert_not_called()
    assert deleted == ["store-1"]


def test_research_brief_recovers_store_identity_when_initial_name_access_fails(
    tmp_path, monkeypatch
):
    config = DistillConfig(gemini_api_key="test-key", distill_output_dir=tmp_path / "lib")
    deleted = []

    class FlakyStore:
        accesses = 0

        @property
        def name(self):
            self.accesses += 1
            if self.accesses == 1:
                raise BrokenPipeError("name access failed")
            return "store-1"

    client = SimpleNamespace(
        file_search_stores=SimpleNamespace(create=lambda **kwargs: FlakyStore())
    )
    monkeypatch.setattr(
        "distill.pipeline.report.brief.gather_topic_files",
        lambda *args, **kwargs: [("doc", "body")],
    )
    monkeypatch.setattr("distill.pipeline.report.brief.genai.Client", lambda **kwargs: client)
    monkeypatch.setattr(
        "distill.pipeline.report.brief.delete_store",
        lambda client, name: deleted.append(name),
    )

    with pytest.raises(BrokenPipeError, match="name access failed"):
        run_research_brief(["ai"], "ctx", "demo", config, tracker=CostTracker())

    assert deleted == ["store-1"]


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

    monkeypatch.setattr("distill.pipeline.report.brief._upload_files", lambda *_args, **_kwargs: 2)
    monkeypatch.setattr(
        "distill.pipeline.report.brief.delete_store", lambda _client, name: deleted.append(name)
    )
    monkeypatch.setattr("distill.pipeline.report.brief.time.sleep", lambda _seconds: None)

    # The credential-isolation autouse fixture injects an inert GEMINI_API_KEY into
    # the env, and DistillConfig reads it -- clear it so this genuinely exercises
    # the missing-key early return rather than the downstream metered path.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    no_key = DistillConfig(gemini_api_key="", distill_output_dir=tmp_path / "empty")
    assert run_research_brief(["ai"], "ctx", "demo", no_key) is None

    monkeypatch.setattr(
        "distill.pipeline.report.brief.gather_topic_files", lambda *_args, **_kwargs: []
    )
    monkeypatch.setattr(
        "distill.pipeline.report.brief.genai.Client",
        lambda **_kwargs: FakeClient(
            [
                SimpleNamespace(
                    status="completed",
                    steps=[
                        SimpleNamespace(
                            type="model_output",
                            content=[SimpleNamespace(type="text", text="ungrounded body")],
                        )
                    ],
                )
            ]
        ),
    )
    assert run_research_brief(["ai"], "ctx", "demo", config, tracker=CostTracker()) is None

    monkeypatch.setattr(
        "distill.pipeline.report.brief.gather_topic_files",
        lambda *_args, **_kwargs: [("doc", "body")],
    )
    monkeypatch.setattr(
        "distill.pipeline.report.brief.genai.Client",
        lambda **_kwargs: FakeClient(
            [SimpleNamespace(status="completed", steps=[])], store_name=""
        ),
    )
    assert run_research_brief(["ai"], "ctx", "demo", config, tracker=CostTracker()) is None

    monkeypatch.setattr(
        "distill.pipeline.report.brief.genai.Client",
        lambda **_kwargs: FakeClient([SimpleNamespace(status="failed", steps=[])]),
    )
    assert run_research_brief(["ai"], "ctx", "demo", config, tracker=CostTracker()) is None

    monkeypatch.setattr(
        "distill.pipeline.report.brief.genai.Client",
        lambda **_kwargs: FakeClient([SimpleNamespace(status="completed", steps=[])]),
    )
    assert run_research_brief(["ai"], "ctx", "demo", config, tracker=CostTracker()) is None

    monkeypatch.setattr(
        "distill.pipeline.report.brief.genai.Client",
        lambda **_kwargs: FakeClient(
            [
                SimpleNamespace(status="in_progress", steps=[]),
                SimpleNamespace(
                    status="completed",
                    steps=[
                        SimpleNamespace(type="file_search_call", id="search-1"),
                        SimpleNamespace(type="file_search_result", call_id="search-1"),
                        SimpleNamespace(
                            type="model_output",
                            content=[
                                SimpleNamespace(
                                    type="text",
                                    text="brief body",
                                    annotations=[
                                        SimpleNamespace(
                                            type="file_citation",
                                            file_name="doc.md",
                                        )
                                    ],
                                )
                            ],
                        ),
                    ],
                ),
            ]
        ),
    )
    tracker = CostTracker()
    result = run_research_brief(["ai"], "ctx", "demo", config, tracker=tracker)

    assert result == Path("output") / "briefing-demo.md"
    assert result.read_text(encoding="utf-8") == "brief body"
    assert tracker.gemini_queries == 1
    assert deleted


def test_run_research_brief_refuses_unresolved_numbered_citation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = DistillConfig(gemini_api_key="test-key", distill_output_dir=tmp_path / "lib")
    deleted = []

    class FakeInteractions:
        def create(self, **_kwargs):
            return SimpleNamespace(id="job-1")

        def get(self, _interaction_id):
            return SimpleNamespace(
                status="completed",
                steps=[
                    SimpleNamespace(type="file_search_call", id="search-1"),
                    SimpleNamespace(type="file_search_result", call_id="search-1"),
                    SimpleNamespace(
                        type="model_output",
                        content=[
                            SimpleNamespace(
                                type="text",
                                text="Unsupported briefing claim [cite: 1].",
                                annotations=[
                                    SimpleNamespace(type="file_citation", file_name="doc.md")
                                ],
                            )
                        ],
                    ),
                ],
            )

    class FakeClient:
        def __init__(self):
            self.file_search_stores = SimpleNamespace(
                create=lambda **_kwargs: SimpleNamespace(name="store-1")
            )
            self.interactions = FakeInteractions()

    monkeypatch.setattr("distill.pipeline.report.brief._upload_files", lambda *_args: 1)
    monkeypatch.setattr(
        "distill.pipeline.report.brief.delete_store", lambda _client, name: deleted.append(name)
    )
    monkeypatch.setattr(
        "distill.pipeline.report.brief.gather_topic_files",
        lambda *_args, **_kwargs: [("doc", "body")],
    )
    monkeypatch.setattr(
        "distill.pipeline.report.brief.genai.Client",
        lambda **_kwargs: FakeClient(),
    )
    tracker = CostTracker()

    result = run_research_brief(["ai"], "ctx", "refused", config, tracker=tracker)

    assert result is None
    assert tracker.gemini_queries == 1
    assert not (tmp_path / "output" / "briefing-refused.md").exists()
    assert deleted == ["store-1"]
