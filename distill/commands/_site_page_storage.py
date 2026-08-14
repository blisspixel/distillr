# pyright: strict
"""Stable ownership records for persisted website page directories."""

from __future__ import annotations

import contextlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import cast

from distill.config import DistillConfig
from distill.ingestors.net import url_for_persistence
from distill.ingestors.sites.scraper import (
    SitePage,
    canonicalize_url,
    page_id_from_url,
    site_page_id,
)
from distill.library.confined import read_confined_text, validate_confined_path
from distill.library.locking import exclusive_file_lock, open_lock_file
from distill.library.paths import (
    artifact_candidate_paths,
    atomic_write_text,
    slugify_title,
)

_SOURCE_TYPE = "site_page"
_OWNER_FILENAME = ".source_meta.json"
_OWNER_LOCK_FILENAME = ".site-page-ownership.lock"
_OWNER_SCHEMA_VERSION = 2
_OWNER_DIGEST_DOMAIN = b"distill-site-owner-v2\0"
_OWNER_MAX_BYTES = 4_096
_LEGACY_METADATA_MAX_BYTES = 1_048_576
_ATTACHMENT_MANIFEST_MAX_BYTES = 1_048_576
_MAX_COLLISION_ATTEMPTS = 1_024
_MAX_ATTACHMENT_RECORDS = 512


@dataclass(frozen=True)
class OwnedSitePageDirectory:
    path: Path
    source_url: str
    source_id: str


def _mapping(value: object) -> Mapping[str, object] | None:
    return cast("Mapping[str, object]", value) if isinstance(value, dict) else None


def _owner_digest(source_url: str) -> str:
    return sha256(_OWNER_DIGEST_DOMAIN + source_url.encode("utf-8")).hexdigest()


def _owner_matches(
    page_dir: Path,
    pages_dir: Path,
    source_url: str,
    persisted_url: str,
    owner_digest: str,
) -> bool | None:
    """Match an owner record while the caller holds the site ownership lock."""

    owner_path = page_dir / _OWNER_FILENAME
    try:
        owner_path.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        return False
    raw = read_confined_text(owner_path, pages_dir, max_bytes=_OWNER_MAX_BYTES)
    if raw is None:
        return False
    try:
        owner = _mapping(json.loads(raw))
    except (json.JSONDecodeError, RecursionError, ValueError):
        return False
    if owner is None or owner.get("source_type") != _SOURCE_TYPE:
        return False
    if owner.get("schema_version") == _OWNER_SCHEMA_VERSION:
        return bool(
            owner.get("source_id") == persisted_url and owner.get("source_hash") == owner_digest
        )
    if owner.get("schema_version") == 1 and owner.get("source_id") == source_url:
        _write_owner(page_dir, persisted_url, owner_digest)
        return True
    return False


def _write_owner(page_dir: Path, persisted_url: str, owner_digest: str) -> None:
    owner = {
        "schema_version": _OWNER_SCHEMA_VERSION,
        "source_type": _SOURCE_TYPE,
        "source_id": persisted_url,
        "source_hash": owner_digest,
    }
    atomic_write_text(
        page_dir / _OWNER_FILENAME,
        json.dumps(owner, indent=2, sort_keys=True) + "\n",
    )


def _legacy_metadata_matches(page_dir: Path, pages_dir: Path, source_url: str) -> bool:
    raw = read_confined_text(
        page_dir / "metadata.json",
        pages_dir,
        max_bytes=_LEGACY_METADATA_MAX_BYTES,
    )
    if raw is None:
        return False
    try:
        metadata = _mapping(json.loads(raw))
    except (json.JSONDecodeError, RecursionError, ValueError):
        return False
    if metadata is None:
        return False
    landed_url = metadata.get("final_url") or metadata.get("url")
    return isinstance(landed_url, str) and canonicalize_url(landed_url) == source_url


def _safe_existing_directory(path: Path, pages_dir: Path) -> bool:
    return validate_confined_path(path, pages_dir, expect_directory=True) is not None


def _legacy_page_id(page: SitePage) -> str:
    return slugify_title(
        page.title or page.url,
        page_id_from_url(page.final_url or page.url),
        max_len=70,
    )


