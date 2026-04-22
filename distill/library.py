"""Library management — topics, channels, library.json."""

import contextlib
import json
from dataclasses import dataclass

from distill.config import DistillConfig


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
    days: int = 14


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


class Library:
    """Manages the topic → channel hierarchy."""

    def __init__(self, config: DistillConfig):
        self.config = config
        self.library_file = config.library_dir / "library.json"
        self._data = self._load()

    def _load(self) -> dict:
        if self.library_file.exists():
            try:
                data = json.loads(self.library_file.read_text(encoding="utf-8"))
                if "topics" not in data or not isinstance(data["topics"], dict):
                    data["topics"] = {}
                if "watchlist" not in data or not isinstance(data["watchlist"], list):
                    data["watchlist"] = []
                if "topic_watchlist" not in data or not isinstance(data["topic_watchlist"], list):
                    data["topic_watchlist"] = []
                return data
            except (json.JSONDecodeError, OSError):
                # Corrupted library file — start fresh but keep backup
                backup = self.library_file.with_suffix(".json.bak")
                with contextlib.suppress(OSError):
                    self.library_file.rename(backup)
                return {"topics": {}, "watchlist": [], "topic_watchlist": []}
        return {"topics": {}, "watchlist": [], "topic_watchlist": []}

    def _save(self):
        self.library_file.parent.mkdir(parents=True, exist_ok=True)
        self.library_file.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def add_channel(self, topic: str, url: str, name: str):
        """Add a channel to a topic."""
        if topic not in self._data["topics"]:
            self._data["topics"][topic] = {"channels": []}

        channels = self._data["topics"][topic]["channels"]
        # Check for duplicate
        if any(c["url"] == url for c in channels):
            return False

        channels.append({"url": url, "name": name})
        self._save()

        # Create directory structure
        channel_dir = self.config.channel_dir(topic, name)
        (channel_dir / "videos").mkdir(parents=True, exist_ok=True)
        return True

    def remove_channel(self, topic: str, url: str) -> bool:
        """Remove a channel from a topic."""
        if topic not in self._data["topics"]:
            return False
        channels = self._data["topics"][topic]["channels"]
        before = len(channels)
        self._data["topics"][topic]["channels"] = [c for c in channels if c["url"] != url]
        if len(self._data["topics"][topic]["channels"]) < before:
            self._save()
            return True
        return False

    def get_topics(self) -> list[str]:
        return list(self._data["topics"].keys())

    def get_channels(self, topic: str) -> list[ChannelInfo]:
        if topic not in self._data["topics"]:
            return []
        return [
            ChannelInfo(url=c["url"], name=c["name"], topic=topic)
            for c in self._data["topics"][topic]["channels"]
        ]

    def get_all_channels(self) -> list[ChannelInfo]:
        result = []
        for topic in self.get_topics():
            result.extend(self.get_channels(topic))
        return result

    def get_channel_by_name(self, topic: str, name: str) -> ChannelInfo | None:
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
                topic=e.get("topic", "watch"),
                added_at=e.get("added_at", ""),
                instructions=e.get("instructions", ""),
                days=e.get("days", 14),
            )
            for e in self._data.get("watchlist", [])
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
        wl = self._data.setdefault("watchlist", [])
        if any(e["url"] == url for e in wl):
            return False
        from datetime import datetime

        wl.append(
            {
                "url": url,
                "name": name,
                "topic": topic,
                "added_at": datetime.now().isoformat(),
                "instructions": instructions,
                "days": days,
            }
        )
        # Also register channel under the topic
        self.add_channel(topic, url, name)
        self._save()
        return True

    def remove_from_watchlist(self, name: str) -> bool:
        """Remove a channel from the watch list by name (case-insensitive)."""
        wl = self._data.get("watchlist", [])
        before = len(wl)
        self._data["watchlist"] = [e for e in wl if e["name"].lower() != name.lower()]
        if len(self._data["watchlist"]) < before:
            self._save()
            return True
        return False

    def get_watch_entry(self, name: str) -> WatchEntry | None:
        """Look up a watch entry by channel name (case-insensitive)."""
        for e in self.get_watchlist():
            if e.name.lower() == name.lower():
                return e
        return None

    def update_watch_days(self, name: str, days: int) -> bool:
        """Update lookback days for a watched channel."""
        wl = self._data.get("watchlist", [])
        for e in wl:
            if e["name"].lower() == name.lower():
                e["days"] = days
                self._save()
                return True
        return False

    def update_watch_instructions(self, name: str, instructions: str) -> bool:
        """Update custom instructions for a watched channel."""
        wl = self._data.get("watchlist", [])
        for e in wl:
            if e["name"].lower() == name.lower():
                e["instructions"] = instructions
                self._save()
                return True
        return False

    # ─── Topic Watchlist ──────────────────────────────────────────────

    def get_topic_watchlist(self) -> list[TopicWatchEntry]:
        return [
            TopicWatchEntry(
                name=e["name"],
                query=e["query"],
                topic=e.get("topic", "watch"),
                cadence=e.get("cadence", "weekly"),
                days=e.get("days", 7),
                limit=e.get("limit", 10),
                sort=e.get("sort", "date"),
                channel_cap=e.get("channel_cap", 3),
                ranking_mode=e.get("ranking_mode", "balanced"),
                added_at=e.get("added_at", ""),
                last_run_at=e.get("last_run_at", ""),
                report=e.get("report", False),
                max_run_cost=float(e.get("max_run_cost", 0.0) or 0.0),
                monthly_budget=float(e.get("monthly_budget", 0.0) or 0.0),
                paused=bool(e.get("paused", False)),
            )
            for e in self._data.get("topic_watchlist", [])
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
        twl = self._data.setdefault("topic_watchlist", [])
        if any(e["name"].lower() == name.lower() for e in twl):
            return False

        from datetime import datetime

        twl.append(
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
                "added_at": datetime.now().isoformat(),
                "last_run_at": "",
            }
        )
        self._save()
        return True

    def remove_from_topic_watchlist(self, name: str) -> bool:
        twl = self._data.get("topic_watchlist", [])
        before = len(twl)
        self._data["topic_watchlist"] = [e for e in twl if e["name"].lower() != name.lower()]
        if len(self._data["topic_watchlist"]) < before:
            self._save()
            return True
        return False

    def get_topic_watch_entry(self, name: str) -> TopicWatchEntry | None:
        for e in self.get_topic_watchlist():
            if e.name.lower() == name.lower():
                return e
        return None

    def update_topic_watch_days(self, name: str, days: int) -> bool:
        twl = self._data.get("topic_watchlist", [])
        for e in twl:
            if e["name"].lower() == name.lower():
                e["days"] = days
                self._save()
                return True
        return False

    def update_topic_watch_cadence(self, name: str, cadence: str) -> bool:
        twl = self._data.get("topic_watchlist", [])
        for e in twl:
            if e["name"].lower() == name.lower():
                e["cadence"] = cadence
                self._save()
                return True
        return False

    def update_topic_watch_ranking_mode(self, name: str, ranking_mode: str) -> bool:
        twl = self._data.get("topic_watchlist", [])
        for e in twl:
            if e["name"].lower() == name.lower():
                e["ranking_mode"] = ranking_mode
                self._save()
                return True
        return False

    def mark_topic_watch_run(self, name: str, when_iso: str) -> bool:
        twl = self._data.get("topic_watchlist", [])
        for e in twl:
            if e["name"].lower() == name.lower():
                e["last_run_at"] = when_iso
                self._save()
                return True
        return False

    def update_topic_watch_budget(
        self, name: str, *, max_run_cost: float | None = None, monthly_budget: float | None = None
    ) -> bool:
        twl = self._data.get("topic_watchlist", [])
        for e in twl:
            if e["name"].lower() == name.lower():
                if max_run_cost is not None:
                    e["max_run_cost"] = max_run_cost
                if monthly_budget is not None:
                    e["monthly_budget"] = monthly_budget
                self._save()
                return True
        return False

    def set_topic_watch_paused(self, name: str, paused: bool) -> bool:
        twl = self._data.get("topic_watchlist", [])
        for e in twl:
            if e["name"].lower() == name.lower():
                e["paused"] = paused
                self._save()
                return True
        return False
