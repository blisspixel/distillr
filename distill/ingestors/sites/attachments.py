"""Attachment discovery and optional ingestion for website pages."""

from __future__ import annotations

import json
import re
import tempfile
import time
import urllib.request
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, urlparse

from distill.config import DistillConfig
from distill.ingestors.local.extract import extract_pdf_text_bounded
from distill.ingestors.net import NetworkError, is_public_web_url, safe_urlopen
from distill.ingestors.sites.scraper import SitePage
from distill.ingestors.youtube.transcripts import get_transcript
from distill.library.paths import slugify_title
from distill.parsing import parse_ascii_uint

__all__ = [
    "AttachmentRecord",
    "collect_page_attachments",
    "ingest_page_attachments",
    "write_attachment_manifest",
]

_ATTACHMENT_TEXT_LIMIT = 30_000
# Cap the on-the-wire download size before any parsing happens. PDFs in the
# wild are well under 50 MB; a much larger response either points at the
# wrong resource or is a slow-loris/DoS attempt. Streaming + this cap also
# prevents an internal SSRF target from returning an unbounded body that
# would otherwise be fully read into memory by ``response.content``.
_PDF_DOWNLOAD_CAP_BYTES = 50 * 1024 * 1024
_PDF_BATCH_DOWNLOAD_CAP_BYTES = 75 * 1024 * 1024
_PDF_TRANSFER_TIMEOUT_SECONDS = 30.0
_PDF_BATCH_TIMEOUT_SECONDS = 90.0
_MAX_PDF_ATTACHMENTS_PER_PAGE = 8
_MAX_VIDEO_ATTACHMENTS_PER_PAGE = 8


class _TranscriptionCostTracker(Protocol):
    def authorize_transcription(
        self, provider: str, duration_s: float, *, model: str = ""
    ) -> None: ...

    def record_transcription(
        self,
        provider: str,
        duration_s: float,
        *,
        model: str = "",
        outcome: str = "completed",
    ) -> None: ...


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
    pdf_count = 0
    video_count = 0

    for url in page.pdf_links:
        if pdf_count >= _MAX_PDF_ATTACHMENTS_PER_PAGE:
            break
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
        pdf_count += 1

    for url in page.video_links:
        if video_count >= _MAX_VIDEO_ATTACHMENTS_PER_PAGE:
            break
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
        video_count += 1

    return attachments


