"""Cost tracking for API calls.

Run-level cost aggregation (CostTracker, TokenUsage, save_run_log,
estimate_run_cost).  Per-model pricing is delegated to the unified cost
registry in ``distill.llm.cost`` — this module no longer owns pricing data.
"""

# pyright: strict

from __future__ import annotations

import json
import math
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from distill.llm.cost import (
    DEFAULT_MODEL,
    compute_cost,
    deep_research_query_cost,
    get_pricing,
    transcription_cost,
)
from distill.llm.cost import (
    PRICING as LLM_PRICING,
)
from distill.llm.cost_policy import classify_provider, evaluate_route_cost_policy
from distill.llm.run_context import current_run_elapsed_seconds, current_run_id
from distill.pipeline.cost_history import estimator_accuracy, projected_next_run_cost
from distill.pipeline.cost_warnings import CostWarning, cost_anomaly_warnings

if TYPE_CHECKING:
    from distill.llm.router import RouterConfig

ACCORDION_GROK_ESTIMATE: float = 0.05
NO_METERED_PROVIDERS: frozenset[str] = frozenset({"ollama", "lmstudio", "agent"})
NO_METERED_PROVIDER_TYPES: frozenset[str] = frozenset({"local", "included-plan"})

__all__ = [
    "ACCORDION_GROK_ESTIMATE",
    "LLM_PRICING",
    "BudgetExceededError",
    "CostCalibration",
    "CostEstimate",
    "CostTracker",
    "CostWarning",
    "ProjectedBudgetExceededError",
    "TokenUsage",
    "TranscriptionUsage",
    "cost_anomaly_warnings",
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

# Representative (input, output) token volumes for one ingested unit of each
# pipeline stage. Cold-start cost estimates are DERIVED from these against the
# current default model's pricing (``estimate_stage_cost``) rather than hard-coded
# in dollars, so they track the model. This closes the class of bug where the
# estimates stayed at the retired grok-4-1-fast rate (~$0.006/video) after the
# default moved to grok-4.3 (~$0.03/video), silently under-projecting budgets.
# Once a topic accrues history, ``load_cost_calibration`` overrides these with
# the real measured rates; until then these are the model-accurate fallback.
_STAGE_TOKENS: dict[str, tuple[int, int]] = {
    "video_full": (13_000, 6_000),  # 2-pass analysis
    "video_short": (800, 500),  # 1-pass Short
    "video_scan": (1_500, 800),  # lightweight triage
    "paper": (20_000, 3_000),  # full-PDF analysis
    "site_page": (12_000, 3_000),  # page analysis
    "synthesis": (20_000, 4_000),  # channel/topic synthesis
    "claim_extraction": (4_000, 2_000),  # one structured pass over an insight
}

_ASK_PROMPT_OVERHEAD_CHARS: int = 1_200
_ASK_OUTPUT_TOKENS: int = 2_000
_CHARS_PER_TOKEN_ESTIMATE: int = 4


def estimate_stage_cost(stage: str, *, model: str = "") -> float:
    """USD estimate for one ingested unit of ``stage`` at the default model's pricing.

    Derives from ``_STAGE_TOKENS`` and the unified pricing registry so the
    estimate always reflects the model actually in use (``DEFAULT_MODEL`` unless
    overridden), instead of a stale hard-coded rate.
    """
    tin, tout = _STAGE_TOKENS[stage]
    return compute_cost(model or DEFAULT_MODEL, tin, tout)


def estimate_synthesis_workflow_cost(
    calls: int = 1,
    *,
    router_config: RouterConfig | None = None,
) -> float:
    """Projected USD cost for known synthesis calls before model execution."""
    if calls <= 0:
        return 0.0
    rate = (
        _routed_stage_cost("synthesis", "synthesis", router_config)
        if router_config is not None
        else estimate_stage_cost("synthesis")
    )
    return calls * rate


def estimate_paper_workflow_cost(
    paper_count: int,
    *,
    synthesis_calls: int = 0,
    router_config: RouterConfig | None = None,
    analysis_mode: Literal["unknown", "single", "multipass"] = "unknown",
) -> float:
    """Projected USD cost for paper analysis plus known paper-tail calls.

    Short papers use the ``site`` route, while chunked multipass papers use the
    ``analysis`` route. Before PDF extraction the mode is unknown, so routed
    estimates conservatively price the costlier eligible route. Paper-topic
    synthesis and its optional corpus tail use ``site``.
    """
    if router_config is None:
        paper_rate = estimate_stage_cost("paper")
    else:
        single_rate = _routed_stage_cost("paper", "site", router_config)
        multipass_rate = _routed_stage_cost("paper", "analysis", router_config)
        if analysis_mode == "single":
            paper_rate = single_rate
        elif analysis_mode == "multipass":
            paper_rate = multipass_rate
        else:
            paper_rate = max(single_rate, multipass_rate)
    paper_cost = max(0, paper_count) * paper_rate
    synthesis_rate = (
        _routed_stage_cost("synthesis", "site", router_config)
        if router_config is not None
        else estimate_stage_cost("synthesis")
    )
    synthesis_cost = max(0, synthesis_calls) * synthesis_rate
    return paper_cost + synthesis_cost


def estimate_ask_workflow_cost(
    source_chars: int,
    *,
    question_chars: int = 0,
    model: str = "",
    router_config: RouterConfig | None = None,
) -> float:
    """Projected USD cost for one corpus ask call after source retrieval."""
    if source_chars <= 0:
        return 0.0
    prompt_chars = max(0, source_chars) + max(0, question_chars) + _ASK_PROMPT_OVERHEAD_CHARS
    input_tokens = max(1, math.ceil(prompt_chars / _CHARS_PER_TOKEN_ESTIMATE))
    if router_config is not None:
        return _routed_model_cost(
            "qa",
            router_config,
            lambda resolved_model: compute_cost(
                resolved_model,
                input_tokens,
                _ASK_OUTPUT_TOKENS,
            ),
        )
    return compute_cost(model or DEFAULT_MODEL, input_tokens, _ASK_OUTPUT_TOKENS)


def estimate_site_batch_workflow_cost(
    page_count: int,
    *,
    synthesis_calls: int = 0,
    include_report: bool = False,
    router_config: RouterConfig | None = None,
) -> float:
    """Projected USD upper bound for site pages and site-routed synthesis calls."""
    page_rate = (
        _routed_stage_cost("site_page", "site", router_config)
        if router_config is not None
        else estimate_stage_cost("site_page")
    )
    page_cost = max(0, page_count) * page_rate
    synthesis_rate = (
        _routed_stage_cost("synthesis", "site", router_config)
        if router_config is not None
        else estimate_stage_cost("synthesis")
    )
    synthesis_cost = max(0, synthesis_calls) * synthesis_rate
    report_cost = report_deep_research_estimate() if include_report else 0.0
    return page_cost + synthesis_cost + report_cost


def estimate_video_workflow_cost(
    full_videos: int = 0,
    shorts: int = 0,
    *,
    scan_videos: int = 0,
    include_report: bool = False,
    synthesis_calls: int = 0,
) -> float:
    """Projected USD cost for video-oriented CLI workflows before model calls."""
    grok_cost = (
        full_videos * estimate_stage_cost("video_full")
        + shorts * estimate_stage_cost("video_short")
        + scan_videos * estimate_stage_cost("video_scan")
    )
    synthesis_cost = estimate_synthesis_workflow_cost(synthesis_calls)
    gemini_cost = deep_research_query_cost() if include_report else 0.0
    accordion_grok = ACCORDION_GROK_ESTIMATE if include_report else 0.0
    return grok_cost + synthesis_cost + gemini_cost + accordion_grok


def _routed_stage_cost(
    stage: str,
    workload: str,
    router_config: RouterConfig,
) -> float:
    """Price one stage against its resolved primary and usable fallback routes."""
    return _routed_model_cost(
        workload,
        router_config,
        lambda model: estimate_stage_cost(stage, model=model),
    )


def _routed_model_cost(
    workload: str,
    router_config: RouterConfig,
    cost_for_model: Callable[[str], float],
) -> float:
    """Price one call against its resolved primary and usable fallback routes."""
    provider, model = router_config.resolve(workload)
    primary_cost = 0.0 if classify_provider(provider) == "local" else cost_for_model(model)

    fallback_provider = router_config.fallback_provider.strip()
    fallback_model = router_config.fallback_model.strip()
    if (
        not fallback_provider
        or not fallback_model
        or fallback_provider == provider
        or not evaluate_route_cost_policy(
            cost_mode=router_config.cost_mode,
            provider=fallback_provider,
            workload=workload,
        ).allowed
    ):
        return primary_cost

    fallback_cost = (
        0.0 if classify_provider(fallback_provider) == "local" else cost_for_model(fallback_model)
    )
    # Only one route completes. Use the costlier eligible route so a local
    # primary with an opt-in metered fallback is never advertised as free.
    return max(primary_cost, fallback_cost)


def estimate_routed_video_workflow_cost(
    full_videos: int = 0,
    shorts: int = 0,
    *,
    scan_videos: int = 0,
    include_report: bool = False,
    synthesis_calls: int = 0,
    claim_extraction_calls: int = 0,
    router_config: RouterConfig | None = None,
) -> float:
    """Project a video workflow using the routes that will execute each stage.

    Local Ollama and LM Studio stages have no incremental model charge. Cloud,
    unknown, and eligible fallback routes retain registry-backed estimates.
    Gemini Deep Research remains explicitly metered even when analysis is local.
    """
    if router_config is None:
        from distill.llm.router import RouterConfig

        router_config = RouterConfig()

    analysis_cost = (
        max(0, full_videos) * _routed_stage_cost("video_full", "analysis", router_config)
        + max(0, shorts) * _routed_stage_cost("video_short", "analysis", router_config)
        + max(0, scan_videos) * _routed_stage_cost("video_scan", "analysis", router_config)
    )
    synthesis_cost = max(0, synthesis_calls) * _routed_stage_cost(
        "synthesis", "synthesis", router_config
    )
    claim_extraction_cost = max(0, claim_extraction_calls) * _routed_stage_cost(
        "claim_extraction", "concepts", router_config
    )
    if not include_report:
        return analysis_cost + synthesis_cost + claim_extraction_cost

    deep_research_cost = deep_research_query_cost()
    accordion_cost = _routed_stage_cost("synthesis", "accordion", router_config)
    # Preserve the established cloud accordion estimate rather than replacing
    # it with a potentially smaller token projection. Local accordion work is
    # free by topology; metered work keeps the conservative historical amount.
    if accordion_cost > 0:
        accordion_cost = max(accordion_cost, ACCORDION_GROK_ESTIMATE)
    return (
        analysis_cost + synthesis_cost + claim_extraction_cost + deep_research_cost + accordion_cost
    )


@dataclass
class TokenUsage:
    """Token usage from a single API call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    call_type: str = ""
    provider_name: str = ""
    provider_type: str = ""

    @classmethod
    def from_response(cls, response: Any, *, call_type: str = "") -> TokenUsage:
        """Build a usage row from an LLM router response."""
        return cls(
            prompt_tokens=response.input_tokens,
            completion_tokens=response.output_tokens,
            model=response.model,
            call_type=call_type,
            provider_name=getattr(response, "provider_name", ""),
            provider_type=getattr(response, "provider_type", ""),
        )

    @property
    def no_metered_cost(self) -> bool:
        """True when the call came from a local or deferred no-metered provider."""
        return (
            self.provider_type in NO_METERED_PROVIDER_TYPES
            or self.provider_name in NO_METERED_PROVIDERS
        )


@dataclass
class TranscriptionUsage:
    """One cloud speech-to-text call's audio duration and estimated cost."""

    provider: str = ""
    model: str = ""
    duration_s: float = 0.0
    cost: float = 0.0


class BudgetExceededError(Exception):
    """A run's recorded spend crossed its budget ceiling.

    Raised *after* the crossing call is recorded -- its spend already happened
    and must stay on the ledger (no off-ledger spend, ever). Callers catch
    this to stop cleanly: artifacts written so far are durable and verify-
    gated, and convergent re-runs pick up where the run stopped.
    """

    def __init__(self, spent: float, budget: float):
        self.spent = spent
        self.budget = budget
        cap = f"${budget:.4f}" if budget < 0.01 else f"${budget:.2f}"
        super().__init__(f"spend ${spent:.4f} exceeded the {cap} budget")


class ProjectedBudgetExceededError(BudgetExceededError):
    """A credible pre-run estimate exceeds the configured workflow budget."""

    def __init__(self, projected: float, budget: float):
        self.spent = projected
        self.projected = projected
        self.budget = budget
        cap = f"${budget:.4f}" if budget < 0.01 else f"${budget:.2f}"
        Exception.__init__(
            self,
            f"projected spend ${projected:.4f} exceeds the {cap} budget before the run starts",
        )


@dataclass
class CostTracker:
    """Accumulates token usage and cost across a run.

    With ``budget`` set, every record raises :class:`BudgetExceededError` once
    total recorded cost crosses it. Enforcement is on *actual* recorded spend,
    not an estimate -- the call that crosses completes and is recorded, then
    the run stops; the overshoot is bounded by one call.
    """

    entries: list[TokenUsage] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] "dataclass default_factory appears as list[Unknown] under strict; usage throughout confirms TokenUsage"
    gemini_queries: int = 0
    gemini_query_models: list[str] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] "dataclass default_factory appears as list[Unknown] under strict; usage confirms list[str]"
    transcriptions: list[TranscriptionUsage] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] "dataclass default_factory appears as list[Unknown] under strict; usage confirms TranscriptionUsage"
    budget: float | None = None
    run_id: str = field(default_factory=current_run_id)

    def _check_budget(self):
        if self.budget is not None and self.total_cost > self.budget:
            raise BudgetExceededError(self.total_cost, self.budget)

    def record(self, usage: TokenUsage):
        """Record a token usage entry."""
        self.entries.append(usage)
        self._check_budget()

    def record_gemini_query(self, model: str = ""):
        """Record a Gemini Deep Research query (model-aware for per-query cost)."""
        self.gemini_queries += 1
        self.gemini_query_models.append(model)
        self._check_budget()

    def record_transcription(self, provider: str, duration_s: float, *, model: str = ""):
        """Record a cloud transcription call's audio duration and estimated cost.

        Local transcription (faster-whisper) is free; recording it is harmless
        (cost resolves to 0) and keeps the ledger complete.
        """
        self.transcriptions.append(
            TranscriptionUsage(
                provider=provider,
                model=model,
                duration_s=duration_s,
                cost=transcription_cost(provider, duration_s),
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
        total = 0.0
        for entry in self.entries:
            if entry.no_metered_cost:
                continue
            rates = get_pricing(entry.model)
            total += entry.prompt_tokens * rates.get("input", 0.0) / 1_000_000
            total += entry.completion_tokens * rates.get("output", 0.0) / 1_000_000
        return total

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
            "metered_calls": sum(1 for e in self.entries if not e.no_metered_cost),
            "no_metered_calls": sum(1 for e in self.entries if e.no_metered_cost),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "estimated_grok_cost": f"${self.total_grok_cost:.4f}",
            "estimated_gemini_cost": f"${self.total_gemini_cost:.2f}",
            "estimated_total_cost": self.format_cost(),
            "by_model": by_model,
            "by_provider": by_provider,
        }
        if self.transcriptions:
            summary["transcription_calls"] = len(self.transcriptions)
            summary["transcription_seconds"] = round(
                sum(t.duration_s for t in self.transcriptions), 1
            )
            summary["estimated_transcription_cost"] = f"${self.total_transcription_cost:.4f}"
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
    entry = {
        "timestamp": datetime.now().isoformat(),
        "run_id": tracker.run_id or current_run_id(),
        "command": recorded_command,
        "full_videos": full_videos,
        "shorts": shorts,
        "grok_calls": len(tracker.entries),
        "gemini_queries": tracker.gemini_queries,
        "total_input_tokens": tracker.total_input_tokens,
        "total_output_tokens": tracker.total_output_tokens,
        "actual_cost": round(tracker.total_cost, 6),
        "estimated_cost": round(estimated_cost, 6) if estimated_cost is not None else None,
        "elapsed_seconds": round(effective_elapsed, 1),
        "metadata": metadata or {},
    }

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
        "metered_llm_calls": sum(1 for e in tracker.entries if not e.no_metered_cost),
        "no_metered_llm_calls": sum(1 for e in tracker.entries if e.no_metered_cost),
        "gemini_queries": tracker.gemini_queries,
        "transcription_calls": len(tracker.transcriptions),
        "metered_transcription_calls": sum(1 for t in tracker.transcriptions if t.cost > 0),
        "no_metered_transcription_calls": sum(1 for t in tracker.transcriptions if t.cost == 0),
    }

    with log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _provider_key(entry: TokenUsage) -> str:
    return entry.provider_name or entry.provider_type or "unknown"


