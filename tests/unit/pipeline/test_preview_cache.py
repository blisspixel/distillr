"""Tests for distill.pipeline.preview_cache (commit-by-id discover replay)."""

import json
from concurrent.futures import ThreadPoolExecutor

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
            section_label="guide",
            source_hint="sitemap",
            freshness_hint="2026-06-18",
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
        settings={"video_limit": 8, "paper_limit": 5, "days": 21, "shorts": True},
    )

    loaded = load_preview(cache, saved.id)
    assert loaded.id == saved.id
    assert loaded.goal == "learn X"
    assert loaded.rigor == "balanced"
    assert loaded.created_at == _NOW
    assert loaded.settings == {
        "video_limit": 8,
        "paper_limit": 5,
        "days": 21,
        "shorts": True,
    }
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
    assert site.site_seed.section_label == "guide"
    assert site.site_seed.source_hint == "sitemap"
    assert site.site_seed.freshness_hint == "2026-06-18"


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


def test_concurrent_identical_saves_leave_one_complete_snapshot(tmp_path):
    cache = preview_cache_dir(tmp_path)

    def save_once(_index: int) -> str:
        return save_preview(
            cache,
            goal="concurrent goal",
            model="grok-4.3",
            rigor="balanced",
            items=[_paper_item(), _video_item()],
            estimate=_estimate(),
            now_iso=_NOW,
            settings={"days": 14},
        ).id

    with ThreadPoolExecutor(max_workers=8) as pool:
        preview_ids = list(pool.map(save_once, range(24)))

    assert len(set(preview_ids)) == 1
    snapshot = load_preview(cache, preview_ids[0])
    assert [item.identifier for item in snapshot.items] == ["2601.00001", "vid123"]


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


def test_load_non_finite_preview_scores_raises(tmp_path):
    cache = preview_cache_dir(tmp_path)
    snapshot = save_preview(
        cache,
        goal="goal",
        model="",
        rigor="balanced",
        items=[_paper_item()],
        estimate=_estimate(),
        now_iso=_NOW,
    )
    path = cache / f"{snapshot.id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["items"][0]["final_score"] = float("nan")
    path.write_text(json.dumps(payload, allow_nan=True), encoding="utf-8")
    with pytest.raises(PreviewCacheError, match="unreadable"):
        load_preview(cache, snapshot.id)


def test_load_wrong_shape_snapshot_raises(tmp_path):
    cache = preview_cache_dir(tmp_path)
    cache.mkdir(parents=True)
    (cache / "deadbeef00.json").write_text("[]", encoding="utf-8")
    with pytest.raises(PreviewCacheError, match="unexpected shape"):
        load_preview(cache, "deadbeef00")


def test_load_snapshot_with_non_object_item_raises(tmp_path):
    cache = preview_cache_dir(tmp_path)
    snapshot = save_preview(
        cache,
        goal="first goal",
        model="",
        rigor="loose",
        items=[_paper_item()],
        estimate=_estimate(),
        now_iso=_NOW,
    )
    (cache / f"{snapshot.id}.json").write_text(
        f'{{"schema_version":1,"id":"{snapshot.id}","items":["not an object"]}}',
        encoding="utf-8",
    )
    with pytest.raises(PreviewCacheError, match="items must contain objects"):
        load_preview(cache, snapshot.id)


def test_load_snapshot_with_id_mismatch_raises(tmp_path):
    cache = preview_cache_dir(tmp_path)
    snapshot = save_preview(
        cache,
        goal="first goal",
        model="",
        rigor="loose",
        items=[_paper_item()],
        estimate=_estimate(),
        now_iso=_NOW,
    )
    (cache / f"{snapshot.id}.json").write_text(
        '{"schema_version":1,"id":"000000","items":[]}',
        encoding="utf-8",
    )
    with pytest.raises(PreviewCacheError, match="id must match"):
        load_preview(cache, snapshot.id)


def test_load_rejects_incompatible_schema_and_listing_skips_it(tmp_path):
    cache = preview_cache_dir(tmp_path)
    snapshot = save_preview(
        cache,
        goal="first goal",
        model="",
        rigor="loose",
        items=[_paper_item()],
        estimate=_estimate(),
        now_iso=_NOW,
    )
    path = cache / f"{snapshot.id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = 2
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PreviewCacheError, match="schema_version must be 1"):
        load_preview(cache, snapshot.id)
    assert list_previews(cache) == []


