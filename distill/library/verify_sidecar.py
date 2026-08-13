"""Versioned verification-sidecar contract shared by writers and readers."""

# pyright: strict

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal, cast

__all__ = [
    "VERIFY_SCHEMA_VERSION",
    "EntailmentStatus",
    "ParsedVerifyFlag",
    "ParsedVerifySidecar",
    "parse_verify_sidecar",
]

VERIFY_SCHEMA_VERSION = 3
_SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2, VERIFY_SCHEMA_VERSION})

type EntailmentStatus = Literal[
    "not_required",
    "passed",
    "flagged",
    "unavailable",
    "error",
    "incomplete",
]

_ENTAILMENT_STATUSES = frozenset(
    {"not_required", "passed", "flagged", "unavailable", "error", "incomplete"}
)
_UNUSABLE_ENTAILMENT_STATUSES = frozenset({"unavailable", "error", "incomplete"})
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class ParsedVerifyFlag:
    """A validated unsupported claim in audit-ready form."""

    token: str
    kind: str
    context: str


@dataclass(frozen=True)
class ParsedVerifySidecar:
    """A structurally valid sidecar and its usable verification coverage."""

    checked: int
    flags: tuple[ParsedVerifyFlag, ...]
    entailment_status: EntailmentStatus | None = None
    insight_sha256: str | None = None

    @property
    def has_usable_coverage(self) -> bool:
        """Whether audit may treat this record as a completed verification."""

        return self.checked > 0 and self.entailment_status not in _UNUSABLE_ENTAILMENT_STATUSES


def _object(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    raw = cast("dict[object, object]", value)
    if not all(isinstance(key, str) for key in raw):
        return None
    return {cast("str", key): item for key, item in raw.items()}


def _object_list(value: object) -> list[dict[str, object]] | None:
    if not isinstance(value, list):
        return None
    rows: list[dict[str, object]] = []
    for item in cast("list[object]", value):
        parsed = _object(item)
        if parsed is None:
            return None
        rows.append(parsed)
    return rows


def _nonnegative_int(value: object) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    return value


def _probability(value: object, *, allow_zero: bool) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    lower_ok = value >= 0 if allow_zero else value > 0
    if not lower_ok or value > 1:
        return None
    return float(value)


def _required_string(data: dict[str, object], key: str, *, nonempty: bool = False) -> str | None:
    value = data.get(key)
    if not isinstance(value, str) or (nonempty and not value.strip()):
        return None
    return value


def _numeric_flags(data: dict[str, object]) -> tuple[int, tuple[ParsedVerifyFlag, ...]] | None:
    checked = _nonnegative_int(data.get("checked"))
    supported = _nonnegative_int(data.get("supported"))
    unsupported = _object_list(data.get("unsupported"))
    if checked is None or supported is None or unsupported is None:
        return None
    if checked != supported + len(unsupported):
        return None

    flags: list[ParsedVerifyFlag] = []
    for item in unsupported:
        token = _required_string(item, "token", nonempty=True)
        kind = _required_string(item, "kind", nonempty=True)
        context = _required_string(item, "context")
        if token is None or kind is None or context is None:
            return None
        flags.append(ParsedVerifyFlag(token=token, kind=kind, context=context[:200]))
    return checked, tuple(flags)


def _entailment_flags(data: dict[str, object]) -> tuple[int, tuple[ParsedVerifyFlag, ...]] | None:
    checked = _nonnegative_int(data.get("checked"))
    supported = _nonnegative_int(data.get("supported"))
    flagged = _object_list(data.get("flagged"))
    model = _required_string(data, "model", nonempty=True)
    threshold = _probability(data.get("threshold"), allow_zero=False)
    if (
        checked is None
        or supported is None
        or flagged is None
        or model is None
        or threshold is None
    ):
        return None
    if checked != supported + len(flagged):
        return None

    flags: list[ParsedVerifyFlag] = []
    for item in flagged:
        claim = _required_string(item, "claim", nonempty=True)
        preview = _required_string(item, "best_chunk_preview")
        score = _probability(item.get("score"), allow_zero=True)
        if claim is None or preview is None or score is None:
            return None
        flags.append(ParsedVerifyFlag(token=claim[:80], kind="entailment", context=preview[:200]))
    return checked, tuple(flags)


def _v3_entailment(
    data: dict[str, object],
) -> tuple[int, tuple[ParsedVerifyFlag, ...], EntailmentStatus] | None:
    raw_status = data.get("status")
    if not isinstance(raw_status, str) or raw_status not in _ENTAILMENT_STATUSES:
        return None
    status = cast("EntailmentStatus", raw_status)
    if status == "not_required":
        return None

    if status in {"unavailable", "error"}:
        checked = _nonnegative_int(data.get("checked"))
        supported = _nonnegative_int(data.get("supported"))
        flagged = _object_list(data.get("flagged"))
        model = _required_string(data, "model")
        reason = _required_string(data, "reason", nonempty=True)
        if (
            checked != 0
            or supported != 0
            or flagged != []
            or model != ""
            or data.get("threshold") is not None
            or reason is None
        ):
            return None
        return 0, (), status

    parsed = _entailment_flags(data)
    if parsed is None:
        return None
    checked, flags = parsed
    if status == "passed" and (checked == 0 or flags):
        return None
    if status == "flagged" and (checked == 0 or not flags):
        return None
    if status == "incomplete":
        reason = _required_string(data, "reason", nonempty=True)
        if checked != 0 or flags or reason is None:
            return None
    return checked, flags, status


def _versioned_entailment(
    version: int, value: object
) -> tuple[int, tuple[ParsedVerifyFlag, ...], EntailmentStatus | None] | None:
    if version == 1:
        return (0, (), None) if value is None else None
    if value is None:
        return 0, (), None
    data = _object(value)
    if data is None:
        return None
    if version == 2:
        if "status" in data:
            return None
        parsed = _entailment_flags(data)
        return (*parsed, None) if parsed is not None else None
    return _v3_entailment(data)


def _insight_sha256(data: dict[str, object]) -> tuple[bool, str | None]:
    if "insight_sha256" not in data:
        return True, None
    value = data["insight_sha256"]
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        return False, None
    if _required_string(data, "insight", nonempty=True) is None:
        return False, None
    return True, value


def parse_verify_sidecar(value: object) -> ParsedVerifySidecar | None:
    """Parse a known sidecar schema, rejecting malformed or incoherent state.

    Unknown and missing versions fail closed. Additive fields remain tolerated
    within known versions, while every field that can affect audit trust is
    validated before the record can contribute clean or flagged coverage.
    """

    data = _object(value)
    if data is None:
        return None
    version = _nonnegative_int(data.get("schema_version"))
    mode = data.get("mode")
    if version not in _SUPPORTED_SCHEMA_VERSIONS or mode not in {"warn", "strict"}:
        return None

    numeric = _numeric_flags(data)
    if numeric is None:
        return None
    numeric_checked, numeric_flags = numeric

    entailment = _versioned_entailment(version, data.get("entailment"))
    if entailment is None:
        return None
    checked, flags, status = entailment
    digest_is_valid, digest = _insight_sha256(data)
    if not digest_is_valid:
        return None
    return ParsedVerifySidecar(
        checked=numeric_checked + checked,
        flags=numeric_flags + flags,
        entailment_status=status,
        insight_sha256=digest,
    )
