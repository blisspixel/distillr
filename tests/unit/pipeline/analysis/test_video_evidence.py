"""Connected local image-byte evidence with mocked model transport only.

Passing transport stubs establish contracts, not real vision comprehension.
"""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from dataclasses import replace

import pytest

from distill.config import DistillConfig
from distill.ingestors.youtube.local_frames import LocalVideoFrames, SampledFrame
from distill.llm.router import RouterConfig
from distill.llm.types import LLM_Response
from distill.pipeline.analysis.video import analyze_video
from distill.pipeline.analysis.video_evidence import analyze_local_video_evidence
from distill.pipeline.costs import CostTracker

_CRITERIA = (
    "source_fidelity",
    "material_qualifications",
    "disagreement",
    "coverage_disclosure",
    "detail_and_citations",
)
_LATE = "Late spoken qualification: the ratio is observational and not causal."
_OBSERVATION = "Image 0 shows a legible slide qualification; this is a model description."
_EXTRACTION = f"Mechanism and example from source. {_LATE} {_OBSERVATION}"
_INSIGHT = (
    f"## Findings\n{_EXTRACTION}\nCoverage is sampled-only and original completeness unknown."
)


def _png():
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00\xff"))
        + chunk(b"IEND", b"")
    )


def _review():
    return {
        name: {"verdict": "pass", "reason": f"Reviewed {name} against supplied evidence."}
        for name in _CRITERIA
    }


@pytest.fixture
def source_frames(tmp_path):
    source = b"Fixture source snapshot; codec decoding is qualified by capture tests separately."
    (tmp_path / "source.mp4").write_bytes(source)
    image = _png()
    (tmp_path / "frame.png").write_bytes(image)
    return LocalVideoFrames(
        source_sha256=hashlib.sha256(source).hexdigest(),
        source_relative_path="source.mp4",
        duration_ms=120_000,
        frames=(SampledFrame(60_000, "frame.png", hashlib.sha256(image).hexdigest()),),
        blind_intervals_ms=((0, 59_999), (60_001, 119_999)),
    )


@pytest.fixture
def transport(monkeypatch):
    calls = []
    modifications = {}
    review = _review()

    def respond(router, *, prompt, call_type, **kwargs):
        images = kwargs.get("images", ())
        index = len(calls)
        calls.append({"prompt": prompt, "call_type": call_type, **kwargs})
        text = {
            "video_visual_observation": _OBSERVATION,
            "pass1": _EXTRACTION,
            "pass2": _INSIGHT,
            "video_visual_review": json.dumps(review),
        }[call_type]
        response = LLM_Response(
            text=text,
            model="fixture-model",
            input_tokens=10,
            output_tokens=20,
            provider_name="ollama",
            provider_type="local",
            finish_reason="stop",
            input_image_hashes=tuple(image.sha256 for image in images),
        )
        change = modifications.get(index)
        return change(response) if change is not None else response

    monkeypatch.setattr("distill.pipeline.analysis.video_evidence.llm_call", respond)
    monkeypatch.setattr("distill.pipeline.analysis.video.llm_call", respond)
    return calls, modifications, review


def _run(source_frames, tmp_path, *, router=None, transcript=None, **kwargs):
    return analyze_local_video_evidence(
        "Synthetic video",
        transcript if transcript is not None else "Source opening.\n" + "Context. " * 5000 + _LATE,
        source_frames,
        tmp_path,
        DistillConfig(distill_output_dir=tmp_path / "library"),
        router_config=router
        or RouterConfig(provider="ollama", model="fixture-model", cost_mode="no-metered"),
        question="What is supported and what remains unseen?",
        **kwargs,
    )


def test_actual_images_survive_four_stage_path_with_separate_derived_observations(
    source_frames, tmp_path, transport
):
    calls, _, _ = transport
    tracker = CostTracker()
    result = _run(source_frames, tmp_path, tracker=tracker)
    assert result.status == "model_review_passed"
    assert result.observations is not None and result.observations.origin == "model_description"
    assert result.observations.text == _OBSERVATION
    assert result.review is not None and result.review.all_pass()
    assert len(calls) == len(result.calls) == len(tracker.entries) == 4
    assert [item.stage for item in result.calls] == [
        "video_visual_observation",
        "pass1",
        "pass2",
        "video_visual_review",
    ]
    for index in (0, 3):
        assert calls[index]["images"][0].data == (tmp_path / "frame.png").read_bytes()
        assert source_frames.source_sha256 in calls[index]["prompt"]
        assert source_frames.frames[0].sha256 in calls[index]["prompt"]
        assert "requested_seek_not_measured_pts" in calls[index]["prompt"]
    assert _LATE not in calls[0]["prompt"]
    assert _OBSERVATION not in calls[0]["prompt"]
    assert _LATE in calls[1]["prompt"] and calls[1]["prompt"].index(_LATE) > 30_000
    assert _OBSERVATION in calls[1]["prompt"]
    assert "derived interpretation" in calls[1]["prompt"]
    assert _LATE in calls[2]["prompt"]
    assert result.transcript in calls[3]["prompt"]
    assert result.insight in calls[3]["prompt"]
    assert all(
        call["max_tokens"] == 1024 and call["timeout"] == 60 and call["retries"] == 0
        for call in calls
    )
    record = result.as_record()
    assert record["visual_coverage"] == "sampled_only"
    assert record["original_source_completeness"] == "not_established"
    assert record["text_coverage"] == "not_independently_verified"
    assert json.loads(json.dumps(record))["transcript"] == result.transcript


