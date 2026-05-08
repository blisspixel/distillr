"""Attachment discovery and optional ingestion for website pages."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from pypdf import PdfReader

from distill.config import DistillConfig
from distill.ingestors.sites.scraper import SitePage
from distill.ingestors.youtube.transcripts import get_transcript
from distill.library.paths import slugify_title

__all__ = [
    "AttachmentRecord",
    "collect_page_attachments",
    "ingest_page_attachments",
    "write_attachment_manifest",
]

_ATTACHMENT_TEXT_LIMIT = 30_000


@dataclass
class AttachmentRecord:
    url: str
    kind: str
    provider: str = ""
    source: str = ""
    status: str = "detected"
    text_path: str = ""
    note: str = ""
    content_chars: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def collect_page_attachments(page: SitePage) -> list[AttachmentRecord]:
    attachments: list[AttachmentRecord] = []
    seen: set[tuple[str, str]] = set()

    for url in page.pdf_links:
        key = ("pdf", url)
        if key in seen:
            continue
        seen.add(key)
        attachments.append(
            AttachmentRecord(
                url=url,
                kind="pdf",
                provider=_provider_for_url(url),
                source="pdf_link",
            )
        )

    for url in page.video_links:
        provider = _provider_for_url(url)
        key = ("video", url)
        if key in seen:
            continue
        seen.add(key)
        attachments.append(
            AttachmentRecord(
                url=url,
                kind="video",
                provider=provider,
                source="video_link",
            )
        )

    return attachments


def ingest_page_attachments(
    page: SitePage,
    page_dir: Path,
    config: DistillConfig,
) -> tuple[list[AttachmentRecord], str]:
    attachments = collect_page_attachments(page)
    if not attachments:
        return [], ""

    attachments_dir = page_dir / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    context_parts: list[str] = []
    updated: list[AttachmentRecord] = []

    for attachment in attachments:
        if attachment.kind == "pdf":
            updated_attachment, context = _ingest_pdf_attachment(attachment, attachments_dir)
        elif attachment.kind == "video" and attachment.provider == "youtube":
            updated_attachment, context = _ingest_youtube_attachment(
                attachment, attachments_dir, config
            )
        else:
            updated_attachment, context = attachment, ""
            if attachment.kind == "video":
                updated_attachment.note = f"{attachment.provider or 'unknown'} video detected; transcript ingestion not supported yet"
        updated.append(updated_attachment)
        if context:
            context_parts.append(context)

    context = "\n\n".join(part for part in context_parts if part).strip()
    return updated, context


def write_attachment_manifest(page_dir: Path, attachments: list[AttachmentRecord]) -> Path | None:
    if not attachments:
        return None
    manifest_path = page_dir / "attachments.json"
    manifest_path.write_text(
        json.dumps([item.to_dict() for item in attachments], indent=2),
        encoding="utf-8",
    )
    return manifest_path


def _ingest_pdf_attachment(
    attachment: AttachmentRecord,
    attachments_dir: Path,
) -> tuple[AttachmentRecord, str]:
    try:
        response = requests.get(attachment.url, timeout=30)
        response.raise_for_status()
        reader = PdfReader(BytesIO(response.content))
        text_parts: list[str] = []
        for pdf_page in reader.pages[:10]:
            text = (pdf_page.extract_text() or "").strip()
            if text:
                text_parts.append(text)
        extracted = "\n\n".join(text_parts).strip()[:_ATTACHMENT_TEXT_LIMIT]
        if not extracted:
            attachment.status = "failed"
            attachment.note = "PDF downloaded but no extractable text was found"
            return attachment, ""
        filename = f"{slugify_title(attachment.url, max_len=40)}.txt"
        text_path = attachments_dir / filename
        text_path.write_text(extracted, encoding="utf-8")
        attachment.status = "ingested"
        attachment.text_path = str(text_path.name)
        attachment.content_chars = len(extracted)
        return attachment, f"### PDF Attachment: {attachment.url}\n{extracted}"
    except Exception as exc:
        attachment.status = "failed"
        attachment.note = str(exc)
        return attachment, ""


def _ingest_youtube_attachment(
    attachment: AttachmentRecord,
    attachments_dir: Path,
    config: DistillConfig,
) -> tuple[AttachmentRecord, str]:
    video_id = _extract_youtube_video_id(attachment.url)
    if not video_id:
        attachment.status = "failed"
        attachment.note = "Could not resolve YouTube video ID"
        return attachment, ""

    transcript_path = attachments_dir / f"{video_id}-transcript.txt"
    watch_url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        success = get_transcript(watch_url, video_id, transcript_path, config)
    except Exception as exc:
        attachment.status = "failed"
        attachment.note = str(exc)
        return attachment, ""

    if not success or not transcript_path.exists():
        attachment.status = "failed"
        attachment.note = "Transcript extraction failed"
        return attachment, ""

    transcript = transcript_path.read_text(encoding="utf-8").strip()[:_ATTACHMENT_TEXT_LIMIT]
    attachment.status = "ingested"
    attachment.text_path = str(transcript_path.name)
    attachment.content_chars = len(transcript)
    return attachment, f"### YouTube Attachment: {watch_url}\n{transcript}"


def _provider_for_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    if "vimeo.com" in host:
        return "vimeo"
    if url.lower().endswith(".pdf"):
        return "pdf"
    return host.removeprefix("www.")


def _extract_youtube_video_id(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if "youtu.be" in host:
        return parsed.path.strip("/")
    if "youtube.com" not in host:
        return ""
    query_id = parse_qs(parsed.query).get("v")
    if query_id:
        return query_id[0]
    match = re.search(r"/(?:embed|shorts)/([A-Za-z0-9_-]{6,})", parsed.path)
    if match:
        return match.group(1)
    return ""
