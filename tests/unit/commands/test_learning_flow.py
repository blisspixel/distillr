import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import typer
from pydantic import SecretStr

from distill.commands import _learning_flow as learning_flow
from distill.commands._json import ExitCode
from distill.config import DistillConfig
from distill.ingestors.youtube.discovery import VideoInfo
from distill.library import Library
from distill.pipeline.costs import BudgetExceededError, CostTracker, TokenUsage
from distill.pipeline.summary import RunSummary


@dataclass
class _Selected:
    video: VideoInfo
    final_score: float = 0.9
    rationale: str = "best fit"


def _selected_video(
    video_id: str,
    title: str,
    *,
    channel_name: str = "Creator",
    channel_url: str = "https://www.youtube.com/@creator",
    upload_date: str = "20260420",
    duration: int = 900,
) -> learning_flow._SelectedVideo:
    return _Selected(
        video=VideoInfo(
            video_id=video_id,
            title=title,
            channel_name=channel_name,
            channel_url=channel_url,
            upload_date=upload_date,
            duration=duration,
            url=f"https://www.youtube.com/watch?v={video_id}",
        )
    )


def test_validate_learning_options_rejects_bad_values():
    invalid_options = [
        ("weird", 1, 1, 1, None),
        ("date", 1, 1, 1, 0),
        ("date", 0, 1, 1, None),
        ("date", 1, 0, 1, None),
        ("date", 1, 1, 0, None),
    ]
    for sort, limit, days, per_channel_cap, hours in invalid_options:
        with pytest.raises(typer.Exit) as excinfo:
            learning_flow.validate_learning_options(
                sort,
                limit,
                days,
                per_channel_cap,
                hours=hours,
            )
        assert excinfo.value.exit_code == int(ExitCode.USAGE_ERROR)
    learning_flow.validate_learning_options("date", 1, 1, 1, hours=1)


def test_preview_learning_selection_returns_selected_items(config):
    tracker = CostTracker()
    selected = [_selected_video("v1", "Video One")]
    displayed = {}
    selection_kwargs = {}

    returned_config, returned_tracker, returned_selected = learning_flow.preview_learning_selection(
        "Claude Code leak",
        days=3,
        limit=5,
        sort="date",
        per_channel_cap=2,
        shorts=True,
        rerank=True,
        header="Latest",
        table_title="Preview",
        get_config=lambda: config,
        cost_tracker_factory=lambda: tracker,
        auto_skeptical_mode=lambda query, **kwargs: True,
        window_label=lambda days, hours: f"{days}d",
        select_learning_videos=lambda *args, **kwargs: (
            selection_kwargs.update(kwargs),
            selected,
        ),
        display_ranked_videos=lambda items, title: displayed.update(items=items, title=title),
    )

    assert returned_config is config
    assert returned_tracker is tracker
    assert returned_selected == selected
    assert displayed["title"] == "Preview"
    assert displayed["items"] == selected
    assert selection_kwargs["expand"] is True
    assert selection_kwargs["top_by_date"] is False


def test_preview_learning_selection_exits_when_no_matches(config):
    with pytest.raises(typer.Exit) as excinfo:
        learning_flow.preview_learning_selection(
            "query",
            days=3,
            limit=5,
            sort="date",
            per_channel_cap=2,
            shorts=True,
            rerank=True,
            header="Latest",
            table_title="Preview",
            get_config=lambda: config,
            cost_tracker_factory=CostTracker,
            auto_skeptical_mode=lambda query, **kwargs: False,
            window_label=lambda days, hours: "3d",
            select_learning_videos=lambda *args, **kwargs: ([], []),
            display_ranked_videos=lambda items, title: None,
        )

    assert excinfo.value.exit_code == 0


def test_preview_top_by_date_disables_expansion(config):
    selected = [_selected_video("v1", "Video One")]
    captured = {}

    learning_flow.preview_learning_selection(
        "query",
        days=3,
        limit=5,
        sort="date",
        per_channel_cap=2,
        shorts=True,
        rerank=True,
        header="Latest",
        table_title="Preview",
        get_config=lambda: config,
        cost_tracker_factory=CostTracker,
        auto_skeptical_mode=lambda *args, **kwargs: pytest.fail(
            "explicit skeptical mode must bypass inference"
        ),
        window_label=lambda days, hours: "3d",
        select_learning_videos=lambda *args, **kwargs: (
            captured.update(kwargs),
            selected,
        ),
        display_ranked_videos=lambda *args, **kwargs: None,
        skeptical=False,
        top_by_date=True,
    )

    assert captured["expand"] is False
    assert captured["top_by_date"] is True
    assert captured["skeptical"] is False


