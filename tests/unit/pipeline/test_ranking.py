"""Tests for distill.ranking."""

from datetime import datetime, timedelta
from types import SimpleNamespace

from distill.config import DistillConfig
from distill.ingestors.youtube.discovery import VideoInfo
from distill.pipeline.ranking import (
    _credibility_score,
    _depth_score,
    _freshness_score,
    _heuristic_rank,
    _parse_rerank_response,
    _practicality_score,
    _query_overlap,
    _tokenize,
    _topicality_score,
    chronological_rank,
    rerank_videos,
)


def _recent(days_ago: int = 1) -> str:
    """Return a YYYYMMDD date string for `days_ago` days before today."""
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y%m%d")


def _date_ago(days: int) -> str:
    """Return a YYYYMMDD date string for `days` days before today."""
    return (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")


def test_rerank_videos_falls_back_to_heuristic_when_llm_disabled(tmp_path):
    config = DistillConfig(xai_api_key="", distill_output_dir=tmp_path / "library")
    videos = [
        VideoInfo(
            "v1",
            "Microsoft Fabric IaC best practices",
            _recent(3),
            1200,
            "https://youtube.com/watch?v=v1",
            "CreatorA",
            description="Architecture and deployment guide",
            view_count=5000,
        ),
        VideoInfo(
            "v2",
            "Weekly Fabric news",
            _recent(4),
            300,
            "https://youtube.com/watch?v=v2",
            "CreatorB",
            description="Roundup",
            view_count=2000,
        ),
    ]

    ranked = rerank_videos(
        "Microsoft Fabric IaC best practices", videos, config, top_n=2, use_llm=False
    )

    assert [item.video.video_id for item in ranked] == ["v1", "v2"]
    assert ranked[0].selected_by == "heuristic"


def test_rerank_videos_uses_llm_response_when_available(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "library")
    videos = [
        VideoInfo("v1", "One", _recent(3), 1200, "https://youtube.com/watch?v=v1", "CreatorA"),
        VideoInfo("v2", "Two", _recent(4), 1200, "https://youtube.com/watch?v=v2", "CreatorB"),
    ]

    from distill.llm.router import LLM_Response

    monkeypatch.setattr(
        "distill.pipeline.ranking.llm_call",
        lambda rc, workload_tag, prompt, **kwargs: LLM_Response(
            text='{"ranked_videos": [{"video_id": "v2", "relevance_score": 0.9, "depth_score": 0.8, "practicality_score": 0.8, "freshness_score": 0.7, "credibility_score": 0.6, "final_score": 0.82, "rationale": "best match"}]}',
            input_tokens=100,
            output_tokens=50,
            model="grok-4.3",
        ),
    )

    ranked = rerank_videos("query", videos, config, top_n=1, use_llm=True)

    assert [item.video.video_id for item in ranked] == ["v2"]
    assert ranked[0].selected_by == "llm"


def test_rerank_videos_generic_topicality_penalizes_off_topic(tmp_path):
    config = DistillConfig(xai_api_key="", distill_output_dir=tmp_path / "library")
    videos = [
        VideoInfo(
            "v1",
            "Kubernetes best practices for production",
            _recent(3),
            1200,
            "https://youtube.com/watch?v=v1",
            "CreatorA",
            description="Cluster architecture guide",
            view_count=5000,
        ),
        VideoInfo(
            "v2",
            "Weekly cloud news roundup",
            _recent(4),
            1200,
            "https://youtube.com/watch?v=v2",
            "CreatorB",
            description="AWS Azure Google recap",
            view_count=9000,
        ),
    ]

    ranked = rerank_videos("Kubernetes best practices", videos, config, top_n=2, use_llm=False)

    assert [item.video.video_id for item in ranked] == ["v1", "v2"]


def test_rerank_videos_falls_back_when_llm_errors(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "library")
    videos = [
        VideoInfo(
            "v1",
            "Microsoft Fabric architecture",
            _recent(3),
            1200,
            "https://youtube.com/watch?v=v1",
            "CreatorA",
        )
    ]
    monkeypatch.setattr(
        "distill.pipeline.ranking._llm_rerank",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    ranked = rerank_videos("Microsoft Fabric architecture", videos, config)

    assert ranked[0].selected_by == "heuristic"


def test_rerank_videos_supplements_partial_llm_results(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "library")
    videos = [
        VideoInfo("v1", "One", _recent(3), 1200, "https://youtube.com/watch?v=v1", "CreatorA"),
        VideoInfo("v2", "Two", _recent(4), 1200, "https://youtube.com/watch?v=v2", "CreatorB"),
    ]
    monkeypatch.setattr(
        "distill.pipeline.ranking._llm_rerank",
        lambda *args, **kwargs: [
            SimpleNamespace(video=videos[1], final_score=0.9, selected_by="llm")
        ],
    )

    ranked = rerank_videos("query", videos, config, top_n=2)

    assert [item.video.video_id for item in ranked] == ["v2", "v1"]


def test_parse_rerank_response_handles_code_fences_and_dicts():
    content = """```json
{"ranked_videos": [{"video_id": "v1"}]}
```"""

    assert _parse_rerank_response(content) == [{"video_id": "v1"}]
    assert _parse_rerank_response('{"ranked_videos": [{"video_id": "v2"}]}') == [{"video_id": "v2"}]
    assert _parse_rerank_response('[{"video_id": "v3"}]') == [{"video_id": "v3"}]


def test_scoring_helpers_cover_edge_cases():
    video = VideoInfo(
        "v1",
        "Microsoft Fabric implementation guide",
        _recent(3),
        1800,
        "https://youtube.com/watch?v=v1",
        "Creator",
        description="Governance walkthrough and architecture pattern",
        view_count=10000,
        like_count=50,
        comment_count=10,
    )

    assert _query_overlap("Microsoft Fabric guide", video) > 0
    assert _query_overlap("", video) == 0.5
    assert _depth_score(0) == 0.0
    assert _depth_score(60 * 3) == 0.15
    assert _depth_score(60 * 6) == 0.45
    assert _depth_score(60 * 20) == 0.95
    assert _depth_score(60 * 50) == 0.75
    assert _depth_score(60 * 70) == 0.55
    assert _freshness_score("bad") == 0.0
    assert _credibility_score(VideoInfo("x", "t", _recent(3), 10, "u")) >= 0.2
    assert _practicality_score("best practice", video) > 0.18
    assert _topicality_score("Microsoft Fabric architecture", video) > 0.5
    assert _topicality_score("Obscure Anchor Topic", video) < 0.5
    assert _tokenize("A/B test!") == ["a", "b", "test"]


def test_heuristic_rank_orders_by_final_score():
    videos = [
        VideoInfo(
            "v1",
            "Microsoft Fabric best practices",
            _recent(3),
            1800,
            "https://youtube.com/watch?v=v1",
            "CreatorA",
            description="Architecture guide",
            view_count=10000,
        ),
        VideoInfo(
            "v2",
            "Weekly roundup",
            _recent(3),
            120,
            "https://youtube.com/watch?v=v2",
            "CreatorB",
            description="News recap",
            view_count=100,
        ),
    ]

    ranked = _heuristic_rank("Microsoft Fabric best practices", videos)

    assert ranked[0].video.video_id == "v1"
    assert ranked[0].final_score >= ranked[1].final_score


def test_rerank_videos_handles_empty_inputs_and_empty_llm_results(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "library")
    videos = [
        VideoInfo("v1", "One", _recent(3), 1200, "https://youtube.com/watch?v=v1", "CreatorA")
    ]
    monkeypatch.setattr("distill.pipeline.ranking._llm_rerank", lambda *args, **kwargs: [])

    assert rerank_videos("query", [], config) == []
    ranked = rerank_videos("query", videos, config)

    assert ranked[0].selected_by == "heuristic"


def test_llm_rerank_ignores_unknown_ids_and_tracks_usage(tmp_path, monkeypatch):
    from distill.pipeline.costs import CostTracker
    from distill.pipeline.ranking import _llm_rerank

    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "library")
    tracker = CostTracker()
    videos = [
        VideoInfo("v1", "One", _recent(3), 1200, "https://youtube.com/watch?v=v1", "CreatorA")
    ]

    from distill.llm.router import LLM_Response

    monkeypatch.setattr(
        "distill.pipeline.ranking.llm_call",
        lambda rc, workload_tag, prompt, **kwargs: LLM_Response(
            text='[{"video_id": "missing"}, {"video_id": "v1", "final_score": 0.8}]',
            input_tokens=12,
            output_tokens=5,
            model="grok-4.3",
        ),
    )

    ranked = _llm_rerank("query", videos, config, tracker)

    assert [item.video.video_id for item in ranked] == ["v1"]
    assert tracker.entries[0].call_type == "search_rerank"


def test_scoring_helpers_cover_remaining_ranges():
    video = VideoInfo("v1", "Generic video", _recent(3), 600, "u", "Creator")

    assert _freshness_score(_date_ago(3)) == 1.0  # 3 days ago -> within 7
    assert _freshness_score(_date_ago(14)) == 0.85  # 14 days ago -> 8-21
    assert _freshness_score(_date_ago(30)) == 0.7  # 30 days ago -> 22-45
    assert _freshness_score(_date_ago(50)) == 0.55  # 50 days ago -> 46-60
    assert _freshness_score(_date_ago(90)) == 0.25  # 90 days ago -> >60
    assert _topicality_score("best practices", video) == 0.7


def test_skeptical_ranking_prefers_concrete_evidence_terms(tmp_path):
    config = DistillConfig(xai_api_key="", distill_output_dir=tmp_path / "library")
    videos = [
        VideoInfo(
            "v1",
            "Claude Code source code sourcemap analysis",
            _recent(1),
            900,
            "https://youtube.com/watch?v=v1",
            "CreatorA",
            description="Breakdown of leaked files and feature flags",
            view_count=500,
        ),
        VideoInfo(
            "v2",
            "Claude Code leak worst nightmare lol",
            _recent(1),
            900,
            "https://youtube.com/watch?v=v2",
            "CreatorB",
            description="crazy reaction",
            view_count=500,
        ),
    ]

    ranked = rerank_videos(
        "Claude Code leak analysis",
        videos,
        config,
        top_n=2,
        use_llm=False,
        skeptical=True,
    )

    assert [item.video.video_id for item in ranked] == ["v1", "v2"]
    assert "concrete evidence terms" in ranked[0].rationale


# --- RankedPaper / rerank_papers tests ---------------------------------------


def _paper(paper_id: str, title: str, **overrides):
    from distill.ingestors.papers.arxiv import PaperRecord

    return PaperRecord(
        paper_id=paper_id,
        title=title,
        abstract=overrides.get(
            "abstract",
            "We propose a substantive method with experiments and ablations across multiple benchmarks.",
        ),
        authors=overrides.get("authors", ["Alice", "Bob", "Carol"]),
        categories=overrides.get("categories", ["cs.LG"]),
        published_at=overrides.get(
            "published_at", (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%dT00:00:00Z")
        ),
        abs_url=overrides.get("abs_url", f"https://arxiv.org/abs/{paper_id}"),
    )


def test_rerank_papers_falls_back_to_heuristic_when_llm_disabled(tmp_path):
    from distill.pipeline.ranking import rerank_papers

    config = DistillConfig(xai_api_key="", distill_output_dir=tmp_path / "library")
    papers = [
        _paper(
            "p1",
            "Symbolic Music Transformer",
            abstract="We propose a transformer for symbolic music generation with extensive experiments.",
        ),
        _paper("p2", "Image Harmonization Pipeline", abstract="Image compositing."),
    ]

    ranked = rerank_papers("symbolic music transformer", papers, config, top_n=2, use_llm=False)

    assert [item.paper.paper_id for item in ranked] == ["p1", "p2"]
    assert ranked[0].selected_by == "heuristic"
    assert ranked[0].final_score > ranked[1].final_score


def test_rerank_papers_uses_llm_response_when_available(tmp_path, monkeypatch):
    from distill.pipeline.ranking import rerank_papers

    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "library")
    papers = [_paper("p1", "One"), _paper("p2", "Two")]

    from distill.llm.router import LLM_Response

    monkeypatch.setattr(
        "distill.pipeline.ranking.llm_call",
        lambda rc, workload_tag, prompt, **kwargs: LLM_Response(
            text='{"ranked_papers": [{"paper_id": "p2", "relevance_score": 0.9, "depth_score": 0.8, "novelty_score": 0.7, "credibility_score": 0.8, "final_score": 0.85, "rationale": "best fit"}]}',
            input_tokens=80,
            output_tokens=40,
            model="grok-4.3",
        ),
    )

    ranked = rerank_papers("query", papers, config, top_n=1, use_llm=True)

    assert [item.paper.paper_id for item in ranked] == ["p2"]
    assert ranked[0].selected_by == "llm"
    assert ranked[0].rationale == "best fit"


def test_llm_reranks_pin_temperature_for_reproducible_previews(tmp_path, monkeypatch):
    """A preview and its re-run must rank identically; both rerank calls pin
    temperature=0.0 (the discover rerank already does)."""
    from distill.llm.router import LLM_Response
    from distill.pipeline.ranking import rerank_papers

    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "library")
    captured: list[float] = []

    def fake_llm_call(rc, **kwargs):
        captured.append(kwargs["temperature"])
        return LLM_Response(text="{}", input_tokens=1, output_tokens=1, model="grok-4.3")

    monkeypatch.setattr("distill.pipeline.ranking.llm_call", fake_llm_call)

    videos = [VideoInfo("v1", "One", _recent(3), 1200, "https://youtube.com/watch?v=v1")]
    rerank_videos("query", videos, config, top_n=1, use_llm=True)
    rerank_papers("query", [_paper("p1", "One")], config, top_n=1, use_llm=True)

    assert captured == [0.0, 0.0]


