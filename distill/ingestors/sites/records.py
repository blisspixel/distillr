"""Site ingest record types.

``SitePage``, ``SiteSeed``, and ``SiteBatch`` are shared by the crawler, the
batch manifest parser, and the browser worker boundary, so they live below all
three rather than inside any one of them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from distill.ingestors.sites._site_urls import (
    MAX_SITE_CRAWL_DEPTH,
    MAX_SITE_CRAWL_PAGES,
    site_page_id,
    site_section_key,
)
from distill.ingestors.sites._site_urls import (
    normalized_crawl_prefix as _normalize_crawl_prefix,
)
from distill.ingestors.sites._site_urls import (
    validated_crawl_limit as _validated_crawl_limit,
)
from distill.library.paths import site_name_from_url

__all__ = ["SiteBatch", "SitePage", "SiteSeed"]


@dataclass
class SitePage:
    url: str
    title: str
    site_name: str
    page_type: str
    text: str
    final_url: str = ""
    canonical_url: str = ""
    description: str = ""
    published_at: str = ""
    authors: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    pdf_links: list[str] = field(default_factory=list)
    video_links: list[str] = field(default_factory=list)
    has_video: bool = False
    transcript: str = ""
    attachment_context: str = ""
    truncation_reasons: list[str] = field(default_factory=list)
    source_url: str = ""
    depth: int = 0

    @property
    def page_id(self) -> str:
        return site_page_id(self.final_url or self.url)

    def metadata(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "final_url": self.final_url or self.url,
            "canonical_url": self.canonical_url or self.final_url or self.url,
            "title": self.title,
            "site_name": self.site_name,
            "page_type": self.page_type,
            "section": site_section_key(self.final_url or self.url),
            "description": self.description,
            "published_at": self.published_at,
            "authors": self.authors,
            "tags": self.tags,
            "links": self.links,
            "pdf_links": self.pdf_links,
            "video_links": self.video_links,
            "has_video": self.has_video,
            "has_transcript": bool(self.transcript.strip()),
            "has_attachment_context": bool(self.attachment_context.strip()),
            "extraction_truncated": bool(self.truncation_reasons),
            "truncation_reasons": self.truncation_reasons,
            "source_url": self.source_url,
            "depth": self.depth,
        }


@dataclass
class SiteSeed:
    url: str
    topic: str
    site_name: str = ""
    label: str = ""
    section_label: str = ""
    source_hint: str = ""
    freshness_hint: str = ""
    crawl_prefix: str = ""
    discover_crawl: bool = False
    max_depth: int = 1
    max_pages: int = 8
    same_section_only: bool = False

    def __post_init__(self) -> None:
        self.crawl_prefix = _normalize_crawl_prefix(self.crawl_prefix)
        self.max_depth = _validated_crawl_limit(
            "max_depth",
            self.max_depth,
            minimum=0,
            maximum=MAX_SITE_CRAWL_DEPTH,
        )
        self.max_pages = _validated_crawl_limit(
            "max_pages",
            self.max_pages,
            minimum=1,
            maximum=MAX_SITE_CRAWL_PAGES,
        )

    def resolved_site_name(self) -> str:
        return self.site_name or site_name_from_url(self.url)


@dataclass
class SiteBatch:
    topic: str
    seeds: list[SiteSeed]
