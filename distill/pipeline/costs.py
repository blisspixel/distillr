"""Cost tracking for API calls.

Run-level cost aggregation (CostTracker, TokenUsage, save_run_log,
estimate_run_cost).  Per-model pricing is delegated to the unified cost
registry in ``distill.llm.cost`` — this module no longer owns pricing data.
"""

# pyright: strict

from __future__ import annotations

import json
import math
import os
import re
import secrets
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from distill.llm.cost import (
    PRICING as LLM_PRICING,
)
from distill.llm.cost import (
    deep_research_query_cost,
    get_pricing,
    normalize_transcription_duration,
    transcription_cost,
)
from distill.llm.run_context import (
    current_run,
    current_run_elapsed_seconds,
    current_run_id,
    mark_profile_receipt_written,
)
from distill.llm.usage import LLMUsageAttempt
from distill.pipeline.budget import BudgetExceededError, ProjectedBudgetExceededError
from distill.pipeline.cost_estimates import (
    ACCORDION_GROK_ESTIMATE,
    CostCalibration,
    CostEstimate,
    estimate_ask_workflow_cost,
    estimate_discover_cost,
    estimate_discover_items,
    estimate_paper_workflow_cost,
    estimate_routed_video_workflow_cost,
    estimate_run_cost,
    estimate_site_batch_workflow_cost,
    estimate_stage_cost,
    estimate_synthesis_workflow_cost,
    estimate_video_workflow_cost,
    load_cost_calibration,
    report_deep_research_estimate,
)
from distill.pipeline.cost_history import estimator_accuracy, projected_next_run_cost
from distill.pipeline.cost_warnings import CostWarning, cost_anomaly_warnings
from distill.pipeline.usage_records import (
    TokenUsage,
    TranscriptionUsage,
)

__all__ = [
    "ACCORDION_GROK_ESTIMATE",
    "LLM_PRICING",
    "PROFILE_RECEIPT_ENV",
    "BudgetExceededError",
    "CostCalibration",
    "CostEstimate",
    "CostTracker",
    "CostWarning",
    "ProjectedBudgetExceededError",
    "TokenUsage",
    "TranscriptionUsage",
    "cost_anomaly_warnings",
    "ensure_terminal_profile_receipt",
    "estimate_ask_workflow_cost",
    "estimate_discover_cost",
    "estimate_discover_items",
    "estimate_paper_workflow_cost",
    "estimate_routed_video_workflow_cost",
    "estimate_run_cost",
    "estimate_site_batch_workflow_cost",
    "estimate_stage_cost",
    "estimate_synthesis_workflow_cost",
    "estimate_video_workflow_cost",
    "estimator_accuracy",
    "load_cost_calibration",
    "projected_next_run_cost",
    "report_deep_research_estimate",
    "save_run_log",
]

PROFILE_RECEIPT_ENV = "DISTILL_PROFILE_RECEIPT_ID"
_PROFILE_RECEIPT_RE = re.compile(r"[0-9a-f]{64}")


def _token_usage_cost(usage: TokenUsage) -> float:
    if usage.provider_type == "host-managed":
        return 0.0
    if usage.no_metered_cost:
        return 0.0
    rates = get_pricing(usage.model)
    return (
        usage.prompt_tokens * rates.get("input", 0.0) / 1_000_000
        + usage.completion_tokens * rates.get("output", 0.0) / 1_000_000
    )


def _empty_attempt_id_set() -> set[str]:
    return set()


