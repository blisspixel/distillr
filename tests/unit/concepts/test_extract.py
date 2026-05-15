"""Unit tests for distill.concepts.extract.

The extraction layer wraps an LLM call. Tests mock the LLM at the
``llm_call`` boundary and exercise the parser + validation paths.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from distill.concepts.extract import extract_from_insight
from distill.concepts.records import ConceptKind, Polarity
from distill.llm import RouterConfig


class _StubResponse:
    """Minimal duck-type matching LLM_Response for the bits we use."""

    def __init__(self, text: str, model: str = "grok-4.3") -> None:
        self.text = text
        self.model = model
        self.input_tokens = 100
        self.output_tokens = 50


def _write_insight(tmp_path: Path, content: str = "# Sample insight\n\nbody") -> Path:
    path = tmp_path / "papers" / "sample" / "sample_Insights.md"
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    return path


def _valid_row(**overrides) -> dict:
    base = {
        "name": "Rotational Embeddings",
        "normalized_name": "rotational embeddings",
        "kind": "technique",
        "polarity": "helpful",
        "claim_excerpt": "Rotation beats discrete timestamps.",
        "evidence_type": "empirical_result",
    }
    base.update(overrides)
    return base


@pytest.fixture
def rc() -> RouterConfig:
    return RouterConfig()


class TestExtractFromInsight:
    def test_happy_path(self, tmp_path: Path, rc: RouterConfig) -> None:
        path = _write_insight(tmp_path)
        rows = [_valid_row(), _valid_row(name="EST", normalized_name="est", kind="architecture")]
        with patch(
            "distill.concepts.extract.llm_call",
            return_value=_StubResponse(json.dumps(rows)),
        ):
            result = extract_from_insight(
                path,
                topic="tkg",
                source_id="2604.11544",
                artifact_path="papers/sample/sample_Insights.md",
                rc=rc,
                now_iso="2026-05-15T10:00:00Z",
            )
        assert len(result.mentions) == 2
        assert result.mentions[0].name == "Rotational Embeddings"
        assert result.mentions[0].kind == ConceptKind.TECHNIQUE
        assert result.mentions[0].polarity == Polarity.HELPFUL
        assert result.mentions[0].source_id == "2604.11544"
        assert result.mentions[0].artifact_path == "papers/sample/sample_Insights.md"
        assert result.mentions[0].extracted_at == "2026-05-15T10:00:00Z"
        assert result.skipped_rows == []

    def test_provenance_captured(self, tmp_path: Path, rc: RouterConfig) -> None:
        path = _write_insight(tmp_path)
        with patch(
            "distill.concepts.extract.llm_call",
            return_value=_StubResponse(json.dumps([_valid_row()]), model="grok-4.3"),
        ):
            result = extract_from_insight(
                path,
                topic="tkg",
                source_id="X",
                artifact_path="papers/x/x_Insights.md",
                rc=rc,
            )
        assert result.model == "grok-4.3"
        assert result.prompt_id == "concepts.extract.v1"
        assert result.provenance == {
            "model": "grok-4.3",
            "model_version": "grok-4.3",
            "prompt_id": "concepts.extract.v1",
        }

    def test_empty_array_response(self, tmp_path: Path, rc: RouterConfig) -> None:
        path = _write_insight(tmp_path)
        with patch(
            "distill.concepts.extract.llm_call",
            return_value=_StubResponse("[]"),
        ):
            result = extract_from_insight(
                path,
                topic="tkg",
                source_id="X",
                artifact_path="papers/x/x_Insights.md",
                rc=rc,
            )
        assert result.mentions == []

    def test_invalid_kind_skipped(self, tmp_path: Path, rc: RouterConfig) -> None:
        path = _write_insight(tmp_path)
        rows = [_valid_row(), _valid_row(name="Bogus", kind="not_a_kind")]
        with patch(
            "distill.concepts.extract.llm_call",
            return_value=_StubResponse(json.dumps(rows)),
        ):
            result = extract_from_insight(
                path,
                topic="tkg",
                source_id="X",
                artifact_path="p.md",
                rc=rc,
            )
        assert len(result.mentions) == 1
        assert len(result.skipped_rows) == 1

    def test_invalid_polarity_skipped(self, tmp_path: Path, rc: RouterConfig) -> None:
        path = _write_insight(tmp_path)
        rows = [_valid_row(polarity="maybe")]
        with patch(
            "distill.concepts.extract.llm_call",
            return_value=_StubResponse(json.dumps(rows)),
        ):
            result = extract_from_insight(
                path,
                topic="tkg",
                source_id="X",
                artifact_path="p.md",
                rc=rc,
            )
        assert result.mentions == []
        assert len(result.skipped_rows) == 1

    def test_missing_required_field_skipped(self, tmp_path: Path, rc: RouterConfig) -> None:
        path = _write_insight(tmp_path)
        rows = [
            {"name": "X", "kind": "technique", "polarity": "helpful"}
        ]  # missing normalized_name
        with patch(
            "distill.concepts.extract.llm_call",
            return_value=_StubResponse(json.dumps(rows)),
        ):
            result = extract_from_insight(
                path,
                topic="tkg",
                source_id="X",
                artifact_path="p.md",
                rc=rc,
            )
        assert result.mentions == []
        assert len(result.skipped_rows) == 1

    def test_non_list_response_skipped(self, tmp_path: Path, rc: RouterConfig) -> None:
        path = _write_insight(tmp_path)
        with patch(
            "distill.concepts.extract.llm_call",
            return_value=_StubResponse('{"not": "a list"}'),
        ):
            result = extract_from_insight(
                path,
                topic="tkg",
                source_id="X",
                artifact_path="p.md",
                rc=rc,
            )
        assert result.mentions == []
        assert result.skipped_rows  # non-empty

    def test_json_in_markdown_code_block(self, tmp_path: Path, rc: RouterConfig) -> None:
        # extract_json tolerates ```json ... ``` wrapping; verify pass-through works
        path = _write_insight(tmp_path)
        wrapped = f"```json\n{json.dumps([_valid_row()])}\n```"
        with patch(
            "distill.concepts.extract.llm_call",
            return_value=_StubResponse(wrapped),
        ):
            result = extract_from_insight(
                path,
                topic="tkg",
                source_id="X",
                artifact_path="p.md",
                rc=rc,
            )
        assert len(result.mentions) == 1

    def test_non_dict_array_member_skipped(self, tmp_path: Path, rc: RouterConfig) -> None:
        path = _write_insight(tmp_path)
        rows = [_valid_row(), "not a dict", 42]
        with patch(
            "distill.concepts.extract.llm_call",
            return_value=_StubResponse(json.dumps(rows)),
        ):
            result = extract_from_insight(
                path,
                topic="tkg",
                source_id="X",
                artifact_path="p.md",
                rc=rc,
            )
        assert len(result.mentions) == 1
        assert len(result.skipped_rows) == 2

    def test_missing_insight_file_raises(self, tmp_path: Path, rc: RouterConfig) -> None:
        missing = tmp_path / "missing.md"
        with pytest.raises(FileNotFoundError):
            extract_from_insight(
                missing,
                topic="tkg",
                source_id="X",
                artifact_path="p.md",
                rc=rc,
            )

    def test_tracker_records_token_usage(self, tmp_path: Path, rc: RouterConfig) -> None:
        from distill.pipeline.costs import CostTracker

        path = _write_insight(tmp_path)
        tracker = CostTracker()
        with patch(
            "distill.concepts.extract.llm_call",
            return_value=_StubResponse("[]"),
        ):
            extract_from_insight(
                path,
                topic="tkg",
                source_id="X",
                artifact_path="p.md",
                rc=rc,
                tracker=tracker,
            )
        assert any(u.call_type == "concepts_extract" for u in tracker.entries)

    def test_normalized_name_forced_lowercase(self, tmp_path: Path, rc: RouterConfig) -> None:
        path = _write_insight(tmp_path)
        rows = [_valid_row(normalized_name="MIXED Case Concept")]
        with patch(
            "distill.concepts.extract.llm_call",
            return_value=_StubResponse(json.dumps(rows)),
        ):
            result = extract_from_insight(
                path,
                topic="tkg",
                source_id="X",
                artifact_path="p.md",
                rc=rc,
            )
        assert result.mentions[0].normalized_name == "mixed case concept"
