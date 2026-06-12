"""Lightweight briefing built from learned insights."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from distill.config import DistillConfig
from distill.library.paths import (
    ProvenanceFields,
    base_frontmatter,
    find_artifact,
    tags_for,
    write_markdown_artifact,
)
from distill.library.wikilinks import emit_wiki_link
from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.registry import PROMPT_IDS
from distill.prompts.report import topic_brief_prompt

__all__ = [
    "generate_topic_brief",
]

logger = logging.getLogger(__name__)


def generate_topic_brief(  # noqa: C901 — legacy, will refactor
    topic: str,
    config: DistillConfig,
    tracker: CostTracker | None = None,
) -> Path | None:
    topic_dir = config.topic_dir(topic)
    topic_dir.mkdir(parents=True, exist_ok=True)

    synth_file = find_artifact(topic_dir, "topic_synthesis", identity=topic)
    topic_synthesis = synth_file.read_text(encoding="utf-8") if synth_file.exists() else ""

    insight_parts = []
    channels_dir = topic_dir / "channels"
    if channels_dir.exists():
        for channel_dir in sorted(channels_dir.iterdir()):
            videos_dir = channel_dir / "videos"
            if not videos_dir.exists():
                continue
            for video_dir in sorted(videos_dir.iterdir(), reverse=True):
                insight_file = find_artifact(video_dir, "insights")
                if insight_file.exists():
                    # Build wiki-link for this source artifact
                    meta_file = video_dir / "metadata.json"
                    title = video_dir.name
                    source_id = video_dir.name
                    if meta_file.exists():
                        try:
                            meta = json.loads(meta_file.read_text(encoding="utf-8"))
                            title = meta.get("title", title)
                            source_id = meta.get("video_id", source_id)
                        except (json.JSONDecodeError, OSError):
                            pass
                    link = emit_wiki_link(title, source_id, "insights")
                    insight_parts.append(
                        f"## {channel_dir.name} / {video_dir.name}\nSource: {link}\n"
                        + insight_file.read_text(encoding="utf-8")
                    )
                if len(insight_parts) >= 6:
                    break
            if len(insight_parts) >= 6:
                break

    if not topic_synthesis and not insight_parts:
        return None

    rc = RouterConfig()
    prompt = topic_brief_prompt(topic, topic_synthesis, "\n\n---\n\n".join(insight_parts))
    response = llm_call(
        rc, workload_tag="brief", prompt=prompt, max_tokens=4096, call_type="topic_brief"
    )

    if tracker:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.input_tokens,
                completion_tokens=response.output_tokens,
                model=response.model,
                call_type="topic_brief",
            )
        )

    content = response.text
    if not content:
        return None

    return write_markdown_artifact(
        topic_dir,
        "brief",
        content,
        identity=topic,
        frontmatter=base_frontmatter(
            artifact_type="brief",
            title=f"Topic brief: {topic}",
            topic=topic,
            source="distill",
            tags=tags_for(topic, "brief"),
            synthesis_scope="interpretation",
            extra={"legacy_filename": "brief.md"},
            provenance=ProvenanceFields(
                model=response.model,
                model_version=response.model,
                temperature=0.0,
                prompt_id=PROMPT_IDS["brief.topic"],
            ),
        ),
    )
