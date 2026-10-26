# pyright: strict
"""Per-video analysis via the LLM router."""

from collections.abc import Callable

from distill.config import DistillConfig
from distill.ingestors.youtube.caption_timing import CaptionEvidence
from distill.library.intent import CorpusIntent
from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
from distill.llm.types import LLM_Response
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.analysis import (
    auto_watch_instructions_prompt,
    channel_context_prompt,
    pass1_extraction_prompt,
    pass2_synthesis_prompt,
    scan_insight_prompt,
    shorts_insight_prompt,
)
from distill.prompts.lenses import DEFAULT_LENS
from distill.prompts.registry import PROMPT_IDS

__all__ = [
    "analyze_scan",
    "analyze_short",
    "analyze_video",
    "generate_channel_context",
    "generate_watch_instructions",
]


def _intent_goal_lens(intent: CorpusIntent | None) -> tuple[str, str]:
    """Resolve (goal, lens) from an optional intent, defaulting to neutral."""
    if intent is None:
        return "", DEFAULT_LENS
    return intent.goal, intent.lens


def _with_caption_evidence(markdown: str, evidence: CaptionEvidence | None) -> str:
    """Record caption coverage on the insight. The prompt is already built."""
    if evidence is None:
        return markdown
    block = (
        f"caption_timing: {evidence.timing}\n"
        f"caption_text_coverage: {evidence.text_coverage}\n"
        f"caption_source: {evidence.source}\n"
        f"caption_cue_count: {len(evidence.cues)}\n"
        f"caption_gap_count: {len(evidence.gaps_ms)}"
    )
    closing = markdown.find("\n---\n")
    if closing == -1:
        return markdown
    return f"{markdown[:closing]}\n{block}{markdown[closing:]}"


def analyze_video(
    title: str,
    upload_date: str,
    channel_name: str,
    transcript: str,
    config: DistillConfig,
    tracker: CostTracker | None = None,
    custom_instructions: str = "",
    router_config: RouterConfig | None = None,
    *,
    intent: CorpusIntent | None = None,
    caption_evidence: CaptionEvidence | None = None,
    response_observer: Callable[[str, LLM_Response], None] | None = None,
    max_tokens: int = 8192,
    timeout: int = 300,
    retries: int = 2,
) -> str:
    """Run 2-pass analysis on a video transcript. Returns insights markdown.

    ``router_config`` lets a caller (e.g. the eval harness) force a specific
    model/provider; defaults to the configured routing. ``intent`` selects the
    analysis lens and goal focus; ``None`` keeps the neutral default.
    """
    if max_tokens <= 0 or timeout <= 0 or retries < 0:
        raise ValueError("Video call limits require positive tokens/time and nonnegative retries")
    rc = router_config or RouterConfig()
    goal, lens = _intent_goal_lens(intent)

    prompt1 = pass1_extraction_prompt(
        title, upload_date, channel_name, transcript, custom_instructions, goal=goal
    )
    response1 = llm_call(
        rc,
        workload_tag="analysis",
        prompt=prompt1,
        call_type="pass1",
        usage_tracker=tracker,
        max_tokens=max_tokens,
        timeout=timeout,
        retries=retries,
    )
    pass1 = response1.text
    if tracker:
        tracker.record(TokenUsage.from_response(response1, call_type="pass1"))
    if response_observer is not None:
        response_observer("pass1", response1)
    if not pass1.strip():
        raise ValueError(
            "Video pass1 extraction returned no content; analysis is incomplete. "
            "Check the source and provider response before retrying."
        )

    prompt2 = pass2_synthesis_prompt(title, upload_date, channel_name, pass1, goal=goal, lens=lens)
    response2 = llm_call(
        rc,
        workload_tag="analysis",
        prompt=prompt2,
        call_type="pass2",
        usage_tracker=tracker,
        max_tokens=max_tokens,
        timeout=timeout,
        retries=retries,
    )
    pass2 = response2.text
    if tracker:
        tracker.record(TokenUsage.from_response(response2, call_type="pass2"))
    if response_observer is not None:
        response_observer("pass2", response2)
    if not pass2.strip():
        raise ValueError(
            "Video pass2 synthesis returned no content; analysis is incomplete. "
            "The acquired transcript remains available for retry."
        )

    model = response2.model
    safe_title = title.replace('"', '\\"')
    markdown = f"""---
video_title: \"{safe_title}\"
channel: {channel_name}
upload_date: {upload_date}
analyzed_by: {model}
model: {model}
model_version: {model}
temperature: 0.0
prompt_id: "{PROMPT_IDS["analysis.pass2"]}"
lens: {lens}
---

{pass2}
"""
    return _with_caption_evidence(markdown, caption_evidence)


