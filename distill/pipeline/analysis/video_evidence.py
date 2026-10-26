# pyright: strict
"""Opt-in local sampled-image understanding, separate from default video analysis."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from distill.config import DistillConfig
from distill.ingestors.youtube.local_frames import MAX_SOURCE_BYTES, LocalVideoFrames
from distill.library.confined import read_confined_bytes
from distill.llm import call as llm_call
from distill.llm.images import MAX_IMAGE_BYTES, MAX_IMAGES, LLMImage, validate_images
from distill.llm.json_extract import extract_json
from distill.llm.router import LLMRouterError, RouterConfig
from distill.llm.types import LLM_Response
from distill.pipeline.analysis.video import analyze_video
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.shared import UNTRUSTED_CONTENT_RULES

_MAX_TRANSCRIPT_BYTES = 2 * 1024 * 1024
_DEFAULT_MAX_TOKENS = 4096
_TIMEOUT_SECONDS = 60
_VERDICT = Literal["pass", "fail", "unknown"]
TranscriptOrigin = Literal["provided_text", "captions", "asr", "model_brief"]
_SAMPLED_EVIDENCE_REQUIREMENTS = (
    "Describe only what the supplied source evidence supports. Keep source content separate "
    "from the caller's title, research question, contextual labels, and your interpretations. "
    "Do not infer a study design or source finding from caller-provided context. "
    "Do not expand undefined acronyms or propose possible expansions; retain the literal "
    "acronym and state that its meaning is unknown. Do not invent author motives, mechanisms, "
    "examples, baseline data, or statistical support absent from the evidence. "
    "Retain material qualifications and unresolved spoken/visual disagreement. "
    "Requested frame anchors establish observations only at those samples, never continuous "
    "visibility throughout an interval between them. Identical frame bytes at multiple anchors "
    "do not prove what appeared between anchors. Disclose blind intervals and unknown original "
    "source completeness. Cite supplied source/image identities and requested anchors exactly. "
    "A source's missing definitions or data are evidence limitations to disclose, not blanks to fill."
)


class CriterionVerdict(BaseModel):
    """A model judgment and its inspectable evidence explanation."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, str_strip_whitespace=True)
    verdict: _VERDICT
    reason: str = Field(min_length=1)


