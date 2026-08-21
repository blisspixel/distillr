# pyright: strict
"""Command-line entry point for live reference-journey evidence."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from benchmarks.live_journey.evidence import ReleaseIdentity, build_evidence_bundle
from benchmarks.live_journey.runner import (
    load_campaign,
    prepare_library,
    provider_preflight,
    result_exit_code,
    run_campaign,
    run_one_journey,
    single_result_exit_code,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Distill live reference-journey evidence")
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight = subparsers.add_parser("preflight", help="validate inputs and local provider")
    preflight.add_argument("--manifest", type=Path, required=True)
    preflight.add_argument("--library", type=Path, required=True)
    run = subparsers.add_parser("run", help="run one independently persisted journey")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--library", type=Path, required=True)
    run.add_argument("--distill", type=Path, required=True)
    run.add_argument("--journey", required=True)
    run.add_argument("--output", type=Path, required=True)
    run_all = subparsers.add_parser("run-all", help="run all journeys in one process")
    run_all.add_argument("--manifest", type=Path, required=True)
    run_all.add_argument("--library", type=Path, required=True)
    run_all.add_argument("--distill", type=Path, required=True)
    run_all.add_argument("--output", type=Path, required=True)
    validate = subparsers.add_parser("validate", help="validate and bundle three receipts")
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument("--receipt", type=Path, action="append", required=True)
    validate.add_argument("--output-dir", type=Path, required=True)
    validate.add_argument("--repository", required=True)
    validate.add_argument("--commit-sha", required=True)
    return parser


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        prefix=f".{path.name}.",
        dir=path.parent,
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
    temporary.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "preflight":
            campaign = load_campaign(args.manifest)
            prepare_library(campaign, args.library)
            result = provider_preflight(campaign)
            sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
            return 0
        if args.command == "run":
            result = run_one_journey(
                args.manifest,
                args.library,
                args.distill,
                args.journey,
            )
            _atomic_json(args.output, result)
            return single_result_exit_code(result)
        if args.command == "run-all":
            result = run_campaign(args.manifest, args.library, args.distill)
            _atomic_json(args.output, result)
            return result_exit_code(result)
        identity = ReleaseIdentity(repository=args.repository, commit_sha=args.commit_sha)
        manifest, summary = build_evidence_bundle(
            args.manifest,
            args.receipt,
            args.output_dir,
            identity,
        )
    except Exception as exc:
        sys.stderr.write(f"live-journey evidence failed: {type(exc).__name__}: {exc}\n")
        return 1
    sys.stdout.write(f"{manifest}\n{summary}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