def _claim_legacy_directory(
    config: DistillConfig,
    topic: str,
    site_name: str,
    page: SitePage,
    pages_dir: Path,
    source_url: str,
    persisted_url: str,
    owner_digest: str,
) -> Path | None:
    legacy = config.site_page_dir(topic, site_name, page.title, _legacy_page_id(page))
    if not _safe_existing_directory(legacy, pages_dir):
        return None
    owner_match = _owner_matches(
        legacy,
        pages_dir,
        source_url,
        persisted_url,
        owner_digest,
    )
    if owner_match is True:
        return legacy
    if owner_match is False or not _legacy_metadata_matches(legacy, pages_dir, source_url):
        return None
    _write_owner(legacy, persisted_url, owner_digest)
    return legacy


def reserve_site_page_directory(
    config: DistillConfig,
    topic: str,
    site_name: str,
    page: SitePage,
) -> OwnedSitePageDirectory:
    """Atomically bind one corpus directory to the page's complete landed URL."""

    pages_dir = config.site_pages_dir(topic, site_name)
    pages_dir.mkdir(parents=True, exist_ok=True)
    source_url = canonicalize_url(page.final_url or page.url)
    persisted_url = url_for_persistence(source_url)
    if persisted_url == "<invalid-url>":
        raise ValueError("Refusing to reserve a directory for an invalid site page URL")
    allocator_id = site_page_id(source_url)
    owner_digest = _owner_digest(source_url)
    lock_path = pages_dir / _OWNER_LOCK_FILENAME
    with (
        open_lock_file(lock_path) as lock_file,
        exclusive_file_lock(
            lock_file,
            timeout_seconds=30.0,
            timeout_message=f"Timed out reserving a page directory under {pages_dir}",
        ),
    ):
        legacy = _claim_legacy_directory(
            config,
            topic,
            site_name,
            page,
            pages_dir,
            source_url,
            persisted_url,
            owner_digest,
        )
        if legacy is not None:
            return OwnedSitePageDirectory(legacy, persisted_url, owner_digest)

        for counter in range(1, _MAX_COLLISION_ATTEMPTS + 1):
            name = allocator_id if counter == 1 else f"{allocator_id}_{counter}"
            candidate = pages_dir / name
            try:
                candidate.mkdir()
            except FileExistsError:
                if _safe_existing_directory(candidate, pages_dir) and _owner_matches(
                    candidate,
                    pages_dir,
                    source_url,
                    persisted_url,
                    owner_digest,
                ):
                    return OwnedSitePageDirectory(candidate, persisted_url, owner_digest)
                continue
            try:
                _write_owner(candidate, persisted_url, owner_digest)
            except BaseException:
                with contextlib.suppress(OSError):
                    candidate.rmdir()
                raise
            return OwnedSitePageDirectory(candidate, persisted_url, owner_digest)
    raise RuntimeError(
        f"Could not allocate a collision-free page directory after {_MAX_COLLISION_ATTEMPTS} attempts"
    )


def remove_absent_transcript(page_dir: Path) -> None:
    """Remove generated transcript variants when the current owned page has none."""

    for candidate in artifact_candidate_paths(page_dir, "transcript", extension="txt"):
        if candidate.parent == page_dir:
            candidate.unlink(missing_ok=True)


def remove_absent_attachments(page_dir: Path) -> None:
    """Remove the old manifest and its generated text files when inventory is empty."""

    manifest_path = page_dir / "attachments.json"
    raw = read_confined_text(
        manifest_path,
        page_dir,
        max_bytes=_ATTACHMENT_MANIFEST_MAX_BYTES,
    )
    if raw is not None:
        try:
            value: object = json.loads(raw)
        except (json.JSONDecodeError, RecursionError, ValueError):
            value = None
        records = cast("list[object]", value) if isinstance(value, list) else []
        if len(records) <= _MAX_ATTACHMENT_RECORDS:
            for item in records:
                record = _mapping(item)
                if record is None:
                    continue
                text_path = record.get("text_path")
                if not isinstance(text_path, str) or not text_path:
                    continue
                relative = Path(text_path)
                if relative.name != text_path:
                    continue
                candidate = page_dir / "attachments" / relative
                if validate_confined_path(candidate, page_dir, expect_directory=False):
                    candidate.unlink(missing_ok=True)
    manifest_path.unlink(missing_ok=True)
