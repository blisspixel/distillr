"""Tests for distill.cli_shared."""

import json
import sys
from types import SimpleNamespace

import pytest
import typer
from rich.console import Console

from distill._bootstrap import ensure_utf8_stdio
from distill.cli_shared import (
    duration_str,
    format_date,
    output_path,
    print_markdown_safely,
    require_api_key,
    resolve_video_channel_name,
    safe_console_text,
    strip_frontmatter,
    topic_from_query,
    write_video_metadata,
)
from distill.commands._helpers import (
    _detect_ramp_source,
    budgeted_cost_tracker,
    enforce_projected_workflow_budget,
    save_command_cost,
)
from distill.commands._topic_resolution import (
    resolve_required_topic_for_channel as _resolve_required_topic_for_channel,
)
from distill.commands._topic_watch import (
    normalize_topic_watch_ranking_mode,
    topic_watch_name,
    topic_watch_ranking_strategy,
)
from distill.llm.cost_policy import CostPolicyError
from distill.llm.errors import ProviderBusyTimeoutError


class TestBudgetedCostTracker:
    def test_applies_exact_configured_workflow_cap(self, tmp_path):
        from distill.config import DistillConfig

        config = DistillConfig(
            distill_output_dir=tmp_path / "library",
            distill_cost_workflow_budgets="learn=0.01,site-batch=2",
        )

        assert budgeted_cost_tracker(config, "learn").budget == 0.01
        assert budgeted_cost_tracker(config, " site-batch ").budget == 2.0
        assert budgeted_cost_tracker(config, "ask").budget is None

    def test_projected_budget_refuses_before_run(self, tmp_path):
        from distill.config import DistillConfig
        from distill.pipeline.costs import ProjectedBudgetExceededError

        config = DistillConfig(
            distill_output_dir=tmp_path / "library",
            distill_cost_workflow_budgets="eval=0.05",
        )

        with pytest.raises(ProjectedBudgetExceededError) as raised:
            enforce_projected_workflow_budget(config, "eval", 0.12)

        assert raised.value.projected == 0.12
        assert raised.value.budget == 0.05

    def test_projected_budget_allows_missing_or_lower_cap(self, tmp_path):
        from distill.config import DistillConfig

        config = DistillConfig(
            distill_output_dir=tmp_path / "library",
            distill_cost_workflow_budgets="eval=0.20",
        )

        enforce_projected_workflow_budget(config, "eval", 0.12)
        enforce_projected_workflow_budget(config, "discover", 999.0)

    def test_save_command_cost_skips_empty_and_persists_local_usage(self, tmp_path):
        from distill.config import DistillConfig
        from distill.pipeline.costs import CostTracker, TokenUsage

        config = DistillConfig(distill_output_dir=tmp_path / "library")
        log_path = config.library_dir / ".distill" / "cost_log.jsonl"

        save_command_cost(config, "empty", CostTracker())
        assert not log_path.exists()

        tracker = CostTracker()
        tracker.record(
            TokenUsage(
                prompt_tokens=10,
                completion_tokens=5,
                model="qwen3.5:27b",
                provider_name="ollama",
                provider_type="local",
            )
        )
        save_command_cost(config, "local", tracker, estimated_cost=0.0)

        row = json.loads(log_path.read_text(encoding="utf-8"))
        assert row["command"] == "local"
        assert row["actual_cost"] == 0
        assert row["estimated_cost"] == 0
        assert row["usage_ledger"]["no_metered_llm_calls"] == 1

    def test_crossing_call_is_logged_once_before_budget_stop(self, tmp_path):
        from distill.config import DistillConfig
        from distill.pipeline.costs import BudgetExceededError, TokenUsage
        from distill.pipeline.summary import RunSummary, display_summary

        config = DistillConfig(
            distill_output_dir=tmp_path / "library",
            distill_cost_workflow_budgets="video=0.000001",
        )
        tracker = budgeted_cost_tracker(config, "video")

        with pytest.raises(BudgetExceededError):
            tracker.record(
                TokenUsage(
                    prompt_tokens=1_000,
                    completion_tokens=1_000,
                    model="grok-4.3",
                    provider_name="xai",
                    provider_type="metered-api",
                )
            )

        summary = RunSummary(command="video")
        summary.add_issue("budget", "stopped after the crossing call")
        save_command_cost(config, "video", tracker)
        display_summary(summary, cost_tracker=tracker, log_dir=config.library_dir)

        log_path = config.library_dir / ".distill" / "cost_log.jsonl"
        rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 1
        assert rows[0]["command"] == "video"
        assert rows[0]["actual_cost"] > 0
        assert rows[0]["metadata"] == {
            "workflow": "video",
            "terminal": "budget_exceeded",
        }


