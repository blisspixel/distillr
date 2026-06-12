"""Podcast episode ingest orchestration.

RSS-first capture with a transcript ladder that prefers free text over paid
audio: a Podcasting-2.0 publisher transcript is fetched when the feed offers
one; only otherwise is the enclosure downloaded and routed through the
local-first Whisper ladder (with a vocabulary hint derived from the episode's
own metadata -- the source knows what's in it). Artifacts follow the adapter
contract, and the write-time verify hook grounds the insight against the
episode receipt before commit.
"""

from __future__ import annotations

import hashlib
import tempfile
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console

from distill.config import DistillConfig
from distill.ingestors.podcasts import (
    PodcastEpisode,
    PodcastFeed,
    PodcastFetchError,
    download_audio,
    fetch_feed,
    fetch_transcript,
)
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
from distill.prompts.podcasts import podcast_insight_prompt
from distill.prompts.registry import PROMPT_IDS

console = Console()

__all__ = ["PodcastIngestResult", "ingest_podcast"]

PROMPT_ID = PROMPT_IDS["analysis.podcast"]


def _short_id(value: str) -> str:
    """Stable 8-hex identity for URL-shaped guids/feed URLs (slug-friendly)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


@dataclass(slots=True)
class PodcastIngestResult:
    """Artifacts and notes from ingesting one feed's episode(s)."""

    feed_title: str
    episode_paths: list[Path] = field(default_factory=list)  # Episode.md receipts
    insight_paths: list[Path] = field(default_factory=list)
    skipped_reasons: list[str] = field(default_factory=list)


def _episode_markdown(feed: PodcastFeed, ep: PodcastEpisode, transcript_source: str) -> str:
    minutes = f"{ep.duration_s // 60} min" if ep.duration_s else "unknown length"
    return "\n".join(
        [
            f"# {ep.title}",
            "",
            f"From **{feed.title}** -- published {ep.published or 'unknown date'} ({minutes}).",
            f"Transcript source: {transcript_source}.",
            "",
            "## Show notes",
            "",
            ep.description or "_(none)_",
            "",
        ]
    )


def _resolve_transcript(
    ep: PodcastEpisode, config: DistillConfig, *, transcribe: bool, skipped: list[str]
) -> tuple[str, str]:
    """Return ``(transcript_text, source_label)`` via the free-first ladder."""
    if ep.transcript_url:
        try:
            text = fetch_transcript(ep.transcript_url, transcript_type=ep.transcript_type)
            if text.strip():
                return text, "publisher transcript"
        except PodcastFetchError as exc:
            skipped.append(f"publisher transcript failed ({exc}); falling back to audio")
    if not ep.audio_url:
        skipped.append(f"{ep.title}: no audio enclosure and no usable transcript")
        return "", "none"
    if not transcribe:
        skipped.append(f"{ep.title}: --no-transcribe set and no publisher transcript")
        return "", "none"
    with tempfile.TemporaryDirectory(prefix="distill-podcast-") as tmp:
        audio = download_audio(ep.audio_url, Path(tmp))
        hint = f"{ep.title}. {ep.description[:300]}"
        try:
            result = transcribe_media(audio, config, vocabulary_hint=hint)
        except TranscriptionError as exc:
            skipped.append(f"{ep.title}: transcription failed ({exc})")
            return "", "none"
        return result.text, f"transcribed ({result.provider}/{result.model})"


