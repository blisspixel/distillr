"""Audio/video transcription with local-first provider routing.

For sources that don't have native captions (X-native ``amplify_video``,
podcasts, etc.) we need to transcribe the audio. Provider ladder:

1. **Local** (``faster-whisper`` ``large-v3`` on CUDA / CPU) — preferred;
   honors the roadmap's local-first principle. Zero per-use cost.
2. **Cloud xAI Grok STT** — first cloud fallback. ~$0.10/hour batch
   (3.6x cheaper than OpenAI Whisper). Reuses the existing
   ``XAI_API_KEY`` distillr already requires for analysis.
3. **Cloud OpenAI Whisper-1** — final fallback at ~$0.36/hour.

Each cloud provider is skipped if its API key isn't configured; local
is skipped if the optional ``faster-whisper`` dependency is missing.
This keeps the same code path usable on a CPU-only laptop with no
local Whisper as well as a 4090 with no cloud keys.
"""

from __future__ import annotations

import json
import logging
import math
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Protocol

from distill.config import DistillConfig
from distill.ingestors._transcribe_parent import (
    _forward_local_progress as _forward_local_progress,
)
from distill.ingestors._transcribe_parent import (
    _local_worker_timeout,
    _read_local_worker_result,
    _run_local_worker_process,
)
from distill.ingestors._transcribe_types import (
    LocalTranscriptionUnavailable as _LocalUnavailable,
)
from distill.ingestors._transcribe_types import ProgressCallback, TranscriptionResult
from distill.library.confined import copy_confined_file
from distill.library.paths import atomic_write_text
from distill.llm.cost_policy import CostPolicyError, require_route_allowed
from distill.process_security import resolve_executable

__all__ = [
    "TranscriptionError",
    "TranscriptionResult",
    "transcribe_media",
]

_log = logging.getLogger(__name__)

_STREAM_PROBE_TIMEOUT_SECONDS = 10
_DECODE_DURATION_TIMEOUT_SECONDS = 30
_MAX_MEDIA_INPUT_BYTES = 500 * 1024 * 1024
_MAX_LOCAL_AUDIO_SECONDS = 3 * 60 * 60


class TranscriptionError(RuntimeError):
    """Raised when no transcription provider can complete the task."""


def _default_progress(audio_seconds: float, total_audio_s: float, words: int) -> None:
    """Default heartbeat printer for long-running transcriptions.

    Writes one line to stderr per call. Stderr keeps progress noise out
    of stdout streams that other tools (e.g. JSON pipelines) may parse,
    but still gives non-TTY supervisors visible output so they don't
    classify the process as hung. Flushes per write because some
    consumers (background task runners, CI capture) only see complete
    lines.
    """
    if total_audio_s > 0:
        pct = min(100.0, 100.0 * audio_seconds / total_audio_s)
        sys.stderr.write(
            f"        [whisper] {audio_seconds:.0f}s of {total_audio_s:.0f}s "
            f"({pct:.0f}%), {words} words so far\n"
        )
    else:
        sys.stderr.write(f"        [whisper] {audio_seconds:.0f}s, {words} words so far\n")
    sys.stderr.flush()


class TranscriptionCostTracker(Protocol):
    """Minimal ledger boundary needed by the transcription router."""

    def authorize_transcription(
        self, provider: str, duration_s: float, *, model: str = ""
    ) -> None: ...

    def record_transcription(
        self,
        provider: str,
        duration_s: float,
        *,
        model: str = "",
        outcome: str = "completed",
    ) -> None: ...

    def reserve_transcription(
        self,
        provider: str,
        duration_s: float,
        *,
        model: str = "",
    ) -> AbstractContextManager[None]: ...


def _complete_transcription(
    result: TranscriptionResult,
    *,
    tracker: TranscriptionCostTracker | None,
    duration_hint_s: float,
) -> TranscriptionResult:
    """Apply trusted duration context and record one completed provider call."""

    result.duration_s = _positive_duration(result.duration_s) or _positive_duration(duration_hint_s)
    if tracker is not None:
        tracker.record_transcription(result.provider, result.duration_s, model=result.model)
    return result