class VideoEvidenceReview(BaseModel):
    """No aggregate score can conceal an individual failed or unknown criterion."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    source_fidelity: CriterionVerdict
    material_qualifications: CriterionVerdict
    disagreement: CriterionVerdict
    coverage_disclosure: CriterionVerdict
    detail_and_citations: CriterionVerdict

    def all_pass(self) -> bool:
        return all(
            item.verdict == "pass"
            for item in (
                self.source_fidelity,
                self.material_qualifications,
                self.disagreement,
                self.coverage_disclosure,
                self.detail_and_citations,
            )
        )


@dataclass(frozen=True, slots=True)
class ModelFrameObservations:
    text: str
    model: str
    input_image_hashes: tuple[str, ...]
    origin: Literal["model_description"] = "model_description"


@dataclass(frozen=True, slots=True)
class EvidenceCall:
    stage: str
    response: LLM_Response


@dataclass(frozen=True, slots=True)
class VideoEvidenceResult:
    status: Literal["incomplete", "model_review_passed"]
    reason: str
    transcript: str
    transcript_sha256: str
    frames: LocalVideoFrames
    insight: str = ""
    observations: ModelFrameObservations | None = None
    review: VideoEvidenceReview | None = None
    calls: tuple[EvidenceCall, ...] = ()
    visual_coverage: Literal["sampled_only"] = "sampled_only"
    original_source_completeness: Literal["not_established"] = "not_established"
    transcript_origin: TranscriptOrigin = "provided_text"
    transcript_source_sha256: str | None = None

    def as_record(self) -> dict[str, object]:
        """Return caller-owned evidence; this function performs no artifact writes."""
        return {
            "schema": "local-video-evidence.v1",
            "status": self.status,
            "reason": self.reason,
            "transcript": self.transcript,
            "transcript_sha256": self.transcript_sha256,
            "transcript_origin": self.transcript_origin,
            "transcript_source_sha256": self.transcript_source_sha256,
            "frames": asdict(self.frames),
            "insight": self.insight,
            "observations": asdict(self.observations) if self.observations is not None else None,
            "review": self.review.model_dump() if self.review is not None else None,
            "calls": [asdict(item) for item in self.calls],
            "visual_coverage": self.visual_coverage,
            "original_source_completeness": self.original_source_completeness,
            "text_coverage": "not_independently_verified",
            "semantic_review": "local_model_review_not_independent_ground_truth",
        }


class _Incomplete(ValueError):
    """A precise evidence boundary prevented qualification."""


def _check_route(router: RouterConfig) -> None:
    if router.resolve("analysis")[0] != "ollama" or router.cost_mode != "no-metered":
        raise _Incomplete("This opt-in evidence path requires an Ollama no-metered analysis route.")
    if router.fallback_provider or router.fallback_model:
        raise _Incomplete("This local evidence path requires all configured fallbacks to be unset.")


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise _Incomplete("Local video evidence processing was cancelled.")


def _load_images(frames: LocalVideoFrames, frame_root: Path) -> tuple[LLMImage, ...]:
    if frames.status != "complete" or not 0 < len(frames.frames) <= MAX_IMAGES:
        raise _Incomplete("Required frame acquisition is cancelled, empty, or exceeds four frames.")
    source = read_confined_bytes(
        frame_root / frames.source_relative_path, frame_root, max_bytes=MAX_SOURCE_BYTES
    )
    if source is None or hashlib.sha256(source).hexdigest() != frames.source_sha256:
        raise _Incomplete(
            "The retained local source snapshot is missing, unsafe, or hash-mismatched."
        )
    timestamps = [frame.timestamp_ms for frame in frames.frames]
    if (
        frames.duration_ms <= 0
        or len(set(timestamps)) != len(timestamps)
        or any(timestamp < 0 or timestamp >= frames.duration_ms for timestamp in timestamps)
    ):
        raise _Incomplete("Requested frame anchors do not match the declared bounded source.")
    images: list[LLMImage] = []
    supplied_hashes: set[str] = set()
    for frame in frames.frames:
        content = read_confined_bytes(
            frame_root / frame.relative_path, frame_root, max_bytes=MAX_IMAGE_BYTES
        )
        if content is None or hashlib.sha256(content).hexdigest() != frame.sha256:
            raise _Incomplete("A required sampled frame is missing, unsafe, or hash-mismatched.")
        image = LLMImage(content)
        if image.sha256 not in supplied_hashes:
            images.append(image)
            supplied_hashes.add(image.sha256)
    result = tuple(images)
    validate_images(result)
    return result


def _frame_identity(frames: LocalVideoFrames) -> str:
    payload_indices: dict[str, int] = {}
    for frame in frames.frames:
        payload_indices.setdefault(frame.sha256, len(payload_indices))
    return json.dumps(
        {
            "source_sha256": frames.source_sha256,
            "timestamp_basis": frames.timestamp_basis,
            "frames": [
                {
                    "image_index": payload_indices[frame.sha256],
                    "requested_timestamp_ms": frame.timestamp_ms,
                    "sha256": frame.sha256,
                }
                for frame in frames.frames
            ],
        },
        sort_keys=True,
    )


def _observation_prompt(frames: LocalVideoFrames) -> str:
    return (
        "Describe the actual supplied sampled PNG images in detailed text, in unique payload image order. "
        "Repeated requested anchors share image_index only for identical frame bytes; "
        "repetition is not independent corroboration. "
        "For each requested time anchor, separate legible quoted text from visual description "
        "and interpretation. A model's reading is not independently verified OCR. Mark "
        "undefined acronyms as undefined; do not expand them or invent author motives. "
        "Keep actual quotations separate from unverified interpretation. "
        "unreadable code or text unknown; do not invent unseen frames or omitted details. "
        "These are samples, not complete video coverage. No expected answer is supplied.\n"
        f"SECURITY: {UNTRUSTED_CONTENT_RULES}\n"
        f"Source and image identities: {_frame_identity(frames)}"
    )


def _text_provenance(origin: TranscriptOrigin, source_sha256: str | None) -> str:
    derivation = (
        "model-derived text, not verbatim primary evidence"
        if origin in {"asr", "model_brief"}
        else "supplied text, not established as verbatim primary evidence"
    )
    return (
        f"CAPTURED TEXT origin={origin}; {derivation}; "
        f"source_sha256={source_sha256 or 'unbound'}; "
        "text fidelity and temporal completeness are not independently verified."
    )


def _origin_is_valid(value: object) -> bool:
    return isinstance(value, str) and value in {"provided_text", "captions", "asr", "model_brief"}


def _combined_evidence(
    transcript: str,
    observations: ModelFrameObservations,
    frames: LocalVideoFrames,
    text_provenance: str,
) -> str:
    return (
        f"{text_provenance}\n"
        f"{transcript}\n\n"
        "SAMPLED VISUAL MODEL DESCRIPTION (derived interpretation, not independent primary text "
        "or independently verified OCR; preserve uncertainty and disagreement):\n"
        f"{observations.text}\n\n"
        f"SOURCE IDENTITIES: {_frame_identity(frames)}\n"
        "COVERAGE: sampled images only; original source completeness not established. "
        f"Blind intervals in milliseconds: {json.dumps(frames.blind_intervals_ms)}. "
        "Times are requested seek anchors, not measured frame presentation times. "
        "Cite transcript passages and source/image hash plus requested time anchors when supported. "
        "Do not treat the model description as independent corroboration of itself."
    )


def _review_prompt(
    transcript: str, insight: str, frames: LocalVideoFrames, question: str, text_provenance: str
) -> str:
    return (
        "Review the candidate against the actual supplied sampled images and captured text, "
        "respecting its declared origin and unverified fidelity. "
        "The CANDIDATE is the object being evaluated, not the quality or completeness of the "
        "underlying study or slides. Judge whether the candidate faithfully represents the "
        "available evidence and visibly discloses its limitations. Missing source definitions, "
        "baseline data, statistics, or external references do not automatically fail a candidate "
        "that explicitly preserves those gaps without overclaiming. Never demand invented data "
        "to repair a weak source. Fail unsupported candidate additions, invented acronym expansions, "
        "or claims of continuous visual coverage inferred from separate samples. "
        "Judge each criterion independently as pass, fail, or unknown with a source-based reason. "
        "Return JSON only, with exactly these five objects, each with verdict and reason: "
        "source_fidelity, material_qualifications, disagreement, coverage_disclosure, "
        "detail_and_citations. source_fidelity checks actual support and metric/denominator scope; "
        "material_qualifications checks decisive limitations; disagreement checks preservation of "
        "audio/image conflicts; coverage_disclosure checks sampled-only and unknown source coverage; "
        "detail_and_citations checks useful mechanisms/examples and supported time/hash citations. "
        "An unreadable decisive qualification is unknown, not a pass. A fluent recap alone is insufficient. "
        "This review is model judgment, not independent ground truth.\n"
        "Required JSON shape (replace each unknown and reason with your judgment): "
        + json.dumps(
            {
                name: {"verdict": "unknown", "reason": "State the evidence and limitation."}
                for name in VideoEvidenceReview.model_fields
            }
        )
        + "\n"
        "A repeated image_index means identical supplied frame bytes at several requested anchors, "
        "not independent corroborating evidence.\n"
        f"SECURITY: {UNTRUSTED_CONTENT_RULES}\n"
        f"QUESTION: {question}\nIDENTITIES: {_frame_identity(frames)}\n"
        f"BLIND INTERVALS MS: {json.dumps(frames.blind_intervals_ms)}\n"
        f"{text_provenance}\n{transcript}\nCANDIDATE:\n{insight}"
    )


def _require_response(stage: str, response: LLM_Response, hashes: tuple[str, ...] = ()) -> None:
    if response.provider_name != "ollama" or response.provider_type != "local":
        raise _Incomplete(f"{stage} did not return a confirmed local Ollama route identity.")
    if not response.text.strip():
        raise _Incomplete(f"{stage} returned no output.")
    if response.finish_reason != "stop":
        raise _Incomplete(f"{stage} did not confirm an untruncated completed response.")
    if response.input_image_hashes != hashes:
        raise _Incomplete(f"{stage} did not confirm the exact supplied image hashes.")


def _vision_call(
    router: RouterConfig,
    prompt: str,
    images: tuple[LLMImage, ...],
    stage: str,
    tracker: CostTracker,
    max_tokens: int,
) -> LLM_Response:
    response = llm_call(
        router,
        workload_tag="analysis",
        prompt=prompt,
        images=images,
        call_type=stage,
        max_tokens=max_tokens,
        timeout=_TIMEOUT_SECONDS,
        retries=0,
        temperature=0.0,
        usage_tracker=tracker,
    )
    tracker.record(TokenUsage.from_response(response, call_type=stage))
    return response


def _parse_review(text: str) -> VideoEvidenceReview:
    try:
        return VideoEvidenceReview.model_validate(extract_json(text))
    except ValidationError as exc:
        raise _Incomplete(
            "The visual review did not provide the required per-criterion verdicts."
        ) from exc


def analyze_local_video_evidence(
    title: str,
    transcript: str,
    frames: LocalVideoFrames,
    frame_root: Path,
    config: DistillConfig,
    *,
    router_config: RouterConfig,
    tracker: CostTracker | None = None,
    question: str = "",
    cancelled: Callable[[], bool] | None = None,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    transcript_origin: TranscriptOrigin = "provided_text",
    transcript_source_sha256: str | None = None,
) -> VideoEvidenceResult:
    """Use two image calls around existing two-pass text analysis, opt-in only.

    Four logical calls at most. Existing provider-attempt receipts remain the
    accounting authority. A passing result is model-reviewed sampled evidence,
    not human validation, complete video capture, or universal prose verification.
    """
    result = VideoEvidenceResult("incomplete", "Not processed.", transcript, "", frames)
    calls: list[EvidenceCall] = []
    ledger = tracker if tracker is not None else CostTracker()
    try:
        if not _origin_is_valid(transcript_origin):
            raise _Incomplete("Captured text origin is invalid.")
        if transcript_source_sha256 is not None and type(transcript_source_sha256) is not str:
            raise _Incomplete("Captured text source hash must be a string.")
        result = replace(
            result,
            transcript_origin=transcript_origin,
            transcript_source_sha256=transcript_source_sha256,
        )
        if (
            transcript_source_sha256 is not None
            and transcript_source_sha256 != frames.source_sha256
        ):
            raise _Incomplete("Captured text source hash does not match the retained video source.")
        text_provenance = _text_provenance(transcript_origin, transcript_source_sha256)
        if type(max_tokens) is not int or not 1 <= max_tokens <= 8192:
            raise _Incomplete("Output token budget must be an integer from 1 to 8192.")
        _check_route(router_config)
        _check_cancelled(cancelled)
        encoded = transcript.encode("utf-8")
        if not transcript.strip() or len(encoded) > _MAX_TRANSCRIPT_BYTES:
            raise _Incomplete("Transcript is empty or exceeds the two-MiB complete-input bound.")
        result = replace(result, transcript_sha256=hashlib.sha256(encoded).hexdigest())
        images = _load_images(frames, frame_root)
        hashes = tuple(image.sha256 for image in images)
        _check_cancelled(cancelled)
        observed = _vision_call(
            router_config,
            _observation_prompt(frames),
            images,
            "video_visual_observation",
            ledger,
            max_tokens,
        )
        calls.append(EvidenceCall("video_visual_observation", observed))
        _require_response("Visual observation", observed, hashes)
        observations = ModelFrameObservations(observed.text, observed.model, hashes)
        result = replace(result, observations=observations)

        def observe_text(stage: str, response: LLM_Response) -> None:
            calls.append(EvidenceCall(stage, response))
            _require_response(stage, response)
            _check_cancelled(cancelled)

        _check_cancelled(cancelled)
        insight = analyze_video(
            title,
            "",
            "",
            _combined_evidence(transcript, observations, frames, text_provenance),
            config,
            tracker=ledger,
            custom_instructions=question,
            router_config=router_config,
            response_observer=observe_text,
            max_tokens=max_tokens,
            timeout=_TIMEOUT_SECONDS,
            retries=0,
            trusted_analysis_instructions=f"{_SAMPLED_EVIDENCE_REQUIREMENTS}\n{text_provenance}",
        )
        result = replace(result, insight=insight)
        _check_cancelled(cancelled)
        reviewed = _vision_call(
            router_config,
            _review_prompt(transcript, insight, frames, question, text_provenance),
            images,
            "video_visual_review",
            ledger,
            max_tokens,
        )
        calls.append(EvidenceCall("video_visual_review", reviewed))
        _require_response("Visual review", reviewed, hashes)
        review = _parse_review(reviewed.text)
        result = replace(result, review=review)
        _check_cancelled(cancelled)
        if not review.all_pass():
            raise _Incomplete("At least one semantic review criterion failed or remains unknown.")
        return replace(
            result,
            status="model_review_passed",
            reason="All local model-review criteria passed; sampled coverage only.",
            calls=tuple(calls),
        )
    except _Incomplete as exc:
        return replace(result, reason=str(exc), calls=tuple(calls))
    except (LLMRouterError, OSError, RuntimeError, ValueError) as exc:
        return replace(
            result,
            reason=f"Local evidence processing failed: {type(exc).__name__}.",
            calls=tuple(calls),
        )
