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
import threading
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from distill.jsonl import append_jsonl_line_locked, jsonl_append_lock
from distill.llm.cost import (
    PRICING as LLM_PRICING,
)
from distill.llm.cost import (
    compute_cost,
    deep_research_authorization_cost,
    deep_research_query_cost,
    has_known_transcription_pricing,
    normalize_transcription_duration,
    transcription_cost,
)
from distill.llm.cost_policy import CostPolicyError
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
    CORPUS_REPORT_ESTIMATE,
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
    report_profile_estimate,
)
from distill.pipeline.cost_history import estimator_accuracy, projected_next_run_cost
from distill.pipeline.cost_warnings import CostWarning, cost_anomaly_warnings
from distill.pipeline.usage_records import (
    TokenUsage,
    TranscriptionUsage,
)

__all__ = [
    "ACCORDION_GROK_ESTIMATE",
    "CORPUS_REPORT_ESTIMATE",
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
    "report_profile_estimate",
    "save_run_log",
]

PROFILE_RECEIPT_ENV = "DISTILL_PROFILE_RECEIPT_ID"
_PROFILE_RECEIPT_RE = re.compile(r"[0-9a-f]{64}")
_ACTIVE_BUDGET_RESERVATION: ContextVar[tuple[int, tuple[str, ...]] | None] = ContextVar(
    "distill_active_budget_reservation",
    default=None,
)


def _token_usage_cost(usage: TokenUsage) -> float:
    if usage.external_cost_unavailable:
        return 0.0
    if usage.no_metered_cost:
        return 0.0
    return compute_cost(usage.model, usage.prompt_tokens, usage.completion_tokens)


def _empty_attempt_id_set() -> set[str]:
    return set()


