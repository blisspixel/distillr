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

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from distill.llm import telemetry as telemetry_module
from distill.llm.telemetry import (
    Telemetry_Record,
    scan_telemetry,
    top_n_by_tokens,
    write_record,
)

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
    # New fields (0.6)
    provider_type=st.sampled_from(["local", "cloud", ""]),
    provider_name=st.sampled_from(["ollama", "lmstudio", "xai", "gemini", "anthropic", ""]),
    tokens_per_second=st.floats(min_value=0.0, max_value=1000.0, allow_nan=False),
    usage_source=st.sampled_from(["reported", "conservative", "unavailable", "unknown"]),
)


# ---------------------------------------------------------------------------
# Property 6: Telemetry JSONL serialization round-trip
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow], deadline=None)
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
        # New fields (0.6)
        assert got.provider_type == record.provider_type
        assert got.provider_name == record.provider_name
        assert got.tokens_per_second == record.tokens_per_second
        assert got.usage_source == record.usage_source


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


def test_unwritable_path_logs_diagnostic_without_raising(tmp_path: Path, caplog: Any) -> None:
    """Unwritable telemetry stays in diagnostics and does not raise."""
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

    with caplog.at_level(logging.DEBUG, logger="distill.llm.telemetry"):
        write_record(bad_ops_dir, record)  # Should not raise

    assert "Failed to write telemetry" in caplog.text


def test_nonfinite_provider_record_is_not_written(tmp_path: Path, caplog: Any) -> None:
    ops_dir = tmp_path / "ops"
    record = Telemetry_Record(
        model="grok-4.3",
        workload_tag="analysis",
        input_tokens=100,
        output_tokens=50,
        elapsed_seconds=float("nan"),
        outcome="success",
    )

    with caplog.at_level(logging.DEBUG, logger="distill.llm.telemetry"):
        write_record(str(ops_dir), record)

    assert not (ops_dir / "telemetry.jsonl").exists()
    assert "Failed to write telemetry" in caplog.text


def test_unexpected_provider_telemetry_failure_is_nonfatal(
    tmp_path: Path,
    caplog: Any,
    monkeypatch,
) -> None:
    def raise_unexpected(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(telemetry_module, "append_jsonl_line", raise_unexpected)
    record = Telemetry_Record(
        model="grok-4.3",
        workload_tag="analysis",
        input_tokens=100,
        output_tokens=50,
        elapsed_seconds=1.0,
        outcome="success",
    )

    with caplog.at_level(logging.DEBUG, logger="distill.llm.telemetry"):
        write_record(str(tmp_path / "ops"), record)

    assert "simulated failure" in caplog.text


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


def test_strict_streaming_reader_isolates_corrupt_and_oversized_rows(
    tmp_path: Path,
    caplog: Any,
    monkeypatch,
) -> None:
    ops_dir = tmp_path / "ops"
    ops_dir.mkdir()
    path = ops_dir / "telemetry.jsonl"
    valid = {
        "model": "grok-4.3",
        "workload_tag": "report",
        "input_tokens": 200,
        "output_tokens": 100,
        "elapsed_seconds": 2.0,
        "outcome": "success",
        "provider_type": "local",
        "tokens_per_second": 50.0,
    }
    invalid_rows = [
        b"[]",
        b"\xff",
        b'{"model":"m","workload_tag":"w","input_tokens":-1,"output_tokens":1,'
        b'"elapsed_seconds":1,"outcome":"success"}',
        b'{"model":"m","workload_tag":"w","input_tokens":1,"output_tokens":1,'
        b'"elapsed_seconds":NaN,"outcome":"success"}',
        b'{"model":"m","workload_tag":"w","input_tokens":true,"output_tokens":1,'
        b'"elapsed_seconds":1,"outcome":"success"}',
        b'{"input_tokens":99999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999}',
        b"x" * (telemetry_module.MAX_TELEMETRY_ROW_BYTES + 1),
    ]
    path.write_bytes(b"\n".join([*invalid_rows, json.dumps(valid).encode("utf-8")]) + b"\n")
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda *args, **kwargs: pytest.fail("provider telemetry must stream"),
    )

    with caplog.at_level(logging.DEBUG, logger="distill.llm.telemetry"):
        scan = scan_telemetry(str(ops_dir), n=10)

    assert [record.workload_tag for record in scan.top_records] == ["report"]
    assert scan.local_records_count == 1
    assert scan.cloud_records_count == 0
    assert scan.malformed_rows == len(invalid_rows)
    assert scan.unreadable is False
    assert "Skipped 7 malformed provider telemetry rows" in caplog.text


