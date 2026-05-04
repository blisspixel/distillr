from pathlib import Path
from types import SimpleNamespace

import pytest
import typer

from distill.cli_support import learning_flow
from distill.pipeline.costs import CostTracker
from distill.pipeline.summary import RunSummary


def _selected_video(
    video_id: str,
    title: str,
    *,
    channel_name: str = "Creator",
    channel_url: str = "https://www.youtube.com/@creator",
    upload_date: str = "20260420",
    duration: int = 900,
):
    return SimpleNamespace(
        video=SimpleNamespace(
            video_id=video_id,
            title=title,
            channel_name=channel_name,
            channel_url=channel_url,
            upload_date=upload_date,
            duration=duration,
        ),
        final_score=0.9,
        rationale="best fit",
    )


def test_validate_learning_options_rejects_bad_values():
    with pytest.raises(typer.Exit):
        learning_flow.validate_learning_options("weird", 1, 1, 1)
    with pytest.raises(typer.Exit):
        learning_flow.validate_learning_options("date", 1, 1, 1, hours=0)


def test_preview_learning_selection_returns_selected_items(config):
    tracker = CostTracker()
    selected = [_selected_video("v1", "Video One")]
    displayed = {}

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
        select_learning_videos=lambda *args, **kwargs: ([], selected),
        display_ranked_videos=lambda items, title: displayed.update(items=items, title=title),
    )

    assert returned_config is config
    assert returned_tracker is tracker
    assert returned_selected == selected
    assert displayed["title"] == "Preview"
    assert displayed["items"] == selected


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


def test_run_learning_command_requires_api_key(tmp_path):
    no_key_config = type("NoKeyConfig", (), {"xai_api_key": "", "distill_output_dir": tmp_path})()

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
        select_learning_videos=lambda *args, **kwargs: ([], selected),
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


def test_process_learning_selection_runs_pipeline_and_follow_ups(config):
    class FakeLibrary:
        def __init__(self, config):
            self.added = []

        def add_channel(self, topic_name, channel_url, channel_name):
            self.added.append((topic_name, channel_url, channel_name))
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
