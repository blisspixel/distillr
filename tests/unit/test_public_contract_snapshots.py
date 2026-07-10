"""Regression checks for versioned public contract snapshots."""

from __future__ import annotations

import asyncio
import json
import runpy
import subprocess
import sys
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import cast

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_SCRIPT = ROOT / "scripts" / "public_contracts.py"
ARTIFACT_SNAPSHOT = ROOT / "docs" / "contracts" / "artifacts-v1.json"
STATE_SNAPSHOT = ROOT / "docs" / "contracts" / "state-v1.json"


def test_public_contract_snapshots_match_runtime() -> None:
    """Runtime public surfaces must match their reviewed candidate-v1 snapshots."""
    result = subprocess.run(
        [sys.executable, str(SNAPSHOT_SCRIPT), "--check"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_artifact_contract_snapshot_is_tracked() -> None:
    """Artifact names and standard frontmatter need their own reviewed contract."""
    assert ARTIFACT_SNAPSHOT.is_file()
    snapshot = json.loads(ARTIFACT_SNAPSHOT.read_text())
    assert snapshot["frontmatter"]["field_types"]["generated_at"] == "string"
    assert snapshot["frontmatter"]["field_types"]["tags"] == "array"
    assert snapshot["frontmatter"]["field_types"]["temperature"] == "number"
    assert snapshot["artifact_types"]["transcript"]["reader_patterns"] == [
        "{identity}_Transcript.txt",
        "{identity}_transcript.txt",
        "transcript.txt",
    ]
    serialized = snapshot["frontmatter"]["serialization_example"]
    assert "boolean_true: true" in serialized
    assert 'array: ["alpha", "beta"]' in serialized
    assert "empty_string" not in serialized


def test_state_contract_snapshot_is_tracked() -> None:
    """Normalized persisted state shapes need a reviewed compatibility contract."""
    assert STATE_SNAPSHOT.is_file()
    snapshot = json.loads(STATE_SNAPSHOT.read_text())
    assert snapshot["json_schema_dialect"].endswith("/draft/2020-12/schema")
    for document in snapshot["documents"].values():
        schema = document["normalized_schema"]
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(schema)
        for case in document["compatibility_cases"]:
            validator.validate(case["normalized"])
    library_cases = snapshot["documents"]["library_index"]["compatibility_cases"]
    libraries = {case["name"]: case["normalized"] for case in library_cases}
    legacy_library = libraries["legacy_missing_optional_fields"]
    assert legacy_library["watchlist"][0]["days"] == 14
    assert legacy_library["topic_watchlist"][0]["ranking_mode"] == "balanced"
    explicit_library = libraries["explicit_fields_and_numeric_types"]
    assert explicit_library["topic_watchlist"][0]["max_run_cost"] == 2.0
    missing_library = libraries["missing_scalar_fields"]
    assert missing_library["topics"]["missing-channels"] == {"channels": []}
    assert missing_library["topics"]["missing-fields"]["channels"][0] == {
        "name": "",
        "url": "",
    }
    channel_cases = snapshot["documents"]["channel_state"]["compatibility_cases"]
    channels = {case["name"]: case["normalized"] for case in channel_cases}
    legacy_channel = channels["legacy_missing_analysis_mode"]
    assert legacy_channel["processed_videos"]["video-id"]["analysis_mode"] == "full"
    missing_channel = channels["missing_scalar_fields"]
    assert missing_channel["processed_videos"]["missing-fields"] == {
        "analysis_mode": "full",
        "processed_at": "",
        "title": "",
        "upload_date": "",
    }


def test_generated_and_tracked_contract_snapshot_sets_match() -> None:
    namespace = runpy.run_path(str(SNAPSHOT_SCRIPT))
    snapshot_fn = cast(
        "Callable[[], Coroutine[object, object, dict[Path, dict[str, object]]]]",
        namespace["snapshots"],
    )
    generated = {path.name for path in asyncio.run(snapshot_fn())}
    tracked = {path.name for path in (ROOT / "docs" / "contracts").glob("*-v1.json")}

    assert (
        generated
        == tracked
        == {
            "artifacts-v1.json",
            "cli-v1.json",
            "mcp-v1.json",
            "state-v1.json",
        }
    )


def test_cli_snapshot_distinguishes_arguments_from_options() -> None:
    """Positional arguments must not be serialized as Click option names."""
    snapshot = json.loads((ROOT / "docs" / "contracts" / "cli-v1.json").read_text())
    commands = {row["path"]: row for row in snapshot["commands"]}
    assert commands["distill"]["invoke_without_command"] is True
    assert commands["distill concepts"]["no_args_is_help"] is True

    add_command = commands["distill add"]
    parameters = {row["name"]: row for row in add_command["parameters"]}

    assert parameters["topic"]["kind"] == "argument"
    assert "names" not in parameters["topic"]

    diff_command = commands["distill concepts diff"]
    arguments = [row for row in diff_command["parameters"] if row["kind"] == "argument"]
    assert [(row["position"], row["name"]) for row in arguments] == [
        (0, "topic"),
        (1, "slug"),
        (2, "ts_a"),
        (3, "ts_b"),
    ]


def test_schema_cleanup_preserves_property_names() -> None:
    """Schema annotations may be removed, but fields with the same names remain."""
    namespace = runpy.run_path(str(SNAPSHOT_SCRIPT))
    clean_schema = cast("Callable[[object], object]", namespace["_schema_without_prose"])

    cleaned = clean_schema(
        {
            "title": "Request",
            "type": "object",
            "properties": {
                "title": {"title": "Title", "type": "string"},
                "description": {"description": "User text", "type": "string"},
            },
            "dependentRequired": {"title": ["description"]},
            "default": {"title": "Untitled", "description": ""},
            "unevaluatedItems": {"description": "Item", "type": "string"},
        }
    )

    assert cleaned == {
        "default": {"description": "", "title": "Untitled"},
        "dependentRequired": {"title": ["description"]},
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
        },
        "unevaluatedItems": {"type": "string"},
    }
