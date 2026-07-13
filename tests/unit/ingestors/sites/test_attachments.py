from pathlib import Path

import pytest

from distill.config import DistillConfig
from distill.ingestors.sites.attachments import (
    _extract_youtube_video_id,
    _ingest_pdf_attachment,
    _ingest_youtube_attachment,
    _provider_for_url,
    collect_page_attachments,
    ingest_page_attachments,
    write_attachment_manifest,
)
from distill.ingestors.sites.scraper import SitePage


class _FakeResponse:
    def __init__(self, *, status_code=200, headers=None, chunks=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks or [b"%PDF-1.4"]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=65536):
        yield from self._chunks


def test_collect_page_attachments_builds_pdf_and_video_records():
    page = SitePage(
        url="https://example.com/page",
        title="Example",
        site_name="example.com",
        page_type="page",
        text="Body",
        pdf_links=["https://example.com/guide.pdf"],
        video_links=[
            "https://www.youtube.com/embed/abc123xyz99",
            "https://player.vimeo.com/video/123",
        ],
    )

    attachments = collect_page_attachments(page)

    assert len(attachments) == 3
    assert attachments[0].kind == "pdf"
    assert attachments[1].provider == "youtube"
    assert attachments[2].provider == "vimeo"


def test_ingest_page_attachments_extracts_pdf_and_youtube(monkeypatch, tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    page_dir = tmp_path / "page"
    page_dir.mkdir(parents=True, exist_ok=True)
    page = SitePage(
        url="https://example.com/page",
        title="Example",
        site_name="example.com",
        page_type="page",
        text="Body",
        pdf_links=["https://example.com/guide.pdf"],
        video_links=["https://www.youtube.com/embed/abc123xyz99"],
    )

    monkeypatch.setattr(
        "distill.ingestors.sites.attachments._ingest_pdf_attachment",
        lambda attachment, attachments_dir: (
            type(attachment)(
                **{
                    **attachment.to_dict(),
                    "status": "ingested",
                    "text_path": "guide.txt",
                    "content_chars": 20,
                }
            ),
            "### PDF Attachment: https://example.com/guide.pdf\nPDF body",
        ),
    )
    monkeypatch.setattr(
        "distill.ingestors.sites.attachments._ingest_youtube_attachment",
        lambda attachment, attachments_dir, config, **_kwargs: (
            type(attachment)(
                **{
                    **attachment.to_dict(),
                    "status": "ingested",
                    "text_path": "abc123xyz99-transcript.txt",
                    "content_chars": 30,
                }
            ),
            "### YouTube Attachment: https://www.youtube.com/watch?v=abc123xyz99\nTranscript body",
        ),
    )

    attachments, context = ingest_page_attachments(page, page_dir, config)
    manifest_path = write_attachment_manifest(page_dir, attachments)

    assert len(attachments) == 2
    assert "PDF body" in context
    assert "Transcript body" in context
    assert manifest_path is not None
    assert manifest_path.exists()


def test_write_attachment_manifest_skips_empty(tmp_path):
    assert write_attachment_manifest(Path(tmp_path), []) is None


def test_ingest_page_attachments_handles_empty_and_unsupported_video(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    page_dir = tmp_path / "page"
    page_dir.mkdir(parents=True, exist_ok=True)

    empty_page = SitePage(
        url="https://example.com/page",
        title="Example",
        site_name="example.com",
        page_type="page",
        text="Body",
    )
    assert ingest_page_attachments(empty_page, page_dir, config) == ([], "")

    video_page = SitePage(
        url="https://example.com/page",
        title="Example",
        site_name="example.com",
        page_type="page",
        text="Body",
        video_links=["https://player.vimeo.com/video/123"],
    )
    attachments, context = ingest_page_attachments(video_page, page_dir, config)

    assert context == ""
    assert attachments[0].status == "detected"
    assert "not supported yet" in attachments[0].note


def test_pdf_attachment_rejects_private_url_before_request(monkeypatch, tmp_path):
    attachments_dir = tmp_path / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    attachment = collect_page_attachments(
        SitePage(
            url="https://example.com/page",
            title="Example",
            site_name="example.com",
            page_type="page",
            text="Body",
            pdf_links=["http://127.0.0.1/private.pdf"],
        )
    )[0]
    calls = []

    monkeypatch.setattr(
        "distill.ingestors.sites.attachments.requests.get",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    updated, context = _ingest_pdf_attachment(attachment, attachments_dir)

    assert updated.status == "failed"
    assert "public http(s)" in updated.note
    assert context == ""
    assert calls == []


def test_pdf_attachment_revalidates_redirect_targets(monkeypatch, tmp_path):
    attachments_dir = tmp_path / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    attachment = collect_page_attachments(
        SitePage(
            url="https://example.com/page",
            title="Example",
            site_name="example.com",
            page_type="page",
            text="Body",
            pdf_links=["https://example.com/guide.pdf"],
        )
    )[0]
    calls = []

    monkeypatch.setattr(
        "distill.ingestors.sites.attachments.is_public_web_url",
        lambda url: not url.startswith("http://127.0.0.1"),
    )

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return _FakeResponse(
            status_code=302,
            headers={"Location": "http://127.0.0.1/private.pdf"},
        )

    monkeypatch.setattr("distill.ingestors.sites.attachments.requests.get", fake_get)

    updated, context = _ingest_pdf_attachment(attachment, attachments_dir)

    assert updated.status == "failed"
    assert "public http(s)" in updated.note
    assert context == ""
    assert calls == [
        (
            "https://example.com/guide.pdf",
            {
                "timeout": 30,
                "stream": True,
                "allow_redirects": False,
                "proxies": {"http": "", "https": ""},
            },
        )
    ]


def test_private_attachment_helpers_cover_failure_paths(monkeypatch, tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    attachments_dir = tmp_path / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)

    pdf_attachment = collect_page_attachments(
        SitePage(
            url="https://example.com/page",
            title="Example",
            site_name="example.com",
            page_type="page",
            text="Body",
            pdf_links=["https://example.com/guide.pdf"],
        )
    )[0]

    monkeypatch.setattr(
        "distill.ingestors.sites.attachments._download_pdf_bytes", lambda url: b"pdf"
    )
    monkeypatch.setattr(
        "distill.ingestors.sites.attachments.extract_pdf_text_bounded",
        lambda path, *, max_chars, max_pages: "",
    )
    updated_pdf, pdf_context = _ingest_pdf_attachment(pdf_attachment, attachments_dir)
    assert updated_pdf.status == "failed"
    assert pdf_context == ""

    monkeypatch.setattr(
        "distill.ingestors.sites.attachments._download_pdf_bytes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    failed_pdf, _ = _ingest_pdf_attachment(pdf_attachment, attachments_dir)
    assert failed_pdf.status == "failed"
    assert "boom" in failed_pdf.note

    video_attachment = collect_page_attachments(
        SitePage(
            url="https://example.com/page",
            title="Example",
            site_name="example.com",
            page_type="page",
            text="Body",
            video_links=["https://www.youtube.com/watch?v=abc123xyz99"],
        )
    )[0]

    assert _provider_for_url("https://youtu.be/abc123xyz99") == "youtube"
    assert _provider_for_url("https://youtube.com.evil/watch?v=abc123xyz99") == "youtube.com.evil"
    assert _provider_for_url("https://youtu.be.evil/abc123xyz99") == "youtu.be.evil"
    assert _provider_for_url("https://example.com/guide.pdf") == "pdf"
    assert _provider_for_url("https://docs.example.com/page") == "docs.example.com"
    assert _extract_youtube_video_id("https://youtu.be/abc123xyz99") == "abc123xyz99"
    assert _extract_youtube_video_id("https://www.youtube.com/shorts/abc123xyz99") == "abc123xyz99"
    assert _extract_youtube_video_id("https://youtube.com.evil/watch?v=abc123xyz99") == ""
    assert _extract_youtube_video_id("https://youtu.be.evil/abc123xyz99") == ""
    assert _extract_youtube_video_id("https://youtu.be/../../outside") == ""
    assert _extract_youtube_video_id("https://youtube.com/watch?v=../outside") == ""
    assert _extract_youtube_video_id("https://youtube.com/watch?v=abc123/extra") == ""
    assert _extract_youtube_video_id("https://example.com/video") == ""

    no_id_attachment = type(video_attachment)(
        **{**video_attachment.to_dict(), "url": "https://example.com"}
    )
    failed_video, context = _ingest_youtube_attachment(no_id_attachment, attachments_dir, config)
    assert failed_video.status == "failed"
    assert context == ""

    monkeypatch.setattr(
        "distill.ingestors.sites.attachments.get_transcript",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("bad transcript")),
    )
    with pytest.raises(RuntimeError, match="bad transcript"):
        _ingest_youtube_attachment(video_attachment, attachments_dir, config)

    monkeypatch.setattr(
        "distill.ingestors.sites.attachments.get_transcript", lambda *_args, **_kwargs: False
    )
    failed_video, _ = _ingest_youtube_attachment(video_attachment, attachments_dir, config)
    assert failed_video.status == "failed"
    assert failed_video.note == "Transcript extraction failed"


# ---------------------------------------------------------------------------
# Helpers + success-path / download-guard coverage
# ---------------------------------------------------------------------------


def _pdf_attachment(url="https://8.8.8.8/guide.pdf"):
    # A literal public IP passes the SSRF guard without any DNS resolution.
    return collect_page_attachments(
        SitePage(
            url="https://example.com/page",
            title="Example",
            site_name="example.com",
            page_type="page",
            text="Body",
            pdf_links=[url],
        )
    )[0]


def _youtube_attachment():
    return collect_page_attachments(
        SitePage(
            url="https://example.com/page",
            title="Example",
            site_name="example.com",
            page_type="page",
            text="Body",
            video_links=["https://www.youtube.com/watch?v=abc123xyz99"],
        )
    )[0]


def test_collect_deduplicates_repeated_links():
    page = SitePage(
        url="https://example.com/page",
        title="Example",
        site_name="example.com",
        page_type="page",
        text="Body",
        pdf_links=["https://example.com/a.pdf", "https://example.com/a.pdf"],
        video_links=["https://youtu.be/abc123xyz99", "https://youtu.be/abc123xyz99"],
    )
    attachments = collect_page_attachments(page)
    assert len(attachments) == 2  # one pdf + one video; duplicates dropped


def test_pdf_attachment_success_extracts_and_writes(monkeypatch, tmp_path):
    attachments_dir = tmp_path / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        "distill.ingestors.sites.attachments.requests.get",
        lambda url, **kwargs: _FakeResponse(
            status_code=200,
            headers={"Content-Type": "application/pdf"},
            chunks=[b"%PDF-1.4 data"],
        ),
    )

    def extract(path, *, max_chars, max_pages):
        assert path.read_bytes() == b"%PDF-1.4 data"
        assert (max_chars, max_pages) == (30_000, 10)
        return "Extracted text."

    monkeypatch.setattr(
        "distill.ingestors.sites.attachments.extract_pdf_text_bounded",
        extract,
    )

    updated, context = _ingest_pdf_attachment(_pdf_attachment(), attachments_dir)

    assert updated.status == "ingested"
    assert updated.content_chars == len("Extracted text.")
    assert "Extracted text." in context
    assert updated.text_path
    assert (attachments_dir / updated.text_path).read_text(encoding="utf-8") == "Extracted text."


def test_pdf_download_rejects_unexpected_content_type(monkeypatch, tmp_path):
    attachments_dir = tmp_path / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "distill.ingestors.sites.attachments.requests.get",
        lambda url, **kwargs: _FakeResponse(status_code=200, headers={"Content-Type": "text/html"}),
    )
    updated, context = _ingest_pdf_attachment(_pdf_attachment(), attachments_dir)
    assert updated.status == "failed"
    assert "content-type" in updated.note.lower()
    assert context == ""


def test_pdf_download_rejects_oversized_content_length(monkeypatch, tmp_path):
    attachments_dir = tmp_path / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "distill.ingestors.sites.attachments.requests.get",
        lambda url, **kwargs: _FakeResponse(
            status_code=200,
            headers={"Content-Type": "application/pdf", "Content-Length": str(60 * 1024 * 1024)},
        ),
    )
    updated, _ = _ingest_pdf_attachment(_pdf_attachment(), attachments_dir)
    assert updated.status == "failed"
    assert "size cap" in updated.note


