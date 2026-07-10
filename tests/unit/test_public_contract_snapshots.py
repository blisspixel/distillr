"""Regression checks for versioned public contract snapshots."""

from __future__ import annotations

import json
import runpy
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_SCRIPT = ROOT / "scripts" / "public_contracts.py"
ARTIFACT_SNAPSHOT = ROOT / "docs" / "contracts" / "artifacts-v1.json"


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
