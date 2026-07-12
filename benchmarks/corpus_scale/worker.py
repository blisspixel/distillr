# pyright: strict
"""Private one-operation worker for process-isolated benchmark samples."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from benchmarks.corpus_scale.generator import load_worker_corpus
from benchmarks.corpus_scale.runner import (
    OPERATION_NAMES,
    WORKER_RESULT_SCHEMA_VERSION,
    measure_operation,
    operation_by_name,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Internal Distill corpus benchmark worker")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--worker-token", required=True)
    parser.add_argument("--operation", choices=OPERATION_NAMES, required=True)
    return parser


def _emit(value: object) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        corpus = load_worker_corpus(args.workspace, args.worker_token)
        operation = operation_by_name(corpus, args.operation)
        sample, _ = measure_operation(operation)
    except Exception as exc:
        _emit(
            {
                "schema_version": WORKER_RESULT_SCHEMA_VERSION,
                "operation": args.operation,
                "status": "error",
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
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