def _route_class(entry: TokenUsage) -> str:
    if entry.provider_type == "local":
        return "local"
    if entry.provider_type == "included-plan":
        return "included-plan"
    if entry.no_metered_cost:
        return "no-metered"
    return "metered"


def estimate_run_cost(
    full_videos: int,
    shorts: int,
    accordion: bool = False,
    *,
    router_config: RouterConfig | None = None,
) -> str:
    """Pre-run cost estimate for dry-run output.

    The default remains a stable cloud-baseline calculation for pure estimator
    callers. CLI dry runs pass their active router configuration so local and
    mixed-route output matches what the workflow can actually spend.
    """
    full_rate = (
        _routed_stage_cost("video_full", "analysis", router_config)
        if router_config is not None
        else estimate_stage_cost("video_full")
    )
    short_rate = (
        _routed_stage_cost("video_short", "analysis", router_config)
        if router_config is not None
        else estimate_stage_cost("video_short")
    )
    grok_cost = full_videos * full_rate + shorts * short_rate
    gemini_cost = deep_research_query_cost() if accordion else 0.0
    accordion_generation = 0.0
    if accordion:
        if router_config is None:
            accordion_generation = ACCORDION_GROK_ESTIMATE
        else:
            routed_accordion = _routed_stage_cost("synthesis", "accordion", router_config)
            if routed_accordion > 0:
                accordion_generation = max(routed_accordion, ACCORDION_GROK_ESTIMATE)
    total = grok_cost + gemini_cost + accordion_generation

    parts: list[str] = []
    if full_videos:
        parts.append(
            f"{full_videos} full videos x ${full_rate:.3f} = ${full_videos * full_rate:.2f}"
        )
    if shorts:
        parts.append(f"{shorts} Shorts x ${short_rate:.4f} = ${shorts * short_rate:.3f}")
    if accordion:
        parts.append(
            f"Accordion: ~${report_deep_research_estimate():.2f} "
            f"(Gemini ${gemini_cost:.2f} + generation ${accordion_generation:.2f})"
        )

    return f"Estimated cost: ${total:.2f} ({'; '.join(parts)})"