class TestEnsureUtf8Stdio:
    def test_calls_reconfigure_on_capable_streams(self, monkeypatch):
        calls = []

        class FakeStream:
            def reconfigure(self, **kwargs):
                calls.append(kwargs)

        fake_out = FakeStream()
        fake_err = FakeStream()
        monkeypatch.setattr(sys, "stdout", fake_out)
        monkeypatch.setattr(sys, "stderr", fake_err)

        ensure_utf8_stdio()

        assert calls == [
            {"encoding": "utf-8", "errors": "replace", "line_buffering": True},
            {"encoding": "utf-8", "errors": "replace", "line_buffering": True},
        ]

    def test_silent_when_stream_lacks_reconfigure(self, monkeypatch):
        # pytest's capsys streams don't expose reconfigure -- must not raise.
        class StreamWithoutReconfigure:
            def write(self, *_args, **_kwargs):
                pass

        monkeypatch.setattr(sys, "stdout", StreamWithoutReconfigure())
        monkeypatch.setattr(sys, "stderr", StreamWithoutReconfigure())

        # Should not raise.
        ensure_utf8_stdio()

    def test_swallows_oserror_from_underlying_buffer(self, monkeypatch):
        class FlakyStream:
            def reconfigure(self, **_kwargs):
                raise OSError("buffer not seekable")

        monkeypatch.setattr(sys, "stdout", FlakyStream())
        monkeypatch.setattr(sys, "stderr", FlakyStream())

        # Should not raise.
        ensure_utf8_stdio()


class TestFormatDate:
    def test_yyyymmdd(self):
        result = format_date("20250115")
        assert "Jan" in result
        assert "2025" in result

    def test_iso_datetime(self):
        result = format_date("2025-01-15T10:30:00")
        assert "Jan" in result
        assert "2025" in result

    def test_invalid_returns_original(self):
        assert format_date("not-a-date") == "not-a-date"

    def test_empty_returns_unknown(self):
        assert format_date("") == "Unknown"

    def test_none_returns_unknown(self):
        assert format_date(None) == "Unknown"


class TestDurationStr:
    def test_seconds(self):
        assert duration_str(45) == "45s"

    def test_zero_seconds(self):
        assert duration_str(0) == "0s"

    def test_minutes(self):
        assert duration_str(120) == "2m"

    def test_hours_and_minutes(self):
        assert duration_str(3720) == "1h 2m"

    def test_none(self):
        assert duration_str(None) == "?"

    def test_negative(self):
        assert duration_str(-5) == "?"

    def test_string_input(self):
        assert duration_str("hello") == "?"

    def test_float(self):
        assert duration_str(90.5) == "1m"


class TestOutputPath:
    def test_creates_output_dir_and_returns_path(self, config):
        result = output_path(config, "report.md")
        assert result.name == "report.md"
        assert result.parent.name == "output"
        assert result.parent.exists()

    def test_returns_correct_parent(self, config):
        result = output_path(config, "test.txt")
        assert result.parent == config.library_dir.parent / "output"

    def test_sanitizes_pathlike_filename(self, config):
        result = output_path(config, "../escape.txt")

        assert result.parent == config.library_dir.parent / "output"
        assert result.name == "-escape.txt"
        assert not (config.library_dir.parent / "escape.txt").exists()


class TestTopicFromQuery:
    def test_normal_query(self):
        result = topic_from_query("Microsoft Fabric best practices")
        assert result
        assert " " not in result  # should be slugified

    def test_empty_query(self):
        assert topic_from_query("") == "research"


class TestDetectRampSource:
    def test_routes_known_public_hosts(self):
        assert _detect_ramp_source("https://arxiv.org/abs/2601.00001") == "paper"
        assert _detect_ramp_source("https://www.youtube.com/watch?v=abc") == "youtube-url"
        assert _detect_ramp_source("https://youtu.be/abc") == "youtube-url"
        assert _detect_ramp_source("https://example.com/page") == "website"

    def test_rejects_lookalike_hosts(self):
        assert _detect_ramp_source("https://arxiv.org.evil/abs/2601.00001") == "website"
        assert _detect_ramp_source("https://youtube.com.evil/watch?v=abc") == "website"
        assert _detect_ramp_source("https://youtu.be.evil/abc") == "website"


