# pyright: strict
"""Cost registry — pricing data and cost computation for LLM models.

Centralises per-model pricing so that ``distill/costs.py`` (run-level
aggregation) and the telemetry module can both compute costs from a single
source of truth.  Supports per-token and per-query pricing models.
"""

from __future__ import annotations

import logging
import math
from datetime import date

logger = logging.getLogger(__name__)

GEMINI_DEEP_RESEARCH_MODEL: str = "gemini-deep-research"
GEMINI_DEEP_RESEARCH_COST: float = 2.50
# Google bills Deep Research for underlying model tokens and tools rather than
# at a flat query price. Distill retains non-binding planning placeholders for
# estimates and display. They are never treated as an actual or enforceable cap.
DEEP_RESEARCH_MAX_COST: float = 5.00
DEEP_RESEARCH_MODEL_ALIASES: tuple[str, ...] = (
    GEMINI_DEEP_RESEARCH_MODEL,
    "deep-research",
    "deep-research-preview-04-2026",
    "deep-research-max-preview-04-2026",
    "deep-research-pro-preview-12-2025",  # superseded 2026-04; kept for historical cost
)
_GEMINI_DEEP_RESEARCH_PRICING: dict[str, float] = {"per_query": GEMINI_DEEP_RESEARCH_COST}
_DEEP_RESEARCH_MAX_PRICING: dict[str, float] = {"per_query": DEEP_RESEARCH_MAX_COST}
_GEMINI_FLASH_INTRO_PRICING_END = date(2026, 12, 31)
_GEMINI_FLASH_INTRO_PRICING: dict[str, float] = {"input": 0.75, "output": 3.75}
_GEMINI_FLASH_STANDARD_PRICING: dict[str, float] = {"input": 1.50, "output": 7.50}

# Registry review metadata is deliberately code-visible so operators and tests
# can distinguish a recently verified price from an old hard-coded guess. CI
# never scrapes vendor pages or contacts a paid API.
PRICING_VERIFIED_ON: str = "2026-08-13"
PRICING_SOURCE_URLS: dict[str, str] = {
    "xai": "https://docs.x.ai/developers/models",
    "gemini": "https://ai.google.dev/gemini-api/docs/pricing",
    "anthropic": "https://platform.claude.com/docs/en/about-claude/pricing",
    "openai": "https://developers.openai.com/api/docs/models/compare",
}

# Cloud speech-to-text pricing, USD per hour of audio (batch rates). Local
# faster-whisper is free. Keyed by the provider/model string TranscriptionResult
# reports, so both are accepted.
TRANSCRIPTION_PRICING: dict[str, float] = {
    "xai-grok-stt": 0.10,
    "grok-stt": 0.10,
    "openai": 0.36,
    "whisper-1": 0.36,
    "local": 0.0,
    "faster-whisper": 0.0,
}
MAX_TRANSCRIPTION_DURATION_SECONDS = 10 * 365 * 24 * 60 * 60

# ---------------------------------------------------------------------------
# Pricing per 1 M tokens.  Per-query models use a ``per_query`` key instead.
# ---------------------------------------------------------------------------

