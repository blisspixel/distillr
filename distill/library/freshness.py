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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from distill.library.insights import (
    discover_insights,
    insight_candidate_paths,
    read_discovered_insight,
)
from distill.library.paths import artifact_filename, extract_frontmatter, legacy_artifact_path

__all__ = [
    "SynthesisFreshness",
    "collect_synthesis_freshness",
]

# Topic-level synthesis kinds checked for source-relative freshness, each
# scoped to the source subtree it actually synthesizes (``None`` = the whole
# topic). Without the scoping, a paper synthesis would read "stale" the moment
# a video landed -- caught live on the dogfood library. Per-site syntheses live
# below ``sites/``; the root site synthesis is the cross-site rollup tracked
# here. Reports are terminal artifacts and do not belong here.
_SYNTHESIS_KINDS: dict[str, tuple[str, ...] | None] = {
    "topic_synthesis": ("channels",),
    "site_synthesis": ("sites",),
    "corpus_synthesis": None,
    "paper_synthesis": ("papers",),
}

# Insights are written before the synthesis in the same run, and cloud-sync
# tools can rewrite mtimes minutes apart; only a gap beyond this is staleness.
_FRESHNESS_TOLERANCE = timedelta(hours=1)
CLAIMS_DERIVED_DIRTY = ".distill-claims-derived-dirty"


@dataclass(frozen=True)
class SynthesisFreshness:
    """Whether each synthesis is current with the sources underneath it."""

    checked: int = 0  # syntheses present and compared
    stale: list[dict[str, Any]] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] dataclass default_factory appears as list[Unknown] under strict; usage confirms list[dict] -- {synthesis, behind, gap_days}
    shadowed_legacy: list[dict[str, Any]] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] dataclass default_factory appears as list[Unknown] under strict; usage confirms list[dict] -- {active, legacy}
    unknown: tuple[str, ...] = ()

    @property
    def current(self) -> int:
        return self.checked - len(self.stale) - len(self.unknown)


@dataclass(frozen=True)
class _ArtifactTime:
    instant: datetime
    explicit: bool
    timezone_known: bool = True


def _artifact_timestamp(path: Path, content: str | None = None) -> _ArtifactTime | None:
    """Best timestamp for an artifact: frontmatter ``generated_at``, else mtime."""
    if content is None:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return None
    recorded = extract_frontmatter(content).get("generated_at", "")
    if recorded:
        try:
            instant = datetime.fromisoformat(recorded.replace("Z", "+00:00"))
            if instant.tzinfo is None:
                return _ArtifactTime(
                    instant.replace(tzinfo=UTC), explicit=True, timezone_known=False
                )
            return _ArtifactTime(instant.astimezone(UTC), explicit=True)
        except ValueError:
            return None
    try:
        return _ArtifactTime(datetime.fromtimestamp(path.stat().st_mtime, UTC), explicit=False)
    except OSError:
        return None


def _timed_insights(topic_dir: Path) -> list[tuple[str, _ArtifactTime | None]]:
    timed_insights: list[tuple[str, _ArtifactTime | None]] = []
    refs = discover_insights(topic_dir)
    for ref in refs:
        content = read_discovered_insight(ref, topic_dir.parent.parent)
        timestamp = _artifact_timestamp(ref.path, content) if content is not None else None
        timed_insights.append((ref.path.relative_to(topic_dir).parts[0], timestamp))
    readable = {ref.path for ref in refs}
    for path in insight_candidate_paths(topic_dir):
        if path not in readable:
            timed_insights.append((path.relative_to(topic_dir).parts[0], None))
    return timed_insights


def collect_synthesis_freshness(topic_dir: Path, topic: str) -> SynthesisFreshness:
    """Compare each synthesis with its scoped inputs and retain unknown evidence."""
    timed_insights = _timed_insights(topic_dir)

    checked = 0
    stale: list[dict[str, Any]] = []
    shadowed: list[dict[str, Any]] = []
    unknown: list[str] = []
    for kind, scope in _SYNTHESIS_KINDS.items():
        modern = topic_dir / artifact_filename(topic, kind)
        legacy = legacy_artifact_path(topic_dir, kind)
        if modern.exists() and legacy.exists():
            shadowed.append({"active": modern.name, "legacy": legacy.name})
        active = modern if modern.exists() else legacy
        if not active.exists():
            continue
        checked += 1
        if kind == "corpus_synthesis" and (topic_dir / CLAIMS_DERIVED_DIRTY).exists():
            unknown.append(active.name)
            continue
        scoped_times = [t for top, t in timed_insights if scope is None or top in scope]
        synth_time = _artifact_timestamp(active)
        if synth_time is None or not scoped_times or any(t is None for t in scoped_times):
            unknown.append(active.name)
            continue
        if any(
            t is not None and t.timezone_known != synth_time.timezone_known for t in scoped_times
        ):
            unknown.append(active.name)
            continue
        newer = [
            t.instant
            for t in scoped_times
            if t is not None
            and t.instant - synth_time.instant
            > (timedelta(0) if t.explicit and synth_time.explicit else _FRESHNESS_TOLERANCE)
        ]
        if newer:
            stale.append(
                {
                    "synthesis": active.name,
                    "behind": len(newer),
                    "gap_days": (max(newer) - synth_time.instant).days,
                }
            )
    return SynthesisFreshness(
        checked=checked, stale=stale, shadowed_legacy=shadowed, unknown=tuple(unknown)
    )
