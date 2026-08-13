# pyright: strict
"""Versioned report section profiles loaded from packaged data."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any, NotRequired, TypedDict, cast

__all__ = [
    "CORPUS_SECTION_PROFILE",
    "DEFAULT_SECTION_PROFILE",
    "REPORT_SECTIONS",
    "SINGLE_CHANNEL_REPLACEMENT",
    "ReportSection",
    "WrittenSection",
    "get_active_sections",
    "load_report_section_profiles",
]

DEFAULT_SECTION_PROFILE = "strategic-intelligence"
CORPUS_SECTION_PROFILE = "corpus-research"
_ALLOWED_POSITIONS = frozenset({"opening", "middle", "closing"})
_ALLOWED_VOICES = frozenset({"reference", "analytical", "actionable"})


class ReportSection(TypedDict):
    """One schema-validated report section definition."""

    id: str
    title: str
    position: str
    voice: str
    instructions: str
    dossier_focus: list[str] | None
    multi_channel_only: NotRequired[bool]


class WrittenSection(TypedDict):
    """An already-written section used as continuity context."""

    id: NotRequired[str]
    title: str
    content: str
    word_count: int


class SectionReplacement(TypedDict):
    replace_id: str
    section: ReportSection


class SectionProfile(TypedDict):
    sections: list[ReportSection]
    single_channel_replacement: SectionReplacement | None


def _required_text(raw: dict[str, Any], key: str, location: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{location}.{key} must be a nonempty string")
    return value


def _parse_section(value: object, location: str) -> ReportSection:
    if not isinstance(value, dict):
        raise ValueError(f"{location} must be an object")
    raw = cast("dict[str, Any]", value)
    section_id = _required_text(raw, "id", location)
    title = _required_text(raw, "title", location)
    position = _required_text(raw, "position", location)
    voice = _required_text(raw, "voice", location)
    instructions = _required_text(raw, "instructions", location)
    if position not in _ALLOWED_POSITIONS:
        raise ValueError(f"{location}.position is not supported: {position}")
    if voice not in _ALLOWED_VOICES:
        raise ValueError(f"{location}.voice is not supported: {voice}")

    focus_raw = raw.get("dossier_focus")
    focus: list[str] | None
    if focus_raw is None:
        focus = None
    elif isinstance(focus_raw, list):
        focus_items = cast("list[object]", focus_raw)
        if not all(isinstance(item, str) and item.strip() for item in focus_items):
            raise ValueError(f"{location}.dossier_focus must be null or a list of strings")
        focus = [cast("str", item) for item in focus_items]
    else:
        raise ValueError(f"{location}.dossier_focus must be null or a list of strings")

    section: ReportSection = {
        "id": section_id,
        "title": title,
        "position": position,
        "voice": voice,
        "instructions": instructions,
        "dossier_focus": focus,
    }
    multi_channel = raw.get("multi_channel_only")
    if multi_channel is not None:
        if not isinstance(multi_channel, bool):
            raise ValueError(f"{location}.multi_channel_only must be a boolean")
        section["multi_channel_only"] = multi_channel
    return section


def _parse_profile(value: object, location: str) -> SectionProfile:
    if not isinstance(value, dict):
        raise ValueError(f"{location} must be an object")
    raw = cast("dict[str, Any]", value)
    raw_sections = raw.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        raise ValueError(f"{location}.sections must be a nonempty list")
    section_items = cast("list[object]", raw_sections)
    sections = [
        _parse_section(item, f"{location}.sections[{index}]")
        for index, item in enumerate(section_items)
    ]
    ids = [section["id"] for section in sections]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{location}.sections contains duplicate ids")
    if sections[0]["position"] != "opening" or sections[-1]["position"] != "closing":
        raise ValueError(f"{location}.sections must start with opening and end with closing")

    replacement_raw = raw.get("single_channel_replacement")
    replacement: SectionReplacement | None = None
    if replacement_raw is not None:
        if not isinstance(replacement_raw, dict):
            raise ValueError(f"{location}.single_channel_replacement must be an object or null")
        replacement_obj = cast("dict[str, Any]", replacement_raw)
        replace_id = _required_text(replacement_obj, "replace_id", location)
        if replace_id not in ids:
            raise ValueError(f"{location}.single_channel_replacement target is missing")
        replacement = {
            "replace_id": replace_id,
            "section": _parse_section(
                replacement_obj.get("section"),
                f"{location}.single_channel_replacement.section",
            ),
        }
    return {"sections": sections, "single_channel_replacement": replacement}


def load_report_section_profiles(path: Path | None = None) -> dict[str, SectionProfile]:
    """Load and validate all versioned section profiles."""

    raw_text = (
        path.read_text(encoding="utf-8")
        if path is not None
        else files("distill.prompts")
        .joinpath("data/report_sections.v1.json")
        .read_text(encoding="utf-8")
    )
    raw_document = json.loads(raw_text)
    if not isinstance(raw_document, dict):
        raise ValueError("report section document must be an object")
    document = cast("dict[str, Any]", raw_document)
    if document.get("schema_version") != 1:
        raise ValueError("report section schema_version must be 1")
    profiles_raw = document.get("profiles")
    if not isinstance(profiles_raw, dict) or not profiles_raw:
        raise ValueError("report section profiles must be a nonempty object")
    profiles_obj = cast("dict[str, Any]", profiles_raw)
    profiles = {
        name: _parse_profile(value, f"profiles.{name}")
        for name, value in profiles_obj.items()
        if name.strip()
    }
    if len(profiles) != len(profiles_obj):
        raise ValueError("report section profile names must be nonempty strings")
    for required in (DEFAULT_SECTION_PROFILE, CORPUS_SECTION_PROFILE):
        if required not in profiles:
            raise ValueError(f"required report section profile is missing: {required}")
    return profiles


_SECTION_PROFILES = load_report_section_profiles()
REPORT_SECTIONS = [
    section.copy() for section in _SECTION_PROFILES[DEFAULT_SECTION_PROFILE]["sections"]
]
_replacement = _SECTION_PROFILES[DEFAULT_SECTION_PROFILE]["single_channel_replacement"]
if _replacement is None:
    raise ValueError("strategic-intelligence requires a single-channel replacement")
SINGLE_CHANNEL_REPLACEMENT = _replacement["section"].copy()


def get_active_sections(
    scope: str = "topic",
    channel_count: int = 1,
    *,
    profile: str = DEFAULT_SECTION_PROFILE,
) -> list[ReportSection]:
    """Return defensive section copies adapted to scope and profile."""

    try:
        selected = _SECTION_PROFILES[profile]
    except KeyError as exc:
        raise ValueError(f"unknown report section profile: {profile}") from exc
    is_single = scope == "channel" or channel_count <= 1
    replacement = selected["single_channel_replacement"] if is_single else None
    active: list[ReportSection] = []
    for section in selected["sections"]:
        if replacement is not None and section["id"] == replacement["replace_id"]:
            active.append(replacement["section"].copy())
            continue
        if section.get("multi_channel_only", False) and is_single:
            continue
        active.append(section.copy())
    return active
