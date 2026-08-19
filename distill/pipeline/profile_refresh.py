# pyright: strict
"""Pack recurring profiles into an overnight time window.

Distill does not schedule itself. This planner decides *which* due profiles fit
the remaining hours so Task Scheduler, cron, or an agent can run one command
and keep a Karpathy-style wiki fed without starting 100 full ingests at once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

from distill.library.profiles import (
    ProfileValidationError,
    ResearchProfile,
    list_research_profile_paths,
    load_research_profile,
)
from distill.llm.cost_policy import LOCAL_PROVIDER_NAMES, CostMode
from distill.parsing import parse_iso_day_hour_duration
from distill.pipeline.duration_estimates import (
    SpeedCalibration,
    estimate_workflow_duration,
    format_duration,
    load_speed_calibration,
)
from distill.pipeline.profile_run import profile_run_state_path, read_profile_state_document

__all__ = [
    "ProfileRefreshPlan",
    "ProfileRefreshSlot",
    "pack_profile_refresh",
]

RefreshReason = Literal["never_run", "failed", "stale", "fresh"]
SkipReason = Literal["", "fresh", "manual", "metered", "invalid", "time_budget", "profile_cap"]

_REASON_ORDER: dict[str, int] = {
    "never_run": 0,
    "failed": 1,
    "stale": 2,
    "fresh": 3,
}
_DEFAULT_FIRST_NIGHT_ITEMS = 3


@dataclass(frozen=True)
class ProfileRefreshSlot:
    """One profile considered for tonight's window."""

    name: str
    topic: str
    cost_mode: str
    reason: RefreshReason
    skip_reason: SkipReason = ""
    estimated_seconds: float = 0.0
    estimated_calibrated: bool = False
    max_new_items: int = 0
    last_run_at: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "topic": self.topic,
            "cost_mode": self.cost_mode,
            "reason": self.reason,
            "skip_reason": self.skip_reason,
            "estimated_seconds": round(self.estimated_seconds, 1),
            "estimated_calibrated": self.estimated_calibrated,
            "estimated_duration": (
                format_duration(self.estimated_seconds)
                if self.estimated_calibrated and self.estimated_seconds > 0
                else "unknown"
            ),
            "max_new_items": self.max_new_items,
            "last_run_at": self.last_run_at,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ProfileRefreshPlan:
    """Library-wide overnight pack: selected work plus what waits until tomorrow."""

    selected: list[ProfileRefreshSlot] = field(default_factory=list[ProfileRefreshSlot])
    deferred: list[ProfileRefreshSlot] = field(default_factory=list[ProfileRefreshSlot])
    max_hours: float = 0.0
    max_profiles: int = 0
    item_limit: int = 0
    estimated_seconds: float = 0.0
    estimated_calibrated: bool = False
    cost_mode: str = "auto"
    local: bool = False
    model: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "profile-refresh.v1",
            "cost_mode": self.cost_mode,
            "local": self.local,
            "model": self.model,
            "max_hours": self.max_hours,
            "max_profiles": self.max_profiles,
            "item_limit": self.item_limit,
            "estimated_seconds": round(self.estimated_seconds, 1),
            "estimated_calibrated": self.estimated_calibrated,
            "estimated_duration": (
                format_duration(self.estimated_seconds)
                if self.estimated_calibrated and self.estimated_seconds > 0
                else "unknown"
            ),
            "selected": [slot.to_dict() for slot in self.selected],
            "deferred": [slot.to_dict() for slot in self.deferred],
            "selected_count": len(self.selected),
            "deferred_count": len(self.deferred),
        }


