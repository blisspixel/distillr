"""Transcript acquisition — YouTube captions first, Whisper ladder, then scribe.

The resilience order (0.12.11, the 0.11 YouTube-resilience margin):

1. **YouTube captions** via yt-dlp — free, instant. Transient failures
   (network, throttling, the PO-token/SABR churn) are retried with backoff;
   a clean download that simply lands no subtitle file means the video is
   captionless, which is permanent and not retried.
2. **Local-first Whisper ladder** — download bestaudio and run the same
   ``transcribe_media`` routing every other audio source uses
   (faster-whisper local -> Grok STT -> OpenAI Whisper), with a vocabulary
   hint built from the video's own title and uploader. Free on a CUDA box.
3. **Scribe** — the legacy external fallback, kept as a last resort for
   installs that configured it.
"""

import contextlib
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from rich.markup import escape

from distill._console import console
from distill.config import DistillConfig
from distill.ingestors.youtube._yt_dlp_boundary import (
    first_text,
    info_mapping,
    int_field,
)
from distill.library.confined import list_confined_files, read_confined_text
from distill.library.locking import exclusive_file_lock, open_lock_file
from distill.library.paths import atomic_write_text
from distill.process_resources import (
    ProcessBudgetExceeded,
    assign_windows_memory_job,
    close_windows_job,
    start_bounded_pipe_drain,
    terminate_isolated_process_tree,
    wait_for_process_budget,
)
from distill.process_security import sanitized_package_env
from distill.youtube_urls import (
    normalize_video_id,
    normalize_youtube_video_url,
    youtube_video_id_from_url,
)

if TYPE_CHECKING:
    from distill.ingestors.youtube.safe_ytdlp import (
        YTDLP_METADATA_RESPONSE_BYTES,
        YTDLP_METADATA_TOTAL_BYTES,
        SafeYoutubeDL,
    )

__all__ = [
    "MAX_TRANSCRIPT_BYTES",
    "get_transcript",
]

_SAFE_YTDLP_NAMES = (
    "SafeYoutubeDL",
    "YTDLP_METADATA_RESPONSE_BYTES",
    "YTDLP_METADATA_TOTAL_BYTES",
)


def _bind_safe_ytdlp() -> None:
    """Bind the yt-dlp-backed transport on first use, not at module import.

    Importing yt-dlp costs a noticeable slice of CLI startup, so this module
    stays cheap to import and pays for the transport only when a transcript
    fetch actually runs. Tests that patch ``SafeYoutubeDL`` on this module
    keep working: an existing module attribute is never overwritten.
    """
    global SafeYoutubeDL, YTDLP_METADATA_RESPONSE_BYTES, YTDLP_METADATA_TOTAL_BYTES
    if "SafeYoutubeDL" in globals():
        return
    from distill.ingestors.youtube import safe_ytdlp

    SafeYoutubeDL = safe_ytdlp.SafeYoutubeDL
    YTDLP_METADATA_RESPONSE_BYTES = safe_ytdlp.YTDLP_METADATA_RESPONSE_BYTES
    YTDLP_METADATA_TOTAL_BYTES = safe_ytdlp.YTDLP_METADATA_TOTAL_BYTES


def __getattr__(name: str) -> object:
    """Resolve lazily bound transport names on first module-attribute access."""
    if name in _SAFE_YTDLP_NAMES:
        _bind_safe_ytdlp()
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


_SCRIBE_LOCK_TIMEOUT_SECONDS = 610.0


@contextlib.contextmanager
def _scribe_output_lock(scribe_path: Path) -> Generator[None]:
    """Serialize access to Scribe's shared output directory across processes."""

    lock_path = scribe_path / ".distill-scribe.lock"
    with (
        open_lock_file(lock_path) as lock_file,
        exclusive_file_lock(
            lock_file,
            timeout_seconds=_SCRIBE_LOCK_TIMEOUT_SECONDS,
            timeout_message="timed out waiting for the Scribe output lock",
        ),
    ):
        yield


# Backoff schedule for transient caption-fetch failures. Two retries keeps a
# 20-video sweep from stalling minutes on a dead video while still riding out
# one-off throttles. Module-level so tests can shrink it.
_RETRY_DELAYS: tuple[float, ...] = (1.0, 3.0)
_sleep = time.sleep

