# pyright: strict
"""Tweet ingestion + analysis orchestration.

Pulls a tweet via the syndication endpoint, optionally downloads and
transcribes the attached X-native video, runs the analysis prompt, and
writes the conventional artifact set (Tweet.md / Transcript.txt /
Insights.md) under ``library/topics/<topic>/x/<handle>/posts/<slug>/``.
"""

from __future__ import annotations

import contextlib
import sys
from dataclasses import dataclass, field
from pathlib import Path

from distill._console import console
from distill.config import DistillConfig
from distill.ingestors.transcribe import TranscriptionError, transcribe_media
from distill.ingestors.x.media import download_video
from distill.ingestors.x.syndication import TweetRecord, fetch_tweet
from distill.library.paths import (
    ProvenanceFields,
    artifact_path,
    base_frontmatter,
    sanitize_path_component,
    slugify_title,
    tags_for,
    write_markdown_artifact,
    write_text_artifact,
)
from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.registry import PROMPT_IDS
from distill.prompts.x import tweet_insight_prompt, vocabulary_expansion_prompt

__all__ = ["IngestedTweet", "analyze_tweet", "ingest_tweet"]


@dataclass(slots=True)
class IngestedTweet:
    tweet: TweetRecord
    post_dir: Path
    tweet_path: Path
    transcript_path: Path | None = None
    insights_path: Path | None = None
    media_path: Path | None = None
    transcript_text: str = ""
    insights_text: str = ""
    skipped_reasons: list[str] = field(default_factory=list[str])


def _x_post_dir(config: DistillConfig, topic: str, tweet: TweetRecord) -> Path:
    handle_dir = sanitize_path_component(tweet.author_handle or "anonymous")
    slug = slugify_title(
        f"{tweet.author_handle} {tweet.tweet_id}",
        tweet.tweet_id,
        max_len=70,
    )
    return config.topic_dir(topic) / "x" / handle_dir / "posts" / slug


def _tweet_identity(tweet: TweetRecord) -> str:
    handle = sanitize_path_component(tweet.author_handle or "anon")
    return f"{handle}_{tweet.tweet_id}"


def _tweet_markdown(tweet: TweetRecord, transcript_text: str) -> str:
    lines = [
        f"# {tweet.author_name} ({tweet.display_handle}) - {tweet.published_iso or tweet.created_at}",
        "",
        f"Source: {tweet.url}",
        f"Likes: {tweet.like_count}  •  Replies: {tweet.reply_count}",
        "",
        "## Tweet",
        "",
        tweet.text or "(no text)",
    ]
    if tweet.note_text and tweet.note_text.strip() != tweet.text.strip():
        lines += ["", "## Long-form body (note_tweet)", "", tweet.note_text]
    if tweet.photo_urls:
        lines += ["", "## Attached photos"]
        lines += [f"- {url}" for url in tweet.photo_urls]
    if tweet.has_video:
        duration_s = tweet.video_duration_ms / 1000.0
        # Append the video block directly. (Previously this filtered every ""
        # out of the whole document to drop the optional poster line, which
        # collapsed all paragraph separators and produced malformed Markdown
        # for any tweet with a video.)
        lines += ["", "## Attached video", "", f"- Source: {tweet.video_url}"]
        if tweet.video_poster:
            lines.append(f"- Poster: {tweet.video_poster}")
        lines.append(f"- Duration: {duration_s:.1f}s")
    if transcript_text:
        lines += ["", "## Video transcript (whisper-transcribed)", "", transcript_text]
    return "\n".join(lines) + "\n"


def _source_text_hint(tweet: TweetRecord) -> str:
    """Build the source-text portion of the Whisper ``initial_prompt``.

    Uses only the tweet's verbatim text + author identity. Posters
    usually spell brand names correctly in the headline, so this gives
    Whisper a first pass at the proper nouns the source already names.
    The LLM-expanded hint (see :func:`_expanded_vocabulary_hint`) layers
    on top to cover proper nouns the tweet text doesn't spell out.
    """
    parts: list[str] = []
    if tweet.author_name:
        parts.append(tweet.author_name)
    if tweet.author_handle:
        parts.append(f"@{tweet.author_handle}")
    if tweet.text:
        parts.append(tweet.text)
    if tweet.note_text and tweet.note_text.strip() != tweet.text.strip():
        parts.append(tweet.note_text)
    return " - ".join(parts)


def _expanded_vocabulary_hint(
    tweet: TweetRecord,
    *,
    tracker: CostTracker | None = None,
) -> str:
    """Call the LLM to expand the tweet's metadata into a proper-noun list.

    Returns a comma-separated string of proper nouns the attached video
    is likely to mention. Empty string on failure (transcription
    proceeds with just the source-text hint). The LLM call is cheap
    (small input, small output) - typically a few hundred tokens total.
    """
    rc = RouterConfig()
    duration_s = tweet.video_duration_ms / 1000.0
    prompt = vocabulary_expansion_prompt(
        author_name=tweet.author_name,
        author_handle=tweet.display_handle,
        tweet_text=tweet.text,
        note_text=tweet.note_text,
        video_duration_s=duration_s,
    )
    try:
        response = llm_call(rc, workload_tag="site", prompt=prompt, call_type="x_vocab_expand")
    except Exception as exc:
        console.print(
            f"        [yellow]vocab expansion failed (continuing without): {exc}[/yellow]"
        )
        return ""
    if tracker:
        tracker.record(TokenUsage.from_response(response, call_type="x_vocab_expand"))
    # Collapse to one line; drop common prefixes the LLM sometimes adds
    # despite instructions.
    text = " ".join(response.text.split())
    for prefix in ("Output:", "Output now:", "Terms:", "Vocabulary:"):
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix) :].strip()
    return text