def test_run_learning_command_requires_a_model(tmp_path, monkeypatch):
    # No usable model for any workload: the flagship command exits cleanly. Force
    # an unimplemented provider so "no model" is deterministic and
    # independent of any ambient cloud key.
    monkeypatch.setenv("DISTILL_PROVIDER", "openai")
    no_key_config = DistillConfig(
        xai_api_key=SecretStr(""),
        gemini_api_key=SecretStr(""),
        anthropic_api_key=SecretStr(""),
        distill_output_dir=tmp_path,
    )

    with pytest.raises(typer.Exit) as excinfo:
        learning_flow.run_learning_command(
            "query",
            topic=None,
            days=3,
            limit=5,
            sort="date",
            per_channel_cap=2,
            shorts=True,
            rerank=True,
            save=False,
            report=False,
            test=False,
            generate_brief=False,
            header="Latest",
            get_config=lambda: no_key_config,
            cost_tracker_factory=CostTracker,
            topic_from_query=lambda query: "topic",
            auto_skeptical_mode=lambda query, **kwargs: False,
            default_report_focus=lambda query, skeptical: None,
            window_label=lambda days, hours: "3d",
            select_learning_videos=lambda *args, **kwargs: ([], []),
            display_ranked_videos=lambda items, title: None,
            process_learning_selection=lambda *args, **kwargs: None,
        )

    assert excinfo.value.exit_code == 1


def test_run_learning_command_processes_selected_items(config):
    tracker = CostTracker()
    selected = [_selected_video("v1", "Video One")]
    captured = {}

    learning_flow.run_learning_command(
        "query text",
        topic=None,
        days=3,
        limit=5,
        sort="date",
        per_channel_cap=2,
        shorts=True,
        rerank=True,
        save=True,
        report=True,
        test=False,
        generate_brief=False,
        header="Latest",
        get_config=lambda: config,
        cost_tracker_factory=lambda: tracker,
        topic_from_query=lambda query: "derived-topic",
        auto_skeptical_mode=lambda query, **kwargs: True,
        default_report_focus=lambda query, skeptical: "focus text",
        window_label=lambda days, hours: "3d",
        select_learning_videos=lambda *args, **kwargs: (
            captured.update(selection_kwargs=kwargs),
            selected,
        ),
        display_ranked_videos=lambda items, title: captured.update(
            display_title=title, items=items
        ),
        process_learning_selection=lambda *args, **kwargs: captured.update(
            topic_name=args[0], process_kwargs=kwargs
        ),
    )

    assert captured["display_title"] == "Selected Learning Set"
    assert captured["topic_name"] == "derived-topic"
    assert captured["process_kwargs"]["save"] is True
    assert captured["process_kwargs"]["report_focus"] == "focus text"
    assert captured["selection_kwargs"]["expand"] is True
    assert captured["selection_kwargs"]["top_by_date"] is False


def test_run_learning_top_by_date_exits_when_selection_is_empty(config, monkeypatch):
    captured = {}
    monkeypatch.setattr(learning_flow.cli_shared, "require_model", lambda: None)

    with pytest.raises(typer.Exit) as excinfo:
        learning_flow.run_learning_command(
            "query",
            topic="topic-a",
            days=3,
            limit=5,
            sort="date",
            per_channel_cap=2,
            shorts=True,
            rerank=True,
            save=False,
            report=False,
            test=False,
            generate_brief=False,
            header="Latest",
            get_config=lambda: config,
            cost_tracker_factory=CostTracker,
            topic_from_query=lambda query: pytest.fail("explicit topic must be preserved"),
            auto_skeptical_mode=lambda *args, **kwargs: False,
            default_report_focus=lambda *args, **kwargs: None,
            window_label=lambda days, hours: "3d",
            select_learning_videos=lambda *args, **kwargs: (
                captured.update(kwargs),
                [],
            ),
            display_ranked_videos=lambda *args, **kwargs: pytest.fail(
                "empty selections must not render a table"
            ),
            process_learning_selection=lambda *args, **kwargs: pytest.fail(
                "empty selections must not be processed"
            ),
            top_by_date=True,
        )

    assert excinfo.value.exit_code == 0
    assert captured["expand"] is False
    assert captured["top_by_date"] is True