def test_rerank_papers_falls_back_when_llm_errors(tmp_path, monkeypatch):
    from distill.pipeline.ranking import rerank_papers

    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "library")
    papers = [_paper("p1", "Symbolic Music Transformer")]

    def boom(*args, **kwargs):
        raise RuntimeError("LLM down")

    monkeypatch.setattr("distill.pipeline.ranking._llm_rerank_papers", boom)

    ranked = rerank_papers("symbolic music transformer", papers, config, top_n=1, use_llm=True)

    assert [item.paper.paper_id for item in ranked] == ["p1"]
    assert ranked[0].selected_by == "heuristic"


def test_parse_paper_rerank_response_handles_code_fences():
    from distill.pipeline.ranking import _parse_paper_rerank_response

    content = """```json
{"ranked_papers": [{"paper_id": "p1", "final_score": 0.5}]}
```"""
    parsed = _parse_paper_rerank_response(content)
    assert parsed == [{"paper_id": "p1", "final_score": 0.5}]


def test_search_arxiv_multi_dedupes_and_preserves_order(monkeypatch):
    from distill.ingestors.papers import arxiv as paper_ingest_mod
    from distill.ingestors.papers.arxiv import PaperRecord, search_arxiv_multi

    calls: list = []

    def fake_search(query, limit=10, sort="date"):
        calls.append(query)
        if query == "a":
            return [
                PaperRecord(paper_id="1", title="A1", abstract=""),
                PaperRecord(paper_id="2", title="A2", abstract=""),
            ]
        if query == "b":
            return [
                PaperRecord(paper_id="2", title="A2-dup", abstract=""),
                PaperRecord(paper_id="3", title="B1", abstract=""),
            ]
        return []

    monkeypatch.setattr(paper_ingest_mod, "search_arxiv_papers", fake_search)
    monkeypatch.setattr(paper_ingest_mod.time, "sleep", lambda _s: None)

    result = search_arxiv_multi(["a", "b"], limit_per_query=5)

    assert [r.paper_id for r in result] == ["1", "2", "3"]
    assert calls == ["a", "b"]


