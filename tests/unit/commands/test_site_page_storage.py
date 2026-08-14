"""Regression tests for site page ownership and persistence."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Barrier
from types import SimpleNamespace

import pytest

from distill.commands import _site_ingest as ingest_mod
from distill.commands import _site_page_storage as storage_mod
from distill.config import DistillConfig
from distill.ingestors.sites.attachments import AttachmentRecord
from distill.ingestors.sites.scraper import (
    SitePage,
    SiteSeed,
    page_id_from_url,
    site_page_id,
)
from distill.library.paths import find_artifact, slugify_title
from distill.pipeline.costs import CostTracker
from distill.pipeline.summary import RunSummary


def _config(tmp_path) -> DistillConfig:
    return DistillConfig(distill_output_dir=tmp_path / "library")


def _page(url: str, *, title: str = "Shared Documentation Title", transcript: str = ""):
    return SitePage(
        url=url,
        final_url=url,
        canonical_url=url,
        title=title,
        site_name="shared.example",
        page_type="article",
        text=f"Content from {url}",
        transcript=transcript,
    )


def _legacy_directory(config: DistillConfig, page: SitePage):
    legacy_page_id = slugify_title(
        page.title,
        page_id_from_url(page.final_url),
        max_len=70,
    )
    return config.site_page_dir("web", "shared.example", page.title, legacy_page_id)


def test_owner_and_legacy_metadata_treat_recursive_json_as_unreadable(tmp_path):
    config = _config(tmp_path)
    pages_dir = config.site_pages_dir("web", "shared.example")
    page_dir = pages_dir / "page"
    page_dir.mkdir(parents=True)
    nested = "[" * 1200 + "]" * 1200
    (page_dir / ".source_meta.json").write_text(nested, encoding="utf-8")
    (page_dir / "metadata.json").write_text(nested, encoding="utf-8")

    assert (
        storage_mod._owner_matches(
            page_dir,
            pages_dir,
            "https://shared.example/docs/a",
            "https://shared.example/docs/a",
            "deadbeef",
        )
        is False
    )
    assert (
        storage_mod._legacy_metadata_matches(page_dir, pages_dir, "https://shared.example/docs/a")
        is False
    )


def test_site_page_id_uses_complete_canonical_url_identity():
    first = "https://shared.example/docs/abcdefgh-first"
    second = "https://shared.example/docs/abcdefgh-second"

    assert site_page_id(first) != site_page_id(second)
    assert site_page_id(first) == site_page_id(f"{first}/?utm_source=test#section")
    assert site_page_id(first) == site_page_id("HTTPS://SHARED.EXAMPLE.:443/docs/abcdefgh-first")
    assert site_page_id(f"{first}?version=1") != site_page_id(f"{first}?version=2")


def test_exact_report_collision_reserves_distinct_owned_directories(tmp_path):
    config = _config(tmp_path)
    first = _page("https://shared.example/docs/abcdefgh-first")
    second = _page("https://shared.example/docs/abcdefgh-second")

    first_owned = storage_mod.reserve_site_page_directory(config, "web", "shared.example", first)
    second_owned = storage_mod.reserve_site_page_directory(config, "web", "shared.example", second)

    assert first_owned.path != second_owned.path
    first_owner = json.loads((first_owned.path / ".source_meta.json").read_text(encoding="utf-8"))
    second_owner = json.loads((second_owned.path / ".source_meta.json").read_text(encoding="utf-8"))
    assert first_owner["schema_version"] == 2
    assert second_owner["schema_version"] == 2
    assert first_owner["source_id"] == first.final_url
    assert second_owner["source_id"] == second.final_url
    assert first_owned.source_id == first_owner["source_hash"]
    assert second_owned.source_id == second_owner["source_hash"]


def test_query_sensitive_owner_identity_never_persists_raw_url(tmp_path):
    config = _config(tmp_path)
    first_url = "https://shared.example/docs/report?version=1&token=FIRST-CANARY"
    second_url = "https://shared.example/docs/report?version=2&token=SECOND-CANARY"

    first = storage_mod.reserve_site_page_directory(
        config, "web", "shared.example", _page(first_url)
    )
    second = storage_mod.reserve_site_page_directory(
        config, "web", "shared.example", _page(second_url)
    )

    assert first.path != second.path
    assert first.source_url == second.source_url == "https://shared.example/docs/report"
    assert first.source_id != second.source_id
    expected = sha256(b"distill-site-owner-v2\0" + first_url.encode("utf-8")).hexdigest()
    assert first.source_id == expected
    owner_text = (first.path / ".source_meta.json").read_text(encoding="utf-8")
    owner_text += (second.path / ".source_meta.json").read_text(encoding="utf-8")
    assert "FIRST-CANARY" not in owner_text
    assert "SECOND-CANARY" not in owner_text


def test_same_landed_url_reuses_owned_directory_when_title_changes(tmp_path):
    config = _config(tmp_path)
    first = _page("https://shared.example/docs/agent", title="Original title")
    renamed = _page("https://shared.example/docs/agent", title="Renamed page")

    first_owned = storage_mod.reserve_site_page_directory(config, "web", "shared.example", first)
    renamed_owned = storage_mod.reserve_site_page_directory(
        config, "web", "shared.example", renamed
    )

    assert renamed_owned.path == first_owned.path


def test_full_owner_check_separates_forced_allocator_collision(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setattr(storage_mod, "site_page_id", lambda _url: "a" * 64)

    first = storage_mod.reserve_site_page_directory(
        config,
        "web",
        "shared.example",
        _page("https://shared.example/first"),
    )
    second = storage_mod.reserve_site_page_directory(
        config,
        "web",
        "shared.example",
        _page("https://shared.example/second"),
    )

    assert first.path.name == "a" * 64
    assert second.path.name == f"{'a' * 64}_2"


def test_mismatched_owner_is_never_reused_or_modified(tmp_path, monkeypatch):
    config = _config(tmp_path)
    pages_dir = config.site_pages_dir("web", "shared.example")
    pages_dir.mkdir(parents=True)
    monkeypatch.setattr(storage_mod, "site_page_id", lambda _url: "b" * 64)
    occupied = pages_dir / ("b" * 64)
    occupied.mkdir()
    (occupied / ".source_meta.json").write_text(
        json.dumps(
            {
                "source_type": "site_page",
                "source_id": "https://shared.example/another-owner",
            }
        ),
        encoding="utf-8",
    )
    sentinel = occupied / "sentinel.txt"
    sentinel.write_text("unchanged", encoding="utf-8")

    owned = storage_mod.reserve_site_page_directory(
        config,
        "web",
        "shared.example",
        _page("https://shared.example/requested-owner"),
    )

    assert owned.path.name == f"{'b' * 64}_2"
    assert sentinel.read_text(encoding="utf-8") == "unchanged"


def test_valid_legacy_directory_is_claimed_without_moving_data(tmp_path):
    config = _config(tmp_path)
    page = _page("https://shared.example/docs/legacy")
    legacy = _legacy_directory(config, page)
    legacy.mkdir(parents=True)
    (legacy / "metadata.json").write_text(
        json.dumps({"url": page.url, "final_url": page.final_url}),
        encoding="utf-8",
    )
    sentinel = legacy / "content.md"
    sentinel.write_text("legacy content", encoding="utf-8")

    owned = storage_mod.reserve_site_page_directory(config, "web", "shared.example", page)

    assert owned.path == legacy
    assert sentinel.read_text(encoding="utf-8") == "legacy content"
    assert (
        json.loads((legacy / ".source_meta.json").read_text(encoding="utf-8"))["source_id"]
        == page.final_url
    )


def test_matching_v1_owner_is_rewritten_to_sanitized_v2_under_reservation(tmp_path):
    config = _config(tmp_path)
    raw_url = "https://shared.example/docs/legacy?token=V1-CANARY"
    page = _page(raw_url)
    pages_dir = config.site_pages_dir("web", "shared.example")
    page_dir = pages_dir / site_page_id(raw_url)
    page_dir.mkdir(parents=True)
    (page_dir / ".source_meta.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_type": "site_page",
                "source_id": raw_url,
                "source_hash": site_page_id(raw_url),
            }
        ),
        encoding="utf-8",
    )

    owned = storage_mod.reserve_site_page_directory(config, "web", "shared.example", page)

    owner_text = (owned.path / ".source_meta.json").read_text(encoding="utf-8")
    owner = json.loads(owner_text)
    assert owned.path == page_dir
    assert owner["schema_version"] == 2
    assert owner["source_id"] == "https://shared.example/docs/legacy"
    assert owner["source_hash"] == owned.source_id
    assert "V1-CANARY" not in owner_text


def test_unprovable_legacy_directory_is_preserved_but_not_claimed(tmp_path):
    config = _config(tmp_path)
    page = _page("https://shared.example/docs/unprovable")
    legacy = _legacy_directory(config, page)
    legacy.mkdir(parents=True)
    sentinel = legacy / "content.md"
    sentinel.write_text("operator review required", encoding="utf-8")

    owned = storage_mod.reserve_site_page_directory(config, "web", "shared.example", page)

    assert owned.path != legacy
    assert sentinel.read_text(encoding="utf-8") == "operator review required"
    assert not (legacy / ".source_meta.json").exists()


@pytest.mark.parametrize(
    ("metadata", "owner"),
    [
        ("{malformed", None),
        (json.dumps({"final_url": "https://shared.example/different"}), None),
        (
            json.dumps({"final_url": "https://shared.example/docs/legacy-conflict"}),
            "{malformed",
        ),
        (
            json.dumps({"final_url": "https://shared.example/docs/legacy-conflict"}),
            json.dumps(
                {
                    "source_type": "site_page",
                    "source_id": "https://shared.example/different",
                }
            ),
        ),
    ],
)
def test_malformed_or_conflicting_legacy_evidence_fails_closed(tmp_path, metadata, owner):
    config = _config(tmp_path)
    page = _page("https://shared.example/docs/legacy-conflict")
    legacy = _legacy_directory(config, page)
    legacy.mkdir(parents=True)
    (legacy / "metadata.json").write_text(metadata, encoding="utf-8")
    if owner is not None:
        (legacy / ".source_meta.json").write_text(owner, encoding="utf-8")
    sentinel = legacy / "content.md"
    sentinel.write_text("preserve for review", encoding="utf-8")

    owned = storage_mod.reserve_site_page_directory(config, "web", "shared.example", page)

    assert owned.path != legacy
    assert sentinel.read_text(encoding="utf-8") == "preserve for review"


def test_concurrent_forced_collision_claims_are_atomic(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setattr(storage_mod, "site_page_id", lambda _url: "c" * 64)
    barrier = Barrier(2)

    def reserve(url: str):
        barrier.wait(timeout=5)
        return storage_mod.reserve_site_page_directory(
            config,
            "web",
            "shared.example",
            _page(url),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(reserve, "https://shared.example/first"),
            executor.submit(reserve, "https://shared.example/second"),
        ]
        owned = [future.result(timeout=10) for future in futures]

    assert {item.path.name for item in owned} == {"c" * 64, f"{'c' * 64}_2"}
    assert len({item.source_id for item in owned}) == 2


def test_absent_optional_outputs_remove_only_owned_generated_files(tmp_path):
    page_dir = tmp_path / "page"
    attachments_dir = page_dir / "attachments"
    attachments_dir.mkdir(parents=True)
    transcript = page_dir / "transcript.txt"
    transcript.write_text("stale transcript", encoding="utf-8")
    extracted = attachments_dir / "old.txt"
    extracted.write_text("stale attachment text", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("must remain", encoding="utf-8")
    (page_dir / "attachments.json").write_text(
        json.dumps(
            [
                {"text_path": "old.txt"},
                {"text_path": "../outside.txt"},
            ]
        ),
        encoding="utf-8",
    )

    storage_mod.remove_absent_transcript(page_dir)
    storage_mod.remove_absent_attachments(page_dir)

    assert not transcript.exists()
    assert not extracted.exists()
    assert not (page_dir / "attachments.json").exists()
    assert outside.read_text(encoding="utf-8") == "must remain"


def test_process_site_seed_preserves_both_colliding_sources(tmp_path, monkeypatch):
    config = _config(tmp_path)
    config.distill_verify = "off"
    first = _page(
        "https://shared.example/docs/abcdefgh-first",
        transcript="first transcript",
    )
    second = _page("https://shared.example/docs/abcdefgh-second")
    monkeypatch.setattr(ingest_mod, "crawl_site", lambda _seed: [first, second])
    monkeypatch.setattr(
        ingest_mod,
        "analyze_site_page",
        lambda page, *_args, **_kwargs: f"# Insight\n\n{page.final_url}",
    )
    monkeypatch.setattr(ingest_mod, "synthesize_site", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(ingest_mod, "resolve_intent", lambda *_args, **_kwargs: None)

    result = ingest_mod.process_site_seed(
        SiteSeed(url="https://shared.example/docs", topic="web"),
        config,
        CostTracker(),
        RunSummary(command="test"),
    )

    pages_dir = config.site_pages_dir("web", "shared.example")
    page_dirs = sorted(path for path in pages_dir.iterdir() if path.is_dir())
    assert result.analyzed_pages == 2
    assert len(page_dirs) == 2
    owners = {
        json.loads((path / ".source_meta.json").read_text(encoding="utf-8"))["source_id"]: path
        for path in page_dirs
    }
    assert set(owners) == {first.final_url, second.final_url}
    assert find_artifact(owners[first.final_url], "transcript", extension="txt").exists()
    assert not find_artifact(owners[second.final_url], "transcript", extension="txt").exists()
    for source_url, path in owners.items():
        assert source_url in find_artifact(path, "content").read_text(encoding="utf-8")
        assert source_url in find_artifact(path, "insights").read_text(encoding="utf-8")


def test_process_site_seed_sanitizes_every_post_fetch_consumer(tmp_path, monkeypatch):
    config = _config(tmp_path)
    config.distill_verify = "strict"
    seed_url = "https://seed-user:seed-pass@shared.example/docs?token=SEED-CANARY#fragment"
    page_url = (
        "https://page-user:page-pass@shared.example/docs/report"
        "?view=full&token=PAGE-CANARY#fragment"
    )
    pdf_url = "https://cdn.example/private/guide.pdf?signature=PDF-CANARY"
    video_url = "https://www.youtube.com/watch?v=abc123&token=VIDEO-LINK-CANARY"
    page = SitePage(
        url=page_url,
        final_url=page_url,
        canonical_url=page_url,
        source_url=seed_url,
        title="Privacy report",
        site_name="shared.example",
        page_type="article",
        text="Stable report content.",
        links=[f"{page_url}&next=LINK-CANARY"],
        pdf_links=[pdf_url],
        video_links=[video_url],
    )
    captured: dict[str, object] = {}

    def fake_attachments(raw_page, page_dir, _config, *, tracker):
        captured["attachment_page"] = raw_page
        attachments_dir = page_dir / "attachments"
        attachments_dir.mkdir(parents=True, exist_ok=True)
        raw_text_path = "guide-PDF-CANARY.txt"
        (attachments_dir / raw_text_path).write_text(
            "Extracted attachment content.", encoding="utf-8"
        )
        return (
            [
                AttachmentRecord(
                    url=pdf_url,
                    kind="pdf",
                    status="ingested",
                    text_path=raw_text_path,
                ),
                AttachmentRecord(url=video_url, kind="video", provider="youtube"),
            ],
            f"### PDF Attachment: {pdf_url}\nExtracted attachment content.\n\n"
            f"### YouTube Attachment: {video_url}\nVideo transcript.",
        )

    def fake_analysis(safe_page, *_args, **_kwargs):
        captured["analysis_page"] = safe_page
        return "# Safe insight"

    monkeypatch.setattr(ingest_mod, "crawl_site", lambda _seed: [page])
    monkeypatch.setattr(ingest_mod, "ingest_page_attachments", fake_attachments)
    monkeypatch.setattr(ingest_mod, "analyze_site_page", fake_analysis)
    monkeypatch.setattr(
        ingest_mod,
        "synthesize_site",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("synthesis failed")),
    )
    monkeypatch.setattr(ingest_mod, "resolve_intent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "distill.pipeline.verify.run_verify_hook",
        lambda *_args, **_kwargs: SimpleNamespace(
            report=SimpleNamespace(ok=False),
            refused=True,
            summary_line="verification refused",
        ),
    )
    summary = RunSummary(command="site-privacy")

    result = ingest_mod.process_site_seed(
        SiteSeed(
            url=seed_url,
            topic="web",
            site_name="seed-user-seed-pass@shared.example",
        ),
        config,
        CostTracker(),
        summary,
        ingest_attachments=True,
    )

    raw_attachment_page = captured["attachment_page"]
    assert isinstance(raw_attachment_page, SitePage)
    assert raw_attachment_page.final_url == page_url
    assert raw_attachment_page.pdf_links == [pdf_url]
    safe_analysis_page = captured["analysis_page"]
    assert isinstance(safe_analysis_page, SitePage)
    assert safe_analysis_page.final_url == "https://shared.example/docs/report"
    assert safe_analysis_page.source_url == "https://shared.example/docs"
    assert safe_analysis_page.pdf_links == ["https://cdn.example/private/guide.pdf"]
    assert safe_analysis_page.video_links == ["https://www.youtube.com/watch?v=abc123"]
    assert "https://www.youtube.com/watch?v=abc123" in (safe_analysis_page.attachment_context)
    assert "PDF-CANARY" not in safe_analysis_page.attachment_context

    canaries = (
        "SEED-CANARY",
        "PAGE-CANARY",
        "LINK-CANARY",
        "PDF-CANARY",
        "VIDEO-LINK-CANARY",
        "seed-pass",
        "page-pass",
    )
    persisted = []
    for path in config.library_dir.rglob("*"):
        persisted.append(str(path))
        if path.is_file():
            persisted.append(path.read_text(encoding="utf-8"))
    run_evidence = json.dumps(
        {
            "issues": [issue.to_dict() for issue in summary.issues],
            "outputs": [str(path) for path in summary.output_files],
        }
    )
    combined = "\n".join([*persisted, run_evidence])
    assert result.page_count == 1
    assert {issue.context for issue in summary.issues} == {"https://shared.example"}
    for canary in canaries:
        assert canary not in combined
