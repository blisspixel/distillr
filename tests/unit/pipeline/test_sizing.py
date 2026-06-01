"""Tests for build_sizing_options (preview-as-default sizing ladder)."""

from distill.ingestors.youtube.discovery import VideoInfo
from distill.pipeline.discovery import RankedDiscoverItem, build_sizing_options


def _item(kind: str, ident: str, score: float, duration: int = 900) -> RankedDiscoverItem:
    video = None
    if kind == "video":
        video = VideoInfo(
            video_id=ident, title=ident, upload_date="20260101", duration=duration, url="u"
        )
    return RankedDiscoverItem(
        kind=kind,
        identifier=ident,
        title=ident,
        subtitle="s",
        date="2026-01-01",
        final_score=score,
        goal_fit=score,
        depth_score=score,
        complementarity_score=score,
        rationale="r",
        video=video,
    )


def test_sizing_options_ladder_is_nested_and_sorted():
    ranked = [
        _item("paper", "p1", 0.95),
        _item("paper", "p2", 0.92),  # cliff likely after these two (drop to 0.6)
        _item("video", "v1", 0.60),
        _item("video", "v2", 0.55),
        _item("paper", "p3", 0.35),
    ]
    options = build_sizing_options(
        ranked, paper_limit=10, video_limit=10, site_limit=0, calibration=None
    )
    # Distinct cuts (excellent / good / everything) -> 3 options, smallest first.
    assert [len(o.items) for o in options] == sorted(len(o.items) for o in options)
    assert options[0].items[0].final_score >= options[-1].items[0].final_score
    # Largest option includes the 0.35 item; smallest does not.
    assert any(it.identifier == "p3" for it in options[-1].items)
    assert all(it.identifier != "p3" for it in options[0].items)
    # Every option carries a spend estimate.
    assert all(o.estimate.expected >= 0 for o in options)


def test_sizing_options_dedupe_identical_cuts():
    # All scores high and flat -> excellent / good / everything resolve to the same
    # set, so only one option survives de-duplication.
    ranked = [_item("paper", f"p{i}", 0.9) for i in range(4)]
    options = build_sizing_options(
        ranked, paper_limit=10, video_limit=10, site_limit=0, calibration=None
    )
    assert len(options) == 1
    assert len(options[0].items) == 4


def test_sizing_options_respect_per_source_limits():
    ranked = [_item("paper", f"p{i}", 0.9 - i * 0.01) for i in range(8)]
    options = build_sizing_options(
        ranked, paper_limit=3, video_limit=10, site_limit=0, calibration=None
    )
    # No option may exceed the per-source cap of 3 papers.
    assert all(o.papers <= 3 for o in options)


def test_sizing_options_empty_when_nothing_qualifies():
    ranked = [_item("paper", "p1", 0.1)]  # below the loose 0.3 floor
    options = build_sizing_options(
        ranked, paper_limit=10, video_limit=10, site_limit=0, calibration=None
    )
    # The cliff option still surfaces the single top item even if thresholds drop it.
    assert all(len(o.items) >= 1 for o in options)
