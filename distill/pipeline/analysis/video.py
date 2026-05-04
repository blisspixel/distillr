"""Per-video analysis via the LLM router."""

from rich.console import Console

from distill.config import DistillConfig, router_config_from_distill
from distill.llm import call as llm_call
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.analysis import (
    auto_watch_instructions_prompt,
    channel_context_prompt,
    pass1_extraction_prompt,
    pass2_synthesis_prompt,
    scan_insight_prompt,
    shorts_insight_prompt,
)

__all__ = [
    "analyze_scan",
    "analyze_short",
    "analyze_video",
    "generate_channel_context",
    "generate_watch_instructions",
]

console = Console()


def analyze_video(
    title: str,
    upload_date: str,
    channel_name: str,
    transcript: str,
    config: DistillConfig,
    tracker: CostTracker | None = None,
    custom_instructions: str = "",
) -> str:
    """Run 2-pass analysis on a video transcript. Returns insights markdown."""
    rc = router_config_from_distill(config)

    prompt1 = pass1_extraction_prompt(
        title, upload_date, channel_name, transcript, custom_instructions
    )
    response1 = llm_call(rc, workload_tag="analysis", prompt=prompt1, call_type="pass1")
    pass1 = response1.text
    if tracker:
        tracker.record(
            TokenUsage(
                prompt_tokens=response1.input_tokens,
                completion_tokens=response1.output_tokens,
                model=response1.model,
                call_type="pass1",
            )
        )

    prompt2 = pass2_synthesis_prompt(title, upload_date, channel_name, pass1)
    response2 = llm_call(rc, workload_tag="analysis", prompt=prompt2, call_type="pass2")
    pass2 = response2.text
    if tracker:
        tracker.record(
            TokenUsage(
                prompt_tokens=response2.input_tokens,
                completion_tokens=response2.output_tokens,
                model=response2.model,
                call_type="pass2",
            )
        )

    model = response2.model
    safe_title = title.replace('"', '\\"')
    return f"""---
video_title: \"{safe_title}\"
channel: {channel_name}
upload_date: {upload_date}
analyzed_by: {model}
---

{pass2}
"""


def analyze_short(
    title: str,
    upload_date: str,
    channel_name: str,
    transcript: str,
    config: DistillConfig,
    tracker: CostTracker | None = None,
) -> str:
    """Single-pass analysis for YouTube Shorts. Returns insights markdown."""
    rc = router_config_from_distill(config)

    prompt = shorts_insight_prompt(title, upload_date, channel_name, transcript)
    response = llm_call(
        rc, workload_tag="analysis", prompt=prompt, max_tokens=2048, call_type="short"
    )
    result = response.text
    if tracker:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.input_tokens,
                completion_tokens=response.output_tokens,
                model=response.model,
                call_type="short",
            )
        )

    safe_title = title.replace('"', '\\"')
    return f"""---
video_title: \"{safe_title}\"
channel: {channel_name}
upload_date: {upload_date}
analyzed_by: {response.model}
content_type: short
---

{result}
"""


def analyze_scan(
    title: str,
    upload_date: str,
    channel_name: str,
    transcript: str,
    config: DistillConfig,
    tracker: CostTracker | None = None,
    custom_instructions: str = "",
) -> str:
    """Single-pass scan analysis for any video. Lightweight triage."""
    rc = router_config_from_distill(config)

    prompt = scan_insight_prompt(title, upload_date, channel_name, transcript, custom_instructions)
    response = llm_call(
        rc, workload_tag="analysis", prompt=prompt, max_tokens=2048, call_type="scan"
    )
    result = response.text
    if tracker:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.input_tokens,
                completion_tokens=response.output_tokens,
                model=response.model,
                call_type="scan",
            )
        )

    safe_title = title.replace('"', '\\"')
    return f"""---
video_title: \"{safe_title}\"
channel: {channel_name}
upload_date: {upload_date}
analyzed_by: {response.model}
analysis_mode: scan
---

{result}
"""


def generate_channel_context(
    channel_name: str,
    video_titles: list[str],
    config: DistillConfig,
    tracker: CostTracker | None = None,
) -> str:
    """Generate a channel profile/context document."""
    rc = router_config_from_distill(config)
    prompt = channel_context_prompt(channel_name, video_titles)
    response = llm_call(rc, workload_tag="analysis", prompt=prompt, call_type="channel_context")
    if tracker:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.input_tokens,
                completion_tokens=response.output_tokens,
                model=response.model,
                call_type="channel_context",
            )
        )
    return response.text


def generate_watch_instructions(
    channel_name: str,
    video_titles: list[str],
    config: DistillConfig,
    tracker: CostTracker | None = None,
) -> str:
    """Auto-generate smart default analysis instructions for a channel."""
    rc = router_config_from_distill(config)
    prompt = auto_watch_instructions_prompt(channel_name, video_titles)
    response = llm_call(
        rc, workload_tag="analysis", prompt=prompt, max_tokens=256, call_type="watch_instructions"
    )
    if tracker:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.input_tokens,
                completion_tokens=response.output_tokens,
                model=response.model,
                call_type="watch_instructions",
            )
        )
    return response.text
