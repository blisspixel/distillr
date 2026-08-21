# pyright: strict
"""Validate and bundle all three live reference-journey receipts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from benchmarks.live_journey.runner import (
    REQUIRED_KINDS,
    RESULT_SCHEMA_VERSION,
    Campaign,
    Journey,
    load_campaign,
)

BUNDLE_SCHEMA_VERSION = "live-journey-evidence-bundle.v1"
_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}")
_VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[a-zA-Z0-9.+-]*)?")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class ReleaseIdentity:
    repository: str
    commit_sha: str


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    raw = cast("dict[object, object]", value)
    if not all(isinstance(key, str) for key in raw):
        raise ValueError(f"{label} must use string keys")
    return {cast("str", key): item for key, item in raw.items()}


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return cast("list[object]", value)


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{label} must be numeric")
    return float(value)


def _identity(identity: ReleaseIdentity) -> None:
    if "/" not in identity.repository or any(
        character.isspace() for character in identity.repository
    ):
        raise ValueError("repository must be an owner/name identifier")
    if _COMMIT_RE.fullmatch(identity.commit_sha) is None:
        raise ValueError("commit_sha must be a lowercase Git object id")


def _load(path: Path) -> tuple[dict[str, object], bytes]:
    payload = path.read_bytes()
    if not payload or len(payload) > 32 * 1024 * 1024:
        raise ValueError(f"receipt has an invalid size: {path}")
    raw: object = json.loads(payload)
    return _object(raw, path.name), payload


def _expected(campaign: Campaign, journey_id: object) -> Journey:
    matches = [item for item in campaign.journeys if item.id == journey_id]
    if len(matches) != 1:
        raise ValueError("receipt journey id is not unique in the campaign")
    return matches[0]


def _validate_cost_row(value: object) -> tuple[int, int, int]:
    row = _object(value, "cost row")
    if _number(row.get("actual_cost"), "actual cost") != 0:
        raise ValueError("live evidence must record zero actual paid cost")
    ledger = _object(row.get("usage_ledger"), "usage ledger")
    for key in (
        "metered_llm_calls",
        "metered_transcription_calls",
        "unknown_external_cost_calls",
        "unknown_external_cost_llm_calls",
        "unknown_external_cost_transcription_calls",
    ):
        if ledger.get(key) != 0:
            raise ValueError(f"live evidence has unsafe usage field: {key}")
    providers = _object(row.get("by_provider"), "provider ledger")
    for value in providers.values():
        if _object(value, "provider entry").get("no_metered_cost") is not True:
            raise ValueError("provider ledger does not prove no-metered topology")
    return (
        _integer(row.get("total_input_tokens"), "input token count"),
        _integer(row.get("total_output_tokens"), "output token count"),
        _integer(ledger.get("llm_calls"), "LLM call count"),
    )


def _validate_attempt(value: object) -> dict[str, int]:
    attempt = _object(value, "journey attempt")
    process = _object(attempt.get("process"), "process evidence")
    if process.get("returncode") != 0:
        raise ValueError("journey attempt process did not succeed")
    correlation = _object(attempt.get("correlation"), "correlation evidence")
    if not all(
        correlation.get(key) is True
        for key in (
            "phase_rows_complete",
            "provider_rows_complete",
            "cost_rows_complete",
            "run_rows_complete",
        )
    ):
        raise ValueError("journey correlation evidence is incomplete")
    cost_rows = _list(correlation.get("cost_rows"), "cost rows")
    if len(cost_rows) != 1:
        raise ValueError("journey attempt must have one cost row")
    input_tokens, output_tokens, calls = _validate_cost_row(cost_rows[0])
    phase_rows = _list(correlation.get("phase_rows"), "phase rows")
    provider_rows = _list(correlation.get("provider_rows"), "provider rows")
    if not phase_rows or not provider_rows:
        raise ValueError("journey attempt lacks phase or provider evidence")
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "llm_calls": calls,
        "wall_ns": _integer(process.get("wall_ns"), "attempt wall time"),
        "peak_rss_bytes": _integer(process.get("peak_rss_bytes"), "attempt peak RSS"),
    }


def _validate_receipt(  # noqa: C901 - validates the complete nested evidence contract
    payload: dict[str, object], campaign: Campaign
) -> tuple[dict[str, object], dict[str, int], str]:
    if payload.get("schema_version") != RESULT_SCHEMA_VERSION:
        raise ValueError(f"receipt schema must be {RESULT_SCHEMA_VERSION}")
    if payload.get("suite") != "live-reference-journey":
        raise ValueError("bundle inputs must be single-journey receipts")
    campaign_row = _object(payload.get("campaign"), "receipt campaign")
    if (
        campaign_row.get("id") != campaign.id
        or campaign_row.get("manifest_sha256") != campaign.manifest_sha256
        or campaign_row.get("cost_mode") != "no-metered"
        or _number(campaign_row.get("actual_paid_usd"), "receipt cost") != 0
    ):
        raise ValueError("receipt is not bound to the no-metered campaign")
    preflight = _object(payload.get("provider_preflight"), "provider preflight")
    if (
        preflight.get("status") != "ok"
        or preflight.get("provider") != campaign.provider
        or preflight.get("model") != campaign.model
        or preflight.get("endpoint_class") != "http-loopback"
    ):
        raise ValueError("receipt provider preflight does not match the campaign")
    environment = _object(payload.get("environment"), "receipt environment")
    fingerprint = environment.get("source_fingerprint_sha256")
    if not isinstance(fingerprint, str) or _SHA256_RE.fullmatch(fingerprint) is None:
        raise ValueError("receipt source fingerprint is invalid")
    distill_version = environment.get("distill_version")
    executable_digest = environment.get("distill_executable_sha256")
    if (
        not isinstance(distill_version, str)
        or _VERSION_RE.fullmatch(distill_version) is None
        or not isinstance(executable_digest, str)
        or _SHA256_RE.fullmatch(executable_digest) is None
    ):
        raise ValueError("receipt Distill installation identity is invalid")
    journey = _object(payload.get("journey"), "receipt journey")
    expected = _expected(campaign, journey.get("id"))
    if (
        journey.get("kind") != expected.kind
        or journey.get("topic") != expected.topic
        or journey.get("expected_items") != expected.expected_items
        or journey.get("final_source_item_count") != expected.expected_items
        or journey.get("status") != "complete"
        or _number(journey.get("actual_paid_usd"), "journey cost") != 0
    ):
        raise ValueError("journey result does not satisfy its campaign contract")
    attempts = _list(journey.get("attempts"), "journey attempts")
    if not attempts or len(attempts) > expected.max_attempts:
        raise ValueError("journey attempt count is invalid")
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "llm_calls": 0,
        "wall_ns": 0,
        "peak_rss_bytes": 0,
    }
    for attempt in attempts:
        measured = _validate_attempt(attempt)
        totals["input_tokens"] += measured["input_tokens"]
        totals["output_tokens"] += measured["output_tokens"]
        totals["llm_calls"] += measured["llm_calls"]
        totals["wall_ns"] += measured["wall_ns"]
        totals["peak_rss_bytes"] = max(totals["peak_rss_bytes"], measured["peak_rss_bytes"])
    no_op = _object(journey.get("no_op_probe"), "no-op probe")
    if (
        _number(no_op.get("no_op_rate"), "no-op rate") != 1
        or no_op.get("new_items") != 0
        or no_op.get("changed_items") != 0
    ):
        raise ValueError("journey no-op probe is not convergent")
    verification = _object(journey.get("verification"), "journey verification")
    first = verification.get("time_to_first_verified_artifact_ns")
    final = verification.get("time_to_final_verified_artifact_ns")
    if not isinstance(first, int) or not isinstance(final, int) or first < 0 or final < first:
        raise ValueError("journey lacks valid first and final verified-artifact timing")
    if verification.get("new_verified_artifact_count") != expected.expected_items:
        raise ValueError("journey did not time every expected verified source artifact")
    totals["first_verified_ns"] = first
    totals["final_verified_ns"] = final
    totals["retry_count"] = _integer(journey.get("retry_count"), "retry count")
    return journey, totals, fingerprint


def _seconds(nanoseconds: int) -> str:
    return f"{nanoseconds / 1_000_000_000:.3f}"


def _summary(
    identity: ReleaseIdentity,
    campaign: Campaign,
    rows: list[tuple[dict[str, object], dict[str, int]]],
    distill_version: str,
) -> str:
    lines = [
        "# Live reference-journey evidence",
        "",
        f"- Repository: `{identity.repository}`",
        f"- Commit: `{identity.commit_sha}`",
        f"- Distill version: `{distill_version}`",
        f"- Campaign: `{campaign.id}`",
        f"- Provider: `{campaign.provider}`",
        f"- Model: `{campaign.model}`",
        "- Cost mode: `no-metered`",
        "- Paid spend: `$0.00`",
        "",
        "| Journey | Items | Primary wall (s) | First verified (s) | Final verified (s) | Peak RSS (MiB) | Input tokens | Output tokens | LLM calls | Retries | No-op rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for journey, totals in rows:
        no_op = _object(journey.get("no_op_probe"), "no-op probe")
        lines.append(
            f"| {journey['kind']} | {journey['expected_items']} | {_seconds(totals['wall_ns'])} "
            f"| {_seconds(totals['first_verified_ns'])} | {_seconds(totals['final_verified_ns'])} "
            f"| {totals['peak_rss_bytes'] / (1024 * 1024):.1f} | {totals['input_tokens']} "
            f"| {totals['output_tokens']} | {totals['llm_calls']} | {totals['retry_count']} "
            f"| {float(cast('int | float', no_op['no_op_rate'])):.3f} |"
        )
    lines.extend(
        [
            "",
            "Timings include live acquisition and local model execution. They are release evidence, not a blocking performance objective.",
            "Verified-artifact timing means a source insight paired with a structurally valid verification sidecar. A present content binding must match.",
            "",
        ]
    )
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def build_evidence_bundle(
    campaign_path: Path,
    receipt_paths: list[Path],
    output_dir: Path,
    identity: ReleaseIdentity,
) -> tuple[Path, Path]:
    """Validate the complete campaign and bind its receipts to a release commit."""

    _identity(identity)
    campaign = load_campaign(campaign_path)
    if len(receipt_paths) != 3 or len({path.resolve() for path in receipt_paths}) != 3:
        raise ValueError("bundle requires exactly three distinct journey receipts")
    validated: list[tuple[dict[str, object], dict[str, int]]] = []
    receipt_rows: list[dict[str, object]] = []
    fingerprints: set[str] = set()
    versions: set[str] = set()
    executable_digests: set[str] = set()
    kinds: set[object] = set()
    for path in receipt_paths:
        payload, raw = _load(path)
        journey, totals, fingerprint = _validate_receipt(payload, campaign)
        validated.append((journey, totals))
        fingerprints.add(fingerprint)
        environment = _object(payload.get("environment"), "receipt environment")
        versions.add(cast("str", environment["distill_version"]))
        executable_digests.add(cast("str", environment["distill_executable_sha256"]))
        kinds.add(journey.get("kind"))
        receipt_rows.append(
            {"path": path.name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        )
    if (
        kinds != set(REQUIRED_KINDS)
        or len(fingerprints) != 1
        or len(versions) != 1
        or len(executable_digests) != 1
    ):
        raise ValueError("receipts do not cover one comparable run of every required journey")
    validated.sort(key=lambda item: REQUIRED_KINDS.index(cast("str", item[0]["kind"])))
    distill_version = next(iter(versions))
    summary = _summary(identity, campaign, validated, distill_version)
    summary_path = output_dir / "SUMMARY.md"
    manifest_path = output_dir / "MANIFEST.json"
    campaign_raw = campaign_path.read_bytes()
    manifest = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "repository": identity.repository,
        "commit_sha": identity.commit_sha,
        "campaign_id": campaign.id,
        "campaign": {
            "path": campaign_path.name,
            "bytes": len(campaign_raw),
            "sha256": hashlib.sha256(campaign_raw).hexdigest(),
        },
        "source_fingerprint_sha256": next(iter(fingerprints)),
        "distill_version": distill_version,
        "distill_executable_sha256": next(iter(executable_digests)),
        "provider": campaign.provider,
        "model": campaign.model,
        "cost_mode": "no-metered",
        "max_paid_usd": campaign.max_paid_usd,
        "actual_paid_usd": 0.0,
        "receipts": sorted(receipt_rows, key=lambda row: cast("str", row["path"])),
        "summary": {
            "path": summary_path.name,
            "bytes": len(summary.encode()),
            "sha256": hashlib.sha256(summary.encode()).hexdigest(),
        },
        "verification": {
            "required_journeys_complete": True,
            "exact_item_counts": True,
            "verified_artifact_timings_complete": True,
            "phase_provider_cost_correlation_complete": True,
            "no_op_rates_complete": True,
            "metered_calls": 0,
            "unknown_external_cost_calls": 0,
            "actual_paid_usd": 0.0,
        },
    }
    _atomic_write(summary_path, summary)
    _atomic_write(manifest_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest_path, summary_path


__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "ReleaseIdentity",
    "build_evidence_bundle",
]