# Per-source analysis-cost defaults (USD), derived from the current default
# model's pricing and representative per-stage token volumes (``_STAGE_TOKENS``);
# transcription is assumed local (free) for the preview estimate. These are the
# cold-start fallback used until enough history accrues for
# ``load_cost_calibration`` to derive real per-unit rates from cost_log.jsonl.
_DISCOVER_PAPER_COST: float = estimate_stage_cost("paper")  # full-PDF analysis
_DISCOVER_SITE_COST: float = estimate_stage_cost("site_page")  # page analysis
_DISCOVER_VIDEO_COST: float = estimate_stage_cost("video_full")  # transcript analysis

# Assumed historical-average video length the calibrated per-video rate is
# anchored to; a candidate's real duration scales linearly around this.
_NOMINAL_VIDEO_SECONDS: float = 900.0  # 15 minutes
# How far a single video's duration is allowed to move the per-video estimate.
_VIDEO_FACTOR_FLOOR: float = 0.3
_VIDEO_FACTOR_CEIL: float = 4.0
# Minimum clean single-source runs before a calibrated rate replaces the default.
_CALIBRATION_MIN_SAMPLES: int = 3
# Call-type markers used to tell what a logged run actually analyzed.
_VIDEO_CALL_TYPES: frozenset[str] = frozenset({"pass1", "pass2", "short", "scan"})


