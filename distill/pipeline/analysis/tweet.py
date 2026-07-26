# pyright: strict
"""Tweet ingestion + analysis orchestration.

Pulls a tweet via the syndication endpoint, optionally downloads and
transcribes the attached X-native video, runs the analysis prompt, and
writes the conventional artifact set (Tweet.md / Transcript.txt /
Insights.md) under ``library/topics/<topic>/x/<handle>/posts/<slug>/``.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from distill._console import console
from distill.config import DistillConfig
from distill.ingestors.transcribe import TranscriptionError, transcribe_media
from distill.ingestors.x.media import download_video, is_reusable_video
from distill.ingestors.x.syndication import TweetRecord, fetch_tweet
from distill.library.paths import (
    ProvenanceFields,
    apply_frontmatter,
    artifact_path,
    atomic_write_text,
    base_frontmatter,
    extract_frontmatter,
    find_artifact,
    sanitize_path_component,
    slugify_title,
    strip_frontmatter,
    tags_for,
    write_markdown_artifact,
    write_text_artifact,
)
from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
from distill.pipeline.costs import BudgetExceededError, CostTracker, TokenUsage
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
    reused: bool = False


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


def _stable_media_url(value: str) -> str:
    """Discard volatile query parameters while retaining media identity."""
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return ""
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
    ):
        return ""
    return f"{parsed.scheme.lower()}://{parsed.hostname.lower()}{parsed.path}"


def _tweet_source_content_hash(tweet: TweetRecord) -> str:
    """Hash semantic source fields while excluding mutable engagement counts."""
    payload = {
        "tweet_id": tweet.tweet_id,
        "author_name": tweet.author_name,
        "author_handle": tweet.author_handle,
        "created_at": tweet.created_at,
        "text": tweet.text,
        "note_text": tweet.note_text,
        "language": tweet.language,
        "photo_urls": [_stable_media_url(url) for url in tweet.photo_urls],
        "video_url": _stable_media_url(tweet.video_url),
        "video_duration_ms": tweet.video_duration_ms,
        "link_preview_type": tweet.link_preview_type,
        "link_preview_title": tweet.link_preview_title,
        "link_preview_description": tweet.link_preview_description,
        "link_preview_domain": tweet.link_preview_domain,
        "link_preview_url": tweet.link_preview_url,
        "quoted_tweet_status": tweet.quoted_tweet_status,
        "quoted_tweet_id": tweet.quoted_tweet_id,
        "quoted_tweet_url": tweet.quoted_tweet_url,
        "quoted_tweet_author_name": tweet.quoted_tweet_author_name,
        "quoted_tweet_author_handle": tweet.quoted_tweet_author_handle,
        "quoted_tweet_text": tweet.quoted_tweet_text,
        "capture_status": tweet.capture_status,
        "capture_warning": tweet.capture_warning,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _existing_tweet_receipt(
    config: DistillConfig,
    topic: str,
    tweet_id: str,
) -> Path | None:
    """Find a prior receipt by stable post ID, even if the handle changed."""
    x_dir = config.topic_dir(topic) / "x"
    if not x_dir.exists():
        return None
    candidates = [*sorted(x_dir.rglob("*_Tweet.md")), *sorted(x_dir.rglob("Tweet.md"))]
    for path in candidates:
        try:
            frontmatter = extract_frontmatter(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        if frontmatter.get("source_id") == tweet_id:
            return path
    return None


def _identity_from_tweet_path(path: Path, fallback: str) -> str:
    suffix = "_Tweet.md"
    return path.name[: -len(suffix)] if path.name.endswith(suffix) else fallback


def _nonempty(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def _completed_tweet_replay(
    tweet: TweetRecord,
    post_dir: Path,
    identity: str,
    existing_receipt: Path | None,
    source_content_hash: str,
    *,
    transcribe: bool,
    analyze: bool,
    force: bool,
) -> IngestedTweet | None:
    """Return a completed unchanged replay without touching its artifacts."""
    if force or existing_receipt is None:
        return None
    try:
        previous_hash = extract_frontmatter(existing_receipt.read_text(encoding="utf-8")).get(
            "content_hash"
        )
    except OSError:
        return None
    existing_transcript = find_artifact(
        post_dir,
        "transcript",
        identity=identity,
        extension="txt",
    )
    transcript_complete = not tweet.has_video or not transcribe or _nonempty(existing_transcript)
    if previous_hash != source_content_hash or not transcript_complete:
        return None
    existing_insights: Path | None = None
    insights_text = ""
    if analyze:
        existing_insights = find_artifact(post_dir, "insights", identity=identity)
        try:
            insights_text = existing_insights.read_text(encoding="utf-8")
            insight_hash = extract_frontmatter(insights_text).get("content_hash")
        except OSError:
            return None
        if insight_hash != source_content_hash or not _nonempty(existing_insights):
            return None
    transcript_text = (
        existing_transcript.read_text(encoding="utf-8") if _nonempty(existing_transcript) else ""
    )
    media_path = post_dir / "media.mp4"
    return IngestedTweet(
        tweet=tweet,
        post_dir=post_dir,
        tweet_path=existing_receipt,
        transcript_path=existing_transcript if _nonempty(existing_transcript) else None,
        insights_path=existing_insights,
        media_path=media_path if _nonempty(media_path) else None,
        transcript_text=transcript_text,
        insights_text=insights_text,
        skipped_reasons=[
            "unchanged completed requested artifacts; reusing them (pass --force to refresh)"
        ],
        reused=True,
    )


def _normalized_legacy_receipt_body(content: str) -> str:
    """Remove engagement counters that can change without a source edit."""
    body = strip_frontmatter(content)
    return "\n".join(
        line.rstrip()
        for line in body.splitlines()
        if not (line.startswith("Likes:") and "Replies:" in line)
    ).strip()


def _legacy_pair_order_is_safe(receipt_path: Path, insights_path: Path) -> bool:
    """Reject raw-capture refreshes whose old insight predates the receipt."""
    try:
        receipt_text = receipt_path.read_text(encoding="utf-8")
        insights_text = insights_path.read_text(encoding="utf-8")
        receipt_generated = extract_frontmatter(receipt_text).get("generated_at", "")
        insights_generated = extract_frontmatter(insights_text).get("generated_at", "")
        if receipt_generated and insights_generated and receipt_generated != insights_generated:
            return insights_generated > receipt_generated
        return insights_path.stat().st_mtime_ns >= receipt_path.stat().st_mtime_ns
    except OSError:
        return False


def _migrate_legacy_completed_tweet(
    tweet: TweetRecord,
    post_dir: Path,
    identity: str,
    existing_receipt: Path | None,
    source_content_hash: str,
    *,
    transcribe: bool,
    analyze: bool,
    force: bool,
) -> IngestedTweet | None:
    """Stamp proven unchanged pre-hash requested artifacts without model work."""
    if force or existing_receipt is None:
        return None
    try:
        receipt_text = existing_receipt.read_text(encoding="utf-8")
        receipt_hash = extract_frontmatter(receipt_text).get("content_hash")
    except OSError:
        return None
    if receipt_hash:
        return None
    existing_transcript = find_artifact(
        post_dir,
        "transcript",
        identity=identity,
        extension="txt",
    )
    transcript_complete = not tweet.has_video or not transcribe or _nonempty(existing_transcript)
    if not transcript_complete:
        return None
    existing_insights: Path | None = None
    insights_text = ""
    if analyze:
        existing_insights = find_artifact(post_dir, "insights", identity=identity)
        if not _nonempty(existing_insights) or not _legacy_pair_order_is_safe(
            existing_receipt, existing_insights
        ):
            return None
        insights_text = existing_insights.read_text(encoding="utf-8")
    transcript_text = (
        existing_transcript.read_text(encoding="utf-8") if _nonempty(existing_transcript) else ""
    )
    current_body = _tweet_markdown(tweet, transcript_text)
    if _normalized_legacy_receipt_body(receipt_text) != _normalized_legacy_receipt_body(
        current_body
    ):
        return None

    if existing_insights is not None:
        atomic_write_text(
            existing_insights,
            apply_frontmatter(insights_text, {"content_hash": source_content_hash}),
        )
    atomic_write_text(
        existing_receipt,
        apply_frontmatter(receipt_text, {"content_hash": source_content_hash}),
    )
    media_path = post_dir / "media.mp4"
    return IngestedTweet(
        tweet=tweet,
        post_dir=post_dir,
        tweet_path=existing_receipt,
        transcript_path=existing_transcript if _nonempty(existing_transcript) else None,
        insights_path=existing_insights,
        media_path=media_path if _nonempty(media_path) else None,
        transcript_text=transcript_text,
        insights_text=(
            existing_insights.read_text(encoding="utf-8") if existing_insights is not None else ""
        ),
        skipped_reasons=[
            "unchanged legacy requested artifacts; recorded a content hash and reused them "
            "(pass --force to refresh)"
        ],
        reused=True,
    )


def _existing_tweet_replay(
    tweet: TweetRecord,
    post_dir: Path,
    identity: str,
    existing_receipt: Path | None,
    source_content_hash: str,
    *,
    transcribe: bool,
    analyze: bool,
    force: bool,
) -> IngestedTweet | None:
    replay = _completed_tweet_replay(
        tweet,
        post_dir,
        identity,
        existing_receipt,
        source_content_hash,
        transcribe=transcribe,
        analyze=analyze,
        force=force,
    )
    if replay is not None:
        return replay
    return _migrate_legacy_completed_tweet(
        tweet,
        post_dir,
        identity,
        existing_receipt,
        source_content_hash,
        transcribe=transcribe,
        analyze=analyze,
        force=force,
    )


def _link_preview_context(tweet: TweetRecord) -> str:
    if not tweet.has_link_preview:
        return ""
    lines: list[str] = []
    if tweet.link_preview_type == "x_article":
        lines.append("- Type: X Article preview")
    elif tweet.link_preview_type == "card":
        lines.append("- Type: Card preview")
    if tweet.link_preview_title:
        lines.append(f"- Title: {tweet.link_preview_title}")
    if tweet.link_preview_description:
        lines.append(f"- Description: {tweet.link_preview_description}")
    if tweet.link_preview_domain:
        lines.append(f"- Domain: {tweet.link_preview_domain}")
    if tweet.link_preview_url:
        lines.append(f"- URL: {tweet.link_preview_url}")
    return "\n".join(lines)


def _quoted_post_context(tweet: TweetRecord) -> str:
    if not tweet.has_quoted_post:
        return ""
    lines: list[str] = []
    quoted_handle = (
        f"@{tweet.quoted_tweet_author_handle}" if tweet.quoted_tweet_author_handle else ""
    )
    if tweet.quoted_tweet_author_name and quoted_handle:
        lines.append(f"- Author: {tweet.quoted_tweet_author_name} ({quoted_handle})")
    elif tweet.quoted_tweet_author_name or quoted_handle:
        lines.append(f"- Author: {tweet.quoted_tweet_author_name or quoted_handle}")
    if tweet.quoted_tweet_id:
        lines.append(f"- Post ID: {tweet.quoted_tweet_id}")
    if tweet.quoted_tweet_url:
        lines.append(f"- Source: {tweet.quoted_tweet_url}")
    lines += [
        "",
        "Text:",
        tweet.quoted_tweet_text or "(not available in the public syndication payload)",
    ]
    return "\n".join(lines)


def _tweet_markdown(tweet: TweetRecord, transcript_text: str) -> str:
    lines = [
        f"# {tweet.author_name} ({tweet.display_handle}) - {tweet.published_iso or tweet.created_at}",
        "",
        f"Source: {tweet.url}",
        f"Likes: {tweet.like_count}  •  Replies: {tweet.reply_count}",
    ]
    if tweet.capture_status == "partial":
        lines += [
            "",
            "## Capture status",
            "",
            f"Partial: {tweet.capture_warning or 'The full source body was not captured.'}",
        ]
    lines += ["", "## Tweet", "", tweet.text or "(no text)"]
    quoted_post = _quoted_post_context(tweet)
    if quoted_post:
        lines += ["", "## Quoted Post", "", quoted_post]
    if tweet.note_text and tweet.note_text.strip() != tweet.text.strip():
        lines += ["", "## Long-form body (note_tweet)", "", tweet.note_text]
    link_preview = _link_preview_context(tweet)
    if link_preview:
        lines += [
            "",
            "## Link Preview",
            "",
            "Metadata from public syndication; this is not the full linked page.",
            "",
            link_preview,
        ]
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
        response = llm_call(
            rc,
            workload_tag="analysis",
            prompt=prompt,
            call_type="x_vocab_expand",
            usage_tracker=tracker,
        )
    except BudgetExceededError:
        raise
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
        link_preview=_link_preview_context(tweet),
        capture_status=tweet.capture_status,
        capture_warning=tweet.capture_warning,
        quoted_post=_quoted_post_context(tweet),
        transcript=transcript_text,
        media_summary=_media_summary(tweet),
    )
    response = llm_call(
        rc,
        workload_tag="analysis",
        prompt=prompt,
        call_type="x_tweet",
        usage_tracker=tracker,
    )
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
            "capture_status": tweet.capture_status,
            "capture_warning": tweet.capture_warning,
            "has_link_preview": tweet.has_link_preview,
            "quoted_post_status": tweet.quoted_tweet_status,
            "has_quoted_post": tweet.has_quoted_post,
            "quoted_post_id": tweet.quoted_tweet_id,
            "quoted_post_url": tweet.quoted_tweet_url,
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
    if outcome is not None and outcome.has_flags:
        style = "red" if outcome.refused else "yellow"
        console.print(f"        [{style}]{outcome.summary_line}[/{style}]")
    if outcome is not None and outcome.refused:
        skipped.append(outcome.summary_line)
        return None
    return write_markdown_artifact(post_dir, "insights", insights_text, identity=identity)


def _commit_completed_tweet_receipt(
    tweet_path: Path,
    insights_path: Path | None,
    transcript_path: Path | None,
    post_dir: Path,
    identity: str,
    tweet_md: str,
    tweet_frontmatter: dict[str, Any],
    source_content_hash: str,
    *,
    tweet: TweetRecord,
    transcribe: bool,
    analyze: bool,
) -> Path:
    """Commit the receipt hash after every requested artifact has landed."""
    if analyze and insights_path is None:
        return tweet_path
    if (
        not analyze
        and tweet.has_video
        and transcribe
        and (transcript_path is None or not _nonempty(transcript_path))
    ):
        return tweet_path
    completed_frontmatter = {**tweet_frontmatter, "content_hash": source_content_hash}
    return write_markdown_artifact(
        post_dir,
        "tweet",
        tweet_md,
        identity=identity,
        frontmatter=completed_frontmatter,
    )


def ingest_tweet(
    url_or_id: str,
    topic: str,
    config: DistillConfig,
    *,
    transcribe: bool = True,
    tracker: CostTracker | None = None,
    analyze: bool = True,
    force: bool = False,
) -> IngestedTweet:
    """End-to-end ingest of a single tweet.

    1. Fetch metadata via syndication.
    2. Write Tweet.md raw artifact.
    3. If video present and ``transcribe`` is true, download .mp4 and
       run Whisper, write Transcript.txt.
    4. If ``analyze`` is true, run the insight prompt and write Insights.md.
    """
    console.print("  [cyan]X[/cyan]  fetching tweet")
    tweet = fetch_tweet(url_or_id)
    source_content_hash = _tweet_source_content_hash(tweet)
    existing_receipt = _existing_tweet_receipt(config, topic, tweet.tweet_id)
    post_dir = existing_receipt.parent if existing_receipt else _x_post_dir(config, topic, tweet)
    identity = (
        _identity_from_tweet_path(
            existing_receipt,
            _tweet_identity(tweet),
        )
        if existing_receipt
        else _tweet_identity(tweet)
    )

    replay = _existing_tweet_replay(
        tweet,
        post_dir,
        identity,
        existing_receipt,
        source_content_hash,
        transcribe=transcribe,
        analyze=analyze,
        force=force,
    )
    if replay is not None:
        return replay

    post_dir.mkdir(parents=True, exist_ok=True)

    transcript_text = ""
    transcript_path: Path | None = None
    media_path: Path | None = None
    skipped: list[str] = []

    if tweet.has_video and transcribe:
        media_path = post_dir / "media.mp4"
        try:
            if is_reusable_video(media_path):
                console.print(
                    f"        reusing existing {media_path.name} "
                    f"({media_path.stat().st_size / 1_000_000:.1f} MB)"
                )
            else:
                media_path.unlink(missing_ok=True)
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
        except BudgetExceededError:
            raise
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
            "capture_status": tweet.capture_status,
            "capture_warning": tweet.capture_warning,
            "has_link_preview": tweet.has_link_preview,
            "quoted_post_status": tweet.quoted_tweet_status,
            "has_quoted_post": tweet.has_quoted_post,
            "quoted_post_id": tweet.quoted_tweet_id,
            "quoted_post_url": tweet.quoted_tweet_url,
            "content_hash": "",
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
        insights_text = apply_frontmatter(
            insights_text,
            {
                "topic": topic,
                "tags": tags_for(topic, "x"),
                "content_hash": source_content_hash,
            },
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

    # The receipt hash is the completion marker for the requested artifact set.
    # Analysis requires a matching insight hash; raw-only video capture requires
    # a transcript only when transcription was requested.
    tweet_path = _commit_completed_tweet_receipt(
        tweet_path,
        insights_path,
        transcript_path,
        post_dir,
        identity,
        tweet_md,
        tweet_frontmatter,
        source_content_hash,
        tweet=tweet,
        transcribe=transcribe,
        analyze=analyze,
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
