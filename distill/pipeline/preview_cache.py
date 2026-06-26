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
from typing import Any

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
    paper = d.get("paper")
    video = d.get("video")
    site = d.get("site_seed")
    return RankedDiscoverItem(
        kind=d["kind"],
        identifier=d["identifier"],
        title=d["title"],
        subtitle=d["subtitle"],
        date=d["date"],
        final_score=d["final_score"],
        goal_fit=d["goal_fit"],
        depth_score=d["depth_score"],
        complementarity_score=d["complementarity_score"],
        rationale=d["rationale"],
        paper=PaperRecord(**paper) if paper else None,
        video=VideoInfo(**video) if video else None,
        site_seed=SiteSeed(**site) if site else None,
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
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreviewCacheError(f"Preview snapshot '{clean}' is unreadable: {exc}") from exc
    try:
        items = [_item_from_dict(it) for it in payload.get("items", [])]
        return PreviewSnapshot(
            id=payload["id"],
            goal=payload.get("goal", ""),
            model=payload.get("model", ""),
            rigor=payload.get("rigor", ""),
            created_at=payload.get("created_at", ""),
            estimate=payload.get("estimate", {}),
            items=items,
        )
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
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append(
            {
                "id": payload.get("id", path.stem),
                "goal": payload.get("goal", ""),
                "rigor": payload.get("rigor", ""),
                "created_at": payload.get("created_at", ""),
                "items": len(payload.get("items", [])),
            }
        )
    return out
