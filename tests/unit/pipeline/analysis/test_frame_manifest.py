"""Synthetic frame manifests qualify visual answers without a model."""

from typing import Literal

from distill.pipeline.analysis.frame_manifest import (
    FrameManifest,
    FrameRecord,
    VisualAnswer,
    inspect_manifest,
    plan_sample_times,
    qualify_visual_answer,
)

_Status = Literal["complete", "cancelled", "restarted"]


def _frame(
    timestamp_ms: int,
    text: str,
    *,
    present: bool = True,
    readable: bool = True,
    fingerprint: str = "slide-a",
    path: str = "frames/sample.png",
) -> FrameRecord:
    return FrameRecord(timestamp_ms, path, present, readable, text, fingerprint)


def _manifest(
    *frames: FrameRecord,
    status: _Status = "complete",
    duration_ms: int = 125_000,
) -> FrameManifest:
    return FrameManifest(status, duration_ms, 60_000, frames)


def test_sample_grid_and_blind_intervals():
    assert plan_sample_times(125_000) == (0, 60_000, 120_000)
    inspection = inspect_manifest(_manifest(_frame(0, "open"), _frame(60_000, "middle")))
    assert inspection.missing_planned_ms == (120_000,)
    assert (1, 59_999) in inspection.blind_intervals_ms
    assert (60_001, 119_999) in inspection.blind_intervals_ms


def test_one_visual_answer_qualifies_from_a_readable_frame():
    manifest = _manifest(_frame(60_000, "denominator: pull requests", fingerprint="ratio"))
    answer = VisualAnswer("denominator: pull requests", 60_000, "", False)
    result = qualify_visual_answer(answer, manifest)
    assert result.status == "qualified_visual"
    assert result.claim == "denominator: pull requests"


def test_transcript_only_does_not_require_frames():
    answer = VisualAnswer("spoken claim", None, "spoken claim", False)
    assert qualify_visual_answer(answer, None).status == "qualified_transcript"
    cancelled = _manifest(status="cancelled")
    assert qualify_visual_answer(answer, cancelled).status == "qualified_transcript"


def test_missing_unreadable_blind_and_disagreement_states():
    missing = _manifest(_frame(60_000, "code", present=False, path="frames/missing.png"))
    missing_answer = VisualAnswer("code", 60_000, "", False)
    assert qualify_visual_answer(missing_answer, missing).status == "missing_frame"

    unreadable = _manifest(_frame(60_000, "code", readable=False))
    assert qualify_visual_answer(VisualAnswer("code", 60_000, "", False), unreadable).status == (
        "unreadable"
    )

    blind = _manifest(_frame(0, "open"), _frame(60_000, "middle"))
    assert qualify_visual_answer(
        VisualAnswer("changed slide", 30_000, "", False), blind
    ).status == ("blind_interval")

    disagreed = _manifest(_frame(60_000, "on screen"))
    answer = VisualAnswer("on screen", 60_000, "the audio says otherwise", True)
    result = qualify_visual_answer(answer, disagreed)
    assert result.status == "disagreement"
    assert result.claim == "on screen"
    assert result.transcript_support == "the audio says otherwise"


def test_repeated_slides_and_restart_use_only_the_current_manifest():
    frames = (
        _frame(0, "same", fingerprint="same"),
        _frame(60_000, "same", fingerprint="same"),
    )
    inspection = inspect_manifest(_manifest(*frames))
    assert inspection.repeated_slides_ms == ((0, 60_000),)
    assert qualify_visual_answer(
        VisualAnswer("same", 60_000, "", False), _manifest(*frames)
    ).status == ("qualified_visual")
    restarted = _manifest(_frame(0, "after restart"), status="restarted", duration_ms=30_000)
    assert (
        qualify_visual_answer(VisualAnswer("old", 60_000, "", False), restarted).status
        == "unmatched"
    )
    cancelled = _manifest(_frame(60_000, "left behind"), status="cancelled")
    assert qualify_visual_answer(
        VisualAnswer("left behind", 60_000, "", False), cancelled
    ).status == ("cancelled")
    assert qualify_visual_answer(VisualAnswer("left behind", 60_000, "", False), None).status == (
        "cancelled"
    )


def test_unmatched_claims_and_an_empty_sample_grid():
    manifest = _manifest(_frame(60_000, "on screen"))
    assert qualify_visual_answer(VisualAnswer("different", 60_000, "", False), manifest).status == (
        "unmatched"
    )
    assert qualify_visual_answer(
        VisualAnswer("spoken", None, "other words", False), None
    ).status == ("unmatched")
    assert plan_sample_times(0) == ()
    assert plan_sample_times(10_000, 0) == ()
    empty = inspect_manifest(_manifest(status="complete", duration_ms=0))
    assert empty.planned_ms == ()
    assert empty.blind_intervals_ms == ()
    different = inspect_manifest(
        _manifest(_frame(0, "a", fingerprint="a"), _frame(60_000, "b", fingerprint=""))
    )
    assert different.repeated_slides_ms == ()