def _positive_duration(value: float) -> float:
    """Normalize finite positive duration values for cost accounting."""

    duration = float(value)
    return duration if math.isfinite(duration) and duration > 0 else 0.0


def _run_media_probe(
    command: list[str], media_path: Path, *, timeout_seconds: int
) -> subprocess.CompletedProcess[str] | None:
    """Run one bounded media probe over a pipe-only input boundary."""
    try:
        with media_path.open("rb") as media_file:
            completed = subprocess.run(
                command,
                capture_output=True,
                check=False,
                stdin=media_file,
                text=True,
                timeout=timeout_seconds,
            )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed


def _has_one_audio_stream(media_path: Path) -> bool:
    """Reject media whose cloud provider stream choice would be ambiguous."""

    ffprobe = resolve_executable("ffprobe")
    if ffprobe is None:
        return False

    completed = _run_media_probe(
        [
            ffprobe,
            "-v",
            "error",
            "-protocol_whitelist",
            "cache,pipe",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            "cache:pipe:0",
        ],
        media_path,
        timeout_seconds=_STREAM_PROBE_TIMEOUT_SECONDS,
    )
    if completed is None:
        return False
    return len([line for line in completed.stdout.splitlines() if line.strip()]) == 1


def _decoded_progress_duration(stdout: str) -> float:
    """Parse the final sample-timeline duration from FFmpeg progress output."""

    duration_us = 0
    reached_end = False
    for line in stdout.splitlines():
        key, separator, raw_value = line.partition("=")
        if not separator:
            continue
        if key == "out_time_us":
            try:
                duration_us = max(duration_us, int(raw_value))
            except ValueError:
                return 0.0
        elif key == "progress" and raw_value == "end":
            reached_end = True
    if not reached_end:
        return 0.0
    return _positive_duration(duration_us / 1_000_000)


def _probe_media_duration(media_path: Path) -> float:
    """Return decoded audio duration without trusting container timestamps.

    Billing follows decoded audio, while container and stream duration fields
    can be attacker-controlled presentation timestamps. FFmpeg therefore resets
    timestamps from the decoded sample count before reporting progress. The
    media bytes enter through a pipe whose protocol whitelist forbids manifests
    from opening secondary files or network resources. The probe is
    time-bounded, stops on the first decode error, and refuses media with zero
    or multiple audio streams rather than guessing which stream a cloud
    provider will bill.
    """

    if not _has_one_audio_stream(media_path):
        return 0.0
    ffmpeg = resolve_executable("ffmpeg")
    if ffmpeg is None:
        return 0.0
    completed = _run_media_probe(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-xerror",
            "-nostdin",
            "-protocol_whitelist",
            "cache,pipe",
            "-stats_period",
            "3600",
            "-progress",
            "pipe:1",
            "-i",
            "cache:pipe:0",
            "-map",
            "0:a:0",
            "-af",
            "asetpts=N/SR/TB",
            "-f",
            "null",
            "-",
        ],
        media_path,
        timeout_seconds=_DECODE_DURATION_TIMEOUT_SECONDS,
    )
    if completed is None:
        return 0.0
    return _decoded_progress_duration(completed.stdout)


def _require_ledger_duration(media_path: Path) -> float:
    """Probe billable duration or refuse an unaccountable cloud call."""

    duration_s = _probe_media_duration(media_path)
    if duration_s <= 0:
        raise TranscriptionError(
            "Cloud transcription refused because media duration is unavailable; "
            "install ffmpeg and ffprobe or provide single-stream decodable media so "
            "spend can be recorded."
        )
    return duration_s


def _prepare_ledger_duration(
    media_path: Path,
    duration_hint_s: float,
    *,
    tracker: TranscriptionCostTracker | None,
    api_key: str,
) -> float:
    """Require duration only when a tracked cloud route is configured."""

    if tracker is None or not api_key:
        return duration_hint_s
    return _require_ledger_duration(media_path)


