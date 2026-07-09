"""Persist a previewed ``discover`` shortlist for exact-set replay.

A ``discover --preview`` run writes its goal-ranked shortlist here under a
content-addressed id; ``discover --from-preview <id>`` reloads it and ingests the
*exact* same set, skipping query-generation and the (non-deterministic) LLM
rerank. This is the honest answer to "the previewed order is a judgment call, let
me commit to the set I just saw" — temperature=0 (shipped 0.8.12) makes a re-rank
reproducible, but replay guarantees it.

Pure functions, filesystem IO only, with an injected ``now_iso`` timestamp so the
save path is deterministic under test.
"""

# pyright: strict

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, cast

from distill.ingestors.papers.arxiv import PaperRecord
from distill.ingestors.sites.scraper import SiteSeed
from distill.ingestors.youtube.discovery import VideoInfo
from distill.pipeline.discovery import RankedDiscoverItem

__all__ = [
    "PreviewCacheError",
    "PreviewSnapshot",
    "list_previews",
    "load_preview",
    "preview_cache_dir",
    "save_preview",
]

PREVIEW_CACHE_DIRNAME = ".preview_cache"
_SCHEMA_VERSION = 1
_ID_RE = re.compile(r"^[0-9a-f]{6,}$")


class PreviewCacheError(Exception):
    """Raised when a requested preview snapshot is missing or unreadable."""


@dataclass(frozen=True)
class PreviewSnapshot:
    """A previewed shortlist plus the context needed to replay it verbatim."""

    id: str
    goal: str
    model: str
    rigor: str
    created_at: str
    estimate: dict[str, Any]
    items: list[RankedDiscoverItem] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] -- default_factory=list reads as list[Unknown] under strict; the annotation is the real element type


def preview_cache_dir(library_dir: Path) -> Path:
    """Resolve the per-library preview-cache directory (hidden dotfolder)."""
    return library_dir / PREVIEW_CACHE_DIRNAME


def compute_preview_id(goal: str, model: str, rigor: str, identifiers: list[str]) -> str:
    """Content-address a previewed set by its goal, model, rigor, and members.

    The same goal + rerank settings over the same candidate set yields the same
    id, so the id is honest that it names *a selection*, not a random handle.
    """
    payload = "\n".join([goal.strip(), model.strip(), rigor.strip(), *sorted(identifiers)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:10]


def _item_to_dict(item: RankedDiscoverItem) -> dict[str, Any]:
    return {
        "kind": item.kind,
        "identifier": item.identifier,
        "title": item.title,
        "subtitle": item.subtitle,
        "date": item.date,
        "final_score": item.final_score,
        "goal_fit": item.goal_fit,
        "depth_score": item.depth_score,
        "complementarity_score": item.complementarity_score,
        "rationale": item.rationale,
        "paper": asdict(item.paper) if item.paper is not None else None,
        "video": asdict(item.video) if item.video is not None else None,
        "site_seed": asdict(item.site_seed) if item.site_seed is not None else None,
    }


def _item_from_dict(d: dict[str, Any]) -> RankedDiscoverItem:
    paper = _optional_object_or_none(d, "paper")
    video = _optional_object_or_none(d, "video")
    site = _optional_object_or_none(d, "site_seed")
    return RankedDiscoverItem(
        kind=_required_text(d, "kind"),
        identifier=_required_text(d, "identifier"),
        title=_required_text(d, "title"),
        subtitle=_required_text(d, "subtitle"),
        date=_required_text(d, "date"),
        final_score=_required_float(d, "final_score"),
        goal_fit=_required_float(d, "goal_fit"),
        depth_score=_required_float(d, "depth_score"),
        complementarity_score=_required_float(d, "complementarity_score"),
        rationale=_required_text(d, "rationale"),
        paper=_paper_from_payload(paper),
        video=_video_from_payload(video),
        site_seed=_site_seed_from_payload(site),
    )


def _load_json_object(path: Path) -> dict[str, Any]:
    payload: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected object, got {type(payload).__name__}")
    return cast("dict[str, Any]", payload)


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    return value


def _optional_text(payload: dict[str, Any], key: str, default: str = "") -> str:
    value = payload.get(key, default)
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    return value


def _optional_text_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key, [])
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list of strings")
    items = cast("list[object]", value)
    if not all(isinstance(item, str) for item in items):
        raise TypeError(f"{key} must be a list of strings")
    return cast("list[str]", items)


