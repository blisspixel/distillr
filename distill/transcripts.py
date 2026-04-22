"""Transcript acquisition — YouTube captions first, scribe fallback."""

import re
import subprocess
import tempfile
from pathlib import Path

import yt_dlp
from rich.console import Console

from distill.config import DistillConfig

console = Console()


def get_transcript(video_url: str, video_id: str, output_path: Path, config: DistillConfig) -> bool:
    """Get transcript for a video. Returns True if successful."""
    # Try YouTube captions first (free, instant)
    transcript = _try_youtube_captions(video_url, video_id)
    if transcript:
        output_path.write_text(transcript, encoding="utf-8")
        return True

    # Fallback to scribe
    console.print("    [yellow]No captions, falling back to scribe...[/yellow]")
    return _try_scribe(video_url, output_path, config)


def _try_youtube_captions(video_url: str, video_id: str) -> str | None:
    """Try to get YouTube auto-captions via yt-dlp."""
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
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
        except Exception:
            return None

        # Find the subtitle file
        sub_file = None
        for f in Path(tmpdir).iterdir():
            if f.suffix == ".vtt" and "en" in f.name:
                sub_file = f
                break

        if not sub_file:
            return None

        # Parse VTT to plain text
        return _vtt_to_text(sub_file.read_text(encoding="utf-8"))


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
    """Fallback: use scribe to transcribe."""
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
                "python",
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
