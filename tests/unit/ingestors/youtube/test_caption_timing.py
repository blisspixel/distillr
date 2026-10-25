"""Caption timestamps stay beside the plain transcript and are not invented."""

import json
from pathlib import Path

import pytest

from distill.ingestors.youtube.caption_timing import (
    CAPTION_GAP_MS,
    evidence_failed,
    evidence_for_asr,
    evidence_from_vtt,
    evidence_unavailable,
    load_caption_evidence,
    parse_caption_evidence,
    parse_vtt_cues,
    write_caption_evidence,
)
from distill.ingestors.youtube.transcripts import _vtt_to_text

_BASIC = """WEBVTT

00:00:01.000 --> 00:00:05.000
Hello world

00:00:05.000 --> 00:00:10.000
This is a test
"""


def test_cues_keep_times_that_plain_text_drops():
    cues = parse_vtt_cues(_BASIC)
    plain = _vtt_to_text(_BASIC)
    assert [cue.text for cue in cues] == ["Hello world", "This is a test"]
    assert cues[0].start_ms == 1000
    assert cues[0].end_ms == 5000
    assert "-->" not in plain
    assert plain == "Hello world This is a test"


def test_repeated_caption_lines_stay_in_the_timed_record():
    vtt = """WEBVTT

00:00:01.000 --> 00:00:05.000
Hello world

00:00:03.000 --> 00:00:07.000
Hello world
"""
    cues = parse_vtt_cues(vtt)
    assert len(cues) == 2
    assert _vtt_to_text(vtt).count("Hello world") == 1


def test_short_and_long_timestamps_and_cue_settings():
    vtt = """WEBVTT

01:02.000 --> 01:03.500 align:start
Short form

1:02:03.004 --> 1:02:04.004
<c.colorCCCCCC>Tagged</c>
"""
    cues = parse_vtt_cues(vtt)
    assert cues[0].start_ms == 62_000
    assert cues[0].end_ms == 63_500
    assert cues[1].start_ms == 3_723_004
    assert cues[1].text == "Tagged"


def test_reversed_timestamp_is_dropped():
    vtt = "WEBVTT\n\n00:00:05.000 --> 00:00:01.000\nBackwards\n"
    assert parse_vtt_cues(vtt) == ()


def test_interior_gap_is_partial_and_unknown_duration_adds_no_tail():
    vtt = """WEBVTT

00:00:01.000 --> 00:00:02.000
Start

00:02:03.000 --> 00:02:04.000
Later
"""
    evidence = evidence_from_vtt(vtt)
    assert evidence.text_coverage == "partial"
    assert evidence.timing == "caption"
    assert evidence.duration_known is False
    assert evidence.gaps_ms == ((2000, 123_000),)
    assert evidence.gaps_ms[0][1] - evidence.gaps_ms[0][0] > CAPTION_GAP_MS


def test_known_duration_records_a_trailing_gap():
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nStart\n"
    evidence = evidence_from_vtt(vtt, duration_ms=120_000)
    assert evidence.duration_known is True
    assert evidence.text_coverage == "partial"
    assert evidence.gaps_ms == ((2000, 120_000),)


@pytest.mark.parametrize("duration_ms", [None, 180_000])
def test_leading_gap_is_partial_even_without_known_duration(duration_ms):
    vtt = "WEBVTT\n\n00:02:00.000 --> 00:02:01.000\nLate start\n"
    evidence = evidence_from_vtt(vtt, duration_ms=duration_ms)
    assert evidence.text_coverage == "partial"
    assert evidence.gaps_ms == ((0, 120_000),)
    assert evidence.duration_known is (duration_ms is not None)


@pytest.mark.parametrize("duration_ms", [None, 180_000, 300_000])
def test_nested_cues_do_not_invent_interior_or_trailing_gaps(duration_ms):
    # Input order is intentionally different from chronological order. The
    # first long interval covers both shorter cues and the apparent gap.
    vtt = (
        "WEBVTT\n\n"
        "00:01:40.000 --> 00:02:00.000\nNested later\n\n"
        "00:00:00.000 --> 00:03:00.000\nLong coverage\n\n"
        "00:00:10.000 --> 00:00:20.000\nNested earlier\n"
    )
    evidence = evidence_from_vtt(vtt, duration_ms=duration_ms)
    expected = ((180_000, 300_000),) if duration_ms == 300_000 else ()
    assert evidence.gaps_ms == expected
    assert evidence.text_coverage == ("partial" if expected else "complete")
    assert len(evidence.cues) == 3