@pytest.mark.parametrize("declared", ["\u00b2", "\u0661\u0662", "9" * 5000])
def test_pdf_download_ignores_invalid_content_length(monkeypatch, tmp_path, declared):
    attachments_dir = tmp_path / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "distill.ingestors.sites.attachments.requests.get",
        lambda url, **kwargs: _FakeResponse(
            status_code=200,
            headers={"Content-Type": "application/pdf", "Content-Length": declared},
            chunks=[b"%PDF-1.4 data"],
        ),
    )
    monkeypatch.setattr(
        "distill.ingestors.sites.attachments.extract_pdf_text_bounded",
        lambda path, *, max_chars, max_pages: "Extracted text.",
    )

    updated, context = _ingest_pdf_attachment(_pdf_attachment(), attachments_dir)

    assert updated.status == "ingested"
    assert "Extracted text." in context


def test_pdf_download_enforces_streaming_size_cap(monkeypatch, tmp_path):
    attachments_dir = tmp_path / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("distill.ingestors.sites.attachments._PDF_DOWNLOAD_CAP_BYTES", 10)
    monkeypatch.setattr(
        "distill.ingestors.sites.attachments.requests.get",
        lambda url, **kwargs: _FakeResponse(
            status_code=200,
            headers={"Content-Type": "application/pdf"},
            chunks=[b"x" * 20],  # exceeds the 10-byte cap mid-stream
        ),
    )
    updated, _ = _ingest_pdf_attachment(_pdf_attachment(), attachments_dir)
    assert updated.status == "failed"
    assert "size cap" in updated.note


