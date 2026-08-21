from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

_REPOSITORY_ROOT = Path(__file__).parents[3]
_BASELINE = _REPOSITORY_ROOT / "docs" / "performance" / "cross-platform-0.19.66"
_EXPECTED_COMMIT = "1c72d1125fad079253b441f3595ad587f5aa4686"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _result_signatures(receipt: dict[str, Any]) -> dict[str, tuple[int, str]]:
    signatures: dict[str, tuple[int, str]] = {}
    for operation in receipt["operations"]:
        samples = operation["samples"]
        assert operation["status"] == "ok"
        assert len(samples) == 20
        counts = {sample["result_count"] for sample in samples}
        digests = {sample["result_digest"] for sample in samples}
        assert len(counts) == 1
        assert len(digests) == 1
        signatures[operation["name"]] = (counts.pop(), digests.pop())
    return signatures


def test_published_bundles_match_their_manifests() -> None:
    for host, operating_system in (("linux", "Linux"), ("macos", "macOS")):
        bundle = _BASELINE / host
        manifest = _read_json(bundle / "MANIFEST.json")

        assert manifest["schema_version"] == "performance-evidence-bundle.v1"
        assert manifest["repository"] == "blisspixel/distillr"
        assert manifest["commit_sha"] == _EXPECTED_COMMIT
        assert manifest["project_version"] == "0.19.66"
        assert manifest["workflow_run_id"] == "32431022291"
        assert manifest["workflow_run_attempt"] == "1"
        assert manifest["runner"]["operating_system"] == operating_system
        assert all(manifest["verification"].values())

        entries = [*manifest["receipts"], manifest["summary"]]
        for entry in entries:
            content = (bundle / entry["path"]).read_bytes()
            assert len(content) == entry["bytes"]
            assert hashlib.sha256(content).hexdigest() == entry["sha256"]


def test_published_results_are_identical_across_hosts() -> None:
    linux = _BASELINE / "linux"
    macos = _BASELINE / "macos"

    for name in (
        "corpus-scale-100.json",
        "corpus-scale-500.json",
        "corpus-scale-1000.json",
        "corpus-scale-10000.json",
    ):
        linux_receipt = _read_json(linux / name)
        macos_receipt = _read_json(macos / name)

        assert (
            linux_receipt["source_integrity"]["before_digest"]
            == (macos_receipt["source_integrity"]["before_digest"])
        )
        assert (
            linux_receipt["corpus"]["digest_sha256"] == (macos_receipt["corpus"]["digest_sha256"])
        )
        assert _result_signatures(linux_receipt) == _result_signatures(macos_receipt)

    linux_replay = _read_json(linux / "workflow-replay.json")
    macos_replay = _read_json(macos / "workflow-replay.json")

    assert (
        linux_replay["source_integrity"]["before_digest"]
        == (macos_replay["source_integrity"]["before_digest"])
    )
    assert linux_replay["fixtures"]["digest_sha256"] == (macos_replay["fixtures"]["digest_sha256"])
    for receipt in (linux_replay, macos_replay):
        assert receipt["execution"]["network"] == "fail-closed"
        assert receipt["execution"]["provider"] == "deterministic-stub"
        assert receipt["execution"]["simulated_provider_wait_ns"] == 0
    assert _result_signatures(linux_replay) == _result_signatures(macos_replay)
