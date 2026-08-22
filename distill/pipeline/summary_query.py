"""Token-bounded, cached query summaries for sub-agent consumption.

The Agent SDK sub-agent pattern delegates "answer X over corpus Y, here's
bounded context, return result" -- which needs a query primitive that fits a
sub-agent's context window instead of returning full artifact bodies. This
module is that primitive's engine: the existing lexical rank selects the
slice, one compression call summarizes it *focused on the query*, and the
result is cached by ``(topic, query, max_tokens, corpus_revision)`` so
repeated sub-agent calls don't repay the compression cost. The revision is a
hash of the ordered matched files' relative paths and exact bounded bodies, so
the cache invalidates when the text supplied as model context changes, never on a clock
or a racy pre-read metadata snapshot.
"""

# pyright: strict

from __future__ import annotations

import hashlib
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from distill.config import DistillConfig
from distill.library.paths import atomic_write_json, strip_frontmatter
from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
from distill.parsing import read_bounded_json_object
from distill.pipeline.citation_refs import (
    citation_refusal_reason,
    extract_source_citations,
)
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.pipeline.search import read_search_result, search_corpus
from distill.prompts.summary_query import summary_query_prompt

__all__ = ["QuerySummary", "summarize_query"]

_TOP_K = 8
_MAX_SOURCE_CHARS = 8_000
_CACHE_DIRNAME = "summary_cache"
_MAX_CACHE_BYTES = 1024 * 1024


@dataclass(frozen=True)
class QuerySummary:
    """One bounded summary, with its receipts and cache provenance."""

    summary: str
    sources: list[str]  # artifact stems the summary drew from
    cached: bool
    model: str
    refused_reason: str = ""


def _corpus_revision(sources: list[tuple[str, str]]) -> str:
    """Hash the ordered path and bounded-body pairs supplied as model context."""
    h = hashlib.sha256()
    for source_path, content in sources:
        path_bytes = source_path.encode()
        content_bytes = content.encode()
        h.update(len(path_bytes).to_bytes(8, "big"))
        h.update(path_bytes)
        h.update(len(content_bytes).to_bytes(8, "big"))
        h.update(content_bytes)
    return h.hexdigest()[:16]


def _cache_path(config: DistillConfig, key: str) -> Path:
    return config.library_dir / ".distill" / _CACHE_DIRNAME / f"{key}.json"


def _cited_sources(summary: str, allowed_stems: list[str]) -> tuple[list[str], str]:
    citations = extract_source_citations(summary)
    cited = [citation for citation in citations if citation in allowed_stems]
    refusal = citation_refusal_reason(
        citations,
        cited,
        allowed_stems,
        subject="summary",
        action="cache",
    )
    return cited, refusal


def _load_cached_summary(cache_file: Path, allowed_stems: list[str]) -> QuerySummary | None:
    row = read_bounded_json_object(cache_file, max_bytes=_MAX_CACHE_BYTES)
    summary_value = row.get("summary")
    if not isinstance(summary_value, str):
        raise ValueError("summary cache row is missing a string summary")
    cited, refusal = _cited_sources(summary_value, allowed_stems)
    if refusal:
        return None
    model_value = row.get("model", "")
    return QuerySummary(
        summary=summary_value,
        sources=cited,
        cached=True,
        model=model_value if isinstance(model_value, str) else "",
    )


def summarize_query(
    config: DistillConfig,
    topic: str,
    query: str,
    *,
    max_tokens: int = 4000,
    tracker: CostTracker | None = None,
) -> QuerySummary | None:
    """Summarize the topic's best-matching insights, focused on *query*.

    Returns ``None`` when nothing in the topic matches. A cache hit costs
    nothing and makes no model call.
    """
    results = search_corpus(config, topic, query, limit=_TOP_K)
    if not results:
        return None

    files = [config.library_dir / result.path for result in results]

    blocks: list[str] = []
    stems: list[str] = []
    revision_sources: list[tuple[str, str]] = []
    for result, source_file in zip(results, files, strict=True):
        source_text = read_search_result(config, result)
        if source_text is None:
            continue
        body = strip_frontmatter(source_text)[:_MAX_SOURCE_CHARS]
        stems.append(source_file.stem)
        blocks.append(f"[{source_file.stem}]\n{body}")
        revision_sources.append((result.path, body))
    if not blocks:
        return None

    revision = _corpus_revision(revision_sources)
    key = hashlib.sha256(f"{topic}|{query}|{max_tokens}|{revision}".encode()).hexdigest()[:20]
    cache_file = _cache_path(config, key)
    if cache_file.exists():
        with suppress(OSError, RecursionError, UnicodeError, ValueError):
            cached_summary = _load_cached_summary(cache_file, stems)
            if cached_summary is not None:
                return cached_summary
        with suppress(OSError):
            cache_file.unlink()

    rc = RouterConfig()
    response = llm_call(
        rc,
        workload_tag="site",
        prompt=summary_query_prompt(
            topic=topic,
            query=query,
            max_words=max(150, int(max_tokens * 0.7)),
            sources_block="\n\n---\n\n".join(blocks),
        ),
        call_type="find_summary",
        usage_tracker=tracker,
    )
    if tracker is not None:
        tracker.record(TokenUsage.from_response(response, call_type="find_summary"))
    summary = response.text.strip()
    cited, refusal = _cited_sources(summary, stems)
    if refusal:
        return QuerySummary(
            summary=summary,
            sources=cited,
            cached=False,
            model=response.model,
            refused_reason=refusal,
        )

    atomic_write_json(
        cache_file,
        {"summary": summary, "sources": cited, "model": response.model},
    )
    return QuerySummary(summary=summary, sources=cited, cached=False, model=response.model)
