# pyright: strict
"""Cost registry — pricing data and cost computation for LLM models.

Centralises per-model pricing so that ``distill/costs.py`` (run-level
aggregation) and the telemetry module can both compute costs from a single
source of truth.  Supports per-token and per-query pricing models.
"""

from __future__ import annotations

import logging
from datetime import date

logger = logging.getLogger(__name__)

GEMINI_DEEP_RESEARCH_MODEL: str = "gemini-deep-research"
GEMINI_DEEP_RESEARCH_COST: float = 2.50
# Deep Research Max reads many more sources per task (~$5/report typical, $2-15
# range) so it carries a distinct per-query estimate from the standard variant.
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
_SONNET_5_INTRO_PRICING_END = date(2026, 8, 31)
_SONNET_5_INTRO_PRICING: dict[str, float] = {"input": 2.00, "output": 10.00}
_SONNET_5_STANDARD_PRICING: dict[str, float] = {"input": 3.00, "output": 15.00}

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

# ---------------------------------------------------------------------------
# Pricing per 1 M tokens.  Per-query models use a ``per_query`` key instead.
# ---------------------------------------------------------------------------

PRICING: dict[str, dict[str, float]] = {
    # xAI Grok — current models
    "grok-4.3": {"input": 1.25, "output": 2.50},
    "grok-4.20-non-reasoning": {"input": 2.00, "output": 6.00},
    "grok-4.20-0309-reasoning": {"input": 2.00, "output": 6.00},
    "grok-4.20": {"input": 2.00, "output": 6.00},
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
    # Google Gemini models
    "gemini-3.5-flash": {"input": 1.50, "output": 9.00},
    "gemini-3.1-pro": {"input": 2.00, "output": 12.00},
    "gemini-3.1-flash": {"input": 0.25, "output": 1.50},
    # Deep Research is a per-query product; $2.50/query is an approximation across
    # the standard variants (Max may run higher).
    GEMINI_DEEP_RESEARCH_MODEL: _GEMINI_DEEP_RESEARCH_PRICING,
    "deep-research": _GEMINI_DEEP_RESEARCH_PRICING,
    "deep-research-preview-04-2026": _GEMINI_DEEP_RESEARCH_PRICING,
    # Broad "deep-research-max" alias so any dated Max variant prices at the Max
    # rate via prefix match (with longest-prefix-wins in get_pricing), not the
    # cheaper standard "deep-research" alias.
    "deep-research-max": _DEEP_RESEARCH_MAX_PRICING,
    "deep-research-max-preview-04-2026": _DEEP_RESEARCH_MAX_PRICING,
    "deep-research-pro-preview-12-2025": _GEMINI_DEEP_RESEARCH_PRICING,
    # Anthropic reserved route pricing estimates
    "claude-sonnet-5": _SONNET_5_INTRO_PRICING,
    "claude-sonnet-4": {"input": 3.00, "output": 15.00},
    "claude-haiku-4": {"input": 0.80, "output": 4.00},
    # OpenAI reserved route pricing estimates
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
}

DEFAULT_MODEL: str = "grok-4.3"


def deep_research_query_cost(model: str = "") -> float:
    """Return the per-query estimate for a Gemini Deep Research job.

    Model-aware: ``deep-research-max-preview-04-2026`` is ~$5/query, the standard
    variants ~$2.50. An empty model falls back to the standard estimate.
    """
    name = model or GEMINI_DEEP_RESEARCH_MODEL
    return get_pricing(name).get("per_query", GEMINI_DEEP_RESEARCH_COST)


def transcription_cost(provider: str, seconds: float) -> float:
    """USD for ``seconds`` of audio at ``provider``'s per-hour STT rate.

    Returns 0 for local/unknown providers. ``provider`` is the provider or model
    string from ``TranscriptionResult`` (e.g. ``"xai-grok-stt"``, ``"whisper-1"``).
    """
    rate = TRANSCRIPTION_PRICING.get(provider, 0.0)
    return rate * max(0.0, seconds) / 3600.0


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Compute estimated cost in USD for an LLM call.

    For per-token models the formula is::

        (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000

    For per-query models (e.g. ``gemini-deep-research``) the per-query cost
    is returned directly, ignoring token counts.
    """
    rates = get_pricing(model)
    if "per_query" in rates:
        return rates["per_query"]
    return (
        input_tokens * rates.get("input", 0.0) + output_tokens * rates.get("output", 0.0)
    ) / 1_000_000


def get_pricing(model: str) -> dict[str, float]:
    """Look up pricing for *model*, with prefix-match and default fallback.

    Resolution order:
    1. Date-resolved temporary pricing windows.
    2. Exact match in ``PRICING``.
    3. Prefix match, e.g. ``"grok-4.3-beta"`` matches ``"grok-4.3"``.
    4. Fall back to ``DEFAULT_MODEL`` and log a warning.
    """
    if _is_sonnet_5_model(model):
        return _sonnet_5_pricing()
    if model in PRICING:
        return PRICING[model]
    # Prefix matching for versioned model names. Longest key first so the most
    # specific prefix wins -- otherwise a broad alias like "deep-research" would
    # shadow "deep-research-max-..." ($5) and silently price it at the standard
    # $2.50 rate.
    for key in sorted(PRICING, key=len, reverse=True):
        if model.startswith(key):
            return PRICING[key]
    logger.warning(
        "No pricing found for model '%s'; falling back to '%s'",
        model,
        DEFAULT_MODEL,
    )
    return PRICING[DEFAULT_MODEL]


def _is_sonnet_5_model(model: str) -> bool:
    return model.startswith("claude-sonnet-5")


def _sonnet_5_pricing() -> dict[str, float]:
    if _pricing_reference_date() <= _SONNET_5_INTRO_PRICING_END:
        return _SONNET_5_INTRO_PRICING
    return _SONNET_5_STANDARD_PRICING


def _pricing_reference_date() -> date:
    return date.today()