def _vocabulary_hint(tweet: TweetRecord, *, tracker: CostTracker | None = None) -> str:
    """Whisper ``initial_prompt`` combining source text and LLM expansion.

    Layered approach:
    1. Source-text hint (tweet body + author) - proper nouns the
       poster literally spelled.
    2. LLM-expanded hint - proper nouns the tweet implies but doesn't
       spell out (Anthropic tweet about Claude → also "Claude Code",
       "CLAUDE.md", "MCP", etc.).

    Both layers are joined with ``" - "``. Whisper's effective prompt
    budget is ~200 tokens; ``_clip_for_whisper`` in transcribe.py trims
    the combined string at a word boundary if it overflows.
    """
    source = _source_text_hint(tweet)
    expanded = _expanded_vocabulary_hint(tweet, tracker=tracker)
    if expanded and source:
        return f"{source} - {expanded}"
    return expanded or source


def _media_summary(tweet: TweetRecord) -> str:
    parts: list[str] = []
    if tweet.has_video:
        duration_s = tweet.video_duration_ms / 1000.0
        parts.append(f"video clip, ~{duration_s:.1f}s")
    if tweet.photo_urls:
        parts.append(f"{len(tweet.photo_urls)} photo(s)")
    return ", ".join(parts)


def analyze_tweet(
    tweet: TweetRecord,
    *,
    transcript_text: str = "",
    config: DistillConfig | None = None,
    tracker: CostTracker | None = None,
) -> str:
    """Run the insight prompt for a tweet and return a frontmattered Markdown blob."""
    _ = config  # not currently needed; reserved for future model routing
    rc = RouterConfig()
    prompt = tweet_insight_prompt(
        author_name=tweet.author_name,
        author_handle=tweet.display_handle,
        posted_at=tweet.published_iso or tweet.created_at,
        tweet_url=tweet.url,
        tweet_text=tweet.text,
        note_text=tweet.note_text,
        transcript=transcript_text,
        media_summary=_media_summary(tweet),
    )
    response = llm_call(rc, workload_tag="site", prompt=prompt, call_type="x_tweet")
    if tracker:
        tracker.record(TokenUsage.from_response(response, call_type="x_tweet"))
    body = response.text
    frontmatter = base_frontmatter(
        artifact_type="insights",
        title=f"X post by {tweet.author_name} ({tweet.display_handle})",
        topic="",  # filled in by caller via apply_frontmatter
        source="x",
        source_id=tweet.tweet_id,
        url=tweet.url,
        date=tweet.published_iso or tweet.created_at,
        authors=[tweet.author_name] if tweet.author_name else [],
        tags=tags_for("", "x"),
        synthesis_scope="single-post",
        extra={
            "handle": tweet.display_handle,
            "has_video": tweet.has_video,
            "video_duration_ms": tweet.video_duration_ms,
            "like_count": tweet.like_count,
            "reply_count": tweet.reply_count,
        },
        provenance=ProvenanceFields(
            model=response.model,
            model_version=response.model,
            temperature=0.0,
            prompt_id=PROMPT_IDS["analysis.x_tweet"],
        ),
    )
    from distill.library.paths import apply_frontmatter

    return apply_frontmatter(body, frontmatter)


def _verified_insights_write(
    post_dir: Path,
    insights_text: str,
    tweet_md: str,
    *,
    config: DistillConfig,
    identity: str,
    source_name: str,
    skipped: list[str],
) -> Path | None:
    """Run the write-time verify hook, then write the insight unless refused.

    The receipt is the tweet markdown itself (post text + inline transcript);
    under strict mode an insight with unsupported numeric claims is not
    written and the refusal joins the run's skip reasons.
    """
    from distill.pipeline.verify import resolve_verify_mode, run_verify_hook

    outcome = run_verify_hook(
        post_dir,
        insights_text,
        tweet_md,
        mode=resolve_verify_mode(config.distill_verify),
        identity=identity,
        insight_name=artifact_path(post_dir, "insights", identity=identity).name,
        source_name=source_name,
    )
    if outcome is not None and not outcome.report.ok:
        style = "red" if outcome.refused else "yellow"
        console.print(f"        [{style}]{outcome.summary_line}[/{style}]")
    if outcome is not None and outcome.refused:
        skipped.append(outcome.summary_line)
        return None
    return write_markdown_artifact(post_dir, "insights", insights_text, identity=identity)


