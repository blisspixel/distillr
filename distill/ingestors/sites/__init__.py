"""Sites ingestor — web scraping, crawling, and attachment extraction."""

from distill.ingestors.sites.attachments import (
    AttachmentRecord,
    collect_page_attachments,
    ingest_page_attachments,
    write_attachment_manifest,
)
from distill.ingestors.sites.scraper import (
    SiteBatch,
    SitePage,
    SiteSeed,
    build_page_document,
    canonicalize_url,
    classify_page_type,
    crawl_site,
    dedupe_urls,
    is_crawlable_url,
    is_same_section,
    load_site_batch,
    normalize_host,
    page_id_from_url,
    site_section_key,
)

__all__ = [
    "AttachmentRecord",
    "SiteBatch",
    "SitePage",
    "SiteSeed",
    "build_page_document",
    "canonicalize_url",
    "classify_page_type",
    "collect_page_attachments",
    "crawl_site",
    "dedupe_urls",
    "ingest_page_attachments",
    "is_crawlable_url",
    "is_same_section",
    "load_site_batch",
    "normalize_host",
    "page_id_from_url",
    "site_section_key",
    "write_attachment_manifest",
]
