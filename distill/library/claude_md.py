"""Generate agent-orientation ``CLAUDE.md`` + ``AGENTS.md`` for the library and topics.

Distillr is the persistent research corpus for AI agent workflows. The MCP
server makes the corpus queryable for agents that speak MCP, but a large
fraction of real agent traffic auto-loads an orientation file from the working
directory - and the convention split by vendor: Claude Code reads ``CLAUDE.md``;
Codex, Cursor, Gemini CLI and the 30+ tools on the cross-vendor AGENTS.md
standard read ``AGENTS.md`` (and ignore ``CLAUDE.md``). An agent that ``cd``s
into a topic directory should get immediate orientation regardless of harness,
so every write emits the same rendered content under **both** filenames.
(Identical copies rather than an ``@AGENTS.md`` import shim: copies are
self-contained in tools that don't follow imports, and the files are
regenerated, never hand-maintained, so duplication costs nothing.)

This module writes those orientation files:

- ``library/topics/<topic>/CLAUDE.md`` + ``AGENTS.md`` summarize one topic's corpus.
- ``library/CLAUDE.md`` + ``AGENTS.md`` index every topic, one line each.

Design discipline (foundational layer, same as the rest of ``distill.library``):

- Pure templating over artifacts the library already produces. No LLM calls, no
  network, no new dependencies, no cost.
- Reads the concept/entity rollups (``concepts.jsonl`` / ``entities.jsonl``) as
  raw JSON via stdlib, rather than importing ``distill.concepts`` -- so this
  module stays inside the foundational layer the import-linter contracts pin.
- Render functions take an injected ``now_iso`` so tests are deterministic; the
  thin write wrappers stamp the current time at the call site.
"""

# pyright: strict

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from distill.library.freshness import collect_synthesis_freshness
from distill.library.paths import atomic_write_text, find_artifact, strip_frontmatter

__all__ = [
    "MCP_TOOLS",
    "count_topic_sources",
    "render_library_claude_md",
    "render_topic_claude_md",
    "top_named_things",
    "topic_summary_line",
    "write_library_claude_md",
    "write_topic_claude_md",
]

# Canonical read-surface MCP tools advertised in every CLAUDE.md, so an agent
# that auto-loads the file knows the structured query layer exists alongside the
# filesystem. The rollup filenames below (concepts.jsonl / entities.jsonl) are
# the same ones distill.concepts.exports writes; named here as literals to keep
# this module inside the foundational layer.
MCP_TOOLS: tuple[tuple[str, str], ...] = (
    ("list_topics(limit=50)", "list available corpus topics before choosing a topic-scoped tool"),
    ("find_insights(topic, query)", "semantic search across the topic's per-source insights"),
    ("read_insight(path, section=None)", "read one insight file, optionally a single section"),
    (
        "find_concepts(topic, query='', kind='', contested_only=False)",
        "query the concept/entity playbook",
    ),
    ("read_concept(path)", "read one concept or entity note"),
    ("research_gaps(topic)", "what the corpus is thin on, plus suggested next actions"),
    ("concept_history(topic, slug)", "version history of a concept note"),
    ("concept_diff(topic, slug, ts_a='', ts_b='')", "structured diff of a note across versions"),
)

# Insight artifact filename patterns, modern and legacy. Modern writes use
# ``<slug>_Insights.md``; pre-0.7 libraries used bare ``insights.md`` and scan
# artifacts used lowercase ``*_insights.md`` (which ``rglob`` matches
# case-insensitively on Windows but not on Linux -- list it explicitly so
# counts agree across platforms). Counting dedups by parent directory, so the
# overlapping patterns cannot double-count a source.
_INSIGHT_GLOBS: tuple[str, ...] = ("*_Insights.md", "*_insights.md", "insights.md")
_SKIP_TOP_DIRS = frozenset({"concepts", "entities"})
_CONCEPTS_JSONL = "concepts.jsonl"
_ENTITIES_JSONL = "entities.jsonl"

