"""Mixed-source topic corpus synthesis."""

from __future__ import annotations

from distill.config import DistillConfig, router_config_from_distill
from distill.library.paths import base_frontmatter, find_artifact, tags_for, write_markdown_artifact
from distill.llm import call as llm_call
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.synthesis import corpus_synthesis_prompt

__all__ = [
    "synthesize_corpus",
]


def synthesize_corpus(
    topic: str,
    config: DistillConfig,
    tracker: CostTracker | None = None,
) -> str:
    source_sections: dict[str, str] = {}

    topic_dir = config.topic_dir(topic)
    topic_synth = find_artifact(topic_dir, "topic_synthesis", identity=topic)
    if topic_synth.exists():
        source_sections["YouTube / Website Topic Synthesis"] = topic_synth.read_text(
            encoding="utf-8"
        )

    paper_synth = find_artifact(topic_dir, "paper_synthesis", identity=topic)
    if paper_synth.exists():
        source_sections["Paper Synthesis"] = paper_synth.read_text(encoding="utf-8")

    sites_dir = config.sites_dir(topic)
    if sites_dir.exists():
        for site_dir in sorted(sites_dir.iterdir()):
            if not site_dir.is_dir():
                continue
            synth_file = find_artifact(
                site_dir,
                "site_synthesis",
                identity=f"{topic}_{site_dir.name}",
            )
            if synth_file.exists():
                source_sections[f"Site: {site_dir.name}"] = synth_file.read_text(encoding="utf-8")

    if not source_sections:
        return ""

    rc = router_config_from_distill(config)
    response = llm_call(
        rc,
        workload_tag="site",
        prompt=corpus_synthesis_prompt(topic, source_sections),
        call_type="corpus_synthesis",
    )
    synthesis = response.text
    if tracker:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.input_tokens,
                completion_tokens=response.output_tokens,
                model=response.model,
                call_type="corpus_synthesis",
            )
        )
    write_markdown_artifact(
        topic_dir,
        "corpus_synthesis",
        synthesis,
        identity=topic,
        frontmatter=base_frontmatter(
            artifact_type="corpus-synthesis",
            title=f"Corpus synthesis: {topic}",
            topic=topic,
            source="distill",
            tags=tags_for(topic, "mixed"),
            confidence="corpus-consensus",
            extra={"legacy_filename": "corpus_synthesis.md"},
        ),
    )
    return synthesis
