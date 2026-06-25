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

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict(),
            "cost_class": self.cost_class,
            "allowed": self.allowed,
            "blocked_reasons": list(self.blocked_reasons),
            "graduation": self.graduation.to_dict() if self.graduation else None,
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
) -> RoutePoolSelection:
    """Return the admissible route pool and the preferred route.

    Selection is cost-policy first, not quality-ranked. Among admissible routes,
    local routes are preferred, then graduated included-plan adapters, then
    metered APIs, then explicitly paid-ok credit-metered routes. Candidates keep
    their input order inside each cost class.
    """

    mode = normalize_cost_mode(cost_mode)
    workload_label = (workload or "default").strip()
    graduation_index = _graduation_index(graduations)
    entries = tuple(
        _evaluate_candidate(
            candidate,
            cost_mode=mode,
            default_workload=workload_label,
            graduation_index=graduation_index,
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


def _graduation_index(
    graduations: Sequence[AdapterGraduationDecision],
) -> dict[_GraduationKey, AdapterGraduationDecision]:
    return {
        _key(graduation.adapter, graduation.model, graduation.workload): graduation
        for graduation in graduations
    }


def _evaluate_candidate(
    candidate: RouteCandidate,
    *,
    cost_mode: CostMode,
    default_workload: str,
    graduation_index: dict[_GraduationKey, AdapterGraduationDecision],
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

    return RoutePoolEntry(
        candidate=candidate,
        cost_class=policy.cost_class,
        allowed=not blocked,
        blocked_reasons=tuple(blocked),
        graduation=graduation,
    )


def _key(provider: str, model: str, workload: str) -> _GraduationKey:
    return (provider.strip().lower(), model.strip(), workload.strip() or "default")


def _route_priority(entry: RoutePoolEntry) -> tuple[int, str, str]:
    order = {
        "local": 0,
        "included-plan": 1,
        "metered-api": 2,
        "credit-metered": 3,
        "unknown": 9,
    }
    return (
        order[entry.cost_class],
        entry.candidate.normalized_provider,
        entry.candidate.model,
    )
