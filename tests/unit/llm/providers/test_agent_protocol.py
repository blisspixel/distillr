"""Tests for host-session submission receipt validation."""

from __future__ import annotations

import copy
import hashlib

import pytest

from distill.llm.providers._agent_protocol import (
    HostSubmission,
    validate_host_submission,
)
from distill.llm.usage import MAX_USAGE_TOKENS

TASK_ID = "0123456789ab"
PROMPT_HASH = "1234567890abcdef"
RESULT = "# Result\n"


def _hash(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"
    return f"sha256:{hashlib.sha256(normalized.encode()).hexdigest()}"


def _payload(*, reported: bool = True) -> dict[str, object]:
    return {
        "schema_version": "agent-worker-submission.v1",
        "protocol": "agent-worker.v1",
        "task_id": TASK_ID,
        "prompt_hash": PROMPT_HASH,
        "claim_token_hash": "a" * 64,
        "host": "Codex",
        "worker_id": "session.1",
        "model": "gpt-test",
        "workload": "analysis",
        "claimed_at": "2026-07-15T12:00:00+00:00",
        "submitted_at": "2026-07-15T12:00:01+00:00",
        "elapsed_ms": 1000,
        "result_sha256": _hash(RESULT),
        "result_bytes": len(RESULT.encode()),
        "usage": {
            "input_tokens": 12 if reported else None,
            "output_tokens": 4 if reported else None,
            "source": "host-reported" if reported else "host-managed-unavailable",
        },
        "billing": {
            "class": "host-managed",
            "no_metered_proven": False,
            "proof": "unavailable",
        },
        "files_read": ["prompt.md", "task.json"],
        "files_written": ["result.md"],
        "published_result": f"analysis_{TASK_ID}_result.md",
    }


def test_validate_host_submission_with_reported_usage() -> None:
    receipt = validate_host_submission(
        _payload(),
        task_id=TASK_ID,
        prompt_hash=PROMPT_HASH,
        result_text="# Result\r\n",
    )
    assert receipt == HostSubmission(
        task_id=TASK_ID,
        prompt_hash=PROMPT_HASH,
        claim_token_hash="a" * 64,
        host="codex",
        worker_id="session.1",
        model="gpt-test",
        input_tokens=12,
        output_tokens=4,
        usage_source="host-reported",
        result_sha256=_hash(RESULT),
    )
    assert receipt.model_label == "gpt-test"


def test_validate_host_submission_without_usage_uses_host_model_label() -> None:
    payload = _payload(reported=False)
    payload["model"] = ""
    receipt = validate_host_submission(
        payload,
        task_id=TASK_ID,
        prompt_hash=PROMPT_HASH,
        result_text="# Result",
    )
    assert receipt.input_tokens is None
    assert receipt.output_tokens is None
    assert receipt.model_label == "host:codex"


def _set_nested(payload: dict[str, object], path: str, value: object) -> None:
    parts = path.split(".")
    target = payload
    for part in parts[:-1]:
        target = target[part]  # type: ignore[assignment]
    target[parts[-1]] = value


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        ("schema_version", "wrong", "schema"),
        ("extra", True, "fields"),
        ("protocol", "wrong", "protocol"),
        ("task_id", "wrong", "identity"),
        ("prompt_hash", "wrong", "identity"),
        ("host", "", "non-empty"),
        ("host", "bad host", "host is invalid"),
        ("worker_id", "bad worker", "worker_id is invalid"),
        ("claim_token_hash", "bad", "token hash"),
        ("model", 7, "model"),
        ("model", "x" * 201, "model"),
        ("model", "bad\nmodel", "model"),
        ("result_sha256", "wrong", "result hash"),
        ("workload", "bad workload", "workload"),
        ("result_bytes", 1, "byte count"),
        ("files_read", ["other.md"], "read set"),
        ("files_written", ["other.md"], "write set"),
        ("published_result", "other.md", "published result"),
        ("claimed_at", "bad", "claimed_at"),
        ("claimed_at", 7, "claimed_at"),
        ("claimed_at", "2026-07-15T12:00:00", "timezone"),
        ("submitted_at", "2026-07-15T11:59:59+00:00", "predates"),
        ("elapsed_ms", 999, "elapsed"),
        ("usage", "bad", "usage must"),
        ("usage.extra", 1, "usage fields"),
        ("usage.output_tokens", None, "supplied together"),
        ("usage.input_tokens", True, "input_tokens"),
        ("usage.input_tokens", -1, "input_tokens"),
        ("usage.output_tokens", MAX_USAGE_TOKENS + 1, "output_tokens"),
        ("usage.source", "reported", "usage source"),
        ("billing", "bad", "billing must"),
        ("billing.extra", 1, "billing fields"),
        ("billing.class", "included-plan", "class"),
        ("billing.no_metered_proven", True, "proven no-metered"),
        ("billing.proof", "claimed", "proof"),
    ],
)
def test_validate_host_submission_rejects_invalid_receipts(
    path: str,
    value: object,
    message: str,
) -> None:
    payload = copy.deepcopy(_payload())
    _set_nested(payload, path, value)
    with pytest.raises(ValueError, match=message):
        validate_host_submission(
            payload,
            task_id=TASK_ID,
            prompt_hash=PROMPT_HASH,
            result_text=RESULT,
        )