def test_load_snapshot_with_non_string_metadata_raises(tmp_path):
    cache = preview_cache_dir(tmp_path)
    snapshot = save_preview(
        cache,
        goal="first goal",
        model="",
        rigor="loose",
        items=[_paper_item()],
        estimate=_estimate(),
        now_iso=_NOW,
    )
    payload = json.loads((cache / f"{snapshot.id}.json").read_text(encoding="utf-8"))
    payload["goal"] = 123
    (cache / f"{snapshot.id}.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PreviewCacheError, match="goal must be a string"):
        load_preview(cache, snapshot.id)


def test_load_snapshot_with_non_numeric_score_raises(tmp_path):
    cache = preview_cache_dir(tmp_path)
    snapshot = save_preview(
        cache,
        goal="first goal",
        model="",
        rigor="loose",
        items=[_paper_item()],
        estimate=_estimate(),
        now_iso=_NOW,
    )
    payload = json.loads((cache / f"{snapshot.id}.json").read_text(encoding="utf-8"))
    payload["items"][0]["final_score"] = "0.91"
    (cache / f"{snapshot.id}.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PreviewCacheError, match="final_score must be a number"):
        load_preview(cache, snapshot.id)


def test_load_snapshot_with_bad_paper_record_raises(tmp_path):
    cache = preview_cache_dir(tmp_path)
    snapshot = save_preview(
        cache,
        goal="first goal",
        model="",
        rigor="loose",
        items=[_paper_item()],
        estimate=_estimate(),
        now_iso=_NOW,
    )
    payload = json.loads((cache / f"{snapshot.id}.json").read_text(encoding="utf-8"))
    payload["items"][0]["paper"]["authors"] = ["Alice", 42]
    (cache / f"{snapshot.id}.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PreviewCacheError, match="authors must be a list of strings"):
        load_preview(cache, snapshot.id)


def test_load_snapshot_with_bad_video_record_raises(tmp_path):
    cache = preview_cache_dir(tmp_path)
    snapshot = save_preview(
        cache,
        goal="first goal",
        model="",
        rigor="loose",
        items=[_video_item()],
        estimate=_estimate(),
        now_iso=_NOW,
    )
    payload = json.loads((cache / f"{snapshot.id}.json").read_text(encoding="utf-8"))
    payload["items"][0]["video"]["duration"] = "1800"
    (cache / f"{snapshot.id}.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PreviewCacheError, match="duration must be an integer"):
        load_preview(cache, snapshot.id)


def test_load_snapshot_with_bad_site_seed_record_raises(tmp_path):
    cache = preview_cache_dir(tmp_path)
    snapshot = save_preview(
        cache,
        goal="first goal",
        model="",
        rigor="loose",
        items=[_site_item()],
        estimate=_estimate(),
        now_iso=_NOW,
    )
    payload = json.loads((cache / f"{snapshot.id}.json").read_text(encoding="utf-8"))
    payload["items"][0]["site_seed"]["crawl_prefix"] = 123
    (cache / f"{snapshot.id}.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PreviewCacheError, match="crawl_prefix must be a string"):
        load_preview(cache, snapshot.id)


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


def test_list_previews_skips_wrong_shape_json(tmp_path):
    cache = preview_cache_dir(tmp_path)
    cache.mkdir(parents=True)
    (cache / "deadbeef00.json").write_text("[]", encoding="utf-8")
    assert list_previews(cache) == []


def test_list_previews_skips_bad_metadata_json(tmp_path):
    cache = preview_cache_dir(tmp_path)
    cache.mkdir(parents=True)
    (cache / "deadbeef00.json").write_text(
        '{"id":123,"goal":"first goal","items":[]}',
        encoding="utf-8",
    )
    assert list_previews(cache) == []


def test_list_previews_skips_id_mismatch(tmp_path):
    cache = preview_cache_dir(tmp_path)
    cache.mkdir(parents=True)
    (cache / "deadbeef00.json").write_text(
        '{"id":"000000","goal":"first goal","items":[]}',
        encoding="utf-8",
    )
    assert list_previews(cache) == []


def test_list_previews_skips_bad_nested_item_json(tmp_path):
    cache = preview_cache_dir(tmp_path)
    snapshot = save_preview(
        cache,
        goal="first goal",
        model="",
        rigor="loose",
        items=[_site_item()],
        estimate=_estimate(),
        now_iso=_NOW,
    )
    payload = json.loads((cache / f"{snapshot.id}.json").read_text(encoding="utf-8"))
    payload["items"][0]["site_seed"]["crawl_prefix"] = 123
    (cache / f"{snapshot.id}.json").write_text(json.dumps(payload), encoding="utf-8")

    assert list_previews(cache) == []