@dataclass(frozen=True)
class CostCalibration:
    """Per-source-type USD rates derived from historical run logs.

    Each rate is the average whole-run cost attributable to one ingested item of
    that type (analysis plus its share of synthesis), measured from *clean*
    single-source runs so cross-attribution does not skew it. When history is
    thin the corresponding default constant is used and ``samples`` records 0.
    """

    per_paper: float = _DISCOVER_PAPER_COST
    per_video: float = _DISCOVER_VIDEO_COST
    per_site: float = _DISCOVER_SITE_COST
    samples: dict[str, int] = field(default_factory=lambda: {"paper": 0, "video": 0, "site": 0})

    @property
    def any_calibrated(self) -> bool:
        """True if at least one rate came from real history rather than a default."""
        return any(v > 0 for v in self.samples.values())


@dataclass(frozen=True)
class CostEstimate:
    """A pre-run spend estimate with an honest uncertainty range."""

    expected: float
    low: float
    high: float
    calibrated: bool

    def format(self) -> str:
        """Compact human-readable estimate, e.g. ``~$0.42 (est; $0.29-$0.63)``."""
        return f"~${self.expected:.2f} (est; ${self.low:.2f}-${self.high:.2f})"


def _cost_log_path(log_dir: Path) -> Path:
    """Resolve the cost-log path, preferring the ``.distill/`` ops dir.

    Mirrors :func:`save_run_log`'s location logic, read-only: the current log
    lives under ``.distill/`` but a legacy root-level log may still exist.
    """
    new_log = log_dir / ".distill" / "cost_log.jsonl"
    if new_log.exists():
        return new_log
    return log_dir / "cost_log.jsonl"