def ingest_page_attachments(
    page: SitePage,
    page_dir: Path,
    config: DistillConfig,
    *,
    tracker: _TranscriptionCostTracker | None = None,
) -> tuple[list[AttachmentRecord], str]:
    attachments = collect_page_attachments(page)
    if not attachments:
        return [], ""

    attachments_dir = page_dir / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    context_parts: list[str] = []
    updated: list[AttachmentRecord] = []
    pdf_budget = _AttachmentBatchBudget()

    for attachment in attachments:
        if attachment.kind == "pdf":
            updated_attachment, context = _ingest_pdf_attachment(
                attachment,
                attachments_dir,
                budget=pdf_budget,
            )
        elif attachment.kind == "video" and attachment.provider == "youtube":
            updated_attachment, context = _ingest_youtube_attachment(
                attachment, attachments_dir, config, tracker=tracker
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


class _AttachmentFetchError(Exception):
    """Internal: signals a fetch-time failure with a human-readable note."""

    def __init__(self, note: str) -> None:
        super().__init__(note)
        self.note = note


@dataclass
class _AttachmentBatchBudget:
    """Aggregate PDF count, bytes, and elapsed time for one crawled page."""

    timeout_seconds: float = _PDF_BATCH_TIMEOUT_SECONDS
    byte_limit: int = _PDF_BATCH_DOWNLOAD_CAP_BYTES
    max_pdfs: int = _MAX_PDF_ATTACHMENTS_PER_PAGE
    started_at: float = 0.0
    pdfs_started: int = 0
    bytes_consumed: int = 0

    def __post_init__(self) -> None:
        if self.started_at == 0.0:
            self.started_at = time.monotonic()

    def remaining_seconds(self) -> float:
        remaining = self.timeout_seconds - (time.monotonic() - self.started_at)
        if remaining <= 0:
            raise _AttachmentFetchError("PDF attachment batch deadline exceeded")
        return remaining

    def start_pdf(self) -> None:
        self.remaining_seconds()
        if self.pdfs_started >= self.max_pdfs:
            raise _AttachmentFetchError("PDF attachment count limit exceeded")
        self.pdfs_started += 1

    def consume_bytes(self, amount: int) -> None:
        self.remaining_seconds()
        if amount > self.byte_limit - self.bytes_consumed:
            raise _AttachmentFetchError("PDF attachment batch byte limit exceeded")
        self.bytes_consumed += amount


def _download_pdf_bytes(
    url: str,
    *,
    budget: _AttachmentBatchBudget | None = None,
) -> bytes:
    """Stream a PDF response with content-type and size guards.

    Raises ``_AttachmentFetchError`` if the response is the wrong content
    type or exceeds the configured size cap; the caller turns that into an
    ``attachment.status = "failed"`` record.
    """
    batch = budget or _AttachmentBatchBudget(max_pdfs=1)
    batch.start_pdf()
    timeout = min(_PDF_TRANSFER_TIMEOUT_SECONDS, batch.remaining_seconds())
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/pdf, application/octet-stream;q=0.8",
            "Accept-Encoding": "identity",
            "User-Agent": "distillr",
        },
    )
    try:
        with safe_urlopen(request, timeout=timeout, retries=1) as response:
            content_encoding = (response.headers.get("Content-Encoding") or "").strip().lower()
            if content_encoding not in {"", "identity"}:
                raise _AttachmentFetchError(f"Unexpected content-encoding: {content_encoding}")
            content_type = (
                (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            )
            if content_type and content_type not in {
                "application/pdf",
                "application/octet-stream",
            }:
                raise _AttachmentFetchError(f"Unexpected content-type: {content_type}")
            declared = response.headers.get("Content-Length")
            declared_size = parse_ascii_uint(declared or "")
            if declared_size is not None and declared_size > _PDF_DOWNLOAD_CAP_BYTES:
                raise _AttachmentFetchError("PDF exceeds size cap")
            if (
                declared_size is not None
                and declared_size > batch.byte_limit - batch.bytes_consumed
            ):
                raise _AttachmentFetchError("PDF attachment batch byte limit exceeded")
            buf = BytesIO()
            total = 0
            while True:
                chunk = response.read(min(64 * 1024, _PDF_DOWNLOAD_CAP_BYTES - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > _PDF_DOWNLOAD_CAP_BYTES:
                    raise _AttachmentFetchError("PDF exceeds size cap")
                batch.consume_bytes(len(chunk))
                buf.write(chunk)
            return buf.getvalue()
    except NetworkError as exc:
        raise _AttachmentFetchError(f"PDF fetch failed: {exc}") from exc


def _ingest_pdf_attachment(
    attachment: AttachmentRecord,
    attachments_dir: Path,
    *,
    budget: _AttachmentBatchBudget | None = None,
) -> tuple[AttachmentRecord, str]:
    # SSRF guard: refuse to fetch attachments that point at the local browser
    # host, RFC1918 networks, or cloud metadata endpoints. Without this, a
    # malicious page can embed a ``href="http://169.254.169.254/.../pdf"``
    # link and have the crawler exfiltrate internal responses through the
    # downstream LLM prompt.
    if urlparse(attachment.url).scheme.lower() != "https" or not is_public_web_url(attachment.url):
        attachment.status = "failed"
        attachment.note = "PDF URL is not a public HTTPS resource"
        return attachment, ""
    try:
        data = _download_pdf_bytes(attachment.url, budget=budget)
        with tempfile.TemporaryDirectory(prefix="distill-attachment-pdf-") as temp_dir:
            pdf_path = Path(temp_dir) / "attachment.pdf"
            pdf_path.write_bytes(data)
            parse_timeout = (
                _PDF_TRANSFER_TIMEOUT_SECONDS
                if budget is None
                else min(_PDF_TRANSFER_TIMEOUT_SECONDS, budget.remaining_seconds())
            )
            extracted = extract_pdf_text_bounded(
                pdf_path,
                max_chars=_ATTACHMENT_TEXT_LIMIT,
                max_pages=10,
                timeout_seconds=parse_timeout,
            ).strip()
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
    except _AttachmentFetchError as exc:
        attachment.status = "failed"
        attachment.note = exc.note
        return attachment, ""
    except Exception as exc:
        attachment.status = "failed"
        attachment.note = str(exc)
        return attachment, ""


def _ingest_youtube_attachment(
    attachment: AttachmentRecord,
    attachments_dir: Path,
    config: DistillConfig,
    *,
    tracker: _TranscriptionCostTracker | None = None,
) -> tuple[AttachmentRecord, str]:
    video_id = _extract_youtube_video_id(attachment.url)
    if not video_id:
        attachment.status = "failed"
        attachment.note = "Could not resolve YouTube video ID"
        return attachment, ""

    transcript_path = attachments_dir / f"{video_id}-transcript.txt"
    watch_url = f"https://www.youtube.com/watch?v={video_id}"
    success = get_transcript(
        watch_url,
        video_id,
        transcript_path,
        config,
        tracker=tracker,
    )

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
    host = (urlparse(url).hostname or "").lower()
    if _host_matches(host, "youtube.com") or _host_matches(host, "youtu.be"):
        return "youtube"
    if _host_matches(host, "vimeo.com"):
        return "vimeo"
    if url.lower().endswith(".pdf"):
        return "pdf"
    return host.removeprefix("www.")


def _extract_youtube_video_id(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if _host_matches(host, "youtu.be"):
        return _validated_youtube_video_id(parsed.path.strip("/"))
    if not _host_matches(host, "youtube.com"):
        return ""
    for query_id in parse_qs(parsed.query).get("v", []):
        if validated := _validated_youtube_video_id(query_id):
            return validated
    match = re.search(r"/(?:embed|shorts)/([A-Za-z0-9_-]{6,})", parsed.path)
    if match:
        return _validated_youtube_video_id(match.group(1))
    return ""


def _validated_youtube_video_id(candidate: str) -> str:
    return candidate if re.fullmatch(r"[A-Za-z0-9_-]{6,64}", candidate) else ""


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")