class TestResolveRequiredTopicForChannel:
    def test_preserves_explicit_topic_and_channel(self):
        calls = []
        lib = SimpleNamespace(
            get_topics=lambda: ["ai"],
            find_channel=lambda name: calls.append(name),
        )

        topic, channel = _resolve_required_topic_for_channel(lib, "ai", "NateBJones")

        assert topic == "ai"
        assert channel == "NateBJones"
        assert calls == []

    def test_preserves_known_topic_without_channel(self):
        calls = []
        lib = SimpleNamespace(
            get_topics=lambda: ["ai"],
            find_channel=lambda name: calls.append(name),
        )

        topic, channel = _resolve_required_topic_for_channel(lib, "ai", None)

        assert topic == "ai"
        assert channel is None
        assert calls == []

    def test_resolves_channel_name_to_topic(self):
        lib = SimpleNamespace(
            get_topics=lambda: ["ai"],
            find_channel=lambda name: SimpleNamespace(topic="research", name=name),
        )

        topic, channel = _resolve_required_topic_for_channel(lib, "NateBJones", None)

        assert topic == "research"
        assert channel == "NateBJones"

    def test_resolves_explicit_channel_to_topic(self):
        lib = SimpleNamespace(
            get_topics=lambda: ["ai"],
            find_channel=lambda name: SimpleNamespace(topic="research", name=name),
        )

        topic, channel = _resolve_required_topic_for_channel(lib, None, "NateBJones")

        assert topic == "research"
        assert channel == "NateBJones"

    def test_keeps_unknown_topic_when_no_channel_matches(self):
        lib = SimpleNamespace(
            get_topics=lambda: ["ai"],
            find_channel=lambda _name: None,
        )

        topic, channel = _resolve_required_topic_for_channel(lib, "ghost-topic", None)

        assert topic == "ghost-topic"
        assert channel is None

    def test_rejects_unknown_channel_without_topic(self):
        lib = SimpleNamespace(
            get_topics=lambda: ["ai"],
            find_channel=lambda _name: None,
        )

        with pytest.raises(typer.BadParameter, match="Topic is required"):
            _resolve_required_topic_for_channel(lib, None, "ghost-channel")

    def test_rejects_missing_topic_after_resolution(self):
        lib = SimpleNamespace(
            get_topics=lambda: [],
            find_channel=lambda _name: None,
        )

        with pytest.raises(typer.BadParameter, match="Topic is required"):
            _resolve_required_topic_for_channel(lib, None, None)


class TestTopicWatchHelpers:
    def test_topic_watch_name_prefers_explicit_name(self):
        assert topic_watch_name("Microsoft AI news", "microsoft-ai", "daily-ai") == "daily-ai"

    def test_topic_watch_name_falls_back_to_topic_or_query_slug(self):
        assert topic_watch_name("Microsoft AI news", "microsoft-ai", None) == "microsoft-ai"
        assert topic_watch_name("Microsoft AI news", None, None) == "microsoft-ai-news"

    def test_topic_watch_ranking_strategy_normalizes_aliases(self):
        assert normalize_topic_watch_ranking_mode("fresh") == "freshness"
        assert topic_watch_ranking_strategy("popular") == {
            "mode": "popularity",
            "sort": "relevance",
            "rerank": False,
            "label": "popularity-biased",
        }
        assert topic_watch_ranking_strategy("balanced")["rerank"] is True

    def test_topic_watch_ranking_rejects_unknown_mode(self):
        with pytest.raises(typer.BadParameter, match="ranking mode"):
            normalize_topic_watch_ranking_mode("random")


class TestWriteVideoMetadata:
    def test_writes_correct_json(self, tmp_path):
        vid_dir = tmp_path / "video1"
        vid_dir.mkdir()
        video = SimpleNamespace(
            video_id="abc123",
            title="Test Video",
            upload_date="20250101",
            duration=600,
            url="https://youtube.com/watch?v=abc123",
        )
        write_video_metadata(vid_dir, video, "TestChannel", "full")

        meta_file = vid_dir / "metadata.json"
        assert meta_file.exists()
        data = json.loads(meta_file.read_text(encoding="utf-8"))
        assert data["video_id"] == "abc123"
        assert data["title"] == "Test Video"
        assert data["channel"] == "TestChannel"
        assert data["analysis_mode"] == "full"

    def test_uses_video_channel_name_attr(self, tmp_path):
        vid_dir = tmp_path / "video2"
        vid_dir.mkdir()
        video = SimpleNamespace(
            video_id="xyz",
            title="V",
            upload_date="20250101",
            duration=300,
            url="https://youtube.com/watch?v=xyz",
            channel_name="FromAttr",
        )
        write_video_metadata(vid_dir, video, "Fallback")

        data = json.loads((vid_dir / "metadata.json").read_text(encoding="utf-8"))
        assert data["channel"] == "FromAttr"


class TestRequireApiKey:
    def test_raises_on_empty(self):
        # require_api_key raises typer.Exit. Catch that directly rather than
        # click.exceptions.Exit: typer >=0.26 vendors its own click, so
        # typer.Exit is no longer identical to click.exceptions.Exit.
        import typer

        with pytest.raises(typer.Exit):
            require_api_key("", "Key missing")

    def test_raises_on_none(self):
        import typer

        with pytest.raises(typer.Exit):
            require_api_key(None, "Key missing")

    def test_passes_on_value(self):
        require_api_key("sk-test-123", "Key missing")  # should not raise


class TestStripFrontmatter:
    def test_with_frontmatter(self):
        content = '---\ntitle: "Test"\n---\n\n## Summary\nHello'
        result = strip_frontmatter(content)
        assert result == "## Summary\nHello"

    def test_without_frontmatter(self):
        content = "## Summary\nHello"
        assert strip_frontmatter(content) == content

    def test_incomplete_frontmatter(self):
        content = "---\ntitle: Test\nNo closing"
        assert strip_frontmatter(content) == content


