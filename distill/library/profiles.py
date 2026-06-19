"""Versioned recurring research profile schema."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from distill.library.paths import sanitize_topic

__all__ = [
    "PROFILE_SCHEMA_VERSION",
    "CostMode",
    "FeedSource",
    "FreshnessPolicy",
    "OutputPreferences",
    "ProfileLimits",
    "ProfileValidationError",
    "ResearchProfile",
    "SourceSet",
    "YouTubeChannelSource",
    "find_research_profile",
    "load_research_profile",
    "profile_path",
]

PROFILE_SCHEMA_VERSION = "research-profile.v1"
CostMode = Literal["auto", "no-metered", "paid-ok"]
Cadence = Literal["manual", "hourly", "daily", "weekly"]

_HTTP_SCHEMES = {"http", "https"}
_ISO_DURATION_RE = re.compile(r"^P(?:(?:\d+D)(?:T\d+H)?|T\d+H)$")
_PROFILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class ProfileValidationError(ValueError):
    """A research profile could not be parsed or validated."""


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def _require_non_empty(value: object, field_name: str) -> str:
    text = _clean(value)
    if not text:
        raise ValueError(f"{field_name} cannot be empty")
    return text


def _validate_http_url(value: object, field_name: str) -> str:
    text = _require_non_empty(value, field_name)
    parsed = urlparse(text)
    if parsed.scheme.lower() not in _HTTP_SCHEMES or not parsed.netloc:
        raise ValueError(f"{field_name} must be an http or https URL")
    return text


def _normalize_domain(value: object) -> str:
    text = _require_non_empty(value, "domain")
    parsed = urlparse(text if "://" in text else f"https://{text}")
    host = parsed.netloc.lower().removeprefix("www.")
    if not host or "/" in host or host.startswith(".") or host.endswith("."):
        raise ValueError("domain must be a hostname")
    if parsed.path not in {"", "/"}:
        raise ValueError("domain must not include a path")
    return host


def _normalize_repository(value: object) -> str:
    text = _require_non_empty(value, "repository")
    if text.startswith(("http://", "https://")):
        parsed = urlparse(text)
        if parsed.netloc.lower().removeprefix("www.") != "github.com":
            raise ValueError("repository URL must point to github.com")
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2:
            text = f"{parts[0]}/{parts[1]}"
    if not _REPO_RE.fullmatch(text):
        raise ValueError("repository must use owner/name")
    return text


def _validate_relative_path(value: object) -> str:
    text = _require_non_empty(value, "goal_file")
    normalized = text.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError("goal_file must be relative")
    parts = PurePosixPath(normalized).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("goal_file must not contain traversal segments")
    return normalized


class YouTubeChannelSource(BaseModel):
    """One YouTube source, identified by channel id, handle, or URL."""

    model_config = ConfigDict(extra="forbid")

    channel_id: str = ""
    handle: str = ""
    url: str = ""
    label: str = ""

    @field_validator("channel_id", "handle", "url", "label", mode="before")
    @classmethod
    def _clean_optional(cls, value: object) -> str:
        return _clean(value)

    @field_validator("handle")
    @classmethod
    def _normalize_handle(cls, value: str) -> str:
        if value and not value.startswith("@"):
            return f"@{value}"
        return value

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        if value:
            return _validate_http_url(value, "youtube channel url")
        return value

    @model_validator(mode="after")
    def _has_identifier(self) -> YouTubeChannelSource:
        if not (self.channel_id or self.handle or self.url):
            raise ValueError("youtube channel needs channel_id, handle, or url")
        return self


class FeedSource(BaseModel):
    """One RSS or Atom feed source."""

    model_config = ConfigDict(extra="forbid")

    url: str
    label: str = ""

    @field_validator("url", mode="before")
    @classmethod
    def _validate_url(cls, value: object) -> str:
        return _validate_http_url(value, "feed url")

    @field_validator("label", mode="before")
    @classmethod
    def _clean_label(cls, value: object) -> str:
        return _clean(value)


class SourceSet(BaseModel):
    """Trusted source declarations for a recurring profile."""

    model_config = ConfigDict(extra="forbid")

    youtube_channels: list[YouTubeChannelSource] = Field(default_factory=list)
    feeds: list[FeedSource] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    repositories: list[str] = Field(default_factory=list)

    @field_validator("youtube_channels", mode="before")
    @classmethod
    def _coerce_youtube_channels(cls, value: object) -> object:
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        channels: list[object] = []
        for item in value:
            if isinstance(item, str):
                text = item.strip()
                if text.startswith(("http://", "https://")):
                    channels.append({"url": text})
                elif text.startswith("UC"):
                    channels.append({"channel_id": text})
                else:
                    channels.append({"handle": text})
            else:
                channels.append(item)
        return channels

    @field_validator("feeds", mode="before")
    @classmethod
    def _coerce_feeds(cls, value: object) -> object:
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        return [{"url": item} if isinstance(item, str) else item for item in value]

    @field_validator("domains", mode="before")
    @classmethod
    def _clean_domains(cls, value: object) -> object:
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        return [_normalize_domain(item) for item in value]

    @field_validator("repositories", mode="before")
    @classmethod
    def _clean_repositories(cls, value: object) -> object:
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        return [_normalize_repository(item) for item in value]

    @property
    def source_count(self) -> int:
        return (
            len(self.youtube_channels)
            + len(self.feeds)
            + len(self.domains)
            + len(self.repositories)
        )


class FreshnessPolicy(BaseModel):
    """How often a profile is expected to be refreshed."""

    model_config = ConfigDict(extra="forbid")

    cadence: Cadence = "manual"
    stale_after: str = "P7D"

    @field_validator("stale_after")
    @classmethod
    def _validate_stale_after(cls, value: str) -> str:
        text = _require_non_empty(value, "stale_after")
        if not _ISO_DURATION_RE.fullmatch(text) or text == "P":
            raise ValueError("stale_after must be an ISO-8601 day or hour duration")
        return text


class OutputPreferences(BaseModel):
    """Which derived artifacts a profile run should prefer."""

    model_config = ConfigDict(extra="forbid")

    summary: bool = True
    trend_notes: bool = True
    okf_export: bool = False


class ProfileLimits(BaseModel):
    """Bounded run limits for a recurring profile."""

    model_config = ConfigDict(extra="forbid")

    max_new_items: int = Field(default=25, ge=1)
    max_metered_usd: float = Field(default=0.0, ge=0.0)


class ResearchProfile(BaseModel):
    """A saved recurring research plan."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["research-profile.v1"]
    name: str
    topic: str
    goal_file: str
    cost_mode: CostMode = "auto"
    description: str = ""
    freshness: FreshnessPolicy = Field(default_factory=FreshnessPolicy)
    sources: SourceSet = Field(default_factory=SourceSet)
    queries: list[str] = Field(default_factory=list)
    outputs: OutputPreferences = Field(default_factory=OutputPreferences)
    limits: ProfileLimits = Field(default_factory=ProfileLimits)

    @field_validator("name", mode="before")
    @classmethod
    def _validate_name(cls, value: object) -> str:
        text = _require_non_empty(value, "name")
        if not _PROFILE_NAME_RE.fullmatch(text):
            raise ValueError("name must be a lowercase slug")
        return text

    @field_validator("topic", mode="before")
    @classmethod
    def _validate_topic(cls, value: object) -> str:
        text = _require_non_empty(value, "topic")
        safe = sanitize_topic(text)
        if safe != text:
            raise ValueError("topic must already be a safe topic slug")
        return text

    @field_validator("goal_file", mode="before")
    @classmethod
    def _validate_goal_file(cls, value: object) -> str:
        return _validate_relative_path(value)

    @field_validator("description", mode="before")
    @classmethod
    def _clean_description(cls, value: object) -> str:
        return _clean(value)

    @field_validator("queries", mode="before")
    @classmethod
    def _clean_queries(cls, value: object) -> object:
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        return [_require_non_empty(item, "query") for item in value]

    @model_validator(mode="after")
    def _validate_profile(self) -> ResearchProfile:
        if self.sources.source_count == 0 and not self.queries:
            raise ValueError("profile must include at least one source or query")
        if self.cost_mode == "no-metered" and self.limits.max_metered_usd != 0:
            raise ValueError("no-metered profiles must set limits.max_metered_usd to 0")
        return self