PRICING: dict[str, dict[str, float]] = {
    # xAI Grok — current models
    # xAI bills the higher rates for every token in a request once its prompt
    # reaches 200K tokens. Cached-input discounts are intentionally omitted:
    # Distill does not yet receive a provider-accurate cached-token count, so
    # authorization stays conservative at the uncached rate.
    "grok-4.6": {
        "input": 2.00,
        "output": 6.00,
        "long_context_min_input": 200_000,
        "long_input": 4.00,
        "long_output": 12.00,
    },
    "grok-4.5": {
        "input": 2.00,
        "output": 6.00,
        "long_context_min_input": 200_000,
        "long_input": 4.00,
        "long_output": 12.00,
    },
    "grok-4.3": {
        "input": 1.25,
        "output": 2.50,
        "long_context_min_input": 200_000,
        "long_input": 2.50,
        "long_output": 5.00,
    },
    "grok-4.20-multi-agent-0309": {
        "input": 1.25,
        "output": 2.50,
        "long_context_min_input": 200_000,
        "long_input": 2.50,
        "long_output": 5.00,
    },
    "grok-4.20-0309-non-reasoning": {
        "input": 1.25,
        "output": 2.50,
        "long_context_min_input": 200_000,
        "long_input": 2.50,
        "long_output": 5.00,
    },
    # Compatibility alias retained for configurations written before xAI's
    # exact dated slug was reflected in Distill's registry.
    "grok-4.20-non-reasoning": {
        "input": 1.25,
        "output": 2.50,
        "long_context_min_input": 200_000,
        "long_input": 2.50,
        "long_output": 5.00,
    },
    "grok-4.20-0309-reasoning": {
        "input": 1.25,
        "output": 2.50,
        "long_context_min_input": 200_000,
        "long_input": 2.50,
        "long_output": 5.00,
    },
    "grok-4.20": {
        "input": 1.25,
        "output": 2.50,
        "long_context_min_input": 200_000,
        "long_input": 2.50,
        "long_output": 5.00,
    },
    "grok-imagine-image": {"per_query": 0.50},
    # xAI Grok — retired models (retained for historical cost computation)
    "grok-4-1-fast-reasoning": {"input": 0.20, "output": 0.50},
    "grok-4-1-fast-non-reasoning": {"input": 0.10, "output": 0.25},
    "grok-4-fast-reasoning": {"input": 0.50, "output": 1.50},
    "grok-4-fast-non-reasoning": {"input": 0.25, "output": 0.75},
    "grok-4-0709": {"input": 0.50, "output": 1.50},
    "grok-code-fast-1": {"input": 0.20, "output": 0.50},
    "grok-3": {"input": 3.00, "output": 9.00},
    "grok-imagine-image-pro": {"per_query": 1.00},
    # Google Gemini models (standard paid tier). Gemini 3.7 Flash and 3.6 Flash
    # use launch pricing through 2026-12-31. get_pricing() resolves the date
    # window so estimates change automatically on 2027-01-01.
    "gemini-3.7-flash": _GEMINI_FLASH_INTRO_PRICING,
    "gemini-3.6-flash": _GEMINI_FLASH_INTRO_PRICING,
    "gemini-3.5-flash": {"input": 1.50, "output": 9.00},
    "gemini-3.5-flash-lite": {"input": 0.30, "output": 2.50},
    "gemini-3.1-pro-preview": {
        "input": 2.00,
        "output": 12.00,
        "long_context_min_input": 200_001,
        "long_input": 4.00,
        "long_output": 18.00,
    },
    # Compatibility alias retained for existing configuration and ledgers.
    "gemini-3.1-pro": {
        "input": 2.00,
        "output": 12.00,
        "long_context_min_input": 200_001,
        "long_input": 4.00,
        "long_output": 18.00,
    },
    "gemini-3.1-flash": {"input": 0.25, "output": 1.50},
    # Planning estimates for one Deep Research run. Actual Google billing is
    # based on underlying model inference and tool usage.
    GEMINI_DEEP_RESEARCH_MODEL: _GEMINI_DEEP_RESEARCH_PRICING,
    "deep-research": _GEMINI_DEEP_RESEARCH_PRICING,
    "deep-research-preview-04-2026": _GEMINI_DEEP_RESEARCH_PRICING,
    # Broad "deep-research-max" alias so any dated Max variant prices at the Max
    # rate via prefix match (with longest-prefix-wins in get_pricing), not the
    # cheaper standard "deep-research" alias.
    "deep-research-max": _DEEP_RESEARCH_MAX_PRICING,
    "deep-research-max-preview-04-2026": _DEEP_RESEARCH_MAX_PRICING,
    "deep-research-pro-preview-12-2025": _GEMINI_DEEP_RESEARCH_PRICING,
    # Anthropic API pricing. Fable and Mythos share the high-capability tier;
    # Mythos is limited availability. Opus 5 and the recent Opus 4 releases
    # share the $5/$25 tier.
    "claude-fable-5": {"input": 10.00, "output": 50.00},
    "claude-mythos-5": {"input": 10.00, "output": 50.00},
    "claude-opus-5": {"input": 5.00, "output": 25.00},
    "claude-opus-4-8": {"input": 5.00, "output": 25.00},
    "claude-opus-4-7": {"input": 5.00, "output": 25.00},
    "claude-opus-4-6": {"input": 5.00, "output": 25.00},
    # Family fallback so an unlisted but routable Opus point release (e.g.
    # claude-opus-4-5) prices at the Opus tier instead of falling through to
    # DEFAULT_MODEL's much cheaper Grok rate, which under-reported spend and let
    # a budget cap overshoot by the same factor. Longest-prefix-wins keeps the
    # exact entries above authoritative.
    "claude-opus-4": {"input": 5.00, "output": 25.00},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "claude-sonnet-4": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-haiku-4": {"input": 0.80, "output": 4.00},
    # OpenAI reserved route pricing. The route remains unimplemented, but
    # registry entries keep future estimates and historical ledgers honest.
    "gpt-5.6-sol": {
        "input": 5.00,
        "output": 30.00,
        "long_context_min_input": 272_001,
        "long_input": 10.00,
        "long_output": 45.00,
    },
    # The unqualified gpt-5.6 id aliases Sol in OpenAI's current model catalog.
    "gpt-5.6": {
        "input": 5.00,
        "output": 30.00,
        "long_context_min_input": 272_001,
        "long_input": 10.00,
        "long_output": 45.00,
    },
    "gpt-5.6-terra": {
        "input": 2.50,
        "output": 15.00,
        "long_context_min_input": 272_001,
        "long_input": 5.00,
        "long_output": 22.50,
    },
    "gpt-5.6-luna": {
        "input": 1.00,
        "output": 6.00,
        "long_context_min_input": 272_001,
        "long_input": 2.00,
        "long_output": 9.00,
    },
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
}