def _video(video_id: str, upload_date: str, *, title: str = "T") -> VideoInfo:
    return VideoInfo(
        video_id,
        title,
        upload_date,
        600,
        f"https://youtube.com/watch?v={video_id}",
        view_count=0,
        like_count=0,
        comment_count=0,
        channel_name="ch",
    )


def test_chronological_rank_returns_videos_in_descending_upload_date_order():
    older = _video("v_old", _date_ago(60), title="old upload")
    newer = _video("v_new", _date_ago(2), title="new upload")
    middle = _video("v_mid", _date_ago(20), title="middle upload")

    ranked = chronological_rank([older, newer, middle], top_n=5)

    assert [r.video.video_id for r in ranked] == ["v_new", "v_mid", "v_old"]


def test_chronological_rank_truncates_at_top_n():
    videos = [_video(f"v{i}", _date_ago(i)) for i in range(10)]

    ranked = chronological_rank(videos, top_n=3)

    assert len(ranked) == 3
    # Smallest days_ago == most recent.
    assert [r.video.video_id for r in ranked] == ["v0", "v1", "v2"]


def test_chronological_rank_sorts_unparseable_dates_to_bottom():
    good = _video("good", _date_ago(5))
    broken = _video("broken", "not-a-date")

    ranked = chronological_rank([broken, good], top_n=2)

    assert [r.video.video_id for r in ranked] == ["good", "broken"]


def test_chronological_rank_records_selected_by_chronological():
    """The provenance field tells downstream code (and the user-facing rationale)
    that scores came from upload date alone, not the heuristic mix."""
    ranked = chronological_rank([_video("v", _date_ago(3))], top_n=1)
    assert ranked[0].selected_by == "chronological"
    assert "upload date" in ranked[0].rationale