def _classify_clean_run(row: dict[str, Any]) -> tuple[str, float, int] | None:
    """Map a run-log row to ``(source_kind, cost, item_count)`` if it's usable.

    Returns ``None`` unless the row is a *clean* single-source run with a real
    cost and item count — preview rows and mixed runs (which would
    cross-contaminate a per-source rate) are rejected here.
    """
    if str(row.get("command", "")).endswith("_preview"):
        return None
    cost = row.get("actual_cost") or 0.0
    if cost <= 0:
        return None
    by_type: dict[str, Any] = cast(dict[str, Any], row.get("by_call_type") or {})
    has_paper = "paper" in by_type
    has_site = "site_page" in by_type
    has_video = any(ct in by_type for ct in _VIDEO_CALL_TYPES)
    if has_paper and not has_site and not has_video:
        n = int(by_type.get("paper", {}).get("calls", 0))
        return ("paper", cost, n) if n else None
    # The per-video rate calibrates only on pure full-analysis video runs. A
    # scan/short pass is ~8x cheaper than a full 2-pass analysis, and Shorts add
    # cost to the numerator without entering the full_videos denominator -- so a
    # scan-only or mixed run would skew the calibrated rate (badly under- or
    # over-projecting real ingests). Exclude them; the cold-start default
    # (video_full) already carries the right number until clean runs accrue.
    has_full_video = "pass1" in by_type or "pass2" in by_type
    has_scan_or_short = (
        "scan" in by_type or "short" in by_type or int(row.get("shorts", 0) or 0) > 0
    )
    if has_full_video and not has_paper and not has_site and not has_scan_or_short:
        n = int(row.get("full_videos", 0)) or int(by_type.get("pass1", {}).get("calls", 0))
        return ("video", cost, n) if n else None
    if has_site and not has_paper and not has_video:
        n = int(by_type.get("site_page", {}).get("calls", 0))
        return ("site", cost, n) if n else None
    return None


