"""Per-video analysis via xAI models."""

import time

from openai import OpenAI
from rich.console import Console

from distill.config import DistillConfig
from distill.costs import CostTracker, TokenUsage
from distill.prompts import (
    auto_watch_instructions_prompt,
    channel_context_prompt,
    pass1_extraction_prompt,
    pass2_synthesis_prompt,
    scan_insight_prompt,
    shorts_insight_prompt,
)

console = Console()

XAI_BASE_URL = "https://api.x.ai/v1"
DEFAULT_XAI_MODEL = "grok-4-1-fast-reasoning"


def _get_client(config: DistillConfig) -> OpenAI:
    return OpenAI(api_key=config.xai_api_key, base_url=XAI_BASE_URL)


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
    client = _get_client(config)
    model = config.xai_model_for("analysis")

    prompt1 = pass1_extraction_prompt(
        title, upload_date, channel_name, transcript, custom_instructions
    )
    pass1 = _call_grok(client, prompt1, model=model, tracker=tracker, call_type="pass1")

    prompt2 = pass2_synthesis_prompt(title, upload_date, channel_name, pass1)
    pass2 = _call_grok(client, prompt2, model=model, tracker=tracker, call_type="pass2")

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
    client = _get_client(config)
    model = config.xai_model_for("analysis")

    prompt = shorts_insight_prompt(title, upload_date, channel_name, transcript)
    result = _call_grok(
        client,
        prompt,
        model=model,
        max_tokens=2048,
        tracker=tracker,
        call_type="short",
    )

    safe_title = title.replace('"', '\\"')
    return f"""---
video_title: \"{safe_title}\"
channel: {channel_name}
upload_date: {upload_date}
analyzed_by: {model}
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
    client = _get_client(config)
    model = config.xai_model_for("analysis")

    prompt = scan_insight_prompt(title, upload_date, channel_name, transcript, custom_instructions)
    result = _call_grok(
        client,
        prompt,
        model=model,
        max_tokens=2048,
        tracker=tracker,
        call_type="scan",
    )

    safe_title = title.replace('"', '\\"')
    return f"""---
video_title: \"{safe_title}\"
channel: {channel_name}
upload_date: {upload_date}
analyzed_by: {model}
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
    client = _get_client(config)
    model = config.xai_model_for("analysis")
    prompt = channel_context_prompt(channel_name, video_titles)
    return _call_grok(
        client,
        prompt,
        model=model,
        tracker=tracker,
        call_type="channel_context",
    )


def generate_watch_instructions(
    channel_name: str,
    video_titles: list[str],
    config: DistillConfig,
    tracker: CostTracker | None = None,
) -> str:
    """Auto-generate smart default analysis instructions for a channel."""
    client = _get_client(config)
    model = config.xai_model_for("analysis")
    prompt = auto_watch_instructions_prompt(channel_name, video_titles)
    return _call_grok(
        client,
        prompt,
        model=model,
        max_tokens=256,
        tracker=tracker,
        call_type="watch_instructions",
    )


def _call_grok(
    client: OpenAI,
    prompt: str,
    model: str = DEFAULT_XAI_MODEL,
    retries: int = 2,
    max_tokens: int = 8192,
    tracker: CostTracker | None = None,
    call_type: str = "",
) -> str:
    """Call Grok via xAI API with retry on transient failures."""
    last_error = None
    for attempt in range(retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=max_tokens,
                timeout=300,
            )
            if not response.choices:
                return ""

            if tracker and response.usage:
                tracker.record(
                    TokenUsage(
                        prompt_tokens=response.usage.prompt_tokens or 0,
                        completion_tokens=response.usage.completion_tokens or 0,
                        model=model,
                        call_type=call_type,
                    )
                )

            return response.choices[0].message.content or ""
        except Exception as e:
            last_error = e
            if attempt < retries:
                wait = 2**attempt * 5
                console.print(
                    f"    [yellow]API error (attempt {attempt + 1}/{retries + 1}): {e}. Retrying in {wait}s...[/yellow]"
                )
                time.sleep(wait)
            else:
                raise
    raise last_error
