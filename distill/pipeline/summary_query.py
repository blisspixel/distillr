"""Token-bounded, cached query summaries for sub-agent consumption.

The Agent SDK sub-agent pattern delegates "answer X over corpus Y, here's
bounded context, return result" -- which needs a query primitive that fits a
sub-agent's context window instead of returning full artifact bodies. This
module is that primitive's engine: the existing lexical rank selects the
slice, one compression call summarizes it *focused on the query*, and the
result is cached by ``(topic, query, max_tokens, corpus_revision)`` so
repeated sub-agent calls don't repay the compression cost. The revision is a
hash of the matched files' identity + mtime + size -- the cache invalidates
exactly when the underlying corpus slice changes, never on a clock.
"""

# pyright: strict

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from distill.config import DistillConfig
from distill.library.paths import strip_frontmatter
from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.pipeline.search import search_corpus
from distill.prompts.summary_query import summary_query_prompt

__all__ = ["QuerySummary", "summarize_query"]

_TOP_K = 8
_MAX_SOURCE_CHARS = 8_000
_CACHE_DIRNAME = "summary_cache"


@dataclass(frozen=True)
class QuerySummary:
    """One bounded summary, with its receipts and cache provenance."""

    summary: str
    sources: list[str]  # artifact stems the summary drew from
    cached: bool
    model: str


def _corpus_revision(files: list[Path]) -> str:
    """Identity of the matched slice: path + mtime + size, order-stable."""
    h = hashlib.sha256()
    for f in sorted(files):
        try:
            st = f.stat()
            h.update(f"{f.name}|{st.st_mtime_ns}|{st.st_size}\n".encode())
        except OSError:
            h.update(f"{f.name}|gone\n".encode())
    return h.hexdigest()[:16]


def _cache_path(config: DistillConfig, key: str) -> Path:
    return config.library_dir / ".distill" / _CACHE_DIRNAME / f"{key}.json"


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

    files = [config.library_dir / r.path for r in results]
    revision = _corpus_revision(files)
    key = hashlib.sha256(f"{topic}|{query}|{max_tokens}|{revision}".encode()).hexdigest()[:20]
    cache_file = _cache_path(config, key)
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            return QuerySummary(
                summary=data["summary"],
                sources=list(data.get("sources", [])),
                cached=True,
                model=str(data.get("model", "")),
            )
        except (OSError, json.JSONDecodeError, KeyError):
            pass  # corrupt cache entry: fall through and regenerate

    blocks: list[str] = []
    stems: list[str] = []
    for f in files:
        try:
            body = strip_frontmatter(f.read_text(encoding="utf-8"))[:_MAX_SOURCE_CHARS]
        except OSError:
            continue
        stems.append(f.stem)
        blocks.append(f"[{f.stem}]\n{body}")
    if not blocks:
        return None

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
    )
    if tracker is not None:
        tracker.record(TokenUsage.from_response(response, call_type="find_summary"))
    summary = response.text.strip()
    cited = [s for s in stems if f"[{s}]" in summary] or stems

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps({"summary": summary, "sources": cited, "model": response.model}, indent=2),
        encoding="utf-8",
    )
    return QuerySummary(summary=summary, sources=cited, cached=False, model=response.model)