def test_streaming_top_n_preserves_file_order_for_equal_totals(tmp_path: Path) -> None:
    ops_dir = str(tmp_path / "ops")
    records = [
        Telemetry_Record(
            model="model",
            workload_tag=tag,
            input_tokens=5,
            output_tokens=5,
            elapsed_seconds=1.0,
            outcome="success",
        )
        for tag in ("first", "second", "third")
    ]
    for record in records:
        write_record(ops_dir, record)

    assert [row.workload_tag for row in top_n_by_tokens(ops_dir, n=2)] == ["first", "second"]
    assert top_n_by_tokens(ops_dir, n=0) == []
    assert top_n_by_tokens(ops_dir, n=-1) == []


def test_streaming_scan_retains_only_requested_rows_across_large_history(tmp_path: Path) -> None:
    ops_dir = tmp_path / "ops"
    ops_dir.mkdir()
    path = ops_dir / "telemetry.jsonl"
    with path.open("w", encoding="utf-8", newline="") as stream:
        for index in range(5_000):
            stream.write(
                json.dumps(
                    {
                        "model": "model",
                        "workload_tag": str(index),
                        "input_tokens": index,
                        "output_tokens": 0,
                        "elapsed_seconds": 1.0,
                        "outcome": "success",
                    }
                )
                + ("\r\n" if index == 0 else "\n")
            )

    scan = scan_telemetry(ops_dir, n=10)

    assert len(scan.top_records) == 10
    assert [row.input_tokens for row in scan.top_records] == list(range(4_999, 4_989, -1))
    assert scan.cloud_records_count == 5_000
    assert scan.malformed_rows == 0


def test_streaming_scan_rejects_nonfinite_aggregate(tmp_path: Path) -> None:
    ops_dir = tmp_path / "ops"
    ops_dir.mkdir()
    path = ops_dir / "telemetry.jsonl"
    row = {
        "model": "local-model",
        "workload_tag": "analysis",
        "input_tokens": 1,
        "output_tokens": 1,
        "elapsed_seconds": 1e308,
        "outcome": "success",
        "provider_type": "local",
        "tokens_per_second": 1e308,
    }
    path.write_text(f"{json.dumps(row)}\n{json.dumps(row)}\n", encoding="utf-8")

    scan = scan_telemetry(ops_dir, n=10)

    assert scan.local_records_count == 1
    assert scan.local_total_seconds == 1e308
    assert scan.total_tokens_per_second == 1e308
    assert scan.malformed_rows == 1
    assert len(scan.top_records) == 1


def test_provider_reader_fails_soft_when_log_cannot_be_opened(
    tmp_path: Path,
    caplog: Any,
) -> None:
    ops_dir = tmp_path / "ops"
    (ops_dir / "telemetry.jsonl").mkdir(parents=True)

    with caplog.at_level(logging.DEBUG, logger="distill.llm.telemetry"):
        scan = scan_telemetry(str(ops_dir), n=10)

    assert scan.top_records == ()
    assert scan.unreadable is True
    assert "Failed to read provider telemetry" in caplog.text


def test_invalid_token_type_lines_are_skipped(tmp_path: Path) -> None:
    """Records with non-numeric token counts are skipped without error."""
    ops_dir = str(tmp_path / "ops")
    Path(ops_dir).mkdir(parents=True, exist_ok=True)
    jsonl_path = Path(ops_dir) / "telemetry.jsonl"

    invalid_record = {
        "model": "grok-4.3",
        "workload_tag": "analysis",
        "input_tokens": "many",
        "output_tokens": 50,
        "elapsed_seconds": 1.0,
        "outcome": "success",
    }
    valid_record = {
        "model": "grok-4.3",
        "workload_tag": "report",
        "input_tokens": 200,
        "output_tokens": 100,
        "elapsed_seconds": 2.0,
        "outcome": "success",
    }
    jsonl_path.write_text(
        json.dumps(invalid_record) + "\n" + json.dumps(valid_record) + "\n",
        encoding="utf-8",
    )

    results = top_n_by_tokens(ops_dir, n=10)

    assert len(results) == 1
    assert results[0].workload_tag == "report"


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


