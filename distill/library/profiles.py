"""Versioned recurring research profile schema."""

# pyright: strict

from __future__ import annotations

import ipaddress
import re
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import Literal, cast
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from distill.library.paths import sanitize_path_component, sanitize_topic
from distill.parsing import (
    MAX_ASCII_UINT_DIGITS,
    MAX_LOOKBACK_DAYS,
    parse_iso_day_hour_duration,
)
from distill.youtube_urls import normalize_youtube_channel_url

__all__ = [
    "MAX_LIBRARY_PROFILES",
    "MAX_PROFILE_DECLARATIONS",
    "MAX_PROFILE_NEW_ITEMS",
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
    "list_research_profile_paths",
    "load_research_profile",
    "profile_path",
]

PROFILE_SCHEMA_VERSION = "research-profile.v1"
MAX_PROFILE_NEW_ITEMS = 1_000
MAX_PROFILE_DECLARATIONS = 100
MAX_LIBRARY_PROFILES = 200
_MAX_PROFILE_FILE_BYTES = 1_000_000
_MAX_PROFILE_YAML_NODES = 100_000
_MAX_SLUG_CHARS = 100
_MAX_GOAL_PATH_CHARS = 512
_MAX_URL_CHARS = 2_048
_MAX_LABEL_CHARS = 256
_MAX_QUERY_CHARS = 1_000
_MAX_DESCRIPTION_CHARS = 4_000
_MAX_DOMAIN_CHARS = 253
_MAX_REPOSITORY_CHARS = 200
_MAX_YAML_INTEGER_CHARS = MAX_ASCII_UINT_DIGITS
CostMode = Literal["auto", "no-metered", "paid-ok"]
Cadence = Literal["manual", "hourly", "daily", "weekly"]

_HTTP_SCHEMES = {"http", "https"}
_PROFILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_YOUTUBE_CHANNEL_ID_RE = re.compile(r"UC[A-Za-z0-9_-]{6,62}")
_YOUTUBE_HANDLE_RE = re.compile(r"@[A-Za-z0-9][A-Za-z0-9._-]{1,28}[A-Za-z0-9]")


class ProfileValidationError(ValueError):
    """A research profile could not be parsed or validated."""


class _BoundedSafeLoader(yaml.SafeLoader):
    """Profile-only loader that bounds integer text before conversion."""


def _construct_bounded_yaml_int(
    loader: _BoundedSafeLoader,
    node: yaml.nodes.ScalarNode,
) -> int:
    raw_value = loader.construct_scalar(node)
    if len(raw_value) > _MAX_YAML_INTEGER_CHARS:
        raise ValueError(f"YAML integer cannot exceed {_MAX_YAML_INTEGER_CHARS} source characters")
    return yaml.constructor.SafeConstructor.construct_yaml_int(loader, node)


_BoundedSafeLoader.add_constructor(
    "tag:yaml.org,2002:int",
    _construct_bounded_yaml_int,
)


def _load_bounded_yaml(source: str) -> object:
    """Parse YAML with the bounded SafeLoader and always release parser state."""

    loader = _BoundedSafeLoader(source)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()  # pyright: ignore[reportUnknownMemberType] "PyYAML has incomplete stubs"


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def _require_non_empty(value: object, field_name: str, *, maximum_chars: int | None = None) -> str:
    text = _clean(value)
    if not text:
        raise ValueError(f"{field_name} cannot be empty")
    if maximum_chars is not None and len(text) > maximum_chars:
        raise ValueError(f"{field_name} cannot exceed {maximum_chars} characters")
    return text


def _validate_http_url(value: object, field_name: str) -> str:
    text = _require_non_empty(value, field_name, maximum_chars=_MAX_URL_CHARS)
    parsed = urlparse(text)
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError(f"{field_name} has an invalid port") from exc
    if (
        parsed.scheme.lower() not in _HTTP_SCHEMES
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(f"{field_name} must be an http or https URL")
    return text


def _normalize_domain(value: object) -> str:
    text = _require_non_empty(value, "domain", maximum_chars=_MAX_URL_CHARS)
    parsed = urlparse(text if "://" in text else f"https://{text}")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("domain has an invalid port") from exc
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if (
        not host
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
        or len(host) > _MAX_DOMAIN_CHARS
        or host.startswith(".")
        or host.endswith(".")
    ):
        raise ValueError("domain must be a hostname")
    if parsed.path not in {"", "/"}:
        raise ValueError("domain must not include a path")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("domain must be a public DNS hostname, not an IP address")
    labels = host.split(".")
    if len(labels) < 2 or any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or re.fullmatch(r"[a-z0-9-]+", label) is None
        for label in labels
    ):
        raise ValueError("domain must be a public DNS hostname")
    return host


