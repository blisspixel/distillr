from pathlib import Path

from distill.config import DistillConfig
from distill.site_attachments import (
    collect_page_attachments,
    ingest_page_attachments,
    write_attachment_manifest,
)
from distill.site_scraper import SitePage


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
        "distill.site_attachments._ingest_pdf_attachment",
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
        "distill.site_attachments._ingest_youtube_attachment",
        lambda attachment, attachments_dir, config: (
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
