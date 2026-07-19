"""Tests for serialized append-only JSONL writes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import pytest

from distill import jsonl
from distill.library.confined_state import ConfinedStateError


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


def test_append_jsonl_lines_writes_one_contiguous_batch_after_torn_tail(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    path.write_bytes(b'{"torn":')

    jsonl.append_jsonl_lines(path, ['{"index":1}', '{"index":2}'], durable=True)

    assert path.read_bytes() == b'{"torn":\n{"index":1}\n{"index":2}\n'


def test_append_jsonl_lines_validates_complete_batch_before_touching_disk(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"

    with pytest.raises(ValueError, match="one nonempty line"):
        jsonl.append_jsonl_lines(path, ['{"index":1}', "bad\nrow"])

    assert not path.exists()
    assert not path.with_name(f".{path.name}.lock").exists()


@pytest.mark.parametrize("invalid", ["not-json", "[]", '"text"', '{"x":NaN}'])
def test_append_jsonl_lines_rejects_non_object_or_non_strict_json_before_touch(
    tmp_path: Path, invalid: str
) -> None:
    path = tmp_path / "history.jsonl"

    with pytest.raises(ValueError, match="JSONL record 2"):
        jsonl.append_jsonl_lines(path, ['{"index":1}', invalid])

    assert not path.exists()
    assert not path.with_name(f".{path.name}.lock").exists()


def test_append_jsonl_lines_fsyncs_once_per_durable_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    monkeypatch.setattr(jsonl.os, "fsync", calls.append)

    jsonl.append_jsonl_lines(
        tmp_path / "history.jsonl",
        ['{"index":1}', '{"index":2}'],
        durable=True,
    )

    assert len(calls) == 1


def test_append_jsonl_lines_retries_short_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_write_all = jsonl._write_all

    class ShortWriter:
        def __init__(self, writer) -> None:
            self.writer = writer

        def write(self, data: bytes | memoryview) -> int | None:
            return self.writer.write(data[:2])

    def write_in_short_chunks(writer, payload: bytes) -> None:
        real_write_all(ShortWriter(writer), payload)

    monkeypatch.setattr(jsonl, "_write_all", write_in_short_chunks)
    path = tmp_path / "history.jsonl"

    jsonl.append_jsonl_lines(path, ['{"index":1}', '{"index":2}'])

    assert path.read_text(encoding="utf-8").splitlines() == ['{"index":1}', '{"index":2}']


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


def test_append_jsonl_lines_serializes_cross_process_batches(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.jsonl"
    script = "\n".join(
        [
            "import json, sys",
            "from pathlib import Path",
            "from distill.jsonl import append_jsonl_lines",
            "path = Path(sys.argv[1])",
            "worker = int(sys.argv[2])",
            "lines = [json.dumps({'worker': worker, 'index': i}) for i in range(20)]",
            "append_jsonl_lines(path, lines)",
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
    assert len(rows) == 80
    for offset in range(0, 80, 20):
        batch = rows[offset : offset + 20]
        assert [row["index"] for row in batch] == list(range(20))
        assert len({row["worker"] for row in batch}) == 1


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


def test_jsonl_target_rejects_symbolic_link(tmp_path: Path) -> None:
    target = tmp_path / "target.jsonl"
    target.write_text('{"safe":true}\n', encoding="utf-8")
    link = tmp_path / "history.jsonl"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(ValueError, match="link"):
        jsonl.append_jsonl_line(link, '{"unsafe":true}')
    with pytest.raises(jsonl.JsonlIntegrityError, match=str(link).replace("\\", "\\\\")):
        jsonl.read_jsonl_objects_strict(
            link,
            max_file_bytes=1024,
            max_row_bytes=512,
            max_rows=10,
        )

    assert target.read_text(encoding="utf-8") == '{"safe":true}\n'


def test_jsonl_target_rejects_hard_link(tmp_path: Path) -> None:
    target = tmp_path / "target.jsonl"
    target.write_text('{"safe":true}\n', encoding="utf-8")
    link = tmp_path / "history.jsonl"
    try:
        os.link(target, link)
    except OSError:
        pytest.skip("hard links are unavailable")

    with pytest.raises(ValueError, match="multiply linked"):
        jsonl.append_jsonl_line(link, '{"unsafe":true}')
    with pytest.raises(jsonl.JsonlIntegrityError, match="multiply linked"):
        jsonl.read_jsonl_objects_strict(
            link,
            max_file_bytes=1024,
            max_row_bytes=512,
            max_rows=10,
        )


def test_append_rejects_target_swap_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "history.jsonl"
    path.write_text('{"seed":true}\n', encoding="utf-8")
    replacement = tmp_path / "replacement.jsonl"
    replacement.write_text('{"replacement":true}\n', encoding="utf-8")
    real_lstat = Path.lstat
    target_stats = 0

    def swapped_lstat(candidate: Path):
        nonlocal target_stats
        if candidate == path:
            target_stats += 1
            if target_stats >= 2:
                return real_lstat(replacement)
        return real_lstat(candidate)

    monkeypatch.setattr(Path, "lstat", swapped_lstat)

    with pytest.raises(ValueError, match="changed while it was being opened"):
        jsonl.append_jsonl_line(path, '{"unsafe":true}')

    assert path.read_text(encoding="utf-8") == '{"seed":true}\n'
    assert replacement.read_text(encoding="utf-8") == '{"replacement":true}\n'


@pytest.mark.skipif(os.name != "posix", reason="FIFO fixture requires POSIX")
def test_jsonl_target_rejects_special_file(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    os.mkfifo(path)

    with pytest.raises(ValueError, match="non-file"):
        jsonl.append_jsonl_line(path, "{}")


def test_read_jsonl_objects_strict_accepts_complete_bounded_objects(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    path.write_bytes(b'{"first":1}\r\n{"second":2}\n')

    assert jsonl.read_jsonl_objects_strict(
        path,
        max_file_bytes=1024,
        max_row_bytes=512,
        max_rows=10,
    ) == [{"first": 1}, {"second": 2}]


def test_read_jsonl_objects_strict_returns_empty_only_for_missing_file(tmp_path: Path) -> None:
    assert (
        jsonl.read_jsonl_objects_strict(
            tmp_path / "missing.jsonl",
            max_file_bytes=1024,
            max_row_bytes=512,
            max_rows=10,
        )
        == []
    )


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (b'{"valid":true}', "newline-terminated"),
        (b"\n", "row 1 is empty"),
        (b"not-json\n", "not strict JSON"),
        (b"42\n", "not a JSON object"),
        (b'{"value":NaN}\n', "not strict JSON"),
        (b'{"value":"\xff"}\n', "not strict JSON"),
    ],
)
def test_read_jsonl_objects_strict_rejects_incomplete_evidence(
    tmp_path: Path,
    content: bytes,
    reason: str,
) -> None:
    path = tmp_path / "history.jsonl"
    path.write_bytes(content)

    with pytest.raises(jsonl.JsonlIntegrityError) as caught:
        jsonl.read_jsonl_objects_strict(
            path,
            max_file_bytes=1024,
            max_row_bytes=512,
            max_rows=10,
        )

    assert str(path) in str(caught.value)
    assert reason in str(caught.value)


def test_read_jsonl_objects_strict_enforces_each_limit(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    path.write_text('{"first":1}\n{"second":2}\n', encoding="utf-8")

    with pytest.raises(jsonl.JsonlIntegrityError, match="file exceeds"):
        jsonl.read_jsonl_objects_strict(
            path,
            max_file_bytes=10,
            max_row_bytes=512,
            max_rows=10,
        )
    with pytest.raises(jsonl.JsonlIntegrityError, match="row 1 exceeds"):
        jsonl.read_jsonl_objects_strict(
            path,
            max_file_bytes=1024,
            max_row_bytes=5,
            max_rows=10,
        )
    with pytest.raises(jsonl.JsonlIntegrityError, match="row limit"):
        jsonl.read_jsonl_objects_strict(
            path,
            max_file_bytes=1024,
            max_row_bytes=512,
            max_rows=1,
        )


def test_read_jsonl_objects_strict_stops_if_file_grows_past_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "history.jsonl"
    path.write_text('{"first":1}\n', encoding="utf-8")
    admitted_size = path.stat().st_size + 8
    real_lines = jsonl.bounded_jsonl_lines

    def growing_lines(stream, *, max_row_bytes: int):
        for index, row in enumerate(real_lines(stream, max_row_bytes=max_row_bytes)):
            yield row
            if index == 0:
                with path.open("ab") as writer:
                    writer.write(b'{"second":"oversized-growth"}\n')

    monkeypatch.setattr(jsonl, "bounded_jsonl_lines", growing_lines)

    with pytest.raises(jsonl.JsonlIntegrityError, match="file exceeds"):
        jsonl.read_jsonl_objects_strict(
            path,
            max_file_bytes=admitted_size,
            max_row_bytes=512,
            max_rows=10,
        )


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


def test_confined_append_rejects_escaping_target_before_creating_lock(tmp_path: Path) -> None:
    root = tmp_path / "topic"
    root.mkdir()
    outside = tmp_path / "outside.jsonl"

    with pytest.raises(ConfinedStateError, match="escapes"):
        jsonl.append_jsonl_line(
            outside,
            '{"source":"outside"}',
            confinement_root=root,
        )

    assert not outside.exists()
    assert list(root.glob(".distill-jsonl-*.lock")) == []
