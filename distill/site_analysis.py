"""Website page analysis and synthesis helpers."""

from __future__ import annotations

import time

from openai import OpenAI
from rich.console import Console

from distill.analysis import XAI_BASE_URL
from distill.artifacts import base_frontmatter, find_artifact, tags_for, write_markdown_artifact
from distill.config import DistillConfig
from distill.costs import CostTracker, TokenUsage
from distill.prompts import (
    site_page_insight_prompt,
    site_synthesis_prompt,
    site_topic_synthesis_prompt,
)
from distill.site_scraper import SitePage, build_page_document

console = Console()


def _get_client(config: DistillConfig) -> OpenAI:
    return OpenAI(api_key=config.xai_api_key, base_url=XAI_BASE_URL)


def _call_grok(
    client: OpenAI,
    prompt: str,
    model: str,
    retries: int = 2,
    max_tokens: int = 8192,
    tracker: CostTracker | None = None,
    call_type: str = "",
) -> str:
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
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                wait = 2**attempt * 5
                console.print(
                    f"  [yellow]API error (attempt {attempt + 1}/{retries + 1}): {exc}. Retrying in {wait}s...[/yellow]"
                )
                time.sleep(wait)
            else:
                raise
    raise last_error


def analyze_site_page(
    page: SitePage,
    config: DistillConfig,
    tracker: CostTracker | None = None,
) -> str:
    client = _get_client(config)
    model = config.xai_model_for("site")
    prompt = site_page_insight_prompt(
        page.title,
        page.url,
        page.site_name,
        page.page_type,
        build_page_document(page),
    )
    result = _call_grok(client, prompt, model=model, tracker=tracker, call_type="site_page")
    safe_title = page.title.replace('"', '\\"')
    return (
        f"---\n"
        f'page_title: "{safe_title}"\n'
        f"site: {page.site_name}\n"
        f"page_type: {page.page_type}\n"
        f"url: {page.url}\n"
        f"analyzed_by: {model}\n"
        "---\n\n"
        f"{result}\n"
    )


def synthesize_site(
    topic: str,
    site_name: str,
    config: DistillConfig,
    tracker: CostTracker | None = None,
) -> str:
    pages_dir = config.site_pages_dir(topic, site_name)
    if not pages_dir.exists():
        return ""

    parts = []
    for page_dir in sorted(pages_dir.iterdir()):
        if not page_dir.is_dir():
            continue
        insights_file = find_artifact(page_dir, "insights")
        if not insights_file.exists():
            continue
        parts.append(f"\n\n---\n{insights_file.read_text(encoding='utf-8')}")

    if not parts:
        return ""

    client = _get_client(config)
    model = config.xai_model_for("site")
    synthesis = _call_grok(
        client,
        site_synthesis_prompt(site_name, "".join(parts)),
        model=model,
        tracker=tracker,
        call_type="site_synthesis",
    )
    site_dir = config.site_dir(topic, site_name)
    write_markdown_artifact(
        site_dir,
        "site_synthesis",
        synthesis,
        identity=f"{topic}_{site_dir.name}",
        frontmatter=base_frontmatter(
            artifact_type="site-synthesis",
            title=f"Site synthesis: {site_name}",
            topic=topic,
            source="distill",
            tags=tags_for(topic, "website"),
            confidence="corpus-consensus",
            extra={"site": site_name, "legacy_filename": "synthesis.md"},
        ),
    )
    return synthesis


def synthesize_site_topic(
    topic: str,
    config: DistillConfig,
    tracker: CostTracker | None = None,
) -> str:
    sites_dir = config.sites_dir(topic)
    if not sites_dir.exists():
        return ""

    site_summaries: dict[str, str] = {}
    for site_dir in sorted(sites_dir.iterdir()):
        if not site_dir.is_dir():
            continue
        synth_file = find_artifact(
            site_dir,
            "site_synthesis",
            identity=f"{topic}_{site_dir.name}",
        )
        if synth_file.exists():
            site_summaries[site_dir.name] = synth_file.read_text(encoding="utf-8")

    if not site_summaries:
        return ""

    client = _get_client(config)
    model = config.xai_model_for("site")
    synthesis = _call_grok(
        client,
        site_topic_synthesis_prompt(topic, site_summaries),
        model=model,
        tracker=tracker,
        call_type="site_topic_synthesis",
    )
    write_markdown_artifact(
        config.topic_dir(topic),
        "topic_synthesis",
        synthesis,
        identity=topic,
        frontmatter=base_frontmatter(
            artifact_type="topic-synthesis",
            title=f"Topic synthesis: {topic}",
            topic=topic,
            source="distill",
            tags=tags_for(topic, "website"),
            confidence="corpus-consensus",
            extra={"legacy_filename": "topic_synthesis.md"},
        ),
    )
    return synthesis