def test_process_learning_selection_runs_pipeline_and_follow_ups(config):
    class FakeLibrary(Library):
        def __init__(self, config: DistillConfig):
            super().__init__(config)
            self.added: list[tuple[str, str, str]] = []

        def add_channel(self, topic: str, url: str, name: str) -> bool:
            self.added.append((topic, url, name))
            return True

    tracker = CostTracker()
    selected = [
        _selected_video("v1", "Video One", channel_name="CreatorOne"),
        _selected_video("v2", "Video Two", channel_name="CreatorTwo"),
    ]
    calls = {
        "ensure": [],
        "process": [],
        "channel_synth": [],
        "topic_synth": [],
        "report": [],
        "brief": [],
    }

    def ensure_channel_context(topic_name, channel_name, videos, config, tracker):
        calls["ensure"].append((topic_name, channel_name, len(videos)))

    def process_video(topic_name, channel_name, video, config, tracker, summary, **kwargs):
        calls["process"].append((topic_name, channel_name, video.video_id))

    def synthesize_channel(topic_name, channel_name, config, tracker=None):
        calls["channel_synth"].append((topic_name, channel_name))
        path = config.channel_dir(topic_name, channel_name) / "synthesis.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("channel synthesis", encoding="utf-8")

    def synthesize_topic(topic_name, config, tracker=None):
        calls["topic_synth"].append(topic_name)
        path = config.topic_dir(topic_name) / "topic_synthesis.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("topic synthesis", encoding="utf-8")

    def synthesize_corpus(topic_name, config, tracker=None):
        path = config.topic_dir(topic_name) / "corpus_synthesis.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("corpus synthesis", encoding="utf-8")
        return path

    learning_flow.process_learning_selection(
        "topic-a",
        config,
        tracker,
        selected,
        save=True,
        report=True,
        test=False,
        generate_brief=True,
        library_factory=FakeLibrary,
        run_summary_factory=RunSummary,
        output_path=lambda cfg, name: cfg.distill_output_dir / "output" / name,
        ensure_channel_context=ensure_channel_context,
        process_video=process_video,
        synthesize_channel=synthesize_channel,
        synthesize_topic=synthesize_topic,
        synthesize_corpus=synthesize_corpus,
        run_scope_report=lambda *args, **kwargs: calls["report"].append((args, kwargs)),
        generate_and_export_topic_brief=lambda *args, **kwargs: calls["brief"].append(
            (args, kwargs)
        ),
        report_focus="focus text",
    )

    assert len(calls["ensure"]) == 2
    assert len(calls["process"]) == 2
    assert len(calls["channel_synth"]) == 2
    assert calls["topic_synth"] == ["topic-a"]
    assert len(calls["report"]) == 1
    assert len(calls["brief"]) == 1


def test_process_learning_selection_handles_registration_and_resume_edges(config, monkeypatch):
    state_paths = []

    class FakeState:
        def __init__(self, path):
            self.path = path
            state_paths.append(path)

        def is_processed(self, video_id):
            return video_id == "done"

    added = []
    processed = []
    monkeypatch.setattr(learning_flow, "ChannelState", FakeState)
    selected = [
        _selected_video("done", "Already Done", channel_name="Existing"),
        _selected_video("new", "No Stable URL", channel_name="NoUrl", channel_url=""),
    ]

    def process_video(*args, **kwargs):
        processed.append((args[2].video_id, kwargs["state"]))

    learning_flow.process_learning_selection(
        "topic-a",
        config,
        CostTracker(),
        selected,
        save=True,
        report=False,
        test=False,
        generate_brief=False,
        library_factory=lambda cfg: cast(
            Library,
            SimpleNamespace(add_channel=lambda *args: added.append(args) or False),
        ),
        run_summary_factory=RunSummary,
        output_path=lambda *args, **kwargs: None,
        ensure_channel_context=lambda *args, **kwargs: None,
        process_video=process_video,
        synthesize_channel=lambda *args, **kwargs: None,
        synthesize_topic=lambda *args, **kwargs: None,
        synthesize_corpus=lambda *args, **kwargs: None,
        run_scope_report=lambda *args, **kwargs: None,
        generate_and_export_topic_brief=lambda *args, **kwargs: None,
    )

    assert added == [("topic-a", "https://www.youtube.com/@creator", "Existing")]
    assert state_paths == [
        config.channel_dir("topic-a", "Existing") / "state.json",
        config.channel_dir("topic-a", "NoUrl") / "state.json",
    ]
    assert [video_id for video_id, _state in processed] == ["new"]
    assert processed[0][1].path == state_paths[1]


