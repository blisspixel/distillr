"""Report pipeline — deep research, accordion, and brief generation."""

from distill.pipeline.report.accordion import run_accordion_research
from distill.pipeline.report.brief import (
    compose_prompt,
    gather_topic_files,
    run_research_brief,
)
from distill.pipeline.report.briefing import generate_topic_brief
from distill.pipeline.report.deep_research import run_deep_research
from distill.pipeline.report.file_search import (
    cleanup_stores,
    create_research_store,
    delete_store,
    list_stores,
)
from distill.pipeline.report.synthesize import compose_synthesis_prompt, run_synthesis

__all__ = [
    "cleanup_stores",
    "compose_prompt",
    "compose_synthesis_prompt",
    "create_research_store",
    "delete_store",
    "gather_topic_files",
    "generate_topic_brief",
    "list_stores",
    "run_accordion_research",
    "run_deep_research",
    "run_research_brief",
    "run_synthesis",
]