def test_provider_writer_isolates_an_unterminated_tail(tmp_path: Path) -> None:
    ops_dir = tmp_path / "ops"
    ops_dir.mkdir()
    path = ops_dir / "telemetry.jsonl"
    path.write_bytes(b'{"torn":')

    write_record(
        str(ops_dir),
        Telemetry_Record(
            model="grok-4.3",
            workload_tag="analysis",
            input_tokens=100,
            output_tokens=50,
            elapsed_seconds=1.0,
            outcome="success",
        ),
    )

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == '{"torn":'
    assert json.loads(lines[1])["model"] == "grok-4.3"


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


# ---------------------------------------------------------------------------
# Property 11: Telemetry serialization round-trip (local-inference)
# Feature: local-inference, Property 11: Telemetry serialization round-trip
# ---------------------------------------------------------------------------

# Strategy that generates records both with and without new fields
_telemetry_record_with_optional_new_fields_st = st.builds(
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
    timestamp=st.just(""),
    # Mix of populated and empty new fields for backward compat testing
    provider_type=st.sampled_from(["local", "cloud", ""]),
    provider_name=st.sampled_from(["ollama", "lmstudio", "xai", "gemini", ""]),
    tokens_per_second=st.one_of(
        st.just(0.0), st.floats(min_value=0.1, max_value=500.0, allow_nan=False)
    ),
    usage_source=st.sampled_from(["reported", "conservative", "unavailable", "unknown"]),
)


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(record=_telemetry_record_with_optional_new_fields_st)
def test_telemetry_round_trip_with_new_fields(record: Telemetry_Record) -> None:
    """Feature: local-inference, Property 11: Telemetry serialization round-trip

    For any valid Telemetry_Record (including records with the new
    provider_type, provider_name, and tokens_per_second fields, and records
    without them for backward compatibility), serializing to JSON and
    deserializing back shall produce an equivalent record.

    **Validates: Requirements 17.4, 18.7**
    """
    with tempfile.TemporaryDirectory() as tmp:
        ops_dir = str(Path(tmp) / "ops")
        write_record(ops_dir, record)

        results = top_n_by_tokens(ops_dir, n=1)
        assert len(results) == 1
        got = results[0]

        # All original fields preserved
        assert got.model == record.model
        assert got.workload_tag == record.workload_tag
        assert got.input_tokens == record.input_tokens
        assert got.output_tokens == record.output_tokens
        assert got.elapsed_seconds == record.elapsed_seconds
        assert got.outcome == record.outcome
        assert got.call_type == record.call_type
        assert got.error_type == record.error_type
        assert got.run_id == record.run_id
        assert got.timestamp != ""
        # New fields round-trip correctly
        assert got.provider_type == record.provider_type
        assert got.provider_name == record.provider_name
        assert got.tokens_per_second == record.tokens_per_second
        assert got.usage_source == record.usage_source


def test_backward_compat_records_without_new_fields(tmp_path: Path) -> None:
    """Records written without new fields can still be read back."""
    ops_dir = str(tmp_path / "ops")
    Path(ops_dir).mkdir(parents=True, exist_ok=True)
    jsonl_path = Path(ops_dir) / "telemetry.jsonl"

    # Simulate an old record without the new fields
    old_record = {
        "model": "grok-4.3",
        "workload_tag": "analysis",
        "input_tokens": 1000,
        "output_tokens": 500,
        "elapsed_seconds": 2.5,
        "outcome": "success",
        "call_type": "paper",
        "error_type": "",
        "run_id": "abc123",
        "timestamp": "2026-01-01T00:00:00Z",
    }
    jsonl_path.write_text(json.dumps(old_record) + "\n", encoding="utf-8")

    results = top_n_by_tokens(ops_dir, n=1)
    assert len(results) == 1
    got = results[0]
    assert got.model == "grok-4.3"
    # New fields should default to empty/zero
    assert got.provider_type == ""
    assert got.provider_name == ""
    assert got.tokens_per_second == 0.0
    assert got.usage_source == "unknown"
