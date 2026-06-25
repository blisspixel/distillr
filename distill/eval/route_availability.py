# pyright: strict
"""Pure route availability signals for quota-aware route pools.

The route pool needs live service state without learning provider-specific
scraping details. This module normalizes already collected evidence into a
small structural contract:

- rolling quota windows, where the most constrained window governs availability
- stale evidence, which cannot prove a route is live
- quota or rate-limit stops, which evict a route until retry/reset evidence

No provider calls happen here.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Self, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from distill.doctor.adapter_manifest import AdapterResultManifest

__all__ = [
    "MIN_USABLE_HEADROOM_PERCENT",
    "ROUTE_AVAILABILITY_SCHEMA_VERSION",
    "RouteAvailabilityDecision",
    "RouteAvailabilitySignal",
    "RouteAvailabilitySnapshot",
    "RouteQuotaStop",
    "RouteQuotaWindow",
    "load_route_availability_snapshot",
    "local_service_route_availability_signal",
    "parse_route_availability_snapshot",
    "route_availability_decision",
    "route_availability_signal_from_manifest",
]

MIN_USABLE_HEADROOM_PERCENT = 0.5
ROUTE_AVAILABILITY_SCHEMA_VERSION = "route-availability.v1"
_FORBIDDEN_NATIVE_KEYS = frozenset(
    {
        "account",
        "api_key",
        "email",
        "login",
        "organization",
        "org",
        "secret",
        "tenant",
        "token",
        "user",
        "username",
    }
)


@dataclass(frozen=True)
class RouteQuotaWindow:
    """One rolling quota window for a route."""

    label: str
    used_percent: float | None = None
    remaining_percent: float | None = None
    resets_at: int | None = None

    def remaining(self, now: int) -> float | None:
        """Return remaining headroom, treating already reset windows as fresh."""

        if self.resets_at is not None and self.resets_at <= now:
            return 100.0
        if self.remaining_percent is not None:
            return _clamp_percent(self.remaining_percent)
        if self.used_percent is not None:
            return _clamp_percent(100.0 - self.used_percent)
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "used_percent": self.used_percent,
            "remaining_percent": self.remaining_percent,
            "resets_at": self.resets_at,
        }


@dataclass(frozen=True)
class RouteQuotaStop:
    """Structured quota or rate-limit stop evidence for a route."""

    reached: bool
    reason: str = ""
    retry_after_seconds: int | None = None
    provider_code: str = ""
    native: Mapping[str, Any] | None = None

    def blocked_until(self, now: int) -> int | None:
        if not self.reached or self.retry_after_seconds is None:
            return None
        return now + max(0, self.retry_after_seconds)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reached": self.reached,
            "reason": self.reason,
            "retry_after_seconds": self.retry_after_seconds,
            "provider_code": self.provider_code,
            "native": dict(self.native or {}),
        }


@dataclass(frozen=True)
class RouteAvailabilitySignal:
    """Already collected route service state."""

    provider: str
    model: str = ""
    workload: str = ""
    evidence_source: str = ""
    checked_at: int | None = None
    stale: bool = False
    windows: tuple[RouteQuotaWindow, ...] = ()
    quota_stop: RouteQuotaStop | None = None
    unavailable_reason: str = ""

    @property
    def normalized_provider(self) -> str:
        return self.provider.strip().lower()

    @property
    def normalized_model(self) -> str:
        return self.model.strip()

    def normalized_workload(self, default: str = "default") -> str:
        return (self.workload or default).strip() or "default"

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "workload": self.workload,
            "evidence_source": self.evidence_source,
            "checked_at": self.checked_at,
            "stale": self.stale,
            "windows": [window.to_dict() for window in self.windows],
            "quota_stop": self.quota_stop.to_dict() if self.quota_stop else None,
            "unavailable_reason": self.unavailable_reason,
        }


@dataclass(frozen=True)
class RouteAvailabilitySnapshot:
    """Portable route availability evidence loaded from a snapshot file."""

    checked_at: int
    signals: tuple[RouteAvailabilitySignal, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": ROUTE_AVAILABILITY_SCHEMA_VERSION,
            "checked_at": self.checked_at,
            "signals": [signal.to_dict() for signal in self.signals],
        }


@dataclass(frozen=True)
class RouteAvailabilityDecision:
    """Availability verdict derived from one signal."""

    available: bool
    headroom_percent: float | None
    binding_window: RouteQuotaWindow | None
    resets_at: int | None
    stale: bool
    blocked_until: int | None
    blocked_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "headroom_percent": self.headroom_percent,
            "binding_window": self.binding_window.to_dict() if self.binding_window else None,
            "resets_at": self.resets_at,
            "stale": self.stale,
            "blocked_until": self.blocked_until,
            "blocked_reasons": list(self.blocked_reasons),
        }


def route_availability_decision(
    signal: RouteAvailabilitySignal,
    *,
    now: int,
) -> RouteAvailabilityDecision:
    """Return whether a route is currently usable from structural quota evidence."""

    blocked: list[str] = []
    blocked_until: int | None = None

    if signal.stale:
        blocked.append("route availability proof is stale")
    if signal.unavailable_reason.strip():
        blocked.append(signal.unavailable_reason.strip())

    if signal.quota_stop is not None and signal.quota_stop.reached:
        reason = signal.quota_stop.reason.strip() or "quota or rate limit reached"
        blocked.append(reason)
        blocked_until = signal.quota_stop.blocked_until(now)

    binding_window, headroom = _binding_window(signal.windows, now)
    resets_at = binding_window.resets_at if binding_window else None
    if headroom is not None and headroom <= MIN_USABLE_HEADROOM_PERCENT:
        label = binding_window.label if binding_window else "unknown"
        blocked.append(f"binding quota window {label!r} has {headroom:.1f}% headroom")
        if blocked_until is None:
            blocked_until = resets_at

    return RouteAvailabilityDecision(
        available=not blocked,
        headroom_percent=headroom,
        binding_window=binding_window,
        resets_at=resets_at,
        stale=signal.stale,
        blocked_until=blocked_until,
        blocked_reasons=tuple(blocked),
    )


def route_availability_signal_from_manifest(
    manifest: AdapterResultManifest,
    *,
    now: int,
    workload: str = "",
) -> RouteAvailabilitySignal:
    """Create a route availability signal from a verified adapter manifest."""

    quota_stop = None
    if manifest.quota_stop is not None:
        quota_stop = RouteQuotaStop(
            reached=manifest.quota_stop.reached,
            reason=manifest.quota_stop.reason,
            retry_after_seconds=manifest.quota_stop.retry_after_seconds,
            provider_code=manifest.quota_stop.provider_code,
            native=manifest.quota_stop.native,
        )
    return RouteAvailabilitySignal(
        provider=manifest.adapter,
        model=manifest.model,
        workload=workload,
        evidence_source="adapter-result-manifest",
        checked_at=now,
        stale=False,
        quota_stop=quota_stop,
    )


def local_service_route_availability_signal(
    *,
    provider: str,
    status: str,
    checked_at: int,
    models: tuple[str, ...] = (),
    model: str = "",
    workload: str = "",
) -> RouteAvailabilitySignal:
    """Normalize local service reachability into route availability evidence."""

    provider_label = provider.strip().lower()
    status_label = status.strip().lower()
    model_label = model.strip()
    model_set = {entry.strip() for entry in models if entry.strip()}
    unavailable_reason = ""
    if status_label != "running":
        unavailable_reason = f"{provider_label} local service is not reachable"
    elif model_label and model_set and model_label not in model_set:
        unavailable_reason = f"{provider_label} local model {model_label!r} is not installed"

    return RouteAvailabilitySignal(
        provider=provider_label,
        model=model_label,
        workload=workload,
        evidence_source="local-doctor",
        checked_at=checked_at,
        stale=False,
        unavailable_reason=unavailable_reason,
    )


def parse_route_availability_snapshot(payload: Mapping[str, Any]) -> RouteAvailabilitySnapshot:
    """Parse a portable route availability snapshot.

    The schema intentionally has no account, email, token, or organization
    fields. Availability must be expressed as route evidence, not identity.
    """

    parsed = _RouteAvailabilitySnapshotModel.model_validate(dict(payload))
    return parsed.to_snapshot()


def load_route_availability_snapshot(path: Path) -> RouteAvailabilitySnapshot:
    """Load a JSON or YAML route availability snapshot from disk."""

    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        payload = yaml.safe_load(text)
    else:
        payload = json.loads(text)
    if not isinstance(payload, Mapping):
        raise ValueError("route availability snapshot must be a mapping")
    return parse_route_availability_snapshot(cast("Mapping[str, Any]", payload))


def _binding_window(
    windows: tuple[RouteQuotaWindow, ...],
    now: int,
) -> tuple[RouteQuotaWindow | None, float | None]:
    binding: RouteQuotaWindow | None = None
    lowest: float | None = None
    for window in windows:
        remaining = window.remaining(now)
        if remaining is None:
            continue
        if lowest is None or remaining < lowest:
            lowest = remaining
            binding = window
    return binding, lowest


def _clamp_percent(value: float) -> float:
    return max(0.0, min(100.0, value))


def _reject_identity_metadata(value: object) -> None:
    """Reject account-bearing metadata in portable availability snapshots."""

    if isinstance(value, Mapping):
        for raw_key, child in cast("Mapping[object, object]", value).items():
            key = str(raw_key).strip().lower()
            if key in _FORBIDDEN_NATIVE_KEYS:
                raise ValueError(f"native quota metadata cannot include identity field {key!r}")
            _reject_identity_metadata(child)
    elif isinstance(value, list):
        for item in cast("list[object]", value):
            _reject_identity_metadata(item)


class _RouteQuotaWindowModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    label: str
    used_percent: float | None = None
    remaining_percent: float | None = None
    resets_at: int | None = None

    @field_validator("label")
    @classmethod
    def _non_empty_label(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("quota window label must be non-empty")
        return text

    @field_validator("used_percent", "remaining_percent")
    @classmethod
    def _valid_percent(cls, value: float | None) -> float | None:
        if value is not None and not 0.0 <= value <= 100.0:
            raise ValueError("quota percentages must be between 0 and 100")
        return value

    @field_validator("resets_at")
    @classmethod
    def _non_negative_reset(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("resets_at must be non-negative")
        return value

    def to_window(self) -> RouteQuotaWindow:
        return RouteQuotaWindow(
            label=self.label,
            used_percent=self.used_percent,
            remaining_percent=self.remaining_percent,
            resets_at=self.resets_at,
        )


class _RouteQuotaStopModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    reached: bool
    reason: str = ""
    retry_after_seconds: int | None = None
    provider_code: str = ""
    native: dict[str, Any] = Field(default_factory=dict)

    @field_validator("reason", "provider_code")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("retry_after_seconds")
    @classmethod
    def _non_negative_retry_after(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("retry_after_seconds must be non-negative")
        return value

    @model_validator(mode="after")
    def _require_reason_when_reached(self) -> Self:
        if self.reached and not self.reason:
            raise ValueError("quota_stop.reason is required when quota was reached")
        _reject_identity_metadata(self.native)
        return self

    def to_stop(self) -> RouteQuotaStop:
        return RouteQuotaStop(
            reached=self.reached,
            reason=self.reason,
            retry_after_seconds=self.retry_after_seconds,
            provider_code=self.provider_code,
            native=self.native,
        )


class _RouteAvailabilitySignalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    provider: str
    model: str = ""
    workload: str = ""
    evidence_source: str = "snapshot"
    checked_at: int | None = None
    stale: bool = False
    windows: list[_RouteQuotaWindowModel] = Field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] "Pydantic Field default_factory is untyped here; annotation is the runtime contract"
    quota_stop: _RouteQuotaStopModel | None = None
    unavailable_reason: str = ""

    @field_validator("provider")
    @classmethod
    def _non_empty_provider(cls, value: str) -> str:
        text = value.strip().lower()
        if not text:
            raise ValueError("provider must be non-empty")
        return text

    @field_validator("model", "workload", "evidence_source", "unavailable_reason")
    @classmethod
    def _strip_optional_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("checked_at")
    @classmethod
    def _non_negative_checked_at(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("checked_at must be non-negative")
        return value

    def to_signal(self, *, default_checked_at: int) -> RouteAvailabilitySignal:
        return RouteAvailabilitySignal(
            provider=self.provider,
            model=self.model,
            workload=self.workload,
            evidence_source=self.evidence_source or "snapshot",
            checked_at=self.checked_at if self.checked_at is not None else default_checked_at,
            stale=self.stale,
            windows=tuple(window.to_window() for window in self.windows),
            quota_stop=self.quota_stop.to_stop() if self.quota_stop else None,
            unavailable_reason=self.unavailable_reason,
        )


class _RouteAvailabilitySnapshotModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["route-availability.v1"]
    checked_at: int
    signals: list[_RouteAvailabilitySignalModel]

    @field_validator("checked_at")
    @classmethod
    def _non_negative_checked_at(cls, value: int) -> int:
        if value < 0:
            raise ValueError("checked_at must be non-negative")
        return value

    def to_snapshot(self) -> RouteAvailabilitySnapshot:
        return RouteAvailabilitySnapshot(
            checked_at=self.checked_at,
            signals=tuple(
                signal.to_signal(default_checked_at=self.checked_at) for signal in self.signals
            ),
        )
