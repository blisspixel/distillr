"""Trust-boundary tests for insight verification bindings."""

from __future__ import annotations

from pathlib import Path

from distill.library.insights import (
    insight_has_body,
    insight_verification_binding_is_valid,
    insight_verification_payload_is_valid,
    verify_sidecar_for_insight,
)


def _insight(tmp_path: Path, *, required: bool = False) -> Path:
    path = tmp_path / "example_Insights.md"
    frontmatter = "verification_required: true\n" if required else ""
    path.write_text(f"---\n{frontmatter}---\n\nGrounded content.\n", encoding="utf-8")
    return path


def test_insight_has_body_rejects_frontmatter_only_or_whitespace() -> None:
    assert not insight_has_body("")
    assert not insight_has_body("   \n")
    assert not insight_has_body("---\nvideo_title: x\n---\n")
    assert not insight_has_body("---\nvideo_title: x\n---\n\n  \n")
    assert insight_has_body("---\ntitle: x\n---\n\nA real finding.\n")
    assert insight_has_body("No frontmatter, but a body.")


def test_verification_helpers_reject_missing_insight(tmp_path: Path) -> None:
    missing = tmp_path / "missing_Insights.md"

    assert not insight_verification_payload_is_valid(missing, {})
    assert not insight_verification_binding_is_valid(missing)


def test_payload_validation_handles_unbound_and_malformed_payloads(tmp_path: Path) -> None:
    insight = _insight(tmp_path)

    assert insight_verification_payload_is_valid(insight, [])
    assert not insight_verification_payload_is_valid(
        insight,
        {"insight_sha256": "not-a-digest"},
    )


def test_optional_binding_defaults_to_valid_without_sidecar(tmp_path: Path) -> None:
    insight = _insight(tmp_path)

    assert insight_verification_binding_is_valid(insight)


def test_binding_rejects_unreadable_sidecar(tmp_path: Path) -> None:
    insight = _insight(tmp_path)
    verify_sidecar_for_insight(insight).write_bytes(b"\xff")

    assert not insight_verification_binding_is_valid(insight)


def test_optional_binding_tolerates_malformed_sidecar_json(tmp_path: Path) -> None:
    insight = _insight(tmp_path)
    verify_sidecar_for_insight(insight).write_text("{", encoding="utf-8")

    assert insight_verification_binding_is_valid(insight)


def test_required_binding_rejects_malformed_sidecar_json(tmp_path: Path) -> None:
    insight = _insight(tmp_path, required=True)
    verify_sidecar_for_insight(insight).write_text("{", encoding="utf-8")

    assert not insight_verification_binding_is_valid(insight)