# Synthesis section headings that are not useful as a one-line summary -- when
# the lede is exactly one of these (no topic-specific tail), keep scanning for
# the first real sentence. Matched case-folded against the cleaned line.
_GENERIC_HEADERS = frozenset(
    {
        "where they agree",
        "where they disagree",
        "where the sources agree",
        "where the sources disagree",
        "where the sources reinforce each other",
        "where the sources diverge",
        "synthesis",
        "overview",
        "summary",
        "introduction",
        "key takeaways",
        "takeaways",
    }
)
_GENERATED_NOTE = "<!-- Regenerated on every topic refresh. Do not edit by hand. -->"


# ---- source counting -------------------------------------------------------


def count_topic_sources(topic_dir: Path) -> dict[str, int]:
    """Count ingested sources by scanning for insight artifacts.

    One source per directory holding an insight file -- modern
    ``<slug>_Insights.md`` or the pre-0.7 legacy names (the class the
    dogfooded "0 sources" index bug hid: legacy-layout topics with real
    corpora showed empty in the library index). Buckets by the top-level
    source directory: ``papers/`` -> papers, ``channels/`` -> videos,
    ``sites/`` -> pages; anything else counts toward ``other``.
    Derived-artifact subtrees (``concepts/``, ``entities/``, any dot-prefixed
    directory such as ``.history``) are skipped, matching
    ``distill.library.insights.discover_insights``. Pure filesystem scan,
    tolerant of a missing topic directory (returns zeros).
    """
    counts = {"papers": 0, "videos": 0, "pages": 0, "other": 0, "total": 0}
    if not topic_dir.is_dir():
        return counts
    seen_dirs: set[Path] = set()
    for pattern in _INSIGHT_GLOBS:
        for insight in topic_dir.rglob(pattern):
            rel_parts = insight.relative_to(topic_dir).parts
            top = rel_parts[0] if len(rel_parts) > 1 else ""
            if top in _SKIP_TOP_DIRS or top.startswith("."):
                continue
            if insight.parent in seen_dirs:
                continue
            seen_dirs.add(insight.parent)
            if top == "papers":
                counts["papers"] += 1
            elif top == "channels":
                counts["videos"] += 1
            elif top == "sites":
                counts["pages"] += 1
            else:
                counts["other"] += 1
            counts["total"] += 1
    return counts


def _sources_phrase(counts: dict[str, int]) -> str:
    """Human-readable breakdown like ``12 sources (8 papers, 3 videos, 1 page)``."""
    parts: list[str] = []
    for key, singular in (("papers", "paper"), ("videos", "video"), ("pages", "page")):
        n = counts.get(key, 0)
        if n:
            parts.append(f"{n} {singular}{'s' if n != 1 else ''}")
    total = counts.get("total", 0)
    head = f"{total} source{'s' if total != 1 else ''}"
    return f"{head} ({', '.join(parts)})" if parts else head


# ---- topic summary ---------------------------------------------------------


def topic_summary_line(topic_dir: Path, topic: str, *, max_len: int = 200) -> str:
    """Return a one-line summary from the topic synthesis lede, or ``""``.

    Reads the topic synthesis artifact, strips frontmatter, and returns the
    first meaningful prose line with Markdown emphasis/heading markers removed.
    A leading ``Sources:`` provenance line is skipped. Returns an empty string
    when no synthesis exists yet.
    """
    synth = find_artifact(topic_dir, "topic_synthesis", identity=topic)
    if not synth.exists():
        return ""
    try:
        body = strip_frontmatter(synth.read_text(encoding="utf-8"))
    except OSError:
        return ""
    for raw in body.splitlines():
        line = raw.strip().lstrip("#>*_- ").rstrip("*_ ").strip()
        if not line or line.lower().startswith("sources:"):
            continue
        if line.casefold() in _GENERIC_HEADERS:
            continue
        if len(line) > max_len:
            line = line[: max_len - 3].rstrip() + "..."
        return line
    return ""


# ---- concept / entity names ------------------------------------------------


def _score_named_row(line: str) -> tuple[int, str] | None:
    """Parse one rollup JSONL line into ``(source_count, name)`` or ``None``.

    Skips blank lines, malformed JSON, valid-JSON-but-non-object rows (which would
    otherwise crash ``.get(...)``), and rows with no usable name.
    """
    line = line.strip()
    if not line:
        return None
    try:
        row = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(row, dict):
        return None
    row = cast("dict[str, Any]", row)
    name = str(row.get("name") or row.get("normalized_name") or "").strip()
    if not name:
        return None
    try:
        return (int(row.get("source_count", 0) or 0), name)
    except (ValueError, TypeError):
        return None


