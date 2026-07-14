"""Regression tests for collision-resistant site page persistence."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from distill.commands import _site_ingest as ingest_mod
from distill.commands import _site_page_storage as storage_mod
from distill.config import DistillConfig
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
    assert first_owned.source_id == first.page_id
    assert second_owned.source_id == second.page_id
    assert (
        json.loads((first_owned.path / ".source_meta.json").read_text(encoding="utf-8"))[
            "source_id"
        ]
        == first.final_url
    )
    assert (
        json.loads((second_owned.path / ".source_meta.json").read_text(encoding="utf-8"))[
            "source_id"
        ]
        == second.final_url
    )


def test_same_landed_url_reuses_owned_directory_when_title_changes(tmp_path):
    config = _config(tmp_path)
    first = _page("https://shared.example/docs/agent", title="Original title")
    renamed = _page("https://shared.example/docs/agent", title="Renamed page")

    first_owned = storage_mod.reserve_site_page_directory(config, "web", "shared.example", first)
    renamed_owned = storage_mod.reserve_site_page_directory(
        config, "web", "shared.example", renamed
    )

    assert renamed_owned.path == first_owned.path


def test_full_owner_check_separates_forced_digest_collision(tmp_path, monkeypatch):
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
    assert len({item.source_url for item in owned}) == 2


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
