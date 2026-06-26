"""Synthesis freshness: is each synthesis current with the sources under it?

Distinct from prompt-version staleness (a newer prompt exists) and from the
dashboard's 90-day wall-clock warning: this is *relative* staleness -- a
synthesis generated before sources that now sit beneath it. A stale synthesis
is the most dangerous artifact in the corpus because it reads with the
confidence of well-written prose while silently missing everything that came
after it (the "confident misinformation" failure mode the roadmap names).

Foundational-layer module (pure filesystem reads, no LLM, no pipeline
imports) so both the audit pipeline and the orientation-file generator can
use the same collector. Timestamps come from frontmatter ``generated_at``
where stamped; cloud-sync tools rewrite mtimes wholesale, so mtime is only
the legacy fallback.
"""

# pyright: strict

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from distill.library.insights import discover_insights
from distill.library.paths import artifact_filename, extract_frontmatter, legacy_artifact_path

__all__ = [
    "SynthesisFreshness",
    "collect_synthesis_freshness",
]

# Topic-level synthesis kinds checked for source-relative freshness, each
# scoped to the source subtree it actually synthesizes (``None`` = the whole
# topic). Without the scoping, a paper synthesis would read "stale" the moment
# a video landed -- caught live on the dogfood library. Site syntheses live
# per-site, and reports are terminal artifacts; neither belongs here.
_SYNTHESIS_KINDS: dict[str, tuple[str, ...] | None] = {
    "topic_synthesis": ("channels",),
    "corpus_synthesis": None,
    "paper_synthesis": ("papers",),
}

# Insights are written before the synthesis in the same run, and cloud-sync
# tools can rewrite mtimes minutes apart; only a gap beyond this is staleness.
_FRESHNESS_TOLERANCE = timedelta(hours=1)


@dataclass(frozen=True)
class SynthesisFreshness:
    """Whether each synthesis is current with the sources underneath it."""

    checked: int = 0  # syntheses present and compared
    stale: list[dict[str, Any]] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] dataclass default_factory appears as list[Unknown] under strict; usage confirms list[dict] -- {synthesis, behind, gap_days}
    shadowed_legacy: list[dict[str, Any]] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] dataclass default_factory appears as list[Unknown] under strict; usage confirms list[dict] -- {active, legacy}


def _artifact_timestamp(path: Path) -> datetime | None:
    """Best timestamp for an artifact: frontmatter ``generated_at``, else mtime."""
    try:
        recorded = extract_frontmatter(path.read_text(encoding="utf-8")).get("generated_at", "")
    except OSError:
        return None
    if recorded:
        try:
            return datetime.fromisoformat(recorded.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None


def collect_synthesis_freshness(topic_dir: Path, topic: str) -> SynthesisFreshness:
    """Compare each synthesis's timestamp against the sources underneath it.

    Two finding classes, both caught live in the dogfood library: a synthesis
    generated before insights that now sit under it (reads confidently, missing
    everything newer), and a superseded legacy-named synthesis lingering beside
    its modern replacement (two confident syntheses, one wrong by age).
    """
    timed_insights = [
        (ref.path.relative_to(topic_dir).parts[0], t)
        for ref, t in ((ref, _artifact_timestamp(ref.path)) for ref in discover_insights(topic_dir))
        if t
    ]

    checked = 0
    stale: list[dict[str, Any]] = []
    shadowed: list[dict[str, Any]] = []
    for kind, scope in _SYNTHESIS_KINDS.items():
        modern = topic_dir / artifact_filename(topic, kind)
        legacy = legacy_artifact_path(topic_dir, kind)
        if modern.exists() and legacy.exists():
            shadowed.append({"active": modern.name, "legacy": legacy.name})
        active = modern if modern.exists() else legacy
        if not active.exists():
            continue
        checked += 1
        scoped_times = [t for top, t in timed_insights if scope is None or top in scope]
        synth_time = _artifact_timestamp(active)
        if synth_time is None or not scoped_times:
            continue
        newest_source = max(scoped_times)
        if newest_source - synth_time > _FRESHNESS_TOLERANCE:
            cutoff = synth_time + _FRESHNESS_TOLERANCE
            behind = sum(1 for t in scoped_times if t > cutoff)
            stale.append(
                {
                    "synthesis": active.name,
                    "behind": behind,
                    "gap_days": (newest_source - synth_time).days,
                }
            )
    return SynthesisFreshness(checked=checked, stale=stale, shadowed_legacy=shadowed)