# Audio-download ceiling for the Whisper fallback: ~3h of 128kbps m4a. A
# longer video almost certainly has captions; this caps disk and ladder time.
_MAX_AUDIO_BYTES = 200_000_000
MAX_TRANSCRIPT_BYTES = 20_000_000
_MAX_CAPTION_BYTES = MAX_TRANSCRIPT_BYTES
_SCRIBE_DIAGNOSTIC_BYTES = 32 * 1024
_SCRIBE_MEMORY_BYTES = 8 * 1024 * 1024 * 1024
_SCRIBE_TIMEOUT_SECONDS = 600.0
_SCRIBE_MAX_OUTPUT_ENTRIES = 32


class _DownloadSizeExceeded(RuntimeError):
    """A yt-dlp transfer crossed its deterministic byte ceiling."""


def _enforce_download_size(status: object, *, byte_limit: int, label: str) -> None:
    row = info_mapping(status)
    if row is None:
        return
    observed = 0
    for field_name in ("downloaded_bytes", "total_bytes", "total_bytes_estimate"):
        if row.get(field_name) is None:
            continue
        value = int_field(row, field_name, -1)
        if value < 0:
            raise _DownloadSizeExceeded(f"{label} download reported an invalid byte count")
        observed = max(observed, value)
    if observed > byte_limit:
        raise _DownloadSizeExceeded(f"{label} download exceeds the {byte_limit:,}-byte cap")


def _caption_download_progress(status: object) -> None:
    _enforce_download_size(status, byte_limit=_MAX_CAPTION_BYTES, label="caption")


def _audio_download_progress(status: object) -> None:
    _enforce_download_size(status, byte_limit=_MAX_AUDIO_BYTES, label="audio")


class _TranscriptionCostTracker(Protocol):
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


def get_transcript(
    video_url: str,
    video_id: str,
    output_path: Path,
    config: DistillConfig,
    tracker: _TranscriptionCostTracker | None = None,
) -> bool:
    """Get transcript for a video. Returns True if successful.

    ``tracker`` (a ``CostTracker``, optional) records cloud STT spend when the
    Whisper fallback routes to a paid tier; local transcription records $0.
    """
    canonical_url = normalize_youtube_video_url(video_url)
    canonical_id = youtube_video_id_from_url(video_url)
    if not canonical_url or normalize_video_id(video_id) != canonical_id:
        console.print(f"    [red]Refusing non-YouTube URL: {video_url}[/red]")
        return False

    transcript = _try_youtube_captions(canonical_url, canonical_id)
    if transcript:
        atomic_write_text(output_path, transcript)
        return True

    console.print("    [yellow]No captions; transcribing audio (local-first ladder)...[/yellow]")
    if _try_whisper_ladder(canonical_url, canonical_id, output_path, config, tracker=tracker):
        return True

    if config.scribe_path:
        console.print("    [yellow]Whisper ladder unavailable, falling back to scribe...[/yellow]")
        return _try_scribe(canonical_url, output_path, config)
    return False


def _try_youtube_captions(video_url: str, video_id: str) -> str | None:
    """Try YouTube auto-captions via yt-dlp, retrying transient failures.

    The transient/permanent split is structural: an exception from yt-dlp
    (network, HTTP 429/5xx, extractor churn) is worth retrying; a download
    that completes but leaves no ``.vtt`` behind means the video has no
    English captions, which a retry cannot change.
    """
    for attempt, delay in enumerate((*_RETRY_DELAYS, None)):
        result = _fetch_captions_once(video_url, video_id)
        if result is not None:
            return result or None  # "" -> no captions (permanent), None below
        if delay is None:
            break
        console.print(
            f"    [dim]caption fetch failed (attempt {attempt + 1}); "
            f"retrying in {delay:.0f}s...[/dim]"
        )
        _sleep(delay)
    return None


