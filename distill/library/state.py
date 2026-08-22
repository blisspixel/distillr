"""Library and channel state management.

Combines the Library class (topic/channel hierarchy, watchlists) with
ChannelState (per-channel video processing state).

Both classes persist as JSON. JSON is an untrusted, corruptible boundary, so the
on-disk payload is *parsed once* into a typed shape at load time (the ``_parse_*``
functions below) rather than re-validated ad hoc at every read. After parsing,
the required keys are guaranteed present and well-typed, so the methods operate
on the typed structure directly - illegal states (missing keys, wrong value
types, a non-object top-level document) are normalized away at the boundary
instead of crashing a downstream read.
"""

# pyright: strict

import json
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict, cast

from distill.config import DistillConfig
from distill.library.paths import atomic_update_text, sanitize_topic, text_write_lock
from distill.parsing import as_whole_number, strict_json_loads
from distill.youtube_urls import normalize_video_id, normalize_youtube_channel_url

__all__ = [
    "ChannelInfo",
    "ChannelState",
    "Library",
    "TopicWatchEntry",
    "WatchEntry",
]

logger = logging.getLogger(__name__)

_MAX_STATE_BYTES = 16 * 1024 * 1024
_MAX_CORRUPT_BACKUPS = 100


# ─── Domain types (returned to callers) ──────────────────────────────────────


@dataclass
class ChannelInfo:
    url: str
    name: str
    topic: str


@dataclass
class WatchEntry:
    url: str
    name: str
    topic: str
    added_at: str = ""
    instructions: str = ""
    instructions_approved: bool = False
    days: int = 14

    @property
    def active_instructions(self) -> str:
        """Return only instructions explicitly approved by the local operator."""
        return self.instructions if self.instructions_approved else ""


@dataclass
class TopicWatchEntry:
    name: str
    query: str
    topic: str
    cadence: str = "weekly"
    days: int = 7
    limit: int = 10
    sort: str = "date"
    channel_cap: int = 3
    ranking_mode: str = "balanced"
    added_at: str = ""
    last_run_at: str = ""
    report: bool = False
    max_run_cost: float = 0.0
    monthly_budget: float = 0.0
    paused: bool = False


# ─── Persistence shapes (the on-disk JSON, parsed once at the boundary) ───────


class ChannelRow(TypedDict):
    url: str
    name: str


class TopicData(TypedDict):
    channels: list[ChannelRow]


class WatchRow(TypedDict):
    url: str
    name: str
    topic: str
    added_at: str
    instructions: str
    instructions_approved: bool
    days: int


class TopicWatchRow(TypedDict):
    name: str
    query: str
    topic: str
    cadence: str
    days: int
    limit: int
    sort: str
    channel_cap: int
    ranking_mode: str
    added_at: str
    last_run_at: str
    report: bool
    max_run_cost: float
    monthly_budget: float
    paused: bool


class LibraryData(TypedDict):
    topics: dict[str, TopicData]
    watchlist: list[WatchRow]
    topic_watchlist: list[TopicWatchRow]


class ProcessedVideo(TypedDict):
    title: str
    upload_date: str
    processed_at: str
    analysis_mode: str


class ChannelStateData(TypedDict):
    processed_videos: dict[str, ProcessedVideo]
    last_refresh: str | None


# ─── Boundary coercion helpers ────────────────────────────────────────────────
#
# Each takes a raw JSON value (typed ``object`` because json.loads yields Any)
# and returns a well-typed value, substituting the default when the shape is
# wrong. bool is excluded from the numeric coercions because ``bool`` is an
# ``int`` subclass and a JSON ``true`` must not read as the integer 1.


def _as_dict(value: object) -> dict[str, Any]:
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def _as_list(value: object) -> list[Any]:
    return cast("list[Any]", value) if isinstance(value, list) else []


