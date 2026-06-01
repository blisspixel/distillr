"""Tests for distill.pipeline.preview_cache (commit-by-id discover replay)."""

import pytest

from distill.ingestors.papers.arxiv import PaperRecord
from distill.ingestors.sites.scraper import SiteSeed
from distill.ingestors.youtube.discovery import VideoInfo
from distill.pipeline.discovery import RankedDiscoverItem
from distill.pipeline.preview_cache import (
    PreviewCacheError,
    compute_preview_id,
    list_previews,
    load_preview,
    preview_cache_dir,
    save_preview,
)

_NOW = "2026-06-01T12:00:00"


def _paper_item() -> RankedDiscoverItem:
    return RankedDiscoverItem(
        kind="paper",
        identifier="2601.00001",
        title="A Paper",
        subtitle="Alice, Bob",
        date="2026-01-01",
        final_score=0.91,
        goal_fit=0.9,
        depth_score=0.8,
        complementarity_score=0.7,
        rationale="directly on goal",
        paper=PaperRecord(
            paper_id="2601.00001",
            title="A Paper",
            abstract="An abstract.",
            authors=["Alice", "Bob"],
            categories=["cs.AI"],
            abs_url="https://arxiv.org/abs/2601.00001",
            pdf_url="https://arxiv.org/pdf/2601.00001",
        ),
    )


def _video_item() -> RankedDiscoverItem:
    return RankedDiscoverItem(
        kind="video",
        identifier="vid123",
        title="A Talk",
        subtitle="Some Channel",
        date="20260115",
        final_score=0.8,
        goal_fit=0.8,
        depth_score=0.75,
        complementarity_score=0.6,
        rationale="practitioner depth",
        video=VideoInfo(
            video_id="vid123",
            title="A Talk",
            upload_date="20260115",
            duration=1800,
            url="https://youtu.be/vid123",
            channel_name="Some Channel",
            view_count=1000,
        ),
    )


def _site_item() -> RankedDiscoverItem:
    return RankedDiscoverItem(
        kind="site",
        identifier="https://learn.example.com/guide",
        title="Guide",
        subtitle="learn.example.com",
        date="",
        final_score=0.72,
        goal_fit=0.7,
        depth_score=0.7,
        complementarity_score=0.65,
        rationale="official docs",
        site_seed=SiteSeed(
            url="https://learn.example.com/guide",
            topic="t",
            site_name="Example Docs",
            label="Guide",
        ),
    )


def _estimate() -> dict:
    return {"expected": 0.05, "low": 0.035, "high": 0.075, "calibrated": False}


def test_save_then_load_round_trips_all_source_types(tmp_path):
    cache = preview_cache_dir(tmp_path)
    items = [_paper_item(), _video_item(), _site_item()]
    saved = save_preview(
        cache,
        goal="learn X",
        model="grok-4.3",
        rigor="balanced",
        items=items,
        estimate=_estimate(),
        now_iso=_NOW,
    )

    loaded = load_preview(cache, saved.id)
    assert loaded.id == saved.id
    assert loaded.goal == "learn X"
    assert loaded.rigor == "balanced"
    assert loaded.created_at == _NOW
    assert len(loaded.items) == 3

    paper = next(it for it in loaded.items if it.kind == "paper")
    assert paper.paper is not None
    assert paper.paper.paper_id == "2601.00001"
    assert paper.paper.authors == ["Alice", "Bob"]
    assert paper.final_score == 0.91

    video = next(it for it in loaded.items if it.kind == "video")
    assert video.video is not None
    assert video.video.duration == 1800
    assert video.video.channel_name == "Some Channel"

    site = next(it for it in loaded.items if it.kind == "site")
    assert site.site_seed is not None
    assert site.site_seed.url == "https://learn.example.com/guide"
    assert site.site_seed.label == "Guide"


def test_preview_id_is_content_addressed():
    items = [_paper_item(), _video_item()]
    ids = [it.identifier for it in items]
    a = compute_preview_id("goal one", "m", "balanced", ids)
    b = compute_preview_id("goal one", "m", "balanced", list(reversed(ids)))
    c = compute_preview_id("goal two", "m", "balanced", ids)
    assert a == b  # member order does not change the id
    assert a != c  # a different goal does


def test_save_uses_content_addressed_filename(tmp_path):
    cache = preview_cache_dir(tmp_path)
    saved = save_preview(
        cache,
        goal="g",
        model="",
        rigor="strict",
        items=[_paper_item()],
        estimate=_estimate(),
        now_iso=_NOW,
    )
    assert (cache / f"{saved.id}.json").exists()


def test_load_unknown_id_raises(tmp_path):
    with pytest.raises(PreviewCacheError, match="No previewed set"):
        load_preview(preview_cache_dir(tmp_path), "abc123def0")


def test_load_malformed_id_raises(tmp_path):
    with pytest.raises(PreviewCacheError, match="not a valid preview id"):
        load_preview(preview_cache_dir(tmp_path), "../etc/passwd")


def test_load_corrupt_snapshot_raises(tmp_path):
    cache = preview_cache_dir(tmp_path)
    cache.mkdir(parents=True)
    (cache / "deadbeef00.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(PreviewCacheError, match="unreadable"):
        load_preview(cache, "deadbeef00")


def test_list_previews_returns_metadata(tmp_path):
    cache = preview_cache_dir(tmp_path)
    save_preview(
        cache,
        goal="first goal",
        model="",
        rigor="loose",
        items=[_paper_item()],
        estimate=_estimate(),
        now_iso=_NOW,
    )
    entries = list_previews(cache)
    assert len(entries) == 1
    assert entries[0]["goal"] == "first goal"
    assert entries[0]["rigor"] == "loose"
    assert entries[0]["items"] == 1


def test_list_previews_empty_when_no_cache(tmp_path):
    assert list_previews(preview_cache_dir(tmp_path)) == []
