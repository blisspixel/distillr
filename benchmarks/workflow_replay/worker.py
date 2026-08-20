# pyright: strict
"""Private one-operation worker for process-isolated workflow replay samples."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from benchmarks.workflow_replay.netguard import install_network_guard
from benchmarks.workflow_replay.operations import OPERATION_NAMES, operation_by_name
from benchmarks.workflow_replay.runner import WORKER_RESULT_SCHEMA_VERSION, measure_operation
from benchmarks.workflow_replay.workspace import load_workspace


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Internal Distill workflow replay worker")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--worker-token", required=True)
    parser.add_argument("--operation", choices=OPERATION_NAMES, required=True)
    parser.add_argument("--wait-ns", type=int, default=0)
    return parser


def _emit(value: object) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.wait_ns < 0:
        _emit(
            {
                "schema_version": WORKER_RESULT_SCHEMA_VERSION,
                "operation": args.operation,
                "status": "error",
                "error": {"type": "ValueError", "message": "wait_ns cannot be negative"},
            }
        )
        return 1
    try:
        install_network_guard()
        workspace = load_workspace(args.workspace, args.worker_token)
        operation = operation_by_name(
            workspace.library_root,
            args.operation,
            wait_ns=args.wait_ns,
        )
        sample, _ = measure_operation(operation)
    except Exception as exc:
        _emit(
            {
                "schema_version": WORKER_RESULT_SCHEMA_VERSION,
                "operation": args.operation,
                "status": "error",
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
        )
        return 1
    _emit(
        {
            "schema_version": WORKER_RESULT_SCHEMA_VERSION,
            "operation": args.operation,
            "status": "ok",
            "sample": sample,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
