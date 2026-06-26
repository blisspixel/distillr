"""Shared loop-readable next-action schema."""

# pyright: strict

from __future__ import annotations

from dataclasses import dataclass

from distill.library.paths import sanitize_path_component

__all__ = [
    "LoopMetadata",
    "NextAction",
    "NextActionPlan",
    "NextActionVerifier",
    "action_id",
    "loop_metadata",
]


@dataclass(frozen=True)
class NextActionVerifier:
    """Machine-checkable stop condition for an external loop."""

    command: list[str]
    expect: str

    def to_dict(self) -> dict[str, object]:
        return {"command": self.command, "expect": self.expect}


@dataclass(frozen=True)
class LoopMetadata:
    """Small loop admission record for external runners."""

    state_path: str
    max_attempts: int
    acceptance_metric: str

    def to_dict(self) -> dict[str, object]:
        return {
            "state_path": self.state_path,
            "max_attempts": self.max_attempts,
            "acceptance_metric": self.acceptance_metric,
        }


@dataclass(frozen=True)
class NextAction:
    """One bounded action an external runner can inspect, run, and verify."""

    id: str
    kind: str
    severity: str
    rationale: str
    command: list[str]
    approval: str
    estimated_cost_usd: float | None
    writes: list[str]
    verifier: NextActionVerifier
    loop: LoopMetadata | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "id": self.id,
            "kind": self.kind,
            "severity": self.severity,
            "rationale": self.rationale,
            "command": self.command,
            "approval": self.approval,
            "estimated_cost_usd": self.estimated_cost_usd,
            "writes": self.writes,
            "verifier": self.verifier.to_dict(),
        }
        if self.loop is not None:
            data["loop"] = self.loop.to_dict()
        return data


@dataclass(frozen=True)
class NextActionPlan:
    """Stable JSON contract for external stewardship loops."""

    schema_version: str
    topic: str
    generated_at: str
    actions: list[NextAction]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "topic": self.topic,
            "generated_at": self.generated_at,
            "actions": [a.to_dict() for a in self.actions],
        }


def action_id(scope: str, kind: str, suffix: str = "") -> str:
    """Return a stable dotted action id."""

    raw = ".".join(p for p in (scope, kind, suffix) if p)
    return sanitize_path_component(raw).replace("-", ".")


def loop_metadata(
    action_id_value: str,
    *,
    max_attempts: int = 1,
    acceptance_metric: str = "verifier_passed",
) -> LoopMetadata:
    """Return standard loop metadata for one action id."""

    return LoopMetadata(
        state_path=f".distill/loops/{action_id_value}.json",
        max_attempts=max_attempts,
        acceptance_metric=acceptance_metric,
    )
