# pyright: strict
"""Pick an installed local model without calling the daemon."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

__all__ = ["suggest_installed_model"]

_SIZE_HINT = re.compile(r"(\d+(?:\.\d+)?)b", re.IGNORECASE)


def _size_hint(name: str, sizes: dict[str, float] | None) -> float:
    if sizes is not None and name in sizes:
        return float(sizes[name])
    matches = _SIZE_HINT.findall(name)
    if not matches:
        return math.inf
    return float(matches[-1])


def suggest_installed_model(
    installed: Sequence[str],
    *,
    sizes: dict[str, float] | None = None,
    rates: dict[str, float] | None = None,
) -> str:
    """Smallest installed model that bench rates as feasible.

    With no bench history, pick the smallest size hint, then the name. An empty
    inventory returns an empty string. This does not query Ollama.
    """

    names = [name.strip() for name in installed if name.strip()]
    if not names:
        return ""
    if rates is None:
        from distill.commands.bench import stored_decode_rates

        rates = stored_decode_rates()
    pool = names
    rated = [name for name in names if rates.get(name, 0.0) > 0]
    if rated:
        pool = rated
    return min(pool, key=lambda name: (_size_hint(name, sizes), name))