@dataclass
class CostTracker:
    """Accumulates token usage and cost across a run.

    With ``budget`` set, every record raises :class:`BudgetExceededError` once
    total recorded cost crosses it. Fixed-price calls are also authorized
    against the projected total before provider contact, preventing known
    overspend while conservatively recording ambiguous submission failures.
    """

    entries: list[TokenUsage] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] "dataclass default_factory appears as list[Unknown] under strict; usage throughout confirms TokenUsage"
    gemini_queries: int = 0
    gemini_query_models: list[str] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] "dataclass default_factory appears as list[Unknown] under strict; usage confirms list[str]"
    gemini_query_outcomes: list[str] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] "dataclass default_factory appears as list[Unknown] under strict; usage confirms list[str]"
    transcriptions: list[TranscriptionUsage] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] "dataclass default_factory appears as list[Unknown] under strict; usage confirms TranscriptionUsage"
    budget: float | None = None
    run_id: str = field(default_factory=current_run_id)
    _recorded_attempt_ids: set[str] = field(
        default_factory=_empty_attempt_id_set,
        init=False,
        repr=False,
    )
    _profile_tracker_id: str = field(
        default_factory=lambda: secrets.token_hex(16),
        init=False,
        repr=False,
        compare=False,
    )

    @property
    def profile_tracker_id(self) -> str:
        """Stable identity used to deduplicate cumulative profile receipts."""

        return self._profile_tracker_id

    def _check_budget(self):
        if self.budget is not None and self.total_cost > self.budget:
            raise BudgetExceededError(self.total_cost, self.budget)

    def record(self, usage: TokenUsage):
        """Record provider-accurate usage without duplicating streamed attempts."""
        for entry in usage.expanded():
            if entry.attempt_id and entry.attempt_id in self._recorded_attempt_ids:
                continue
            self.entries.append(entry)
            if entry.attempt_id:
                self._recorded_attempt_ids.add(entry.attempt_id)
        self._check_budget()

    def authorize_token_usage(self, usage: TokenUsage) -> None:
        """Refuse projected token spend before provider contact without recording it."""

        seen_attempt_ids = set(self._recorded_attempt_ids)
        projected_increment = 0.0
        for entry in usage.expanded():
            if entry.attempt_id and entry.attempt_id in seen_attempt_ids:
                continue
            if entry.attempt_id:
                seen_attempt_ids.add(entry.attempt_id)
            projected_increment += _token_usage_cost(entry)
        projected = self.total_cost + projected_increment
        if self.budget is not None and projected > self.budget:
            raise ProjectedBudgetExceededError(projected, self.budget)

    def record_attempt(self, attempt: LLMUsageAttempt, *, call_type: str = "") -> None:
        """Record one request before a provider retries or the router falls back."""

        self.record_attempts((attempt,), call_type=call_type)

    def record_attempts(
        self,
        attempts: tuple[LLMUsageAttempt, ...],
        *,
        call_type: str = "",
    ) -> None:
        """Record a completed attempt batch before enforcing the spend limit."""

        self.record(
            TokenUsage(
                call_type=call_type,
                attempts=attempts,
            )
        )

    def authorize_gemini_query(self, model: str = "") -> None:
        """Refuse a known-price Deep Research query before provider contact."""

        projected = self.total_cost + deep_research_query_cost(model)
        if self.budget is not None and projected > self.budget:
            raise ProjectedBudgetExceededError(projected, self.budget)

    def record_gemini_query(self, model: str = "", *, outcome: str = "accepted") -> None:
        """Record an accepted or ambiguously submitted Deep Research query."""

        if outcome not in {"accepted", "ambiguous"}:
            raise ValueError(f"unsupported Gemini query outcome: {outcome}")
        self.gemini_queries += 1
        self.gemini_query_models.append(model)
        self.gemini_query_outcomes.append(outcome)
        self._check_budget()

    def authorize_transcription(self, provider: str, duration_s: float, *, model: str = "") -> None:
        """Refuse a known-price transcription before provider contact."""

        del model
        duration = normalize_transcription_duration(duration_s)
        projected = self.total_cost + transcription_cost(provider, duration)
        if self.budget is not None and projected > self.budget:
            raise ProjectedBudgetExceededError(projected, self.budget)

    def record_transcription(
        self,
        provider: str,
        duration_s: float,
        *,
        model: str = "",
        outcome: str = "completed",
    ) -> None:
        """Record a cloud transcription call's audio duration and estimated cost.

        Local transcription (faster-whisper) is free; recording it is harmless
        (cost resolves to 0) and keeps the ledger complete.
        """
        if outcome not in {"completed", "failed"}:
            raise ValueError(f"unsupported transcription outcome: {outcome}")
        duration = normalize_transcription_duration(duration_s)
        self.transcriptions.append(
            TranscriptionUsage(
                provider=provider,
                model=model,
                duration_s=duration,
                cost=transcription_cost(provider, duration),
                outcome=outcome,
            )
        )
        self._check_budget()

    @property
    def total_input_tokens(self) -> int:
        return sum(e.prompt_tokens for e in self.entries)

    @property
    def total_output_tokens(self) -> int:
        return sum(e.completion_tokens for e in self.entries)

    @property
    def total_grok_cost(self) -> float:
        """Estimated xAI cost based on token usage and the actual model used."""
        return sum(_token_usage_cost(entry) for entry in self.entries)

    @property
    def total_gemini_cost(self) -> float:
        """Estimated Gemini Deep Research cost, per-query and model-aware.

        When the per-query models are known (the normal path) each query is
        priced by its model, so Deep Research Max (~$5) is counted at its higher
        rate. Falls back to the standard per-query estimate for count-only
        trackers (e.g. sub-range report copies that carry only ``gemini_queries``).
        """
        if self.gemini_query_models:
            return sum(deep_research_query_cost(m) for m in self.gemini_query_models)
        return self.gemini_queries * deep_research_query_cost()

    @property
    def total_transcription_cost(self) -> float:
        """Estimated cloud speech-to-text cost across the run."""
        return sum(t.cost for t in self.transcriptions)

    @property
    def total_cost(self) -> float:
        return self.total_grok_cost + self.total_gemini_cost + self.total_transcription_cost

    def format_cost(self) -> str:
        """Human-readable cost string."""
        total = self.total_cost
        if total < 0.01:
            return f"${total:.4f}"
        return f"${total:.2f}"

    def summary_dict(self) -> dict[str, Any]:
        """Summary for logging/display."""
        by_model: dict[str, dict[str, float | int]] = {}
        by_provider: dict[str, dict[str, Any]] = {}
        host_managed_calls = sum(
            1 for entry in self.entries if entry.provider_type == "host-managed"
        )
        for entry in self.entries:
            model_summary = by_model.setdefault(
                entry.model or "unknown",
                {"calls": 0, "input_tokens": 0, "output_tokens": 0},
            )
            model_summary["calls"] += 1
            model_summary["input_tokens"] += entry.prompt_tokens
            model_summary["output_tokens"] += entry.completion_tokens

            provider_key = _provider_key(entry)
            provider_summary = by_provider.setdefault(
                provider_key,
                {
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "provider_name": entry.provider_name,
                    "provider_type": entry.provider_type,
                    "no_metered_cost": entry.no_metered_cost,
                },
            )
            provider_summary["calls"] += 1
            provider_summary["input_tokens"] += entry.prompt_tokens
            provider_summary["output_tokens"] += entry.completion_tokens

        summary: dict[str, Any] = {
            "grok_calls": len(self.entries),
            "gemini_queries": self.gemini_queries,
            "metered_calls": sum(
                1
                for e in self.entries
                if not e.no_metered_cost and e.provider_type != "host-managed"
            ),
            "no_metered_calls": sum(1 for e in self.entries if e.no_metered_cost),
            "host_managed_calls": host_managed_calls,
            "conservative_usage_calls": sum(
                1 for e in self.entries if e.usage_source == "conservative"
            ),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "estimated_grok_cost": f"${self.total_grok_cost:.4f}",
            "estimated_gemini_cost": f"${self.total_gemini_cost:.2f}",
            "estimated_total_cost": self.format_cost(),
            "by_model": by_model,
            "by_provider": by_provider,
        }
        if host_managed_calls:
            summary["external_cost_status"] = "unavailable"
            summary["estimated_total_cost_scope"] = "distill-direct-charges"
        if self.gemini_query_outcomes:
            summary["gemini_query_outcomes"] = {
                outcome: self.gemini_query_outcomes.count(outcome)
                for outcome in sorted(set(self.gemini_query_outcomes))
            }
        if self.transcriptions:
            summary["transcription_calls"] = len(self.transcriptions)
            summary["transcription_seconds"] = round(
                sum(t.duration_s for t in self.transcriptions), 1
            )
            summary["estimated_transcription_cost"] = f"${self.total_transcription_cost:.4f}"
            summary["transcription_outcomes"] = {
                outcome: sum(1 for row in self.transcriptions if row.outcome == outcome)
                for outcome in sorted({row.outcome for row in self.transcriptions})
            }
        return summary


