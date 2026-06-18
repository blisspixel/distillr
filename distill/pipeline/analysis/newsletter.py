"""Newsletter (Substack-class) ingest orchestration.

The same RSS capture path as podcasts -- one feed parser, one hardened
fetcher -- routed by what the items actually carry: enclosures mean episodes,
full-text ``content:encoded`` bodies mean posts. Substack and most newsletter
platforms publish complete post HTML in the feed, so capture needs no page
scraping at all: reduce the HTML to text, write the ``_Content.md`` receipt,
analyze with the page-insight prompt, verify-gate the insight against the
receipt.
"""

from __future__ import annotations

import hashlib
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from distill._console import console
from distill.config import DistillConfig
from distill.ingestors.local import html_to_text
from distill.ingestors.podcasts import PodcastFeed, fetch_feed
from distill.library.paths import (
    ProvenanceFields,
    artifact_path,
    base_frontmatter,
    slugify_title,
    tags_for,
    write_markdown_artifact,
)
from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.registry import PROMPT_IDS
from distill.prompts.synthesis import site_page_insight_prompt

__all__ = ["NewsletterIngestResult", "feed_is_newsletter", "ingest_newsletter"]

PROMPT_ID = PROMPT_IDS["analysis.newsletter"]


def _short_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def feed_is_newsletter(feed: PodcastFeed) -> bool:
    """Route by what the items substantively carry.

    Substantial ``content:encoded`` bodies mean newsletter-first **even when
    audio enclosures exist** -- Substack attaches narration MP3s to text
    posts, and the text is the substance (caught in live validation: a
    narrated Substack mis-routed to the podcast path and tried to transcribe
    its own narration). A feed with audio but no real post bodies is a
    podcast; show-notes HTML is short, full posts are not.
    """
    sample = feed.episodes[:5]
    if not sample:
        return False
    substantial_bodies = sum(1 for item in sample if len(item.content_html) > 1000)
    if substantial_bodies >= max(1, len(sample) // 2):
        return True
    has_audio = any(item.audio_url for item in sample)
    has_body = any(item.content_html or item.description for item in sample)
    return has_body and not has_audio


@dataclass(slots=True)
class NewsletterIngestResult:
    """Artifacts and notes from ingesting one feed's post(s)."""

    feed_title: str
    content_paths: list[Path] = field(default_factory=list)
    insight_paths: list[Path] = field(default_factory=list)
    skipped_reasons: list[str] = field(default_factory=list)


def ingest_newsletter(
    feed_url: str,
    *,
    topic: str,
    config: DistillConfig,
    posts: int = 1,
    analyze: bool = True,
    tracker: CostTracker | None = None,
    feed: PodcastFeed | None = None,
) -> NewsletterIngestResult:
    """Ingest the latest *posts* of a newsletter RSS feed into *topic*."""
    if feed is None:
        feed = fetch_feed(feed_url)
    result = NewsletterIngestResult(feed_title=feed.title or feed_url)
    if not feed.episodes:
        result.skipped_reasons.append("Feed parsed but contains no posts.")
        return result

    host = urllib.parse.urlparse(feed_url).netloc.removeprefix("www.")
    feed_slug = slugify_title(feed.title or feed_url, source_id=host or _short_id(feed_url))
    for post in feed.episodes[: max(1, posts)]:
        post_sid = (
            post.guid
            if not post.guid.lower().startswith(("http://", "https://"))
            else _short_id(post.guid)
        )
        post_slug = slugify_title(post.title, source_id=post_sid)
        post_dir = config.topic_dir(topic) / "newsletters" / feed_slug / post_slug
        console.print(f"  [dim]{post.title}[/dim]")

        body = html_to_text(post.content_html) if post.content_html else post.description
        if not body.strip():
            result.skipped_reasons.append(f"{post.title}: feed item carries no post body")
            continue

        content_md = "\n".join(
            [
                f"# {post.title}",
                "",
                f"From **{feed.title}** -- published {post.published or 'unknown date'}.",
                "",
                body,
                "",
            ]
        )
        frontmatter = base_frontmatter(
            artifact_type="content",
            title=post.title,
            topic=topic,
            source="newsletter",
            source_id=post.guid,
            url=post.link or feed.link,
            date=post.published,
            tags=tags_for(topic, "newsletter"),
            extra={"publication": feed.title},
        )
        content_path = write_markdown_artifact(
            post_dir, "content", content_md, identity=post_slug, frontmatter=frontmatter
        )
        result.content_paths.append(content_path)

        if not analyze:
            continue

        rc = RouterConfig()
        response = llm_call(
            rc,
            workload_tag="site",
            prompt=site_page_insight_prompt(
                post.title, post.link or feed.link, feed.title, "newsletter", body
            ),
            call_type="newsletter_analysis",
        )
        if tracker is not None:
            tracker.record(TokenUsage.from_response(response, call_type="newsletter_analysis"))

        # Write-time verify hook: the receipt is the captured post body.
        from distill.pipeline.verify import resolve_verify_mode, run_verify_hook

        outcome = run_verify_hook(
            post_dir,
            response.text,
            content_md,
            mode=resolve_verify_mode(config.distill_verify),
            identity=post_slug,
            insight_name=artifact_path(post_dir, "insights", identity=post_slug).name,
            source_name=content_path.name,
        )
        if outcome is not None and not outcome.report.ok:
            style = "red" if outcome.refused else "yellow"
            console.print(f"  [{style}]{outcome.summary_line}[/{style}]")
        if outcome is not None and outcome.refused:
            result.skipped_reasons.append(outcome.summary_line)
            continue

        insight_path = write_markdown_artifact(
            post_dir,
            "insights",
            response.text,
            identity=post_slug,
            frontmatter=base_frontmatter(
                artifact_type="insights",
                title=post.title,
                topic=topic,
                source="newsletter",
                source_id=post.guid,
                url=post.link or feed.link,
                date=post.published,
                tags=tags_for(topic, "newsletter"),
                synthesis_scope="single-source",
                extra={"publication": feed.title},
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
