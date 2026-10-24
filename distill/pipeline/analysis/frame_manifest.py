# pyright: strict
"""Bounded frame samples for a local or synthetic video.

Default video analysis does not call this module. A manifest records the
sample grid, blind intervals between samples, repeated slides, and whether
an advertised frame file exists. Qualification is structural: the claim
must match the frame's visible text, and a missing or unreadable frame
does not become evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

__all__ = [
    "FRAME_INTERVAL_MS",
    "FrameManifest",
    "FrameRecord",
    "ManifestInspection",
    "Qualification",
    "VisualAnswer",
    "inspect_manifest",
    "plan_sample_times",
    "qualify_visual_answer",
]

FRAME_INTERVAL_MS = 60_000
ManifestStatus = Literal["complete", "cancelled", "restarted"]
QualificationStatus = Literal[
    "qualified_visual",
    "qualified_transcript",
    "missing_frame",
    "unreadable",
    "blind_interval",
    "disagreement",
    "cancelled",
    "unmatched",
]


@dataclass(frozen=True, slots=True)
class FrameRecord:
    timestamp_ms: int
    relative_path: str
    present: bool
    readable: bool
    visible_text: str
    fingerprint: str


@dataclass(frozen=True, slots=True)
class FrameManifest:
    status: ManifestStatus
    duration_ms: int
    interval_ms: int
    frames: tuple[FrameRecord, ...]


@dataclass(frozen=True, slots=True)
class VisualAnswer:
    """A candidate answer. Transcript-only leaves the frame timestamp empty."""

    claim: str
    frame_timestamp_ms: int | None
    transcript_support: str
    contradicts_transcript: bool


@dataclass(frozen=True, slots=True)
class Qualification:
    status: QualificationStatus
    claim: str
    transcript_support: str
    frame_timestamp_ms: int | None
    detail: str


@dataclass(frozen=True, slots=True)
class ManifestInspection:
    planned_ms: tuple[int, ...]
    missing_planned_ms: tuple[int, ...]
    blind_intervals_ms: tuple[tuple[int, int], ...]
    repeated_slides_ms: tuple[tuple[int, int], ...]


def plan_sample_times(duration_ms: int, interval_ms: int = FRAME_INTERVAL_MS) -> tuple[int, ...]:
    """Sample the start and each later grid point that falls inside the video."""
    if duration_ms <= 0 or interval_ms <= 0:
        return ()
    times: list[int] = []
    timestamp = 0
    while timestamp < duration_ms:
        times.append(timestamp)
        timestamp += interval_ms
    return tuple(times)


def inspect_manifest(manifest: FrameManifest) -> ManifestInspection:
    planned = plan_sample_times(manifest.duration_ms, manifest.interval_ms)
    present_times = {frame.timestamp_ms for frame in manifest.frames}
    missing = tuple(timestamp for timestamp in planned if timestamp not in present_times)
    return ManifestInspection(
        planned_ms=planned,
        missing_planned_ms=missing,
        blind_intervals_ms=_blind(planned, manifest.duration_ms),
        repeated_slides_ms=_repeated(manifest.frames),
    )


def qualify_visual_answer(answer: VisualAnswer, manifest: FrameManifest | None) -> Qualification:
    """Qualify one answer. Transcript-only does not require a frame manifest."""
    if answer.frame_timestamp_ms is None:
        return _transcript_only(answer)
    if manifest is None or manifest.status == "cancelled":
        return _result(answer, "cancelled", "Frame sampling is cancelled or absent.")
    frame = _frame_at(manifest, answer.frame_timestamp_ms)
    if frame is None:
        return _missing_or_blind(answer, manifest)
    if not frame.present:
        return _result(answer, "missing_frame", f"{frame.relative_path} was not materialized.")
    if not frame.readable:
        return _result(answer, "unreadable", "The frame is present and not readable.")
    if answer.claim != frame.visible_text:
        return _result(answer, "unmatched", "The claim does not match the frame text.")
    if answer.contradicts_transcript:
        return _result(
            answer,
            "disagreement",
            "The frame and the transcript disagree. Both are retained.",
        )
    return _result(answer, "qualified_visual", "The claim matches one readable sampled frame.")


def _transcript_only(answer: VisualAnswer) -> Qualification:
    if answer.claim and answer.claim == answer.transcript_support:
        return _result(answer, "qualified_transcript", "The transcript supports the claim.")
    return _result(answer, "unmatched", "The transcript does not support the claim.")


def _missing_or_blind(answer: VisualAnswer, manifest: FrameManifest) -> Qualification:
    timestamp = answer.frame_timestamp_ms
    inspection = inspect_manifest(manifest)
    if timestamp is not None and _inside_blind(timestamp, inspection.blind_intervals_ms):
        return _result(answer, "blind_interval", "The timestamp falls between samples.")
    return _result(answer, "unmatched", "No frame is recorded at that timestamp.")


def _result(answer: VisualAnswer, status: QualificationStatus, detail: str) -> Qualification:
    return Qualification(
        status=status,
        claim=answer.claim,
        transcript_support=answer.transcript_support,
        frame_timestamp_ms=answer.frame_timestamp_ms,
        detail=detail,
    )


def _frame_at(manifest: FrameManifest, timestamp_ms: int) -> FrameRecord | None:
    for frame in manifest.frames:
        if frame.timestamp_ms == timestamp_ms:
            return frame
    return None


def _blind(planned: tuple[int, ...], duration_ms: int) -> tuple[tuple[int, int], ...]:
    if not planned:
        return ()
    intervals: list[tuple[int, int]] = []
    points = (*planned, duration_ms)
    for start, end in pairwise(points):
        if end - start > 1:
            intervals.append((start + 1, end - 1))
    return tuple(intervals)


def _inside_blind(timestamp_ms: int, intervals: tuple[tuple[int, int], ...]) -> bool:
    return any(start <= timestamp_ms <= end for start, end in intervals)


def _repeated(frames: tuple[FrameRecord, ...]) -> tuple[tuple[int, int], ...]:
    ordered = tuple(sorted(frames, key=lambda frame: frame.timestamp_ms))
    pairs: list[tuple[int, int]] = []
    for prev, nxt in pairwise(ordered):
        if prev.fingerprint and prev.fingerprint == nxt.fingerprint:
            pairs.append((prev.timestamp_ms, nxt.timestamp_ms))
    return tuple(pairs)