def save_run_log(
    log_dir: Path,
    command: str,
    tracker: CostTracker,
    estimated_cost: float | None = None,
    full_videos: int = 0,
    shorts: int = 0,
    elapsed_seconds: float = 0,
    metadata: dict[str, Any] | None = None,
    preview: bool = False,
):
    """Append a run cost entry to the cost log for estimate calibration.

    The log is written to ``<log_dir>/.distill/cost_log.jsonl`` (the ops_dir).
    If a ``cost_log.jsonl`` exists at the old location (``<log_dir>/cost_log.jsonl``),
    it is migrated into ``.distill/`` on first run.

    When ``preview=True``, the recorded ``command`` field is suffixed with
    ``_preview`` so iterative preview spend is visible separately from ingest
    spend in ``cost_log.jsonl``.
    """
    ops_dir = log_dir / ".distill"
    ops_dir.mkdir(parents=True, exist_ok=True)

    # Migration helper: move legacy root-level cost_log.jsonl into .distill/
    old_log = log_dir / "cost_log.jsonl"
    new_log = ops_dir / "cost_log.jsonl"
    if old_log.exists() and not new_log.exists():
        shutil.move(str(old_log), str(new_log))
        # stderr, not stdout: this one-time notice must never land in a
        # command's --json stdout (it would corrupt the envelope).
        from distill._console import err_console

        err_console.print("Migrated cost_log.jsonl to .distill/ for cleaner library layout")

    log_file = new_log

    recorded_command = f"{command}_preview" if preview else command
    effective_elapsed = elapsed_seconds or current_run_elapsed_seconds()
    host_managed_calls = sum(1 for row in tracker.entries if row.provider_type == "host-managed")
    entry = {
        "timestamp": datetime.now().isoformat(),
        "run_id": tracker.run_id or current_run_id(),
        "command": recorded_command,
        "full_videos": full_videos,
        "shorts": shorts,
        "grok_calls": len(tracker.entries),
        "gemini_queries": tracker.gemini_queries,
        "gemini_query_outcomes": {
            outcome: tracker.gemini_query_outcomes.count(outcome)
            for outcome in sorted(set(tracker.gemini_query_outcomes))
        },
        "total_input_tokens": tracker.total_input_tokens,
        "total_output_tokens": tracker.total_output_tokens,
        "conservative_usage_calls": sum(
            1 for e in tracker.entries if e.usage_source == "conservative"
        ),
        "actual_cost": round(tracker.total_cost, 6),
        "estimated_cost": round(estimated_cost, 6) if estimated_cost is not None else None,
        "elapsed_seconds": round(effective_elapsed, 1),
        "metadata": metadata or {},
    }
    if host_managed_calls:
        entry["external_cost_status"] = "unavailable"
        entry["actual_cost_scope"] = "distill-direct-charges"
    has_profile_receipt = _stamp_profile_receipt(
        entry,
        tracker,
        receipt_id=_active_profile_receipt_id(),
        host_managed_calls=host_managed_calls,
    )

    by_type: dict[str, Any] = {}
    by_model: dict[str, Any] = {}
    by_provider: dict[str, Any] = {}
    by_route_class: dict[str, Any] = {}
    for e in tracker.entries:
        ct = e.call_type or "unknown"
        if ct not in by_type:
            by_type[ct] = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
        by_type[ct]["calls"] += 1
        by_type[ct]["input_tokens"] += e.prompt_tokens
        by_type[ct]["output_tokens"] += e.completion_tokens

        model_key = e.model or "unknown"
        if model_key not in by_model:
            by_model[model_key] = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
        by_model[model_key]["calls"] += 1
        by_model[model_key]["input_tokens"] += e.prompt_tokens
        by_model[model_key]["output_tokens"] += e.completion_tokens

        provider_key = _provider_key(e)
        if provider_key not in by_provider:
            by_provider[provider_key] = {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "provider_name": e.provider_name,
                "provider_type": e.provider_type,
                "no_metered_cost": e.no_metered_cost,
            }
        by_provider[provider_key]["calls"] += 1
        by_provider[provider_key]["input_tokens"] += e.prompt_tokens
        by_provider[provider_key]["output_tokens"] += e.completion_tokens

        route_class = _route_class(e)
        if route_class not in by_route_class:
            by_route_class[route_class] = {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
            }
        by_route_class[route_class]["calls"] += 1
        by_route_class[route_class]["input_tokens"] += e.prompt_tokens
        by_route_class[route_class]["output_tokens"] += e.completion_tokens
    entry["by_call_type"] = by_type
    entry["by_model"] = by_model
    entry["by_provider"] = by_provider
    entry["by_route_class"] = by_route_class
    entry["usage_ledger"] = {
        "llm_calls": len(tracker.entries),
        "metered_llm_calls": sum(
            1
            for e in tracker.entries
            if not e.no_metered_cost and e.provider_type != "host-managed"
        ),
        "no_metered_llm_calls": sum(1 for e in tracker.entries if e.no_metered_cost),
        "host_managed_llm_calls": host_managed_calls,
        "conservative_usage_calls": sum(
            1 for e in tracker.entries if e.usage_source == "conservative"
        ),
        "gemini_queries": tracker.gemini_queries,
        "gemini_query_outcomes": {
            outcome: tracker.gemini_query_outcomes.count(outcome)
            for outcome in sorted(set(tracker.gemini_query_outcomes))
        },
        "transcription_calls": len(tracker.transcriptions),
        "metered_transcription_calls": sum(1 for t in tracker.transcriptions if t.cost > 0),
        "no_metered_transcription_calls": sum(1 for t in tracker.transcriptions if t.cost == 0),
    }

    with log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    if has_profile_receipt:
        mark_profile_receipt_written()


