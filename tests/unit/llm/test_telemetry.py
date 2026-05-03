# pyright: strict
"""Property and unit tests for the telemetry module.

Feature: llm-router-model-upgrade
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from distill.llm.telemetry import Telemetry_Record, top_n_by_tokens, write_record

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_safe_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
    min_size=1,
    max_size=30,
)

_telemetry_record_st = st.builds(
    Telemetry_Record,
    model=_safe_text,
    workload_tag=st.sampled_from(["analysis", "rerank", "synthesis", "site", "qa"]),
    input_tokens=st.integers(min_value=0, max_value=10_000_000),
    output_tokens=st.integers(min_value=0, max_value=10_000_000),
    elapsed_seconds=st.floats(min_value=0.0, max_value=600.0, allow_nan=False),
    outcome=st.sampled_from(["success", "error"]),
    call_type=st.from_regex(r"[a-z0-9_]{0,10}", fullmatch=True),
    error_type=st.from_regex(r"[a-zA-Z]{0,10}", fullmatch=True),
    run_id=st.from_regex(r"[a-f0-9]{0,16}", fullmatch=True),
    # timestamp is set by write_record, leave empty
    timestamp=st.just(""),
)


# ---------------------------------------------------------------------------
# Property 6: Telemetry JSONL serialization round-trip
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(record=_telemetry_record_st)
def test_jsonl_round_trip(record: Telemetry_Record) -> None:
    """Feature: llm-router-model-upgrade, Property 6: Telemetry JSONL round-trip

    Write a Telemetry_Record via write_record(), read it back via
    top_n_by_tokens(), and assert field equivalence (except timestamp,
    which is set at write time).

    **Validates: Requirements 6.2**
    """
    with tempfile.TemporaryDirectory() as tmp:
        ops_dir = str(Path(tmp) / "ops")
        write_record(ops_dir, record)

        results = top_n_by_tokens(ops_dir, n=1)
        assert len(results) == 1
        got = results[0]

        assert got.model == record.model
        assert got.workload_tag == record.workload_tag
        assert got.input_tokens == record.input_tokens
        assert got.output_tokens == record.output_tokens
        assert got.elapsed_seconds == record.elapsed_seconds
        assert got.outcome == record.outcome
        assert got.call_type == record.call_type
        assert got.error_type == record.error_type
        assert got.run_id == record.run_id
        # timestamp is set by write_record — just verify it's non-empty
        assert got.timestamp != ""


# ---------------------------------------------------------------------------
# Property 7: Top-N telemetry query ordering
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    records=st.lists(_telemetry_record_st, min_size=1, max_size=20),
    n=st.integers(min_value=1, max_value=30),
)
def test_top_n_ordering(records: list[Telemetry_Record], n: int) -> None:
    """Feature: llm-router-model-upgrade, Property 7: Top-N telemetry ordering

    Write a list of records, call top_n_by_tokens, and assert results are
    sorted descending by (input_tokens + output_tokens) with correct length.

    **Validates: Requirements 6.3**
    """
    with tempfile.TemporaryDirectory() as tmp:
        ops_dir = str(Path(tmp) / "ops")
        for rec in records:
            write_record(ops_dir, rec)

        results = top_n_by_tokens(ops_dir, n=n)

        # Length is min(n, total_records)
        assert len(results) == min(n, len(records))

        # Descending order by total tokens
        for i in range(len(results) - 1):
            total_a = results[i].input_tokens + results[i].output_tokens
            total_b = results[i + 1].input_tokens + results[i + 1].output_tokens
            assert total_a >= total_b


# ---------------------------------------------------------------------------
# Unit tests — telemetry error resilience
# ---------------------------------------------------------------------------


def test_unwritable_path_logs_warning(tmp_path: Path, caplog: Any) -> None:
    """Unwritable path logs a warning without raising."""
    # Use a path that cannot be created (file where dir expected)
    blocker = tmp_path / "blocker"
    blocker.write_text("I am a file", encoding="utf-8")
    bad_ops_dir = str(blocker / "subdir")

    record = Telemetry_Record(
        model="grok-4.3",
        workload_tag="analysis",
        input_tokens=100,
        output_tokens=50,
        elapsed_seconds=1.0,
        outcome="success",
    )

    with caplog.at_level(logging.WARNING, logger="distill.llm.telemetry"):
        write_record(bad_ops_dir, record)  # Should not raise

    assert "Failed to write telemetry" in caplog.text


def test_malformed_jsonl_lines_are_skipped(tmp_path: Path) -> None:
    """Malformed JSONL lines are skipped without error."""
    ops_dir = str(tmp_path / "ops")
    Path(ops_dir).mkdir(parents=True, exist_ok=True)
    jsonl_path = Path(ops_dir) / "telemetry.jsonl"

    good_record = {
        "model": "grok-4.3",
        "workload_tag": "analysis",
        "input_tokens": 100,
        "output_tokens": 50,
        "elapsed_seconds": 1.0,
        "outcome": "success",
        "call_type": "",
        "error_type": "",
        "run_id": "",
        "timestamp": "2026-01-01T00:00:00Z",
    }

    lines = [
        "this is not json",
        json.dumps(good_record),
        "{bad json",
        "",
    ]
    jsonl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    results = top_n_by_tokens(ops_dir, n=10)
    assert len(results) == 1
    assert results[0].model == "grok-4.3"


def test_ops_dir_auto_creation(tmp_path: Path) -> None:
    """ops_dir is created automatically on first write."""
    ops_dir = str(tmp_path / "new" / "nested" / "ops")
    assert not Path(ops_dir).exists()

    record = Telemetry_Record(
        model="grok-4.3",
        workload_tag="analysis",
        input_tokens=100,
        output_tokens=50,
        elapsed_seconds=1.0,
        outcome="success",
    )
    write_record(ops_dir, record)

    assert Path(ops_dir).exists()
    assert (Path(ops_dir) / "telemetry.jsonl").exists()


def test_empty_ops_dir_skips_write() -> None:
    """write_record with empty ops_dir is a no-op."""
    record = Telemetry_Record(
        model="grok-4.3",
        workload_tag="analysis",
        input_tokens=100,
        output_tokens=50,
        elapsed_seconds=1.0,
        outcome="success",
    )
    # Should not raise
    write_record("", record)


def test_top_n_nonexistent_dir(tmp_path: Path) -> None:
    """top_n_by_tokens returns empty list when ops_dir doesn't exist."""
    results = top_n_by_tokens(str(tmp_path / "nonexistent"), n=10)
    assert results == []
