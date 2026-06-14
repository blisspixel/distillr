"""Small-sample statistics for the model eval — pure, deterministic, no IO.

The eval gate decides a model *migration* from N fixtures (N=3 per workload
today). A bare ``mean >= bar`` over three points hides how little evidence that
is. These helpers put an honest uncertainty band on the decision: a paired
bootstrap CI on the per-fixture signal, plus a min-sample rule so "high"
confidence is reserved for runs with enough fixtures to mean it.

This is invariant #6's deterministic side — the model proposes per-fixture
verdicts, Python owns the arithmetic and the thresholds. The bootstrap is seeded
(fixed seed) so the eval stays reproducible across runs and in CI.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

__all__ = ["BOOTSTRAP_RESAMPLES", "BOOTSTRAP_SEED", "bootstrap_mean_ci"]

BOOTSTRAP_SEED: int = 0  # fixed so the eval is reproducible run-to-run and in CI
BOOTSTRAP_RESAMPLES: int = 2000


def bootstrap_mean_ci(
    values: Sequence[float],
    *,
    confidence: float = 0.90,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float]:
    """Percentile-bootstrap confidence interval for the mean of ``values``.

    Returns ``(low, high)`` at the given two-sided ``confidence``. Degenerate by
    design at the small end: an empty input is ``(0.0, 0.0)`` and a single point
    (or identical points) yields a zero-width interval at that value — which is
    *why* the caller also enforces a minimum sample count rather than trusting a
    narrow CI from too few points. Seeded, so identical inputs give identical
    bounds (reproducible eval).
    """
    vals = list(values)
    if not vals:
        return (0.0, 0.0)
    if len(vals) == 1:
        return (vals[0], vals[0])
    rng = random.Random(seed)
    n = len(vals)
    means = sorted(sum(vals[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    lo_idx = int((1.0 - confidence) / 2.0 * resamples)
    hi_idx = min(resamples - 1, int((1.0 + confidence) / 2.0 * resamples))
    return (means[lo_idx], means[hi_idx])
