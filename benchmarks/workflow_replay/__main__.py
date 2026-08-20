# pyright: strict
"""Repository-only entry point for frozen workflow replay."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping, Sequence
from typing import cast

from benchmarks.workflow_replay.operations import OPERATION_NAMES
from benchmarks.workflow_replay.runner import (
    DEFAULT_TIMEOUT_SECONDS,
    run_workflow_replay,
)
from benchmarks.workflow_replay.workspace import temporary_workspace


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("cannot be negative")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Replay Distill paper, video, site, synthesis, and verify paths against "
            "frozen receipts and a deterministic model stub. No user library, "
            "network, or live model is used."
        )
    )
    parser.add_argument("--iterations", type=_positive_int, default=5)
    parser.add_argument("--warmups", type=_non_negative_int, default=1)
    parser.add_argument(
        "--operation",
        action="append",
        choices=OPERATION_NAMES,
        help="Run only this operation. Repeat to select more than one.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=_positive_float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Maximum wall time for each fresh worker sample.",
    )
    parser.add_argument(
        "--wait-ns",
        type=_non_negative_int,
        default=0,
        help="Simulated provider wait injected into each stubbed model call.",
    )
    return parser


def _result_exit_code(result: dict[str, object]) -> int:
    source = result.get("source_integrity")
    operations = result.get("operations")
    source_ok = False
    if isinstance(source, dict):
        source_ok = cast("Mapping[str, object]", source).get("unchanged") is True
    if not isinstance(operations, list):
        return 1
    for raw_row in cast("list[object]", operations):
        if not isinstance(raw_row, dict):
            return 1
        if cast("Mapping[str, object]", raw_row).get("status") != "ok":
            return 1
    return 0 if source_ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    with temporary_workspace() as workspace:
        result = run_workflow_replay(
            workspace,
            iterations=args.iterations,
            warmups=args.warmups,
            operations=args.operation,
            timeout_seconds=args.timeout_seconds,
            wait_ns=args.wait_ns,
        )
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    return _result_exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