def analyze_short(
    title: str,
    upload_date: str,
    channel_name: str,
    transcript: str,
    config: DistillConfig,
    tracker: CostTracker | None = None,
    *,
    intent: CorpusIntent | None = None,
    caption_evidence: CaptionEvidence | None = None,
) -> str:
    """Single-pass analysis for YouTube Shorts. Returns insights markdown."""
    rc = RouterConfig()
    goal, _ = _intent_goal_lens(intent)

    prompt = shorts_insight_prompt(title, upload_date, channel_name, transcript, goal=goal)
    response = llm_call(
        rc,
        workload_tag="analysis",
        prompt=prompt,
        max_tokens=2048,
        call_type="short",
        usage_tracker=tracker,
    )
    result = response.text
    if tracker:
        tracker.record(TokenUsage.from_response(response, call_type="short"))

    safe_title = title.replace('"', '\\"')
    markdown = f"""---
video_title: \"{safe_title}\"
channel: {channel_name}
upload_date: {upload_date}
analyzed_by: {response.model}
content_type: short
model: {response.model}
model_version: {response.model}
temperature: 0.0
prompt_id: "{PROMPT_IDS["analysis.short"]}"
---

{result}
"""
    return _with_caption_evidence(markdown, caption_evidence)


def analyze_scan(
    title: str,
    upload_date: str,
    channel_name: str,
    transcript: str,
    config: DistillConfig,
    tracker: CostTracker | None = None,
    custom_instructions: str = "",
    *,
    intent: CorpusIntent | None = None,
    caption_evidence: CaptionEvidence | None = None,
) -> str:
    """Single-pass scan analysis for any video. Lightweight triage."""
    rc = RouterConfig()
    goal, _ = _intent_goal_lens(intent)

    prompt = scan_insight_prompt(
        title, upload_date, channel_name, transcript, custom_instructions, goal=goal
    )
    response = llm_call(
        rc,
        workload_tag="analysis",
        prompt=prompt,
        max_tokens=2048,
        call_type="scan",
        usage_tracker=tracker,
    )
    result = response.text
    if tracker:
        tracker.record(TokenUsage.from_response(response, call_type="scan"))

    safe_title = title.replace('"', '\\"')
    markdown = f"""---
video_title: \"{safe_title}\"
channel: {channel_name}
upload_date: {upload_date}
analyzed_by: {response.model}
analysis_mode: scan
model: {response.model}
model_version: {response.model}
temperature: 0.0
prompt_id: "{PROMPT_IDS["analysis.scan"]}"
---

{result}
"""
    return _with_caption_evidence(markdown, caption_evidence)


def generate_channel_context(
    channel_name: str,
    video_titles: list[str],
    config: DistillConfig,
    tracker: CostTracker | None = None,
) -> str:
    """Generate a channel profile/context document."""
    rc = RouterConfig()
    prompt = channel_context_prompt(channel_name, video_titles)
    response = llm_call(
        rc,
        workload_tag="analysis",
        prompt=prompt,
        call_type="channel_context",
        usage_tracker=tracker,
    )
    if tracker:
        tracker.record(TokenUsage.from_response(response, call_type="channel_context"))
    return response.text


def generate_watch_instructions(
    channel_name: str,
    video_titles: list[str],
    config: DistillConfig,
    tracker: CostTracker | None = None,
) -> str:
    """Auto-generate smart default analysis instructions for a channel."""
    rc = RouterConfig()
    prompt = auto_watch_instructions_prompt(channel_name, video_titles)
    response = llm_call(
        rc,
        workload_tag="analysis",
        prompt=prompt,
        max_tokens=256,
        call_type="watch_instructions",
        usage_tracker=tracker,
    )
    if tracker:
        tracker.record(TokenUsage.from_response(response, call_type="watch_instructions"))
    return response.text
