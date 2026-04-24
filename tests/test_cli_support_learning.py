from datetime import datetime
from types import SimpleNamespace

from distill.cli_support import learning
from distill.costs import CostTracker
from distill.discovery import VideoInfo
from distill.ranking import RankedPaper


def _fake_openai_response(content: str, *, prompt_tokens: int = 13, completion_tokens: int = 9):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        ),
    )


def test_expand_learning_queries_returns_url_unchanged():
    url = "https://example.com/watch?v=abc123"

    assert learning._expand_learning_queries(url) == [url]


def test_heuristic_learning_queries_adds_focus_and_skeptical_variants():
    queries = learning._heuristic_learning_queries(
        "Claude Code leak analysis best practices",
        skeptical=True,
    )

    assert "Claude Code leak analysis best practices" in queries
    assert any("architecture" in query.lower() for query in queries)
    assert any("source code" in query.lower() for query in queries)
    assert any("debunk" in query.lower() for query in queries)


def test_expand_learning_queries_merges_llm_and_heuristics(config, monkeypatch):
    monkeypatch.setattr(
        learning,
        "_heuristic_learning_queries",
        lambda query, skeptical=False: ["base", "walkthrough", "tutorial"],
    )
    monkeypatch.setattr(
        learning,
        "_llm_expand_learning_queries",
        lambda query, config, tracker=None, skeptical=False: [
            "llm-a",
            "llm-b",
            "llm-c",
            "llm-d",
        ],
    )

    queries = learning._expand_learning_queries(" topic ", config, CostTracker(), skeptical=True)

    assert queries == ["topic", "llm-a", "llm-b", "llm-c", "llm-d", "base"]


def test_llm_expand_learning_queries_parses_fenced_json_and_records_usage(config, monkeypatch):
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _fake_openai_response('```json\n{"queries":["alpha","beta"]}\n```')

    monkeypatch.setattr(
        learning,
        "OpenAI",
        lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())),
    )
    tracker = CostTracker()

    queries = learning._llm_expand_learning_queries(
        "Microsoft Fabric best practices",
        config,
        tracker=tracker,
        skeptical=True,
    )

    assert queries == ["alpha", "beta"]
    assert captured["model"] == config.xai_model_for("rerank")
    assert tracker.entries[0].call_type == "search_expand"


def test_expand_paper_queries_falls_back_when_llm_errors(config, monkeypatch):
    monkeypatch.setattr(
        learning,
        "_llm_expand_paper_queries",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    queries = learning._expand_paper_queries("agent memory", config, CostTracker(), expand=True)

    assert queries == ["agent memory"]


def test_llm_expand_paper_queries_parses_response_and_records_usage(config, monkeypatch):
    class FakeCompletions:
        def create(self, **kwargs):
            return _fake_openai_response('{"queries":["paper-a","paper-b"]}')

    monkeypatch.setattr(
        learning,
        "OpenAI",
        lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())),
    )
    tracker = CostTracker()

    queries = learning._llm_expand_paper_queries("agent memory", config, tracker=tracker)

    assert queries == ["paper-a", "paper-b"]
    assert tracker.entries[0].call_type == "paper_expand"


def test_filter_recent_candidates_handles_exact_published_at_and_bad_dates():
    recent = VideoInfo(
        "recent",
        "Recent",
        "20260420",
        600,
        "https://youtube.com/watch?v=recent",
        published_at=datetime.now().isoformat(),
    )
    invalid = VideoInfo(
        "invalid",
        "Invalid",
        "not-a-date",
        600,
        "https://youtube.com/watch?v=invalid",
        published_at="invalid",
    )
    stale = VideoInfo(
        "stale",
        "Stale",
        "20200101",
        600,
        "https://youtube.com/watch?v=stale",
    )
    missing_upload = SimpleNamespace(video_id="missing", published_at="", upload_date="")

    filtered = learning._filter_recent_candidates([recent, invalid, stale, missing_upload], days=7)

    assert [video.video_id for video in filtered] == ["recent", "invalid", "missing"]


def test_auto_skeptical_mode_triggers_on_april_first(monkeypatch):
    class FakeDateTime:
        @staticmethod
        def now():
            return datetime(2026, 4, 1, 10, 0, 0)

    monkeypatch.setattr(learning, "datetime", FakeDateTime)

    assert learning._auto_skeptical_mode("boring query", hours=12, days=5) is True