def _normalize_repository(value: object) -> str:
    text = _require_non_empty(value, "repository", maximum_chars=_MAX_REPOSITORY_CHARS)
    if text.startswith(("http://", "https://")):
        parsed = urlparse(text)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("repository URL has an invalid port") from exc
        if (
            (parsed.hostname or "").lower().removeprefix("www.") != "github.com"
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("repository URL must point to github.com")
        parts = parsed.path.strip("/").split("/")
        if len(parts) != 2 or any(not part for part in parts):
            raise ValueError("repository must use owner/name")
        name = parts[1].removesuffix(".git")
        text = f"{parts[0]}/{name}"
    if not _REPO_RE.fullmatch(text):
        raise ValueError("repository must use owner/name")
    return text


def _validate_relative_path(value: object) -> str:
    text = _require_non_empty(value, "goal_file", maximum_chars=_MAX_GOAL_PATH_CHARS)
    normalized = text.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError("goal_file must be relative")
    raw_parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ValueError("goal_file must not contain traversal segments")
    canonical = PurePosixPath(normalized).as_posix()
    if canonical != normalized:
        raise ValueError("goal_file must use a canonical relative path")
    parts = PurePosixPath(normalized).parts
    if any(len(part) > 255 for part in parts):
        raise ValueError("goal_file path components cannot exceed 255 characters")
    if any(sanitize_path_component(part) != part for part in parts):
        raise ValueError("goal_file path components must be cross-platform safe")
    return normalized


class YouTubeChannelSource(BaseModel):
    """One YouTube source, identified by channel id, handle, or URL."""

    model_config = ConfigDict(extra="forbid")

    channel_id: str = Field(default="", max_length=64)
    handle: str = Field(default="", max_length=31)
    url: str = Field(default="", max_length=_MAX_URL_CHARS)
    label: str = Field(default="", max_length=_MAX_LABEL_CHARS)

    @field_validator("channel_id", "handle", "url", "label", mode="before")
    @classmethod
    def _clean_optional(cls, value: object) -> str:
        return _clean(value)

    @field_validator("handle")
    @classmethod
    def _normalize_handle(cls, value: str) -> str:
        if value and not value.startswith("@"):
            value = f"@{value}"
        if value and not _YOUTUBE_HANDLE_RE.fullmatch(value):
            raise ValueError("youtube handle must use 3-30 ASCII handle characters")
        return value

    @field_validator("channel_id")
    @classmethod
    def _validate_channel_id(cls, value: str) -> str:
        if value and not _YOUTUBE_CHANNEL_ID_RE.fullmatch(value):
            raise ValueError("youtube channel_id must use a bounded UC identifier")
        return value

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        if value:
            text = _validate_http_url(value, "youtube channel url")
            if not normalize_youtube_channel_url(text):
                raise ValueError("youtube channel url must be a canonical YouTube channel URL")
            return text.rstrip("/")
        return value

    @model_validator(mode="after")
    def _has_exactly_one_identifier(self) -> YouTubeChannelSource:
        identifier_count = sum(bool(value) for value in (self.channel_id, self.handle, self.url))
        if identifier_count != 1:
            raise ValueError("youtube channel needs exactly one of channel_id, handle, or url")
        return self


class FeedSource(BaseModel):
    """One RSS or Atom feed source."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=_MAX_URL_CHARS)
    label: str = Field(default="", max_length=_MAX_LABEL_CHARS)

    @field_validator("url", mode="before")
    @classmethod
    def _validate_url(cls, value: object) -> str:
        url = _validate_http_url(value, "feed url")
        parsed = urlparse(url)
        if parsed.scheme.casefold() != "https":
            raise ValueError("feed url must use HTTPS")
        if parsed.port == 0:
            raise ValueError("feed url port must be between 1 and 65535")
        return url

    @field_validator("label", mode="before")
    @classmethod
    def _clean_label(cls, value: object) -> str:
        return _clean(value)


class SourceSet(BaseModel):
    """Trusted source declarations for a recurring profile."""

    model_config = ConfigDict(extra="forbid")

    youtube_channels: list[YouTubeChannelSource] = Field(  # pyright: ignore[reportUnknownVariableType] "Pydantic Field + submodel appears Unknown under strict; post-validation ensures correct type per model_config"
        default_factory=list, max_length=MAX_PROFILE_DECLARATIONS
    )
    feeds: list[FeedSource] = Field(  # pyright: ignore[reportUnknownVariableType] "Pydantic Field + submodel appears Unknown under strict; post-validation ensures correct type per model_config"
        default_factory=list, max_length=MAX_PROFILE_DECLARATIONS
    )
    domains: list[str] = Field(  # pyright: ignore[reportUnknownVariableType] "Pydantic Field appears Unknown under strict; post-validation ensures list[str]"
        default_factory=list, max_length=MAX_PROFILE_DECLARATIONS
    )
    repositories: list[str] = Field(  # pyright: ignore[reportUnknownVariableType] "Pydantic Field appears Unknown under strict; post-validation ensures list[str]"
        default_factory=list, max_length=MAX_PROFILE_DECLARATIONS
    )

    @field_validator("youtube_channels", mode="before")
    @classmethod
    def _coerce_youtube_channels(cls, value: object) -> object:
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        channels: list[object] = []
        for item in cast(list[object], value):  # pyright: ignore[reportUnknownArgumentType] "yaml/user input object unknown; coercion + pydantic validate post"
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
        return [
            {"url": item} if isinstance(item, str) else item for item in cast(list[object], value)
        ]  # pyright: ignore[reportUnknownArgumentType] "yaml/user input object unknown; coercion + pydantic validate post"

    @field_validator("domains", mode="before")
    @classmethod
    def _clean_domains(cls, value: object) -> object:
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        return [_normalize_domain(item) for item in cast(list[object], value)]  # pyright: ignore[reportUnknownArgumentType] "yaml/user input object unknown; coercion + pydantic validate post"

    @field_validator("repositories", mode="before")
    @classmethod
    def _clean_repositories(cls, value: object) -> object:
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        return [_normalize_repository(item) for item in cast(list[object], value)]  # pyright: ignore[reportUnknownArgumentType] "yaml/user input object unknown; coercion + pydantic validate post"

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
        duration = parse_iso_day_hour_duration(text)
        if duration is None:
            raise ValueError("stale_after must be an ISO-8601 day or hour duration")
        if duration > timedelta(days=MAX_LOOKBACK_DAYS):
            raise ValueError(f"stale_after cannot exceed P{MAX_LOOKBACK_DAYS}D")
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

    max_new_items: int = Field(default=25, ge=1, le=MAX_PROFILE_NEW_ITEMS)
    max_metered_usd: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)

    @field_validator("max_new_items", "max_metered_usd", mode="before")
    @classmethod
    def _reject_boolean_limits(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("profile limits must be numeric, not boolean")
        return value


class ResearchProfile(BaseModel):
    """A saved recurring research plan."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["research-profile.v1"]
    name: str = Field(max_length=_MAX_SLUG_CHARS)
    topic: str = Field(max_length=_MAX_SLUG_CHARS)
    goal_file: str = Field(max_length=_MAX_GOAL_PATH_CHARS)
    cost_mode: CostMode = "auto"
    description: str = Field(default="", max_length=_MAX_DESCRIPTION_CHARS)
    freshness: FreshnessPolicy = Field(default_factory=FreshnessPolicy)
    sources: SourceSet = Field(default_factory=SourceSet)
    queries: list[str] = Field(default_factory=list, max_length=MAX_PROFILE_DECLARATIONS)
    outputs: OutputPreferences = Field(default_factory=OutputPreferences)
    limits: ProfileLimits = Field(default_factory=ProfileLimits)

    @field_validator("name", mode="before")
    @classmethod
    def _validate_name(cls, value: object) -> str:
        text = _require_non_empty(value, "name", maximum_chars=_MAX_SLUG_CHARS)
        if not _PROFILE_NAME_RE.fullmatch(text):
            raise ValueError("name must be a lowercase slug")
        return text

    @field_validator("topic", mode="before")
    @classmethod
    def _validate_topic(cls, value: object) -> str:
        text = _require_non_empty(value, "topic", maximum_chars=_MAX_SLUG_CHARS)
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
        text = _clean(value)
        if len(text) > _MAX_DESCRIPTION_CHARS:
            raise ValueError(f"description cannot exceed {_MAX_DESCRIPTION_CHARS} characters")
        return text

    @field_validator("queries", mode="before")
    @classmethod
    def _clean_queries(cls, value: object) -> object:
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        return [
            _require_non_empty(item, "query", maximum_chars=_MAX_QUERY_CHARS)
            for item in cast(list[object], value)  # pyright: ignore[reportUnknownArgumentType] "yaml/user input object unknown; coercion + pydantic validate post"
        ]

    @model_validator(mode="after")
    def _validate_profile(self) -> ResearchProfile:
        if sanitize_path_component(self.name) != self.name:
            raise ValueError("profile name must be a canonical cross-platform path component")
        if self.sources.source_count == 0 and not self.queries:
            raise ValueError("profile must include at least one source or query")
        if self.sources.source_count + len(self.queries) > MAX_PROFILE_DECLARATIONS:
            raise ValueError(
                f"profile cannot declare more than {MAX_PROFILE_DECLARATIONS} total sources "
                "and queries"
            )
        if self.cost_mode == "no-metered" and self.limits.max_metered_usd != 0:
            raise ValueError("no-metered profiles must set limits.max_metered_usd to 0")
        return self


def load_research_profile(path: Path) -> ResearchProfile:
    """Load one research profile YAML file."""

    try:
        if path.stat().st_size > _MAX_PROFILE_FILE_BYTES:
            raise ValueError(f"profile exceeds the {_MAX_PROFILE_FILE_BYTES:,}-byte cap")
        with path.open("rb") as stream:
            content = stream.read(_MAX_PROFILE_FILE_BYTES + 1)
        if len(content) > _MAX_PROFILE_FILE_BYTES:
            raise ValueError(f"profile exceeds the {_MAX_PROFILE_FILE_BYTES:,}-byte cap")
        payload = _load_bounded_yaml(content.decode("utf-8"))
        _validate_yaml_tree(payload)
    except OSError as exc:
        raise ProfileValidationError(f"Could not read profile {path}: {exc}") from exc
    except (RecursionError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        raise ProfileValidationError(f"Invalid YAML in profile {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProfileValidationError(f"Profile {path} must contain a YAML mapping")
    try:
        return ResearchProfile.model_validate(payload)
    except (RecursionError, ValidationError) as exc:
        raise ProfileValidationError(f"Invalid profile {path}: {exc}") from exc


def _validate_yaml_tree(payload: object) -> None:
    stack: list[tuple[object, bool]] = [(payload, False)]
    active: set[int] = set()
    visited = 0
    while stack:
        value, exiting = stack.pop()
        if isinstance(value, dict):
            mapping = cast(dict[object, object], value)
            identity = id(mapping)
            container: object = mapping
            children: list[object] = list(mapping.values())
        elif isinstance(value, list):
            sequence = cast(list[object], value)
            identity = id(sequence)
            container = sequence
            children = sequence
        else:
            continue
        if exiting:
            active.remove(identity)
            continue
        if identity in active:
            raise ValueError("recursive YAML aliases are not supported")
        visited += 1
        if visited > _MAX_PROFILE_YAML_NODES:
            raise ValueError("profile YAML structure exceeds the node cap")
        active.add(identity)
        stack.append((container, True))
        stack.extend((child, False) for child in children)


def list_research_profile_paths(library_dir: Path) -> list[Path]:
    """Return saved profile files under ``library/profiles``, newest-name last.

    Caps the library at ``MAX_LIBRARY_PROFILES`` so an overnight refresh cannot
    walk an unbounded directory. Duplicate stems (``.yaml`` and ``.yml``) keep
    the first path in sorted order.
    """

    profiles_dir = library_dir / "profiles"
    if not profiles_dir.is_dir():
        return []
    found: dict[str, Path] = {}
    try:
        entries = sorted(profiles_dir.iterdir(), key=lambda path: path.name.lower())
    except OSError:
        return []
    for path in entries:
        if path.suffix.lower() not in {".yaml", ".yml"} or not path.is_file():
            continue
        stem = path.stem.lower()
        if stem in found:
            continue
        found[stem] = path
        if len(found) >= MAX_LIBRARY_PROFILES:
            break
    return list(found.values())


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