def _str(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _int(value: object, default: int) -> int:
    parsed = as_whole_number(value)
    return default if parsed is None else parsed


def _float(value: object, default: float) -> float:
    if isinstance(value, bool):
        return default
    if not isinstance(value, int | float):
        return default
    parsed = float(value)
    return parsed if math.isfinite(parsed) and parsed >= 0 else default


def _validated_budget(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be a finite non-negative number")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(f"{field_name} must be a finite non-negative number")
    return parsed


def _bool(value: object, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def _channel_url(value: object) -> str:
    raw_url = _str(value)
    return normalize_youtube_channel_url(raw_url) or raw_url


def _channel_row(value: object) -> ChannelRow:
    row = _as_dict(value)
    return {"url": _channel_url(row.get("url")), "name": _str(row.get("name"))}


def _watch_row(value: object) -> WatchRow:
    row = _as_dict(value)
    return {
        "url": _channel_url(row.get("url")),
        "name": _str(row.get("name")),
        "topic": _str(row.get("topic"), "watch"),
        "added_at": _str(row.get("added_at")),
        "instructions": _str(row.get("instructions")),
        # Historical auto-generated instructions have no provenance. Fail
        # closed until the operator explicitly saves them again.
        "instructions_approved": _bool(row.get("instructions_approved")),
        "days": _int(row.get("days"), 14),
    }


def _topic_watch_row(value: object) -> TopicWatchRow:
    row = _as_dict(value)
    return {
        "name": _str(row.get("name")),
        "query": _str(row.get("query")),
        "topic": _str(row.get("topic"), "watch"),
        "cadence": _str(row.get("cadence"), "weekly"),
        "days": _int(row.get("days"), 7),
        "limit": _int(row.get("limit"), 10),
        "sort": _str(row.get("sort"), "date"),
        "channel_cap": _int(row.get("channel_cap"), 3),
        "ranking_mode": _str(row.get("ranking_mode"), "balanced"),
        "added_at": _str(row.get("added_at")),
        "last_run_at": _str(row.get("last_run_at")),
        "report": _bool(row.get("report")),
        "max_run_cost": _float(row.get("max_run_cost"), 0.0),
        "monthly_budget": _float(row.get("monthly_budget"), 0.0),
        "paused": _bool(row.get("paused")),
    }


def _parse_library(raw: object) -> LibraryData:
    data = _as_dict(raw)
    topics: dict[str, TopicData] = {}
    for name, topic_data in _as_dict(data.get("topics")).items():
        channels = [_channel_row(c) for c in _as_list(_as_dict(topic_data).get("channels"))]
        topics[str(name)] = {"channels": channels}
    return {
        "topics": topics,
        "watchlist": [_watch_row(e) for e in _as_list(data.get("watchlist"))],
        "topic_watchlist": [_topic_watch_row(e) for e in _as_list(data.get("topic_watchlist"))],
    }


def _empty_library() -> LibraryData:
    return {"topics": {}, "watchlist": [], "topic_watchlist": []}


def _parse_channel_state(raw: object) -> ChannelStateData:
    data = _as_dict(raw)
    processed: dict[str, ProcessedVideo] = {}
    for video_id, entry in _as_dict(data.get("processed_videos")).items():
        row = _as_dict(entry)
        processed[str(video_id)] = {
            "title": _str(row.get("title")),
            "upload_date": _str(row.get("upload_date")),
            "processed_at": _str(row.get("processed_at")),
            "analysis_mode": _str(row.get("analysis_mode"), "full"),
        }
    return {"processed_videos": processed, "last_refresh": _str_or_none(data.get("last_refresh"))}


def _empty_channel_state() -> ChannelStateData:
    return {"processed_videos": {}, "last_refresh": None}


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _serialized_state(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)


def _read_state_json(path: Path) -> object:
    with path.open("rb") as stream:
        content = stream.read(_MAX_STATE_BYTES + 1)
    if len(content) > _MAX_STATE_BYTES:
        raise ValueError(f"State file exceeds the {_MAX_STATE_BYTES:,}-byte limit: {path}")
    return strict_json_loads(content)


def _next_corrupt_backup(path: Path) -> Path:
    first = path.with_suffix(f"{path.suffix}.bak")
    for index in range(_MAX_CORRUPT_BACKUPS):
        candidate = first if index == 0 else first.with_name(f"{first.name}.{index}")
        if not candidate.exists():
            return candidate
    raise OSError(f"No free corrupt-state backup slot for {path}")


def _quarantine_corrupt_locked(path: Path, error: BaseException) -> bool:
    """Move one invalid state revision aside while its shared write lock is held."""

    try:
        backup = _next_corrupt_backup(path)
        path.rename(backup)
    except OSError as backup_error:
        logger.error(
            "Cannot quarantine corrupt state %s after %s: %s",
            path,
            type(error).__name__,
            backup_error,
        )
        return False
    logger.warning(
        "Quarantined corrupt state after %s: %s -> %s",
        type(error).__name__,
        path,
        backup,
    )
    return True


def _recover_corrupt_locked[State](
    path: Path,
    error: BaseException,
    *,
    empty: Callable[[], State],
) -> State:
    if not _quarantine_corrupt_locked(path, error):
        raise error
    return empty()


def _load_state[State](
    path: Path,
    *,
    parse: Callable[[object], State],
    empty: Callable[[], State],
) -> State:
    try:
        raw = _read_state_json(path)
    except FileNotFoundError:
        return empty()
    except (OSError, RecursionError, ValueError):
        pass
    else:
        return parse(raw)

    # Clean reads are side-effect free. Only a suspected corrupt revision takes
    # the writer lock, then rechecks before moving that exact revision aside.
    with text_write_lock(path):
        try:
            raw = _read_state_json(path)
        except FileNotFoundError:
            return empty()
        except (OSError, RecursionError, ValueError) as exc:
            return _recover_corrupt_locked(path, exc, empty=empty)
        return parse(raw)


# ─── Stores ───────────────────────────────────────────────────────────────────


class Library:
    """Manages the topic → channel hierarchy."""

    def __init__(self, config: DistillConfig):
        self.config = config
        self.library_file = config.library_dir / "library.json"
        self._data = self._load()

    def _load(self) -> LibraryData:
        return _load_state(
            self.library_file,
            parse=_parse_library,
            empty=_empty_library,
        )

    def _mutate[Result](self, mutation: Callable[[LibraryData], Result]) -> Result:
        def update(current: str) -> tuple[str, tuple[Result, LibraryData]]:
            try:
                data = _parse_library(strict_json_loads(current))
            except (RecursionError, ValueError) as exc:
                data = _recover_corrupt_locked(
                    self.library_file,
                    exc,
                    empty=_empty_library,
                )
            result = mutation(data)
            return _serialized_state(data), (result, data)

        def recover_invalid(error: BaseException) -> str:
            data = _recover_corrupt_locked(
                self.library_file,
                error,
                empty=_empty_library,
            )
            return _serialized_state(data)

        result, data = atomic_update_text(
            self.library_file,
            update,
            missing=_serialized_state(_empty_library()),
            max_bytes=_MAX_STATE_BYTES,
            recover_invalid=recover_invalid,
        )
        self._data = data
        return result

    def add_channel(self, topic: str, url: str, name: str):
        """Add a channel to a topic."""
        normalized_url = normalize_youtube_channel_url(url)
        if not normalized_url:
            raise ValueError("Refusing invalid YouTube channel URL")
        url = normalized_url
        topic = sanitize_topic(topic)

        def add(data: LibraryData) -> bool:
            if topic not in data["topics"]:
                data["topics"][topic] = {"channels": []}
            channels = data["topics"][topic]["channels"]
            if any(channel["url"] == url for channel in channels):
                return False
            channels.append({"url": url, "name": name})
            return True

        added = self._mutate(add)
        if not added:
            return False

        # Create directory structure
        channel_dir = self.config.channel_dir(topic, name)
        (channel_dir / "videos").mkdir(parents=True, exist_ok=True)
        return True

    def remove_channel(self, topic: str, url: str) -> bool:
        """Remove a channel from a topic."""
        normalized_url = normalize_youtube_channel_url(url)
        if not normalized_url:
            return False
        url = normalized_url
        topic = sanitize_topic(topic)

        def remove(data: LibraryData) -> bool:
            if topic not in data["topics"]:
                return False
            channels = data["topics"][topic]["channels"]
            retained = [channel for channel in channels if channel["url"] != url]
            if len(retained) == len(channels):
                return False
            data["topics"][topic]["channels"] = retained
            return True

        return self._mutate(remove)

    def get_topics(self) -> list[str]:
        return list(self._data["topics"].keys())

    def get_corpus_topics(self) -> list[str]:
        """Return registered topics plus topic directories found on disk.

        Direct ingestion writes a corpus without registering a recurring
        channel URL in ``library.json``. Read-only inventory surfaces need to
        see those artifacts, while execution paths must continue to use
        :meth:`get_topics` and :meth:`get_channels` as the subscription truth.
        """
        topics = self.get_topics()
        seen = {topic.casefold() for topic in topics}
        topics_dir = self.config.topics_dir()
        try:
            children = sorted(topics_dir.iterdir(), key=lambda path: path.name.casefold())
        except OSError:
            return topics
        for child in children:
            try:
                is_topic = child.is_dir()
            except OSError:
                continue
            if not is_topic or child.name.startswith(".") or child.name.casefold() in seen:
                continue
            topics.append(child.name)
            seen.add(child.name.casefold())
        return topics

    def get_corpus_channel_names(self, topic: str) -> list[str]:
        """Return registered and filesystem-backed channel names for reading.

        The returned names do not carry URLs and are intentionally separate
        from :meth:`get_channels`, so a direct-ingest directory cannot become a
        runnable channel subscription by being discovered here.
        """
        topic = sanitize_topic(topic)
        names = [channel.name for channel in self.get_channels(topic)]
        seen = {name.casefold() for name in names}
        channels_dir = self.config.topic_dir(topic) / "channels"
        try:
            children = sorted(channels_dir.iterdir(), key=lambda path: path.name.casefold())
        except OSError:
            return names
        for child in children:
            try:
                is_channel = child.is_dir()
            except OSError:
                continue
            if not is_channel or child.name.startswith(".") or child.name.casefold() in seen:
                continue
            names.append(child.name)
            seen.add(child.name.casefold())
        return names

    def get_channels(self, topic: str) -> list[ChannelInfo]:
        topic = sanitize_topic(topic)
        if topic not in self._data["topics"]:
            return []
        return [
            ChannelInfo(url=c["url"], name=c["name"], topic=topic)
            for c in self._data["topics"][topic]["channels"]
        ]

    def get_all_channels(self) -> list[ChannelInfo]:
        result: list[ChannelInfo] = []
        for topic in self.get_topics():
            result.extend(self.get_channels(topic))
        return result

    def get_channel_by_name(self, topic: str, name: str) -> ChannelInfo | None:
        topic = sanitize_topic(topic)
        for ch in self.get_channels(topic):
            if ch.name == name:
                return ch
        return None

    def find_channel(self, name: str) -> ChannelInfo | None:
        """Find a channel by name across all topics (case-insensitive)."""
        for topic in self.get_topics():
            for ch in self.get_channels(topic):
                if ch.name.lower() == name.lower():
                    return ch
        return None

    # ─── Watchlist ───────────────────────────────────────────────────

    def get_watchlist(self) -> list[WatchEntry]:
        return [
            WatchEntry(
                url=e["url"],
                name=e["name"],
                topic=sanitize_topic(e["topic"]),
                added_at=e["added_at"],
                instructions=e["instructions"],
                instructions_approved=e["instructions_approved"],
                days=e["days"],
            )
            for e in self._data["watchlist"]
        ]

    def add_to_watchlist(
        self,
        url: str,
        name: str,
        topic: str = "watch",
        instructions: str = "",
        days: int = 14,
    ) -> bool:
        """Add a channel to the watch list. Also registers it under the topic."""
        normalized_url = normalize_youtube_channel_url(url)
        if not normalized_url:
            raise ValueError("Refusing invalid YouTube channel URL")
        url = normalized_url
        topic = sanitize_topic(topic)
        added_at = datetime.now().isoformat()

        def add(data: LibraryData) -> bool:
            watchlist = data["watchlist"]
            if any(entry["url"] == url for entry in watchlist):
                return False
            watchlist.append(
                {
                    "url": url,
                    "name": name,
                    "topic": topic,
                    "added_at": added_at,
                    "instructions": instructions,
                    "instructions_approved": bool(instructions),
                    "days": days,
                }
            )
            if topic not in data["topics"]:
                data["topics"][topic] = {"channels": []}
            channels = data["topics"][topic]["channels"]
            if not any(channel["url"] == url for channel in channels):
                channels.append({"url": url, "name": name})
            return True

        added = self._mutate(add)
        if not added:
            return False
        (self.config.channel_dir(topic, name) / "videos").mkdir(parents=True, exist_ok=True)
        return True

    def remove_from_watchlist(self, name: str) -> bool:
        """Remove a channel from the watch list by name (case-insensitive)."""
        normalized = name.lower()

        def remove(data: LibraryData) -> bool:
            watchlist = data["watchlist"]
            retained = [entry for entry in watchlist if entry["name"].lower() != normalized]
            if len(retained) == len(watchlist):
                return False
            data["watchlist"] = retained
            return True

        return self._mutate(remove)

    def get_watch_entry(self, name: str) -> WatchEntry | None:
        """Look up a watch entry by channel name (case-insensitive)."""
        for e in self.get_watchlist():
            if e.name.lower() == name.lower():
                return e
        return None

    def update_watch_days(self, name: str, days: int) -> bool:
        """Update lookback days for a watched channel."""
        normalized = name.lower()

        def update(data: LibraryData) -> bool:
            for entry in data["watchlist"]:
                if entry["name"].lower() == normalized:
                    entry["days"] = days
                    return True
            return False

        return self._mutate(update)

    def update_watch_instructions(self, name: str, instructions: str) -> bool:
        """Update custom instructions for a watched channel."""
        normalized = name.lower()

        def update(data: LibraryData) -> bool:
            for entry in data["watchlist"]:
                if entry["name"].lower() == normalized:
                    entry["instructions"] = instructions
                    entry["instructions_approved"] = bool(instructions)
                    return True
            return False

        return self._mutate(update)

    # ─── Topic Watchlist ──────────────────────────────────────────────

    def get_topic_watchlist(self) -> list[TopicWatchEntry]:
        return [
            TopicWatchEntry(
                name=e["name"],
                query=e["query"],
                topic=sanitize_topic(e["topic"]),
                cadence=e["cadence"],
                days=e["days"],
                limit=e["limit"],
                sort=e["sort"],
                channel_cap=e["channel_cap"],
                ranking_mode=e["ranking_mode"],
                added_at=e["added_at"],
                last_run_at=e["last_run_at"],
                report=e["report"],
                max_run_cost=e["max_run_cost"],
                monthly_budget=e["monthly_budget"],
                paused=e["paused"],
            )
            for e in self._data["topic_watchlist"]
        ]

    def add_to_topic_watchlist(
        self,
        name: str,
        query: str,
        *,
        topic: str = "watch",
        cadence: str = "weekly",
        days: int = 7,
        limit: int = 10,
        sort: str = "date",
        channel_cap: int = 3,
        ranking_mode: str = "balanced",
        report: bool = False,
        max_run_cost: float = 0.0,
        monthly_budget: float = 0.0,
    ) -> bool:
        topic = sanitize_topic(topic)
        max_run_cost = _validated_budget(max_run_cost, field_name="max_run_cost")
        monthly_budget = _validated_budget(monthly_budget, field_name="monthly_budget")
        normalized = name.lower()
        added_at = datetime.now().isoformat()

        def add(data: LibraryData) -> bool:
            topic_watchlist = data["topic_watchlist"]
            if any(entry["name"].lower() == normalized for entry in topic_watchlist):
                return False
            topic_watchlist.append(
                {
                    "name": name,
                    "query": query,
                    "topic": topic,
                    "cadence": cadence,
                    "days": days,
                    "limit": limit,
                    "sort": sort,
                    "channel_cap": channel_cap,
                    "ranking_mode": ranking_mode,
                    "report": report,
                    "max_run_cost": max_run_cost,
                    "monthly_budget": monthly_budget,
                    "paused": False,
                    "added_at": added_at,
                    "last_run_at": "",
                }
            )
            return True

        return self._mutate(add)

    def remove_from_topic_watchlist(self, name: str) -> bool:
        normalized = name.lower()

        def remove(data: LibraryData) -> bool:
            topic_watchlist = data["topic_watchlist"]
            retained = [entry for entry in topic_watchlist if entry["name"].lower() != normalized]
            if len(retained) == len(topic_watchlist):
                return False
            data["topic_watchlist"] = retained
            return True

        return self._mutate(remove)

    def get_topic_watch_entry(self, name: str) -> TopicWatchEntry | None:
        for e in self.get_topic_watchlist():
            if e.name.lower() == name.lower():
                return e
        return None

    def update_topic_watch_days(self, name: str, days: int) -> bool:
        return self._update_topic_watch_field(name, "days", days)

    def update_topic_watch_cadence(self, name: str, cadence: str) -> bool:
        return self._update_topic_watch_field(name, "cadence", cadence)

    def update_topic_watch_ranking_mode(self, name: str, ranking_mode: str) -> bool:
        return self._update_topic_watch_field(name, "ranking_mode", ranking_mode)

    def mark_topic_watch_run(self, name: str, when_iso: str) -> bool:
        return self._update_topic_watch_field(name, "last_run_at", when_iso)

    def _update_topic_watch_field(
        self,
        name: str,
        field: str,
        value: object,
    ) -> bool:
        normalized = name.lower()

        def update(data: LibraryData) -> bool:
            for entry in data["topic_watchlist"]:
                if entry["name"].lower() == normalized:
                    entry[field] = value  # type: ignore[literal-required]
                    return True
            return False

        return self._mutate(update)

    def update_topic_watch_budget(
        self, name: str, *, max_run_cost: float | None = None, monthly_budget: float | None = None
    ) -> bool:
        validated_run_cost = (
            _validated_budget(max_run_cost, field_name="max_run_cost")
            if max_run_cost is not None
            else None
        )
        validated_monthly_budget = (
            _validated_budget(monthly_budget, field_name="monthly_budget")
            if monthly_budget is not None
            else None
        )
        normalized = name.lower()

        def update(data: LibraryData) -> bool:
            for entry in data["topic_watchlist"]:
                if entry["name"].lower() != normalized:
                    continue
                if validated_run_cost is not None:
                    entry["max_run_cost"] = validated_run_cost
                if validated_monthly_budget is not None:
                    entry["monthly_budget"] = validated_monthly_budget
                return True
            return False

        return self._mutate(update)

    def set_topic_watch_paused(self, name: str, paused: bool) -> bool:
        return self._update_topic_watch_field(name, "paused", paused)


class ChannelState:
    """Tracks which videos have been processed for a channel."""

    def __init__(self, state_file: Path):
        self.state_file = state_file
        self._data = self._load()

    def _load(self) -> ChannelStateData:
        return _load_state(
            self.state_file,
            parse=_parse_channel_state,
            empty=_empty_channel_state,
        )

    def _mutate(self, mutation: Callable[[ChannelStateData], None]) -> None:
        def update(current: str) -> tuple[str, ChannelStateData]:
            try:
                data = _parse_channel_state(strict_json_loads(current))
            except (RecursionError, ValueError) as exc:
                data = _recover_corrupt_locked(
                    self.state_file,
                    exc,
                    empty=_empty_channel_state,
                )
            mutation(data)
            return _serialized_state(data), data

        def recover_invalid(error: BaseException) -> str:
            data = _recover_corrupt_locked(
                self.state_file,
                error,
                empty=_empty_channel_state,
            )
            return _serialized_state(data)

        data = atomic_update_text(
            self.state_file,
            update,
            missing=_serialized_state(_empty_channel_state()),
            max_bytes=_MAX_STATE_BYTES,
            recover_invalid=recover_invalid,
        )
        self._data = data

    def is_processed(self, video_id: str) -> bool:
        normalized_id = normalize_video_id(video_id)
        return bool(normalized_id and normalized_id in self._data["processed_videos"])

    def mark_processed(
        self, video_id: str, title: str, upload_date: str, analysis_mode: str = "full"
    ):
        normalized_id = normalize_video_id(video_id)
        if not normalized_id:
            raise ValueError("Refusing invalid YouTube video id")
        video_id = normalized_id
        processed_at = datetime.now().isoformat()

        def mark(data: ChannelStateData) -> None:
            data["processed_videos"][video_id] = {
                "title": title,
                "upload_date": upload_date,
                "processed_at": processed_at,
                "analysis_mode": analysis_mode,
            }
            data["last_refresh"] = processed_at

        self._mutate(mark)

    def get_analysis_mode(self, video_id: str) -> str:
        """Get the analysis mode for a processed video (legacy entries default to 'full')."""
        entry = self._data["processed_videos"].get(video_id)
        return entry["analysis_mode"] if entry else "full"

    def get_processed_count(self) -> int:
        return len(self._data["processed_videos"])

    def processed_video_ids(self) -> list[str]:
        """Identifiers of every processed video, in insertion order."""
        return list(self._data["processed_videos"].keys())

    def get_last_refresh(self) -> str | None:
        return self._data["last_refresh"]