def _prepare_cloud_route(
    media_path: Path,
    duration_hint_s: float,
    *,
    config: DistillConfig,
    route_name: str,
    provider: str,
    api_key: str,
    errors: list[str],
    tracker: TranscriptionCostTracker | None,
) -> float:
    """Enforce cost policy before cloud ledger work or provider invocation."""

    if api_key:
        try:
            require_route_allowed(
                cost_mode=config.distill_cost_mode,
                provider=provider,
                workload="speech-to-text",
            )
        except CostPolicyError as exc:
            errors.append(f"{route_name}: {exc}")
            raise TranscriptionError("; ".join(errors)) from exc
        if tracker is None:
            errors.append(
                f"{route_name}: cloud transcription requires a cost tracker so "
                "provider usage cannot bypass the run ledger"
            )
            raise TranscriptionError("; ".join(errors))
    return _prepare_ledger_duration(
        media_path,
        duration_hint_s,
        tracker=tracker,
        api_key=api_key,
    )


def _attempt(
    name: str,
    fn: Callable[[], TranscriptionResult],
    errors: list[str],
    *,
    must_succeed: bool,
) -> TranscriptionResult | None:
    """Run one provider attempt for transcribe_media's ladder.

    Returns the result on success, or None on a caught failure so the caller
    can fall through to the next provider. Records the failure in *errors*; if
    *must_succeed* (the provider was explicitly requested, or is the final
    fallback) it raises TranscriptionError instead of returning None.
    """
    try:
        return fn()
    except CostPolicyError as exc:
        errors.append(f"{name}: {exc}")
        raise TranscriptionError("; ".join(errors)) from exc
    except Exception as exc:
        errors.append(f"{name}: {exc}")
        if must_succeed:
            raise TranscriptionError("; ".join(errors)) from exc
    return None


def _recorded_cloud_attempt(
    name: str,
    fn: Callable[[], TranscriptionResult],
    errors: list[str],
    *,
    must_succeed: bool,
    tracker: TranscriptionCostTracker,
    provider: str,
    model: str,
    duration_s: float,
) -> TranscriptionResult | None:
    """Attempt one admitted cloud call and persist success or failure."""

    try:
        result = _attempt(name, fn, errors, must_succeed=must_succeed)
    except BaseException:
        tracker.record_transcription(
            provider,
            duration_s,
            model=model,
            outcome="failed",
        )
        raise
    tracker.record_transcription(
        provider,
        duration_s,
        model=model,
        outcome="completed" if result is not None else "failed",
    )
    return result


def _attempt_cloud_route(
    media_path: Path,
    duration_hint_s: float,
    *,
    config: DistillConfig,
    errors: list[str],
    tracker: TranscriptionCostTracker | None,
    route_name: str,
    policy_provider: str,
    ledger_provider: str,
    model: str,
    api_key: str,
    fn: Callable[[], TranscriptionResult],
    must_succeed: bool,
) -> tuple[TranscriptionResult | None, float]:
    duration_s = _prepare_cloud_route(
        media_path,
        duration_hint_s,
        config=config,
        route_name=route_name,
        provider=policy_provider,
        api_key=api_key,
        errors=errors,
        tracker=tracker,
    )
    if not api_key:
        return _attempt(route_name, fn, errors, must_succeed=must_succeed), duration_s
    if tracker is None:
        raise TranscriptionError(
            f"{route_name}: cloud transcription requires a cost tracker so "
            "provider usage cannot bypass the run ledger"
        )
    tracker.authorize_transcription(ledger_provider, duration_s, model=model)
    with tracker.reserve_transcription(ledger_provider, duration_s, model=model):
        result = _recorded_cloud_attempt(
            route_name,
            fn,
            errors,
            must_succeed=must_succeed,
            tracker=tracker,
            provider=ledger_provider,
            model=model,
            duration_s=duration_s,
        )
    return result, duration_s