def pack_profile_refresh(
    library_dir: Path,
    *,
    cost_mode: CostMode,
    provider: str,
    model: str,
    max_hours: float,
    max_profiles: int,
    item_limit: int,
    include_fresh: bool = False,
    include_manual: bool = False,
    now: datetime | None = None,
    calibration: SpeedCalibration | None = None,
) -> ProfileRefreshPlan:
    """Choose due profiles that fit the remaining overnight window."""

    now = now or datetime.now(UTC)
    local = provider in LOCAL_PROVIDER_NAMES
    loaded = (
        calibration
        if calibration is not None
        else load_speed_calibration(library_dir, model=model, provider=provider)
    )
    ranked: list[ProfileRefreshSlot] = []
    deferred: list[ProfileRefreshSlot] = []
    for path in list_research_profile_paths(library_dir):
        slot = _slot_for_profile(
            path,
            library_dir=library_dir,
            cost_mode=cost_mode,
            item_limit=item_limit,
            include_fresh=include_fresh,
            include_manual=include_manual,
            now=now,
            calibration=loaded,
        )
        if slot.skip_reason:
            deferred.append(slot)
        else:
            ranked.append(slot)
    ranked.sort(key=_sort_key)
    selected, overflow = _pack_slots(
        ranked,
        max_seconds=max(max_hours, 0.0) * 3600.0,
        max_profiles=max(max_profiles, 0),
    )
    estimated = sum(slot.estimated_seconds for slot in selected)
    calibrated = bool(selected) and all(slot.estimated_calibrated for slot in selected)
    return ProfileRefreshPlan(
        selected=selected,
        deferred=[*deferred, *overflow],
        max_hours=max_hours,
        max_profiles=max_profiles,
        item_limit=item_limit,
        estimated_seconds=estimated,
        estimated_calibrated=calibrated,
        cost_mode=cost_mode,
        local=local,
        model=model,
    )


def _sort_key(slot: ProfileRefreshSlot) -> tuple[int, str, str]:
    return (_REASON_ORDER.get(slot.reason, 9), slot.last_run_at or "", slot.name)


def _pack_slots(
    ranked: list[ProfileRefreshSlot],
    *,
    max_seconds: float,
    max_profiles: int,
) -> tuple[list[ProfileRefreshSlot], list[ProfileRefreshSlot]]:
    selected: list[ProfileRefreshSlot] = []
    overflow: list[ProfileRefreshSlot] = []
    used = 0.0
    time_limited = max_seconds > 0 and any(slot.estimated_calibrated for slot in ranked)
    for slot in ranked:
        if max_profiles and len(selected) >= max_profiles:
            overflow.append(_with_skip(slot, "profile_cap"))
            continue
        effective = _effective_seconds(
            slot,
            max_seconds=max_seconds,
            used=used,
            time_limited=time_limited,
        )
        next_used = used + effective
        if time_limited and selected and next_used > max_seconds:
            overflow.append(_with_skip(slot, "time_budget"))
            continue
        if time_limited and not selected and effective > max_seconds:
            # Always allow one due profile even if it overruns the window, so a
            # first-night topic still moves. Remaining work waits until tomorrow.
            selected.append(slot)
            used = next_used
            continue
        selected.append(slot)
        used = next_used
    return selected, overflow


def _effective_seconds(
    slot: ProfileRefreshSlot,
    *,
    max_seconds: float,
    used: float,
    time_limited: bool,
) -> float:
    """Duration that actually consumes the overnight window.

    Uncalibrated slots must not pack as free once any sibling has a measured
    duration. An unknown topic fills whatever time is left, so at most one
    unmeasured profile starts in a time-limited window.
    """

    if slot.estimated_calibrated:
        return slot.estimated_seconds
    if not time_limited:
        return 0.0
    remaining = max_seconds - used
    return remaining if remaining > 0 else max_seconds


def _with_skip(slot: ProfileRefreshSlot, skip_reason: SkipReason) -> ProfileRefreshSlot:
    return ProfileRefreshSlot(
        name=slot.name,
        topic=slot.topic,
        cost_mode=slot.cost_mode,
        reason=slot.reason,
        skip_reason=skip_reason,
        estimated_seconds=slot.estimated_seconds,
        estimated_calibrated=slot.estimated_calibrated,
        max_new_items=slot.max_new_items,
        last_run_at=slot.last_run_at,
        detail=slot.detail,
    )


