"""Trust-boundary tests for insight verification bindings."""

from __future__ import annotations

from pathlib import Path

import pytest

from distill.library.insights import (
    discover_insights,
    insight_current_receipt_is_valid,
    insight_has_body,
    insight_verification_binding_is_valid,
    insight_verification_payload_is_valid,
    read_discovered_insight,
    receipt_body_sha256,
    verify_sidecar_for_insight,
)
from distill.library.paths import dump_frontmatter


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


def _paper_pair(
    tmp_path: Path, *, bound: bool = True, stamped: bool = True
) -> tuple[Path, Path, Path]:
    topic = tmp_path / "library" / "topics" / "example"
    directory = topic / "papers" / "paper"
    directory.mkdir(parents=True)
    source_body = "The current paper reports a qualified result."
    digest = receipt_body_sha256(source_body)
    source_fields = {"receipt_sha256": digest} if stamped else {}
    source = directory / "paper_Paper.md"
    source.write_text(dump_frontmatter(source_fields) + "\n\n" + source_body, encoding="utf-8")
    fields = {"source": "arxiv", "paper_id": "synthetic-v1"}
    if bound:
        fields["paper_receipt_body_sha256"] = digest
    insight = directory / "paper_Insights.md"
    insight.write_text(
        dump_frontmatter(fields) + "\n\nA qualified interpretation.", encoding="utf-8"
    )
    return topic, source, insight


def test_current_paper_binding_is_reusable_by_discovery_and_direct_readers(tmp_path: Path) -> None:
    topic, _, insight = _paper_pair(tmp_path)
    assert insight_current_receipt_is_valid(insight, root=topic)
    refs = discover_insights(topic)
    assert len(refs) == 1
    assert read_discovered_insight(refs[0], topic) == insight.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "failure", ["changed", "body-corrupt", "stamp-corrupt", "missing", "unreadable"]
)
def test_bound_paper_requires_the_current_stamped_capture(tmp_path: Path, failure: str) -> None:
    topic, source, insight = _paper_pair(tmp_path)
    if failure == "changed":
        body = "A later capture changes the qualified result."
        source.write_text(
            dump_frontmatter({"receipt_sha256": receipt_body_sha256(body)}) + "\n\n" + body,
            encoding="utf-8",
        )
    elif failure == "body-corrupt":
        source.write_text(
            source.read_text(encoding="utf-8") + " Unstamped mutation.", encoding="utf-8"
        )
    elif failure == "stamp-corrupt":
        source.write_text(
            source.read_text(encoding="utf-8").replace("receipt_sha256:", "old_receipt_sha256:"),
            encoding="utf-8",
        )
    elif failure == "missing":
        source.unlink()
    else:
        source.write_bytes(b"\xff")
    assert not insight_current_receipt_is_valid(insight, root=topic)
    assert discover_insights(topic) == []


@pytest.mark.parametrize("digest", ["", "not-a-sha256", "0" * 64])
def test_invalid_or_mismatched_paper_binding_is_not_legacy_compatibility(
    tmp_path: Path, digest: str
) -> None:
    topic, _, insight = _paper_pair(tmp_path)
    insight.write_text(
        dump_frontmatter({"paper_id": "synthetic-v1", "paper_receipt_body_sha256": digest})
        + "\n\nAn interpretation.",
        encoding="utf-8",
    )
    assert not insight_current_receipt_is_valid(insight, root=topic)


def test_unbound_legacy_paper_is_current_only_until_a_stamped_capture_exists(
    tmp_path: Path,
) -> None:
    topic, source, insight = _paper_pair(tmp_path, bound=False, stamped=False)
    assert insight_current_receipt_is_valid(insight, root=topic)
    assert len(discover_insights(topic)) == 1
    source.write_text(
        dump_frontmatter({"receipt_sha256": receipt_body_sha256("New capture.")})
        + "\n\nNew capture.",
        encoding="utf-8",
    )
    assert not insight_current_receipt_is_valid(insight, root=topic)
    assert discover_insights(topic) == []


def test_legacy_paper_without_a_capture_remains_compatible(tmp_path: Path) -> None:
    topic, source, insight = _paper_pair(tmp_path, bound=False, stamped=False)
    source.unlink()
    assert insight_current_receipt_is_valid(insight, root=topic)
    assert len(discover_insights(topic)) == 1


def test_capture_change_after_discovery_invalidates_the_unchanged_insight_reference(
    tmp_path: Path,
) -> None:
    topic, source, insight = _paper_pair(tmp_path)
    ref = discover_insights(topic)[0]
    initial_insight = insight.read_bytes()
    body = "A later corrected capture."
    source.write_text(
        dump_frontmatter({"receipt_sha256": receipt_body_sha256(body)}) + "\n\n" + body,
        encoding="utf-8",
    )
    assert insight.read_bytes() == initial_insight
    assert read_discovered_insight(ref, topic) is None


def test_changed_capture_and_refused_replacement_cannot_leave_old_analysis_current(
    tmp_path: Path,
) -> None:
    from distill.commands._paper_artifacts import (
        PaperPublicationRefusedError,
        write_paper_artifacts,
    )
    from distill.config import DistillConfig
    from distill.ingestors.papers.arxiv import PaperRecord
    from distill.library.paths import find_artifact

    config = DistillConfig(distill_output_dir=tmp_path / "library", distill_verify="strict")
    paper = PaperRecord(
        paper_id="synthetic-refused-correction",
        title="Synthetic refused correction",
        abstract="Authored paper fixture.",
        authors=["Fixture"],
        abs_url="https://example.invalid/paper",
    )
    directory = write_paper_artifacts(
        "correction", paper, config, "The score was 72.6 MRR.", "The score was 72.6 MRR."
    )
    topic = config.topic_dir("correction")
    insight = find_artifact(directory, "insights")
    initial_insight = insight.read_bytes()
    ref = discover_insights(topic)[0]
    with pytest.raises(PaperPublicationRefusedError):
        write_paper_artifacts(
            "correction", paper, config, "The score was 99.9 MRR.", "The score was 73.0 MRR."
        )
    assert insight.read_bytes() == initial_insight
    assert "73.0" in find_artifact(directory, "paper").read_text(encoding="utf-8")
    assert not insight_current_receipt_is_valid(insight, root=topic)
    assert discover_insights(topic) == []
    assert read_discovered_insight(ref, topic) is None


def test_public_receipt_gate_rejects_missing_or_outside_insight(tmp_path: Path) -> None:
    missing = tmp_path / "missing_Insights.md"
    assert not insight_current_receipt_is_valid(missing)
    outside = _insight(tmp_path)
    root = tmp_path / "confined"
    root.mkdir()
    assert not insight_current_receipt_is_valid(outside, root=root)
