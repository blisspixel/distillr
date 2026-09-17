# pyright: strict
"""Command-level cost tracking, workflow budgets, and terminal ledger persistence."""

from __future__ import annotations

import logging
import math
from typing import Any

from distill.config import DistillConfig
from distill.pipeline.costs import (
    BudgetExceededError,
    CostTracker,
    ProjectedBudgetExceededError,
    save_run_log,
)

__all__ = [
    "_CommandCostTracker",
    "budgeted_cost_tracker",
    "enforce_projected_workflow_budget",
    "save_command_cost",
    "save_synthesis_command_cost",
    "set_command_cost_metadata",
]

logger = logging.getLogger(__name__)


class _CommandCostTracker(CostTracker):
    """Cost tracker that persists usage and terminal budget evidence."""

    def __init__(
        self,
        config: DistillConfig,
        command: str,
        budget: float | None,
    ) -> None:
        super().__init__(budget=budget)
        self._config = config
        self._command = command
        self._terminal_metadata: dict[str, Any] = {}
        self.budget_failure_logged = False

    def update_terminal_metadata(self, metadata: dict[str, str]) -> None:
        self._terminal_metadata.update({key: value for key, value in metadata.items() if value})

    def _check_budget(self) -> None:
        try:
            super()._check_budget()
        except BudgetExceededError:
            if not self.budget_failure_logged:
                try:
                    save_run_log(
                        self._config.library_dir,
                        self._command,
                        self,
                        metadata={
                            "workflow": self._command,
                            "terminal": "budget_exceeded",
                            **self._terminal_metadata,
                        },
                    )
                except Exception:
                    logger.debug("Failed to persist budget-exceeded cost row", exc_info=True)
                else:
                    self.budget_failure_logged = True
            raise


def budgeted_cost_tracker(config: DistillConfig, command: str) -> CostTracker:
    """Create a run tracker with the configured workflow cap, if any."""
    budget = _workflow_budget_usd(config, command)
    normalized_command = " ".join(command.split()).strip().lower()
    return _CommandCostTracker(config, normalized_command, budget)


def set_command_cost_metadata(tracker: CostTracker, **metadata: str) -> None:
    """Attach known command context to a possible terminal budget ledger row."""
    if isinstance(tracker, _CommandCostTracker):
        tracker.update_terminal_metadata(metadata)


def _workflow_budget_usd(config: DistillConfig, command: str) -> float | None:
    return config.workflow_budget_usd(command)


def enforce_projected_workflow_budget(
    config: DistillConfig,
    command: str,
    projected_cost: float,
) -> None:
    """Refuse a workflow before execution when its credible estimate exceeds its cap."""
    budget = _workflow_budget_usd(config, command)
    if budget is None:
        return
    if not math.isfinite(projected_cost) or projected_cost <= 0:
        return
    if projected_cost > budget:
        raise ProjectedBudgetExceededError(projected_cost, budget)


def save_command_cost(
    config: DistillConfig,
    command: str,
    tracker: CostTracker,
    *,
    metadata: dict[str, Any] | None = None,
    estimated_cost: float | None = None,
) -> None:
    """Persist a command ledger row when a direct workflow recorded usage."""
    if getattr(tracker, "budget_failure_logged", False):
        return
    if not (tracker.entries or tracker.gemini_queries or tracker.transcriptions):
        return
    save_run_log(
        config.library_dir,
        command,
        tracker,
        estimated_cost=estimated_cost,
        metadata=metadata,
    )


def save_synthesis_command_cost(
    config: DistillConfig,
    topic: str,
    channel: str | None,
    tracker: CostTracker,
    *,
    estimated_cost: float | None = None,
) -> None:
    metadata: dict[str, Any] = {"topic": topic}
    if channel:
        metadata["channel"] = channel
    save_command_cost(
        config,
        "synthesis",
        tracker,
        metadata=metadata,
        estimated_cost=estimated_cost,
    )
