"""Bound paper-input receipts without injecting full manifests into prompts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from distill.config import DistillConfig
from distill.ingestors.papers.arxiv import PaperRecord
from distill.library.insights import receipt_body_sha256
from distill.library.paper_inputs import (
    archive_paper_receipt,
    paper_input_binding_is_valid,
    prepare_paper_input_evidence,
)
from distill.library.paths import (
    apply_frontmatter,
    dump_frontmatter,
    extract_frontmatter,
    find_artifact,
    render_markdown_artifact,
)

_SOURCE = "# **Source heading**\n\nThe reported ratio rose under condition X.\n"


def _manifest(source: str = _SOURCE) -> dict[str, object]:
    return {
        "schema": "paper-input-evidence.v1",
        "document_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "published_receipt_body_sha256": receipt_body_sha256(
            render_markdown_artifact("paper", source)
        ),
        "source_capture": "full_pdf",
        "original_source_completeness": "not_established",
        "execution_mode": "single_pass",
        "workload_tag": "site",
        "context_window_tokens": 4096,
        "context_window_basis": "requested_workload_metadata",
        "selection_budget_estimated_tokens": int(4096 * 0.8),
        "token_estimator": "characters_div_4",
        "prompt_chunk_coverage": "all_supplied_chunks",
        "semantic_sufficiency": "not_assessed",
        "chunks": [
            {
                "index": 0,
                "heading": "# **Source heading**",
                "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                "estimated_tokens": len(source) // 4,
            }
        ],
        "passes": [
            {
                "section": "single pass",
                "chunk_indices": [0],
                "model": "actual-response-model",
                "selection_mode": "single_pass",
                "output_present": True,
            }
        ],
        "selected_chunk_indices": [0],
        "omitted_chunk_indices": [],
    }


def _insight(manifest: object, body: str = "## Findings\n\nA bounded interpretation.\n") -> str:
    return dump_frontmatter({"paper_input_evidence": json.dumps(manifest)}) + "\n\n" + body


def test_absent_internal_field_is_exact_noop_without_creating_directory(tmp_path: Path) -> None:
    destination = tmp_path / "not-created"
    original = "---\nmodel: older-model\n---\n\nAn existing insight.\n"
    assert prepare_paper_input_evidence(destination, original, source_document=_SOURCE) == original
    assert not destination.exists()


def test_receipt_is_canonical_digest_bound_and_published_header_is_small(tmp_path: Path) -> None:
    original = _insight(_manifest())
    reduced = prepare_paper_input_evidence(tmp_path, original, source_document=_SOURCE)
    fields = extract_frontmatter(reduced)
    assert "paper_input_evidence" not in fields
    assert fields["paper_input_evidence_schema"] == "paper-input-evidence.v1"
    assert fields["paper_input_coverage"] == "all_supplied_chunks"
    sidecar_path = tmp_path / fields["paper_input_evidence_file"]
    encoded = sidecar_path.read_bytes()
    digest = hashlib.sha256(encoded).hexdigest()
    assert fields["paper_input_evidence_sha256"] == digest
    assert sidecar_path.name == f"paper-input-evidence.{digest}.json"
    receipt = json.loads(encoded)
    assert receipt["insight_body_sha256"] == receipt_body_sha256(
        render_markdown_artifact("insights", original)
    )
    assert receipt["published_receipt_body_sha256"] == fields["paper_receipt_body_sha256"]
    assert receipt["document_sha256"] != receipt["published_receipt_body_sha256"]
    assert receipt["passes"][0]["model"] == "actual-response-model"
    assert encoded == (
        json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")
    assert "chunk_indices" not in reduced
    assert "A bounded interpretation." in reduced


def test_same_evidence_reuses_immutable_receipt_without_rewriting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = _insight(_manifest())
    first = prepare_paper_input_evidence(tmp_path, original, source_document=_SOURCE)
    sidecar_path = tmp_path / extract_frontmatter(first)["paper_input_evidence_file"]
    initial_modified = sidecar_path.stat().st_mtime_ns

    def unexpected_write(*args: object, **kwargs: object) -> None:
        pytest.fail("Identical content-addressed evidence should be reused")

    monkeypatch.setattr("distill.library.paper_inputs.atomic_write_confined_text", unexpected_write)
    assert prepare_paper_input_evidence(tmp_path, original, source_document=_SOURCE) == first
    assert sidecar_path.stat().st_mtime_ns == initial_modified


def test_changed_interpretation_creates_new_receipt_and_keeps_prior_evidence(
    tmp_path: Path,
) -> None:
    first = prepare_paper_input_evidence(tmp_path, _insight(_manifest()), source_document=_SOURCE)
    original_path = tmp_path / extract_frontmatter(first)["paper_input_evidence_file"]
    original_bytes = original_path.read_bytes()
    second = prepare_paper_input_evidence(
        tmp_path, _insight(_manifest(), "A different interpretation.\n"), source_document=_SOURCE
    )
    second_path = tmp_path / extract_frontmatter(second)["paper_input_evidence_file"]
    assert second_path != original_path
    assert original_path.read_bytes() == original_bytes
    assert second_path.is_file()


def test_corrupt_content_addressed_file_is_not_replaced(tmp_path: Path) -> None:
    original = _insight(_manifest())
    first = prepare_paper_input_evidence(tmp_path, original, source_document=_SOURCE)
    sidecar_path = tmp_path / extract_frontmatter(first)["paper_input_evidence_file"]
    sidecar_path.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="corrupt"):
        prepare_paper_input_evidence(tmp_path, original, source_document=_SOURCE)
    assert sidecar_path.read_bytes() == b"corrupted"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema", "paper-input-evidence.v2"),
        ("document_sha256", "not-a-digest"),
        ("context_window_tokens", True),
        ("source_capture", "video"),
        ("semantic_sufficiency", "passed"),
        ("chunks", "not-a-list"),
        ("passes", []),
        ("selected_chunk_indices", [True]),
        ("omitted_chunk_indices", [0]),
        ("prompt_chunk_coverage", "some_supplied_chunks"),
    ],
)
def test_invalid_generated_manifest_refuses_before_writing(
    tmp_path: Path, field: str, value: object
) -> None:
    manifest = _manifest()
    manifest[field] = value
    with pytest.raises(ValueError):
        prepare_paper_input_evidence(tmp_path, _insight(manifest), source_document=_SOURCE)
    assert not list(tmp_path.glob("paper-input-evidence.*.json"))


@pytest.mark.parametrize("raw", ["{", "null", "[]", '{"schema":"paper-input-evidence.v1"}'])
def test_malformed_or_missing_manifest_fields_are_not_silently_ignored(
    tmp_path: Path, raw: str
) -> None:
    original = dump_frontmatter({"paper_input_evidence": raw}) + "\n\nA body.\n"
    with pytest.raises(ValueError):
        prepare_paper_input_evidence(tmp_path, original, source_document=_SOURCE)
    assert not list(tmp_path.glob("paper-input-evidence.*.json"))


def test_changed_source_body_refuses_false_provenance(tmp_path: Path) -> None:
    manifest = _manifest()
    changed_source = "A different source."
    manifest["document_sha256"] = hashlib.sha256(changed_source.encode("utf-8")).hexdigest()
    with pytest.raises(ValueError, match="source receipt body"):
        prepare_paper_input_evidence(tmp_path, _insight(manifest), source_document=changed_source)
    assert not list(tmp_path.glob("paper-input-evidence.*.json"))


def test_normalized_equal_source_still_requires_exact_analyzer_input(tmp_path: Path) -> None:
    equivalent = _SOURCE + "\n"
    assert receipt_body_sha256(render_markdown_artifact("paper", equivalent)) == (
        receipt_body_sha256(render_markdown_artifact("paper", _SOURCE))
    )
    with pytest.raises(ValueError, match="supplied source document"):
        prepare_paper_input_evidence(tmp_path, _insight(_manifest()), source_document=equivalent)
    assert not list(tmp_path.glob("paper-input-evidence.*.json"))


@pytest.mark.parametrize("indices", [[], [False], [0, 0], [2]])
def test_invalid_executed_pass_identity_is_refused(tmp_path: Path, indices: list[object]) -> None:
    manifest = _manifest()
    manifest["passes"] = [
        {
            "section": "single pass",
            "chunk_indices": indices,
            "model": "effective",
            "selection_mode": "single_pass",
            "output_present": True,
        }
    ]
    with pytest.raises(ValueError):
        prepare_paper_input_evidence(tmp_path, _insight(manifest), source_document=_SOURCE)
    assert not list(tmp_path.glob("paper-input-evidence.*.json"))


def test_legacy_unknown_prompt_identities_stay_explicitly_unknown(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["prompt_chunk_coverage"] = "unknown"
    manifest["selected_chunk_indices"] = []
    manifest["omitted_chunk_indices"] = None
    manifest["passes"] = [
        {
            "section": "single pass",
            "chunk_indices": None,
            "model": "unknown",
            "selection_mode": "single_pass",
            "output_present": True,
        }
    ]
    reduced = prepare_paper_input_evidence(tmp_path, _insight(manifest), source_document=_SOURCE)
    assert extract_frontmatter(reduced)["paper_input_coverage"] == "unknown"


def test_sidecar_write_failure_prevents_candidate_publication_and_preserves_old_insight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from distill.commands._paper_artifacts import write_paper_artifacts

    config = DistillConfig(distill_output_dir=tmp_path / "library", distill_verify="off")
    paper = PaperRecord(
        paper_id="synthetic-input-boundary",
        title="Synthetic input boundary",
        abstract="Synthetic source.",
        authors=["Fixture"],
        abs_url="https://example.invalid/paper",
    )
    directory = write_paper_artifacts("test", paper, config, _insight(_manifest()), _SOURCE)
    old_insight = find_artifact(directory, "insights")
    old_bytes = old_insight.read_bytes()
    old_evidence = directory / extract_frontmatter(old_bytes.decode())["paper_input_evidence_file"]
    old_evidence_bytes = old_evidence.read_bytes()
    old_source = find_artifact(directory, "paper").read_bytes()
    changed_source = _SOURCE + "\nA later correction."

    def deny_write(*args: object, **kwargs: object) -> None:
        raise OSError("receipt write denied")

    monkeypatch.setattr("distill.library.paper_inputs.atomic_write_confined_text", deny_write)
    with pytest.raises(OSError, match="receipt write denied"):
        write_paper_artifacts(
            "test",
            paper,
            config,
            _insight(_manifest(changed_source), "Changed interpretation."),
            changed_source,
        )
    assert old_insight.read_bytes() == old_bytes
    assert old_evidence.read_bytes() == old_evidence_bytes
    archived = (
        directory / ".history/paper-receipts" / f"{hashlib.sha256(old_source).hexdigest()}.md"
    )
    assert archived.read_bytes() == old_source
    assert find_artifact(directory, "paper").read_bytes() != old_source


def test_archive_preserves_exact_bytes_and_reuses_prior_generation(tmp_path: Path) -> None:
    source = tmp_path / "paper.md"
    assert archive_paper_receipt(tmp_path, source) is None
    content = b"---\r\ntype: paper\r\n---\r\n\r\nCaptured source.\r\n"
    source.write_bytes(content)
    archived = archive_paper_receipt(tmp_path, source)
    assert (
        archived
        == tmp_path / ".history/paper-receipts" / f"{hashlib.sha256(content).hexdigest()}.md"
    )
    assert archived.read_bytes() == content
    modified = archived.stat().st_mtime_ns
    assert archive_paper_receipt(tmp_path, source) == archived
    assert archived.stat().st_mtime_ns == modified
    assert source.read_bytes() == content
    archived.write_bytes(b"corrupted history")
    with pytest.raises(ValueError, match="Archived paper receipt is corrupt"):
        archive_paper_receipt(tmp_path, source)
    assert source.read_bytes() == content
    assert archived.read_bytes() == b"corrupted history"


def test_unreadable_prior_source_is_not_silently_discarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "paper.md"
    source.write_text("Old capture.", encoding="utf-8")
    monkeypatch.setattr(
        "distill.library.paper_inputs.read_confined_state_bytes", lambda *a, **k: None
    )
    with pytest.raises(ValueError, match="safely retained"):
        archive_paper_receipt(tmp_path, source)
    assert source.read_text(encoding="utf-8") == "Old capture."


def test_binding_checks_the_exact_sidecar_and_current_insight_body(tmp_path: Path) -> None:
    path = tmp_path / "paper_Insights.md"
    reduced = prepare_paper_input_evidence(tmp_path, _insight(_manifest()), source_document=_SOURCE)
    assert paper_input_binding_is_valid(path, reduced, root=tmp_path)
    assert not paper_input_binding_is_valid(
        path, reduced + "Changed interpretation.", root=tmp_path
    )
    assert paper_input_binding_is_valid(path, "Legacy body without refs.", root=tmp_path)
    sidecar = tmp_path / extract_frontmatter(reduced)["paper_input_evidence_file"]
    original = sidecar.read_bytes()
    sidecar.write_bytes(b"corruption")
    assert not paper_input_binding_is_valid(path, reduced, root=tmp_path)
    sidecar.write_bytes(original)
    assert paper_input_binding_is_valid(path, reduced, root=tmp_path)
    sidecar.unlink()
    assert not paper_input_binding_is_valid(path, reduced, root=tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("paper_input_evidence_schema", "unsupported.v2"),
        ("paper_input_evidence_sha256", "not-a-digest"),
        ("paper_input_evidence_file", "../outside.json"),
        ("paper_input_coverage", "unknown"),
        ("paper_receipt_body_sha256", "a" * 64),
        ("paper_original_source_completeness", "complete"),
        ("paper_input_evidence_schema", None),
        ("paper_receipt_body_sha256", None),
    ],
)
def test_partial_or_inconsistent_compact_references_are_not_current(
    tmp_path: Path, field: str, value: object
) -> None:
    reduced = prepare_paper_input_evidence(tmp_path, _insight(_manifest()), source_document=_SOURCE)
    candidate = apply_frontmatter(reduced, {field: value})
    assert not paper_input_binding_is_valid(
        tmp_path / "paper_Insights.md", candidate, root=tmp_path
    )


def test_content_hash_cannot_turn_invalid_json_into_valid_evidence(tmp_path: Path) -> None:
    reduced = prepare_paper_input_evidence(tmp_path, _insight(_manifest()), source_document=_SOURCE)
    invalid = b'{"schema":"unsupported"}\n'
    digest = hashlib.sha256(invalid).hexdigest()
    filename = f"paper-input-evidence.{digest}.json"
    (tmp_path / filename).write_bytes(invalid)
    candidate = apply_frontmatter(
        reduced, {"paper_input_evidence_sha256": digest, "paper_input_evidence_file": filename}
    )
    assert not paper_input_binding_is_valid(
        tmp_path / "paper_Insights.md", candidate, root=tmp_path
    )


def test_receipt_bound_is_enforced_before_write_and_during_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reduced = prepare_paper_input_evidence(tmp_path, _insight(_manifest()), source_document=_SOURCE)
    monkeypatch.setattr("distill.library.paper_inputs._MAX_INPUT_EVIDENCE_BYTES", 1)
    assert not paper_input_binding_is_valid(tmp_path / "paper_Insights.md", reduced, root=tmp_path)
    with pytest.raises(ValueError, match="bounded reader size"):
        prepare_paper_input_evidence(tmp_path, _insight(_manifest()), source_document=_SOURCE)


def _published_paper(tmp_path: Path, verify_mode: str = "warn"):
    from distill.commands._paper_artifacts import write_paper_artifacts

    config = DistillConfig(distill_output_dir=tmp_path / "library", distill_verify=verify_mode)
    paper = PaperRecord(
        paper_id="synthetic-history",
        title="Synthetic paper history",
        abstract="Synthetic source.",
        authors=["Fixture"],
        abs_url="https://example.invalid/history",
    )
    directory = write_paper_artifacts("test", paper, config, _insight(_manifest()), _SOURCE)
    return directory, paper, config


def test_changed_source_refusal_keeps_history_old_insight_and_verify_binding(
    tmp_path: Path,
) -> None:
    from distill.commands._paper_artifacts import (
        PaperPublicationRefusedError,
        write_paper_artifacts,
    )

    directory, paper, config = _published_paper(tmp_path, "strict")
    old_insight = find_artifact(directory, "insights").read_bytes()
    old_verify = find_artifact(directory, "verify", extension="json").read_bytes()
    old_source = find_artifact(directory, "paper").read_bytes()
    changed_source = _SOURCE + "\nThe source was narrowed."
    with pytest.raises(PaperPublicationRefusedError):
        write_paper_artifacts(
            "test",
            paper,
            config,
            _insight(_manifest(changed_source), "Unsupported measurement reached 99.9%."),
            changed_source,
        )
    assert find_artifact(directory, "insights").read_bytes() == old_insight
    assert find_artifact(directory, "verify", extension="json").read_bytes() == old_verify
    archived = (
        directory / ".history/paper-receipts" / f"{hashlib.sha256(old_source).hexdigest()}.md"
    )
    assert archived.read_bytes() == old_source
    current_source = find_artifact(directory, "paper").read_text(encoding="utf-8")
    assert extract_frontmatter(current_source)["receipt_sha256"] == receipt_body_sha256(
        current_source
    )


@pytest.mark.parametrize("failure_site", ["sidecar", "artifact"])
def test_publication_failure_preserves_old_analysis_verify_and_archived_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_site: str
) -> None:
    from distill.commands._paper_artifacts import write_paper_artifacts

    directory, paper, config = _published_paper(tmp_path)
    old_insight = find_artifact(directory, "insights").read_bytes()
    old_verify = find_artifact(directory, "verify", extension="json").read_bytes()
    old_source = find_artifact(directory, "paper").read_bytes()
    changed_source = _SOURCE + "\nThe source changed."

    def deny_write(*args: object, **kwargs: object) -> None:
        raise OSError(f"{failure_site} publication denied")

    target = "write_verify_sidecar" if failure_site == "sidecar" else "_write_verified_output"
    monkeypatch.setattr(f"distill.pipeline.verify.{target}", deny_write)
    with pytest.raises(OSError, match="publication denied"):
        write_paper_artifacts(
            "test", paper, config, _insight(_manifest(changed_source)), changed_source
        )
    assert find_artifact(directory, "insights").read_bytes() == old_insight
    assert find_artifact(directory, "verify", extension="json").read_bytes() == old_verify
    archived = (
        directory / ".history/paper-receipts" / f"{hashlib.sha256(old_source).hexdigest()}.md"
    )
    assert archived.read_bytes() == old_source


def test_no_manifest_legacy_caller_still_binds_source_and_final_verify(tmp_path: Path) -> None:
    from distill.commands._paper_artifacts import write_paper_artifacts
    from distill.library.insights import insight_content_sha256

    directory, paper, config = _published_paper(tmp_path)
    write_paper_artifacts("test", paper, config, "A legacy caller's new insight.", _SOURCE)
    source = find_artifact(directory, "paper").read_text(encoding="utf-8")
    insight = find_artifact(directory, "insights").read_text(encoding="utf-8")
    verify = json.loads(find_artifact(directory, "verify", extension="json").read_text())
    expected = receipt_body_sha256(source)
    assert extract_frontmatter(source)["receipt_sha256"] == expected
    assert extract_frontmatter(insight)["paper_receipt_body_sha256"] == expected
    assert verify["insight_sha256"] == insight_content_sha256(insight)


def test_prior_source_is_archived_inside_whole_publication_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from distill.commands import _paper_artifacts

    directory, paper, config = _published_paper(tmp_path)
    old_source = find_artifact(directory, "paper").read_bytes()
    original_lock = _paper_artifacts.text_write_lock
    original_archive = _paper_artifacts.archive_paper_receipt
    original_verify = _paper_artifacts.run_verify_hook
    original_publish = _paper_artifacts.write_verified_artifact
    active = False
    order: list[str] = []

    @contextmanager
    def publication_lock(path: Path) -> Iterator[None]:
        nonlocal active
        assert path == directory / ".paper-publication"
        with original_lock(path):
            assert not active
            active = True
            order.append("locked")
            try:
                yield
            finally:
                active = False
                order.append("released")

    def archive_locked(root: Path, source: Path) -> Path | None:
        assert active
        assert source.read_bytes() == old_source
        order.append("archive")
        return original_archive(root, source)

    def verify_locked(*args, **kwargs):
        assert active
        order.append("verify")
        archived = (
            directory / ".history/paper-receipts" / f"{hashlib.sha256(old_source).hexdigest()}.md"
        )
        assert archived.read_bytes() == old_source
        return original_verify(*args, **kwargs)

    def publish_locked(*args, **kwargs):
        assert active
        order.append("publish")
        return original_publish(*args, **kwargs)

    monkeypatch.setattr(_paper_artifacts, "text_write_lock", publication_lock)
    monkeypatch.setattr(_paper_artifacts, "archive_paper_receipt", archive_locked)
    monkeypatch.setattr(_paper_artifacts, "run_verify_hook", verify_locked)
    monkeypatch.setattr(_paper_artifacts, "write_verified_artifact", publish_locked)
    changed_source = _SOURCE + "\nA concurrent refresh boundary."
    _paper_artifacts.write_paper_artifacts(
        "test", paper, config, _insight(_manifest(changed_source)), changed_source
    )
    assert order == ["locked", "archive", "verify", "publish", "released"]
    assert not active