def _fetch_captions_once(video_url: str, video_id: str) -> str | None:
    """One caption attempt: text on success, ``""`` if captionless, ``None`` on error."""
    _bind_safe_ytdlp()
    with tempfile.TemporaryDirectory() as tmpdir:
        output_template = str(Path(tmpdir) / video_id)

        ydl_opts: dict[str, object] = {
            "writeautomaticsub": True,
            "writesubtitles": True,
            "subtitleslangs": ["en"],
            "subtitlesformat": "vtt",
            "skip_download": True,
            "outtmpl": output_template,
            "quiet": True,
            "noprogress": True,
            "no_warnings": True,
            "retries": 2,
            "socket_timeout": 30,
            "progress_hooks": [_caption_download_progress],
        }

        try:
            with SafeYoutubeDL(
                ydl_opts,
                metadata_byte_limit=_MAX_CAPTION_BYTES,
                total_byte_limit=YTDLP_METADATA_TOTAL_BYTES,
            ) as ydl:
                ydl.download([video_url])
        except Exception:
            return None

        sub_file = None
        for f in Path(tmpdir).iterdir():
            if f.suffix == ".vtt" and "en" in f.name:
                sub_file = f
                break

        if not sub_file:
            return ""

        content = _read_bounded_utf8(sub_file, byte_limit=_MAX_CAPTION_BYTES)
        return _vtt_to_text(content) if content is not None else None


