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
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Generator
from pathlib import Path
from typing import Protocol

import yt_dlp

from distill._console import console
from distill.config import DistillConfig
from distill.ingestors.youtube._yt_dlp_boundary import (
    first_text,
    info_mapping,
    int_field,
    ydl_params,
)
from distill.library.locking import exclusive_file_lock, open_lock_file
from distill.library.paths import atomic_write_text
from distill.youtube_urls import (
    normalize_video_id,
    normalize_youtube_video_url,
    youtube_video_id_from_url,
)

__all__ = [
    "get_transcript",
]

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
_MAX_CAPTION_BYTES = 20_000_000


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
            with yt_dlp.YoutubeDL(ydl_params(ydl_opts)) as ydl:
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
        with yt_dlp.YoutubeDL(ydl_params(ydl_opts)) as ydl:
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

    scribe_path = Path(config.scribe_path)
    if not scribe_path.exists():
        console.print(f"    [red]Scribe not found at {scribe_path}[/red]")
        return False

    try:
        with _scribe_output_lock(scribe_path):
            return _run_scribe(video_url, output_path, scribe_path)

    except subprocess.TimeoutExpired:
        console.print("    [red]Scribe timed out[/red]")
        return False
    except Exception as e:
        console.print(f"    [red]Scribe error: {e}[/red]")
        return False


def _run_scribe(video_url: str, output_path: Path, scribe_path: Path) -> bool:
    """Run Scribe and select its output while the shared lock is held."""

    output_dir = scribe_path / "output"
    before = {
        path.resolve(): (path.stat().st_mtime_ns, path.stat().st_size)
        for path in output_dir.glob("*.txt")
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scribe",
            "url",
            video_url,
            "--no-notes",
            "--no-joke",
            "--no-meme",
            "--no-docx",
        ],
        capture_output=True,
        text=True,
        cwd=str(scribe_path),
        timeout=600,
    )

    if result.returncode != 0:
        console.print(f"    [red]Scribe failed: {result.stderr[:200]}[/red]")
        return False

    if output_dir.exists():
        txt_files = sorted(
            (
                path
                for path in output_dir.glob("*.txt")
                if before.get(path.resolve()) != (path.stat().st_mtime_ns, path.stat().st_size)
            ),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        if txt_files:
            transcript = txt_files[0].read_text(encoding="utf-8")
            atomic_write_text(output_path, transcript)
            return True

    console.print("    [red]Scribe ran but transcript not found[/red]")
    return False
