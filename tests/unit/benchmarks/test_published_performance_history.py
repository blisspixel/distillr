from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from benchmarks import performance_history

_REPOSITORY_ROOT = Path(__file__).parents[3]
_HISTORY_ROOT = _REPOSITORY_ROOT / "docs" / "performance" / "comparable-history-0.19.70"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_published_performance_history_revalidates_all_raw_bundles() -> None:
    manifest = _read_json(_HISTORY_ROOT / "MANIFEST.json")
    history = _read_json(_HISTORY_ROOT / "HISTORY.json")

    assert manifest["schema_version"] == performance_history.HISTORY_BUNDLE_SCHEMA_VERSION
    assert manifest["verification"] == {
        "advisory_policy_derived": True,
        "blocking_timing_gate": False,
        "minimum_comparable_runs_per_host": 5,
        "paired_workflow_runs_complete": True,
        "raw_receipt_hashes_complete": True,
        "required_hosts_complete": True,
        "semantic_compatibility_complete": True,
    }
    assert history["workflow_run_count"] == 5
    assert {host["run_count"] for host in history["hosts"]} == {5}
    assert history["regression_policy"]["status"] == "active-advisory"
    assert history["regression_policy"]["blocking_timing_gate"] is False

    published_runs = []
    for item in manifest["inputs"]:
        bundle = (
            _HISTORY_ROOT / "inputs" / item["workflow_run_id"] / item["operating_system"].lower()
        )
        manifest_bytes = (bundle / "MANIFEST.json").read_bytes()
        assert hashlib.sha256(manifest_bytes).hexdigest() == item["bundle_manifest_sha256"]
        published_runs.append(performance_history._load_bundle(bundle))

    rebuilt = performance_history._history_payload(published_runs, minimum_runs=5)
    rebuilt.pop("generated_at")
    expected = dict(history)
    expected.pop("generated_at")
    assert rebuilt == expected


def test_published_performance_history_outputs_match_manifest() -> None:
    manifest = _read_json(_HISTORY_ROOT / "MANIFEST.json")
    for key in ("history", "summary"):
        item = manifest[key]
        payload = (_HISTORY_ROOT / item["path"]).read_bytes()
        assert len(payload) == item["bytes"]
        assert hashlib.sha256(payload).hexdigest() == item["sha256"]
