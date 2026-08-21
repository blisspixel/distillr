"""Fail-closed contract tests for live reference-journey evidence."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from benchmarks.live_journey import evidence, runner
from benchmarks.live_journey.evidence import ReleaseIdentity, build_evidence_bundle


def _manifest() -> dict[str, object]:
    return {
        "schema_version": runner.CAMPAIGN_SCHEMA_VERSION,
        "campaign_id": "test-live-campaign",
        "cost_mode": "no-metered",
        "max_paid_usd": 0,
        "provider": "ollama",
        "model": "test-model:latest",
        "verification_mode": "warn",
        "journeys": [
            {
                "id": "papers-20",
                "kind": "papers",
                "topic": "evidence-papers",
                "expected_items": 20,
                "timeout_seconds": 600,
                "max_attempts": 2,
                "query": "trustworthy systems",
                "sort": "relevance",
                "expand": True,
                "rerank": True,
                "workers": 1,
            },
            {
                "id": "videos-50",
                "kind": "videos",
                "topic": "evidence-videos",
                "expected_items": 50,
                "timeout_seconds": 600,
                "max_attempts": 2,
                "channel_url": "https://www.youtube.com/@3blue1brown",
                "channel_name": "3Blue1Brown",
                "days": 365,
                "include_shorts": False,
            },
            {
                "id": "site-batch-2",
                "kind": "site-batch",
                "topic": "evidence-sites",
                "expected_items": 2,
                "timeout_seconds": 600,
                "max_attempts": 2,
                "urls": [
                    "https://docs.python.org/3/library/pathlib.html",
                    "https://docs.python.org/3/library/subprocess.html",
                ],
            },
        ],
    }


def _write_manifest(tmp_path: Path, value: dict[str, object] | None = None) -> Path:
    path = tmp_path / "campaign.json"
    path.write_text(json.dumps(value or _manifest()), encoding="utf-8")
    return path


def _cost_row(*, unknown: int = 0) -> dict[str, object]:
    return {
        "actual_cost": 0.0,
        "total_input_tokens": 100,
        "total_output_tokens": 20,
        "by_provider": {
            "ollama:local": {
                "calls": 1,
                "input_tokens": 100,
                "output_tokens": 20,
                "provider_name": "ollama",
                "provider_type": "local",
                "no_metered_cost": True,
            }
        },
        "usage_ledger": {
            "llm_calls": 1,
            "metered_llm_calls": 0,
            "no_metered_llm_calls": 1,
            "unknown_external_cost_calls": unknown,
            "unknown_external_cost_llm_calls": 0,
            "transcription_calls": 0,
            "metered_transcription_calls": 0,
            "no_metered_transcription_calls": 0,
            "unknown_external_cost_transcription_calls": 0,
        },
    }


def _receipt(campaign: runner.Campaign, journey: runner.Journey) -> dict[str, object]:
    process = {
        "wall_ns": 10_000,
        "cpu_ns": 4_000,
        "peak_rss_bytes": 2_000,
        "returncode": 0,
        "stdout_bytes": 0,
        "stdout_sha256": "0" * 64,
        "stderr_bytes": 0,
        "stderr_sha256": "0" * 64,
    }
    correlation = {
        "run_id": "run-id",
        "phase_rows": [{"run_id": "run-id", "phase": "command"}],
        "provider_rows": [{"run_id": "run-id", "model": campaign.model}],
        "cost_rows": [_cost_row()],
        "run_rows": [{"run_id": "run-id", "command": journey.kind}],
        "phase_rows_complete": True,
        "provider_rows_complete": True,
        "cost_rows_complete": True,
        "run_rows_complete": True,
    }
    result = {
        "id": journey.id,
        "kind": journey.kind,
        "topic": journey.topic,
        "expected_items": journey.expected_items,
        "status": "complete",
        "attempt_count": 1,
        "retry_count": 0,
        "retry_attempt_rate": 0.0,
        "primary_completion_rate": 1.0,
        "resume_completion_rate": 0.0,
        "attempts": [
            {
                "process": process,
                "correlation": correlation,
                "actual_paid_usd": 0.0,
            }
        ],
        "no_op_probe": {
            "no_op_rate": 1.0,
            "new_items": 0,
            "changed_items": 0,
        },
        "actual_paid_usd": 0.0,
        "verification": {
            "time_to_first_verified_artifact_ns": 100,
            "time_to_final_verified_artifact_ns": 200,
            "new_verified_artifact_count": journey.expected_items,
        },
        "final_source_item_count": journey.expected_items,
        "final_source_digest": "1" * 64,
    }
    return {
        "schema_version": runner.RESULT_SCHEMA_VERSION,
        "suite": "live-reference-journey",
        "generated_at": "2026-08-21T00:00:00Z",
        "campaign": {
            "id": campaign.id,
            "manifest_sha256": campaign.manifest_sha256,
            "cost_mode": "no-metered",
            "max_paid_usd": 0.0,
            "actual_paid_usd": 0.0,
            "verification_mode": "warn",
        },
        "provider_preflight": {
            "status": "ok",
            "provider": campaign.provider,
            "model": campaign.model,
            "endpoint_class": "http-loopback",
        },
        "environment": {
            "source_fingerprint_sha256": "2" * 64,
            "distill_version": "0.19.68",
            "distill_executable_sha256": "3" * 64,
        },
        "journey": result,
        "verification": {
            "journey_complete": True,
            "exact_item_count": True,
            "no_op_rate": 1.0,
            "metered_calls": 0,
            "unknown_external_cost_calls": 0,
            "actual_paid_usd": 0.0,
        },
    }


def test_load_campaign_requires_exact_reference_set_and_zero_spend(tmp_path: Path) -> None:
    path = _write_manifest(tmp_path)
    campaign = runner.load_campaign(path)
    assert [item.kind for item in campaign.journeys] == ["papers", "videos", "site-batch"]
    assert campaign.max_paid_usd == 0

    paid = _manifest()
    paid["cost_mode"] = "paid-ok"
    with pytest.raises(ValueError, match="no-metered"):
        runner.load_campaign(_write_manifest(tmp_path, paid))


def test_prepare_library_refuses_unmarked_nonempty_directory(tmp_path: Path) -> None:
    campaign = runner.load_campaign(_write_manifest(tmp_path))
    library = tmp_path / "library"
    library.mkdir()
    (library / "existing.txt").write_text("user data", encoding="utf-8")
    with pytest.raises(ValueError, match="unmarked non-empty"):
        runner.prepare_library(campaign, library)


def test_provider_preflight_requires_exact_local_model(tmp_path: Path, monkeypatch) -> None:
    campaign = runner.load_campaign(_write_manifest(tmp_path))

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit: int) -> bytes:
            return json.dumps(
                {"models": [{"name": campaign.model, "size": 10, "digest": "a" * 64}]}
            ).encode()

    monkeypatch.setattr(runner.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    result = runner.provider_preflight(campaign)
    assert result["endpoint_class"] == "http-loopback"
    assert result["no_metered_cost_proven_by"] == "local-loopback-topology"


def test_command_environment_bootstraps_no_metered_config(tmp_path: Path, monkeypatch) -> None:
    campaign = runner.load_campaign(_write_manifest(tmp_path))
    monkeypatch.setenv("DISTILL_COST_WORKFLOW_BUDGETS", "papers=5")
    environment = runner._command_environment(campaign, tmp_path / "library", tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from distill.config import DistillConfig; print(DistillConfig().distill_cost_mode)",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "no-metered"
    assert "DISTILL_COST_WORKFLOW_BUDGETS" not in environment
    assert not any("KEY" in name or "TOKEN" in name for name in environment)
    assert environment["PATH"] == os.environ["PATH"]


def test_cost_validator_fails_closed_on_unknown_external_cost() -> None:
    correlation = {"cost_rows": [_cost_row(unknown=1)]}
    with pytest.raises(ValueError, match="unknown_external_cost_calls"):
        runner._cost(correlation)


def test_bundle_validates_three_complete_zero_cost_receipts(tmp_path: Path) -> None:
    campaign_path = _write_manifest(tmp_path)
    campaign = runner.load_campaign(campaign_path)
    receipts: list[Path] = []
    for journey in campaign.journeys:
        path = tmp_path / f"{journey.id}.json"
        path.write_text(json.dumps(_receipt(campaign, journey)), encoding="utf-8")
        receipts.append(path)
    manifest_path, summary_path = build_evidence_bundle(
        campaign_path,
        receipts,
        tmp_path / "bundle",
        ReleaseIdentity(repository="owner/repository", commit_sha="f" * 40),
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == evidence.BUNDLE_SCHEMA_VERSION
    assert manifest["actual_paid_usd"] == 0
    assert manifest["verification"]["phase_provider_cost_correlation_complete"] is True
    assert "| papers | 20 |" in summary_path.read_text(encoding="utf-8")


def test_bundle_rejects_incomplete_verified_artifact_timing(tmp_path: Path) -> None:
    campaign_path = _write_manifest(tmp_path)
    campaign = runner.load_campaign(campaign_path)
    receipts: list[Path] = []
    for index, journey in enumerate(campaign.journeys):
        payload = _receipt(campaign, journey)
        if index == 0:
            journey_result = cast("dict[str, object]", payload["journey"])
            verification = cast("dict[str, object]", journey_result["verification"])
            verification["new_verified_artifact_count"] = 19
        path = tmp_path / f"{journey.id}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        receipts.append(path)
    with pytest.raises(ValueError, match="every expected verified"):
        build_evidence_bundle(
            campaign_path,
            receipts,
            tmp_path / "bundle",
            ReleaseIdentity(repository="owner/repository", commit_sha="f" * 40),
        )


def test_single_result_exit_code_tracks_correctness_not_timing() -> None:
    verification = {
        "journey_complete": True,
        "exact_item_count": True,
        "no_op_rate": 1.0,
        "metered_calls": 0,
        "unknown_external_cost_calls": 0,
        "actual_paid_usd": 0.0,
    }
    assert runner.single_result_exit_code({"verification": verification}) == 0
    verification["no_op_rate"] = 0.98
    assert runner.single_result_exit_code({"verification": verification}) == 1
