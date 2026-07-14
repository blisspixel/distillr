"""Strict parsing tests for verification sidecars consumed by audit."""

from __future__ import annotations

from copy import deepcopy

import pytest

from distill.pipeline.verify_sidecar import parse_verify_sidecar


def _numeric_sidecar(*, version: int = 1, checked: int = 1) -> dict[str, object]:
    return {
        "schema_version": version,
        "mode": "warn",
        "checked": checked,
        "supported": checked,
        "unsupported": [],
        "insight": "example_Insights.md",
        "source": "receipt.md",
        "generated_at": "2026-07-13T12:00:00Z",
    }


def _entailment(*, status: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "checked": 2,
        "supported": 2,
        "flagged": [],
        "model": "cross-encoder/nli-deberta-v3-small",
        "threshold": 0.58,
    }
    if status is not None:
        payload["status"] = status
    return payload


def test_accepts_canonical_v1_numeric_results() -> None:
    clean = parse_verify_sidecar(_numeric_sidecar())
    flagged_payload = _numeric_sidecar(checked=2)
    flagged_payload["supported"] = 1
    flagged_payload["unsupported"] = [
        {"token": "99.9", "kind": "decimal", "context": "Unsupported 99.9 claim."}
    ]

    flagged = parse_verify_sidecar(flagged_payload)

    assert clean is not None
    assert clean.checked == 1
    assert clean.has_usable_coverage
    assert clean.flags == ()
    assert flagged is not None
    assert flagged.checked == 2
    assert flagged.has_usable_coverage
    assert flagged.flags[0].token == "99.9"


def test_accepts_valid_insight_content_binding() -> None:
    payload = _numeric_sidecar()
    payload["insight_sha256"] = "a" * 64

    parsed = parse_verify_sidecar(payload)

    assert parsed is not None
    assert parsed.insight_sha256 == "a" * 64


@pytest.mark.parametrize("digest", ["", "a" * 63, "A" * 64, "g" * 64, 7])
def test_rejects_malformed_insight_content_binding(digest: object) -> None:
    payload = _numeric_sidecar()
    payload["insight_sha256"] = digest

    assert parse_verify_sidecar(payload) is None


def test_accepts_canonical_v2_entailment_results() -> None:
    clean_payload = _numeric_sidecar(version=2, checked=0)
    clean_payload["entailment"] = _entailment()
    flagged_payload = deepcopy(clean_payload)
    flagged_payload["entailment"] = {
        "checked": 2,
        "supported": 1,
        "flagged": [
            {
                "claim": "An unsupported prose claim with enough detail.",
                "score": 0.12,
                "best_chunk_preview": "Closest available source passage.",
            }
        ],
        "model": "cross-encoder/nli-deberta-v3-small",
        "threshold": 0.58,
    }

    clean = parse_verify_sidecar(clean_payload)
    flagged = parse_verify_sidecar(flagged_payload)

    assert clean is not None
    assert clean.checked == 2
    assert clean.has_usable_coverage
    assert flagged is not None
    assert flagged.flags[0].kind == "entailment"


@pytest.mark.parametrize("status", ["unavailable", "error", "incomplete"])
def test_v3_semantic_failure_never_grants_clean_coverage(status: str) -> None:
    payload = _numeric_sidecar(version=3)
    if status == "incomplete":
        payload["entailment"] = {
            "status": status,
            "checked": 0,
            "supported": 0,
            "flagged": [],
            "model": "cross-encoder/nli-deberta-v3-small",
            "threshold": 0.58,
            "reason": "no prose claims checked",
        }
    else:
        payload["entailment"] = {
            "status": status,
            "checked": 0,
            "supported": 0,
            "flagged": [],
            "model": "",
            "threshold": None,
            "reason": "checker unavailable" if status == "unavailable" else "checker failed",
        }

    parsed = parse_verify_sidecar(payload)

    assert parsed is not None
    assert parsed.checked == 1
    assert not parsed.has_usable_coverage


def test_accepts_canonical_v3_passed_entailment_result() -> None:
    payload = _numeric_sidecar(version=3, checked=0)
    payload["entailment"] = _entailment(status="passed")

    parsed = parse_verify_sidecar(payload)

    assert parsed is not None
    assert parsed.checked == 2
    assert parsed.has_usable_coverage
    assert parsed.flags == ()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.pop("schema_version"),
        lambda payload: payload.__setitem__("schema_version", 4),
        lambda payload: payload.__setitem__("schema_version", True),
        lambda payload: payload.__setitem__("checked", True),
        lambda payload: payload.__setitem__("supported", -1),
        lambda payload: payload.__setitem__("unsupported", "not-a-list"),
        lambda payload: payload.__setitem__("unsupported", ["not-an-object"]),
        lambda payload: payload.__setitem__(
            "unsupported", [{"token": "99.9", "kind": "decimal", "context": "claim"}]
        ),
    ],
    ids=[
        "missing-version",
        "unknown-version",
        "boolean-version",
        "boolean-count",
        "negative-count",
        "non-list-unsupported",
        "non-object-unsupported",
        "inconsistent-counts",
    ],
)
def test_rejects_malformed_numeric_schema(mutate) -> None:
    payload = _numeric_sidecar()
    mutate(payload)

    assert parse_verify_sidecar(payload) is None


