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

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from distill.doctor.adapter_manifest import AdapterResultManifest

__all__ = [
    "MIN_USABLE_HEADROOM_PERCENT",
    "RouteAvailabilityDecision",
    "RouteAvailabilitySignal",
    "RouteQuotaStop",
    "RouteQuotaWindow",
    "route_availability_decision",
    "route_availability_signal_from_manifest",
]

MIN_USABLE_HEADROOM_PERCENT = 0.5


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
            "checked_at": self.checked_at,
            "stale": self.stale,
            "windows": [window.to_dict() for window in self.windows],
            "quota_stop": self.quota_stop.to_dict() if self.quota_stop else None,
            "unavailable_reason": self.unavailable_reason,
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
        checked_at=now,
        stale=False,
        quota_stop=quota_stop,
    )


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