def test_repeated_frame_payload_is_supplied_once_with_all_requested_anchors(
    source_frames, tmp_path, transport
):
    calls, _, _ = transport
    first = source_frames.frames[0]
    (tmp_path / "repeat.png").write_bytes((tmp_path / first.relative_path).read_bytes())
    repeated = replace(
        source_frames,
        frames=(first, replace(first, timestamp_ms=90_000, relative_path="repeat.png")),
        blind_intervals_ms=((0, 59_999), (60_001, 89_999), (90_001, 119_999)),
    )
    result = _run(repeated, tmp_path)
    assert result.status == "model_review_passed"
    assert len(calls) == 4
    assert result.frames.frames == repeated.frames
    assert result.observations is not None
    assert result.observations.input_image_hashes == (first.sha256,)
    for index in (0, 3):
        assert len(calls[index]["images"]) == 1
        assert result.calls[index].response.input_image_hashes == (first.sha256,)
        assert '"image_index": 0' in calls[index]["prompt"]
        assert '"image_index": 1' not in calls[index]["prompt"]
        assert '"requested_timestamp_ms": 60000' in calls[index]["prompt"]
        assert '"requested_timestamp_ms": 90000' in calls[index]["prompt"]


def test_missing_advertised_repeat_is_not_skipped_by_payload_deduplication(
    source_frames, tmp_path, transport
):
    calls, _, _ = transport
    first = source_frames.frames[0]
    repeated = replace(
        source_frames,
        frames=(first, replace(first, timestamp_ms=90_000, relative_path="missing-repeat.png")),
    )
    result = _run(repeated, tmp_path)
    assert result.status == "incomplete"
    assert "required sampled frame" in result.reason
    assert not calls


@pytest.mark.parametrize(
    "overrides",
    [
        {"provider": "xai", "model": "grok-4.6"},
        {"provider": "lmstudio"},
        {"cost_mode": "paid-ok"},
        {"fallback_provider": "gemini"},
        {"fallback_model": "another-model"},
    ],
)
def test_nonlocal_or_fallback_contract_refuses_before_calls(
    source_frames, tmp_path, transport, overrides
):
    calls, _, _ = transport
    router = RouterConfig(
        provider="ollama", model="fixture-model", cost_mode="no-metered"
    ).model_copy(update=overrides)
    result = _run(source_frames, tmp_path, router=router)
    assert result.status == "incomplete"
    assert not calls


@pytest.mark.parametrize(
    "problem",
    ["missing", "hash", "png", "source", "cancelled", "timestamp", "too_many", "combined_bytes"],
)
def test_frame_acquisition_failures_cannot_reach_models(
    source_frames, tmp_path, transport, problem
):
    calls, _, _ = transport
    frame = source_frames.frames[0]
    if problem == "missing":
        (tmp_path / frame.relative_path).unlink()
    elif problem == "hash":
        source_frames = replace(source_frames, frames=(replace(frame, sha256="0" * 64),))
    elif problem == "png":
        damaged = b"not a PNG at all"
        (tmp_path / frame.relative_path).write_bytes(damaged)
        source_frames = replace(
            source_frames, frames=(replace(frame, sha256=hashlib.sha256(damaged).hexdigest()),)
        )
    elif problem == "source":
        source_frames = replace(source_frames, source_sha256="0" * 64)
    elif problem == "cancelled":
        source_frames = replace(source_frames, status="cancelled")
    elif problem == "timestamp":
        source_frames = replace(
            source_frames, frames=(replace(frame, timestamp_ms=source_frames.duration_ms),)
        )
    elif problem == "too_many":
        source_frames = replace(
            source_frames, frames=tuple(replace(frame, timestamp_ms=i) for i in range(5))
        )
    else:
        large_frames = []
        for index in range(3):
            padded = _png() + bytes([index]) * (3 * 1024 * 1024)
            name = f"large-{index}.png"
            (tmp_path / name).write_bytes(padded)
            large_frames.append(
                replace(
                    frame,
                    timestamp_ms=index,
                    relative_path=name,
                    sha256=hashlib.sha256(padded).hexdigest(),
                )
            )
        source_frames = replace(
            source_frames,
            frames=tuple(large_frames),
        )
    result = _run(source_frames, tmp_path)
    assert result.status == "incomplete"
    assert not calls


