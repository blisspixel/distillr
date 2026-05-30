"""Cost tracking for API calls.

Run-level cost aggregation (CostTracker, TokenUsage, save_run_log,
estimate_run_cost).  Per-model pricing is delegated to the unified cost
registry in ``distill.llm.cost`` — this module no longer owns pricing data.
"""

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from distill.llm.cost import (
    PRICING as LLM_PRICING,
)
from distill.llm.cost import (
    deep_research_query_cost,
    get_pricing,
    transcription_cost,
)

ACCORDION_GROK_ESTIMATE: float = 0.05

__all__ = [
    "ACCORDION_GROK_ESTIMATE",
    "LLM_PRICING",
    "CostTracker",
    "TokenUsage",
    "TranscriptionUsage",
    "estimate_run_cost",
    "report_deep_research_estimate",
    "save_run_log",
]


@dataclass
class TokenUsage:
    """Token usage from a single API call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    call_type: str = ""


@dataclass
class TranscriptionUsage:
    """One cloud speech-to-text call's audio duration and estimated cost."""

    provider: str = ""
    model: str = ""
    duration_s: float = 0.0
    cost: float = 0.0


@dataclass
class CostTracker:
    """Accumulates token usage and cost across a run."""

    entries: list[TokenUsage] = field(default_factory=list)
    gemini_queries: int = 0
    gemini_query_models: list[str] = field(default_factory=list)
    transcriptions: list[TranscriptionUsage] = field(default_factory=list)

    def record(self, usage: TokenUsage):
        """Record a token usage entry."""
        self.entries.append(usage)

    def record_gemini_query(self, model: str = ""):
        """Record a Gemini Deep Research query (model-aware for per-query cost)."""
        self.gemini_queries += 1
        self.gemini_query_models.append(model)

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

    def summary_dict(self) -> dict:
        """Summary for logging/display."""
        by_model: dict[str, dict[str, float | int]] = {}
        for entry in self.entries:
            model_summary = by_model.setdefault(
                entry.model or "unknown",
                {"calls": 0, "input_tokens": 0, "output_tokens": 0},
            )
            model_summary["calls"] += 1
            model_summary["input_tokens"] += entry.prompt_tokens
            model_summary["output_tokens"] += entry.completion_tokens

        summary = {
            "grok_calls": len(self.entries),
            "gemini_queries": self.gemini_queries,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "estimated_grok_cost": f"${self.total_grok_cost:.4f}",
            "estimated_gemini_cost": f"${self.total_gemini_cost:.2f}",
            "estimated_total_cost": self.format_cost(),
            "by_model": by_model,
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
    tracker: "CostTracker",
    estimated_cost: float | None = None,
    full_videos: int = 0,
    shorts: int = 0,
    elapsed_seconds: float = 0,
    metadata: dict[str, str] | None = None,
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
        print("Migrated cost_log.jsonl to .distill/ for cleaner library layout")  # noqa: T201

    log_file = new_log

    recorded_command = f"{command}_preview" if preview else command
    entry = {
        "timestamp": datetime.now().isoformat(),
        "command": recorded_command,
        "full_videos": full_videos,
        "shorts": shorts,
        "grok_calls": len(tracker.entries),
        "gemini_queries": tracker.gemini_queries,
        "total_input_tokens": tracker.total_input_tokens,
        "total_output_tokens": tracker.total_output_tokens,
        "actual_cost": round(tracker.total_cost, 6),
        "estimated_cost": round(estimated_cost, 6) if estimated_cost is not None else None,
        "elapsed_seconds": round(elapsed_seconds, 1),
        "metadata": metadata or {},
    }

    by_type: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
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
    entry["by_call_type"] = by_type
    entry["by_model"] = by_model

    with log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def estimate_run_cost(full_videos: int, shorts: int, accordion: bool = False) -> str:
    """Pre-run cost estimate for dry-run output."""
    grok_cost = full_videos * 0.006 + shorts * 0.0004
    gemini_cost = deep_research_query_cost() if accordion else 0.0
    accordion_grok = ACCORDION_GROK_ESTIMATE if accordion else 0.0
    total = grok_cost + gemini_cost + accordion_grok

    parts = []
    if full_videos:
        parts.append(f"{full_videos} full videos x $0.006 = ${full_videos * 0.006:.2f}")
    if shorts:
        parts.append(f"{shorts} Shorts x $0.0004 = ${shorts * 0.0004:.3f}")
    if accordion:
        parts.append(
            f"Accordion: ~${report_deep_research_estimate():.2f} "
            f"(Gemini ${gemini_cost:.2f} + Grok ${accordion_grok:.2f})"
        )

    return f"Estimated cost: ${total:.2f} ({'; '.join(parts)})"


def report_deep_research_estimate(*, include_section_writing: bool = True) -> float:
    """Estimate a report run that submits one Gemini Deep Research job."""
    total = deep_research_query_cost()
    if include_section_writing:
        total += ACCORDION_GROK_ESTIMATE
    return total
