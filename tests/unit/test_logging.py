from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from distill import _logging


@pytest.fixture()
def distill_logger() -> Iterator[logging.Logger]:
    logger = logging.getLogger("distill")
    previous_handlers = list(logger.handlers)
    previous_level = logger.level
    previous_propagate = logger.propagate
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    yield logger

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    for handler in previous_handlers:
        logger.addHandler(handler)
    logger.setLevel(previous_level)
    logger.propagate = previous_propagate


def test_debug_records_write_to_file_when_console_is_warning(
    distill_logger: logging.Logger, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _logging.configure_logging(debug=False, ops_dir=tmp_path)

    logging.getLogger("distill.tests").debug("debug-only-file")
    _flush(distill_logger)

    assert "debug-only-file" in (tmp_path / "distill.log").read_text(encoding="utf-8")
    assert "debug-only-file" not in capsys.readouterr().err


def test_late_ops_dir_adds_file_handler(distill_logger: logging.Logger, tmp_path: Path) -> None:
    _logging.configure_logging(debug=False, ops_dir=None)
    _logging.configure_logging(debug=False, ops_dir=tmp_path)

    logging.getLogger("distill.tests").debug("late-file-handler")
    _flush(distill_logger)

    assert "late-file-handler" in (tmp_path / "distill.log").read_text(encoding="utf-8")


def test_reconfigure_retargets_file_handler(distill_logger: logging.Logger, tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    _logging.configure_logging(debug=False, ops_dir=first)
    _logging.configure_logging(debug=False, ops_dir=second)

    logging.getLogger("distill.tests").debug("second-log-only")
    _flush(distill_logger)

    assert "second-log-only" in (second / "distill.log").read_text(encoding="utf-8")
    assert "second-log-only" not in (first / "distill.log").read_text(encoding="utf-8")
    assert _file_handler_paths(distill_logger) == [second / "distill.log"]


def _flush(logger: logging.Logger) -> None:
    for handler in logger.handlers:
        handler.flush()


def _file_handler_paths(logger: logging.Logger) -> list[Path]:
    return [
        Path(handler.baseFilename)
        for handler in logger.handlers
        if isinstance(handler, logging.FileHandler)
    ]
