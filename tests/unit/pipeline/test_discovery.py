"""Tests for distill.cli_support.discover."""

from distill.cli_support import discover
from distill.ingestors.papers.arxiv import PaperRecord
from distill.ingestors.sites.scraper import SiteSeed
from distill.ingestors.youtube.discovery import VideoInfo
from distill.llm.router import LLM_Response
from distill.pipeline.costs import CostTracker


def test_discover_generate_queries_parses_fenced_json_and_records_usage(config, monkeypatch):
    monkeypatch.setattr(
        discover,
        "llm_call",
        lambda rc, workload_tag, prompt, **kwargs: LLM_Response(
            text='```json\n{"paper_queries":["alpha","alpha","beta"],"video_queries":["walkthrough","walkthrough"]}\n```',
            input_tokens=11,
            output_tokens=7,
            model="grok-4.3",
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
    assert tracker.entries[0].call_type == "discover_plan"


def test_discover_generate_queries_returns_empty_for_blank_response(config, monkeypatch):
    monkeypatch.setattr(
        discover,
        "llm_call",
        lambda rc, workload_tag, prompt, **kwargs: LLM_Response(
            text="   ",
            input_tokens=0,
            output_tokens=0,
            model="grok-4.3",
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


def test_discover_generate_queries_short_circuits_when_both_counts_zero(config, monkeypatch):
    """--papers-only AND --videos-only is a contradiction; defensive guard so we
    don't accidentally pay for query generation that nothing will use."""
    called = []

    def fake_llm_call(*args, **kwargs):
        called.append(True)
        return LLM_Response(text="", input_tokens=0, output_tokens=0, model="grok-4.3")

    monkeypatch.setattr(discover, "llm_call", fake_llm_call)

    paper_queries, video_queries = discover.discover_generate_queries(
        "goal",
        config,
        None,
        paper_count=0,
        video_count=0,
        dedupe_query_strings=lambda items: items,
    )

    assert paper_queries == []
    assert video_queries == []
    assert called == []  # never hit the LLM


def test_discover_generate_queries_drops_disabled_side_after_llm(config, monkeypatch):
    """Even if the LLM ignores the count and emits paper queries when
    paper_count=0 (or vice versa), the disabled side is forced to []."""
    monkeypatch.setattr(
        discover,
        "llm_call",
        lambda rc, workload_tag, prompt, **kwargs: LLM_Response(
            text='{"paper_queries":["should-be-dropped"],"video_queries":["walkthrough"]}',
            input_tokens=0,
            output_tokens=0,
            model="grok-4.3",
        ),
    )

    paper_queries, video_queries = discover.discover_generate_queries(
        "goal",
        config,
        None,
        paper_count=0,  # videos-only mode
        video_count=3,
        dedupe_query_strings=lambda items: list(dict.fromkeys(items)),
    )

    assert paper_queries == []
    assert video_queries == ["walkthrough"]


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
    site = SiteSeed(
        url="https://learn.microsoft.com/en-us/microsoft-365/agents/overview",
        topic="agent365",
        site_name="learn.microsoft.com",
        label="Official Agent365 overview",
    )
    tracker = CostTracker()

    monkeypatch.setattr(
        discover,
        "llm_call",
        lambda rc, workload_tag, prompt, **kwargs: LLM_Response(
            text='```json\n{"ranked_items":[{"kind":"video","identifier":"v1","final_score":0.75,"goal_fit":0.7,"depth_score":0.8,"complementarity_score":0.6,"rationale":"practical walkthrough"},{"kind":"paper","identifier":"p1","final_score":0.9,"goal_fit":0.95,"depth_score":0.85,"complementarity_score":0.7,"rationale":"best conceptual fit"},{"kind":"site","identifier":"https://learn.microsoft.com/en-us/microsoft-365/agents/overview","final_score":0.55,"goal_fit":0.8,"depth_score":0.5,"complementarity_score":0.7,"rationale":"official reference material"}]}\n```',
            input_tokens=11,
            output_tokens=7,
            model="grok-4.3",
        ),
    )

    ranked = discover.discover_rerank("goal", [paper], [video], [site], config, tracker)

    assert [item.kind for item in ranked] == ["paper", "video", "site"]
    assert ranked[0].paper is paper
    assert ranked[1].video is video
    assert ranked[2].site_seed is site
    assert ranked[1].date
    assert tracker.entries[0].call_type == "discover_rerank"


def test_discover_generate_queries_pins_temperature_for_reproducible_plans(config, monkeypatch):
    captured = {}

    def fake_llm_call(rc, **kwargs):
        captured.update(kwargs)
        return LLM_Response(
            text='{"paper_queries":["a"],"video_queries":["b"]}',
            input_tokens=1,
            output_tokens=1,
            model="grok-4.3",
        )

    monkeypatch.setattr(discover, "llm_call", fake_llm_call)

    discover.discover_generate_queries(
        "goal", config, None, paper_count=1, video_count=1, dedupe_query_strings=lambda x: x
    )

    assert captured["temperature"] == 0.0


# ---- corpus-aware dedup (filter_ingested_candidates) ------------------------


def _paper(paper_id: str) -> PaperRecord:
    return PaperRecord(paper_id=paper_id, title=f"T {paper_id}", abstract="a")


def _video(video_id: str) -> VideoInfo:
    return VideoInfo(video_id, f"V {video_id}", "20260101", 600, f"https://yt/{video_id}")


def test_filter_ingested_empty_set_is_passthrough():
    papers = [_paper("2601.00001")]
    videos = [_video("v1")]

    kept_papers, kept_videos, excluded = discover.filter_ingested_candidates(
        papers, videos, ingested=frozenset()
    )

    assert kept_papers is papers
    assert kept_videos is videos
    assert excluded == 0


def test_filter_ingested_drops_exact_paper_and_video_matches():
    papers = [_paper("2601.00001v1"), _paper("2601.00002v1")]
    videos = [_video("v1"), _video("v2")]

    kept_papers, kept_videos, excluded = discover.filter_ingested_candidates(
        papers, videos, ingested=frozenset({"2601.00001v1", "v1"})
    )

    assert [p.paper_id for p in kept_papers] == ["2601.00002v1"]
    assert [v.video_id for v in kept_videos] == ["v2"]
    assert excluded == 2


def test_filter_ingested_paper_match_is_version_insensitive():
    # Corpus holds v1 (walk stores raw + version-stripped); the search now
    # returns v2 of the same paper -- still a duplicate.
    kept_papers, _, excluded = discover.filter_ingested_candidates(
        [_paper("2601.00001v2")], [], ingested=frozenset({"2601.00001v1", "2601.00001"})
    )

    assert kept_papers == []
    assert excluded == 1


def test_filter_ingested_video_ids_match_case_sensitively():
    # YouTube ids are case-sensitive: a different-case id is a different video.
    _, kept_videos, excluded = discover.filter_ingested_candidates(
        [], [_video("AbC123"), _video("abc123")], ingested=frozenset({"AbC123"})
    )

    assert [v.video_id for v in kept_videos] == ["abc123"]
    assert excluded == 1


def test_discover_rerank_returns_empty_for_non_list_payload(config, monkeypatch):
    monkeypatch.setattr(
        discover,
        "llm_call",
        lambda rc, workload_tag, prompt, **kwargs: LLM_Response(
            text='{"ranked_items": {"bad": true}}',
            input_tokens=0,
            output_tokens=0,
            model="grok-4.3",
        ),
    )

    ranked = discover.discover_rerank("goal", [], [], [], config, None)

    assert ranked == []


def test_detect_score_cliff():
    from distill.pipeline.discovery import detect_score_cliff

    # clear cliff: 0.85 -> 0.40 is the biggest drop, 3 items above it
    assert detect_score_cliff([0.90, 0.88, 0.85, 0.40, 0.35]) == 3
    # flat distribution: no drop exceeds min_drop -> keep all
    assert detect_score_cliff([0.50, 0.49, 0.48, 0.47]) == 4
    # order-independent (sorts internally)
    assert detect_score_cliff([0.35, 0.90, 0.40, 0.88, 0.85]) == 3
    assert detect_score_cliff([0.9]) == 1
    assert detect_score_cliff([]) == 0


def test_rigor_threshold():
    from distill.pipeline.discovery import RIGOR_LEVELS, rigor_threshold

    assert RIGOR_LEVELS == ("strict", "balanced", "loose")
    assert rigor_threshold("strict") == 0.7
    assert rigor_threshold("balanced") == 0.5
    assert rigor_threshold("loose") == 0.3
    assert rigor_threshold("unknown") == 0.5  # default balanced
