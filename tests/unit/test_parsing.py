"""Contracts for total structural text parsers."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from distill.parsing import (
    as_whole_number,
    is_recent_iso_timestamp,
    parse_ascii_uint,
    parse_bounded_json_int,
    parse_iso_day_hour_duration,
    read_bounded_json_object,
    read_bounded_jsonl_objects,
    read_local_utf8_text,
    strict_json_loads,
)


def test_is_recent_iso_timestamp_accepts_current_and_recent_values() -> None:
    now = datetime(2026, 8, 22, 12, 0, 0)

    assert is_recent_iso_timestamp(now.isoformat(), now=now, max_age=timedelta(hours=24))
    assert is_recent_iso_timestamp(
        (now - timedelta(hours=23, minutes=59)).isoformat(),
        now=now,
        max_age=timedelta(hours=24),
    )


def test_is_recent_iso_timestamp_rejects_future_expired_and_invalid_values() -> None:
    now = datetime(2026, 8, 22, 12, 0, 0)
    max_age = timedelta(hours=24)

    assert not is_recent_iso_timestamp(
        (now + timedelta(seconds=1)).isoformat(), now=now, max_age=max_age
    )
    assert not is_recent_iso_timestamp((now - max_age).isoformat(), now=now, max_age=max_age)
    assert not is_recent_iso_timestamp("not-a-date", now=now, max_age=max_age)
    assert not is_recent_iso_timestamp(None, now=now, max_age=max_age)
    assert not is_recent_iso_timestamp(now.isoformat(), now=now, max_age=timedelta(0))


def test_is_recent_iso_timestamp_handles_offsets_and_mixed_awareness() -> None:
    aware_now = datetime(2026, 8, 22, 12, 0, 0, tzinfo=UTC)
    naive_now = aware_now.replace(tzinfo=None)
    max_age = timedelta(hours=24)

    assert is_recent_iso_timestamp("2026-08-22T11:00:00Z", now=aware_now, max_age=max_age)
    assert not is_recent_iso_timestamp("2026-08-22T11:00:00Z", now=naive_now, max_age=max_age)
    assert not is_recent_iso_timestamp("2026-08-22T11:00:00", now=aware_now, max_age=max_age)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0", 0),
        ("0012", 12),
        ("42", 42),
        ("", None),
        (" 1", None),
        ("-1", None),
        ("1.0", None),
        ("\u00b2", None),
        ("\u0661\u0662", None),
        ("\uff11\uff12", None),
    ],
)
def test_parse_ascii_uint(raw: str, expected: int | None) -> None:
    assert parse_ascii_uint(raw) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (5, 5),
        (5.0, 5),
        (0.0, 0),
        (-3.0, -3),
        (5.5, None),
        (True, None),
        (False, None),
        ("5", None),
        (float("nan"), None),
        (float("inf"), None),
        (None, None),
    ],
)
def test_as_whole_number(value: object, expected: int | None) -> None:
    assert as_whole_number(value) == expected


def test_default_library_dir_survives_missing_home(tmp_path, monkeypatch) -> None:
    from distill.parsing import default_library_dir

    site = tmp_path / "site-packages" / "distill"
    site.mkdir(parents=True)

    def boom(_cls):
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.setattr(Path, "home", classmethod(boom))
    monkeypatch.chdir(tmp_path)

    assert default_library_dir(site) == tmp_path / ".distill" / "library"


def test_parse_ascii_uint_rejects_conversion_limit_input() -> None:
    assert parse_ascii_uint("9" * 5000) is None


def test_parse_ascii_uint_keeps_its_own_cap_when_interpreter_cap_is_disabled() -> None:
    if not hasattr(sys, "set_int_max_str_digits"):
        pytest.skip("interpreter does not expose the integer conversion limit")
    previous = sys.get_int_max_str_digits()
    try:
        sys.set_int_max_str_digits(0)
        assert parse_ascii_uint("9" * 1_000_000) is None
    finally:
        sys.set_int_max_str_digits(previous)


def test_bounded_json_integer_supports_sign_and_rejects_oversized_values() -> None:
    assert parse_bounded_json_int("42") == 42
    assert parse_bounded_json_int("-42") == -42
    with pytest.raises(ValueError, match="digit bound"):
        parse_bounded_json_int("9" * 101)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("P0D", timedelta(0)),
        ("P7D", timedelta(days=7)),
        ("PT12H", timedelta(hours=12)),
        ("P1DT25H", timedelta(days=2, hours=1)),
        ("", None),
        ("P", None),
        ("P1DT", None),
        ("P\u0661D", None),
        ("P" + "9" * 100 + "D", None),
        ("P" + "9" * 5000 + "D", None),
    ],
)
def test_parse_iso_day_hour_duration(raw: str, expected: timedelta | None) -> None:
    assert parse_iso_day_hour_duration(raw) == expected


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity", "1e999", "9" * 101])
def test_strict_json_rejects_nonfinite_and_oversized_numbers(raw: str) -> None:
    with pytest.raises(ValueError):
        strict_json_loads(f'{{"number":{raw}}}')


def test_bounded_json_object_returns_empty_for_unsafe_inputs(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text('{"ok":true}', encoding="utf-8")
    assert read_bounded_json_object(path, max_bytes=64) == {"ok": True}
    assert read_bounded_json_object(path, max_bytes=0) == {}

    path.write_text("[]", encoding="utf-8")
    assert read_bounded_json_object(path, max_bytes=64) == {}
    path.write_text('{"payload":"too long"}', encoding="utf-8")
    assert read_bounded_json_object(path, max_bytes=4) == {}
    assert read_bounded_json_object(tmp_path / "missing.json", max_bytes=64) == {}


def test_bounded_jsonl_keeps_only_complete_strict_object_rows(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_bytes(b'{"discarded":0}\n{"kept":1}\nNaN\n[]\n{"kept":2}\n')

    assert read_bounded_jsonl_objects(path, max_bytes=35, max_rows=10) == [
        {"kept": 1},
        {"kept": 2},
    ]
    assert read_bounded_jsonl_objects(path, max_bytes=35, max_rows=1) == [{"kept": 2}]
    assert read_bounded_jsonl_objects(path, max_bytes=0, max_rows=10) == []
    assert read_bounded_jsonl_objects(path, max_bytes=35, max_rows=0) == []
    assert read_bounded_jsonl_objects(tmp_path / "missing.jsonl", max_bytes=35, max_rows=10) == []


def test_bounded_jsonl_drops_truncated_tail_without_a_newline(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_bytes(b'{"prefix":"larger-than-window"}')

    assert read_bounded_jsonl_objects(path, max_bytes=5, max_rows=10) == []


def test_read_local_utf8_text_returns_none_for_unreadable_files(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_text("hello", encoding="utf-8")
    assert read_local_utf8_text(path) == "hello"
    path.write_bytes(b"\xff\xfe")
    assert read_local_utf8_text(path) is None
    assert read_local_utf8_text(tmp_path / "missing.md") is None