DEFAULT_MODEL: str = "grok-4.6"


def deep_research_query_cost(model: str = "") -> float:
    """Return the pre-run planning estimate for a Gemini Deep Research job.

    Model-aware: ``deep-research-max-preview-04-2026`` is ~$5/query, the standard
    variants ~$2.50. Actual billing is token and tool based. An empty model
    falls back to the standard estimate.
    """
    name = model or GEMINI_DEEP_RESEARCH_MODEL
    return get_pricing(name).get("per_query", GEMINI_DEEP_RESEARCH_COST)


def normalize_transcription_duration(seconds: object) -> float:
    """Return a finite, nonnegative duration within the accounting bound."""

    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise ValueError("transcription duration must be a real number")
    try:
        normalized = float(seconds)
    except (OverflowError, ValueError) as exc:
        raise ValueError("transcription duration is outside the supported range") from exc
    if (
        not math.isfinite(normalized)
        or normalized < 0
        or normalized > MAX_TRANSCRIPTION_DURATION_SECONDS
    ):
        raise ValueError(
            "transcription duration must be finite and between 0 and "
            f"{MAX_TRANSCRIPTION_DURATION_SECONDS} seconds"
        )
    return normalized


def transcription_cost(provider: str, seconds: object) -> float:
    """USD for ``seconds`` of audio at ``provider``'s per-hour STT rate.

    Returns 0 for local/unknown providers. ``provider`` is the provider or model
    string from ``TranscriptionResult`` (e.g. ``"xai-grok-stt"``, ``"whisper-1"``).
    """
    duration = normalize_transcription_duration(seconds)
    rate = TRANSCRIPTION_PRICING.get(provider, 0.0)
    return rate * duration / 3600.0