class TestSafeConsoleRendering:
    def test_safe_console_text_replaces_unencodable_characters(self):
        console = SimpleNamespace(file=SimpleNamespace(encoding="cp1252"))

        assert safe_console_text(console, "A → B") == "A ? B"

    def test_print_markdown_safely_uses_plain_text_on_legacy_windows(self):
        class DummyConsole:
            def __init__(self):
                self.file = SimpleNamespace(encoding="cp1252")
                self.legacy_windows = True
                self.calls = []

            def print(self, obj, *args, **kwargs):
                self.calls.append((obj, kwargs))

        console = DummyConsole()
        print_markdown_safely(console, "A → B")

        assert console.calls == [("A ? B", {"markup": False})]

    def test_print_markdown_safely_falls_back_and_records_warning(self):
        from distill.pipeline.summary import RunSummary

        summary = RunSummary(command="test")

        class DummyConsole:
            def __init__(self):
                self.file = SimpleNamespace(encoding="cp1252")
                self.legacy_windows = False
                self.calls = []
                self._first = True

            def print(self, obj, *args, **kwargs):
                self.calls.append((obj, kwargs))
                if self._first:
                    self._first = False
                    raise UnicodeEncodeError("cp1252", "→", 0, 1, "bad char")

        console = DummyConsole()
        print_markdown_safely(
            console,
            "A → B",
            summary=summary,
            stage="render-preview-content",
            context="video-1",
            details={"title": "Test"},
        )

        assert console.calls[-1][0] == "A ? B"
        assert console.calls[-1][1]["markup"] is False
        assert summary.issue_count == 1
        issue = summary.issues[0]
        assert issue.severity == "warning"
        assert issue.stage == "render-preview-content"
        assert issue.exception_type == "UnicodeEncodeError"


class TestResolveVideoChannelName:
    def test_url_with_at_sign(self):
        def fallback(url):
            return "ResolvedChannel"

        result = resolve_video_channel_name(
            "https://www.youtube.com/@SomeChannel/videos",
            SimpleNamespace(channel_name=""),
            fallback,
        )
        assert result == "ResolvedChannel"

    def test_from_video_info(self):
        result = resolve_video_channel_name(
            "https://www.youtube.com/watch?v=abc",
            SimpleNamespace(channel_name="InfoChannel"),
            lambda url: "Fallback",
        )
        assert result == "InfoChannel"

    def test_fallback_to_standalone(self, monkeypatch):
        """When video_info has no channel and yt_dlp fails, returns 'standalone'."""
        # Make yt_dlp import fail
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "yt_dlp":
                raise ImportError("no yt_dlp")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        result = resolve_video_channel_name(
            "https://www.youtube.com/watch?v=abc",
            SimpleNamespace(channel_name=""),
            lambda url: "Fallback",
        )
        assert result == "standalone"

    def test_yt_dlp_metadata_falls_back_when_channel_fields_are_not_strings(self, monkeypatch):
        class FakeYDL:
            def __init__(self, _options):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def extract_info(self, _url, *, download):
                assert download is False
                return {"channel": None, "uploader": 123}

        monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYDL))

        result = resolve_video_channel_name(
            "https://www.youtube.com/watch?v=abc",
            SimpleNamespace(channel_name=""),
            lambda url: "Fallback",
        )

        assert result == "standalone"

    def test_yt_dlp_metadata_uses_uploader_string_when_channel_missing(self, monkeypatch):
        class FakeYDL:
            def __init__(self, _options):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def extract_info(self, _url, *, download):
                assert download is False
                return {"uploader": "UploaderChannel"}

        monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYDL))

        result = resolve_video_channel_name(
            "https://www.youtube.com/watch?v=abc",
            SimpleNamespace(channel_name=""),
            lambda url: "Fallback",
        )

        assert result == "UploaderChannel"


class TestEnsureChannelContext:
    def test_creates_context_file(self, config, monkeypatch):
        from distill.cli_shared import ensure_channel_context
        from distill.pipeline.costs import CostTracker

        monkeypatch.setattr(
            "distill.commands._helpers.generate_channel_context",
            lambda *a, **kw: "# Channel Context\nTest channel",
        )
        videos = [SimpleNamespace(title="Video 1"), SimpleNamespace(title="Video 2")]
        tracker = CostTracker()

        ensure_channel_context("ai", "TestCh", videos, config, tracker)

        ctx_file = config.channel_dir("ai", "TestCh") / "channel_context.md"
        assert ctx_file.exists()
        assert "Channel Context" in ctx_file.read_text(encoding="utf-8")

    def test_skips_if_exists(self, config, monkeypatch):
        from distill.cli_shared import ensure_channel_context
        from distill.pipeline.costs import CostTracker

        ch_dir = config.channel_dir("ai", "TestCh")
        ch_dir.mkdir(parents=True, exist_ok=True)
        ctx_file = ch_dir / "channel_context.md"
        ctx_file.write_text("Existing", encoding="utf-8")

        called = []
        monkeypatch.setattr(
            "distill.commands._helpers.generate_channel_context",
            lambda *a, **kw: called.append(1) or "New",
        )

        ensure_channel_context("ai", "TestCh", [], config, CostTracker())
        assert not called
        assert ctx_file.read_text(encoding="utf-8") == "Existing"


