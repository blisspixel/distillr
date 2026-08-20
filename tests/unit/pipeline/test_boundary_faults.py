"""Verification-depth Phase 3: fault injection at external write boundaries.

The named injection classes from docs/design/verification-depth.md:

1. malformed or empty LLM output
2. empty / truncated transcripts
3. network fetch failures
4. yt-dlp failures

Each class must fail closed: no insight artifact, receipts stay, a later
retry can still succeed. These tests drive the real paper, video, and site
write helpers rather than isolated parsers.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from distill.claims.extract import extract_claims_from_insight
from distill.commands import _helpers as helpers_mod
from distill.commands import _site_ingest as ingest_mod
from distill.commands._paper_artifacts import write_paper_artifacts
from distill.config import DistillConfig
from distill.ingestors.papers.arxiv import PaperRecord, fetch_paper_pdf_text
from distill.ingestors.sites.scraper import SitePage, SiteSeed
from distill.ingestors.youtube.discovery import VideoInfo, discover_videos
from distill.library.paths import find_artifact
from distill.llm.router import RouterConfig
from distill.pipeline.costs import CostTracker
from distill.pipeline.ranking import _parse_paper_rerank_response, _parse_rerank_response
from distill.pipeline.summary import RunSummary


def _config(tmp_path: Path) -> DistillConfig:
    return DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "library")


def _paper() -> PaperRecord:
    return PaperRecord(
        paper_id="2601.00099v1",
        title="Fault Injection",
        abstract="A paper about fail-closed writes.",
    )


def _video() -> VideoInfo:
    upload = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    return VideoInfo(
        video_id="dQwReplay00",
        title="Fault Video",
        upload_date=upload,
        duration=600,
        url="https://www.youtube.com/watch?v=dQwReplay00",
        channel_name="TestCh",
        channel_url="https://www.youtube.com/@TestCh",
    )


def _frontmatter_only() -> str:
    return '---\nvideo_title: "Fault Video"\n---\n\n  \n'


class _StubResponse:
    def __init__(self, text: str, model: str = "stub-model") -> None:
        self.text = text
        self.model = model
        self.input_tokens = 1
        self.output_tokens = 1


def _assert_no_insights(directory: Path) -> None:
    assert list(directory.glob("*_Insights.md")) == []
    assert not (directory / "insights.md").exists()
    insights = find_artifact(directory, "insights")
    assert not insights.exists()


def test_empty_paper_analysis_keeps_receipt_and_skips_insight(tmp_path: Path) -> None:
    config = _config(tmp_path)
    paper_dir = write_paper_artifacts(
        "faults",
        _paper(),
        config,
        insights=_frontmatter_only(),
        document="The captured paper receipt.",
    )

    assert list(paper_dir.glob("*_Paper.md"))
    assert list(paper_dir.glob("*_Verify.json")) == []
    _assert_no_insights(paper_dir)


def test_empty_paper_analysis_does_not_overwrite_existing_insight(tmp_path: Path) -> None:
    config = _config(tmp_path)
    paper_dir = write_paper_artifacts(
        "faults",
        _paper(),
        config,
        insights="### Core\n- A grounded finding.\n",
        document="The captured paper receipt.",
    )
    insight_path = find_artifact(paper_dir, "insights")
    before = insight_path.read_text(encoding="utf-8")

    write_paper_artifacts(
        "faults",
        _paper(),
        config,
        insights=_frontmatter_only(),
        document="The captured paper receipt.",
    )

    assert insight_path.read_text(encoding="utf-8") == before


def test_empty_video_analysis_keeps_transcript_and_skips_insight(
    tmp_path: Path, monkeypatch
) -> None:
    config = _config(tmp_path)
    video = _video()
    summary = RunSummary(command="test")
    tracker = CostTracker()

    def write_transcript(_url, _video_id, transcript_file, _cfg, tracker=None):
        transcript_file.parent.mkdir(parents=True, exist_ok=True)
        transcript_file.write_text("Enough transcript text to analyze.", encoding="utf-8")
        return True

    monkeypatch.setattr(helpers_mod, "get_transcript", write_transcript)
    monkeypatch.setattr(helpers_mod, "analyze_video", lambda *_a, **_k: _frontmatter_only())
    monkeypatch.setattr(helpers_mod, "load_intent", lambda *_a, **_k: None)

    ok = helpers_mod.process_video("ai", "TestCh", video, config, tracker, summary)

    assert ok is False
    assert summary.results[0].success is False
    assert summary.results[0].error == "Empty analysis"
    vid_dir = config.video_dir_slug("ai", "TestCh", video.title, video.video_id)
    assert find_artifact(vid_dir, "transcript", extension="txt").exists()
    assert (vid_dir / "metadata.json").exists()
    _assert_no_insights(vid_dir)


def test_empty_transcript_skips_insight(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    video = _video()
    summary = RunSummary(command="test")
    tracker = CostTracker()
    analyzed = {"called": False}

    def write_empty(_url, _video_id, transcript_file, _cfg, tracker=None):
        transcript_file.parent.mkdir(parents=True, exist_ok=True)
        transcript_file.write_text("   \n", encoding="utf-8")
        return True

    def mark_analyzed(*_a, **_k):
        analyzed["called"] = True
        raise AssertionError("analysis must not run on an empty transcript")

    monkeypatch.setattr(helpers_mod, "get_transcript", write_empty)
    monkeypatch.setattr(helpers_mod, "analyze_video", mark_analyzed)

    ok = helpers_mod.process_video("ai", "TestCh", video, config, tracker, summary)

    assert ok is False
    assert analyzed["called"] is False
    assert summary.results[0].error == "Empty transcript"
    vid_dir = config.video_dir_slug("ai", "TestCh", video.title, video.video_id)
    _assert_no_insights(vid_dir)


def test_ytdlp_failure_skips_insight(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    video = _video()
    summary = RunSummary(command="test")
    tracker = CostTracker()
    analyzed = {"called": False}

    monkeypatch.setattr(helpers_mod, "get_transcript", lambda *_a, **_k: False)
    monkeypatch.setattr(
        helpers_mod,
        "analyze_video",
        lambda *_a, **_k: analyzed.__setitem__("called", True) or "body",
    )

    ok = helpers_mod.process_video("ai", "TestCh", video, config, tracker, summary)

    assert ok is False
    assert analyzed["called"] is False
    assert summary.results[0].error == "No transcript"
    vid_dir = config.video_dir_slug("ai", "TestCh", video.title, video.video_id)
    _assert_no_insights(vid_dir)


def test_ytdlp_discovery_exception_returns_no_candidates() -> None:
    with patch("distill.ingestors.youtube.discovery.SafeYoutubeDL") as mock_ydl_cls:
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.side_effect = Exception("network error")
        assert discover_videos("https://www.youtube.com/@Test") == []


def test_empty_site_analysis_keeps_content_and_skips_insight(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    config.distill_verify = "off"
    page = SitePage(
        url="https://shared.example/docs/fault",
        final_url="https://shared.example/docs/fault",
        canonical_url="https://shared.example/docs/fault",
        title="Fault page",
        site_name="shared.example",
        page_type="article",
        text="Stable page content.",
    )
    monkeypatch.setattr(ingest_mod, "crawl_site", lambda _seed: [page])
    monkeypatch.setattr(ingest_mod, "analyze_site_page", lambda *_a, **_k: _frontmatter_only())
    monkeypatch.setattr(ingest_mod, "synthesize_site", lambda *_a, **_k: "")
    monkeypatch.setattr(ingest_mod, "resolve_intent", lambda *_a, **_k: None)
    summary = RunSummary(command="test")

    result = ingest_mod.process_site_seed(
        SiteSeed(url="https://shared.example/docs", topic="web"),
        config,
        CostTracker(),
        summary,
    )

    assert result.analyzed_pages == 0
    pages_dir = config.site_pages_dir("web", "shared.example")
    page_dirs = [path for path in pages_dir.iterdir() if path.is_dir()]
    assert len(page_dirs) == 1
    assert find_artifact(page_dirs[0], "content").exists()
    _assert_no_insights(page_dirs[0])
    assert any(issue.message.startswith("empty analysis") for issue in summary.issues)


def test_malformed_llm_json_does_not_rank_or_extract_claims(tmp_path: Path) -> None:
    assert _parse_rerank_response("not json") == []
    assert _parse_rerank_response("{") == []
    assert _parse_paper_rerank_response("not json") == []
    insight = tmp_path / "x_Insights.md"
    insight.write_text("---\npaper_id: x1\n---\n\nBody.\n", encoding="utf-8")
    with patch(
        "distill.claims.extract.llm_call",
        return_value=_StubResponse("this is not json"),
    ):
        result = extract_claims_from_insight(
            insight,
            topic="ai",
            source_id="x1",
            artifact_path="papers/x/x_Insights.md",
            rc=RouterConfig(),
        )
    assert result.parsed is False
    assert result.claims == []


def test_paper_pdf_fetch_failure_returns_empty_receipt_text(monkeypatch) -> None:
    monkeypatch.setattr(
        "distill.ingestors.papers.arxiv.requests.get",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("deadline")),
    )
    assert fetch_paper_pdf_text("https://arxiv.org/pdf/2602.12670.pdf") == ""
