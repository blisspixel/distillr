"""Strictly validated parsing of site batch manifests.

A batch manifest is operator-supplied but still external input, so every
collection, mapping, and text field is bounded and type-checked before a
``SiteSeed`` is constructed from it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from distill.ingestors.sites._site_urls import (
    crawl_max_depth as _crawl_max_depth,
)
from distill.ingestors.sites._site_urls import (
    crawl_max_pages as _crawl_max_pages,
)
from distill.ingestors.sites._site_urls import (
    crawl_prefix_from_mapping as _crawl_prefix_from_mapping,
)
from distill.ingestors.sites.records import SiteBatch, SiteSeed
from distill.parsing import as_whole_number

__all__ = ["load_site_batch", "parse_site_batch_json"]

_MAX_SITE_BATCH_MANIFEST_SEEDS = 500
_MAX_SITE_BATCH_MANIFEST_TEXT_CHARS = 4_096


def load_site_batch(path: Path, topic_override: str = "") -> SiteBatch:
    if path.suffix.lower() == ".json":
        return parse_site_batch_json(path.read_text(encoding="utf-8"), topic_override)
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    urls = [line for line in lines if line and not line.startswith("#")]
    topic = topic_override or "web"
    return SiteBatch(topic=topic, seeds=[SiteSeed(url=url, topic=topic) for url in urls])


def parse_site_batch_json(content: str, topic_override: str = "") -> SiteBatch:
    """Parse one bounded-shape JSON site manifest from already-read text."""

    try:
        data = json.loads(content)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Site seed manifest must contain valid JSON.") from exc
    _validate_site_batch_manifest(data)
    return _batch_from_json(data, topic_override)


def _validate_site_batch_manifest(data: object) -> None:
    if isinstance(data, list):
        _validate_manifest_items(data, context="urls")
        return
    if not isinstance(data, dict):
        raise ValueError("Site seed manifest must be a JSON object or array.")

    _validate_site_batch_object(data)


def _validate_site_batch_object(data: dict[object, object]) -> None:
    _validate_manifest_text(data.get("topic", "web"), field_name="topic")
    crawl = data.get("crawl", {})
    if not isinstance(crawl, dict):
        raise ValueError("Site seed manifest field 'crawl' must be an object.")
    _validate_manifest_mapping(crawl, context="crawl")

    raw_urls = data.get("urls", [])
    raw_collections = data.get("collections", [])
    if not isinstance(raw_urls, list):
        raise ValueError("Site seed manifest field 'urls' must be an array.")
    if not isinstance(raw_collections, list):
        raise ValueError("Site seed manifest field 'collections' must be an array.")
    if raw_urls and raw_collections:
        raise ValueError("Site seed manifest must use either 'urls' or 'collections', not both.")
    if len(raw_collections) > _MAX_SITE_BATCH_MANIFEST_SEEDS:
        raise ValueError("Site seed manifest has too many collections.")
    _validate_manifest_items(raw_urls, context="urls")
    _validate_manifest_collections(raw_collections, initial_seed_count=len(raw_urls))


def _validate_manifest_collections(
    raw_collections: list[object],
    *,
    initial_seed_count: int,
) -> None:
    total_seeds = initial_seed_count
    for index, raw_collection in enumerate(raw_collections):
        if not isinstance(raw_collection, dict):
            raise ValueError(f"Site seed collection {index + 1} must be an object.")
        _validate_manifest_mapping(raw_collection, context=f"collection {index + 1}")
        seeds = raw_collection.get("seeds", [])
        if not isinstance(seeds, list):
            raise ValueError(f"Site seed collection {index + 1} field 'seeds' must be an array.")
        total_seeds += len(seeds)
        if total_seeds > _MAX_SITE_BATCH_MANIFEST_SEEDS:
            raise ValueError("Site seed manifest has too many seeds.")
        for seed_index, seed in enumerate(seeds):
            if not isinstance(seed, str) or not seed:
                raise ValueError(
                    f"Site seed collection {index + 1} entry {seed_index + 1} must be a URL string."
                )
            _validate_manifest_text(seed, field_name="url")


def _validate_manifest_items(items: list[object], *, context: str) -> None:
    if len(items) > _MAX_SITE_BATCH_MANIFEST_SEEDS:
        raise ValueError("Site seed manifest has too many seeds.")
    for index, item in enumerate(items):
        if isinstance(item, str):
            if not item:
                raise ValueError(f"Site seed {context} entry {index + 1} must not be empty.")
            _validate_manifest_text(item, field_name="url")
            continue
        if not isinstance(item, dict):
            raise ValueError(f"Site seed {context} entry {index + 1} must be a URL or object.")
        _validate_manifest_mapping(item, context=f"{context} entry {index + 1}")
        url = item.get("url")
        if not isinstance(url, str) or not url:
            raise ValueError(f"Site seed {context} entry {index + 1} requires a URL string.")
        _validate_manifest_text(url, field_name="url")


def _validate_manifest_mapping(data: dict[object, object], *, context: str) -> None:
    text_fields = {
        "topic",
        "site_name",
        "label",
        "name",
        "section_label",
        "source_hint",
        "freshness_hint",
        "crawl_prefix",
        "path_prefix",
        "mode",
        "crawl_mode",
    }
    boolean_fields = {"discover_crawl", "same_section_only"}
    integer_fields = {"max_depth", "max_pages", "max_pages_per_seed"}
    for field_name in text_fields:
        if field_name in data:
            _validate_manifest_text(data[field_name], field_name=field_name)
    for field_name in boolean_fields:
        if field_name in data and not isinstance(data[field_name], bool):
            raise ValueError(f"Site seed {context} field '{field_name}' must be a boolean.")
    if "crawl" in data and not isinstance(data["crawl"], bool):
        raise ValueError(f"Site seed {context} field 'crawl' must be a boolean.")
    for field_name in integer_fields:
        if field_name in data:
            parsed = as_whole_number(data[field_name])
            if parsed is None:
                raise ValueError(f"Site seed {context} field '{field_name}' must be an integer.")
            data[field_name] = parsed


def _validate_manifest_text(value: object, *, field_name: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"Site seed manifest field '{field_name}' must be a string.")
    if len(value) > _MAX_SITE_BATCH_MANIFEST_TEXT_CHARS:
        raise ValueError(f"Site seed manifest field '{field_name}' is too long.")


def _batch_from_json(data: Any, topic_override: str) -> SiteBatch:
    topic = (
        topic_override or data.get("topic", "web")
        if isinstance(data, dict)
        else topic_override or "web"
    )
    seeds: list[SiteSeed] = []
    crawl_config = data.get("crawl", {}) if isinstance(data, dict) else {}
    global_crawl_prefix = str(crawl_config.get("crawl_prefix", crawl_config.get("path_prefix", "")))
    global_max_depth = crawl_config.get("max_depth", 1) if isinstance(crawl_config, dict) else 1
    global_max_pages = (
        crawl_config.get("max_pages_per_seed", 8) if isinstance(crawl_config, dict) else 8
    )

    if isinstance(data, list):
        iterable = data
    else:
        collections = data.get("collections", []) if isinstance(data, dict) else []
        if collections:
            for collection in collections:
                for url in collection.get("seeds", []):
                    seeds.append(
                        SiteSeed(
                            url=url,
                            topic=collection.get("topic", topic),
                            site_name=collection.get("site_name", ""),
                            label=collection.get("label", collection.get("name", "")),
                            section_label=collection.get("section_label", ""),
                            source_hint=collection.get("source_hint", ""),
                            freshness_hint=collection.get("freshness_hint", ""),
                            crawl_prefix=_crawl_prefix_from_mapping(
                                collection,
                                fallback=global_crawl_prefix,
                            ),
                            discover_crawl=bool(collection.get("discover_crawl", False)),
                            max_depth=_crawl_max_depth(collection, default=global_max_depth),
                            max_pages=_crawl_max_pages(collection, default=global_max_pages),
                            same_section_only=bool(
                                collection.get(
                                    "same_section_only",
                                    data.get("crawl", {}).get("same_section_only", False),
                                )
                            ),
                        )
                    )
            return SiteBatch(topic=topic, seeds=seeds)
        iterable = data.get("urls", []) if isinstance(data, dict) else []

    for item in iterable:
        if isinstance(item, str):
            seeds.append(SiteSeed(url=item, topic=topic))
        elif isinstance(item, dict) and item.get("url"):
            seeds.append(
                SiteSeed(
                    url=item["url"],
                    topic=item.get("topic", topic),
                    site_name=item.get("site_name", ""),
                    label=item.get("label", item.get("name", "")),
                    section_label=item.get("section_label", ""),
                    source_hint=item.get("source_hint", ""),
                    freshness_hint=item.get("freshness_hint", ""),
                    crawl_prefix=_crawl_prefix_from_mapping(item, fallback=global_crawl_prefix),
                    discover_crawl=bool(item.get("discover_crawl", False)),
                    max_depth=_crawl_max_depth(item, default=global_max_depth),
                    max_pages=_crawl_max_pages(item, default=global_max_pages),
                    same_section_only=bool(item.get("same_section_only", False)),
                )
            )
    return SiteBatch(topic=topic, seeds=seeds)
