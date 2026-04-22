"""Lightweight briefing built from learned insights."""

from __future__ import annotations

from pathlib import Path

from openai import OpenAI

from distill.analysis import XAI_BASE_URL
from distill.config import DistillConfig
from distill.costs import CostTracker, TokenUsage
from distill.prompts import topic_brief_prompt


def generate_topic_brief(
    topic: str,
    config: DistillConfig,
    tracker: CostTracker | None = None,
) -> Path | None:
    topic_dir = config.topic_dir(topic)
    topic_dir.mkdir(parents=True, exist_ok=True)

    synth_file = topic_dir / "topic_synthesis.md"
    topic_synthesis = synth_file.read_text(encoding="utf-8") if synth_file.exists() else ""

    insight_parts = []
    channels_dir = topic_dir / "channels"
    if channels_dir.exists():
        for channel_dir in sorted(channels_dir.iterdir()):
            videos_dir = channel_dir / "videos"
            if not videos_dir.exists():
                continue
            for video_dir in sorted(videos_dir.iterdir(), reverse=True):
                insight_file = video_dir / "insights.md"
                if insight_file.exists():
                    insight_parts.append(
                        f"## {channel_dir.name} / {video_dir.name}\n"
                        + insight_file.read_text(encoding="utf-8")
                    )
                if len(insight_parts) >= 6:
                    break
            if len(insight_parts) >= 6:
                break

    if not topic_synthesis and not insight_parts:
        return None

    prompt = topic_brief_prompt(topic, topic_synthesis, "\n\n---\n\n".join(insight_parts))
    client = OpenAI(api_key=config.xai_api_key, base_url=XAI_BASE_URL)
    model = config.xai_model_for("brief")
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=4096,
        timeout=180,
    )

    if tracker and response.usage:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.usage.prompt_tokens or 0,
                completion_tokens=response.usage.completion_tokens or 0,
                model=model,
                call_type="topic_brief",
            )
        )

    content = response.choices[0].message.content if response.choices else ""
    if not content:
        return None

    output_path = topic_dir / "brief.md"
    output_path.write_text(content, encoding="utf-8")
    return output_path