def load_cost_calibration(
    log_dir: Path, *, min_samples: int = _CALIBRATION_MIN_SAMPLES
) -> CostCalibration:
    """Derive per-source USD rates from historical runs in ``cost_log.jsonl``.

    Only *clean* single-source runs feed each rate (a paper-only run prices
    papers, a video-only run prices videos, a site-only run prices sites), so a
    mixed ``discover`` run never cross-contaminates a rate. A source type with
    fewer than ``min_samples`` ingested items keeps its default constant.
    """
    log_file = _cost_log_path(log_dir)
    if not log_file.exists():
        return CostCalibration()
    try:
        lines = log_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return CostCalibration()

    cost = {"paper": 0.0, "video": 0.0, "site": 0.0}
    count = {"paper": 0, "video": 0, "site": 0}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        # A JSON-valid but schema-invalid row (string ``actual_cost``, non-dict
        # ``by_call_type``, non-numeric ``calls``) would otherwise raise
        # TypeError/ValueError/AttributeError out of the classifier and abort
        # every discover estimate. Skip the bad row like a syntactically-invalid
        # one -- the cost log is best-effort calibration, not a hard input.
        if not isinstance(row, dict):
            continue
        try:
            classified = _classify_clean_run(cast(dict[str, Any], row))
        except (TypeError, ValueError, AttributeError):
            continue
        if classified is None:
            continue
        kind, run_cost, n = classified
        cost[kind] += run_cost
        count[kind] += n

    defaults = {
        "paper": _DISCOVER_PAPER_COST,
        "video": _DISCOVER_VIDEO_COST,
        "site": _DISCOVER_SITE_COST,
    }
    rate = {k: (cost[k] / count[k]) if count[k] >= min_samples else defaults[k] for k in defaults}
    samples = {k: (count[k] if count[k] >= min_samples else 0) for k in defaults}
    return CostCalibration(
        per_paper=rate["paper"],
        per_video=rate["video"],
        per_site=rate["site"],
        samples=samples,
    )