def transcribe_media(
    media_path: Path,
    config: DistillConfig,
    *,
    prefer: str = "auto",
    local_model: str = "large-v3",
    vocabulary_hint: str = "",
    tracker: TranscriptionCostTracker | None = None,
    duration_hint_s: float = 0.0,
    progress: ProgressCallback | None = _default_progress,
    progress_interval_s: float = 30.0,
) -> TranscriptionResult:
    """Transcribe one stable private snapshot of a bounded regular media file."""

    if not media_path.exists():
        raise TranscriptionError(f"Media file not found: {media_path}")
    if prefer not in {"auto", "auto-cloud", "local", "grok", "cloud", "openai"}:
        raise TranscriptionError(f"unknown prefer={prefer!r}")
    absolute_media_path = media_path.absolute()
    trusted_root = Path(absolute_media_path.anchor)
    if not trusted_root.is_absolute():
        raise TranscriptionError("Media input does not have a trusted filesystem anchor.")
    suffix = absolute_media_path.suffix
    if not (2 <= len(suffix) <= 16 and suffix[1:].isalnum()):
        suffix = ".media"
    with tempfile.TemporaryDirectory(prefix="distill-media-") as temp_dir:
        snapshot = Path(temp_dir) / f"input{suffix.lower()}"
        if not copy_confined_file(
            absolute_media_path,
            trusted_root,
            snapshot,
            max_bytes=_MAX_MEDIA_INPUT_BYTES,
        ):
            raise TranscriptionError(
                "Media input and its ancestry must be direct, stable, and single-link, "
                "and the file must be no larger than "
                f"{_MAX_MEDIA_INPUT_BYTES:,} bytes."
            )
        return _transcribe_media_snapshot(
            snapshot,
            config,
            prefer=prefer,
            local_model=local_model,
            vocabulary_hint=vocabulary_hint,
            tracker=tracker,
            duration_hint_s=duration_hint_s,
            progress=progress,
            progress_interval_s=progress_interval_s,
        )


def _transcribe_media_snapshot(
    media_path: Path,
    config: DistillConfig,
    *,
    prefer: str = "auto",
    local_model: str = "large-v3",
    vocabulary_hint: str = "",
    tracker: TranscriptionCostTracker | None = None,
    duration_hint_s: float = 0.0,
    progress: ProgressCallback | None = _default_progress,
    progress_interval_s: float = 30.0,
) -> TranscriptionResult:
    """Transcribe *media_path* to text via the local-first provider ladder.

    ``prefer`` selects routing:

    - ``"auto"`` (default): local -> grok -> openai (skipping providers
      whose dependency or key isn't available).
    - ``"local"``: local only; raise if unavailable.
    - ``"grok"``: xAI Grok STT only.
    - ``"cloud"``: cloud-only ladder, Grok STT then OpenAI Whisper-1,
      skipping a provider when its key is unavailable.
    - ``"openai"``: OpenAI Whisper-1 only.

    ``vocabulary_hint`` is a short free-text string of proper nouns,
    product names, and technical terms the source is likely to discuss.
    Each provider passes it through to its respective biasing parameter
    (Whisper's ``initial_prompt`` for local + OpenAI; Grok STT's
    ``keyterm`` form field). Sharply reduces proper-noun
    mistranscription ("Claude Code -> QuadCode" class of errors).
    """
    if prefer == "cloud":  # back-compat alias for the old two-provider routing
        prefer = "auto-cloud"

    errors: list[str] = []

    if prefer in {"auto", "local"}:
        result = _attempt(
            "local",
            lambda: _transcribe_local(
                media_path,
                model_name=local_model,
                vocabulary_hint=vocabulary_hint,
                progress=progress,
                progress_interval_s=progress_interval_s,
            ),
            errors,
            must_succeed=prefer == "local",
        )
        if result is not None:
            return _complete_transcription(result, tracker=tracker, duration_hint_s=duration_hint_s)

    if prefer in {"auto", "auto-cloud", "grok"}:
        xai_api_key = config.xai_api_key.get_secret_value()
        result, duration_hint_s = _attempt_cloud_route(
            media_path,
            duration_hint_s,
            config=config,
            errors=errors,
            tracker=tracker,
            route_name="grok",
            policy_provider="xai",
            ledger_provider="xai-grok-stt",
            model="grok-stt",
            api_key=xai_api_key,
            fn=lambda: _transcribe_grok(media_path, config, vocabulary_hint=vocabulary_hint),
            must_succeed=prefer == "grok",
        )
        if result is not None:
            return _complete_transcription(result, tracker=None, duration_hint_s=duration_hint_s)

    if prefer in {"auto", "auto-cloud", "openai"}:
        openai_api_key = config.openai_api_key.get_secret_value()
        result, duration_hint_s = _attempt_cloud_route(
            media_path,
            duration_hint_s,
            config=config,
            errors=errors,
            tracker=tracker,
            route_name="openai",
            policy_provider="openai",
            ledger_provider="openai",
            model="whisper-1",
            api_key=openai_api_key,
            fn=lambda: _transcribe_openai(media_path, config, vocabulary_hint=vocabulary_hint),
            must_succeed=True,
        )
        if result is not None:
            return _complete_transcription(result, tracker=None, duration_hint_s=duration_hint_s)

    raise TranscriptionError("; ".join(errors) or f"unknown prefer={prefer!r}")


