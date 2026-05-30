# pyright: strict
"""Cost registry — pricing data and cost computation for LLM models.

Centralises per-model pricing so that ``distill/costs.py`` (run-level
aggregation) and the telemetry module can both compute costs from a single
source of truth.  Supports per-token and per-query pricing models.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

GEMINI_DEEP_RESEARCH_MODEL: str = "gemini-deep-research"
GEMINI_DEEP_RESEARCH_COST: float = 2.50
DEEP_RESEARCH_MODEL_ALIASES: tuple[str, ...] = (
    GEMINI_DEEP_RESEARCH_MODEL,
    "deep-research",
    "deep-research-preview-04-2026",
    "deep-research-max-preview-04-2026",
    "deep-research-pro-preview-12-2025",  # superseded 2026-04; kept for historical cost
)
_GEMINI_DEEP_RESEARCH_PRICING: dict[str, float] = {"per_query": GEMINI_DEEP_RESEARCH_COST}

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
    "deep-research-max-preview-04-2026": _GEMINI_DEEP_RESEARCH_PRICING,
    "deep-research-pro-preview-12-2025": _GEMINI_DEEP_RESEARCH_PRICING,
    # Anthropic (stub pricing for when users configure it)
    "claude-sonnet-4": {"input": 3.00, "output": 15.00},
    "claude-haiku-4": {"input": 0.80, "output": 4.00},
    # OpenAI (stub pricing)
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
}

DEFAULT_MODEL: str = "grok-4.3"


def deep_research_query_cost() -> float:
    """Return the per-query estimate for Gemini Deep Research jobs."""
    return get_pricing(GEMINI_DEEP_RESEARCH_MODEL).get("per_query", GEMINI_DEEP_RESEARCH_COST)


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
    1. Exact match in ``PRICING``.
    2. Prefix match — e.g. ``"grok-4.3-beta"`` matches ``"grok-4.3"``.
    3. Fall back to ``DEFAULT_MODEL`` and log a warning.
    """
    if model in PRICING:
        return PRICING[model]
    # Prefix matching for versioned model names
    for key in PRICING:
        if model.startswith(key):
            return PRICING[key]
    logger.warning(
        "No pricing found for model '%s'; falling back to '%s'",
        model,
        DEFAULT_MODEL,
    )
    return PRICING[DEFAULT_MODEL]