@pytest.mark.parametrize(
    "entailment",
    [
        "not-an-object",
        {"checked": 1, "supported": 1, "flagged": "not-a-list"},
        {
            "checked": 1,
            "supported": 1,
            "flagged": ["not-an-object"],
            "model": "model",
            "threshold": 0.58,
        },
        {
            "checked": 1,
            "supported": 1,
            "flagged": [
                {"claim": "claim", "score": float("nan"), "best_chunk_preview": "evidence"}
            ],
            "model": "model",
            "threshold": 0.58,
        },
        {
            "checked": 1,
            "supported": 1,
            "flagged": [],
            "model": "model",
            "threshold": 2.0,
        },
    ],
)
def test_rejects_malformed_v2_entailment_schema(entailment: object) -> None:
    payload = _numeric_sidecar(version=2)
    payload["entailment"] = entailment

    assert parse_verify_sidecar(payload) is None


def test_rejects_incoherent_v3_status() -> None:
    payload = _numeric_sidecar(version=3)
    payload["entailment"] = _entailment(status="passed")
    assert isinstance(payload["entailment"], dict)
    payload["entailment"]["flagged"] = [
        {"claim": "claim", "score": 0.1, "best_chunk_preview": "evidence"}
    ]
    payload["entailment"]["supported"] = 1

    assert parse_verify_sidecar(payload) is None


def test_rejects_non_string_object_keys() -> None:
    assert parse_verify_sidecar({1: "not-a-schema"}) is None


def test_rejects_invalid_numeric_flag_fields() -> None:
    payload = _numeric_sidecar()
    payload["supported"] = 0
    payload["unsupported"] = [{"token": "", "kind": "decimal", "context": "claim"}]

    assert parse_verify_sidecar(payload) is None


def test_rejects_nonfinite_entailment_probability_after_coherence_checks() -> None:
    payload = _numeric_sidecar(version=2, checked=0)
    payload["entailment"] = {
        "checked": 1,
        "supported": 0,
        "flagged": [
            {
                "claim": "claim",
                "score": float("nan"),
                "best_chunk_preview": "evidence",
            }
        ],
        "model": "model",
        "threshold": 0.58,
    }

    assert parse_verify_sidecar(payload) is None


def test_rejects_invalid_entailment_flag_fields() -> None:
    payload = _numeric_sidecar(version=2, checked=0)
    payload["entailment"] = {
        "checked": 1,
        "supported": 0,
        "flagged": [{"claim": "", "score": 0.1, "best_chunk_preview": "evidence"}],
        "model": "model",
        "threshold": 0.58,
    }

    assert parse_verify_sidecar(payload) is None


@pytest.mark.parametrize("status", ["unknown", "not_required"])
def test_rejects_unusable_v3_status(status: str) -> None:
    payload = _numeric_sidecar(version=3)
    payload["entailment"] = {"status": status}

    assert parse_verify_sidecar(payload) is None


def test_rejects_incoherent_v3_unavailable_state() -> None:
    payload = _numeric_sidecar(version=3)
    payload["entailment"] = {
        "status": "unavailable",
        "checked": 1,
        "supported": 0,
        "flagged": [],
        "model": "",
        "threshold": None,
        "reason": "checker unavailable",
    }

    assert parse_verify_sidecar(payload) is None


def test_rejects_malformed_v3_passed_state() -> None:
    payload = _numeric_sidecar(version=3)
    payload["entailment"] = {
        "status": "passed",
        "checked": 1,
        "supported": 1,
        "flagged": [],
        "model": "model",
        "threshold": 2.0,
    }

    assert parse_verify_sidecar(payload) is None


def test_rejects_v3_flagged_state_without_flags() -> None:
    payload = _numeric_sidecar(version=3)
    payload["entailment"] = _entailment(status="flagged")

    assert parse_verify_sidecar(payload) is None


def test_rejects_incoherent_v3_incomplete_state() -> None:
    payload = _numeric_sidecar(version=3)
    payload["entailment"] = {
        "status": "incomplete",
        "checked": 1,
        "supported": 1,
        "flagged": [],
        "model": "model",
        "threshold": 0.58,
        "reason": "partial",
    }

    assert parse_verify_sidecar(payload) is None


def test_accepts_v2_without_entailment_payload() -> None:
    parsed = parse_verify_sidecar(_numeric_sidecar(version=2))

    assert parsed is not None
    assert parsed.entailment_status is None


def test_rejects_v2_payload_with_v3_status_field() -> None:
    payload = _numeric_sidecar(version=2)
    payload["entailment"] = _entailment(status="passed")

    assert parse_verify_sidecar(payload) is None


def test_rejects_digest_binding_without_insight_name() -> None:
    payload = _numeric_sidecar()
    payload["insight_sha256"] = "a" * 64
    payload.pop("insight")

    assert parse_verify_sidecar(payload) is None


def test_rejects_non_object_top_level_payload() -> None:
    assert parse_verify_sidecar([]) is None