def top_named_things(jsonl_path: Path, limit: int) -> list[str]:
    """Top concept/entity display names from a rollup, by ``source_count`` desc.

    Reads the append-merged rollup as raw JSON (no ``distill.concepts``
    import), dedups case-insensitively, and returns at most ``limit`` names.
    Tolerant of a missing file or malformed lines.
    """
    if limit <= 0 or not jsonl_path.exists():
        return []
    try:
        lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    scored = [s for s in (_score_named_row(line) for line in lines) if s is not None]
    scored.sort(key=lambda r: (-r[0], r[1].lower()))
    out: list[str] = []
    seen: set[str] = set()
    for _, name in scored:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
        if len(out) >= limit:
            break
    return out


def _ask_me_about(topic_dir: Path, topic: str, *, limit: int = 6) -> list[str]:
    """Example queries from the corpus's named concepts and entities.

    Entities (people, orgs, vendors) lead because they make the most concrete
    queries; concepts fill the rest. Falls back to a generic prompt when the
    concept layer has not been built yet.
    """
    entities = top_named_things(topic_dir / _ENTITIES_JSONL, limit=3)
    concepts = top_named_things(topic_dir / _CONCEPTS_JSONL, limit=limit)
    names: list[str] = []
    seen: set[str] = set()
    for name in [*entities, *concepts]:
        key = name.lower()
        if key not in seen:
            seen.add(key)
            names.append(name)
        if len(names) >= limit:
            break
    if not names:
        return [f"What does the corpus say about {topic}?"]
    return [f"What do the sources say about {name}?" for name in names]


# ---- rendering -------------------------------------------------------------


def render_topic_claude_md(topic_dir: Path, topic: str, *, now_iso: str) -> str:
    """Render the per-topic ``CLAUDE.md`` body. Pure; reads existing artifacts."""
    summary = topic_summary_line(topic_dir, topic)
    counts = count_topic_sources(topic_dir)
    questions = _ask_me_about(topic_dir, topic)

    synth = find_artifact(topic_dir, "topic_synthesis", identity=topic)
    has_concepts = (topic_dir / _CONCEPTS_JSONL).exists() or (topic_dir / "concepts").is_dir()

    lines: list[str] = [f"# {topic} -- distillr research corpus", ""]
    if summary:
        lines += [summary, ""]
    lines += [
        f"This directory is a distillr research corpus on **{topic}**: plain-Markdown "
        "per-source insights, cross-source synthesis, and a concept/entity playbook. "
        "Every file is greppable -- no database, no schema. Read it directly "
        "(`grep`, `cat`, `ls`) or query it through distillr's MCP server.",
        "",
        "## Contents",
        "",
        f"- **{_sources_phrase(counts)}** analyzed into `_Insights.md` files under "
        "`papers/`, `channels/`, and `sites/`.",
    ]
    if synth.exists():
        lines.append(
            f"- **Topic synthesis:** [[{synth.stem}]] (`{synth.name}`) -- "
            "cross-source claims, comparisons, and named disagreements."
        )
    freshness = collect_synthesis_freshness(topic_dir, topic)
    for item in freshness.stale:
        lines.append(
            f"- **Warning -- stale synthesis:** `{item['synthesis']}` predates "
            f"{item['behind']} newer source(s) by {item['gap_days']}d; prefer the "
            f"per-source insights, or regenerate with `distill corpus {topic}`."
        )
    if has_concepts:
        lines.append(
            "- **Concept/entity playbook:** `concepts/` and `entities/` "
            f"(rollups in `{_CONCEPTS_JSONL}` / `{_ENTITIES_JSONL}`)."
        )
    lines += [f"- Last refreshed: {now_iso}", "", "## Ask me about", ""]
    lines += [f"- {q}" for q in questions]
    lines += [
        "",
        "## Querying this corpus over MCP",
        "",
        "distillr exposes the corpus to agents through these tools (`topic` is `" + topic + "`):",
        "",
    ]
    lines += [f"- `{sig}` -- {desc}" for sig, desc in MCP_TOOLS]
    lines += ["", _GENERATED_NOTE, ""]
    return "\n".join(lines)


