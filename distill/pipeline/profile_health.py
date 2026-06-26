"""Deterministic health checks for recurring research profiles."""

# pyright: strict

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from distill.library.profiles import ProfileValidationError, ResearchProfile, load_research_profile

__all__ = ["ProfileHealth", "collect_profile_health", "render_profile_health_section"]


@dataclass(frozen=True)
class ProfileHealth:
    """Library-wide recurring profile status from local files and run state."""

    checked: int = 0
    invalid: list[dict[str, str]] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] dataclass default_factory appears as list[Unknown] under strict; usage confirms list[dict[str, str]]
    missing_goal: list[dict[str, str]] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] dataclass default_factory appears as list[Unknown] under strict; usage confirms list[dict[str, str]]
    never_run: list[dict[str, str]] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] dataclass default_factory appears as list[Unknown] under strict; usage confirms list[dict[str, str]]
    stale: list[dict[str, str]] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] dataclass default_factory appears as list[Unknown] under strict; usage confirms list[dict[str, str]]
    last_failed: list[dict[str, str]] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] dataclass default_factory appears as list[Unknown] under strict; usage confirms list[dict[str, str]]
    invalid_state: list[dict[str, str]] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] dataclass default_factory appears as list[Unknown] under strict; usage confirms list[dict[str, str]]
    thin_corpus: list[dict[str, str]] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] dataclass default_factory appears as list[Unknown] under strict; usage confirms list[dict[str, str]]

    @property
    def issue_count(self) -> int:
        return (
            len(self.invalid)
            + len(self.missing_goal)
            + len(self.never_run)
            + len(self.stale)
            + len(self.last_failed)
            + len(self.invalid_state)
            + len(self.thin_corpus)
        )


def collect_profile_health(library_dir: Path, *, now: datetime | None = None) -> ProfileHealth:
    """Inspect recurring profile files and run state without network access."""

    profiles_dir = library_dir / "profiles"
    if not profiles_dir.is_dir():
        return ProfileHealth()

    now = now or datetime.now(UTC)
    profiles = [
        _collect_profile_file_health(path, library_dir=library_dir, now=now)
        for path in sorted(profiles_dir.glob("*.y*ml"), key=lambda p: p.name.lower())
    ]
    return _merge_profile_health(profiles)


def render_profile_health_section(profile_health: ProfileHealth) -> list[str]:
    lines = [
        "## Recurring profile health",
        "",
        f"- Profiles checked: {profile_health.checked}",
    ]
    if profile_health.issue_count == 0:
        return [*lines, "- No recurring profile findings."]

    groups = [
        ("Invalid profile files", profile_health.invalid, "detail"),
        ("Missing goal files", profile_health.missing_goal, "goal_file"),
        ("Profiles never run", profile_health.never_run, "path"),
        ("Stale profile runs", profile_health.stale, "last_run_at"),
        ("Profiles with recorded failures", profile_health.last_failed, "failures"),
        ("Invalid profile run state", profile_health.invalid_state, "detail"),
        ("Profiles with thin local corpus", profile_health.thin_corpus, "topic"),
    ]
    for title, items, detail_key in groups:
        if not items:
            continue
        lines += ["", f"### {title}", ""]
        for item in items:
            detail = item.get(detail_key, "")
            lines.append(f"- `{item.get('profile', '')}`: {detail}")
    return lines


def _merge_profile_health(items: list[ProfileHealth]) -> ProfileHealth:
    return ProfileHealth(
        checked=sum(item.checked for item in items),
        invalid=[finding for item in items for finding in item.invalid],
        missing_goal=[finding for item in items for finding in item.missing_goal],
        never_run=[finding for item in items for finding in item.never_run],
        stale=[finding for item in items for finding in item.stale],
        last_failed=[finding for item in items for finding in item.last_failed],
        invalid_state=[finding for item in items for finding in item.invalid_state],
        thin_corpus=[finding for item in items for finding in item.thin_corpus],
    )


def _collect_profile_file_health(path: Path, *, library_dir: Path, now: datetime) -> ProfileHealth:
    rel_path = _library_relative(path, library_dir)
    try:
        profile = load_research_profile(path)
    except ProfileValidationError as exc:
        return ProfileHealth(invalid=[{"profile": path.stem, "path": rel_path, "detail": str(exc)}])

    return ProfileHealth(
        checked=1,
        missing_goal=_profile_goal_findings(profile.name, profile.goal_file, rel_path, library_dir),
        thin_corpus=_profile_corpus_findings(profile, library_dir),
        **_profile_state_findings(profile, library_dir=library_dir, now=now),
    )