def test_pdf_download_redirect_missing_location_fails(monkeypatch, tmp_path):
    attachments_dir = tmp_path / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "distill.ingestors.sites.attachments.requests.get",
        lambda url, **kwargs: _FakeResponse(status_code=302, headers={}),
    )
    updated, _ = _ingest_pdf_attachment(_pdf_attachment(), attachments_dir)
    assert updated.status == "failed"
    assert "Location" in updated.note


def test_pdf_download_redirect_limit_exceeded(monkeypatch, tmp_path):
    attachments_dir = tmp_path / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "distill.ingestors.sites.attachments.requests.get",
        lambda url, **kwargs: _FakeResponse(
            status_code=302, headers={"Location": "https://8.8.8.8/next.pdf"}
        ),
    )
    updated, _ = _ingest_pdf_attachment(_pdf_attachment(), attachments_dir)
    assert updated.status == "failed"
    assert "redirect limit" in updated.note


def test_youtube_attachment_success(monkeypatch, tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    attachments_dir = tmp_path / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)

    seen = {}

    def fake_get_transcript(watch_url, video_id, transcript_path, config, *, tracker=None):
        seen["tracker"] = tracker
        transcript_path.write_text("Transcript content.", encoding="utf-8")
        return True

    monkeypatch.setattr("distill.ingestors.sites.attachments.get_transcript", fake_get_transcript)
    tracker = object()
    updated, context = _ingest_youtube_attachment(
        _youtube_attachment(), attachments_dir, config, tracker=tracker
    )

    assert updated.status == "ingested"
    assert updated.content_chars == len("Transcript content.")
    assert "Transcript content." in context
    assert updated.text_path == "abc123xyz99-transcript.txt"
    assert seen["tracker"] is tracker


def test_extract_youtube_id_returns_empty_for_youtube_without_id():
    assert _extract_youtube_video_id("https://www.youtube.com/feed/subscriptions") == ""


def test_pdf_download_skips_empty_chunks_and_reports_no_text(monkeypatch, tmp_path):
    attachments_dir = tmp_path / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "distill.ingestors.sites.attachments.requests.get",
        lambda url, **kwargs: _FakeResponse(
            status_code=200,
            headers={"Content-Type": "application/pdf"},
            chunks=[b"", b"%PDF data"],  # the empty chunk is skipped by the streamer
        ),
    )

    monkeypatch.setattr(
        "distill.ingestors.sites.attachments.extract_pdf_text_bounded",
        lambda path, *, max_chars, max_pages: "",
    )
    updated, context = _ingest_pdf_attachment(_pdf_attachment(), attachments_dir)

    assert updated.status == "failed"
    assert "no extractable text" in updated.note
    assert context == ""