def _stamp_profile_receipt(
    entry: dict[str, Any],
    tracker: CostTracker,
    *,
    receipt_id: str,
    host_managed_calls: int,
) -> bool:
    if not _PROFILE_RECEIPT_RE.fullmatch(receipt_id):
        return False
    entry["profile_receipt_id"] = receipt_id
    if host_managed_calls:
        entry["profile_receipt_status"] = "unverified-host-managed"
        return True
    if not math.isfinite(tracker.total_cost) or tracker.total_cost < 0:
        return False
    entry["profile_receipt_cost_usd"] = tracker.total_cost
    entry["profile_receipt_tracker_id"] = tracker.profile_tracker_id
    return True


def ensure_terminal_profile_receipt() -> None:
    """Append a zero-cost receipt when a successful profile child wrote none."""

    context = current_run()
    if (
        not _PROFILE_RECEIPT_RE.fullmatch(_active_profile_receipt_id())
        or context is None
        or context.profile_receipt_written
    ):
        return
    if context.ops_dir is None:
        raise RuntimeError("profile child could not resolve its cost-ledger directory")
    save_run_log(
        context.ops_dir.parent,
        context.command or "profile-child",
        CostTracker(),
        metadata={"profile_terminal_receipt": "zero_usage"},
    )


def _active_profile_receipt_id() -> str:
    return os.environ.get(PROFILE_RECEIPT_ENV, "").strip().lower()


def _provider_key(entry: TokenUsage) -> str:
    return entry.provider_name or entry.provider_type or "unknown"


def _route_class(entry: TokenUsage) -> str:
    if entry.provider_type == "local":
        return "local"
    if entry.provider_type == "included-plan":
        return "included-plan"
    if entry.provider_type == "host-managed":
        return "host-managed"
    if entry.no_metered_cost:
        return "no-metered"
    return "metered"