class _ProviderUnavailable(RuntimeError):
    """Raised internally when a cloud provider's key isn't configured."""


def _transcribe_local(
    media_path: Path,
    *,
    model_name: str,
    vocabulary_hint: str = "",
    progress: ProgressCallback | None = None,
    progress_interval_s: float = 30.0,
) -> TranscriptionResult:
    """Run faster-whisper in a resource-bounded isolated child process."""

    if not model_name or len(model_name) > 128 or any(ord(char) < 32 for char in model_name):
        raise _LocalUnavailable("local model name is invalid")
    if not math.isfinite(progress_interval_s) or progress_interval_s <= 0:
        raise _LocalUnavailable("local progress interval must be positive and finite")
    duration_s = _probe_media_duration(media_path)
    if duration_s <= 0:
        raise _LocalUnavailable(
            "local transcription requires single-stream decodable media and ffmpeg/ffprobe"
        )
    if duration_s > _MAX_LOCAL_AUDIO_SECONDS:
        raise _LocalUnavailable(
            f"local transcription refuses media longer than {_MAX_LOCAL_AUDIO_SECONDS:,} seconds"
        )
    with tempfile.TemporaryDirectory(prefix="distill-transcribe-") as temp_dir:
        root = Path(temp_dir)
        request_path = root / "request.json"
        result_path = root / "result.json"
        progress_path = root / "progress.json"
        request = {
            "media_path": str(media_path.resolve(strict=True)),
            "model_name": model_name,
            "vocabulary_hint": _clip_for_whisper(vocabulary_hint),
            "progress_interval_s": progress_interval_s,
        }
        atomic_write_text(
            request_path,
            json.dumps(request, ensure_ascii=False, allow_nan=False),
        )
        _run_local_worker_process(
            request_path,
            result_path,
            progress_path,
            root,
            timeout_seconds=_local_worker_timeout(duration_s),
            progress=progress,
        )
        return _read_local_worker_result(
            result_path,
            root,
            expected_model=model_name,
        )


