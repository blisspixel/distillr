# pyright: strict
"""Route-pool admission for local, metered, and adapter routes.

This module is the rule-owned selection layer over already collected evidence.
It does not run providers or adapters. It only decides which configured routes
are admissible for a workload under the current cost mode:

- local routes are no-metered by topology
- metered API routes are allowed only when the cost mode permits them
- plan-quota adapter routes require an eligible graduation decision
- credit-metered and unknown routes fail closed unless explicitly allowed

Quality stays outside this module. Adapter quality is represented by
``AdapterGraduationDecision``, which already combines model-judged eval evidence
with adapter doctor proof.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from distill.eval.graduation import AdapterGraduationDecision
from distill.eval.route_availability import (
    RouteAvailabilityDecision,
    RouteAvailabilitySignal,
    route_availability_decision,
)
from distill.llm.cost_policy import (
    CostMode,
    RouteCostClass,
    evaluate_route_cost_policy,
    normalize_cost_mode,
)

__all__ = [
    "RouteCandidate",
    "RoutePoolEntry",
    "RoutePoolSelection",
    "select_route_pool",
]


@dataclass(frozen=True)
class RouteCandidate:
    """One configured route that may be considered for a workload."""

    provider: str
    model: str
    workload: str = ""
    label: str = ""

    @property
    def normalized_provider(self) -> str:
        return self.provider.strip().lower()

    def normalized_workload(self, default: str) -> str:
        return (self.workload or default or "default").strip()

    def to_dict(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "model": self.model,
            "workload": self.workload,
            "label": self.label,
        }


@dataclass(frozen=True)
class RoutePoolEntry:
    """Admission result for one route candidate."""

    candidate: RouteCandidate
    cost_class: RouteCostClass
    allowed: bool
    blocked_reasons: tuple[str, ...] = ()
    graduation: AdapterGraduationDecision | None = None
    availability: RouteAvailabilityDecision | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict(),
            "cost_class": self.cost_class,
            "allowed": self.allowed,
            "blocked_reasons": list(self.blocked_reasons),
            "graduation": self.graduation.to_dict() if self.graduation else None,
            "availability": self.availability.to_dict() if self.availability else None,
        }


@dataclass(frozen=True)
class RoutePoolSelection:
    """The selected route plus the full admissibility ledger."""

    selected: RoutePoolEntry | None
    allowed: tuple[RoutePoolEntry, ...]
    blocked: tuple[RoutePoolEntry, ...]
    cost_mode: CostMode
    workload: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected": self.selected.to_dict() if self.selected else None,
            "allowed": [entry.to_dict() for entry in self.allowed],
            "blocked": [entry.to_dict() for entry in self.blocked],
            "cost_mode": self.cost_mode,
            "workload": self.workload,
        }


def select_route_pool(
    candidates: Sequence[RouteCandidate],
    *,
    cost_mode: CostMode = "auto",
    workload: str = "",
    graduations: Sequence[AdapterGraduationDecision] = (),
    availability_signals: Sequence[RouteAvailabilitySignal] = (),
    now: int | None = None,
    require_live_availability: bool = False,
) -> RoutePoolSelection:
    """Return the admissible route pool and the preferred route.

    Selection is cost-policy first, not quality-ranked. Among admissible routes,
    local routes are preferred, then graduated included-plan adapters, then
    metered APIs, then explicitly paid-ok credit-metered routes. When live
    availability evidence exists inside the same cost class, higher headroom
    wins.
    """

    if availability_signals and now is None:
        raise ValueError("now is required when availability signals are provided")

    mode = normalize_cost_mode(cost_mode)
    workload_label = (workload or "default").strip()
    graduation_index = _graduation_index(graduations)
    availability_index = _availability_index(availability_signals)
    entries = tuple(
        _evaluate_candidate(
            candidate,
            cost_mode=mode,
            default_workload=workload_label,
            graduation_index=graduation_index,
            availability_index=availability_index,
            now=now or 0,
            require_live_availability=require_live_availability,
        )
        for candidate in candidates
    )
    allowed = tuple(entry for entry in entries if entry.allowed)
    blocked = tuple(entry for entry in entries if not entry.allowed)
    selected = min(allowed, key=_route_priority) if allowed else None
    return RoutePoolSelection(
        selected=selected,
        allowed=allowed,
        blocked=blocked,
        cost_mode=mode,
        workload=workload_label,
    )


type _GraduationKey = tuple[str, str, str]
type _AvailabilityKey = tuple[str, str, str]


def _graduation_index(
    graduations: Sequence[AdapterGraduationDecision],
) -> dict[_GraduationKey, AdapterGraduationDecision]:
    return {
        _key(graduation.adapter, graduation.model, graduation.workload): graduation
        for graduation in graduations
    }


def _availability_index(
    availability_signals: Sequence[RouteAvailabilitySignal],
) -> dict[_AvailabilityKey, RouteAvailabilitySignal]:
    index: dict[_AvailabilityKey, RouteAvailabilitySignal] = {}
    for signal in availability_signals:
        workload = signal.workload.strip() or "*"
        index[(signal.normalized_provider, signal.normalized_model, workload)] = signal
    return index


def _evaluate_candidate(
    candidate: RouteCandidate,
    *,
    cost_mode: CostMode,
    default_workload: str,
    graduation_index: dict[_GraduationKey, AdapterGraduationDecision],
    availability_index: dict[_AvailabilityKey, RouteAvailabilitySignal],
    now: int,
    require_live_availability: bool,
) -> RoutePoolEntry:
    provider = candidate.normalized_provider
    workload = candidate.normalized_workload(default_workload)
    policy = evaluate_route_cost_policy(
        cost_mode=cost_mode,
        provider=provider,
        workload=workload,
    )
    blocked = [] if policy.allowed else [policy.reason]
    graduation: AdapterGraduationDecision | None = None
    availability: RouteAvailabilityDecision | None = None

    if policy.cost_class == "included-plan":
        graduation = graduation_index.get(_key(provider, candidate.model, workload))
        if graduation is None:
            blocked.append("adapter graduation proof is missing")
        elif not graduation.eligible:
            blocked.extend(f"adapter graduation: {reason}" for reason in graduation.blocked_reasons)
    elif policy.cost_class == "credit-metered" and cost_mode != "paid-ok":
        blocked.append("credit-metered route requires paid-ok cost mode")
    elif policy.cost_class == "unknown":
        blocked.append("route has unknown billing semantics")

    availability_signal = _find_availability_signal(
        availability_index,
        provider=provider,
        model=candidate.model,
        workload=workload,
    )
    if availability_signal is None:
        if require_live_availability and policy.cost_class in {"included-plan", "local"}:
            blocked.append("live route availability proof is missing")
    else:
        availability = route_availability_decision(availability_signal, now=now)
        if not availability.available:
            blocked.extend(
                f"route availability: {reason}" for reason in availability.blocked_reasons
            )
        elif (
            require_live_availability
            and policy.cost_class == "local"
            and candidate.model.strip()
            and not availability_signal.model.strip()
            and availability_signal.evidence_source == "local-doctor"
        ):
            blocked.append("live local model proof is missing")

    return RoutePoolEntry(
        candidate=candidate,
        cost_class=policy.cost_class,
        allowed=not blocked,
        blocked_reasons=tuple(blocked),
        graduation=graduation,
        availability=availability,
    )


def _key(provider: str, model: str, workload: str) -> _GraduationKey:
    return (provider.strip().lower(), model.strip(), workload.strip() or "default")


def _find_availability_signal(
    availability_index: dict[_AvailabilityKey, RouteAvailabilitySignal],
    *,
    provider: str,
    model: str,
    workload: str,
) -> RouteAvailabilitySignal | None:
    route_model = model.strip()
    route_workload = workload.strip() or "default"
    keys = (
        (provider, route_model, route_workload),
        (provider, "", route_workload),
        (provider, route_model, "*"),
        (provider, "", "*"),
    )
    for key in keys:
        signal = availability_index.get(key)
        if signal is not None:
            return signal
    return None


def _route_priority(entry: RoutePoolEntry) -> tuple[int, int, float, str, str]:
    order = {
        "local": 0,
        "included-plan": 1,
        "metered-api": 2,
        "credit-metered": 3,
        "unknown": 9,
    }
    headroom = entry.availability.headroom_percent if entry.availability else None
    return (
        order[entry.cost_class],
        0 if headroom is not None else 1,
        -(headroom if headroom is not None else -1.0),
        entry.candidate.normalized_provider,
        entry.candidate.model,
    )
