from types import SimpleNamespace

from distill.cli_support import discover
from distill.costs import CostTracker
from distill.discovery import VideoInfo
from distill.paper_ingest import PaperRecord


def _fake_openai_response(content: str, *, prompt_tokens: int = 11, completion_tokens: int = 7):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        ),
    )


def test_discover_generate_queries_parses_fenced_json_and_records_usage(config, monkeypatch):
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _fake_openai_response(
                '```json\n{"paper_queries":["alpha","alpha","beta"],"video_queries":["walkthrough","walkthrough"]}\n```'
            )

    monkeypatch.setattr(
        discover,
        "OpenAI",
        lambda **kwargs: SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions()),
        ),
    )
    tracker = CostTracker()

    paper_queries, video_queries = discover.discover_generate_queries(
        "help an AI compose music",
        config,
        tracker,
        paper_count=3,
        video_count=2,
        dedupe_query_strings=lambda items: list(dict.fromkeys(items)),
    )

    assert paper_queries == ["alpha", "beta"]
    assert video_queries == ["walkthrough"]
    assert captured["model"] == config.xai_model_for("rerank")
    assert tracker.entries[0].call_type == "discover_plan"


def test_discover_generate_queries_returns_empty_for_blank_response(config, monkeypatch):
    monkeypatch.setattr(
        discover,
        "OpenAI",
        lambda **kwargs: SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **_: _fake_openai_response("   "))
            )
        ),
    )

    paper_queries, video_queries = discover.discover_generate_queries(
        "goal",
        config,
        None,
        paper_count=1,
        video_count=1,
        dedupe_query_strings=lambda items: items,
    )

    assert paper_queries == []
    assert video_queries == []


def test_discover_fetch_videos_dedupes_filters_and_enriches(monkeypatch):
    video_short = VideoInfo("v1", "Short", "20260420", 30, "https://youtube.com/watch?v=v1")
    video_full = VideoInfo(
        "v2",
        "Full",
        "20260421",
        900,
        "https://youtube.com/watch?v=v2",
        "Creator",
    )
    search_calls = []
    enrich_calls = []

    result = discover.discover_fetch_videos(
        ["alpha", "beta"],
        effective_days=3,
        candidate_cap=20,
        shorts=False,
        search_youtube_results=lambda query, days, hours, limit: (
            search_calls.append((query, days, hours, limit)) or [video_short, video_full]
        ),
        dedupe_candidates=lambda videos: [video_short, video_full],
        enrich_videos=lambda videos, max_videos=None: enrich_calls.append(max_videos) or videos,
        filter_recent_candidates=lambda videos, effective_days, hours=None: videos,
    )

    assert [item.video_id for item in result] == ["v2"]
    assert len(search_calls) == 2
    assert enrich_calls == [1]


def test_discover_rerank_maps_ranked_items_and_sorts_by_score(config, monkeypatch):
    paper = PaperRecord(
        paper_id="p1",
        title="Paper One",
        abstract="Deep technical paper",
        authors=["Alice", "Bob"],
        categories=["cs.LG"],
        published_at="2026-04-20T00:00:00Z",
    )
    video = VideoInfo(
        "v1",
        "Video One",
        "20260419",
        1200,
        "https://youtube.com/watch?v=v1",
        "Creator",
        description="Detailed build walkthrough",
    )
    tracker = CostTracker()
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _fake_openai_response(
                '```json\n{"ranked_items":[{"kind":"video","identifier":"v1","final_score":0.75,"goal_fit":0.7,"depth_score":0.8,"complementarity_score":0.6,"rationale":"practical walkthrough"},{"kind":"paper","identifier":"p1","final_score":0.9,"goal_fit":0.95,"depth_score":0.85,"complementarity_score":0.7,"rationale":"best conceptual fit"}]}\n```'
            )

    monkeypatch.setattr(
        discover,
        "OpenAI",
        lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())),
    )

    ranked = discover.discover_rerank("goal", [paper], [video], config, tracker)

    assert [item.kind for item in ranked] == ["paper", "video"]
    assert ranked[0].paper is paper
    assert ranked[1].video is video
    assert ranked[1].date
    assert captured["model"] == config.xai_model_for("rerank")
    assert tracker.entries[0].call_type == "discover_rerank"


def test_discover_rerank_returns_empty_for_non_list_payload(config, monkeypatch):
    monkeypatch.setattr(
        discover,
        "OpenAI",
        lambda **kwargs: SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **_: _fake_openai_response('{"ranked_items": {"bad": true}}')
                )
            )
        ),
    )

    ranked = discover.discover_rerank("goal", [], [], config, None)

    assert ranked == []
