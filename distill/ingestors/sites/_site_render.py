# pyright: strict
"""Site-page classification and Markdown rendering."""

from __future__ import annotations

from typing import Protocol


class SitePageView(Protocol):
    url: str
    title: str
    site_name: str
    page_type: str
    text: str
    final_url: str
    canonical_url: str
    description: str
    published_at: str
    authors: list[str]
    tags: list[str]
    pdf_links: list[str]
    video_links: list[str]
    has_video: bool
    transcript: str
    attachment_context: str
    source_url: str
    depth: int


def classify_page_type(url: str, title: str, description: str, has_video: bool) -> str:
    lowered = f"{url} {title} {description}".lower()
    if "/video/" in lowered or has_video:
        return "video"
    if "/partner/" in lowered:
        return "partner"
    if "/topic/" in lowered:
        return "topic"
    if "/lab/" in lowered:
        return "lab"
    if "/research/" in lowered or "/research-and-insights/" in lowered or "/insights/" in lowered:
        return "research"
    if "/category/" in lowered:
        return "category"
    if "/overview" in lowered:
        return "overview"
    if "/explore" in lowered:
        return "explore"
    if "/ecosystem" in lowered:
        return "ecosystem"
    return "page"


def build_page_document(page: SitePageView) -> str:
    transcript_block = f"\n\n## Transcript\n{page.transcript}" if page.transcript.strip() else ""
    video_block = (
        "\n\n## Video Links\n" + "\n".join(f"- {link}" for link in page.video_links)
        if page.video_links
        else ""
    )
    pdf_block = (
        "\n\n## PDF Links\n" + "\n".join(f"- {link}" for link in page.pdf_links)
        if page.pdf_links
        else ""
    )
    attachment_block = (
        f"\n\n## Attachment Extracts\n{page.attachment_context}"
        if page.attachment_context.strip()
        else ""
    )
    return f"""# {page.title}

- URL: {page.url}
- Final URL: {page.final_url or page.url}
- Canonical URL: {page.canonical_url or page.final_url or page.url}
- Site: {page.site_name}
- Page Type: {page.page_type}
- Published: {page.published_at or "Unknown"}
- Authors: {", ".join(page.authors) or "Unknown"}
- Tags: {", ".join(page.tags) or "None"}
- Has Video: {"yes" if page.has_video else "no"}
- Discovered From: {page.source_url or page.url}
- Crawl Depth: {page.depth}

## Description
{page.description or "None"}

## Content
{page.text}{transcript_block}{video_block}{pdf_block}{attachment_block}
"""
