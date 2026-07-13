"""Tests for discover-flow helper boundaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from distill.commands import _discover_flow
from distill.config import DistillConfig
from distill.ingestors.papers.arxiv import PaperRecord
from distill.ingestors.sites.scraper import SiteSeed
from distill.ingestors.youtube.discovery import VideoInfo
from distill.pipeline.costs import CostEstimate, CostTracker
from distill.pipeline.discovery import RankedDiscoverItem, SizingOption
from distill.pipeline.summary import RunSummary


@pytest.fixture
def mock_config(tmp_path: Path) -> DistillConfig:
    return DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "library")


def _estimate() -> CostEstimate:
    return CostEstimate(expected=0.03, low=0.01, high=0.05, calibrated=False)


def _ranked_item(kind: str, identifier: str) -> RankedDiscoverItem:
    paper = (
        PaperRecord(paper_id=identifier, title="Paper", abstract="Abstract")
        if kind == "paper"
        else None
    )
    video = (
        VideoInfo(video_id=identifier, title="Video", upload_date="20260101", duration=600, url="u")
        if kind == "video"
        else None
    )
    site_seed = (
        SiteSeed(url=f"https://example.com/{identifier}", topic="t") if kind == "site" else None
    )
    return RankedDiscoverItem(
        kind=kind,
        identifier=identifier,
        title=identifier,
        subtitle="source",
        date="2026-01-01",
        final_score=0.8,
        goal_fit=0.8,
        depth_score=0.8,
        complementarity_score=0.8,
        rationale="structural fixture",
        paper=paper,
        video=video,
        site_seed=site_seed,
    )


def test_discover_generate_queries_delegates_with_query_deduper(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def generate_queries(
        goal: str,
        config: DistillConfig,
        tracker: CostTracker | None,
        **kwargs: Any,
    ) -> tuple[list[str], list[str]]:
        captured.update(
            {
                "goal": goal,
                "config": config,
                "tracker": tracker,
                "kwargs": kwargs,
            }
        )
        return ["paper"], ["video"]

    monkeypatch.setattr(
        _discover_flow._discover_support, "discover_generate_queries", generate_queries
    )
    tracker = CostTracker()

    result = _discover_flow._discover_generate_queries(
        "goal", mock_config, tracker, paper_count=2, video_count=3
    )

    assert result == (["paper"], ["video"])
    assert captured["goal"] == "goal"
    assert captured["config"] == mock_config
    assert captured["tracker"] == tracker
    assert captured["kwargs"].keys() == {
        "paper_count",
        "video_count",
        "dedupe_query_strings",
    }
    assert captured["kwargs"]["paper_count"] == 2
    assert captured["kwargs"]["video_count"] == 3


def test_discover_fetch_videos_delegates_with_bound_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    expected = [
        VideoInfo(video_id="v1", title="Video", upload_date="20260101", duration=600, url="u")
    ]

    def fetch_videos(
        queries: list[str],
        effective_days: int,
        candidate_cap: int,
        shorts: bool,
        **kwargs: Any,
    ) -> list[VideoInfo]:
        captured.update(
            {
                "queries": queries,
                "effective_days": effective_days,
                "candidate_cap": candidate_cap,
                "shorts": shorts,
                "helpers": set(kwargs),
            }
        )
        return expected

    monkeypatch.setattr(_discover_flow._discover_support, "discover_fetch_videos", fetch_videos)

    result = _discover_flow._discover_fetch_videos(["q"], 14, 5, False)

    assert result == expected
    assert captured == {
        "queries": ["q"],
        "effective_days": 14,
        "candidate_cap": 5,
        "shorts": False,
        "helpers": {
            "search_youtube_results",
            "dedupe_candidates",
            "enrich_videos",
            "filter_recent_candidates",
        },
    }


def test_display_ranked_discover_delegates_to_support_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    items = [_ranked_item("paper", "p1")]

    monkeypatch.setattr(
        _discover_flow._discover_support,
        "display_ranked_discover",
        lambda ranked, title: captured.update({"ranked": ranked, "title": title}),
    )

    _discover_flow._display_ranked_discover(items, "Title")

    assert captured == {"ranked": items, "title": "Title"}


def test_discover_rerank_delegates_to_support_module(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = [_ranked_item("paper", "p1")]
    captured: dict[str, Any] = {}

    def rerank(
        goal: str,
        papers: list[PaperRecord],
        videos: list[VideoInfo],
        sites: list[SiteSeed],
        config: DistillConfig,
        tracker: CostTracker | None,
    ) -> list[RankedDiscoverItem]:
        captured.update(
            {
                "goal": goal,
                "papers": papers,
                "videos": videos,
                "sites": sites,
                "config": config,
                "tracker": tracker,
            }
        )
        return expected

    monkeypatch.setattr(_discover_flow._discover_support, "discover_rerank", rerank)
    tracker = CostTracker()

    result = _discover_flow._discover_rerank("goal", [], [], [], mock_config, tracker)

    assert result == expected
    assert captured == {
        "goal": "goal",
        "papers": [],
        "videos": [],
        "sites": [],
        "config": mock_config,
        "tracker": tracker,
    }


def test_fresh_topic_detection_handles_missing_empty_and_existing_markdown(
    mock_config: DistillConfig,
) -> None:
    assert _discover_flow._is_fresh_topic(mock_config, "missing")

    empty_topic = mock_config.topic_dir("empty")
    empty_topic.mkdir(parents=True)
    assert _discover_flow._is_fresh_topic(mock_config, "empty")

    (empty_topic / "artifact.md").write_text("# Artifact", encoding="utf-8")
    assert not _discover_flow._is_fresh_topic(mock_config, "empty")


def test_sizing_option_line_lists_site_counts() -> None:
    option = SizingOption(
        label="Sites",
        basis="score >= 0.50",
        items=[_ranked_item("site", "site")],
        papers=0,
        videos=0,
        sites=1,
        estimate=_estimate(),
    )

    line = _discover_flow._sizing_option_line(2, option)

    assert "1 site(s)" in line
    assert "0 items" not in line


def test_sizing_option_line_lists_video_counts() -> None:
    option = SizingOption(
        label="Videos",
        basis="score >= 0.50",
        items=[_ranked_item("video", "v1")],
        papers=0,
        videos=1,
        sites=0,
        estimate=_estimate(),
    )

    line = _discover_flow._sizing_option_line(1, option)

    assert "1 video(s)" in line
    assert "0 items" not in line


def test_sizing_flow_exits_when_no_sizing_options(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_discover_flow, "_display_ranked_discover", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        _discover_flow._discover_support, "build_sizing_options", lambda *args, **kwargs: []
    )
    called = {"ingest": False}
    monkeypatch.setattr(
        _discover_flow,
        "_discover_ingest_set",
        lambda **kwargs: called.__setitem__("ingest", True),
    )

    _discover_flow._discover_sizing_flow(
        goal="goal",
        topic_name="t",
        config=mock_config,
        tracker=CostTracker(),
        summary=RunSummary(command="discover"),
        ranked=[],
        paper_limit=1,
        video_limit=1,
        site_limit=1,
        ingest_attachments=False,
    )

    assert called["ingest"] is False


def test_sizing_flow_cancel_choice_aborts_without_ingest(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    option = SizingOption(
        label="One",
        basis="score >= 0.50",
        items=[_ranked_item("paper", "p1")],
        papers=1,
        videos=0,
        sites=0,
        estimate=_estimate(),
    )
    monkeypatch.setattr(_discover_flow, "_display_ranked_discover", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        _discover_flow._discover_support, "build_sizing_options", lambda *args, **kwargs: [option]
    )
    monkeypatch.setattr(_discover_flow, "_tty_prompt", lambda *args, **kwargs: "cancel")
    called = {"ingest": False}
    monkeypatch.setattr(
        _discover_flow,
        "_discover_ingest_set",
        lambda **kwargs: called.__setitem__("ingest", True),
    )

    _discover_flow._discover_sizing_flow(
        goal="goal",
        topic_name="t",
        config=mock_config,
        tracker=CostTracker(),
        summary=RunSummary(command="discover"),
        ranked=[_ranked_item("paper", "p1")],
        paper_limit=1,
        video_limit=0,
        site_limit=0,
        ingest_attachments=False,
    )

    assert called["ingest"] is False


@pytest.mark.parametrize("choice", ["bad", "9", "\u0661", "9" * 5000])
def test_sizing_flow_invalid_choice_aborts_without_ingest(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
    choice: str,
) -> None:
    option = SizingOption(
        label="One",
        basis="score >= 0.50",
        items=[_ranked_item("paper", "p1")],
        papers=1,
        videos=0,
        sites=0,
        estimate=_estimate(),
    )
    monkeypatch.setattr(_discover_flow, "_display_ranked_discover", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        _discover_flow._discover_support, "build_sizing_options", lambda *args, **kwargs: [option]
    )
    monkeypatch.setattr(_discover_flow, "_tty_prompt", lambda *args, **kwargs: choice)
    called = {"ingest": False}
    monkeypatch.setattr(
        _discover_flow,
        "_discover_ingest_set",
        lambda **kwargs: called.__setitem__("ingest", True),
    )

    _discover_flow._discover_sizing_flow(
        goal="goal",
        topic_name="t",
        config=mock_config,
        tracker=CostTracker(),
        summary=RunSummary(command="discover"),
        ranked=[_ranked_item("paper", "p1")],
        paper_limit=1,
        video_limit=0,
        site_limit=0,
        ingest_attachments=False,
    )

    assert called["ingest"] is False


def test_sizing_flow_valid_choice_saves_preview_and_ingests_choice(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = [_ranked_item("paper", "p1"), _ranked_item("site", "s1")]
    option = SizingOption(
        label="Selected",
        basis="score >= 0.50",
        items=selected,
        papers=1,
        videos=0,
        sites=1,
        estimate=_estimate(),
    )
    summary = RunSummary(command="discover")
    captured: dict[str, Any] = {}
    monkeypatch.setattr(_discover_flow, "_display_ranked_discover", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        _discover_flow._discover_support, "build_sizing_options", lambda *args, **kwargs: [option]
    )
    monkeypatch.setattr(_discover_flow, "_tty_prompt", lambda *args, **kwargs: "1")
    monkeypatch.setattr(
        _discover_flow, "_discover_ingest_set", lambda **kwargs: captured.update(kwargs)
    )

    _discover_flow._discover_sizing_flow(
        goal="goal",
        topic_name="t",
        config=mock_config,
        tracker=CostTracker(),
        summary=summary,
        ranked=selected,
        paper_limit=1,
        video_limit=0,
        site_limit=1,
        ingest_attachments=True,
    )

    assert summary.estimated_cost == 0.03
    assert captured["topic_name"] == "t"
    assert captured["ranked_papers"] == [selected[0]]
    assert captured["ranked_sites"] == [selected[1]]
    assert captured["ranked_videos"] == []
    assert captured["ingest_attachments"] is True
    assert captured["yes"] is True
    assert any((mock_config.library_dir / ".preview_cache").glob("*.json"))


def test_confirm_discover_ingest_builds_source_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []
    monkeypatch.setattr(
        _discover_flow,
        "_tty_confirm",
        lambda prompt, default=False: prompts.append(prompt) or True,
    )

    assert _discover_flow._confirm_discover_ingest(
        "t",
        [_ranked_item("paper", "p1")],
        [_ranked_item("video", "v1")],
        [_ranked_item("site", "s1")],
    )
    assert "1 paper(s), 1 video(s), 1 site seed(s)" in prompts[0]

    prompts.clear()
    assert _discover_flow._confirm_discover_ingest("t", [], [], [])
    assert "0 items" in prompts[0]


def test_discover_ingest_papers_delegates_with_bound_helpers(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def ingest_papers(
        topic_name: str,
        config: DistillConfig,
        tracker: CostTracker,
        summary: RunSummary,
        ranked_papers: list[Any],
        **kwargs: Any,
    ) -> None:
        captured.update(
            {
                "topic_name": topic_name,
                "config": config,
                "ranked_papers": ranked_papers,
                "helpers": set(kwargs),
            }
        )

    monkeypatch.setattr(_discover_flow._discover_ingest_support, "ingest_papers", ingest_papers)
    ranked = [_ranked_item("paper", "p1")]

    _discover_flow._discover_ingest_papers(
        "t", mock_config, CostTracker(), RunSummary(command="discover"), ranked
    )

    assert captured["topic_name"] == "t"
    assert captured["config"] == mock_config
    assert captured["ranked_papers"] == ranked
    assert captured["helpers"] == {
        "analyze_paper_fn",
        "write_paper_artifacts_fn",
        "synthesize_papers_fn",
        "resolve_intent_fn",
        "find_artifact_fn",
    }


def test_discover_ingest_videos_filters_missing_video_payloads(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    ranked = [
        _ranked_item("video", "v1"),
        RankedDiscoverItem(
            kind="video",
            identifier="missing",
            title="Missing",
            subtitle="source",
            date="2026-01-01",
            final_score=0.5,
            goal_fit=0.5,
            depth_score=0.5,
            complementarity_score=0.5,
            rationale="no video payload",
            video=None,
        ),
    ]

    def process_selection(
        topic_name: str,
        config: DistillConfig,
        tracker: CostTracker,
        video_items: list[Any],
        **kwargs: Any,
    ) -> None:
        captured.update(
            {
                "topic_name": topic_name,
                "video_items": video_items,
                "kwargs": kwargs,
            }
        )

    monkeypatch.setattr(_discover_flow, "_process_learning_selection", process_selection)

    _discover_flow._discover_ingest_videos("t", mock_config, CostTracker(), ranked)

    assert captured["topic_name"] == "t"
    assert len(captured["video_items"]) == 1
    assert captured["video_items"][0].video.video_id == "v1"
    assert captured["kwargs"] == {
        "save": True,
        "report": False,
        "test": False,
        "generate_brief": False,
    }


def test_discover_ingest_sites_delegates_with_bound_helpers(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def ingest_sites(
        topic_name: str,
        config: DistillConfig,
        tracker: CostTracker,
        summary: RunSummary,
        ranked_sites: list[Any],
        ingest_attachments: bool,
        **kwargs: Any,
    ) -> None:
        captured.update(
            {
                "topic_name": topic_name,
                "config": config,
                "ranked_sites": ranked_sites,
                "ingest_attachments": ingest_attachments,
                "kwargs": kwargs,
            }
        )

    monkeypatch.setattr(_discover_flow._discover_ingest_support, "ingest_sites", ingest_sites)
    ranked = [_ranked_item("site", "s1")]

    _discover_flow._discover_ingest_sites(
        "t",
        mock_config,
        CostTracker(),
        RunSummary(command="discover"),
        ranked,
        True,
        has_videos=True,
    )

    assert captured["topic_name"] == "t"
    assert captured["config"] == mock_config
    assert captured["ranked_sites"] == ranked
    assert captured["ingest_attachments"] is True
    assert captured["kwargs"].keys() == {
        "has_videos",
        "process_site_seed_fn",
        "synthesize_site_topic_fn",
        "find_artifact_fn",
    }
    assert captured["kwargs"]["has_videos"] is True


def test_discover_ingest_set_aborts_when_confirmation_declines(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(_discover_flow, "_confirm_discover_ingest", lambda *args: False)
    monkeypatch.setattr(
        _discover_flow, "display_summary", lambda *args, **kwargs: calls.append("summary")
    )
    monkeypatch.setattr(
        _discover_flow,
        "_discover_ingest_papers",
        lambda *args, **kwargs: calls.append("papers"),
    )

    _discover_flow._discover_ingest_set(
        topic_name="t",
        config=mock_config,
        tracker=CostTracker(),
        summary=RunSummary(command="discover"),
        ranked_papers=[_ranked_item("paper", "p1")],
        ranked_videos=[],
        ranked_sites=[],
        ingest_attachments=False,
        yes=False,
    )

    assert calls == ["summary"]


def test_discover_ingest_set_runs_selected_sources_and_records_corpus_output(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Any]] = []
    output_path = mock_config.topic_dir("t") / "corpus.md"
    output_path.parent.mkdir(parents=True)
    output_path.write_text("# Corpus", encoding="utf-8")

    monkeypatch.setattr(
        _discover_flow,
        "_discover_ingest_papers",
        lambda *args, **kwargs: calls.append(("papers", args)),
    )
    monkeypatch.setattr(
        _discover_flow,
        "_discover_ingest_videos",
        lambda *args, **kwargs: calls.append(("videos", args)),
    )

    def ingest_sites(*args: Any, **kwargs: Any) -> None:
        calls.append(("sites", kwargs["has_videos"]))

    monkeypatch.setattr(_discover_flow, "_discover_ingest_sites", ingest_sites)
    monkeypatch.setattr(_discover_flow, "synthesize_corpus", lambda *args, **kwargs: True)
    monkeypatch.setattr(_discover_flow, "find_artifact", lambda *args, **kwargs: output_path)
    monkeypatch.setattr(
        _discover_flow, "display_summary", lambda *args, **kwargs: calls.append(("summary", None))
    )

    summary = RunSummary(command="discover")
    _discover_flow._discover_ingest_set(
        topic_name="t",
        config=mock_config,
        tracker=CostTracker(),
        summary=summary,
        ranked_papers=[_ranked_item("paper", "p1")],
        ranked_videos=[_ranked_item("video", "v1")],
        ranked_sites=[_ranked_item("site", "s1")],
        ingest_attachments=True,
        yes=True,
    )

    assert [call[0] for call in calls] == ["papers", "videos", "sites", "summary"]
    assert ("sites", True) in calls
    assert summary.output_files == [output_path.resolve()]


def test_discover_ingest_set_allows_empty_set_without_corpus_output(
    mock_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(_discover_flow, "synthesize_corpus", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        _discover_flow, "display_summary", lambda *args, **kwargs: calls.append("summary")
    )
    monkeypatch.setattr(
        _discover_flow,
        "_discover_ingest_papers",
        lambda *args, **kwargs: calls.append("papers"),
    )
    monkeypatch.setattr(
        _discover_flow,
        "_discover_ingest_videos",
        lambda *args, **kwargs: calls.append("videos"),
    )
    monkeypatch.setattr(
        _discover_flow,
        "_discover_ingest_sites",
        lambda *args, **kwargs: calls.append("sites"),
    )

    summary = RunSummary(command="discover")
    _discover_flow._discover_ingest_set(
        topic_name="t",
        config=mock_config,
        tracker=CostTracker(),
        summary=summary,
        ranked_papers=[],
        ranked_videos=[],
        ranked_sites=[],
        ingest_attachments=False,
        yes=True,
    )

    assert calls == ["summary"]
    assert summary.output_files == []