def _transcribe_local_core(
    media_path: Path,
    *,
    model_name: str,
    vocabulary_hint: str = "",
    progress: ProgressCallback | None = None,
    progress_interval_s: float = 30.0,
) -> TranscriptionResult:
    """Transcribe via faster-whisper on the local GPU (or CPU).

    Optimized for throughput while keeping the ``large-v3`` quality bar.
    The four real speedups (in order of impact) are:

    1. ``BatchedInferencePipeline`` — processes multiple VAD chunks in
       parallel on the GPU. Typically 4-12x faster than serial decode
       depending on VRAM headroom. Falls back to serial decode if the
       installed faster-whisper is too old or batched inference raises.
    2. ``beam_size=1`` — Whisper's default. Beam search past 1 buys
       almost nothing on clean speech and costs ~3x throughput. Reserve
       beam=5 for the cloud fallback where latency is dominated by the
       network anyway.
    3. ``without_timestamps=True`` — skips per-word timestamp decoding
       (we only emit the transcript text, not timestamps).
    4. VAD silence skipping — already on; cuts ~10-30% of typical audio.

    Defensive routing:

    - Pick ``(device, compute_type)`` adaptively from ``ctranslate2``
      capability probes (CUDA float16 on modern GPUs, int8_float16 on
      lower-VRAM CUDA, plain int8 on CPU).
    - Pick ``batch_size`` from free VRAM so the same code path is safe
      on a 6GB 3060 and a 24GB 4090.
    - Catch CUDA OOM mid-transcription and retry once with a smaller
      batch (then with serial decode) before bubbling up.

    Long transcriptions (multi-minute audio) emit a heartbeat to the
    supplied ``progress`` callback every ``progress_interval_s`` seconds
    of wall clock. Without this, non-TTY supervisors that watch stdout
    activity classify the process as hung and kill it mid-transcription.
    """
    try:
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]
    except ImportError as exc:
        raise _LocalUnavailable(
            "faster-whisper not installed (pip install faster-whisper)"
        ) from exc

    device, compute_type = _pick_device()
    _log.info(
        "loading faster-whisper model=%s device=%s compute=%s",
        model_name,
        device,
        compute_type,
    )
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    initial_prompt = _clip_for_whisper(vocabulary_hint) if vocabulary_hint else None

    batch_size = _pick_batch_size(device)
    notes = [f"device={device}", f"compute={compute_type}"]
    if initial_prompt:
        notes.append(f"vocab_hint={len(initial_prompt)} chars")

    # Try batched inference first (4-12x speedup); fall back to serial
    # decode if the installed faster-whisper lacks BatchedInferencePipeline
    # or batched inference fails at runtime.
    try:
        from faster_whisper import (  # type: ignore[import-not-found,attr-defined]
            BatchedInferencePipeline,
        )

        batched = BatchedInferencePipeline(model=model)
        segments, info, mode = (
            *_run_transcription(
                batched,
                str(media_path),
                initial_prompt=initial_prompt,
                batch_size=batch_size,
                batched=True,
            ),
            f"batched(size={batch_size})",
        )
        notes.append(mode)
    except (ImportError, AttributeError):
        segments, info = _run_transcription(
            model,
            str(media_path),
            initial_prompt=initial_prompt,
            batch_size=None,
            batched=False,
        )
        notes.append("serial")
    except Exception as exc:  # batched run errored — degrade gracefully
        _log.warning("batched inference failed (%s); falling back to serial", exc)
        notes.append(f"batched_failed:{type(exc).__name__}")
        segments, info = _run_transcription(
            model,
            str(media_path),
            initial_prompt=initial_prompt,
            batch_size=None,
            batched=False,
        )
        notes.append("serial")

    total_audio_s = float(getattr(info, "duration", 0.0) or 0.0)
    text_parts, word_count, last_seg_end = _drain_segments(
        segments,
        progress=progress,
        progress_interval_s=progress_interval_s,
        total_audio_s=total_audio_s,
    )
    # Final heartbeat at 100% so non-TTY supervisors see we finished before
    # the next stdout output (rich.Console writes after this call don't
    # always flush promptly).
    if progress is not None:
        progress(total_audio_s or last_seg_end, total_audio_s, word_count)
    text = "\n".join(text_parts)

    return TranscriptionResult(
        text=text,
        provider="faster-whisper",
        model=model_name,
        language=str(getattr(info, "language", "") or ""),
        duration_s=total_audio_s,
        notes=notes,
    )