def _video_duration_factor(seconds: float | None) -> float:
    """Scale a video's cost by its length around the nominal average.

    Transcript-analysis cost tracks roughly linearly with runtime, so a 30-min
    talk costs about twice a 15-min one. Unknown/zero duration assumes nominal.
    """
    if not seconds or seconds <= 0:
        return 1.0
    return max(_VIDEO_FACTOR_FLOOR, min(_VIDEO_FACTOR_CEIL, seconds / _NOMINAL_VIDEO_SECONDS))


def _routed_discover_calibration(
    calibration: CostCalibration,
    router_config: RouterConfig,
) -> CostCalibration:
    """Adapt discover rates to active routes without discarding useful history."""
    route_rates = {
        "paper": max(
            _routed_stage_cost("paper", "site", router_config),
            _routed_stage_cost("paper", "analysis", router_config),
        ),
        "video": _routed_stage_cost("video_full", "analysis", router_config),
        "site": _routed_stage_cost("site_page", "site", router_config),
    }
    historical_rates = {
        "paper": calibration.per_paper,
        "video": calibration.per_video,
        "site": calibration.per_site,
    }
    rates: dict[str, float] = {}
    samples: dict[str, int] = {}
    for kind, route_rate in route_rates.items():
        sample_count = calibration.samples.get(kind, 0)
        if route_rate <= 0:
            rates[kind] = 0.0
            samples[kind] = 0
        elif sample_count > 0:
            rates[kind] = historical_rates[kind]
            samples[kind] = sample_count
        else:
            rates[kind] = route_rate
            samples[kind] = 0
    return CostCalibration(
        per_paper=rates["paper"],
        per_video=rates["video"],
        per_site=rates["site"],
        samples=samples,
    )


def estimate_discover_cost(
    papers: int = 0,
    videos: int = 0,
    sites: int = 0,
    *,
    calibration: CostCalibration | None = None,
    router_config: RouterConfig | None = None,
) -> float:
    """Rough pre-run USD point estimate for a discover ingest set (counts only).

    Count-based per-source-type estimate, no extra network fetches. Uses
    calibrated per-unit rates when ``calibration`` is supplied, else the default
    constants (identical to the historical behavior). For the metadata-aware
    estimate with an uncertainty range, use :func:`estimate_discover_items`.
    """
    cal = calibration or CostCalibration()
    if router_config is not None:
        cal = _routed_discover_calibration(cal, router_config)
    return (
        max(0, papers) * cal.per_paper
        + max(0, sites) * cal.per_site
        + max(0, videos) * cal.per_video
    )


def estimate_discover_items(
    *,
    papers: int = 0,
    video_durations: Sequence[float | None] = (),
    sites: int = 0,
    calibration: CostCalibration | None = None,
    router_config: RouterConfig | None = None,
) -> CostEstimate:
    """Metadata-aware spend estimate with an uncertainty range.

    Reads the free metadata available at preview time -- per-video duration is
    the strongest signal and scales each video's share around the nominal
    average. Paper PDF page count is *not* fetched at discovery (it would need a
    network call), so papers use the flat calibrated per-paper rate; sites
    likewise use the per-site rate. The returned range is asymmetric (overruns
    are more common than underruns) and widens when no calibration is available.
    """
    cal = calibration or CostCalibration()
    if router_config is not None:
        cal = _routed_discover_calibration(cal, router_config)
    expected = max(0, papers) * cal.per_paper + max(0, sites) * cal.per_site
    expected += sum(cal.per_video * _video_duration_factor(d) for d in video_durations)

    calibrated = cal.any_calibrated
    low_mult, high_mult = (0.7, 1.5) if calibrated else (0.5, 2.0)
    return CostEstimate(
        expected=expected,
        low=expected * low_mult,
        high=expected * high_mult,
        calibrated=calibrated,
    )


def report_deep_research_estimate(*, include_section_writing: bool = True) -> float:
    """Estimate a report run that submits one Gemini Deep Research job."""
    total = deep_research_query_cost()
    if include_section_writing:
        total += ACCORDION_GROK_ESTIMATE
    return total