@pytest.mark.parametrize("stop_phase", ["video", "channel", "topic", "corpus", "post"])
def test_process_learning_selection_propagates_budget_stop_from_every_phase(config, stop_phase):
    events = []
    tracker = CostTracker()

    def phase(name):
        events.append(name)
        if name == stop_phase:
            tracker.record(
                TokenUsage(
                    prompt_tokens=1_000,
                    completion_tokens=100,
                    model="grok-4.3",
                    call_type=name,
                )
            )
            raise BudgetExceededError(0.6, 0.5)

    with pytest.raises(BudgetExceededError):
        learning_flow.process_learning_selection(
            "topic-a",
            config,
            tracker,
            [_selected_video("v1", "Video One")],
            save=False,
            report=False,
            test=False,
            generate_brief=False,
            library_factory=lambda cfg: cast(
                Library,
                SimpleNamespace(
                    add_channel=lambda *args: pytest.fail(
                        "save=False must never register a channel"
                    )
                ),
            ),
            run_summary_factory=RunSummary,
            output_path=lambda *args, **kwargs: None,
            ensure_channel_context=lambda *args, **kwargs: None,
            process_video=lambda *args, **kwargs: phase("video"),
            synthesize_channel=lambda *args, **kwargs: phase("channel"),
            synthesize_topic=lambda *args, **kwargs: phase("topic"),
            synthesize_corpus=lambda *args, **kwargs: phase("corpus"),
            run_scope_report=lambda *args, **kwargs: None,
            generate_and_export_topic_brief=lambda *args, **kwargs: None,
            post_ingest_callback=lambda *args, **kwargs: phase("post"),
        )

    phases = ["video", "channel", "topic", "corpus", "post"]
    assert events == phases[: phases.index(stop_phase) + 1]
    entry = json.loads(
        (config.library_dir / ".distill" / "cost_log.jsonl").read_text(encoding="utf-8").strip()
    )
    assert entry["command"] == "learn"
    assert entry["by_call_type"][stop_phase]["calls"] == 1


def test_process_learning_selection_records_synthesis_and_callback_failures(config):
    captured = {}

    def summary_factory(command):
        summary = RunSummary(command=command)
        captured["summary"] = summary
        return summary

    def fail(message):
        raise RuntimeError(message)

    learning_flow.process_learning_selection(
        "topic-a",
        config,
        CostTracker(),
        [_selected_video("v1", "Video One")],
        save=False,
        report=False,
        test=False,
        generate_brief=False,
        library_factory=lambda cfg: cast(Library, SimpleNamespace(add_channel=lambda *args: True)),
        run_summary_factory=summary_factory,
        output_path=lambda *args, **kwargs: None,
        ensure_channel_context=lambda *args, **kwargs: None,
        process_video=lambda *args, **kwargs: None,
        synthesize_channel=lambda *args, **kwargs: fail("channel failed"),
        synthesize_topic=lambda *args, **kwargs: fail("topic failed"),
        synthesize_corpus=lambda *args, **kwargs: fail("corpus failed"),
        run_scope_report=lambda *args, **kwargs: None,
        generate_and_export_topic_brief=lambda *args, **kwargs: None,
        post_ingest_callback=lambda *args, **kwargs: fail("callback failed"),
    )

    assert [issue.stage for issue in captured["summary"].issues] == [
        "channel-synthesis",
        "topic-synthesis",
        "corpus-synthesis",
        "post-ingest-callback",
    ]


def test_process_empty_selection_skips_topic_synthesis(config):
    topic_synthesized = []

    learning_flow.process_learning_selection(
        "topic-a",
        config,
        CostTracker(),
        [],
        save=False,
        report=False,
        test=False,
        generate_brief=False,
        library_factory=lambda cfg: cast(Library, SimpleNamespace(add_channel=lambda *args: True)),
        run_summary_factory=RunSummary,
        output_path=lambda *args, **kwargs: None,
        ensure_channel_context=lambda *args, **kwargs: None,
        process_video=lambda *args, **kwargs: None,
        synthesize_channel=lambda *args, **kwargs: None,
        synthesize_topic=lambda *args, **kwargs: topic_synthesized.append(args),
        synthesize_corpus=lambda *args, **kwargs: None,
        run_scope_report=lambda *args, **kwargs: None,
        generate_and_export_topic_brief=lambda *args, **kwargs: None,
    )

    assert topic_synthesized == []


def test_generate_and_export_topic_brief_copies_output(config):
    brief_source = config.topic_dir("topic-a") / "brief.md"
    brief_source.parent.mkdir(parents=True, exist_ok=True)
    brief_source.write_text("# Brief", encoding="utf-8")
    output_dir = config.distill_output_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    learning_flow.generate_and_export_topic_brief(
        "topic-a",
        config,
        CostTracker(),
        generate_topic_brief=lambda topic_name, config, tracker=None: brief_source,
        output_path=lambda cfg, name: output_dir / name,
    )

    copied = config.distill_output_dir / "output" / "brief-topic-a.md"
    assert copied.exists()
    assert copied.read_text(encoding="utf-8") == "# Brief"


def test_generate_and_export_topic_brief_handles_missing_brief(config):
    learning_flow.generate_and_export_topic_brief(
        "topic-a",
        config,
        CostTracker(),
        generate_topic_brief=lambda topic_name, config, tracker=None: None,
        output_path=lambda cfg, name: Path(cfg.distill_output_dir / "output" / name),
    )

    assert not (config.distill_output_dir / "output" / "brief-topic-a.md").exists()