def _read_bounded_utf8(path: Path, *, byte_limit: int) -> str | None:
    try:
        with path.open("rb") as stream:
            content = stream.read(byte_limit + 1)
    except OSError:
        return None
    if len(content) > byte_limit:
        return None
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _try_whisper_ladder(
    video_url: str,
    video_id: str,
    output_path: Path,
    config: DistillConfig,
    tracker: _TranscriptionCostTracker | None = None,
) -> bool:
    """Download bestaudio and run the local-first transcription ladder.

    The same ``transcribe_media`` routing every other audio source uses; the
    vocabulary hint comes from the video's own title and uploader (the
    source knows what's in it), closing the proper-noun mistranscription
    class for caption-less YouTube videos too.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path, hint, duration_s = _download_audio(video_url, video_id, Path(tmpdir))
        if audio_path is None:
            return False
        from distill.ingestors.transcribe import TranscriptionError, transcribe_media

        try:
            result = transcribe_media(
                audio_path,
                config,
                vocabulary_hint=hint,
                tracker=tracker,
                duration_hint_s=duration_s,
            )
        except TranscriptionError as exc:
            console.print(f"    [red]Transcription ladder failed: {exc}[/red]")
            return False
        if not result.text.strip():
            return False
        atomic_write_text(output_path, result.text)
        return True


def _download_audio(video_url: str, video_id: str, tmpdir: Path) -> tuple[Path | None, str, float]:
    """Fetch bestaudio and return its path, vocabulary hint, and duration."""
    _bind_safe_ytdlp()
    ydl_opts: dict[str, object] = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": str(tmpdir / f"{video_id}.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "retries": 2,
        "socket_timeout": 30,
        "max_filesize": _MAX_AUDIO_BYTES,
        "noplaylist": True,
        "progress_hooks": [_audio_download_progress],
    }
    try:
        with SafeYoutubeDL(
            ydl_opts,
            metadata_byte_limit=YTDLP_METADATA_RESPONSE_BYTES,
            media_byte_limit=_MAX_AUDIO_BYTES,
            total_byte_limit=_MAX_AUDIO_BYTES + YTDLP_METADATA_TOTAL_BYTES,
        ) as ydl:
            info = info_mapping(ydl.extract_info(video_url, download=True)) or {}
    except Exception as exc:
        console.print(f"    [red]Audio download failed: {exc}[/red]")
        return None, "", 0.0
    files: list[Path] = []
    try:
        for candidate in tmpdir.iterdir():
            if not candidate.is_file():
                continue
            size = candidate.stat().st_size
            if size > _MAX_AUDIO_BYTES:
                return None, "", 0.0
            if size > 0:
                files.append(candidate)
    except OSError:
        return None, "", 0.0
    if not files:
        return None, "", 0.0
    audio = max(files, key=lambda f: f.stat().st_size)
    hint = " - ".join(
        part for part in (first_text(info, ("title",)), first_text(info, ("uploader",))) if part
    )
    duration_s = int_field(info, "duration")
    return audio, hint, float(duration_s) if duration_s > 0 else 0.0


def _vtt_to_text(vtt_content: str) -> str:
    """Convert VTT subtitle content to clean plain text."""
    lines = vtt_content.split("\n")
    text_lines = []
    seen = set()

    for line in lines:
        line = line.strip()
        # Skip headers, timestamps, empty lines
        if not line:
            continue
        if line.startswith("WEBVTT"):
            continue
        if line.startswith("Kind:") or line.startswith("Language:"):
            continue
        if line.startswith("NOTE"):
            continue
        if "-->" in line:
            continue
        if re.match(r"^\d+$", line):
            continue

        # Remove VTT formatting tags
        clean = re.sub(r"<[^>]+>", "", line)
        clean = clean.strip()

        if clean and clean not in seen:
            seen.add(clean)
            text_lines.append(clean)

    return " ".join(text_lines)


def _try_scribe(video_url: str, output_path: Path, config: DistillConfig) -> bool:
    """Legacy last-resort fallback: use scribe to transcribe."""
    if not config.scribe_path:
        console.print("    [red]No SCRIBE_PATH configured for fallback[/red]")
        return False

    configured_path = Path(config.scribe_path)
    try:
        scribe_path = configured_path.resolve(strict=True)
    except (OSError, RuntimeError):
        console.print(f"    [red]Scribe not found at {configured_path}[/red]")
        return False
    if not scribe_path.is_dir():
        console.print(f"    [red]Scribe is not a directory: {scribe_path}[/red]")
        return False

    try:
        with _scribe_output_lock(scribe_path):
            return _run_scribe(video_url, output_path, scribe_path)

    except Exception as e:
        console.print(f"    [red]Scribe error: {escape(str(e))}[/red]")
        return False


def _run_scribe(video_url: str, output_path: Path, scribe_path: Path) -> bool:
    """Run Scribe inside a private scratch tree and accept one safe output."""

    with tempfile.TemporaryDirectory(prefix="distill-scribe-") as temp_dir:
        scratch_root = Path(temp_dir)
        output_dir = scratch_root / "output"
        output_dir.mkdir(mode=0o700)
        executable = str(Path(sys.executable).resolve(strict=True))
        command = [
            executable,
            "-P",
            "-m",
            "scribe",
            "url",
            video_url,
            "--no-notes",
            "--no-joke",
            "--no-meme",
            "--no-docx",
        ]
        child_env = sanitized_package_env()
        child_env["PYTHONPATH"] = str(scribe_path)
        returncode, diagnostic = _run_scribe_process(command, scratch_root, child_env)
        if returncode != 0:
            suffix = f": {escape(diagnostic[-200:])}" if diagnostic else ""
            console.print(f"    [red]Scribe failed{suffix}[/red]")
            return False
        txt_files = list_confined_files(
            output_dir,
            scratch_root,
            suffix=".txt",
            max_entries=_SCRIBE_MAX_OUTPUT_ENTRIES,
            max_files=1,
            max_file_bytes=MAX_TRANSCRIPT_BYTES,
        )
        if not txt_files:
            console.print("    [red]Scribe ran but transcript not found[/red]")
            return False
        transcript = read_confined_text(
            txt_files[0],
            scratch_root,
            max_bytes=MAX_TRANSCRIPT_BYTES,
        )
        if transcript is None:
            console.print("    [red]Scribe returned an unsafe transcript file[/red]")
            return False
        atomic_write_text(output_path, transcript)
        return True


def _run_scribe_process(
    command: list[str],
    cwd: Path,
    env: dict[str, str],
) -> tuple[int, str]:
    """Execute Scribe with bounded diagnostics, resources, and tree lifetime."""

    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    stderr_stream = process.stderr
    if stderr_stream is None:
        terminate_isolated_process_tree(process)
        raise RuntimeError("Scribe did not expose a diagnostic pipe")
    diagnostic_tail, diagnostic_thread = start_bounded_pipe_drain(
        stderr_stream,
        limit=_SCRIBE_DIAGNOSTIC_BYTES,
        thread_name="distill-scribe-diagnostics",
    )
    job_handle: int | None = None
    returncode = -1
    try:
        job_handle = assign_windows_memory_job(
            process,
            job_memory_bytes=_SCRIBE_MEMORY_BYTES,
        )
        wait_for_process_budget(
            process,
            timeout_seconds=_SCRIBE_TIMEOUT_SECONDS,
            memory_limit_bytes=_SCRIBE_MEMORY_BYTES,
        )
        returncode = int(process.returncode or 0)
    except ProcessBudgetExceeded as exc:
        raise RuntimeError(f"Scribe exceeded its {exc.kind} budget") from exc
    finally:
        terminate_isolated_process_tree(process)
        close_windows_job(job_handle)
        diagnostic_thread.join(timeout=1)
        with contextlib.suppress(OSError):
            stderr_stream.close()
        diagnostic_thread.join(timeout=1)
    diagnostic = diagnostic_tail.bytes().decode("utf-8", errors="replace").strip()
    return returncode, diagnostic