def has_known_transcription_pricing(provider: str) -> bool:
    """Return whether *provider* has an explicit duration-based rate."""

    return provider in TRANSCRIPTION_PRICING


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Compute estimated cost in USD for an LLM call.

    For per-token models the formula is::

        (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000

    Models with a registered long-context threshold use their long-context
    rates for every token once ``input_tokens`` reaches that threshold. For
    planning-only per-query entries (e.g. ``gemini-deep-research``) the
    non-binding placeholder is returned directly, ignoring token counts.
    """
    rates = get_pricing(model)
    if "per_query" in rates:
        return rates["per_query"]
    input_rate = rates.get("input", 0.0)
    output_rate = rates.get("output", 0.0)
    long_context_min_input = rates.get("long_context_min_input")
    if long_context_min_input is not None and input_tokens >= long_context_min_input:
        input_rate = rates.get("long_input", input_rate)
        output_rate = rates.get("long_output", output_rate)
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


def get_pricing(model: str) -> dict[str, float]:
    """Look up pricing for *model*, with prefix-match and default fallback.

    Resolution order:
    1. Date-resolved temporary pricing windows.
    2. Exact match in ``PRICING``.
    3. Prefix match, e.g. ``"grok-4.6-beta"`` matches ``"grok-4.6"``.
    4. Fall back to ``DEFAULT_MODEL`` and log a warning.
    """
    # Normalize first: catalog keys are lowercase, but a model id reaches here
    # in whatever case the operator configured (routing case-folds, so
    # "Claude-Opus-4-8" resolves to a provider and then used to miss every
    # pricing key and silently fall back to DEFAULT_MODEL -- an 8x under-report
    # for Opus. Under-reporting spend is the dangerous direction for the ledger,
    # budget caps, and projections, so match case-insensitively.
    resolved = _resolve_known_pricing(model)
    if resolved is not None:
        return resolved
    logger.warning(
        "No pricing found for model '%s'; falling back to '%s'",
        model,
        DEFAULT_MODEL,
    )
    return PRICING[DEFAULT_MODEL]


def has_known_pricing(model: str) -> bool:
    """Return whether *model* resolves to an explicit registry price."""

    return _resolve_known_pricing(model) is not None


def _resolve_known_pricing(model: str) -> dict[str, float] | None:
    normalized = model.strip().lower()
    if not normalized:
        return None
    if _is_intro_priced_gemini_flash_model(normalized):
        return _gemini_flash_pricing()
    if normalized in PRICING:
        return PRICING[normalized]
    # Prefix matching for versioned model names. Longest key first so the most
    # specific prefix wins -- otherwise a broad alias like "deep-research" would
    # shadow "deep-research-max-..." ($5) and silently price it at the standard
    # $2.50 rate.
    for key in sorted(PRICING, key=len, reverse=True):
        if normalized.startswith(key):
            return PRICING[key]
    return None


def pricing_source_for_model(model: str) -> str:
    """Return the authoritative pricing page for a cloud model, if known."""

    normalized = model.strip().lower()
    if normalized.startswith("grok-"):
        return PRICING_SOURCE_URLS["xai"]
    if normalized.startswith(("gemini-", "deep-research")):
        return PRICING_SOURCE_URLS["gemini"]
    if normalized.startswith("claude-"):
        return PRICING_SOURCE_URLS["anthropic"]
    if normalized.startswith("gpt-"):
        return PRICING_SOURCE_URLS["openai"]
    return ""


def _is_intro_priced_gemini_flash_model(model: str) -> bool:
    normalized = model.strip().lower()
    return normalized.startswith(("gemini-3.7-flash", "gemini-3.6-flash"))


def _gemini_flash_pricing() -> dict[str, float]:
    if _pricing_reference_date() <= _GEMINI_FLASH_INTRO_PRICING_END:
        return _GEMINI_FLASH_INTRO_PRICING
    return _GEMINI_FLASH_STANDARD_PRICING


def _pricing_reference_date() -> date:
    return date.today()