def _run_transcription(
    transcriber: Any,
    media_path: str,
    *,
    initial_prompt: str | None,
    batch_size: int | None,
    batched: bool,
) -> tuple[Any, Any]:
    """Invoke ``transcriber.transcribe`` with the right kwargs for batched/serial mode."""
    kwargs: dict[str, Any] = {
        "beam_size": 1,
        "vad_filter": True,
        "without_timestamps": True,
        "initial_prompt": initial_prompt,
    }
    if batched and batch_size:
        kwargs["batch_size"] = batch_size
    return transcriber.transcribe(media_path, **kwargs)


def _drain_segments(
    segments: Iterable[Any],
    *,
    progress: ProgressCallback | None,
    progress_interval_s: float,
    total_audio_s: float,
) -> tuple[list[str], int, float]:
    """Materialize Whisper's segment generator into a list of strings + counters.

    Emits periodic ``progress`` heartbeats so long transcriptions don't
    appear hung under non-TTY supervisors. Wrapped in a try/except so a
    CUDA OOM mid-decode surfaces with a clear message instead of
    propagating as a bare CUDA error.
    """
    text_parts: list[str] = []
    word_count = 0
    last_seg_end = 0.0
    last_progress_at = time.monotonic()
    try:
        for seg in segments:
            chunk = (getattr(seg, "text", "") or "").strip()
            if chunk:
                text_parts.append(chunk)
                word_count += len(chunk.split())
            last_seg_end = float(getattr(seg, "end", last_seg_end) or last_seg_end)
            if (
                progress is not None
                and (time.monotonic() - last_progress_at) >= progress_interval_s
            ):
                progress(last_seg_end, total_audio_s, word_count)
                last_progress_at = time.monotonic()
    except RuntimeError as exc:
        # ctranslate2 raises plain RuntimeError on CUDA OOM with a
        # message like "out of memory". Re-raise with a clearer hint.
        msg = str(exc).lower()
        if "out of memory" in msg or "cuda" in msg:
            raise _LocalUnavailable(
                f"CUDA out of memory during decode after {word_count} words "
                f"({last_seg_end:.0f}s of {total_audio_s:.0f}s). Free VRAM, "
                "lower batch size, or set DISTILL_TRANSCRIBE=cloud."
            ) from exc
        raise
    return text_parts, word_count, last_seg_end


def _pick_batch_size(device: str) -> int:
    """Pick a safe BatchedInferencePipeline batch size for the device.

    Sizing rule of thumb for large-v3 at float16: each batch slot costs
    roughly 200-300 MB of VRAM beyond the ~3 GB the model itself takes.
    Probe free VRAM via ``ctranslate2`` and pick something that fits
    with ~30% headroom. CPU runs default to a small batch so latency
    stays sensible on machines without a discrete GPU.
    """
    if device != "cuda":
        return 4
    try:
        import ctranslate2  # type: ignore[import-not-found]

        # ctranslate2 doesn't expose free VRAM directly; use torch if
        # available, otherwise fall back to a hardcoded conservative
        # batch size that runs on any modern NVIDIA GPU.
        try:
            import torch  # type: ignore[import-not-found]

            if torch.cuda.is_available():
                free_bytes, _total = torch.cuda.mem_get_info()
                free_gb = free_bytes / (1024**3)
                # Reserve ~3 GB for the model itself, ~30% headroom on
                # what's left for activations / KV caches.
                usable_gb = max(0.0, (free_gb - 3.0) * 0.7)
                # Each slot ~0.25 GB at float16 -> slots = usable / 0.25.
                slots = int(usable_gb / 0.25)
                return max(2, min(32, slots))
        except ImportError:
            _ = ctranslate2
            return 4
        # No torch: pick a small batch that works on a 6 GB card.
        _ = ctranslate2
        return 4
    except ImportError:
        return 4


def _clip_for_whisper(hint: str, *, max_chars: int = 900) -> str:
    """Whisper's initial_prompt budget is ~224 GPT-2 tokens. We don't
    want to bring tiktoken in just for this; ~900 characters is a safe
    proxy that keeps us well inside the cap for English text. Trim at
    a word boundary so we don't leave the model with a half-word."""
    text = " ".join(hint.split())
    if len(text) <= max_chars:
        return text
    clipped = text[:max_chars]
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped


