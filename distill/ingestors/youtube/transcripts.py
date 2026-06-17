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

import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yt_dlp

from distill._console import console
from distill.config import DistillConfig
from distill.ingestors.youtube.discovery import is_youtube_url

__all__ = [
    "get_transcript",
]

# Backoff schedule for transient caption-fetch failures. Two retries keeps a
# 20-video sweep from stalling minutes on a dead video while still riding out
# one-off throttles. Module-level so tests can shrink it.
_RETRY_DELAYS: tuple[float, ...] = (1.0, 3.0)
_sleep = time.sleep

# Audio-download ceiling for the Whisper fallback: ~3h of 128kbps m4a. A
# longer video almost certainly has captions; this caps disk and ladder time.
_MAX_AUDIO_BYTES = 200_000_000


def get_transcript(
    video_url: str,
    video_id: str,
    output_path: Path,
    config: DistillConfig,
    tracker=None,
) -> bool:
    """Get transcript for a video. Returns True if successful.

    ``tracker`` (a ``CostTracker``, optional) records cloud STT spend when the
    Whisper fallback routes to a paid tier; local transcription records $0.
    """
    # yt-dlp does its own networking; pin to YouTube hosts so an attacker URL
    # can't drive an SSRF through the caption/audio download.
    if not is_youtube_url(video_url):
        console.print(f"    [red]Refusing non-YouTube URL: {video_url}[/red]")
        return False

    transcript = _try_youtube_captions(video_url, video_id)
    if transcript:
        output_path.write_text(transcript, encoding="utf-8")
        return True

    console.print("    [yellow]No captions; transcribing audio (local-first ladder)...[/yellow]")
    if _try_whisper_ladder(video_url, video_id, output_path, config, tracker=tracker):
        return True

    if config.scribe_path:
        console.print("    [yellow]Whisper ladder unavailable, falling back to scribe...[/yellow]")
        return _try_scribe(video_url, output_path, config)
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

        ydl_opts = {
            "writeautomaticsub": True,
            "writesubtitles": True,
            "subtitleslangs": ["en"],
            "subtitlesformat": "vtt",
            "skip_download": True,
            "outtmpl": output_template,
            "quiet": True,
            "no_warnings": True,
            "retries": 2,
            "socket_timeout": 30,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
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

        return _vtt_to_text(sub_file.read_text(encoding="utf-8"))


def _try_whisper_ladder(
    video_url: str,
    video_id: str,
    output_path: Path,
    config: DistillConfig,
    tracker=None,
) -> bool:
    """Download bestaudio and run the local-first transcription ladder.

    The same ``transcribe_media`` routing every other audio source uses; the
    vocabulary hint comes from the video's own title and uploader (the
    source knows what's in it), closing the proper-noun mistranscription
    class for caption-less YouTube videos too.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path, hint = _download_audio(video_url, video_id, Path(tmpdir))
        if audio_path is None:
            return False
        try:
            from distill.ingestors.transcribe import transcribe_media

            result = transcribe_media(audio_path, config, vocabulary_hint=hint)
        except Exception as exc:
            console.print(f"    [red]Transcription ladder failed: {exc}[/red]")
            return False
        if not result.text.strip():
            return False
        output_path.write_text(result.text, encoding="utf-8")
        if tracker is not None:
            tracker.record_transcription(
                result.provider, result.duration_s or 0.0, model=result.model
            )
        return True


def _download_audio(video_url: str, video_id: str, tmpdir: Path) -> tuple[Path | None, str]:
    """Fetch bestaudio for the Whisper ladder. Returns ``(path, vocab_hint)``."""
    ydl_opts = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": str(tmpdir / f"{video_id}.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "retries": 2,
        "socket_timeout": 30,
        "max_filesize": _MAX_AUDIO_BYTES,
        "noplaylist": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True) or {}
    except Exception as exc:
        console.print(f"    [red]Audio download failed: {exc}[/red]")
        return None, ""
    files = [f for f in tmpdir.iterdir() if f.is_file() and f.stat().st_size > 0]
    if not files:
        return None, ""
    audio = max(files, key=lambda f: f.stat().st_size)
    hint = " — ".join(
        part for part in (str(info.get("title", "")), str(info.get("uploader", ""))) if part
    )
    return audio, hint


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

        # Find the transcript file scribe created
        # Scribe outputs to its configured output folder
        # For now, look for the most recent .txt file
        output_dir = scribe_path / "output"
        if output_dir.exists():
            txt_files = sorted(
                output_dir.glob("*.txt"), key=lambda f: f.stat().st_mtime, reverse=True
            )
            if txt_files:
                transcript = txt_files[0].read_text(encoding="utf-8")
                output_path.write_text(transcript, encoding="utf-8")
                return True

        console.print("    [red]Scribe ran but transcript not found[/red]")
        return False

    except subprocess.TimeoutExpired:
        console.print("    [red]Scribe timed out[/red]")
        return False
    except Exception as e:
        console.print(f"    [red]Scribe error: {e}[/red]")
        return False
