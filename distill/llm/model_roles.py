# pyright: strict
"""Named local model roles, so one machine can hold several brains.

A machine that runs local inference usually has more than one model installed,
and they are not interchangeable. A mixture-of-experts model may decode several
times faster than a smaller dense one; only some models can produce a reasoning
trace; and a corpus about security, drug policy, or extremism will hit refusals
from a safety-tuned model that have nothing to do with analytical quality -- a
refusal mid-corpus is worse than a wrong answer, because it silently leaves a
hole the synthesis will never mention.

So roles name *which brain reads the receipts*. They never change how carefully
it reads: every role runs the same calibrated prompts through the same verify
gate. Buying speed with fidelity is excluded by the project charter -- "a local
insight must be good enough that synthesis and expert queries can trust it
without qualification" -- and a role that lowered that floor would be exactly
the cheap mode the charter refuses.

Assignment is suggested from facts the server reports (declared capabilities)
and facts this machine measured (decode rate).

The unfiltered role is the one case with no server-side signal, so it falls back
to a name hint. That is a deliberate and bounded exception: a name pattern must
never *decide* anything, but offering "this one looks like it, is that what you
meant?" is a discovery aid the operator confirms, not a judgment the tool makes.
It is labeled as a name guess wherever it appears, it never auto-assigns, and
the patterns are operator-editable through ``DISTILL_UNFILTERED_HINTS``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = [
    "ROLES",
    "RoleAssignment",
    "RoleCandidate",
    "resolve_role_model",
    "role_env_var",
    "suggest_roles",
]

# Ordered from least to most effort. "unfiltered" is deliberately outside that
# ordering: it is a different axis (what the model will engage with), not a
# quality or speed tier.
ROLES: tuple[str, ...] = ("fast", "standard", "deep", "unfiltered")

_ENV_PREFIX = "DISTILL_MODEL_"

# A model that reports a reasoning trace is the structural signal for "deep".
_THINKING = "thinking"

# Substrings that commonly mark a model tuned without refusal behavior. Only
# ever used to *offer* a candidate for the unfiltered role, never to classify
# one. Override with DISTILL_UNFILTERED_HINTS as a comma-separated list.
_DEFAULT_UNFILTERED_HINTS: tuple[str, ...] = (
    "abliterated",
    "uncensored",
    "unfiltered",
    "unrestricted",
    "dolphin",
    "nsfw",
)
_UNFILTERED_HINTS_ENV = "DISTILL_UNFILTERED_HINTS"


@dataclass(frozen=True)
class RoleCandidate:
    """One installed model, as the server and this machine describe it."""

    name: str
    size_gb: float = 0.0
    capabilities: frozenset[str] = frozenset()
    decode_tokens_per_second: float = 0.0
    # Model-judged faithfulness from `distill eval`, the only quality signal
    # allowed to influence a suggestion. Speed, size, and capability breadth
    # say nothing about whether a model's analysis is any good.
    judged_faithful: bool = False

    @property
    def can_think(self) -> bool:
        return _THINKING in self.capabilities

    @property
    def measured(self) -> bool:
        return self.decode_tokens_per_second > 0

    @property
    def capability_breadth(self) -> int:
        """How many analysis-relevant capabilities the server declares."""
        return len(self.capabilities & {"completion", "tools", _THINKING})


@dataclass(frozen=True)
class RoleAssignment:
    """Which model a role resolves to, and why."""

    role: str
    model: str
    reason: str


def role_env_var(role: str) -> str:
    """Environment variable that pins a role, e.g. DISTILL_MODEL_DEEP."""
    return f"{_ENV_PREFIX}{role.strip().upper()}"


class _RoleSettings(BaseSettings):
    """Role assignments, read from the environment and the project .env.

    Reading ``os.environ`` alone was wrong: Distill's settings are loaded from
    ``.env`` by pydantic rather than exported into the process environment, so a
    role written by ``distill roles set`` was invisible to a plain env lookup.
    """

    model_config = SettingsConfigDict(
        env_prefix="DISTILL_MODEL_",
        env_file=".env",
        extra="ignore",
        protected_namespaces=(),
    )

    fast: str = ""
    standard: str = ""
    deep: str = ""
    unfiltered: str = ""


def resolve_role_model(
    role: str,
    *,
    env: Mapping[str, str] | None = None,
    fallback: str = "",
) -> str:
    """Model id for ``role``, or ``fallback`` when the role is unset.

    An unset role falls back rather than failing here: the caller decides
    whether an unset role is an error, and a library-level resolver should not
    make that policy choice.
    """
    if role not in ROLES:
        return fallback
    if env is not None:
        return (env.get(role_env_var(role), "") or "").strip() or fallback
    assigned: str = getattr(_RoleSettings(), role, "")
    return assigned.strip() or fallback


def unfiltered_hints(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """Name substrings that hint at a refusal-free model, operator-editable."""
    import os

    source = os.environ if env is None else env
    raw = (source.get(_UNFILTERED_HINTS_ENV, "") or "").strip()
    if not raw:
        return _DEFAULT_UNFILTERED_HINTS
    configured = tuple(part.strip().casefold() for part in raw.split(",") if part.strip())
    return configured or _DEFAULT_UNFILTERED_HINTS


def _unfiltered_hint_match(
    candidates: Sequence[RoleCandidate],
    hints: Sequence[str],
) -> RoleCandidate | None:
    """Smallest model whose name matches a hint, or None.

    Smallest because this role is usually reached for a specific awkward source
    rather than a whole corpus, and the cheapest capable option is the sane
    default to *offer*. The operator decides.
    """
    matched = [
        candidate
        for candidate in candidates
        if any(hint in candidate.name.casefold() for hint in hints)
    ]
    return min(matched, key=lambda c: (c.size_gb, c.name)) if matched else None


def _fastest(candidates: Sequence[RoleCandidate]) -> RoleCandidate | None:
    """Highest measured decode rate, or the smallest when nothing is measured.

    Size is the fallback ordering only. It is a weak proxy -- a 30B
    mixture-of-experts measured four times faster than a 27B dense model on the
    same machine -- which is why a measurement always wins when one exists.
    """
    measured = [c for c in candidates if c.measured]
    if measured:
        return max(measured, key=lambda c: c.decode_tokens_per_second)
    return min(candidates, key=lambda c: (c.size_gb, c.name)) if candidates else None


def _standard(candidates: Sequence[RoleCandidate]) -> RoleCandidate | None:
    """The everyday default: quality-led, never speed-led.

    A model judged faithful wins outright. With no quality evidence the best
    available proxy is what the server says the model can do, broken by size --
    both weak, which is why the reason string says the ranking is unranked on
    quality and points at the arbiter that can rank it.
    """
    if not candidates:
        return None
    judged = [c for c in candidates if c.judged_faithful]
    pool = judged or list(candidates)
    return max(pool, key=lambda c: (c.capability_breadth, c.size_gb, c.name))


def _deepest(candidates: Sequence[RoleCandidate]) -> RoleCandidate | None:
    """Prefer a model the server says can reason; break ties by size."""
    thinkers = [c for c in candidates if c.can_think]
    pool = thinkers or list(candidates)
    return max(pool, key=lambda c: (c.size_gb, c.name)) if pool else None


def suggest_roles(
    candidates: Sequence[RoleCandidate],
    *,
    env: Mapping[str, str] | None = None,
) -> tuple[RoleAssignment, ...]:
    """Propose role assignments from server-declared and measured facts.

    Every suggestion states the evidence behind it, so an operator can see the
    difference between "the server reports this" and "this name looks like it".
    """
    if not candidates:
        return ()

    assignments: list[RoleAssignment] = []
    fast = _fastest(candidates)
    if fast is not None:
        # Speed is the definition of this role, not a claim about its output.
        reason = (
            f"fastest measured decode ({fast.decode_tokens_per_second:.1f} tok/s) "
            f"- speed only, not a quality ranking"
            if fast.measured
            else f"smallest installed ({fast.size_gb:.1f} GB); run `distill bench` to rank by measured speed"
        )
        assignments.append(RoleAssignment("fast", fast.name, reason))

    deep = _deepest(candidates)
    if deep is not None:
        reason = (
            "the only installed model the server reports as thinking-capable"
            if deep.can_think and sum(1 for c in candidates if c.can_think) == 1
            else "reports a reasoning trace"
            if deep.can_think
            else "largest installed; no model here reports a reasoning trace"
        )
        assignments.append(RoleAssignment("deep", deep.name, reason))

    # Standard is the everyday default, so it must not be chosen for speed.
    # Being quick says nothing about whether the analysis is worth keeping, and
    # a corpus is only as good as the insights written into it. Prefer a model
    # `distill eval` has judged faithful; otherwise decline to rank on quality
    # and say so, rather than quietly substituting the fastest.
    standard = _standard(candidates)
    if standard is not None:
        certified = [c for c in candidates if c.judged_faithful]
        reason = (
            "judged faithful by `distill eval` on this corpus"
            if standard.judged_faithful
            else "most capable by the server's own report - quality is UNRANKED "
            "until `distill eval` judges these models"
        )
        assignments.append(RoleAssignment("standard", standard.name, reason))
        del certified

    # Name-based, and labeled as such. Nothing the server reports distinguishes
    # a refusal-free model, so this is an offer to confirm, not a finding.
    hinted = _unfiltered_hint_match(candidates, unfiltered_hints(env))
    if hinted is not None:
        assignments.append(
            RoleAssignment(
                "unfiltered",
                hinted.name,
                "name looks like a refusal-free build - confirm before relying on it",
            )
        )
    return tuple(assignments)