def test_overlapping_chain_preserves_union_and_later_real_gap():
    vtt = (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:01:30.000\nFirst\n\n"
        "00:01:00.000 --> 00:02:30.000\nOverlap\n\n"
        "00:02:00.000 --> 00:03:00.000\nOverlap again\n\n"
        "00:04:01.000 --> 00:04:02.000\nAfter real gap\n"
    )
    evidence = evidence_from_vtt(vtt)
    assert evidence.text_coverage == "partial"
    assert evidence.gaps_ms == ((180_000, 241_000),)


@pytest.mark.parametrize("start_ms", [60_000, 60_001])
def test_leading_gap_retains_strictly_greater_than_sixty_second_policy(start_ms):
    timestamp = f"00:01:00.{start_ms - 60_000:03d}"
    vtt = f"WEBVTT\n\n{timestamp} --> 00:01:01.000\nStart\n"
    evidence = evidence_from_vtt(vtt)
    assert evidence.gaps_ms == (((0, start_ms),) if start_ms > CAPTION_GAP_MS else ())
    assert evidence.text_coverage == ("partial" if start_ms > CAPTION_GAP_MS else "complete")


def test_empty_interrupted_and_asr_states():
    assert evidence_from_vtt("WEBVTT\n\n").text_coverage == "empty"
    interrupted = evidence_from_vtt(_BASIC, interrupted=True)
    assert interrupted.text_coverage == "partial"
    assert interrupted.source == "interrupted"
    assert evidence_from_vtt("", interrupted=True).text_coverage == "failed"
    asr = evidence_for_asr("spoken words without times")
    assert asr.timing == "unknown"
    assert asr.cues == ()
    assert asr.text_coverage == "complete"
    assert evidence_for_asr("  ").text_coverage == "empty"
    assert evidence_failed("none").text_coverage == "failed"


def test_sidecar_round_trip_and_malformed_input(tmp_path):
    transcript = tmp_path / "Demo_Transcript.txt"
    transcript.write_text("Hello world This is a test", encoding="utf-8")
    evidence = evidence_from_vtt(_BASIC)
    path = write_caption_evidence(transcript, evidence)
    assert path.name == "Demo_Transcript.timing.json"
    loaded = load_caption_evidence(path)
    assert loaded == evidence
    assert load_caption_evidence(tmp_path / "missing.timing.json") is None
    path.write_text("{", encoding="utf-8")
    broken = load_caption_evidence(path)
    assert broken is not None
    assert broken.text_coverage == "failed"
    assert parse_caption_evidence('{"schema": "caption-evidence.v1"}').text_coverage == "failed"


def _payload(**overrides: object) -> str:
    body: dict[str, object] = {
        "schema": "caption-evidence.v1",
        "text_coverage": "complete",
        "timing": "caption",
        "source": "youtube_captions",
        "duration_known": False,
        "cues": [{"start_ms": 0, "end_ms": 1000, "text": "Hi"}],
        "gaps_ms": [],
    }
    body.update(overrides)
    return json.dumps(body)


def test_malformed_evidence_and_odd_cues_fail_closed(tmp_path, monkeypatch):
    unavailable = evidence_unavailable()
    assert unavailable.text_coverage == "unavailable"
    assert unavailable.timing == "unavailable"
    for raw in (
        _payload(text_coverage="sometimes"),
        _payload(duration_known=1),
        _payload(cues={}),
        _payload(cues=[1]),
        _payload(cues=[{"start_ms": 5, "end_ms": 1, "text": "Hi"}]),
        _payload(cues=[{"start_ms": True, "end_ms": 1, "text": "Hi"}]),
        _payload(cues=[{"start_ms": 0, "end_ms": 1, "text": "  "}]),
        _payload(cues=[{"start_ms": 0, "end_ms": 1}]),
        _payload(gaps_ms=None),
        _payload(gaps_ms=[[1]]),
        _payload(gaps_ms=[[2, 1]]),
        _payload(gaps_ms=[[-1, 1]]),
        _payload(gaps_ms=[[True, 1]]),
    ):
        assert parse_caption_evidence(raw).text_coverage == "failed"

    vtt = (
        "WEBVTT\n\n\nNOTE aside\n\nnot a cue\n\n00:00:01.000 -->\n\n"
        "00:00:01.000 --> 00:00:02.000\n1\n<c></c>\nHello\n"
    )
    cues = parse_vtt_cues(vtt)
    assert [cue.text for cue in cues] == ["Hello"]

    path = tmp_path / "Demo.timing.json"
    path.write_text("{}", encoding="utf-8")

    def _denied(*_args: object, **_kwargs: object) -> str:
        raise OSError("denied")

    monkeypatch.setattr(Path, "read_text", _denied)
    failed = load_caption_evidence(path)
    assert failed is not None
    assert failed.text_coverage == "failed"
