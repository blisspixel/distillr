# pyright: strict
"""Pure, side-effect-free cost projection and calibration helpers."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from distill.llm.cost import DEFAULT_MODEL, compute_cost, deep_research_query_cost
from distill.llm.cost_policy import classify_provider, evaluate_route_cost_policy
from distill.pipeline.cost_history import scan_confined_cost_log, select_cost_log_path

if TYPE_CHECKING:
    from distill.llm.router import RouterConfig

__all__ = [
    "ACCORDION_GROK_ESTIMATE",
    "CORPUS_REPORT_ESTIMATE",
    "CostCalibration",
    "CostEstimate",
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
    "load_cost_calibration",
    "report_deep_research_estimate",
    "report_profile_estimate",
]

# Report estimates include all sequential section inputs and outputs, one
# full-document QA review, and one likely section rewrite. They are registry
# backed so a default-model price change is visible in dry-run projections.
ACCORDION_GROK_ESTIMATE: float = compute_cost(DEFAULT_MODEL, 360_000, 30_000)
CORPUS_REPORT_ESTIMATE: float = compute_cost(DEFAULT_MODEL, 420_000, 25_000)

# Representative input and output token volumes for one ingested unit. These
# registry-backed estimates track the configured default model rather than a
# stale dollar constant. Historical calibration replaces them when available.
_STAGE_TOKENS: dict[str, tuple[int, int]] = {
    "video_full": (13_000, 6_000),
    "video_short": (800, 500),
    "video_scan": (1_500, 800),
    "paper": (20_000, 3_000),
    "site_page": (12_000, 3_000),
    "synthesis": (20_000, 4_000),
    "claim_extraction": (4_000, 2_000),
}

_ASK_PROMPT_OVERHEAD_CHARS = 1_200
_ASK_OUTPUT_TOKENS = 2_000
_CHARS_PER_TOKEN_ESTIMATE = 4
_NOMINAL_VIDEO_SECONDS = 900.0
_VIDEO_FACTOR_FLOOR = 0.3
_VIDEO_FACTOR_CEIL = 4.0
_CALIBRATION_MIN_SAMPLES = 3
_MAX_CALIBRATION_ITEM_COUNT = 1_000_000
_VIDEO_CALL_TYPES: frozenset[str] = frozenset({"pass1", "pass2", "short", "scan"})


def estimate_stage_cost(stage: str, *, model: str = "") -> float:
    """Return the registry-backed USD estimate for one stage unit."""

    input_tokens, output_tokens = _STAGE_TOKENS[stage]
    return compute_cost(model or DEFAULT_MODEL, input_tokens, output_tokens)


def estimate_synthesis_workflow_cost(
    calls: int = 1,
    *,
    router_config: RouterConfig | None = None,
) -> float:
    """Project known synthesis calls before model execution."""

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
    """Project paper analysis and known paper-tail calls."""

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
    return paper_cost + max(0, synthesis_calls) * synthesis_rate


def estimate_ask_workflow_cost(
    source_chars: int,
    *,
    question_chars: int = 0,
    model: str = "",
    router_config: RouterConfig | None = None,
) -> float:
    """Project one corpus question after source retrieval."""

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
    """Project site pages and site-routed synthesis calls."""

    page_rate = (
        _routed_stage_cost("site_page", "site", router_config)
        if router_config is not None
        else estimate_stage_cost("site_page")
    )
    synthesis_rate = (
        _routed_stage_cost("synthesis", "site", router_config)
        if router_config is not None
        else estimate_stage_cost("synthesis")
    )
    return (
        max(0, page_count) * page_rate
        + max(0, synthesis_calls) * synthesis_rate
        + (report_deep_research_estimate() if include_report else 0.0)
    )


def estimate_video_workflow_cost(
    full_videos: int = 0,
    shorts: int = 0,
    *,
    scan_videos: int = 0,
    include_report: bool = False,
    synthesis_calls: int = 0,
) -> float:
    """Project video-oriented CLI workflows before model calls."""

    analysis_cost = (
        full_videos * estimate_stage_cost("video_full")
        + shorts * estimate_stage_cost("video_short")
        + scan_videos * estimate_stage_cost("video_scan")
    )
    synthesis_cost = estimate_synthesis_workflow_cost(synthesis_calls)
    report_cost = deep_research_query_cost() + ACCORDION_GROK_ESTIMATE if include_report else 0.0
    return analysis_cost + synthesis_cost + report_cost


def _routed_stage_cost(stage: str, workload: str, router_config: RouterConfig) -> float:
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
    """Price a call against its primary and usable fallback routes."""

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
    """Project a video workflow using the routes that will execute each stage."""

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
    claims_cost = max(0, claim_extraction_calls) * _routed_stage_cost(
        "claim_extraction", "concepts", router_config
    )
    if not include_report:
        return analysis_cost + synthesis_cost + claims_cost

    accordion_cost = _routed_stage_cost("synthesis", "accordion", router_config)
    if accordion_cost > 0:
        accordion_cost = max(accordion_cost, ACCORDION_GROK_ESTIMATE)
    return (
        analysis_cost + synthesis_cost + claims_cost + deep_research_query_cost() + accordion_cost
    )


def estimate_run_cost(
    full_videos: int,
    shorts: int,
    accordion: bool = False,
    *,
    router_config: RouterConfig | None = None,
) -> str:
    """Render a pre-run estimate for dry-run output."""

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
    analysis_cost = full_videos * full_rate + shorts * short_rate
    deep_research_cost = deep_research_query_cost() if accordion else 0.0
    accordion_generation = 0.0
    if accordion:
        if router_config is None:
            accordion_generation = ACCORDION_GROK_ESTIMATE
        else:
            routed_accordion = _routed_stage_cost("synthesis", "accordion", router_config)
            if routed_accordion > 0:
                accordion_generation = max(routed_accordion, ACCORDION_GROK_ESTIMATE)
    total = analysis_cost + deep_research_cost + accordion_generation

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
            f"(Gemini ${deep_research_cost:.2f} + generation ${accordion_generation:.2f})"
        )
    return f"Estimated cost: ${total:.2f} ({'; '.join(parts)})"


_DISCOVER_PAPER_COST = estimate_stage_cost("paper")
_DISCOVER_SITE_COST = estimate_stage_cost("site_page")
_DISCOVER_VIDEO_COST = estimate_stage_cost("video_full")


@dataclass(frozen=True)
class CostCalibration:
    """Per-source USD rates derived from clean historical run logs."""

    per_paper: float = _DISCOVER_PAPER_COST
    per_video: float = _DISCOVER_VIDEO_COST
    per_site: float = _DISCOVER_SITE_COST
    samples: dict[str, int] = field(default_factory=lambda: {"paper": 0, "video": 0, "site": 0})

    @property
    def any_calibrated(self) -> bool:
        return any(value > 0 for value in self.samples.values())


@dataclass(frozen=True)
class CostEstimate:
    """A pre-run spend estimate with an explicit uncertainty range."""

    expected: float
    low: float
    high: float
    calibrated: bool

    def format(self) -> str:
        return f"~${self.expected:.2f} (est; ${self.low:.2f}-${self.high:.2f})"


def _classify_clean_run(row: dict[str, Any]) -> tuple[str, float, int] | None:
    """Classify a usable clean single-source calibration row."""

    if str(row.get("command", "")).endswith("_preview"):
        return None
    cost = _positive_calibration_cost(row.get("actual_cost"))
    raw_by_type: object = row.get("by_call_type") or {}
    if cost is None or not isinstance(raw_by_type, dict):
        return None
    by_type = cast(dict[str, Any], raw_by_type)
    has_paper = "paper" in by_type
    has_site = "site_page" in by_type
    has_video = any(call_type in by_type for call_type in _VIDEO_CALL_TYPES)
    if has_paper and not has_site and not has_video:
        count = _call_count(by_type, "paper")
        return ("paper", cost, count) if count else None
    if has_video and not has_paper and not has_site:
        return _classify_clean_video(row, by_type, cost)
    if has_site and not has_paper and not has_video:
        count = _call_count(by_type, "site_page")
        return ("site", cost, count) if count else None
    return None


def _positive_calibration_cost(raw_cost: object) -> float | None:
    if isinstance(raw_cost, bool) or not isinstance(raw_cost, int | float):
        return None
    try:
        cost = float(raw_cost)
    except OverflowError:
        return None
    if not math.isfinite(cost) or cost <= 0:
        return None
    return cost


def _classify_clean_video(
    row: dict[str, Any],
    by_type: dict[str, Any],
    cost: float,
) -> tuple[str, float, int] | None:
    has_full_video = "pass1" in by_type or "pass2" in by_type
    raw_shorts: object = row.get("shorts", 0)
    shorts = _bounded_calibration_count(raw_shorts)
    if shorts is None:
        return None
    has_scan_or_short = "scan" in by_type or "short" in by_type or shorts > 0
    if has_full_video and not has_scan_or_short:
        raw_full_videos: object = row.get("full_videos", 0)
        count = _bounded_calibration_count(raw_full_videos)
        if count is None:
            return None
        if count == 0:
            count = _call_count(by_type, "pass1")
        return ("video", cost, count) if count else None
    return None


def _call_count(by_type: dict[str, Any], call_type: str) -> int | None:
    raw_entry: object = by_type.get(call_type)
    if not isinstance(raw_entry, dict):
        return None
    entry = cast(dict[str, object], raw_entry)
    return _bounded_calibration_count(entry.get("calls", 0))


def _bounded_calibration_count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if not 0 <= value <= _MAX_CALIBRATION_ITEM_COUNT:
        return None
    return value


def load_cost_calibration(
    log_dir: Path,
    *,
    min_samples: int = _CALIBRATION_MIN_SAMPLES,
) -> CostCalibration:
    """Derive per-source rates from clean single-source run logs."""

    log_file = select_cost_log_path(log_dir)
    if log_file is None:
        return CostCalibration()
    scan = scan_confined_cost_log(log_file, log_dir)
    if not scan.complete:
        return CostCalibration()
    cost = {"paper": 0.0, "video": 0.0, "site": 0.0}
    count = {"paper": 0, "video": 0, "site": 0}
    for row in scan.rows:
        try:
            classified = _classify_clean_run(row)
        except (AttributeError, TypeError, ValueError):
            continue
        if classified is None:
            continue
        kind, run_cost, item_count = classified
        cost[kind] += run_cost
        count[kind] += item_count

    defaults = {
        "paper": _DISCOVER_PAPER_COST,
        "video": _DISCOVER_VIDEO_COST,
        "site": _DISCOVER_SITE_COST,
    }
    rates = {
        kind: cost[kind] / count[kind] if count[kind] >= min_samples else default
        for kind, default in defaults.items()
    }
    samples = {kind: count[kind] if count[kind] >= min_samples else 0 for kind in defaults}
    return CostCalibration(
        per_paper=rates["paper"],
        per_video=rates["video"],
        per_site=rates["site"],
        samples=samples,
    )


def _video_duration_factor(seconds: float | None) -> float:
    if not seconds or seconds <= 0:
        return 1.0
    return max(
        _VIDEO_FACTOR_FLOOR,
        min(_VIDEO_FACTOR_CEIL, seconds / _NOMINAL_VIDEO_SECONDS),
    )


def _routed_discover_calibration(
    calibration: CostCalibration,
    router_config: RouterConfig,
) -> CostCalibration:
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
    """Return the count-based point estimate for a discover ingest set."""

    resolved = calibration or CostCalibration()
    if router_config is not None:
        resolved = _routed_discover_calibration(resolved, router_config)
    return (
        max(0, papers) * resolved.per_paper
        + max(0, sites) * resolved.per_site
        + max(0, videos) * resolved.per_video
    )


def estimate_discover_items(
    *,
    papers: int = 0,
    video_durations: Sequence[float | None] = (),
    sites: int = 0,
    calibration: CostCalibration | None = None,
    router_config: RouterConfig | None = None,
) -> CostEstimate:
    """Return a metadata-aware estimate with an uncertainty range."""

    resolved = calibration or CostCalibration()
    if router_config is not None:
        resolved = _routed_discover_calibration(resolved, router_config)
    expected = max(0, papers) * resolved.per_paper + max(0, sites) * resolved.per_site
    expected += sum(
        resolved.per_video * _video_duration_factor(duration) for duration in video_durations
    )
    calibrated = resolved.any_calibrated
    low_multiplier, high_multiplier = (0.7, 1.5) if calibrated else (0.5, 2.0)
    return CostEstimate(
        expected=expected,
        low=expected * low_multiplier,
        high=expected * high_multiplier,
        calibrated=calibrated,
    )


def report_deep_research_estimate(*, include_section_writing: bool = True) -> float:
    """Estimate one Gemini Deep Research report run."""

    total = deep_research_query_cost()
    if include_section_writing:
        total += ACCORDION_GROK_ESTIMATE
    return total


def report_profile_estimate(
    profile: str,
    *,
    research_only: bool = False,
    skip_qa: bool = False,
    router_config: RouterConfig | None = None,
) -> float:
    """Estimate one canonical report profile before any provider call."""

    normalized = profile.strip().casefold().replace("_", "-")
    if normalized in {"deep-research", "legacy"}:
        return deep_research_query_cost()
    if normalized == "accordion":
        if research_only:
            return deep_research_query_cost()
        generation = _report_generation_estimate(
            input_tokens=360_000,
            output_tokens=30_000,
            default=ACCORDION_GROK_ESTIMATE,
            router_config=router_config,
        ) * (0.85 if skip_qa else 1.0)
        return deep_research_query_cost() + generation
    if normalized in {"corpus", "corpus-report"}:
        if research_only:
            raise ValueError("research_only is not supported by corpus-report")
        generation = _report_generation_estimate(
            input_tokens=420_000,
            output_tokens=25_000,
            default=CORPUS_REPORT_ESTIMATE,
            router_config=router_config,
        )
        return generation * (0.85 if skip_qa else 1.0)
    raise ValueError(f"unknown report profile: {profile}")


def _report_generation_estimate(
    *,
    input_tokens: int,
    output_tokens: int,
    default: float,
    router_config: RouterConfig | None,
) -> float:
    if router_config is None:
        return default
    return _routed_model_cost(
        "accordion",
        router_config,
        lambda model: compute_cost(model, input_tokens, output_tokens),
    )
