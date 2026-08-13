# pyright: strict
"""Canonical report profile names and capabilities."""

from __future__ import annotations

from enum import StrEnum

__all__ = ["ReportProfileName", "parse_report_profile", "profile_requires_gemini"]


class ReportProfileName(StrEnum):
    """Supported research and writing paths behind the report facade."""

    CORPUS_REPORT = "corpus-report"
    ACCORDION = "accordion"
    DEEP_RESEARCH = "deep-research"


_PROFILE_ALIASES: dict[str, ReportProfileName] = {
    "corpus": ReportProfileName.CORPUS_REPORT,
    "corpus-report": ReportProfileName.CORPUS_REPORT,
    "accordion": ReportProfileName.ACCORDION,
    "deep-research": ReportProfileName.DEEP_RESEARCH,
    "legacy": ReportProfileName.DEEP_RESEARCH,
}


def parse_report_profile(value: ReportProfileName | str) -> ReportProfileName:
    """Normalize one public report profile name."""

    if isinstance(value, ReportProfileName):
        return value
    normalized = value.strip().casefold().replace("_", "-")
    try:
        return _PROFILE_ALIASES[normalized]
    except KeyError as exc:
        choices = ", ".join(profile.value for profile in ReportProfileName)
        raise ValueError(f"unknown report profile '{value}'; choose one of: {choices}") from exc


def profile_requires_gemini(profile: ReportProfileName | str) -> bool:
    """Return whether the profile always submits a Gemini Deep Research job."""

    return parse_report_profile(profile) is not ReportProfileName.CORPUS_REPORT
