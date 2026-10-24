# pyright: strict
"""Verified local reasoning controls.

Ollama 0.40.4 on this desk accepts ``think`` true or false for models that
advertise the ``thinking`` capability. The same server accepts the strings
low, medium, and high, and a temperature-0 probe of ``gemma4:e2b`` produced
the same answer, thinking length, and token count for all three. Those
strings are not a confirmed effort control. This module does not translate
them into ``think``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_TRUE_VALUES = frozenset({"1", "true", "on", "yes"})
_FALSE_VALUES = frozenset({"0", "false", "off", "no"})
_EFFORT_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_-")


class LocalReasoningConfigError(ValueError):
    """An explicit local reasoning setting cannot be applied as requested."""


@dataclass(frozen=True, slots=True)
class OllamaThinkPlan:
    """What an Ollama chat request will send, and why."""

    think: bool | None
    requested: str
    sent: str
    support: str
    status: str
    effective: str


def local_think_override(provider_name: str, workload_tag: str) -> bool | None:
    """Read ``DISTILL_<WORKLOAD>_LOCAL_THINK``.

    ``None`` means unset, so the provider keeps its current default. An
    explicit value is only returned for Ollama. LM Studio has no verified
    equivalent, so an explicit value there fails before provider contact.
    """

    if provider_name not in {"ollama", "lmstudio"}:
        return None
    key = f"DISTILL_{_env_tag(workload_tag)}_LOCAL_THINK"
    raw = os.environ.get(key, "").strip().lower()
    if raw == "":
        return None
    if raw in _TRUE_VALUES:
        explicit = True
    elif raw in _FALSE_VALUES:
        explicit = False
    else:
        raise LocalReasoningConfigError(
            f"{key} must be true or false. "
            "low, medium, and high are not a confirmed local thinking control."
        )
    if provider_name == "lmstudio":
        raise LocalReasoningConfigError(
            f"{key} is set, but LM Studio has no verified thinking control in this "
            "build. Unset it, or use Ollama with a model that advertises thinking."
        )
    return explicit


def requested_effort_token(workload_tag: str) -> str | None:
    """Return a set effort env value without treating it as a local control."""

    raw = os.environ.get(
        f"DISTILL_{workload_tag.strip().upper()}_REASONING_EFFORT",
        "",
    )
    token = raw.strip().lower()
    return token or None


def lmstudio_effort_receipt(workload_tag: str) -> tuple[str, str, str, str] | None:
    """Receipt for an effort setting LM Studio cannot send."""

    raw = requested_effort_token(workload_tag)
    if not raw:
        return None
    token = _effort_token(raw)
    return (
        f"think=unset;effort={token}",
        "think=omitted",
        f"Effort {token} is not an LM Studio control and was not sent as a level.",
        "unknown",
    )


def plan_ollama_think(
    *,
    explicit_think: bool | None,
    reasoning_effort: str | None,
    supports_thinking: bool | None,
    name_suggests_thinking: bool,
    structured_json: bool,
    degraded: bool = False,
) -> OllamaThinkPlan:
    """Choose the ``think`` field without translating effort labels."""

    effort = _effort_token(reasoning_effort)
    note = _effort_note(effort)
    requested = _requested(explicit_think, effort)
    if degraded:
        return _degraded_plan(requested, note)
    if structured_json:
        return _json_plan(explicit_think, effort, requested, note)
    if explicit_think is True:
        return _explicit_true_plan(
            supports_thinking,
            name_suggests_thinking,
            requested,
            note,
        )
    if explicit_think is False:
        return _explicit_false_plan(supports_thinking, name_suggests_thinking, requested, note)
    return _default_plan(supports_thinking, name_suggests_thinking, effort, requested, note)


def _effort_note(effort: str) -> str:
    if not effort:
        return ""
    return f" Effort {effort} is not an Ollama control and was not sent as a level."


def _degraded_plan(requested: str, note: str) -> OllamaThinkPlan:
    return OllamaThinkPlan(
        think=None,
        requested=requested,
        sent="think=omitted",
        support="The server rejected thinking. The retry omits think." + note,
        status="rejected_retried_without_think",
        effective="rejected_retried_without_think",
    )


def _json_plan(
    explicit_think: bool | None,
    effort: str,
    requested: str,
    note: str,
) -> OllamaThinkPlan:
    if explicit_think is True:
        status = "withheld_for_json"
    elif explicit_think is False:
        status = "applied"
    elif effort:
        status = "effort_unsupported"
    else:
        status = "default"
    return OllamaThinkPlan(
        think=False,
        requested=requested,
        sent="think=false",
        support=(
            "Structured JSON workloads send think=false so the JSON contract stays intact." + note
        ),
        status=status,
        effective="unknown",
    )


def _explicit_true_plan(
    supports_thinking: bool | None,
    name_suggests_thinking: bool,
    requested: str,
    note: str,
) -> OllamaThinkPlan:
    unverified = supports_thinking is False or (
        supports_thinking is None and not name_suggests_thinking
    )
    if unverified:
        raise LocalReasoningConfigError(
            "This Ollama model has no verified thinking control. "
            "Unset DISTILL_<WORKLOAD>_LOCAL_THINK or choose a model whose "
            "server capabilities include thinking."
        )
    if supports_thinking is True:
        basis = "Server capabilities include thinking."
        status = "applied"
    else:
        basis = (
            "Server capabilities were unavailable. The model name matches a "
            "thinking family. Whether the server honors think stays unknown "
            "until it responds."
        )
        status = "name_guess"
    return OllamaThinkPlan(
        think=True,
        requested=requested,
        sent="think=true",
        support=basis + note,
        status=status,
        effective="unknown",
    )


def _explicit_false_plan(
    supports_thinking: bool | None,
    name_suggests_thinking: bool,
    requested: str,
    note: str,
) -> OllamaThinkPlan:
    capable = supports_thinking is True or (supports_thinking is None and name_suggests_thinking)
    if capable:
        return OllamaThinkPlan(
            think=False,
            requested=requested,
            sent="think=false",
            support="Explicit think=false on a thinking-capable model." + note,
            status="applied",
            effective="unknown",
        )
    return OllamaThinkPlan(
        think=None,
        requested=requested,
        sent="think=omitted",
        support="The model does not advertise thinking, so the request omits think." + note,
        status="applied",
        effective="unknown",
    )


def _default_plan(
    supports_thinking: bool | None,
    name_suggests_thinking: bool,
    effort: str,
    requested: str,
    note: str,
) -> OllamaThinkPlan:
    thinking = name_suggests_thinking if supports_thinking is None else supports_thinking
    status = "effort_unsupported" if effort else "default"
    if thinking:
        return OllamaThinkPlan(
            think=True,
            requested=requested,
            sent="think=true",
            support="Default thinking behavior for this model." + note,
            status=status,
            effective="unknown",
        )
    return OllamaThinkPlan(
        think=None,
        requested=requested,
        sent="think=omitted",
        support="Default request omits think for this model." + note,
        status=status,
        effective="unknown",
    )


def confirm_effective(plan: OllamaThinkPlan, *, trace_present: bool) -> str:
    """Record what the runtime confirmed without storing a reasoning trace."""

    if plan.status == "rejected_retried_without_think":
        return plan.effective
    if plan.sent == "think=true" and trace_present:
        return "trace_present"
    return "unknown"


def _env_tag(workload_tag: str) -> str:
    token = workload_tag.strip().upper().replace("-", "_")
    if not token or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for char in token):
        raise LocalReasoningConfigError("Workload tag cannot form a local think setting name.")
    return token


def _effort_token(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    if len(raw) > 32 or any(char not in _EFFORT_CHARS for char in raw):
        return "unrecognized"
    return raw


def _requested(explicit: bool | None, effort: str) -> str:
    think = "unset" if explicit is None else "true" if explicit else "false"
    if effort:
        return f"think={think};effort={effort}"
    return f"think={think}"
