"""Tests for the scratch-only bounded HTML parsing worker."""

from __future__ import annotations

import runpy
import sys
from io import BytesIO
from pathlib import Path

import pytest

from distill.ingestors.local import _html_worker


class _FakeStdin:
    """Minimal stand-in for ``sys.stdin`` exposing a byte ``.buffer``."""

    def __init__(self, gate: bytes) -> None:
        self.buffer = BytesIO(gate)


def _set_argv(
    monkeypatch: pytest.MonkeyPatch,
    source: Path,
    destination: Path,
    max_chars: str,
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["_html_worker", str(source), str(destination), max_chars]
    )


def test_main_success_writes_extracted_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "page.html"
    source.write_text("<html><body><p>Hello world</p></body></html>", encoding="utf-8")
    destination = tmp_path / "out.txt"
    _set_argv(monkeypatch, source, destination, "1000")
    monkeypatch.setattr(sys, "stdin", _FakeStdin(b"1"))

    assert _html_worker.main() == 0
    assert "Hello world" in destination.read_text(encoding="utf-8")


def test_main_wrong_argv_count_returns_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["_html_worker", "only-one-arg"])
    assert _html_worker.main() == 2


def test_main_non_positive_max_chars_returns_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "page.html"
    source.write_text("<p>hi</p>", encoding="utf-8")
    destination = tmp_path / "out.txt"
    _set_argv(monkeypatch, source, destination, "0")
    monkeypatch.setattr(sys, "stdin", _FakeStdin(b"1"))

    assert _html_worker.main() == 2
    assert not destination.exists()


def test_main_missing_stdin_gate_returns_3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "page.html"
    source.write_text("<p>hi</p>", encoding="utf-8")
    destination = tmp_path / "out.txt"
    _set_argv(monkeypatch, source, destination, "1000")
    monkeypatch.setattr(sys, "stdin", _FakeStdin(b"0"))

    assert _html_worker.main() == 3
    assert not destination.exists()


def test_main_oversized_input_returns_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "page.html"
    source.write_text("<p>" + "x" * 100 + "</p>", encoding="utf-8")
    destination = tmp_path / "out.txt"
    _set_argv(monkeypatch, source, destination, "1000")
    monkeypatch.setattr(sys, "stdin", _FakeStdin(b"1"))
    # Shrink the byte cap so the modest fixture trips the oversize guard.
    monkeypatch.setattr(_html_worker, "HTML_WORKER_INPUT_BYTES", 5)

    assert _html_worker.main() == 1
    assert not destination.exists()


def test_main_bad_max_chars_value_returns_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "page.html"
    source.write_text("<p>hi</p>", encoding="utf-8")
    destination = tmp_path / "out.txt"
    _set_argv(monkeypatch, source, destination, "not-a-number")
    monkeypatch.setattr(sys, "stdin", _FakeStdin(b"1"))

    assert _html_worker.main() == 1
    assert not destination.exists()


def test_module_main_guard_exits_with_status(monkeypatch: pytest.MonkeyPatch) -> None:
    # Exercise the ``__main__`` guard in-process: too few argv -> main() == 2,
    # which the guard re-raises as SystemExit(2).
    monkeypatch.setattr(sys, "argv", ["_html_worker"])
    # Drop the cached import so runpy executes the module fresh under __main__
    # (avoids a "found in sys.modules" RuntimeWarning).
    monkeypatch.delitem(sys.modules, "distill.ingestors.local._html_worker", raising=False)
    with pytest.raises(SystemExit) as raised:
        runpy.run_module("distill.ingestors.local._html_worker", run_name="__main__")
    assert raised.value.code == 2
