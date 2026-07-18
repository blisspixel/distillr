"""Tests for serialized append-only JSONL writes."""

from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import pytest

from distill import jsonl


def test_bounded_jsonl_lines_preserves_crlf_and_recovers_after_oversized_row() -> None:
    stream = BytesIO(b'{"first":1}\r\n' + b"x" * 12 + b'\n{"last":2}')

    assert list(jsonl.bounded_jsonl_lines(stream, max_row_bytes=11)) == [
        b'{"first":1}',
        None,
        b'{"last":2}',
    ]


def test_bounded_jsonl_lines_accepts_exact_limit_and_rejects_invalid_limit() -> None:
    assert list(jsonl.bounded_jsonl_lines(BytesIO(b"1234\n"), max_row_bytes=4)) == [b"1234"]

    with pytest.raises(ValueError, match="must be positive"):
        list(jsonl.bounded_jsonl_lines(BytesIO(), max_row_bytes=0))


@pytest.mark.parametrize(
    ("initial", "expected"),
    [
        (b"", b'{"row":1}\n'),
        (b'{"seed":0}\n', b'{"seed":0}\n{"row":1}\n'),
        (b'{"torn":', b'{"torn":\n{"row":1}\n'),
    ],
)
def test_append_jsonl_line_preserves_boundaries(
    tmp_path: Path,
    initial: bytes,
    expected: bytes,
) -> None:
    path = tmp_path / "ops" / "telemetry.jsonl"
    path.parent.mkdir()
    path.write_bytes(initial)

    jsonl.append_jsonl_line(path, '{"row":1}')

    assert path.read_bytes() == expected
    assert path.with_name(f".{path.name}.lock").is_file()


def test_append_jsonl_line_serializes_concurrent_writers(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.jsonl"

    def append(index: int) -> None:
        jsonl.append_jsonl_line(path, json.dumps({"index": index}, separators=(",", ":")))

    with ThreadPoolExecutor(max_workers=12) as executor:
        list(executor.map(append, range(100)))

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 100
    assert {row["index"] for row in rows} == set(range(100))


def test_append_jsonl_line_serializes_cross_process_writers(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.jsonl"
    script = "\n".join(
        [
            "import json, sys",
            "from pathlib import Path",
            "from distill.jsonl import append_jsonl_line",
            "path = Path(sys.argv[1])",
            "worker = int(sys.argv[2])",
            "for index in range(25):",
            "    append_jsonl_line(path, json.dumps({'worker': worker, 'index': index}))",
        ]
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(path), str(worker)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for worker in range(4)
    ]

    failures: list[str] = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=20)
        if process.returncode:
            failures.append(f"exit={process.returncode} stdout={stdout!r} stderr={stderr!r}")

    assert failures == []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 100
    assert {(row["worker"], row["index"]) for row in rows} == {
        (worker, index) for worker in range(4) for index in range(25)
    }


def test_append_jsonl_line_locked_can_share_a_larger_transaction(tmp_path: Path) -> None:
    path = tmp_path / "cost_log.jsonl"

    with jsonl.jsonl_append_lock(path):
        path.write_text('{"legacy":true}', encoding="utf-8")
        jsonl.append_jsonl_line_locked(path, '{"current":true}', durable=False)

    assert path.read_text(encoding="utf-8").splitlines() == [
        '{"legacy":true}',
        '{"current":true}',
    ]


def test_append_jsonl_line_rejects_non_record_text(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.jsonl"

    for invalid in ("", "{}\n{}", "{}\r{}"):
        with pytest.raises(ValueError, match="one nonempty line"):
            jsonl.append_jsonl_line(path, invalid)

    assert not path.exists()


def test_append_jsonl_line_fsyncs_only_durable_records(tmp_path: Path, monkeypatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(jsonl.os, "fsync", calls.append)

    jsonl.append_jsonl_line(tmp_path / "telemetry.jsonl", "{}")
    assert calls == []

    jsonl.append_jsonl_line(tmp_path / "cost_log.jsonl", "{}", durable=True)
    assert len(calls) == 1


def test_write_all_retries_short_writes() -> None:
    class ShortWriter:
        def __init__(self) -> None:
            self.content = bytearray()

        def write(self, data: bytes | memoryview) -> int:
            chunk = bytes(data[:2])
            self.content.extend(chunk)
            return len(chunk)

    writer = ShortWriter()

    jsonl._write_all(writer, b"abcdef")

    assert writer.content == b"abcdef"


@pytest.mark.parametrize("reported", [None, 0, -1, 7])
def test_write_all_rejects_invalid_write_counts(reported: int | None) -> None:
    class StalledWriter:
        def write(self, data: bytes | memoryview) -> int | None:
            return reported

    with pytest.raises(OSError, match="complete JSONL row"):
        jsonl._write_all(StalledWriter(), b"record")