class TestProcessVideo:
    def _make_video(self, duration=600):
        return SimpleNamespace(
            video_id="test123",
            title="Test Video Title",
            upload_date="20250101",
            duration=duration,
            url="https://youtube.com/watch?v=test123",
        )

    def test_no_transcript_returns_false(self, config, monkeypatch):
        from distill.cli_shared import process_video
        from distill.pipeline.costs import CostTracker
        from distill.pipeline.summary import RunSummary

        monkeypatch.setattr("distill.commands._helpers.get_transcript", lambda *a, **kw: False)

        video = self._make_video()
        summary = RunSummary(command="test")
        tracker = CostTracker()

        result = process_video("ai", "TestCh", video, config, tracker, summary)
        assert result is False
        assert summary.failed == 1
        assert summary.results[0].error == "No transcript"

    def test_empty_transcript_returns_false(self, config, monkeypatch):
        from distill.cli_shared import process_video
        from distill.pipeline.costs import CostTracker
        from distill.pipeline.summary import RunSummary

        # Create empty transcript
        vid_dir = config.video_dir_slug("ai", "TestCh", "Test Video Title", "test123")
        vid_dir.mkdir(parents=True, exist_ok=True)
        (vid_dir / "transcript.txt").write_text("", encoding="utf-8")

        video = self._make_video()
        summary = RunSummary(command="test")

        result = process_video("ai", "TestCh", video, config, CostTracker(), summary)
        assert result is False
        assert summary.results[0].error == "Empty transcript"

    def test_successful_analysis(self, config, monkeypatch):
        from distill.cli_shared import process_video
        from distill.pipeline.costs import CostTracker
        from distill.pipeline.summary import RunSummary

        # Create transcript
        vid_dir = config.video_dir_slug("ai", "TestCh", "Test Video Title", "test123")
        vid_dir.mkdir(parents=True, exist_ok=True)
        (vid_dir / "transcript.txt").write_text("This is a test transcript.", encoding="utf-8")

        monkeypatch.setattr(
            "distill.commands._helpers.analyze_video", lambda *a, **kw: "# Insights\nTest"
        )

        video = self._make_video()
        summary = RunSummary(command="test")

        result = process_video("ai", "TestCh", video, config, CostTracker(), summary)
        assert result is True
        assert summary.passed == 1
        from distill.library.paths import find_artifact

        insights = find_artifact(vid_dir, "insights")
        assert insights.name == "test_video_title_test123_Insights.md"
        assert insights.exists()
        assert 'type: "insights"' in insights.read_text(encoding="utf-8")

    def test_video_verification_evidence_includes_fetched_metadata(self):
        from distill.commands._helpers import _video_verification_evidence

        evidence = _video_verification_evidence(
            self._make_video(),
            "TestCh",
            "Transcript receipt.",
            analysis_mode="full",
        )

        assert '"title": "Test Video Title"' in evidence
        assert '"channel": "TestCh"' in evidence
        assert '"upload_date": "20250101"' in evidence
        assert '"upload_date_display": "Jan 01, 2025"' in evidence
        assert '"duration": 600' in evidence
        assert '"url": "https://youtube.com/watch?v=test123"' in evidence
        assert evidence.endswith("Video transcript:\nTranscript receipt.")

    def test_verify_accepts_year_from_fetched_upload_metadata(self, config, monkeypatch):
        from distill.cli_shared import process_video
        from distill.library.paths import find_artifact
        from distill.pipeline.costs import CostTracker
        from distill.pipeline.summary import RunSummary

        config.distill_verify = "strict"
        video = self._make_video()
        vid_dir = config.video_dir_slug("ai", "TestCh", video.title, video.video_id)
        vid_dir.mkdir(parents=True, exist_ok=True)
        (vid_dir / "transcript.txt").write_text(
            "The speaker discusses release planning without stating a year.",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "distill.commands._helpers.analyze_video",
            lambda *args, **kwargs: "# Insights\n\nThe video was uploaded in 2025.",
        )
        monkeypatch.setattr("distill.pipeline.verify._entailment_checker", lambda: None)

        result = process_video(
            "ai", "TestCh", video, config, CostTracker(), RunSummary(command="test")
        )

        assert result is True
        assert find_artifact(vid_dir, "insights").exists()
        sidecar = next(vid_dir.glob("*_Verify.json"))
        report = json.loads(sidecar.read_text(encoding="utf-8"))
        assert report["checked"] == 1
        assert report["supported"] == 1
        assert report["unsupported"] == []
        assert report["source"] == (
            "metadata.json + transcript.txt (upload date normalized for verification)"
        )

    def test_verify_still_refuses_year_absent_from_metadata_and_transcript(
        self, config, monkeypatch
    ):
        from distill.cli_shared import process_video
        from distill.library.paths import find_artifact
        from distill.pipeline.costs import CostTracker
        from distill.pipeline.summary import RunSummary

        config.distill_verify = "strict"
        video = self._make_video()
        vid_dir = config.video_dir_slug("ai", "TestCh", video.title, video.video_id)
        vid_dir.mkdir(parents=True, exist_ok=True)
        (vid_dir / "transcript.txt").write_text(
            "The speaker discusses release planning without stating a year.",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "distill.commands._helpers.analyze_video",
            lambda *args, **kwargs: "# Insights\n\nThe video predicts a release in 2037.",
        )
        monkeypatch.setattr("distill.pipeline.verify._entailment_checker", lambda: None)

        result = process_video(
            "ai", "TestCh", video, config, CostTracker(), RunSummary(command="test")
        )

        assert result is False
        assert not find_artifact(vid_dir, "insights").exists()
        sidecar = next(vid_dir.glob("*_Verify.json"))
        report = json.loads(sidecar.read_text(encoding="utf-8"))
        assert report["supported"] == 0
        assert [claim["token"] for claim in report["unsupported"]] == ["2037"]

    def test_short_video_uses_short_analysis(self, config, monkeypatch):
        from distill.cli_shared import process_video
        from distill.pipeline.costs import CostTracker
        from distill.pipeline.summary import RunSummary

        video = self._make_video(duration=60)  # Short
        vid_dir = config.video_dir_slug("ai", "TestCh", video.title, video.video_id)
        vid_dir.mkdir(parents=True, exist_ok=True)
        (vid_dir / "transcript.txt").write_text("Short content", encoding="utf-8")

        called_with = {}
        monkeypatch.setattr(
            "distill.commands._helpers.analyze_short",
            lambda *a, **kw: called_with.update({"called": True}) or "# Short",
        )

        summary = RunSummary(command="test")

        result = process_video("ai", "TestCh", video, config, CostTracker(), summary)
        assert result is True
        assert called_with.get("called")

    def test_scan_mode(self, config, monkeypatch):
        from distill.cli_shared import process_video
        from distill.pipeline.costs import CostTracker
        from distill.pipeline.summary import RunSummary

        video = self._make_video()
        vid_dir = config.video_dir_slug("ai", "TestCh", video.title, video.video_id)
        vid_dir.mkdir(parents=True, exist_ok=True)
        (vid_dir / "transcript.txt").write_text("Scan content here", encoding="utf-8")

        called_with = {}
        monkeypatch.setattr(
            "distill.commands._helpers.analyze_scan",
            lambda *a, **kw: called_with.update({"called": True}) or "# Scan",
        )

        summary = RunSummary(command="test")

        result = process_video(
            "ai", "TestCh", video, config, CostTracker(), summary, analysis_mode="scan"
        )
        assert result is True
        assert called_with.get("called")

    def test_analysis_failure(self, config, monkeypatch):
        from distill.cli_shared import process_video
        from distill.pipeline.costs import CostTracker
        from distill.pipeline.summary import RunSummary

        video = self._make_video()
        vid_dir = config.video_dir_slug("ai", "TestCh", video.title, video.video_id)
        vid_dir.mkdir(parents=True, exist_ok=True)
        (vid_dir / "transcript.txt").write_text("Content here", encoding="utf-8")

        def raise_error(*a, **kw):
            raise RuntimeError("API error")

        monkeypatch.setattr("distill.commands._helpers.analyze_video", raise_error)
        summary = RunSummary(command="test")

        result = process_video("ai", "TestCh", video, config, CostTracker(), summary)
        assert result is False
        assert "API error" in summary.results[0].error

    def test_budget_exceeded_is_hard_stop(self, config, monkeypatch):
        from distill.cli_shared import process_video
        from distill.pipeline.costs import BudgetExceededError, CostTracker
        from distill.pipeline.summary import RunSummary

        video = self._make_video()
        vid_dir = config.video_dir_slug("ai", "TestCh", video.title, video.video_id)
        vid_dir.mkdir(parents=True, exist_ok=True)
        (vid_dir / "transcript.txt").write_text("Content here", encoding="utf-8")

        def raise_budget(*_args, **_kwargs):
            raise BudgetExceededError(0.6, 0.5)

        monkeypatch.setattr("distill.commands._helpers.analyze_video", raise_budget)
        summary = RunSummary(command="test")

        with pytest.raises(BudgetExceededError):
            process_video("ai", "TestCh", video, config, CostTracker(), summary)
        assert summary.results == []

    @pytest.mark.parametrize(
        "error",
        [
            pytest.param(
                CostPolicyError("route blocked"),
                id="cost-policy",
            ),
            pytest.param(
                ProviderBusyTimeoutError(
                    provider="ollama",
                    requested_model="qwen3.5:27b",
                    active_models=("other:latest",),
                    timeout_seconds=1,
                ),
                id="provider-busy",
            ),
        ],
    )
    def test_operational_errors_are_hard_stops(self, config, monkeypatch, error):
        from distill.cli_shared import process_video
        from distill.pipeline.costs import CostTracker
        from distill.pipeline.summary import RunSummary

        video = self._make_video()
        vid_dir = config.video_dir_slug("ai", "TestCh", video.title, video.video_id)
        vid_dir.mkdir(parents=True, exist_ok=True)
        (vid_dir / "transcript.txt").write_text("Content here", encoding="utf-8")

        def raise_operational(*_args, **_kwargs):
            raise error

        monkeypatch.setattr("distill.commands._helpers.analyze_video", raise_operational)
        summary = RunSummary(command="test")

        with pytest.raises(type(error)):
            process_video("ai", "TestCh", video, config, CostTracker(), summary)
        assert summary.results == []


