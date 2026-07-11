"""Typed record shapes for deterministic audit reports."""

# pyright: strict

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict

from distill.library.freshness import SynthesisFreshness
from distill.library.links import BrokenLink
from distill.pipeline.audit_transcripts import ThinTranscript
from distill.pipeline.audit_video_duplicates import ExactVideoDuplicateGroup
from distill.pipeline.dedup import DuplicateGroup
from distill.pipeline.profile_health import ProfileHealth

__all__ = [
    "AuditReport",
    "ContestedFinding",
    "LibraryHygiene",
    "StalePromptRecord",
    "StalenessRollup",
    "VerifyFlag",
    "VerifyRollup",
]


class VerifyFlag(TypedDict):
    insight: str
    token: str
    kind: str
    context: str


class StalePromptRecord(TypedDict):
    insight: str
    recorded: str
    current: str


class ContestedFinding(TypedDict):
    name: str
    kind: str
    helpful: int
    harmful: int
    sources: int


def _verify_flags_factory() -> list[VerifyFlag]:
    return []


def _stale_prompt_records_factory() -> list[StalePromptRecord]:
    return []


def _duplicate_groups_factory() -> list[DuplicateGroup]:
    return []


def _exact_video_duplicate_groups_factory() -> list[ExactVideoDuplicateGroup]:
    return []


def _thin_transcripts_factory() -> list[ThinTranscript]:
    return []


def _strings_factory() -> list[str]:
    return []


@dataclass(frozen=True)
class VerifyRollup:
    """Verification coverage for a topic's insights, from ``_Verify.json`` sidecars."""

    insights_total: int
    checked: int
    clean: int
    flagged: list[VerifyFlag] = field(default_factory=_verify_flags_factory)
    synthesis_total: int = 0
    synthesis_checked: int = 0
    synthesis_clean: int = 0

    @property
    def unverified(self) -> int:
        """Insights with no successful claim checks, including zero-check sidecars."""
        return self.insights_total - self.checked

    @property
    def synthesis_unverified(self) -> int:
        """Syntheses with no successful claim checks, including zero-check sidecars."""
        return self.synthesis_total - self.synthesis_checked

    @property
    def never_checked(self) -> int:
        """Compatibility alias for callers using the previous audit wording."""
        return self.unverified

    @property
    def synthesis_never_checked(self) -> int:
        """Compatibility alias for callers using the previous audit wording."""
        return self.synthesis_unverified


@dataclass(frozen=True)
class StalenessRollup:
    """Prompt-version drift across a topic's insights."""

    current: int = 0
    stale: list[StalePromptRecord] = field(default_factory=_stale_prompt_records_factory)
    unknown_family: int = 0
    no_provenance: int = 0


@dataclass(frozen=True)
class AuditReport:
    """Everything one audit run found for one topic."""

    topic: str
    health_warnings: list[str]
    contested: list[ContestedFinding]
    broken_links: list[BrokenLink]
    gaps: list[str]
    next_actions: list[str]
    verify: VerifyRollup
    staleness: StalenessRollup = field(default_factory=StalenessRollup)
    near_duplicates: list[DuplicateGroup] = field(default_factory=_duplicate_groups_factory)
    exact_video_duplicates: list[ExactVideoDuplicateGroup] = field(
        default_factory=_exact_video_duplicate_groups_factory
    )
    thin_transcripts: list[ThinTranscript] = field(default_factory=_thin_transcripts_factory)
    freshness: SynthesisFreshness = field(default_factory=SynthesisFreshness)

    @property
    def issue_count(self) -> int:
        return (
            len(self.health_warnings)
            + len(self.contested)
            + len(self.broken_links)
            + len(self.gaps)
            + len(self.verify.flagged)
            + len(self.staleness.stale)
            + len(self.near_duplicates)
            + len(self.exact_video_duplicates)
            + len(self.thin_transcripts)
            + len(self.freshness.stale)
            + len(self.freshness.shadowed_legacy)
            + self.verify.unverified
            + self.verify.synthesis_unverified
        )


@dataclass(frozen=True)
class LibraryHygiene:
    """Library-wide topic-directory status, for the end of ``audit all``."""

    healthy: int = 0
    empty: list[str] = field(default_factory=_strings_factory)
    unreadable: list[str] = field(default_factory=_strings_factory)
    unindexed: list[str] = field(default_factory=_strings_factory)
    test_named: list[str] = field(default_factory=_strings_factory)
    profiles: ProfileHealth = field(default_factory=ProfileHealth)

    @property
    def issue_count(self) -> int:
        return (
            len(self.empty) + len(self.unreadable) + len(self.unindexed) + self.profiles.issue_count
        )