@pytest.mark.parametrize("stage", range(4))
@pytest.mark.parametrize("finish_reason", ["length", "max_tokens", "", "content_filter"])
def test_truncated_unknown_or_refused_completions_do_not_qualify(
    source_frames, tmp_path, transport, stage, finish_reason
):
    calls, changes, _ = transport
    changes[stage] = lambda response: replace(response, finish_reason=finish_reason)
    result = _run(source_frames, tmp_path)
    assert result.status == "incomplete"
    assert len(calls) == stage + 1
    assert len(result.calls) == stage + 1


@pytest.mark.parametrize("stage", range(4))
def test_empty_completed_output_is_not_success(source_frames, tmp_path, transport, stage):
    calls, changes, _ = transport
    changes[stage] = lambda response: replace(response, text=" \n")
    result = _run(source_frames, tmp_path)
    assert result.status == "incomplete"
    assert len(calls) == stage + 1


@pytest.mark.parametrize("stage", [0, 3])
def test_visual_calls_require_response_bound_to_exact_image_hashes(
    source_frames, tmp_path, transport, stage
):
    calls, changes, _ = transport
    changes[stage] = lambda response: replace(response, input_image_hashes=())
    result = _run(source_frames, tmp_path)
    assert result.status == "incomplete"
    assert "image hashes" in result.reason
    assert len(calls) == stage + 1


@pytest.mark.parametrize("criterion", _CRITERIA)
@pytest.mark.parametrize("verdict", ["fail", "unknown"])
def test_individual_semantic_failure_cannot_be_hidden_by_other_passes(
    source_frames, tmp_path, transport, criterion, verdict
):
    calls, _, review = transport
    review[criterion] = {"verdict": verdict, "reason": "The source does not settle this criterion."}
    result = _run(source_frames, tmp_path)
    assert result.status == "incomplete"
    assert result.review is not None
    assert getattr(result.review, criterion).verdict == verdict
    assert result.insight
    assert len(calls) == 4


@pytest.mark.parametrize("response_text", ["{", '{"aggregate":"pass"}', "{}", "[]"])
def test_malformed_review_is_not_retried_or_qualified(
    source_frames, tmp_path, transport, response_text
):
    calls, changes, _ = transport
    changes[3] = lambda response: replace(response, text=response_text)
    result = _run(source_frames, tmp_path)
    assert result.status == "incomplete"
    assert result.review is None
    assert len(calls) == 4


def test_blank_review_reason_is_not_a_valid_verdict(source_frames, tmp_path, transport):
    calls, _, review = transport
    review["source_fidelity"]["reason"] = " \n"
    result = _run(source_frames, tmp_path)
    assert result.status == "incomplete"
    assert result.review is None
    assert len(calls) == 4


def test_cancellation_stops_before_next_stage_and_keeps_observed_evidence(
    source_frames, tmp_path, transport
):
    calls, changes, _ = transport
    cancelled = {"value": False}

    def cancel_after_observing(response):
        cancelled["value"] = True
        return response

    changes[0] = cancel_after_observing
    result = _run(source_frames, tmp_path, cancelled=lambda: cancelled["value"])
    assert result.status == "incomplete"
    assert result.observations is not None
    assert len(calls) == 1


def test_initial_cancellation_and_empty_transcript_make_no_calls(
    source_frames, tmp_path, transport
):
    calls, _, _ = transport
    assert _run(source_frames, tmp_path, cancelled=lambda: True).status == "incomplete"
    assert _run(source_frames, tmp_path, transcript="  ").status == "incomplete"
    assert not calls


def test_route_degradation_is_explicit_incomplete(source_frames, tmp_path, transport):
    calls, changes, _ = transport
    changes[0] = lambda response: replace(response, provider_type="unknown")
    assert _run(source_frames, tmp_path).status == "incomplete"
    assert len(calls) == 1


def test_failed_transport_cannot_be_reported_as_reviewed_success(
    source_frames, tmp_path, transport
):
    calls, changes, _ = transport

    def fail_transport(response):
        raise RuntimeError("Synthetic decoder refusal")

    changes[0] = fail_transport
    result = _run(source_frames, tmp_path)
    assert result.status == "incomplete"
    assert "RuntimeError" in result.reason
    assert result.observations is None and result.review is None
    assert len(calls) == 1


@pytest.mark.parametrize("limits", [{"max_tokens": 0}, {"timeout": 0}, {"retries": -1}])
def test_optional_video_limits_refuse_before_transport(tmp_path, transport, limits):
    calls, _, _ = transport
    with pytest.raises(ValueError, match="call limits"):
        analyze_video(
            "T", "", "", "Transcript", DistillConfig(distill_output_dir=tmp_path), **limits
        )
    assert not calls


def test_existing_transcript_only_video_does_not_require_visual_manifest(tmp_path, transport):
    calls, _, _ = transport
    result = analyze_video("T", "", "", "Transcript", DistillConfig(distill_output_dir=tmp_path))
    assert _INSIGHT in result
    assert [call["call_type"] for call in calls] == ["pass1", "pass2"]
    assert all(call.get("images", ()) == () for call in calls)
    assert all(
        call["max_tokens"] == 8192 and call["timeout"] == 300 and call["retries"] == 2
        for call in calls
    )
