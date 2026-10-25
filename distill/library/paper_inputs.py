# pyright: strict
"""Publish bounded paper-input metadata separately from model-facing insight text."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from distill.library.confined_state import (
    atomic_write_confined_bytes,
    atomic_write_confined_text,
    confined_file_identity,
    ensure_confined_parent,
    read_confined_state_bytes,
)
from distill.library.insights import receipt_body_sha256
from distill.library.paths import (
    apply_frontmatter,
    extract_frontmatter,
    render_markdown_artifact,
    text_write_lock,
)
from distill.parsing import strict_json_loads

_Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
_Index = Annotated[int, Field(ge=0)]
_Coverage = Literal["unknown", "all_supplied_chunks", "some_supplied_chunks"]
_MAX_INPUT_EVIDENCE_BYTES = 4 * 1024 * 1024
_INPUT_REFERENCE_FIELDS = frozenset(
    {
        "paper_input_evidence_schema",
        "paper_input_evidence_file",
        "paper_input_evidence_sha256",
        "paper_input_coverage",
        "paper_original_source_completeness",
    }
)


class _EvidenceRow(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _ChunkEvidence(_EvidenceRow):
    index: _Index
    heading: str
    sha256: _Digest
    estimated_tokens: _Index


class _PassEvidence(_EvidenceRow):
    section: Annotated[str, Field(min_length=1)]
    chunk_indices: list[_Index] | None
    model: Annotated[str, Field(min_length=1)]
    selection_mode: Literal[
        "single_pass", "model", "model_batch", "structural", "positional_order", "keyword_fallback"
    ]
    output_present: bool


def _executed_chunk_union(
    passes: list[_PassEvidence], chunk_ids: set[int]
) -> tuple[set[int], bool]:
    selected: set[int] = set()
    all_known = bool(passes)
    for result in passes:
        if result.chunk_indices is None:
            all_known = False
            continue
        if not result.chunk_indices:
            raise ValueError("Executed paper analysis pass cannot have an empty chunk set")
        indices = set(result.chunk_indices)
        if len(indices) != len(result.chunk_indices) or not indices <= chunk_ids:
            raise ValueError("Paper input evidence has invalid pass chunk identities")
        selected.update(indices)
    return selected, all_known


class _PaperInputEvidence(_EvidenceRow):
    schema_version: Literal["paper-input-evidence.v1"] = Field(alias="schema")
    document_sha256: _Digest
    published_receipt_body_sha256: _Digest
    source_capture: Literal["full_pdf", "abstract_only"]
    original_source_completeness: Literal["not_established"]
    execution_mode: Literal["single_pass", "multipass"]
    workload_tag: Literal["site", "analysis"]
    context_window_tokens: Annotated[int, Field(gt=0)]
    context_window_basis: Literal["requested_workload_metadata"]
    selection_budget_estimated_tokens: _Index
    token_estimator: Literal["characters_div_4"]
    prompt_chunk_coverage: _Coverage
    semantic_sufficiency: Literal["not_assessed"]
    chunks: list[_ChunkEvidence]
    passes: list[_PassEvidence]
    selected_chunk_indices: list[_Index]
    omitted_chunk_indices: list[_Index] | None

    @model_validator(mode="after")
    def validate_coverage(self) -> _PaperInputEvidence:
        chunk_ids = {chunk.index for chunk in self.chunks}
        if len(chunk_ids) != len(self.chunks):
            raise ValueError("Paper input evidence has duplicate chunk identities")
        selected, passes_known = _executed_chunk_union(self.passes, chunk_ids)
        all_known = bool(self.chunks) and passes_known
        if self.selected_chunk_indices != sorted(selected):
            raise ValueError("Paper input evidence selected union does not match its passes")
        if self.prompt_chunk_coverage == "unknown":
            if self.omitted_chunk_indices is not None:
                raise ValueError("Unknown paper input coverage cannot claim an omitted set")
        else:
            expected_coverage = (
                "all_supplied_chunks" if selected == chunk_ids else "some_supplied_chunks"
            )
            if not all_known or self.prompt_chunk_coverage != expected_coverage:
                raise ValueError("Paper input coverage does not match supplied prompt chunks")
            if self.omitted_chunk_indices != sorted(chunk_ids - selected):
                raise ValueError("Paper input evidence omitted set does not match its passes")
        return self


class _PaperInputSidecar(_PaperInputEvidence):
    insight_body_sha256: _Digest


def prepare_paper_input_evidence(
    directory: Path,
    insights: str,
    *,
    source_document: str,
) -> str:
    """Replace the internal manifest with a bound content-addressed reference.

    The immutable sidecar is durable before its insight reference can publish.
    Later verification refusal can leave an unreferenced receipt, but cannot
    rebind an earlier insight to different evidence.
    """
    raw = extract_frontmatter(insights).get("paper_input_evidence")
    if raw is None:
        return insights
    evidence = _PaperInputEvidence.model_validate(strict_json_loads(raw))
    if evidence.document_sha256 != hashlib.sha256(source_document.encode("utf-8")).hexdigest():
        raise ValueError("Paper input evidence does not match the supplied source document")
    source_body_digest = receipt_body_sha256(render_markdown_artifact("paper", source_document))
    if evidence.published_receipt_body_sha256 != source_body_digest:
        raise ValueError("Paper input evidence does not match the published source receipt body")
    insight_body_digest = receipt_body_sha256(render_markdown_artifact("insights", insights))
    sidecar = _PaperInputSidecar.model_validate(
        {**evidence.model_dump(by_alias=True), "insight_body_sha256": insight_body_digest}
    )
    canonical = (
        json.dumps(
            strict_json_loads(sidecar.model_dump_json(by_alias=True)),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if len(canonical.encode("utf-8")) > _MAX_INPUT_EVIDENCE_BYTES:
        raise ValueError("Paper input evidence exceeds its bounded reader size")
    filename = f"paper-input-evidence.{digest}.json"
    path = directory / filename
    with text_write_lock(path):
        if confined_file_identity(path, directory) is None:
            atomic_write_confined_text(path, canonical, directory, exclusive=True)
        elif read_confined_state_bytes(
            path, directory, max_bytes=len(canonical.encode("utf-8"))
        ) != (canonical.encode("utf-8")):
            raise ValueError("Existing content-addressed paper input evidence is corrupt")
    return apply_frontmatter(
        insights,
        {
            "paper_input_evidence": None,
            "paper_input_evidence_schema": "paper-input-evidence.v1",
            "paper_input_evidence_file": filename,
            "paper_input_evidence_sha256": digest,
            "paper_input_coverage": evidence.prompt_chunk_coverage,
            "paper_original_source_completeness": evidence.original_source_completeness,
            "paper_receipt_body_sha256": source_body_digest,
        },
    )


def archive_paper_receipt(directory: Path, source_path: Path) -> Path | None:
    """Retain the exact previous capture before publishing another generation."""
    identity = confined_file_identity(source_path, directory)
    if identity is None:
        return None
    content = read_confined_state_bytes(source_path, directory, max_bytes=identity[3])
    if content is None:
        raise ValueError("Previous paper receipt cannot be safely retained")
    digest = hashlib.sha256(content).hexdigest()
    path = directory / ".history" / "paper-receipts" / f"{digest}.md"
    ensure_confined_parent(path, directory, create=True)
    with text_write_lock(path):
        if confined_file_identity(path, directory) is None:
            atomic_write_confined_bytes(path, content, directory, exclusive=True)
        elif read_confined_state_bytes(path, directory, max_bytes=len(content)) != content:
            raise ValueError("Archived paper receipt is corrupt")
    return path


def paper_input_binding_is_valid(insight_path: Path, content: str, *, root: Path) -> bool:
    """Admit only compact references whose exact retained evidence still exists."""
    fields = extract_frontmatter(content)
    if not _INPUT_REFERENCE_FIELDS.intersection(fields):
        return True
    if not _INPUT_REFERENCE_FIELDS.issubset(fields):
        return False
    digest = fields["paper_input_evidence_sha256"]
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        return False
    expected_filename = f"paper-input-evidence.{digest}.json"
    if fields["paper_input_evidence_file"] != expected_filename:
        return False
    try:
        encoded = read_confined_state_bytes(
            insight_path.parent / expected_filename, root, max_bytes=_MAX_INPUT_EVIDENCE_BYTES
        )
        if encoded is None or hashlib.sha256(encoded).hexdigest() != digest:
            return False
        sidecar = _PaperInputSidecar.model_validate(strict_json_loads(encoded))
    except (OSError, ValueError):
        return False
    return (
        fields["paper_input_evidence_schema"] == sidecar.schema_version
        and fields["paper_input_coverage"] == sidecar.prompt_chunk_coverage
        and fields["paper_original_source_completeness"] == sidecar.original_source_completeness
        and fields.get("paper_receipt_body_sha256") == sidecar.published_receipt_body_sha256
        and sidecar.insight_body_sha256
        == receipt_body_sha256(render_markdown_artifact("insights", content))
    )
