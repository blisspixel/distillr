"""Cost tracking for API calls."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Pricing per 1M tokens (as of April 20, 2026, from xAI and Gemini docs).
# xAI cached-input rates ($0.05 fast, $0.20 premium) are not yet tracked;
# estimates here assume all input tokens are uncached.
PRICING = {
    "grok-4-1-fast-reasoning": {"input": 0.20, "output": 0.50},
    "grok-4.20-0309-reasoning": {"input": 2.00, "output": 6.00},
    "grok-4.20": {"input": 2.00, "output": 6.00},
    "gemini-deep-research": {"per_query": 2.50},
}


def _pricing_for_model(model: str) -> dict[str, float]:
    if model in PRICING:
        return PRICING[model]
    if model.startswith("grok-4.20"):
        return PRICING["grok-4.20"]
    if model.startswith("grok-4-1-fast"):
        return PRICING["grok-4-1-fast-reasoning"]
    return PRICING["grok-4-1-fast-reasoning"]


@dataclass
class TokenUsage:
    """Token usage from a single API call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    call_type: str = ""


@dataclass
class CostTracker:
    """Accumulates token usage and cost across a run."""

    entries: list[TokenUsage] = field(default_factory=list)
    gemini_queries: int = 0

    def record(self, usage: TokenUsage):
        """Record a token usage entry."""
        self.entries.append(usage)

    def record_gemini_query(self):
        """Record a Gemini Deep Research query."""
        self.gemini_queries += 1

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
            rates = _pricing_for_model(entry.model)
            total += entry.prompt_tokens * rates["input"] / 1_000_000
            total += entry.completion_tokens * rates["output"] / 1_000_000
        return total

    @property
    def total_gemini_cost(self) -> float:
        """Estimated Gemini Deep Research cost."""
        rate = PRICING.get("gemini-deep-research", {"per_query": 2.50})
        return self.gemini_queries * rate["per_query"]

    @property
    def total_cost(self) -> float:
        return self.total_grok_cost + self.total_gemini_cost

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

        return {
            "grok_calls": len(self.entries),
            "gemini_queries": self.gemini_queries,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "estimated_grok_cost": f"${self.total_grok_cost:.4f}",
            "estimated_gemini_cost": f"${self.total_gemini_cost:.2f}",
            "estimated_total_cost": self.format_cost(),
            "by_model": by_model,
        }


def save_run_log(
    log_dir: Path,
    command: str,
    tracker: "CostTracker",
    estimated_cost: float | None = None,
    full_videos: int = 0,
    shorts: int = 0,
    elapsed_seconds: float = 0,
    metadata: dict[str, str] | None = None,
):
    """Append a run cost entry to the cost log for estimate calibration."""
    log_file = log_dir / "cost_log.jsonl"
    log_dir.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": datetime.now().isoformat(),
        "command": command,
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
    gemini_cost = 2.50 if accordion else 0
    accordion_grok = 0.05 if accordion else 0
    total = grok_cost + gemini_cost + accordion_grok

    parts = []
    if full_videos:
        parts.append(f"{full_videos} full videos x $0.006 = ${full_videos * 0.006:.2f}")
    if shorts:
        parts.append(f"{shorts} Shorts x $0.0004 = ${shorts * 0.0004:.3f}")
    if accordion:
        parts.append("Accordion: ~$2.55 (Gemini $2.50 + Grok $0.05)")

    return f"Estimated cost: ${total:.2f} ({'; '.join(parts)})"