class TestHelperRecording:
    def test_record_output_or_issue_records_existing_output(self, tmp_path):
        from distill.cli_shared import record_output_or_issue
        from distill.pipeline.summary import RunSummary

        summary = RunSummary(command="test")
        output_file = tmp_path / "insights.md"
        output_file.write_text("x", encoding="utf-8")

        result = record_output_or_issue(
            summary,
            output_file,
            stage="report",
            context="ai",
            missing_message="missing",
        )

        assert result is True
        assert summary.output_files == [output_file.resolve()]
        assert summary.issue_count == 0

    def test_record_output_or_issue_records_missing_issue(self, tmp_path):
        from distill.cli_shared import record_output_or_issue
        from distill.pipeline.summary import RunSummary

        summary = RunSummary(command="test")

        result = record_output_or_issue(
            summary,
            tmp_path / "missing.md",
            stage="report",
            context="ai",
            details={"scope": "topic"},
            missing_message="missing output",
            severity="warning",
        )

        assert result is False
        assert summary.issue_count == 1
        issue = summary.issues[0]
        assert issue.severity == "warning"
        assert issue.details == (("scope", "topic"),)


class TestProcessVideoAdvanced:
    def test_successful_analysis_prints_persistent_progress(self, config, monkeypatch):
        from distill.cli_shared import process_video
        from distill.pipeline.costs import CostTracker
        from distill.pipeline.summary import ETATracker, RunSummary

        video = SimpleNamespace(
            video_id="progress123",
            title="Progress Video",
            upload_date="20250101",
            duration=600,
            url="https://youtube.com/watch?v=progress123",
        )
        vid_dir = config.video_dir_slug("ai", "TestCh", video.title, video.video_id)
        vid_dir.mkdir(parents=True, exist_ok=True)
        (vid_dir / "transcript.txt").write_text("Transcript content", encoding="utf-8")

        monkeypatch.setattr(
            "distill.commands._helpers.analyze_video",
            lambda *a, **kw: "# Insights\nDetailed",
        )
        progress_console = Console(record=True, width=120)
        monkeypatch.setattr("distill.commands._helpers.console", progress_console)

        result = process_video(
            "ai",
            "TestCh",
            video,
            config,
            CostTracker(),
            RunSummary(command="test"),
            eta=ETATracker(total=1),
        )

        assert result is True
        rendered = progress_console.export_text()
        assert "progress | completed 1/1 | failed 0 | spent $0.0000" in rendered

    def test_successful_analysis_marks_state_and_ticks_eta(self, config, monkeypatch):
        from distill.cli_shared import process_video
        from distill.library.state import ChannelState
        from distill.pipeline.costs import CostTracker
        from distill.pipeline.summary import RunSummary

        video = SimpleNamespace(
            video_id="eta123",
            title="ETA Video",
            upload_date="20250101",
            duration=600,
            url="https://youtube.com/watch?v=eta123",
        )
        vid_dir = config.video_dir_slug("ai", "TestCh", video.title, video.video_id)
        vid_dir.mkdir(parents=True, exist_ok=True)
        (vid_dir / "transcript.txt").write_text("Transcript content", encoding="utf-8")

        monkeypatch.setattr(
            "distill.commands._helpers.analyze_video",
            lambda *a, **kw: "# Insights\nDetailed",
        )

        state = ChannelState(config.channel_dir("ai", "TestCh") / "state.json")
        summary = RunSummary(command="test")

        class DummyETA:
            def __init__(self):
                self.started = False
                self.ticks = []

            def start(self):
                self.started = True
                return 123.0

            def tick(self, start_time):
                self.ticks.append(start_time)

            def progress_str(self, current_step=""):
                return f"eta:{current_step}"

        eta = DummyETA()
        result = process_video(
            "ai", "TestCh", video, config, CostTracker(), summary, state=state, eta=eta
        )

        assert result is True
        assert eta.started is True
        assert eta.ticks == [123.0]
        assert state.is_processed(video.video_id) is True
        assert summary.passed == 1


