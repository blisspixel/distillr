"""Tests for distill.file_search."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from distill.config import DistillConfig
from distill.pipeline.report.file_search import _gather_files, cleanup_stores, create_research_store


def test_gather_files_bundles_channel_meta_and_insights(tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    channel_dir = config.channel_dir("ai", "Creator")
    (channel_dir / "videos" / "video-1").mkdir(parents=True, exist_ok=True)
    (channel_dir / "channel_context.md").write_text("# Context", encoding="utf-8")
    (channel_dir / "synthesis.md").write_text("# Synthesis", encoding="utf-8")
    (channel_dir / "videos" / "video-1" / "insights.md").write_text("# Insight", encoding="utf-8")
    (channel_dir / "videos" / "video-1" / "metadata.json").write_text(
        json.dumps({"title": "Video Title", "upload_date": "20260312"}),
        encoding="utf-8",
    )
    (config.topic_dir("ai") / "topic_synthesis.md").write_text("# Topic", encoding="utf-8")

    files = _gather_files("ai", config, "topic", None)

    labels = [label for label, _ in files]
    assert "channel-meta-Creator" in labels
    assert "Creator-insights" in labels
    assert "topic-synthesis-ai" in labels
    insight_content = dict(files)["Creator-insights"]
    assert "Video Title" in insight_content
    assert "# Insight" in insight_content


def test_gather_files_handles_bad_metadata_json(tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    video_dir = config.channel_dir("ai", "Creator") / "videos" / "video-1"
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "insights.md").write_text("# Insight", encoding="utf-8")
    (video_dir / "metadata.json").write_text("{bad json", encoding="utf-8")

    files = _gather_files("ai", config, "channel", "Creator")

    assert any(label == "Creator-insights" for label, _ in files)


def test_gather_files_handles_non_object_metadata_json(tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    video_dir = config.channel_dir("ai", "Creator") / "videos" / "video-1"
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "insights.md").write_text("# Insight", encoding="utf-8")
    (video_dir / "metadata.json").write_text('["bad shape"]', encoding="utf-8")

    files = _gather_files("ai", config, "channel", "Creator")

    bundled = dict(files)["Creator-insights"]
    assert "video-1" in bundled


def test_gather_files_ignores_non_string_metadata_fields(tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    video_dir = config.channel_dir("ai", "Creator") / "videos" / "video-1"
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "insights.md").write_text("# Insight", encoding="utf-8")
    (video_dir / "metadata.json").write_text(
        json.dumps({"title": {"bad": "shape"}, "upload_date": 260312}),
        encoding="utf-8",
    )

    files = _gather_files("ai", config, "channel", "Creator")

    bundled = dict(files)["Creator-insights"]
    assert "video-1" in bundled
    assert "[260312]" not in bundled


def test_gather_files_refuses_linked_corpus_artifacts(tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    video_dir = config.channel_dir("ai", "Creator") / "videos" / "video-1"
    video_dir.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside-secret.md"
    outside.write_text("FILE-SEARCH-SECRET", encoding="utf-8")
    insights = video_dir / "insights.md"
    try:
        insights.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlinks unavailable: {exc}")

    files = _gather_files("ai", config, "channel", "Creator")

    assert "FILE-SEARCH-SECRET" not in "\n".join(content for _, content in files)


def test_gather_files_refuses_hard_linked_corpus_artifacts(tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    video_dir = config.channel_dir("ai", "Creator") / "videos" / "video-1"
    video_dir.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside-secret.md"
    outside.write_text("FILE-SEARCH-HARDLINK-SECRET", encoding="utf-8")
    try:
        (video_dir / "insights.md").hardlink_to(outside)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")

    files = _gather_files("ai", config, "channel", "Creator")

    assert "FILE-SEARCH-HARDLINK-SECRET" not in "\n".join(content for _, content in files)


def test_gather_files_refuses_linked_metadata_payload(tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    video_dir = config.channel_dir("ai", "Creator") / "videos" / "video-1"
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "insights.md").write_text("# Safe insight", encoding="utf-8")
    outside = tmp_path / "outside-metadata.json"
    outside.write_text(
        json.dumps({"title": "FILE-SEARCH-METADATA-SECRET", "upload_date": "20260101"}),
        encoding="utf-8",
    )
    try:
        (video_dir / "metadata.json").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlinks unavailable: {exc}")

    files = _gather_files("ai", config, "channel", "Creator")

    assert "FILE-SEARCH-METADATA-SECRET" not in "\n".join(content for _, content in files)


def test_create_research_store_returns_zero_when_no_files(tmp_path, monkeypatch):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    client = SimpleNamespace(
        file_search_stores=SimpleNamespace(create=lambda config: SimpleNamespace(name="store-1"))
    )
    monkeypatch.setattr(
        "distill.pipeline.report.file_search._gather_files", lambda *args, **kwargs: []
    )

    store_name, uploaded = create_research_store(client, "ai", config, "topic", None)

    assert store_name == "store-1"
    assert uploaded == 0


def test_create_research_store_deletes_store_when_post_create_output_fails(tmp_path, monkeypatch):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    deleted = []

    class FakeStores:
        def create(self, config):
            return SimpleNamespace(name="store-1")

        def delete(self, name, config):
            deleted.append(name)

    print_calls = 0

    def fail_first_print(*args, **kwargs):
        nonlocal print_calls
        print_calls += 1
        if print_calls == 1:
            raise BrokenPipeError("closed output")

    client = SimpleNamespace(file_search_stores=FakeStores())
    monkeypatch.setattr("distill.pipeline.report.file_search.console.print", fail_first_print)

    with pytest.raises(BrokenPipeError, match="closed output"):
        create_research_store(client, "ai", config, "topic", None)

    assert deleted == ["store-1"]


def test_create_research_store_recovers_identity_before_cleanup_when_name_access_fails(
    tmp_path, monkeypatch
):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
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
        file_search_stores=SimpleNamespace(
            create=lambda config: FlakyStore(),
            delete=lambda name, config: deleted.append(name),
        )
    )

    with pytest.raises(BrokenPipeError, match="name access failed"):
        create_research_store(client, "ai", config, "topic", None)

    assert deleted == ["store-1"]


def test_create_research_store_deletes_store_on_process_interruption(tmp_path, monkeypatch):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    deleted = []
    client = SimpleNamespace(
        file_search_stores=SimpleNamespace(
            create=lambda config: SimpleNamespace(name="store-1"),
            delete=lambda name, config: deleted.append(name),
        )
    )

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("distill.pipeline.report.file_search._gather_files", interrupt)

    with pytest.raises(KeyboardInterrupt):
        create_research_store(client, "ai", config, "topic", None)

    assert deleted == ["store-1"]


def test_create_research_store_preserves_active_error_when_cleanup_is_interrupted(
    tmp_path, monkeypatch
):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    client = SimpleNamespace(
        file_search_stores=SimpleNamespace(
            create=lambda config: SimpleNamespace(name="store-1"),
            delete=lambda name, config: (_ for _ in ()).throw(SystemExit(2)),
        )
    )

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt("operator cancelled")

    monkeypatch.setattr("distill.pipeline.report.file_search._gather_files", interrupt)

    with pytest.raises(KeyboardInterrupt, match="operator cancelled") as exc_info:
        create_research_store(client, "ai", config, "topic", None)

    assert any("cleanup was interrupted" in note for note in exc_info.value.__notes__)


def test_cleanup_stores_deletes_matching_prefix_and_skips_others():
    deleted = []
    stores = [
        SimpleNamespace(name="1", display_name="distill-ai-topic"),
        SimpleNamespace(name="2", display_name="other-store"),
    ]
    client = SimpleNamespace(
        file_search_stores=SimpleNamespace(
            list=lambda: stores,
            delete=lambda name, config: deleted.append(name),
        )
    )

    result = cleanup_stores(client, prefix="distill")

    assert result == 1
    assert deleted == ["1"]


def test_create_research_store_uploads_and_waits_for_indexing(tmp_path, monkeypatch):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    monkeypatch.setattr(
        "distill.pipeline.report.file_search._gather_files",
        lambda *args, **kwargs: [("doc-1", "# One"), ("doc-2", "# Two")],
    )
    monkeypatch.setattr("distill.pipeline.report.file_search.time.sleep", lambda seconds: None)
    observed_temp_paths = []

    class FakeStores:
        def create(self, config):
            return SimpleNamespace(name="store-1")

        def upload_to_file_search_store(self, file, file_search_store_name, config):
            observed_temp_paths.append(Path(file))
            assert Path(file).exists()
            return SimpleNamespace(name=f"op-{len(observed_temp_paths)}")

    class FakeOperations:
        def __init__(self):
            self.calls = {}

        def get(self, op):
            op_name = op.name
            self.calls[op_name] = self.calls.get(op_name, 0) + 1
            return SimpleNamespace(name=op_name, done=self.calls[op_name] > 1)

    client = SimpleNamespace(file_search_stores=FakeStores(), operations=FakeOperations())

    store_name, uploaded = create_research_store(client, "ai", config, "topic", None)

    assert store_name == "store-1"
    assert uploaded == 2
    assert [path.exists() for path in observed_temp_paths] == [False, False]


def test_delete_store_and_list_stores_handle_client_objects():
    deleted = []
    stores = [
        SimpleNamespace(name="1", display_name="distill-one"),
        SimpleNamespace(name="2"),
    ]
    client = SimpleNamespace(
        file_search_stores=SimpleNamespace(
            delete=lambda name, config: deleted.append((name, config["force"])),
            list=lambda: stores,
        )
    )

    from distill.pipeline.report.file_search import delete_store, list_stores

    delete_store(client, "1")
    listed = list_stores(client)

    assert deleted == [("1", True)]
    assert listed[0]["display_name"] == "distill-one"
    assert listed[1]["display_name"] == "(unnamed)"


def test_gather_files_all_scope_collects_multiple_topics(tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    for topic in ["ai", "security"]:
        channel_dir = config.channel_dir(topic, "Creator")
        (channel_dir / "videos" / "video-1").mkdir(parents=True, exist_ok=True)
        (channel_dir / "videos" / "video-1" / "insights.md").write_text(
            "# Insight", encoding="utf-8"
        )
        (channel_dir / "videos" / "video-1" / "metadata.json").write_text(
            json.dumps({"title": f"{topic} Video", "upload_date": "20260312"}),
            encoding="utf-8",
        )
        (config.topic_dir(topic) / "topic_synthesis.md").write_text(
            "# Topic Synth", encoding="utf-8"
        )

    files = _gather_files("all", config, "all", None)
    labels = [label for label, _ in files]

    assert "topic-synthesis-ai" in labels
    assert "topic-synthesis-security" in labels


def test_delete_store_swallows_errors():
    from distill.pipeline.report.file_search import delete_store

    class BrokenStores:
        def delete(self, name, config):
            raise Exception("boom")

    client = SimpleNamespace(file_search_stores=BrokenStores())

    delete_store(client, "store-1")


def test_create_research_store_handles_upload_failures_and_timeouts(tmp_path, monkeypatch):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    monkeypatch.setattr(
        "distill.pipeline.report.file_search._gather_files",
        lambda *args, **kwargs: [("doc-1", "# One"), ("doc-2", "# Two")],
    )
    monkeypatch.setattr("distill.pipeline.report.file_search.time.sleep", lambda seconds: None)

    class FakeStores:
        def __init__(self):
            self.calls = 0

        def create(self, config):
            return SimpleNamespace(name="store-1")

        def upload_to_file_search_store(self, file, file_search_store_name, config):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("upload failed")
            return "op-2"

    class FakeOperations:
        def get(self, op):
            raise RuntimeError("still indexing")

    client = SimpleNamespace(file_search_stores=FakeStores(), operations=FakeOperations())

    store_name, uploaded = create_research_store(client, "ai", config, "topic", None)

    assert store_name == "store-1"
    assert uploaded == 0


def test_cleanup_stores_swallows_delete_errors():
    stores = [SimpleNamespace(name="1", display_name="distill-ai-topic")]
    client = SimpleNamespace(
        file_search_stores=SimpleNamespace(
            list=lambda: stores,
            delete=lambda name, config: (_ for _ in ()).throw(RuntimeError("boom")),
        )
    )

    assert cleanup_stores(client, prefix="distill") == 0


def test_gather_files_handles_missing_topics_root(tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")

    assert _gather_files("all", config, "all", None) == []


def test_create_research_store_reports_timeout(tmp_path, monkeypatch):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    monkeypatch.setattr(
        "distill.pipeline.report.file_search._gather_files",
        lambda *args, **kwargs: [("doc-1", "# One")],
    )
    monkeypatch.setattr("distill.pipeline.report.file_search.time.sleep", lambda seconds: None)

    class FakeStores:
        def create(self, config):
            return SimpleNamespace(name="store-1")

        def upload_to_file_search_store(self, file, file_search_store_name, config):
            return "op-1"

    class FakeOperations:
        def get(self, op):
            return SimpleNamespace(done=None)

    client = SimpleNamespace(file_search_stores=FakeStores(), operations=FakeOperations())

    store_name, uploaded = create_research_store(client, "ai", config, "topic", None)

    assert store_name == "store-1"
    assert uploaded == 0


def test_create_research_store_excludes_failed_completed_operations(tmp_path, monkeypatch):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    monkeypatch.setattr(
        "distill.pipeline.report.file_search._gather_files",
        lambda *args, **kwargs: [("doc-1", "# One")],
    )

    class FakeStores:
        def create(self, config):
            return SimpleNamespace(name="store-1")

        def upload_to_file_search_store(self, file, file_search_store_name, config):
            return SimpleNamespace(name="op-1")

    class FakeOperations:
        def get(self, op):
            return SimpleNamespace(name="op-1", done=True, error={"code": 13})

    client = SimpleNamespace(file_search_stores=FakeStores(), operations=FakeOperations())

    store_name, indexed = create_research_store(client, "ai", config, "topic", None)

    assert store_name == "store-1"
    assert indexed == 0


def test_gather_files_skips_nondirs_and_splits_large_bundles(tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    channel_dir = config.channel_dir("ai", "Creator")
    videos_dir = channel_dir / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    (videos_dir / "note.txt").write_text("ignore", encoding="utf-8")
    for idx in range(2):
        video_dir = videos_dir / f"video-{idx}"
        video_dir.mkdir()
        (video_dir / "insights.md").write_text("X" * 500_100, encoding="utf-8")
        (video_dir / "metadata.json").write_text(
            json.dumps({"title": f"Video {idx}", "upload_date": "20260312"}),
            encoding="utf-8",
        )

    files = _gather_files("ai", config, "channel", "Creator")
    labels = [label for label, _ in files]

    assert "Creator-insights-part1" in labels
    assert "Creator-insights-part2" in labels


def test_gather_files_includes_site_synthesis_and_page_insights(tmp_path):
    from distill.config import DistillConfig
    from distill.pipeline.report.file_search import _gather_files

    config = DistillConfig(distill_output_dir=tmp_path / "library")
    site_dir = config.site_dir("web", "example.com")
    pages_dir = config.site_pages_dir("web", "example.com")
    pages_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "synthesis.md").write_text("# Site Summary", encoding="utf-8")

    page_dir = pages_dir / "example-page"
    page_dir.mkdir()
    (page_dir / "metadata.json").write_text(
        '{"title": "Example Page", "url": "https://example.com/page"}',
        encoding="utf-8",
    )
    (page_dir / "insights.md").write_text("# Insight\nBody", encoding="utf-8")

    files = _gather_files("web", config, scope="topic", channel_name=None)
    labels = [label for label, _ in files]

    assert "site-synthesis-example.com" in labels
    assert "example.com-pages" in labels
    bundled = dict(files)["example.com-pages"]
    assert "Example Page" in bundled
    assert "https://example.com/page" in bundled


def test_gather_files_includes_paper_and_corpus_synthesis(tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "library")
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

    files = _gather_files("ai", config, scope="topic", channel_name=None)
    labels = [label for label, _ in files]

    assert "ai-papers" in labels
    assert "paper-synthesis-ai" in labels
    assert "corpus-synthesis-ai" in labels
    bundled = dict(files)["ai-papers"]
    assert "Agent Memory Systems" in bundled
    assert "https://arxiv.org/abs/2602.12670v1" in bundled
    assert "Paper insight" in bundled


def test_create_research_store_polls_with_operation_name(tmp_path, monkeypatch):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    monkeypatch.setattr(
        "distill.pipeline.report.file_search._gather_files",
        lambda *args, **kwargs: [("doc-1", "# One")],
    )
    monkeypatch.setattr("distill.pipeline.report.file_search.time.sleep", lambda seconds: None)
    polled = []

    class FakeStores:
        def create(self, config):
            return SimpleNamespace(name="store-1")

        def upload_to_file_search_store(self, file, file_search_store_name, config):
            return SimpleNamespace(name="operations/upload-1")

    class FakeOperations:
        def get(self, op):
            polled.append(op.name)
            return SimpleNamespace(name=op.name, done=True)

    client = SimpleNamespace(file_search_stores=FakeStores(), operations=FakeOperations())

    store_name, uploaded = create_research_store(client, "ai", config, "topic", None)

    assert store_name == "store-1"
    assert uploaded == 1
    assert polled == ["operations/upload-1"]
