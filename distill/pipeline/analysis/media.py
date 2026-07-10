# pyright: strict
"""Local media-file ingest orchestration (audio/video -> transcript -> insight).

The "raw media" adapter the roadmap scoped as nearly-free once the local-file
dispatcher and the Whisper layer existed: conference talks distributed as
files, downloaded recordings, voice memos, interview audio. The transcript is
the capture receipt; the vocabulary hint comes deterministically from the
filename; the write-time verify hook grounds the insight against the
transcript before commit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from distill._console import console
from distill.config import DistillConfig
from distill.ingestors.transcribe import TranscriptionError, transcribe_media
from distill.library.paths import (
    ProvenanceFields,
    artifact_path,
    base_frontmatter,
    slugify_title,
    tags_for,
    write_markdown_artifact,
    write_text_artifact,
)
from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.media import media_insight_prompt
from distill.prompts.registry import PROMPT_IDS

__all__ = ["MEDIA_EXTENSIONS", "MediaIngestResult", "ingest_media_file", "is_media_file"]

PROMPT_ID = PROMPT_IDS["analysis.media"]

MEDIA_EXTENSIONS = frozenset(
    {".mp3", ".m4a", ".wav", ".opus", ".flac", ".ogg", ".aac", ".mp4", ".webm", ".mov", ".mkv"}
)


def is_media_file(path: Path) -> bool:
    return path.suffix.lower() in MEDIA_EXTENSIONS


@dataclass(slots=True)
class MediaIngestResult:
    """Artifacts and notes from one media-file ingest."""

    transcript_path: Path | None
    insights_path: Path | None
    title: str
    skipped_reasons: list[str] = field(default_factory=list[str])


def ingest_media_file(
    path: Path,
    *,
    topic: str,
    config: DistillConfig,
    analyze: bool = True,
    tracker: CostTracker | None = None,
) -> MediaIngestResult:
    """Transcribe and analyze one local audio/video file into ``topic``.

    Files under ``library/topics/<topic>/media/<slug>/``. The source file
    stays where the user keeps it; the transcript is the corpus receipt
    (referenced by filename in frontmatter).
    """
    title = re.sub(r"[-_]+", " ", path.stem).strip() or path.name
    slug = slugify_title(title, source_id=path.name)
    media_dir = config.topic_dir(topic) / "media" / slug
    result = MediaIngestResult(transcript_path=None, insights_path=None, title=title)

    try:
        transcription = transcribe_media(path, config, vocabulary_hint=title, tracker=tracker)
    except TranscriptionError as exc:
        result.skipped_reasons.append(f"transcription failed: {exc}")
        return result
    transcript = transcription.text
    if not transcript.strip():
        result.skipped_reasons.append("transcription produced no text")
        return result

    result.transcript_path = write_text_artifact(
        media_dir, "transcript", transcript, identity=slug, extension="txt"
    )

    if not analyze:
        return result

    rc = RouterConfig()
    response = llm_call(
        rc,
        workload_tag="site",
        prompt=media_insight_prompt(file_name=path.name, transcript=transcript),
        call_type="media_analysis",
    )
    if tracker is not None:
        tracker.record(TokenUsage.from_response(response, call_type="media_analysis"))

    # Write-time verify hook: the receipt is the transcript itself.
    from distill.pipeline.verify import resolve_verify_mode, run_verify_hook

    outcome = run_verify_hook(
        media_dir,
        response.text,
        transcript,
        mode=resolve_verify_mode(config.distill_verify),
        identity=slug,
        insight_name=artifact_path(media_dir, "insights", identity=slug).name,
        source_name=result.transcript_path.name,
    )
    if outcome is not None and not outcome.report.ok:
        style = "red" if outcome.refused else "yellow"
        console.print(f"  [{style}]{outcome.summary_line}[/{style}]")
    if outcome is not None and outcome.refused:
        result.skipped_reasons.append(outcome.summary_line)
        return result

    result.insights_path = write_markdown_artifact(
        media_dir,
        "insights",
        response.text,
        identity=slug,
        frontmatter=base_frontmatter(
            artifact_type="insights",
            title=title,
            topic=topic,
            source="media",
            source_id=path.name,
            tags=tags_for(topic, "media"),
            synthesis_scope="single-source",
            extra={
                "transcribed_by": f"{transcription.provider}/{transcription.model}",
                "source_file": path.name,
            },
            provenance=ProvenanceFields(
                model=response.model,
                model_version=response.model,
                temperature=0.0,
                prompt_id=PROMPT_ID,
            ),
        ),
    )
    return result
