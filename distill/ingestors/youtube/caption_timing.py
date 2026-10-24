# pyright: strict
"""Caption timing and coverage beside a plain-text transcript.

The plain transcript stays the analysis prompt. Cue times live in a sidecar
and are never invented for ASR. A missing sidecar is unavailable. A broken
sidecar is failed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Literal, cast

from distill.library.paths import atomic_write_text
from distill.parsing import strict_json_loads

__all__ = [
    "CAPTION_GAP_MS",
    "CAPTION_SCHEMA",
    "CaptionCue",
    "CaptionEvidence",
    "dumps_caption_evidence",
    "evidence_failed",
    "evidence_for_asr",
    "evidence_from_vtt",
    "evidence_unavailable",
    "load_caption_evidence",
    "parse_vtt_cues",
    "timing_sidecar_path",
    "write_caption_evidence",
]

CAPTION_GAP_MS = 60_000
CAPTION_SCHEMA = "caption-evidence.v1"
Coverage = Literal["unavailable", "failed", "empty", "partial", "complete"]
Timing = Literal["unavailable", "unknown", "caption"]
CaptionSource = Literal["youtube_captions", "asr", "none", "interrupted"]
_COVERAGE: frozenset[str] = frozenset({"unavailable", "failed", "empty", "partial", "complete"})
_TIMING: frozenset[str] = frozenset({"unavailable", "unknown", "caption"})
_SOURCES: frozenset[str] = frozenset({"youtube_captions", "asr", "none", "interrupted"})
_KEYS: frozenset[str] = frozenset(
    {"schema", "text_coverage", "timing", "source", "duration_known", "cues", "gaps_ms"}
)
_CUE_KEYS: frozenset[str] = frozenset({"start_ms", "end_ms", "text"})
_TIME = re.compile(r"(?:(?P<h>\d+):)?(?P<m>\d{2}):(?P<s>\d{2})[.](?P<ms>\d{3})")
_TAG = re.compile(r"<[^>]+>")
_SKIP = ("WEBVTT", "NOTE", "STYLE", "Kind:", "Language:")


@dataclass(frozen=True, slots=True)
class CaptionCue:
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True, slots=True)
class CaptionEvidence:
    text_coverage: Coverage
    timing: Timing
    source: CaptionSource
    duration_known: bool
    cues: tuple[CaptionCue, ...]
    gaps_ms: tuple[tuple[int, int], ...]


def timing_sidecar_path(transcript_path: Path) -> Path:
    """Sidecar next to a transcript. The transcript stem is preserved."""
    return transcript_path.with_name(f"{transcript_path.stem}.timing.json")


def evidence_unavailable() -> CaptionEvidence:
    return CaptionEvidence("unavailable", "unavailable", "none", False, (), ())


def evidence_failed(source: CaptionSource) -> CaptionEvidence:
    return CaptionEvidence("failed", "unavailable", source, False, (), ())


def evidence_for_asr(text: str) -> CaptionEvidence:
    """Record ASR text without inventing cue times."""
    if not text.strip():
        return CaptionEvidence("empty", "unavailable", "asr", False, (), ())
    return CaptionEvidence("complete", "unknown", "asr", False, (), ())


def parse_vtt_cues(vtt_content: str) -> tuple[CaptionCue, ...]:
    """Keep one cue per timed block, including repeated caption lines."""
    cues: list[CaptionCue] = []
    for block in _blocks(vtt_content):
        cue = _cue_from_block(block)
        if cue is not None:
            cues.append(cue)
    return tuple(cues)


def evidence_from_vtt(
    vtt_content: str,
    *,
    duration_ms: int | None = None,
    interrupted: bool = False,
) -> CaptionEvidence:
    """Build coverage from cues. Unknown duration does not invent a tail gap."""
    return _from_cues(
        parse_vtt_cues(vtt_content),
        source="interrupted" if interrupted else "youtube_captions",
        duration_ms=duration_ms,
        interrupted=interrupted,
    )


def dumps_caption_evidence(evidence: CaptionEvidence) -> str:
    payload = {
        "schema": CAPTION_SCHEMA,
        "text_coverage": evidence.text_coverage,
        "timing": evidence.timing,
        "source": evidence.source,
        "duration_known": evidence.duration_known,
        "cues": [
            {"start_ms": cue.start_ms, "end_ms": cue.end_ms, "text": cue.text}
            for cue in evidence.cues
        ],
        "gaps_ms": [[start, end] for start, end in evidence.gaps_ms],
    }
    return json.dumps(payload, indent=2) + "\n"


def write_caption_evidence(transcript_path: Path, evidence: CaptionEvidence) -> Path:
    path = timing_sidecar_path(transcript_path)
    atomic_write_text(path, dumps_caption_evidence(evidence))
    return path


def load_caption_evidence(path: Path) -> CaptionEvidence | None:
    """Missing file is unavailable to the caller. Broken JSON is failed."""
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return evidence_failed("none")
    return parse_caption_evidence(raw)


def parse_caption_evidence(raw: str) -> CaptionEvidence:
    try:
        loaded = strict_json_loads(raw)
    except (UnicodeError, ValueError):
        return evidence_failed("none")
    body = _as_dict(loaded)
    if body is None or frozenset(body) != _KEYS or body.get("schema") != CAPTION_SCHEMA:
        return evidence_failed("none")
    coverage = body.get("text_coverage")
    timing = body.get("timing")
    source = body.get("source")
    known = body.get("duration_known")
    if (
        not isinstance(coverage, str)
        or coverage not in _COVERAGE
        or not isinstance(timing, str)
        or timing not in _TIMING
        or not isinstance(source, str)
        or source not in _SOURCES
        or not isinstance(known, bool)
    ):
        return evidence_failed("none")
    cues = _parse_cues(body.get("cues"))
    gaps = _parse_gaps(body.get("gaps_ms"))
    if cues is None or gaps is None:
        return evidence_failed("none")
    return CaptionEvidence(
        cast(Coverage, coverage),
        cast(Timing, timing),
        cast(CaptionSource, source),
        known,
        cues,
        gaps,
    )


def _from_cues(
    cues: tuple[CaptionCue, ...],
    *,
    source: CaptionSource,
    duration_ms: int | None,
    interrupted: bool,
) -> CaptionEvidence:
    known = duration_ms is not None
    gaps = _gaps(cues, duration_ms)
    if interrupted and not cues:
        return CaptionEvidence("failed", "unavailable", "interrupted", known, (), ())
    if interrupted:
        return CaptionEvidence("partial", "caption", "interrupted", known, cues, gaps)
    if not cues:
        return CaptionEvidence("empty", "unavailable", source, known, (), ())
    coverage: Coverage = "partial" if gaps else "complete"
    return CaptionEvidence(coverage, "caption", source, known, cues, gaps)


def _gaps(cues: tuple[CaptionCue, ...], duration_ms: int | None) -> tuple[tuple[int, int], ...]:
    ordered = tuple(sorted(cues, key=lambda cue: (cue.start_ms, cue.end_ms)))
    found: list[tuple[int, int]] = []
    for prev, nxt in pairwise(ordered):
        if nxt.start_ms - prev.end_ms > CAPTION_GAP_MS:
            found.append((prev.end_ms, nxt.start_ms))
    if duration_ms is not None and ordered and duration_ms - ordered[-1].end_ms > CAPTION_GAP_MS:
        found.append((ordered[-1].end_ms, duration_ms))
    return tuple(found)


def _blocks(vtt_content: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in vtt_content.splitlines():
        if line.strip():
            current.append(line.strip())
            continue
        if current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def _cue_from_block(block: list[str]) -> CaptionCue | None:
    if block[0].startswith(_SKIP):
        return None
    arrow_at = next((index for index, line in enumerate(block) if "-->" in line), None)
    if arrow_at is None:
        return None
    times = list(_TIME.finditer(block[arrow_at]))
    if len(times) < 2:
        return None
    start = _milliseconds(times[0])
    end = _milliseconds(times[1])
    if end < start:
        return None
    text = _clean_text(block[arrow_at + 1 :])
    if not text:
        return None
    return CaptionCue(start, end, text)


def _milliseconds(match: re.Match[str]) -> int:
    hours = int(match.group("h") or "0")
    minutes = int(match.group("m"))
    seconds = int(match.group("s"))
    millis = int(match.group("ms"))
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def _clean_text(lines: list[str]) -> str:
    cleaned: list[str] = []
    for line in lines:
        if re.fullmatch(r"\d+", line):
            continue
        text = _TAG.sub("", line).strip()
        if text:
            cleaned.append(text)
    return " ".join(cleaned)


def _as_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    raw = cast(dict[object, object], value)
    typed: dict[str, object] = {}
    for key, item in raw.items():
        if not isinstance(key, str):
            return None
        typed[key] = item
    return typed


def _as_list(value: object) -> tuple[object, ...] | None:
    if not isinstance(value, list):
        return None
    return tuple(cast(list[object], value))


def _parse_cues(value: object) -> tuple[CaptionCue, ...] | None:
    items = _as_list(value)
    if items is None:
        return None
    cues: list[CaptionCue] = []
    for item in items:
        cue = _parse_cue(item)
        if cue is None:
            return None
        cues.append(cue)
    return tuple(cues)


def _parse_cue(value: object) -> CaptionCue | None:
    body = _as_dict(value)
    if body is None or frozenset(body) != _CUE_KEYS:
        return None
    start = _nonnegative(body.get("start_ms"))
    end = _nonnegative(body.get("end_ms"))
    text = body.get("text")
    if start is None or end is None or end < start or not isinstance(text, str) or not text.strip():
        return None
    return CaptionCue(start, end, text)


def _parse_gaps(value: object) -> tuple[tuple[int, int], ...] | None:
    items = _as_list(value)
    if items is None:
        return None
    gaps: list[tuple[int, int]] = []
    for item in items:
        pair = _as_list(item)
        if pair is None or len(pair) != 2:
            return None
        start = _nonnegative(pair[0])
        end = _nonnegative(pair[1])
        if start is None or end is None or end < start:
            return None
        gaps.append((start, end))
    return tuple(gaps)


def _nonnegative(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value
