"""Tests for versioned report section profile data."""

from __future__ import annotations

import copy
import json

import pytest

from distill.prompts.report_sections import (
    CORPUS_SECTION_PROFILE,
    DEFAULT_SECTION_PROFILE,
    REPORT_SECTIONS,
    get_active_sections,
    load_report_section_profiles,
)


def _section(section_id: str, position: str = "opening") -> dict[str, object]:
    return {
        "id": section_id,
        "title": section_id.title(),
        "position": position,
        "voice": "analytical",
        "instructions": "Use the evidence.",
        "dossier_focus": None,
    }


def _document() -> dict[str, object]:
    strategic = {
        "sections": [_section("opening"), _section("closing", "closing")],
        "single_channel_replacement": {
            "replace_id": "opening",
            "section": _section("replacement"),
        },
    }
    corpus = {
        "sections": [_section("corpus_open"), _section("corpus_close", "closing")],
        "single_channel_replacement": None,
    }
    return {
        "schema_version": 1,
        "profiles": {
            DEFAULT_SECTION_PROFILE: strategic,
            CORPUS_SECTION_PROFILE: corpus,
        },
    }


def _load(tmp_path, document: object):
    path = tmp_path / "sections.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return load_report_section_profiles(path)


def test_packaged_profiles_are_typed_and_defensively_copied():
    assert len(REPORT_SECTIONS) == 10
    corpus = get_active_sections(profile=CORPUS_SECTION_PROFILE)
    assert [section["id"] for section in corpus] == [
        "executive_synthesis",
        "evidence_map",
        "convergence_disagreement",
        "contradictions_uncertainty",
        "implications",
        "recommendations_next",
    ]
    channel = get_active_sections("channel", 1)
    assert channel[5]["id"] == "creator_accuracy"
    channel[0]["title"] = "mutated"
    assert get_active_sections("channel", 1)[0]["title"] == "Executive Briefing"


def test_loader_accepts_valid_profile_data(tmp_path):
    profiles = _load(tmp_path, _document())
    assert set(profiles) == {DEFAULT_SECTION_PROFILE, CORPUS_SECTION_PROFILE}


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda doc: [], "document must be an object"),
        (lambda doc: {**doc, "schema_version": 2}, "schema_version"),
        (lambda doc: {**doc, "profiles": []}, "profiles must be"),
        (lambda doc: {**doc, "profiles": {}}, "profiles must be"),
        (
            lambda doc: {**doc, "profiles": {**doc["profiles"], "bad": []}},
            "profiles.bad must be an object",
        ),
        (
            lambda doc: _set(doc, ["profiles", DEFAULT_SECTION_PROFILE, "sections"], []),
            "sections must be a nonempty list",
        ),
        (
            lambda doc: _set(doc, ["profiles", DEFAULT_SECTION_PROFILE, "sections"], [None]),
            "must be an object",
        ),
        (
            lambda doc: _set(
                doc,
                ["profiles", DEFAULT_SECTION_PROFILE, "sections", 0, "title"],
                "",
            ),
            "title must be a nonempty string",
        ),
        (
            lambda doc: _set(
                doc,
                ["profiles", DEFAULT_SECTION_PROFILE, "sections", 0, "position"],
                "sideways",
            ),
            "position is not supported",
        ),
        (
            lambda doc: _set(
                doc,
                ["profiles", DEFAULT_SECTION_PROFILE, "sections", 0, "voice"],
                "loud",
            ),
            "voice is not supported",
        ),
        (
            lambda doc: _set(
                doc,
                ["profiles", DEFAULT_SECTION_PROFILE, "sections", 0, "dossier_focus"],
                ["valid", 2],
            ),
            "dossier_focus",
        ),
        (
            lambda doc: _set(
                doc,
                ["profiles", DEFAULT_SECTION_PROFILE, "sections", 0, "multi_channel_only"],
                "yes",
            ),
            "multi_channel_only",
        ),
        (
            lambda doc: _set(
                doc,
                ["profiles", DEFAULT_SECTION_PROFILE, "sections", 1, "id"],
                "opening",
            ),
            "duplicate ids",
        ),
        (
            lambda doc: _set(
                doc,
                ["profiles", DEFAULT_SECTION_PROFILE, "sections", 0, "position"],
                "middle",
            ),
            "start with opening",
        ),
        (
            lambda doc: _set(
                doc,
                ["profiles", DEFAULT_SECTION_PROFILE, "single_channel_replacement"],
                [],
            ),
            "must be an object or null",
        ),
        (
            lambda doc: _set(
                doc,
                [
                    "profiles",
                    DEFAULT_SECTION_PROFILE,
                    "single_channel_replacement",
                    "replace_id",
                ],
                "missing",
            ),
            "target is missing",
        ),
        (
            lambda doc: {
                **doc,
                "profiles": {DEFAULT_SECTION_PROFILE: doc["profiles"][DEFAULT_SECTION_PROFILE]},
            },
            "required report section profile is missing",
        ),
        (
            lambda doc: {
                **doc,
                "profiles": {**doc["profiles"], "": doc["profiles"][CORPUS_SECTION_PROFILE]},
            },
            "profile names",
        ),
    ],
)
def test_loader_rejects_invalid_schema(tmp_path, mutate, message):
    document = mutate(copy.deepcopy(_document()))
    with pytest.raises(ValueError, match=message):
        _load(tmp_path, document)


def _set(document: object, path: list[object], value: object) -> object:
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return document


def test_get_active_sections_rejects_unknown_profile():
    with pytest.raises(ValueError, match="unknown report section profile"):
        get_active_sections(profile="missing")


def test_multi_channel_only_section_is_filtered_for_single_scope(tmp_path):
    document = _document()
    section = document["profiles"][CORPUS_SECTION_PROFILE]["sections"][0]
    section["multi_channel_only"] = True
    profiles = _load(tmp_path, document)
    assert profiles[CORPUS_SECTION_PROFILE]["sections"][0]["multi_channel_only"] is True