def test_select_learning_videos_uses_browser_search_and_channel_cap(config, monkeypatch):
    query_calls = []
    raw_one = VideoInfo("v1", "Video One", "20260420", 900, "https://youtube.com/watch?v=v1", "A")
    raw_two = VideoInfo("v2", "Video Two", "20260420", 900, "https://youtube.com/watch?v=v2", "A")
    raw_three = VideoInfo(
        "v3", "Video Three", "20260420", 900, "https://youtube.com/watch?v=v3", "B"
    )

    monkeypatch.setattr(learning, "_expand_learning_queries", lambda *args, **kwargs: ["q1", "q2"])
    monkeypatch.setattr(
        learning,
        "search_youtube_results",
        lambda query, days=None, hours=None, limit=None: query_calls.append(query)
        or [raw_one, raw_two if query == "q1" else raw_three],
    )
    monkeypatch.setattr(learning, "_dedupe_candidates", lambda videos: [raw_one, raw_two, raw_three])
    monkeypatch.setattr(learning, "enrich_videos", lambda videos, max_videos=None: videos)
    monkeypatch.setattr(learning, "_filter_recent_candidates", lambda videos, days, hours=None: videos)
    monkeypatch.setattr(
        learning,
        "rerank_videos",
        lambda query, vids, config, tracker=None, top_n=10, use_llm=True, skeptical=False: [
            SimpleNamespace(video=vid, final_score=1.0 - idx * 0.1, rationale="fit")
            for idx, vid in enumerate(vids)
        ],
    )

    enriched, selected = learning._select_learning_videos(
        "query",
        config,
        CostTracker(),
        days=7,
        limit=3,
        sort="date",
        per_channel_cap=1,
        shorts=True,
        rerank=False,
    )

    assert query_calls == ["q1", "q2"]
    assert [video.video_id for video in enriched] == ["v1", "v2", "v3"]
    assert [item.video.video_id for item in selected] == ["v1", "v3"]


def test_select_learning_videos_falls_back_to_search_videos(config, monkeypatch):
    full = VideoInfo(
        "full",
        "Full Video",
        "20260420",
        900,
        "https://youtube.com/watch?v=full",
        "Creator",
    )
    short = VideoInfo(
        "short",
        "Short Video",
        "20260420",
        30,
        "https://youtube.com/watch?v=short",
        "Creator",
    )
    fallback_calls = []

    monkeypatch.setattr(learning, "_expand_learning_queries", lambda *args, **kwargs: ["q1"])
    monkeypatch.setattr(learning, "search_youtube_results", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        learning,
        "search_videos",
        lambda query, days, limit, sort, per_channel_cap: fallback_calls.append(
            (query, days, limit, sort, per_channel_cap)
        )
        or [short, full],
    )
    monkeypatch.setattr(learning, "enrich_videos", lambda videos, max_videos=None: videos)
    monkeypatch.setattr(learning, "_filter_recent_candidates", lambda videos, days, hours=None: videos)
    monkeypatch.setattr(
        learning,
        "rerank_videos",
        lambda query, vids, config, tracker=None, top_n=10, use_llm=True, skeptical=False: [
            SimpleNamespace(video=vid, final_score=0.9, rationale="fit") for vid in vids
        ],
    )

    enriched, selected = learning._select_learning_videos(
        "query",
        config,
        CostTracker(),
        days=7,
        limit=2,
        sort="relevance",
        per_channel_cap=2,
        shorts=False,
        rerank=False,
    )

    assert fallback_calls == [("query", 7, 12, "relevance", 4)]
    assert [video.video_id for video in enriched] == ["full"]
    assert [item.video.video_id for item in selected] == ["full"]


def test_display_ranked_papers_and_videos_render_without_error(monkeypatch):
    printed = []
    monkeypatch.setattr(learning.console, "print", lambda obj: printed.append(obj))

    paper = SimpleNamespace(
        title="Paper",
        authors=["Alice", "Bob", "Carol"],
        categories=["cs.LG", "cs.AI"],
        published_at="2026-04-20T00:00:00Z",
    )
    ranked_paper = RankedPaper(
        paper=paper,
        final_score=0.95,
        relevance_score=0.9,
        depth_score=0.9,
        novelty_score=0.8,
        credibility_score=0.85,
        rationale="best paper",
        selected_by="heuristic",
    )
    ranked_video = SimpleNamespace(
        video=SimpleNamespace(
            title="Video",
            channel_name="Creator",
            upload_date="20260420",
            view_count=1500,
        ),
        final_score=0.88,
        rationale="best video",
    )

    learning._display_ranked_papers([ranked_paper], title="Papers")
    learning._display_ranked_videos([ranked_video], title="Videos")

    assert len(printed) == 2