def render_library_claude_md(topics_dir: Path, *, now_iso: str) -> str:
    """Render the library-root ``CLAUDE.md`` indexing every topic. Pure."""
    topics = _list_topics(topics_dir)
    n = len(topics)
    lines: list[str] = [
        "# distillr library",
        "",
        f"A distillr research library: {n} topic{'s' if n != 1 else ''}, each a directory "
        "of plain-Markdown per-source insights and cross-source synthesis under "
        "`topics/<name>/`. No database, no schema -- the corpus is the interface.",
        "",
        "## Topics",
        "",
    ]
    if not topics:
        lines.append(
            "_No topics yet. Run `distill papers`, `distill latest`, or "
            "`distill discover` to start one._"
        )
    for topic_dir in topics:
        topic = topic_dir.name
        counts = count_topic_sources(topic_dir)
        summary = topic_summary_line(topic_dir, topic)
        tail = f" -- {summary}" if summary else ""
        lines.append(f"- **[[{topic}]]** (`topics/{topic}/`, {_sources_phrase(counts)}){tail}")
    lines += [
        "",
        "Each topic directory has its own `CLAUDE.md` / `AGENTS.md` (identical content) "
        "with orientation and example queries. Last refreshed: " + now_iso + ".",
        "",
        _GENERATED_NOTE,
        "",
    ]
    return "\n".join(lines)


def _list_topics(topics_dir: Path) -> list[Path]:
    """Topic dirs that would get a per-topic CLAUDE.md (synthesis or sources).

    Matches :func:`write_topic_claude_md`'s skip rule so the library index and
    the per-topic files stay consistent: an index entry always points at a
    directory that has (or will have) its own ``CLAUDE.md``.
    """
    if not topics_dir.is_dir():
        return []
    out: list[Path] = []
    for child in sorted(topics_dir.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        has_synth = find_artifact(child, "topic_synthesis", identity=child.name).exists()
        if has_synth or count_topic_sources(child)["total"] > 0:
            out.append(child)
    return out


# ---- writing ---------------------------------------------------------------


def _atomic_write(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically and durably (see paths helper)."""
    atomic_write_text(path, content)


def write_topic_claude_md(topic_dir: Path, topic: str, *, now_iso: str) -> Path | None:
    """Write ``<topic_dir>/CLAUDE.md`` + ``AGENTS.md``. Returns ``None`` for an empty topic.

    A topic with no synthesis and no analyzed sources is skipped (no orphan
    orientation files). Otherwise the same rendered content is atomically
    written under both filenames (see module docstring for why identical
    copies). Returns the ``CLAUDE.md`` path for caller compatibility.
    """
    has_synth = find_artifact(topic_dir, "topic_synthesis", identity=topic).exists()
    if not has_synth and count_topic_sources(topic_dir)["total"] == 0:
        return None
    content = render_topic_claude_md(topic_dir, topic, now_iso=now_iso)
    path = topic_dir / "CLAUDE.md"
    _atomic_write(path, content)
    _atomic_write(topic_dir / "AGENTS.md", content)
    return path


def write_library_claude_md(library_dir: Path, *, now_iso: str) -> Path:
    """Write ``<library_dir>/CLAUDE.md`` + ``AGENTS.md`` indexing every topic. Always writes.

    Returns the ``CLAUDE.md`` path for caller compatibility.
    """
    content = render_library_claude_md(library_dir / "topics", now_iso=now_iso)
    path = library_dir / "CLAUDE.md"
    _atomic_write(path, content)
    _atomic_write(library_dir / "AGENTS.md", content)
    return path


def refresh_for_topic(library_dir: Path, topic_dir: Path, topic: str) -> Path | None:
    """Regenerate this topic's ``CLAUDE.md`` and the library index, stamped now.

    The production entry point for the post-refresh hook. The render/write
    functions take an explicit ``now_iso`` so tests stay deterministic; this
    wrapper stamps the current UTC time. Returns the per-topic path written (or
    ``None`` if the topic was empty and skipped).
    """
    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    topic_path = write_topic_claude_md(topic_dir, topic, now_iso=now_iso)
    write_library_claude_md(library_dir, now_iso=now_iso)
    return topic_path