def _slot_for_profile(
    path: Path,
    *,
    library_dir: Path,
    cost_mode: CostMode,
    item_limit: int,
    include_fresh: bool,
    include_manual: bool,
    now: datetime,
    calibration: SpeedCalibration,
) -> ProfileRefreshSlot:
    try:
        profile = load_research_profile(path)
    except ProfileValidationError as exc:
        return ProfileRefreshSlot(
            name=path.stem,
            topic="",
            cost_mode="",
            reason="fresh",
            skip_reason="invalid",
            detail=str(exc),
        )
    if cost_mode == "no-metered" and profile.cost_mode == "paid-ok":
        return _named_slot(profile, reason="fresh", skip_reason="metered")
    reason, last_run_at, prior_seconds = _refresh_reason(profile, library_dir=library_dir, now=now)
    if profile.freshness.cadence == "manual" and not include_manual and reason != "failed":
        return _named_slot(
            profile,
            reason=reason,
            skip_reason="manual",
            last_run_at=last_run_at,
        )
    if (
        reason == "fresh"
        and not include_fresh
        and not (include_manual and profile.freshness.cadence == "manual")
    ):
        return _named_slot(
            profile,
            reason="fresh",
            skip_reason="fresh",
            last_run_at=last_run_at,
        )
    items = max(1, min(profile.limits.max_new_items, item_limit or _DEFAULT_FIRST_NIGHT_ITEMS))
    estimated, calibrated = _estimate_profile_seconds(
        items=items,
        prior_seconds=prior_seconds,
        calibration=calibration,
    )
    return ProfileRefreshSlot(
        name=profile.name,
        topic=profile.topic,
        cost_mode=profile.cost_mode,
        reason=reason,
        estimated_seconds=estimated,
        estimated_calibrated=calibrated,
        max_new_items=items,
        last_run_at=last_run_at,
    )


def _named_slot(
    profile: ResearchProfile,
    *,
    reason: RefreshReason,
    skip_reason: SkipReason,
    last_run_at: str = "",
) -> ProfileRefreshSlot:
    return ProfileRefreshSlot(
        name=profile.name,
        topic=profile.topic,
        cost_mode=profile.cost_mode,
        reason=reason,
        skip_reason=skip_reason,
        last_run_at=last_run_at,
        max_new_items=profile.limits.max_new_items,
    )


def _refresh_reason(
    profile: ResearchProfile,
    *,
    library_dir: Path,
    now: datetime,
) -> tuple[RefreshReason, str, float]:
    state_path = profile_run_state_path(library_dir, profile.name)
    state = _read_state(state_path)
    last_run_at = ""
    prior_seconds = 0.0
    if state is None:
        if profile.freshness.cadence == "manual":
            return "fresh", "", 0.0
        return "never_run", "", 0.0
    last_run_at = str(state.get("last_run_at") or "")
    prior_seconds = _elapsed_from_state(state)
    last_run = state.get("last_run")
    if isinstance(last_run, dict):
        status = str(cast(dict[str, Any], last_run).get("status") or "")
        if status not in {"ok", "complete"}:
            return "failed", last_run_at, prior_seconds
    if profile.freshness.cadence == "manual":
        return "fresh", last_run_at, prior_seconds
    if _is_stale(last_run_at, profile.freshness.stale_after, now=now):
        return "stale", last_run_at, prior_seconds
    return "fresh", last_run_at, prior_seconds


def _read_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        raw = read_profile_state_document(path)
    except (OSError, RecursionError, UnicodeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    return cast(dict[str, Any], raw)


def _elapsed_from_state(state: dict[str, Any]) -> float:
    last_run = state.get("last_run")
    if not isinstance(last_run, dict):
        return 0.0
    run = cast(dict[str, Any], last_run)
    started = _parse_time(str(run.get("started_at") or ""))
    finished = _parse_time(str(run.get("finished_at") or ""))
    if started is None or finished is None or finished <= started:
        return 0.0
    return (finished - started).total_seconds()


def _is_stale(last_run_at: str, stale_after: str, *, now: datetime) -> bool:
    last_run = _parse_time(last_run_at)
    if last_run is None:
        return True
    duration = parse_iso_day_hour_duration(stale_after) or timedelta(days=7)
    return now - last_run > duration


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def _estimate_profile_seconds(
    *,
    items: int,
    prior_seconds: float,
    calibration: SpeedCalibration,
) -> tuple[float, bool]:
    if prior_seconds > 0:
        return prior_seconds, True
    estimate = estimate_workflow_duration(
        {"paper": max(items, 1), "synthesis": 1},
        calibration,
    )
    if estimate.calibrated:
        return estimate.expected_seconds, True
    return 0.0, False