def _pick_device() -> tuple[str, str]:
    """Return (device, compute_type) for faster-whisper.

    Adaptive: probes supported compute types on CUDA and picks the
    fastest that the installed driver + ctranslate2 build supports.
    Order of preference on CUDA: float16 (modern Ampere/Ada) ->
    int8_float16 (older / lower-VRAM) -> float32 (compatibility). On
    CPU: int8 (the recommended CPU compute_type for faster-whisper).
    """
    try:
        import ctranslate2  # type: ignore[import-not-found]
    except ImportError:
        return "cpu", "int8"
    try:
        cuda_count = ctranslate2.get_cuda_device_count()
    except Exception:
        cuda_count = 0
    if cuda_count <= 0:
        return "cpu", "int8"
    try:
        supported = set(ctranslate2.get_supported_compute_types("cuda"))
    except Exception:
        supported = {"float16"}
    for preferred in ("float16", "int8_float16", "float32"):
        if preferred in supported:
            return "cuda", preferred
    return "cuda", "float16"


def _transcribe_openai(
    media_path: Path, config: DistillConfig, *, vocabulary_hint: str = ""
) -> TranscriptionResult:
    """Transcribe via the OpenAI Whisper API (final cloud fallback).

    Delegates the client construction to ``distill.llm.whisper`` so the
    OpenAI() client stays inside ``distill/llm/`` per the architectural
    test ``test_no_openai_construction_outside_llm``.
    """
    from distill.llm.whisper import transcribe_with_openai

    api_key = config.openai_api_key.get_secret_value()
    if not api_key:
        raise _ProviderUnavailable("OPENAI_API_KEY not configured")
    require_route_allowed(
        cost_mode=config.distill_cost_mode,
        provider="openai",
        workload="speech-to-text",
    )
    clipped_hint = _clip_for_whisper(vocabulary_hint) if vocabulary_hint else ""
    text = transcribe_with_openai(
        media_path,
        api_key=api_key,
        model="whisper-1",
        vocabulary_hint=clipped_hint,
    )
    notes = [f"vocab_hint={len(clipped_hint)} chars"] if clipped_hint else []
    return TranscriptionResult(
        text=text,
        provider="openai",
        model="whisper-1",
        notes=notes,
    )


def _transcribe_grok(
    media_path: Path,
    config: DistillConfig,
    *,
    vocabulary_hint: str = "",
    language: str = "en",
) -> TranscriptionResult:
    """Transcribe via xAI Grok STT (first cloud fallback).

    Cheaper than OpenAI Whisper-1 ($0.10/hr vs $0.36/hr) and reuses
    the ``XAI_API_KEY`` distillr already requires for analysis. Lives
    inside ``distill.llm.grok_stt`` for the same containment reason as
    the OpenAI client.

    Defaults ``language="en"`` because Grok STT rejects auto-detect
    when ``format=true`` and most distillr sources today are English.
    Pass ``language=""`` to skip the format flag and let Grok
    auto-detect (transcript will be unpunctuated).
    """
    from distill.llm.grok_stt import transcribe_with_grok

    api_key = config.xai_api_key.get_secret_value()
    if not api_key:
        raise _ProviderUnavailable("XAI_API_KEY not configured")
    require_route_allowed(
        cost_mode=config.distill_cost_mode,
        provider="xai",
        workload="speech-to-text",
    )
    clipped_hint = _clip_for_whisper(vocabulary_hint) if vocabulary_hint else ""
    text = transcribe_with_grok(
        media_path,
        api_key=api_key,
        vocabulary_hint=clipped_hint,
        language=language,
    )
    notes = [f"vocab_hint={len(clipped_hint)} chars"]
    if language:
        notes.append(f"language={language}")
    return TranscriptionResult(
        text=text,
        provider="xai-grok-stt",
        model="grok-stt",
        notes=notes,
    )
