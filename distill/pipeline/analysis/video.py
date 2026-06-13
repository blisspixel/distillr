"""Per-video analysis via the LLM router."""

from distill.config import DistillConfig
from distill.library.intent import CorpusIntent
from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
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
) -> str:
    """Run 2-pass analysis on a video transcript. Returns insights markdown.

    ``router_config`` lets a caller (e.g. the eval harness) force a specific
    model/provider; defaults to the configured routing. ``intent`` selects the
    analysis lens and goal focus; ``None`` keeps the neutral default.
    """
    rc = router_config or RouterConfig()
    goal, lens = _intent_goal_lens(intent)

    prompt1 = pass1_extraction_prompt(
        title, upload_date, channel_name, transcript, custom_instructions, goal=goal
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

    prompt2 = pass2_synthesis_prompt(title, upload_date, channel_name, pass1, goal=goal, lens=lens)
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
model: {model}
model_version: {model}
temperature: 0.0
prompt_id: "analysis.pass2.v2"
lens: {lens}
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
    *,
    intent: CorpusIntent | None = None,
) -> str:
    """Single-pass analysis for YouTube Shorts. Returns insights markdown."""
    rc = RouterConfig()
    goal, _ = _intent_goal_lens(intent)

    prompt = shorts_insight_prompt(title, upload_date, channel_name, transcript, goal=goal)
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
model: {response.model}
model_version: {response.model}
temperature: 0.0
prompt_id: "analysis.short.v2"
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
    *,
    intent: CorpusIntent | None = None,
) -> str:
    """Single-pass scan analysis for any video. Lightweight triage."""
    rc = RouterConfig()
    goal, _ = _intent_goal_lens(intent)

    prompt = scan_insight_prompt(
        title, upload_date, channel_name, transcript, custom_instructions, goal=goal
    )
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
model: {response.model}
model_version: {response.model}
temperature: 0.0
prompt_id: "analysis.scan.v2"
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
    rc = RouterConfig()
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
    rc = RouterConfig()
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
