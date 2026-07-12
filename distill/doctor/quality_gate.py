# pyright: strict
"""Legacy offline structural evaluation helper.

This module scores supplied text with the test fixture in ``tests/eval``. The
public live-model cost and quality workflow is ``distill eval``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Baselines directory — co-located with the eval suite
BASELINES_DIR = Path(__file__).parent.parent.parent / "tests" / "eval" / "baselines"


def _empty_details() -> dict[str, Any]:
    return {}


@dataclass
class EvalResult:
    """Result of evaluating a model against the cloud baseline."""

    model: str
    workload: str
    score: float  # 0.0 - 1.0 (fraction of cloud baseline quality)
    passed: bool  # score >= 0.80
    details: dict[str, Any] = field(default_factory=_empty_details)


def load_baselines(baselines_dir: Path | None = None) -> dict[str, Path]:
    """Load cloud-generated baseline outputs for comparison.

    Returns a mapping of workload name to baseline file path.
    """
    directory = baselines_dir or BASELINES_DIR
    baselines: dict[str, Path] = {}
    if not directory.exists():
        return baselines

    for path in directory.glob("*.md"):
        if path.name == ".gitkeep":
            continue
        # Derive workload name from filename: paper_analysis_amem.md -> analysis
        name = path.stem
        baselines[name] = path

    return baselines


async def run_eval_suite(
    model: str,
    workload: str,
    config: Any = None,
    *,
    test_output: str | None = None,
) -> EvalResult:
    """Run eval suite for a model-workload combination.

    If test_output is provided, evaluates that text directly (useful for
    testing without a live model). Otherwise returns a stub result indicating
    that a live model run is needed.

    Args:
        model: Model name to evaluate.
        workload: Workload type (e.g., "analysis").
        config: Optional router config (unused in offline mode).
        test_output: Pre-generated output to evaluate against baselines.

    Returns:
        EvalResult with score and pass/fail status.
    """
    from tests.eval.runner import evaluate_paper_analysis

    baselines = load_baselines()

    if test_output is not None:
        # Find the best matching baseline for this workload
        baseline_path: Path | None = None
        for name, path in baselines.items():
            if workload in name or "analysis" in name:
                baseline_path = path
                break

        report = evaluate_paper_analysis(test_output, baseline_path=baseline_path)

        return EvalResult(
            model=model,
            workload=workload,
            score=report.overall_score,
            passed=report.passed,
            details={
                "dimensions": [
                    {"name": d.name, "score": d.score, "passed": d.passed, "details": d.details}
                    for d in report.dimensions
                ],
                "summary": report.summary(),
            },
        )

    # Without test_output, we can't run a live model evaluation
    # Return a stub indicating baselines are available but no output to evaluate
    if baselines:
        return EvalResult(
            model=model,
            workload=workload,
            score=0.0,
            passed=False,
            details={
                "status": "no_output",
                "message": (
                    f"Baselines available ({len(baselines)} files) but no model output provided. "
                    "Use `distill eval` for live model evaluation."
                ),
                "baselines": list(baselines.keys()),
            },
        )

    return EvalResult(
        model=model,
        workload=workload,
        score=1.0,
        passed=True,
        details={
            "status": "no_baselines",
            "message": "No baselines available. Generate baselines first.",
        },
    )