def _required_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value


def _optional_int(payload: dict[str, Any], key: str, default: int = 0) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value


def _required_float(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{key} must be a number")
    return float(value)


def _optional_bool(payload: dict[str, Any], key: str, default: bool = False) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise TypeError(f"{key} must be a boolean")
    return value


def _optional_object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key, {})
    if not isinstance(value, dict):
        raise TypeError(f"{key} must be an object")
    return cast("dict[str, Any]", value)


def _optional_object_or_none(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError(f"{key} must be an object or null")
    return cast("dict[str, Any]", value)


def _paper_from_payload(payload: dict[str, Any] | None) -> PaperRecord | None:
    if payload is None:
        return None
    return PaperRecord(
        paper_id=_required_text(payload, "paper_id"),
        title=_required_text(payload, "title"),
        abstract=_required_text(payload, "abstract"),
        authors=_optional_text_list(payload, "authors"),
        published_at=_optional_text(payload, "published_at"),
        updated_at=_optional_text(payload, "updated_at"),
        categories=_optional_text_list(payload, "categories"),
        doi=_optional_text(payload, "doi"),
        abs_url=_optional_text(payload, "abs_url"),
        pdf_url=_optional_text(payload, "pdf_url"),
        source=_optional_text(payload, "source", "arxiv"),
    )


def _video_from_payload(payload: dict[str, Any] | None) -> VideoInfo | None:
    if payload is None:
        return None
    return VideoInfo(
        video_id=_required_text(payload, "video_id"),
        title=_required_text(payload, "title"),
        upload_date=_required_text(payload, "upload_date"),
        duration=_required_int(payload, "duration"),
        url=_required_text(payload, "url"),
        channel_name=_optional_text(payload, "channel_name"),
        channel_url=_optional_text(payload, "channel_url"),
        description=_optional_text(payload, "description"),
        view_count=_optional_int(payload, "view_count"),
        like_count=_optional_int(payload, "like_count"),
        comment_count=_optional_int(payload, "comment_count"),
        published_at=_optional_text(payload, "published_at"),
    )


def _site_seed_from_payload(payload: dict[str, Any] | None) -> SiteSeed | None:
    if payload is None:
        return None
    return SiteSeed(
        url=_required_text(payload, "url"),
        topic=_required_text(payload, "topic"),
        site_name=_optional_text(payload, "site_name"),
        label=_optional_text(payload, "label"),
        section_label=_optional_text(payload, "section_label"),
        source_hint=_optional_text(payload, "source_hint"),
        freshness_hint=_optional_text(payload, "freshness_hint"),
        crawl_prefix=_optional_text(payload, "crawl_prefix"),
        discover_crawl=_optional_bool(payload, "discover_crawl"),
        max_depth=_optional_int(payload, "max_depth", 1),
        max_pages=_optional_int(payload, "max_pages", 8),
        same_section_only=_optional_bool(payload, "same_section_only"),
    )


def _items_from_payload(payload: dict[str, Any]) -> list[RankedDiscoverItem]:
    raw_items = payload.get("items", [])
    if not isinstance(raw_items, list):
        raise TypeError("items must be a list")
    items: list[RankedDiscoverItem] = []
    for raw_item in cast("list[object]", raw_items):
        if not isinstance(raw_item, dict):
            raise TypeError("items must contain objects")
        items.append(_item_from_dict(cast("dict[str, Any]", raw_item)))
    return items


def _snapshot_from_payload(payload: dict[str, Any], expected_id: str) -> PreviewSnapshot:
    snapshot_id = _required_text(payload, "id")
    if snapshot_id != expected_id:
        raise TypeError("id must match the requested preview id")
    return PreviewSnapshot(
        id=snapshot_id,
        goal=_optional_text(payload, "goal"),
        model=_optional_text(payload, "model"),
        rigor=_optional_text(payload, "rigor"),
        created_at=_optional_text(payload, "created_at"),
        estimate=_optional_object(payload, "estimate"),
        items=_items_from_payload(payload),
    )


def save_preview(
    cache_dir: Path,
    *,
    goal: str,
    model: str,
    rigor: str,
    items: list[RankedDiscoverItem],
    estimate: dict[str, Any],
    now_iso: str,
) -> PreviewSnapshot:
    """Write a previewed shortlist to ``<cache_dir>/<id>.json`` and return it.

    ``now_iso`` is supplied by the caller (``datetime.now().isoformat()`` in
    production, a fixed string in tests) so this stays a pure function of inputs.
    """
    preview_id = compute_preview_id(goal, model, rigor, [it.identifier for it in items])
    snapshot = PreviewSnapshot(
        id=preview_id,
        goal=goal,
        model=model,
        rigor=rigor,
        created_at=now_iso,
        estimate=estimate,
        items=list(items),
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "id": snapshot.id,
        "goal": snapshot.goal,
        "model": snapshot.model,
        "rigor": snapshot.rigor,
        "created_at": snapshot.created_at,
        "estimate": snapshot.estimate,
        "items": [_item_to_dict(it) for it in snapshot.items],
    }
    (cache_dir / f"{preview_id}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return snapshot


def load_preview(cache_dir: Path, preview_id: str) -> PreviewSnapshot:
    """Load a previewed shortlist by id, reconstructing the source records.

    Raises :class:`PreviewCacheError` with an actionable message when the id is
    malformed, the snapshot is missing, or the file is corrupt — never silently.
    """
    clean = preview_id.strip().lower()
    if not _ID_RE.match(clean):
        raise PreviewCacheError(
            f"'{preview_id}' is not a valid preview id (expected a short hex code)."
        )
    path = cache_dir / f"{clean}.json"
    if not path.exists():
        raise PreviewCacheError(
            f"No previewed set found for id '{clean}'. Run `distill discover ... --preview` "
            "first, or check `--from-preview` matches the id it printed."
        )
    try:
        payload = _load_json_object(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise PreviewCacheError(f"Preview snapshot '{clean}' is unreadable: {exc}") from exc
    except TypeError as exc:
        raise PreviewCacheError(
            f"Preview snapshot '{clean}' has an unexpected shape: {exc}"
        ) from exc
    try:
        return _snapshot_from_payload(payload, clean)
    except (KeyError, TypeError) as exc:
        raise PreviewCacheError(
            f"Preview snapshot '{clean}' has an unexpected shape: {exc}"
        ) from exc


def list_previews(cache_dir: Path) -> list[dict[str, Any]]:
    """Return lightweight metadata for every cached preview (id, goal, time)."""
    if not cache_dir.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(cache_dir.glob("*.json")):
        try:
            payload = _load_json_object(path)
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        raw_items = payload.get("items", [])
        if not isinstance(raw_items, list):
            continue
        try:
            items = _items_from_payload(payload)
            preview_id = _optional_text(payload, "id", path.stem)
            if preview_id != path.stem:
                continue
            out.append(
                {
                    "id": preview_id,
                    "goal": _optional_text(payload, "goal"),
                    "rigor": _optional_text(payload, "rigor"),
                    "created_at": _optional_text(payload, "created_at"),
                    "items": len(items),
                }
            )
        except TypeError:
            continue
    return out