def ingest_tweet(
    url_or_id: str,
    topic: str,
    config: DistillConfig,
    *,
    transcribe: bool = True,
    tracker: CostTracker | None = None,
    analyze: bool = True,
) -> IngestedTweet:
    """End-to-end ingest of a single tweet.

    1. Fetch metadata via syndication.
    2. Write Tweet.md raw artifact.
    3. If video present and ``transcribe`` is true, download .mp4 and
       run Whisper, write Transcript.txt.
    4. If ``analyze`` is true, run the insight prompt and write Insights.md.
    """
    console.print(f"  [cyan]X[/cyan]  fetching tweet [bold]{url_or_id}[/bold]")
    tweet = fetch_tweet(url_or_id)
    post_dir = _x_post_dir(config, topic, tweet)
    post_dir.mkdir(parents=True, exist_ok=True)
    identity = _tweet_identity(tweet)

    transcript_text = ""
    transcript_path: Path | None = None
    media_path: Path | None = None
    skipped: list[str] = []

    if tweet.has_video and transcribe:
        media_path = post_dir / "media.mp4"
        try:
            if media_path.exists() and media_path.stat().st_size > 0:
                console.print(
                    f"        reusing existing {media_path.name} "
                    f"({media_path.stat().st_size / 1_000_000:.1f} MB)"
                )
            else:
                console.print(
                    f"        downloading video ({tweet.video_duration_ms / 1000:.1f}s) "
                    f"to {media_path.name}"
                )
                download_video(tweet.video_url, media_path)
            console.print("        building vocabulary hint (source + LLM expansion)...")
            vocab_hint = _vocabulary_hint(tweet, tracker=tracker)
            if vocab_hint:
                preview = vocab_hint[:120] + ("..." if len(vocab_hint) > 120 else "")
                console.print(f"        vocab hint ({len(vocab_hint)} chars): {preview}")
            console.print("        transcribing (local-first -> cloud fallback)...")
            result = transcribe_media(
                media_path,
                config,
                vocabulary_hint=vocab_hint,
                tracker=tracker,
                duration_hint_s=tweet.video_duration_ms / 1000.0,
            )
            transcript_text = result.text
            # Flush rich.Console before the long write+analyze block so
            # non-TTY supervisors watching stdout activity see we made it
            # past the transcription step.
            console.print(
                f"        transcript: {len(transcript_text.split())} words "
                f"via {result.provider} ({result.model})"
            )
            with contextlib.suppress(Exception):
                sys.stderr.write("        [pipeline] transcription complete\n")
                sys.stderr.flush()
            transcript_path = write_text_artifact(
                post_dir,
                "transcript",
                transcript_text,
                identity=identity,
                extension="txt",
            )
        except TranscriptionError as exc:
            console.print(f"        [yellow]transcription skipped: {exc}[/yellow]")
            skipped.append(f"transcription: {exc}")
        except Exception as exc:
            console.print(f"        [yellow]video pipeline failed: {exc}[/yellow]")
            skipped.append(f"video: {exc}")
    elif tweet.has_video and not transcribe:
        skipped.append("video present but --no-transcribe set")

    # Raw Tweet.md (now including transcript inline for human reading)
    tweet_md = _tweet_markdown(tweet, transcript_text)
    tweet_frontmatter = base_frontmatter(
        artifact_type="tweet",
        title=f"X post by {tweet.author_name} ({tweet.display_handle})",
        topic=topic,
        source="x",
        source_id=tweet.tweet_id,
        url=tweet.url,
        date=tweet.published_iso or tweet.created_at,
        authors=[tweet.author_name] if tweet.author_name else [],
        tags=tags_for(topic, "x"),
        extra={
            "handle": tweet.display_handle,
            "language": tweet.language,
            "like_count": tweet.like_count,
            "reply_count": tweet.reply_count,
            "has_video": tweet.has_video,
            "video_duration_ms": tweet.video_duration_ms,
            "video_url": tweet.video_url,
            "photo_count": len(tweet.photo_urls),
        },
    )
    tweet_path = write_markdown_artifact(
        post_dir,
        "tweet",
        tweet_md,
        identity=identity,
        frontmatter=tweet_frontmatter,
    )

    insights_path: Path | None = None
    insights_text = ""
    if analyze:
        console.print("        running insight extraction...")
        insights_text = analyze_tweet(
            tweet,
            transcript_text=transcript_text,
            config=config,
            tracker=tracker,
        )
        # Re-apply with the topic filled in (analyze_tweet leaves topic blank).
        from distill.library.paths import apply_frontmatter

        insights_text = apply_frontmatter(
            insights_text, {"topic": topic, "tags": tags_for(topic, "x")}
        )
        insights_path = _verified_insights_write(
            post_dir,
            insights_text,
            tweet_md,
            config=config,
            identity=identity,
            source_name=tweet_path.name,
            skipped=skipped,
        )

    return IngestedTweet(
        tweet=tweet,
        post_dir=post_dir,
        tweet_path=tweet_path,
        transcript_path=transcript_path,
        insights_path=insights_path,
        media_path=media_path,
        transcript_text=transcript_text,
        insights_text=insights_text,
        skipped_reasons=skipped,
    )