def _finite_nonnegative(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{label} must be a finite non-negative number")
    try:
        normalized = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite non-negative number") from exc
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{label} must be a finite non-negative number")
    return normalized


def _finite_cost_sum(values: list[float], *, label: str) -> float:
    try:
        total = math.fsum(values)
    except OverflowError as exc:
        raise ValueError(f"{label} exceeds the supported aggregate range") from exc
    if not math.isfinite(total) or total < 0:
        raise ValueError(f"{label} exceeds the supported aggregate range")
    return total


@dataclass
class CostTracker:
    """Accumulates token usage and cost across a run.

    With ``budget`` set, direct cloud attempts can be conservatively authorized
    and atomically reserved before provider construction. Every recorded row is
    still checked against the cap, fixed-price calls have dedicated admission,
    and ambiguous submissions remain conservatively visible in the ledger.
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
    _lock: Any = field(
        default_factory=threading.RLock,
        init=False,
        repr=False,
        compare=False,
    )
    _budget_reservations: dict[str, float] = field(
        default_factory=dict[str, float],
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self.budget is not None:
            self.budget = _finite_nonnegative(self.budget, label="cost budget")

    @property
    def profile_tracker_id(self) -> str:
        """Stable identity used to deduplicate cumulative profile receipts."""

        return self._profile_tracker_id

    @property
    def budget_limit(self) -> float | None:
        """Budget visible to router admission, including delegated trackers."""

        return self.budget

    def _check_budget(self):
        if self.budget is not None and self.total_cost > self.budget:
            raise BudgetExceededError(self.total_cost, self.budget)

    def _consume_active_reservation(self, actual_cost: float) -> None:
        active = _ACTIVE_BUDGET_RESERVATION.get()
        if active is None or active[0] != id(self) or actual_cost <= 0:
            return
        unallocated = actual_cost
        for reservation_id in active[1]:
            remaining = self._budget_reservations.get(reservation_id, 0.0)
            consumed = min(remaining, unallocated)
            self._budget_reservations[reservation_id] = remaining - consumed
            unallocated -= consumed
            if unallocated <= 0:
                break

    def _projected_total(self, increment: float) -> float:
        """Return an atomic projection including every in-flight reservation.

        The current worker's remaining reservation already covers the same
        amount of its next provider call, so only an excess above that amount
        is added. Reservations owned by other workers are always counted.
        Callers hold ``_lock`` while using this helper.
        """

        reserved = _finite_cost_sum(
            list(self._budget_reservations.values()),
            label="reserved cost",
        )
        active = _ACTIVE_BUDGET_RESERVATION.get()
        covered = 0.0
        if active is not None and active[0] == id(self):
            covered = min(
                increment,
                _finite_cost_sum(
                    [self._budget_reservations.get(key, 0.0) for key in active[1]],
                    label="active reserved cost",
                ),
            )
        return self.total_cost + reserved + max(increment - covered, 0.0)

    def record(self, usage: TokenUsage):
        """Record provider-accurate usage without duplicating streamed attempts."""
        with self._lock:
            added_cost = 0.0
            for entry in usage.expanded():
                if entry.attempt_id and entry.attempt_id in self._recorded_attempt_ids:
                    continue
                self.entries.append(entry)
                added_cost += _token_usage_cost(entry)
                if entry.attempt_id:
                    self._recorded_attempt_ids.add(entry.attempt_id)
            self._consume_active_reservation(added_cost)
            self._check_budget()

    def authorize_token_usage(self, usage: TokenUsage) -> None:
        """Refuse projected token spend before provider contact without recording it."""

        with self._lock:
            seen_attempt_ids = set(self._recorded_attempt_ids)
            projected_increment = 0.0
            for entry in usage.expanded():
                if entry.attempt_id and entry.attempt_id in seen_attempt_ids:
                    continue
                if entry.attempt_id:
                    seen_attempt_ids.add(entry.attempt_id)
                self._require_budget_price(entry)
                projected_increment += _token_usage_cost(entry)
            projected = self._projected_total(projected_increment)
            if self.budget is not None and projected > self.budget:
                raise ProjectedBudgetExceededError(projected, self.budget)

    def authorize_attempt(self, attempt: LLMUsageAttempt, *, call_type: str = "") -> None:
        """Refuse one conservatively bounded provider attempt before construction."""

        self.authorize_token_usage(TokenUsage(call_type=call_type, attempts=(attempt,)))

    @contextmanager
    def reserve_attempt(
        self,
        attempt: LLMUsageAttempt,
        *,
        call_type: str = "",
    ) -> Generator[None, None, None]:
        """Atomically reserve one bounded provider attempt until it is accounted."""

        usage = TokenUsage(call_type=call_type, attempts=(attempt,))
        entries = usage.expanded()
        with self._lock:
            for entry in entries:
                self._require_budget_price(entry)
            amount = _finite_cost_sum(
                [_token_usage_cost(entry) for entry in entries],
                label="projected attempt cost",
            )
        with self.reserve_budget(amount):
            yield

    def _require_budget_price(self, usage: TokenUsage) -> None:
        if self.budget is None or usage.no_metered_cost or not usage.external_cost_unavailable:
            return
        raise CostPolicyError(
            f"Budget cannot authorize model '{usage.model or '(unknown)'}' because "
            "Distill has no verified price for this metered route. Select a registered "
            "model or update the pricing registry before allowing spend."
        )

    @contextmanager
    def reserve_budget(self, projected_cost: float) -> Generator[None, None, None]:
        """Atomically reserve projected spend while one concurrent item runs.

        Reservations are not ledger entries and are always released. They stop
        concurrent workers from independently authorizing against the same
        remaining budget while provider-accurate usage is still in flight.
        """

        amount = _finite_nonnegative(projected_cost, label="projected reservation")
        active = _ACTIVE_BUDGET_RESERVATION.get()
        active_ids = active[1] if active is not None and active[0] == id(self) else ()
        reservation_id = secrets.token_hex(16)
        with self._lock:
            reserved = _finite_cost_sum(
                list(self._budget_reservations.values()),
                label="reserved cost",
            )
            active_reserved = _finite_cost_sum(
                [self._budget_reservations.get(key, 0.0) for key in active_ids],
                label="active reserved cost",
            )
            additional = max(amount - active_reserved, 0.0)
            projected = self.total_cost + reserved + additional
            if self.budget is not None and projected > self.budget:
                raise ProjectedBudgetExceededError(projected, self.budget)
            self._budget_reservations[reservation_id] = additional
        active_token = _ACTIVE_BUDGET_RESERVATION.set((id(self), (*active_ids, reservation_id)))
        try:
            yield
        finally:
            _ACTIVE_BUDGET_RESERVATION.reset(active_token)
            with self._lock:
                self._budget_reservations.pop(reservation_id, None)

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
        """Admit Deep Research against Google's upper typical-cost estimate."""

        with self._lock:
            projected = self._projected_total(deep_research_authorization_cost(model))
            if self.budget is not None and projected > self.budget:
                raise ProjectedBudgetExceededError(projected, self.budget)

    @contextmanager
    def reserve_gemini_query(self, model: str = "") -> Generator[None, None, None]:
        """Reserve Google's upper typical-cost estimate during submission."""

        with self.reserve_budget(deep_research_authorization_cost(model)):
            yield

    def record_gemini_query(self, model: str = "", *, outcome: str = "accepted") -> None:
        """Record an accepted or ambiguously submitted Deep Research query."""

        if outcome not in {"accepted", "ambiguous"}:
            raise ValueError(f"unsupported Gemini query outcome: {outcome}")
        with self._lock:
            self.gemini_queries += 1
            self.gemini_query_models.append(model)
            self.gemini_query_outcomes.append(outcome)
            self._consume_active_reservation(deep_research_query_cost(model))
            self._check_budget()

    def authorize_transcription(self, provider: str, duration_s: float, *, model: str = "") -> None:
        """Refuse a known-price transcription before provider contact."""

        del model
        duration = normalize_transcription_duration(duration_s)
        with self._lock:
            if self.budget is not None and not has_known_transcription_pricing(provider):
                raise CostPolicyError(
                    f"Budget cannot authorize transcription provider '{provider}' because "
                    "Distill has no verified duration price for it."
                )
            projected = self._projected_total(transcription_cost(provider, duration))
            if self.budget is not None and projected > self.budget:
                raise ProjectedBudgetExceededError(projected, self.budget)

    @contextmanager
    def reserve_transcription(
        self,
        provider: str,
        duration_s: float,
        *,
        model: str = "",
    ) -> Generator[None, None, None]:
        """Reserve one duration-priced cloud transcription attempt."""

        del model
        duration = normalize_transcription_duration(duration_s)
        if self.budget is not None and not has_known_transcription_pricing(provider):
            raise CostPolicyError(
                f"Budget cannot reserve transcription provider '{provider}' because "
                "Distill has no verified duration price for it."
            )
        with self.reserve_budget(transcription_cost(provider, duration)):
            yield

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
        with self._lock:
            self.transcriptions.append(
                TranscriptionUsage(
                    provider=provider,
                    model=model,
                    duration_s=duration,
                    cost=transcription_cost(provider, duration),
                    outcome=outcome,
                )
            )
            self._consume_active_reservation(transcription_cost(provider, duration))
            self._check_budget()

    @property
    def total_input_tokens(self) -> int:
        with self._lock:
            return sum(e.prompt_tokens for e in self.entries)

    @property
    def total_output_tokens(self) -> int:
        with self._lock:
            return sum(e.completion_tokens for e in self.entries)

    @property
    def total_grok_cost(self) -> float:
        """Estimated xAI cost based on token usage and the actual model used."""
        with self._lock:
            return _finite_cost_sum(
                [_token_usage_cost(entry) for entry in self.entries],
                label="token cost",
            )

    @property
    def total_gemini_cost(self) -> float:
        """Estimated Gemini Deep Research cost, per-query and model-aware.

        When the per-query models are known (the normal path) each query is
        priced by its model, so Deep Research Max (~$5) is counted at its higher
        rate. Falls back to the standard per-query estimate for count-only
        trackers (e.g. sub-range report copies that carry only ``gemini_queries``).
        """
        with self._lock:
            if self.gemini_query_models:
                return _finite_cost_sum(
                    [deep_research_query_cost(m) for m in self.gemini_query_models],
                    label="Gemini query cost",
                )
            return _finite_nonnegative(
                self.gemini_queries * deep_research_query_cost(),
                label="Gemini query cost",
            )

    @property
    def total_transcription_cost(self) -> float:
        """Estimated cloud speech-to-text cost across the run."""
        with self._lock:
            return _finite_cost_sum(
                [t.cost for t in self.transcriptions],
                label="transcription cost",
            )

    @property
    def total_cost(self) -> float:
        with self._lock:
            return _finite_cost_sum(
                [self.total_grok_cost, self.total_gemini_cost, self.total_transcription_cost],
                label="total cost",
            )

    def format_cost(self) -> str:
        """Human-readable cost string."""
        total = self.total_cost
        direct_cost = f"${total:.4f}" if total < 0.01 else f"${total:.2f}"
        with self._lock:
            if any(entry.external_cost_unavailable for entry in self.entries):
                return f"{direct_cost} direct; external cost unavailable"
        return direct_cost

    def concurrent_child(self) -> CostTracker:
        """Return a per-worker ledger view backed by this synchronized tracker.

        Analysis code sometimes needs the model history from its own item. The
        child retains that local history while delegating every usage row and
        authorization decision to the parent budget and run ledger.
        """

        return _ConcurrentCostTracker(self)

    def summary_dict(self) -> dict[str, Any]:
        """Summary for logging/display."""
        by_model: dict[str, dict[str, float | int]] = {}
        by_provider: dict[str, dict[str, Any]] = {}
        host_managed_calls = sum(
            1 for entry in self.entries if entry.provider_type == "host-managed"
        )
        unknown_external_cost_calls = sum(
            1
            for entry in self.entries
            if entry.external_cost_unavailable and entry.provider_type != "host-managed"
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
                1 for e in self.entries if not e.no_metered_cost and not e.external_cost_unavailable
            ),
            "no_metered_calls": sum(1 for e in self.entries if e.no_metered_cost),
            "host_managed_calls": host_managed_calls,
            "unknown_external_cost_calls": unknown_external_cost_calls,
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
        if host_managed_calls or unknown_external_cost_calls:
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


class _ConcurrentCostTracker(CostTracker):
    """Worker-local usage history that writes through to one parent tracker."""

    def __init__(self, parent: CostTracker) -> None:
        super().__init__(run_id=parent.run_id)
        self._parent = parent

    @property
    def budget_limit(self) -> float | None:
        return self._parent.budget_limit

    def record(self, usage: TokenUsage) -> None:
        super().record(usage)
        self._parent.record(usage)

    def authorize_token_usage(self, usage: TokenUsage) -> None:
        self._parent.authorize_token_usage(usage)

    def authorize_attempt(self, attempt: LLMUsageAttempt, *, call_type: str = "") -> None:
        self._parent.authorize_attempt(attempt, call_type=call_type)

    @contextmanager
    def reserve_attempt(
        self,
        attempt: LLMUsageAttempt,
        *,
        call_type: str = "",
    ) -> Generator[None, None, None]:
        with self._parent.reserve_attempt(attempt, call_type=call_type):
            yield

    def authorize_gemini_query(self, model: str = "") -> None:
        self._parent.authorize_gemini_query(model)

    @contextmanager
    def reserve_gemini_query(self, model: str = "") -> Generator[None, None, None]:
        with self._parent.reserve_gemini_query(model):
            yield

    def record_gemini_query(self, model: str = "", *, outcome: str = "accepted") -> None:
        super().record_gemini_query(model, outcome=outcome)
        self._parent.record_gemini_query(model, outcome=outcome)

    def authorize_transcription(self, provider: str, duration_s: float, *, model: str = "") -> None:
        self._parent.authorize_transcription(provider, duration_s, model=model)

    @contextmanager
    def reserve_transcription(
        self,
        provider: str,
        duration_s: float,
        *,
        model: str = "",
    ) -> Generator[None, None, None]:
        with self._parent.reserve_transcription(provider, duration_s, model=model):
            yield

    def record_transcription(
        self,
        provider: str,
        duration_s: float,
        *,
        model: str = "",
        outcome: str = "completed",
    ) -> None:
        super().record_transcription(provider, duration_s, model=model, outcome=outcome)
        self._parent.record_transcription(provider, duration_s, model=model, outcome=outcome)


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
    actual_cost = _finite_nonnegative(tracker.total_cost, label="actual cost")
    normalized_estimate = (
        _finite_nonnegative(estimated_cost, label="estimated cost")
        if estimated_cost is not None
        else None
    )
    effective_elapsed = _finite_nonnegative(
        elapsed_seconds or current_run_elapsed_seconds(),
        label="elapsed seconds",
    )

    ops_dir = log_dir / ".distill"
    ops_dir.mkdir(parents=True, exist_ok=True)

    # Migration and append share one lock below so concurrent first writers
    # cannot both enter the migration path.
    old_log = log_dir / "cost_log.jsonl"
    new_log = ops_dir / "cost_log.jsonl"
    log_file = new_log

    recorded_command = f"{command}_preview" if preview else command
    host_managed_calls = sum(1 for row in tracker.entries if row.provider_type == "host-managed")
    unknown_external_cost_calls = sum(
        1
        for row in tracker.entries
        if row.external_cost_unavailable and row.provider_type != "host-managed"
    )
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
        "actual_cost": round(actual_cost, 6),
        "estimated_cost": round(normalized_estimate, 6)
        if normalized_estimate is not None
        else None,
        "elapsed_seconds": round(effective_elapsed, 1),
        "metadata": metadata or {},
    }
    if host_managed_calls or unknown_external_cost_calls:
        entry["external_cost_status"] = "unavailable"
        entry["actual_cost_scope"] = "distill-direct-charges"
    has_profile_receipt = _stamp_profile_receipt(
        entry,
        tracker,
        receipt_id=_active_profile_receipt_id(),
        host_managed_calls=host_managed_calls,
        unknown_external_cost_calls=unknown_external_cost_calls,
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
            1 for e in tracker.entries if not e.no_metered_cost and not e.external_cost_unavailable
        ),
        "no_metered_llm_calls": sum(1 for e in tracker.entries if e.no_metered_cost),
        "host_managed_llm_calls": host_managed_calls,
        "unknown_external_cost_llm_calls": unknown_external_cost_calls,
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

    serialized = json.dumps(entry, allow_nan=False)
    migrated = False
    with jsonl_append_lock(log_file):
        if old_log.exists() and not new_log.exists():
            shutil.move(str(old_log), str(new_log))
            migrated = True
        append_jsonl_line_locked(log_file, serialized, durable=True)
    if has_profile_receipt:
        mark_profile_receipt_written()
    if migrated:
        # stderr, not stdout: this one-time notice must never land in a
        # command's --json stdout (it would corrupt the envelope).
        from distill._console import err_console

        err_console.print("Migrated cost_log.jsonl to .distill/ for cleaner library layout")


def _stamp_profile_receipt(
    entry: dict[str, Any],
    tracker: CostTracker,
    *,
    receipt_id: str,
    host_managed_calls: int,
    unknown_external_cost_calls: int,
) -> bool:
    if not _PROFILE_RECEIPT_RE.fullmatch(receipt_id):
        return False
    entry["profile_receipt_id"] = receipt_id
    if host_managed_calls:
        entry["profile_receipt_status"] = "unverified-host-managed"
        return True
    if unknown_external_cost_calls:
        entry["profile_receipt_status"] = "unverified-external-cost"
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
    if getattr(entry, "external_cost_unavailable", False):
        return "unknown-external"
    if entry.no_metered_cost:
        return "no-metered"
    return "metered"