def _profile_goal_findings(
    profile_name: str,
    goal_file: str,
    rel_path: str,
    library_dir: Path,
) -> list[dict[str, str]]:
    if (library_dir / goal_file).exists():
        return []
    return [{"profile": profile_name, "path": rel_path, "goal_file": goal_file}]


def _profile_corpus_findings(profile: ResearchProfile, library_dir: Path) -> list[dict[str, str]]:
    from distill.library.claude_md import count_topic_sources

    topic = profile.topic
    topic_dir = library_dir / "topics" / topic
    try:
        source_total = count_topic_sources(topic_dir)["total"] if topic_dir.is_dir() else 0
    except OSError:
        source_total = 0
    planned_sources = profile.sources.source_count + len(profile.queries)
    if not planned_sources or source_total:
        return []
    return [
        {
            "profile": profile.name,
            "topic": topic,
            "planned_sources": str(planned_sources),
        }
    ]


def _profile_state_findings(
    profile: ResearchProfile, *, library_dir: Path, now: datetime
) -> dict[str, list[dict[str, str]]]:
    from distill.pipeline.profile_run import profile_run_state_path

    state_path = profile_run_state_path(library_dir, profile.name)
    state = _load_profile_state(state_path)
    expects_run = profile.freshness.cadence != "manual"
    if state is None:
        return {
            "never_run": _profile_never_run_findings(profile, state_path, library_dir, expects_run),
        }
    if not isinstance(state, dict):
        return {
            "invalid_state": [
                {
                    "profile": profile.name,
                    "path": _library_relative(state_path, library_dir),
                    "detail": "state is not a JSON object",
                }
            ]
        }
    state = cast("dict[str, Any]", state)
    state_error = state.get("__invalid_state_error")
    if state_error:
        return {
            "invalid_state": [
                {
                    "profile": profile.name,
                    "path": _library_relative(state_path, library_dir),
                    "detail": str(state_error),
                }
            ]
        }
    return {
        "last_failed": _profile_failure_findings(profile, state, state_path, library_dir),
        "stale": _profile_stale_findings(profile, state, now=now),
    }


def _profile_never_run_findings(
    profile: ResearchProfile,
    state_path: Path,
    library_dir: Path,
    expects_run: bool,
) -> list[dict[str, str]]:
    if not expects_run:
        return []
    return [
        {
            "profile": profile.name,
            "path": _library_relative(state_path, library_dir),
        }
    ]


def _profile_failure_findings(
    profile: ResearchProfile,
    state: dict[str, Any],
    state_path: Path,
    library_dir: Path,
) -> list[dict[str, str]]:
    failures = state.get("last_failure")
    if not isinstance(failures, dict) or not failures:
        return []
    failures = cast("dict[str, Any]", failures)
    return [
        {
            "profile": profile.name,
            "path": _library_relative(state_path, library_dir),
            "failures": str(len(failures)),
        }
    ]


def _profile_stale_findings(
    profile: ResearchProfile,
    state: dict[str, Any],
    *,
    now: datetime,
) -> list[dict[str, str]]:
    if profile.freshness.cadence == "manual":
        return []
    last_run_at = str(state.get("last_run_at", ""))
    if not _profile_is_stale(last_run_at, profile.freshness.stale_after, now=now):
        return []
    return [
        {
            "profile": profile.name,
            "last_run_at": last_run_at or "never",
            "stale_after": profile.freshness.stale_after,
        }
    ]


def _load_profile_state(path: Path) -> object | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"__invalid_state_error": str(exc)}


def _profile_is_stale(last_run_at: str, stale_after: str, *, now: datetime) -> bool:
    last_run = _parse_profile_time(last_run_at)
    if last_run is None:
        return True
    return now - last_run > _parse_profile_duration(stale_after)


def _parse_profile_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def _parse_profile_duration(value: str) -> timedelta:
    match = re.fullmatch(r"P(?:(?P<days>\d+)D(?:T(?P<day_hours>\d+)H)?|T(?P<hours>\d+)H)", value)
    if match is None:
        return timedelta(days=7)
    days = int(match.group("days") or 0)
    hours = int(match.group("day_hours") or match.group("hours") or 0)
    return timedelta(days=days, hours=hours)


def _library_relative(path: Path, library_dir: Path) -> str:
    try:
        return path.relative_to(library_dir).as_posix()
    except ValueError:
        return str(path)