class TestRunScopeReport:
    def test_missing_gemini_key_adds_warning_issue(self, config):
        from pydantic import SecretStr

        from distill.cli_shared import run_scope_report
        from distill.pipeline.costs import CostTracker
        from distill.pipeline.summary import RunSummary

        config.gemini_api_key = SecretStr("")
        summary = RunSummary(command="report")

        run_scope_report("ai", config, CostTracker(), scope="topic", summary=summary)

        assert summary.issue_count == 1
        issue = summary.issues[0]
        assert issue.severity == "warning"
        assert issue.message.startswith("GEMINI_API_KEY required")

    def test_research_without_result_adds_issue(self, config, monkeypatch):
        from distill.cli_shared import run_scope_report
        from distill.pipeline.costs import CostTracker
        from distill.pipeline.summary import RunSummary

        monkeypatch.setitem(
            sys.modules,
            "distill.pipeline.report.accordion",
            SimpleNamespace(run_accordion_research=lambda **kwargs: ""),
        )
        monkeypatch.setitem(
            sys.modules,
            "distill.pipeline.report.deep_research",
            SimpleNamespace(
                _get_report_path=lambda *args, **kwargs: config.topic_dir("ai") / "report.md"
            ),
        )
        summary = RunSummary(command="report")

        run_scope_report("ai", config, CostTracker(), scope="topic", summary=summary)

        assert summary.issue_count == 1
        assert summary.issues[0].stage == "report"
        assert summary.issues[0].message == "Research did not produce results"

    def test_successful_report_copies_markdown_and_records_docx_failure(self, config, monkeypatch):
        from distill.cli_shared import run_scope_report
        from distill.pipeline.costs import CostTracker
        from distill.pipeline.summary import RunSummary

        md_source = config.topic_dir("ai") / "report.md"
        md_source.parent.mkdir(parents=True, exist_ok=True)
        md_source.write_text("# Report\nBody", encoding="utf-8")

        monkeypatch.setitem(
            sys.modules,
            "distill.pipeline.report.accordion",
            SimpleNamespace(run_accordion_research=lambda **kwargs: "report body words"),
        )
        monkeypatch.setitem(
            sys.modules,
            "distill.pipeline.report.deep_research",
            SimpleNamespace(_get_report_path=lambda *args, **kwargs: md_source),
        )

        def fail_export(*args, **kwargs):
            raise RuntimeError("docx boom")

        monkeypatch.setattr("distill.library.export.export_report", fail_export)
        summary = RunSummary(command="report")

        run_scope_report("ai", config, CostTracker(), scope="topic", summary=summary)

        output_md = config.library_dir.parent / "output" / "report-ai.md"
        assert output_md.exists()
        assert summary.issue_count == 1
        assert summary.issues[0].stage == "report-docx"
        assert dict(summary.issues[0].details)["output"].endswith("report-ai.docx")
        assert any(path.name == "report-ai.md" for path in summary.output_files)

    def test_successful_report_logs_only_report_cost_delta(self, config, monkeypatch):
        import json

        from distill.cli_shared import run_scope_report
        from distill.pipeline.costs import CostTracker, TokenUsage
        from distill.pipeline.summary import RunSummary

        md_source = config.topic_dir("ai") / "report.md"
        md_source.parent.mkdir(parents=True, exist_ok=True)
        md_source.write_text("# Report\nBody", encoding="utf-8")

        def fake_report(**kwargs):
            kwargs["tracker"].record_gemini_query()
            return "report body words"

        monkeypatch.setitem(
            sys.modules,
            "distill.pipeline.report.accordion",
            SimpleNamespace(run_accordion_research=fake_report),
        )
        monkeypatch.setitem(
            sys.modules,
            "distill.pipeline.report.deep_research",
            SimpleNamespace(_get_report_path=lambda *args, **kwargs: md_source),
        )
        monkeypatch.setattr("distill.library.export.export_report", lambda *args, **kwargs: None)

        tracker = CostTracker()
        tracker.record(
            TokenUsage(
                prompt_tokens=1_000_000,
                completion_tokens=0,
                model="grok-4.3",
                call_type="preexisting",
            )
        )
        summary = RunSummary(command="site")

        run_scope_report("ai", config, tracker, scope="topic", summary=summary)

        log_path = config.library_dir / ".distill" / "cost_log.jsonl"
        entry = json.loads(log_path.read_text(encoding="utf-8").strip())
        assert entry["command"] == "report"
        assert entry["gemini_queries"] == 1
        assert entry["total_input_tokens"] == 0
        assert entry["metadata"]["workflow"] == "report"
