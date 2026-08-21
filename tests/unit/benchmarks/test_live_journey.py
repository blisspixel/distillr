"""Fail-closed contract tests for live reference-journey evidence."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

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
    preflight: dict[str, object] = {
        "status": "ok",
        "provider": campaign.provider,
        "model": campaign.model,
        "endpoint_class": "http-loopback",
    }
    if campaign.minimum_decode_tokens_per_second > 0:
        preflight["throughput_probe"] = {
            "status": "ok",
            "input_tokens": 20,
            "output_tokens": 64,
            "prefill_seconds": 1.0,
            "decode_seconds": 8.0,
            "decode_tokens_per_second": 8.0,
            "minimum_decode_tokens_per_second": campaign.minimum_decode_tokens_per_second,
            "wall_seconds": 10.0,
            "usage_source": "ollama-reported",
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
        "provider_preflight": preflight,
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


@pytest.mark.parametrize("minimum", ["fast", -1, float("inf"), 1001])
def test_load_campaign_rejects_invalid_decode_minimum(tmp_path: Path, minimum: object) -> None:
    manifest = _manifest()
    manifest["minimum_decode_tokens_per_second"] = minimum
    with pytest.raises(ValueError, match="minimum_decode_tokens_per_second"):
        runner.load_campaign(_write_manifest(tmp_path, manifest))


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

    monkeypatch.setattr(runner, "_open_loopback", lambda *_args, **_kwargs: Response())
    result = runner.provider_preflight(campaign)
    assert result["endpoint_class"] == "http-loopback"
    assert result["no_metered_cost_proven_by"] == "local-loopback-topology"


def test_loopback_requests_disable_environment_proxies(monkeypatch) -> None:
    sentinel = object()

    class Opener:
        def open(self, request, *, timeout: float):
            assert request.full_url == "http://127.0.0.1:11434/api/tags"
            assert timeout == 5
            return sentinel

    def build_opener(handler):
        assert isinstance(handler, runner.urllib.request.ProxyHandler)
        assert cast(Any, handler).proxies == {}
        return Opener()

    monkeypatch.setattr(runner.urllib.request, "build_opener", build_opener)
    request = runner.urllib.request.Request("http://127.0.0.1:11434/api/tags")
    assert runner._open_loopback(request, timeout=5) is sentinel


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://127.0.0.1:11434",
        "http://example.com:11434",
        "http://user:password@127.0.0.1:11434",
        "http://127.0.0.1:11434/base",
        "http://127.0.0.1:11434?token=value",
        "http://127.0.0.1:99999",
    ],
)
def test_provider_preflight_rejects_unsafe_local_endpoint(
    tmp_path: Path,
    monkeypatch,
    endpoint: str,
) -> None:
    campaign = runner.load_campaign(_write_manifest(tmp_path))
    monkeypatch.setenv("OLLAMA_BASE_URL", endpoint)
    with pytest.raises(ValueError, match="endpoint"):
        runner.provider_preflight(campaign)


def test_provider_preflight_enforces_reported_decode_throughput(
    tmp_path: Path, monkeypatch
) -> None:
    manifest = _manifest()
    manifest["minimum_decode_tokens_per_second"] = 6
    campaign = runner.load_campaign(_write_manifest(tmp_path, manifest))
    decode_ns = 8_000_000_000

    class Response:
        def __init__(self, payload: object) -> None:
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit: int) -> bytes:
            return json.dumps(self.payload).encode()

    def urlopen(request, **_kwargs):
        if request.full_url.endswith("/api/tags"):
            return Response({"models": [{"name": campaign.model, "size": 10, "digest": "a" * 64}]})
        return Response(
            {
                "model": campaign.model,
                "done": True,
                "prompt_eval_count": 20,
                "prompt_eval_duration": 1_000_000_000,
                "eval_count": 64,
                "eval_duration": decode_ns,
            }
        )

    monkeypatch.setattr(runner, "_open_loopback", urlopen)
    result = runner.provider_preflight(campaign)
    throughput = cast("dict[str, object]", result["throughput_probe"])
    assert throughput["decode_tokens_per_second"] == 8.0
    assert throughput["usage_source"] == "ollama-reported"

    decode_ns = 16_000_000_000
    with pytest.raises(ValueError, match="below the campaign minimum"):
        runner.provider_preflight(campaign)


@pytest.mark.parametrize(
    ("chat_payload", "message"),
    [
        (b"", "invalid response size"),
        (
            json.dumps(
                {
                    "model": "different-model",
                    "done": True,
                    "prompt_eval_count": 20,
                    "prompt_eval_duration": 1_000_000_000,
                    "eval_count": 64,
                    "eval_duration": 8_000_000_000,
                }
            ).encode(),
            "exact model",
        ),
        (
            json.dumps(
                {
                    "model": "test-model:latest",
                    "done": True,
                    "prompt_eval_count": 20,
                    "prompt_eval_duration": 1_000_000_000,
                    "eval_count": 0,
                    "eval_duration": 8_000_000_000,
                }
            ).encode(),
            "reported token timing",
        ),
    ],
)
def test_provider_preflight_rejects_invalid_throughput_response(
    tmp_path: Path,
    monkeypatch,
    chat_payload: bytes,
    message: str,
) -> None:
    manifest = _manifest()
    manifest["minimum_decode_tokens_per_second"] = 6
    campaign = runner.load_campaign(_write_manifest(tmp_path, manifest))

    class Response:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit: int) -> bytes:
            return self.payload

    def urlopen(request, **_kwargs):
        if request.full_url.endswith("/api/tags"):
            return Response(
                json.dumps(
                    {"models": [{"name": campaign.model, "size": 10, "digest": "a" * 64}]}
                ).encode()
            )
        return Response(chat_payload)

    monkeypatch.setattr(runner, "_open_loopback", urlopen)
    with pytest.raises(ValueError, match=message):
        runner.provider_preflight(campaign)


def test_provider_preflight_rejects_lmstudio_throughput_gate(tmp_path: Path, monkeypatch) -> None:
    manifest = _manifest()
    manifest["provider"] = "lmstudio"
    manifest["minimum_decode_tokens_per_second"] = 6
    campaign = runner.load_campaign(_write_manifest(tmp_path, manifest))

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit: int) -> bytes:
            return json.dumps({"data": [{"id": campaign.model}]}).encode()

    monkeypatch.setattr(runner, "_open_loopback", lambda *_args, **_kwargs: Response())
    with pytest.raises(ValueError, match="currently requires Ollama"):
        runner.provider_preflight(campaign)


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


def test_correlation_reads_root_run_summary_and_operational_logs(tmp_path: Path) -> None:
    library = tmp_path / "library"
    operations = library / ".distill"
    operations.mkdir(parents=True)
    run_id = "correlated-run-id"
    rows = {
        operations / "phase_telemetry.jsonl": {"run_id": run_id, "phase": "command"},
        operations / "telemetry.jsonl": {"run_id": run_id, "model": "local-model"},
        operations / "cost_log.jsonl": {"run_id": run_id, **_cost_row()},
        library / "run_log.jsonl": {"run_id": run_id, "command": "papers"},
    }
    for path, payload in rows.items():
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    assert runner._offsets(library).run == (library / "run_log.jsonl").stat().st_size
    correlation = runner._correlation(library, runner._Offsets(0, 0, 0, 0))

    assert correlation["run_id"] == run_id
    assert correlation["phase_rows_complete"] is True
    assert correlation["provider_rows_complete"] is True
    assert correlation["cost_rows_complete"] is True
    assert correlation["run_rows_complete"] is True


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


def test_bundle_requires_campaign_throughput_preflight(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["minimum_decode_tokens_per_second"] = 6
    campaign_path = _write_manifest(tmp_path, manifest)
    campaign = runner.load_campaign(campaign_path)
    receipts: list[Path] = []
    for journey in campaign.journeys:
        payload = _receipt(campaign, journey)
        preflight = cast("dict[str, object]", payload["provider_preflight"])
        preflight.pop("throughput_probe")
        path = tmp_path / f"{journey.id}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        receipts.append(path)
    with pytest.raises(ValueError, match="throughput probe"):
        build_evidence_bundle(
            campaign_path,
            receipts,
            tmp_path / "bundle",
            ReleaseIdentity(repository="owner/repository", commit_sha="f" * 40),
        )


def test_bundle_validates_campaign_throughput_preflight(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["minimum_decode_tokens_per_second"] = 6
    campaign_path = _write_manifest(tmp_path, manifest)
    campaign = runner.load_campaign(campaign_path)
    receipts: list[Path] = []
    for journey in campaign.journeys:
        path = tmp_path / f"{journey.id}.json"
        path.write_text(json.dumps(_receipt(campaign, journey)), encoding="utf-8")
        receipts.append(path)
    manifest_path, _summary_path = build_evidence_bundle(
        campaign_path,
        receipts,
        tmp_path / "bundle",
        ReleaseIdentity(repository="owner/repository", commit_sha="f" * 40),
    )
    assert manifest_path.is_file()


def test_bundle_rejects_throughput_below_campaign_minimum(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["minimum_decode_tokens_per_second"] = 6
    campaign_path = _write_manifest(tmp_path, manifest)
    campaign = runner.load_campaign(campaign_path)
    receipts: list[Path] = []
    for journey in campaign.journeys:
        payload = _receipt(campaign, journey)
        preflight = cast("dict[str, object]", payload["provider_preflight"])
        throughput = cast("dict[str, object]", preflight["throughput_probe"])
        throughput["decode_tokens_per_second"] = 5
        path = tmp_path / f"{journey.id}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        receipts.append(path)
    with pytest.raises(ValueError, match="does not satisfy"):
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