def load_research_profile(path: Path) -> ResearchProfile:
    """Load one research profile YAML file."""

    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ProfileValidationError(f"Could not read profile {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ProfileValidationError(f"Invalid YAML in profile {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProfileValidationError(f"Profile {path} must contain a YAML mapping")
    try:
        return ResearchProfile.model_validate(payload)
    except ValidationError as exc:
        raise ProfileValidationError(f"Invalid profile {path}: {exc}") from exc


def profile_path(library_dir: Path, name: str) -> Path:
    """Return the canonical profile path for a profile name."""

    safe = sanitize_topic(name)
    return library_dir / "profiles" / f"{safe}.yaml"


def find_research_profile(library_dir: Path, name_or_path: str) -> Path:
    """Resolve an explicit path or a profile name under ``library/profiles``."""

    candidate = Path(name_or_path)
    if candidate.exists():
        return candidate
    if candidate.suffix.lower() in {".yaml", ".yml"}:
        if len(candidate.parts) == 1 and not candidate.is_absolute():
            return library_dir / "profiles" / candidate.name
        return candidate
    for suffix in (".yaml", ".yml"):
        path = library_dir / "profiles" / f"{sanitize_topic(name_or_path)}{suffix}"
        if path.exists():
            return path
    return profile_path(library_dir, name_or_path)