def ingest_podcast(
    feed_url: str,
    *,
    topic: str,
    config: DistillConfig,
    episodes: int = 1,
    transcribe: bool = True,
    analyze: bool = True,
    tracker: CostTracker | None = None,
    feed: PodcastFeed | None = None,
) -> PodcastIngestResult:
    """Ingest the latest *episodes* of an RSS podcast feed into *topic*.

    ``feed`` accepts a pre-fetched parse so the dispatcher can route
    podcast-vs-newsletter from one fetch.
    """
    if feed is None:
        feed = fetch_feed(feed_url)
    result = PodcastIngestResult(feed_title=feed.title or feed_url)
    if not feed.episodes:
        result.skipped_reasons.append("Feed parsed but contains no episodes.")
        return result

    # Feed and episode identifiers are usually URLs; a URL fed straight into
    # the slug sanitizer yields a useless "_https" tail. Use the feed host and
    # a short stable digest of the guid instead.
    feed_sid = urllib.parse.urlparse(feed_url).netloc.removeprefix("www.") or _short_id(feed_url)
    feed_slug = slugify_title(feed.title or feed_url, source_id=feed_sid)
    for ep in feed.episodes[: max(1, episodes)]:
        ep_sid = (
            ep.guid
            if not ep.guid.lower().startswith(("http://", "https://"))
            else _short_id(ep.guid)
        )
        ep_slug = slugify_title(ep.title, source_id=ep_sid)
        ep_dir = config.topic_dir(topic) / "podcasts" / feed_slug / ep_slug
        console.print(f"  [dim]{ep.title}[/dim]")

        transcript, transcript_source = _resolve_transcript(
            ep, config, transcribe=transcribe, skipped=result.skipped_reasons
        )
        episode_md = _episode_markdown(feed, ep, transcript_source)
        frontmatter = base_frontmatter(
            artifact_type="episode",
            title=ep.title,
            topic=topic,
            source="podcast",
            source_id=ep.guid,
            url=ep.audio_url or feed.link,
            date=ep.published,
            tags=tags_for(topic, "podcast"),
            extra={
                "show": feed.title,
                "duration_seconds": ep.duration_s,
                "transcript_source": transcript_source,
            },
        )
        episode_path = write_markdown_artifact(
            ep_dir, "episode", episode_md, identity=ep_slug, frontmatter=frontmatter
        )
        result.episode_paths.append(episode_path)
        if transcript:
            write_text_artifact(ep_dir, "transcript", transcript, identity=ep_slug, extension="txt")

        if not (analyze and transcript):
            if analyze and not transcript:
                result.skipped_reasons.append(f"{ep.title}: no transcript; analysis skipped")
            continue

        rc = RouterConfig()
        response = llm_call(
            rc,
            workload_tag="site",
            prompt=podcast_insight_prompt(
                show_title=feed.title,
                episode_title=ep.title,
                published=ep.published,
                episode_url=ep.audio_url or feed.link,
                description=ep.description,
                transcript=transcript,
            ),
            call_type="podcast_analysis",
        )
        if tracker is not None:
            tracker.record(
                TokenUsage(
                    prompt_tokens=response.input_tokens,
                    completion_tokens=response.output_tokens,
                    model=response.model,
                    call_type="podcast_analysis",
                )
            )

        # Write-time verify hook: the receipt is the transcript + show notes.
        from distill.pipeline.verify import resolve_verify_mode, run_verify_hook

        outcome = run_verify_hook(
            ep_dir,
            response.text,
            f"{episode_md}\n\n{transcript}",
            mode=resolve_verify_mode(config.distill_verify),
            identity=ep_slug,
            insight_name=artifact_path(ep_dir, "insights", identity=ep_slug).name,
            source_name=episode_path.name,
        )
        if outcome is not None and not outcome.report.ok:
            style = "red" if outcome.refused else "yellow"
            console.print(f"  [{style}]{outcome.summary_line}[/{style}]")
        if outcome is not None and outcome.refused:
            result.skipped_reasons.append(outcome.summary_line)
            continue

        insight_path = write_markdown_artifact(
            ep_dir,
            "insights",
            response.text,
            identity=ep_slug,
            frontmatter=base_frontmatter(
                artifact_type="insights",
                title=ep.title,
                topic=topic,
                source="podcast",
                source_id=ep.guid,
                url=ep.audio_url or feed.link,
                date=ep.published,
                tags=tags_for(topic, "podcast"),
                synthesis_scope="single-source",
                extra={"show": feed.title, "transcript_source": transcript_source},
                provenance=ProvenanceFields(
                    model=response.model,
                    model_version=response.model,
                    temperature=0.0,
                    prompt_id=PROMPT_ID,
                ),
            ),
        )
        result.insight_paths.append(insight_path)

    return result
