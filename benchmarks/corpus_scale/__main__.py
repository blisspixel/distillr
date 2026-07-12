# pyright: strict
"""Repository-only entry point for the advisory corpus-scale benchmark."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from benchmarks.corpus_scale.generator import DEFAULT_SEED, generated_corpus
from benchmarks.corpus_scale.runner import BenchmarkResult, run_corpus_scale


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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run advisory read benchmarks against a generated temporary Distill corpus. "
            "No user library or network source is read."
        )
    )
    parser.add_argument("--scale", type=_positive_int, default=100)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--iterations", type=_positive_int, default=5)
    parser.add_argument("--warmups", type=_non_negative_int, default=1)
    return parser


def _result_exit_code(result: BenchmarkResult) -> int:
    correct = result["integrity"]["unchanged"] and all(
        operation["status"] == "ok" and operation["integrity"]["unchanged"]
        for operation in result["operations"]
    )
    return 0 if correct else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    with generated_corpus(scale=args.scale, seed=args.seed) as corpus:
        result = run_corpus_scale(
            corpus,
            iterations=args.iterations,
            warmups=args.warmups,
        )
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    return _result_exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
