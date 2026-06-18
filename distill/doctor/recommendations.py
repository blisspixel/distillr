# pyright: strict
"""Model recommendations based on detected hardware profile.

Provides hardware-tier-aware model suggestions for local inference,
including context window sizes and pull commands.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from distill.doctor.hardware import HardwareProfile

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelRecommendation:
    """A recommended model for a given hardware tier."""

    model_name: str
    context_window: int
    reason: str


# Default recommendation table — loaded from config if available, otherwise hardcoded
_DEFAULT_RECOMMENDATIONS: dict[str, list[dict[str, str | int]]] = {
    "nvidia_24gb": [
        {
            "model_name": "qwen3.5:27b",
            "context_window": 131072,
            "reason": "Best reasoning quality for 24GB VRAM",
        },
        {
            "model_name": "llama4:scout",
            "context_window": 131072,
            "reason": "MoE with 10M native context",
        },
    ],
    "nvidia_12gb": [
        {
            "model_name": "qwen3.5:14b",
            "context_window": 65536,
            "reason": "Fits 12-16GB VRAM",
        },
    ],
    "apple_silicon_32gb": [
        {
            "model_name": "qwen3.5:27b",
            "context_window": 131072,
            "reason": "Full-size model in unified memory",
        },
        {
            "model_name": "gemma4:27b",
            "context_window": 131072,
            "reason": "Strong reasoning alternative",
        },
    ],
    "apple_silicon_16gb": [
        {
            "model_name": "qwen3.5:14b",
            "context_window": 65536,
            "reason": "Best fit for 16GB unified memory",
        },
        {
            "model_name": "gemma4:12b",
            "context_window": 32768,
            "reason": "Compact alternative",
        },
    ],
}


def _load_recommendation_table(
    config_path: Path | None = None,
) -> dict[str, list[dict[str, str | int]]]:
    """Load recommendation table from JSON config file, falling back to defaults."""
    if config_path and config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return cast(dict[str, list[dict[str, str | int]]], data)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load recommendation config: %s", exc)
    return _DEFAULT_RECOMMENDATIONS


def recommend_models(
    profile: HardwareProfile,
    config_path: Path | None = None,
) -> list[ModelRecommendation]:
    """Recommend models based on detected hardware.

    Returns a list of ModelRecommendation sorted by preference (best first).
    """
    table = _load_recommendation_table(config_path)
    tier = _classify_hardware_tier(profile)

    if not tier or tier not in table:
        return []

    entries = table[tier]
    return [
        ModelRecommendation(
            model_name=str(e["model_name"]),
            context_window=int(e["context_window"]),
            reason=str(e["reason"]),
        )
        for e in entries
    ]


def _classify_hardware_tier(profile: HardwareProfile) -> str:
    """Classify hardware into a tier key for the recommendation table."""
    if profile.gpu_type == "nvidia" and profile.vram_gb >= 24:
        return "nvidia_24gb"
    elif profile.gpu_type == "nvidia" and profile.vram_gb >= 12:
        return "nvidia_12gb"
    elif profile.gpu_type == "apple_silicon" and profile.vram_gb >= 32:
        return "apple_silicon_32gb"
    elif profile.gpu_type == "apple_silicon" and profile.vram_gb >= 16:
        return "apple_silicon_16gb"
    return ""


def estimate_throughput(profile: HardwareProfile) -> float:
    """Estimate tokens/second based on hardware tier.

    Returns a rough estimate for display purposes.
    """
    if profile.gpu_type == "nvidia":
        if profile.vram_gb >= 24:
            return 60.0
        elif profile.vram_gb >= 12:
            return 35.0
        else:
            return 15.0
    elif profile.gpu_type == "apple_silicon":
        if profile.vram_gb >= 32:
            return 25.0
        elif profile.vram_gb >= 16:
            return 18.0
        else:
            return 10.0
    return 0.0
