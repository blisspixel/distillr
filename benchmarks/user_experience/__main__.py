# pyright: strict
"""CLI for cross-platform user-experience evidence."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from benchmarks.user_experience.evidence import RunIdentity, build_evidence_bundle
from benchmarks.user_experience.runner import (
    DEFAULT_ITERATIONS,
    DEFAULT_WARMUPS,
    EXPORT_SCALE,
    result_exit_code,
    run_user_experience,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Distill user-experience evidence")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="measure a clean install and fresh-process operations")
    run.add_argument("--wheel", type=Path, required=True)
    run.add_argument("--sdist", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    run.add_argument("--warmups", type=int, default=DEFAULT_WARMUPS)
    run.add_argument("--export-scale", type=int, default=EXPORT_SCALE)
    run.add_argument("--uv", type=Path)
    validate = subparsers.add_parser("validate", help="validate and bundle a canonical receipt")
    validate.add_argument("--receipt", type=Path, required=True)
    validate.add_argument("--output-dir", type=Path, required=True)
    validate.add_argument("--repository", required=True)
    validate.add_argument("--commit-sha", required=True)
    validate.add_argument("--workflow-run-id", required=True)
    validate.add_argument("--workflow-run-attempt", required=True)
    validate.add_argument("--runner-os", required=True)
    validate.add_argument("--runner-arch", required=True)
    validate.add_argument("--runner-name", required=True)
    return parser


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "run":
            result = run_user_experience(
                args.wheel,
                args.sdist,
                iterations=args.iterations,
                warmups=args.warmups,
                export_scale=args.export_scale,
                uv_executable=args.uv,
            )
            _write_json(args.output, result)
            return result_exit_code(result)
        identity = RunIdentity(
            repository=args.repository,
            commit_sha=args.commit_sha,
            workflow_run_id=args.workflow_run_id,
            workflow_run_attempt=args.workflow_run_attempt,
            runner_os=args.runner_os,
            runner_arch=args.runner_arch,
            runner_name=args.runner_name,
        )
        manifest, summary = build_evidence_bundle(args.receipt, args.output_dir, identity)
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        sys.stderr.write(f"user-experience evidence failed: {exc}\n")
        return 1
    sys.stdout.write(f"{manifest}\n{summary}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
