"""State tracking — processed videos per channel."""

import contextlib
import json
from datetime import datetime
from pathlib import Path


class ChannelState:
    """Tracks which videos have been processed for a channel."""

    def __init__(self, state_file: Path):
        self.state_file = state_file
        self._data = self._load()

    def _load(self) -> dict:
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                # Ensure required keys exist
                if "processed_videos" not in data or not isinstance(data["processed_videos"], dict):
                    data["processed_videos"] = {}
                if "last_refresh" not in data:
                    data["last_refresh"] = None
                return data
            except (json.JSONDecodeError, OSError):
                # Corrupted state file — start fresh but keep a backup
                backup = self.state_file.with_suffix(".json.bak")
                with contextlib.suppress(OSError):
                    self.state_file.rename(backup)
                return {"processed_videos": {}, "last_refresh": None}
        return {"processed_videos": {}, "last_refresh": None}

    def _save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def is_processed(self, video_id: str) -> bool:
        return video_id in self._data["processed_videos"]

    def mark_processed(
        self, video_id: str, title: str, upload_date: str, analysis_mode: str = "full"
    ):
        self._data["processed_videos"][video_id] = {
            "title": title,
            "upload_date": upload_date,
            "processed_at": datetime.now().isoformat(),
            "analysis_mode": analysis_mode,
        }
        self._data["last_refresh"] = datetime.now().isoformat()
        self._save()

    def get_analysis_mode(self, video_id: str) -> str:
        """Get the analysis mode for a processed video."""
        entry = self._data["processed_videos"].get(video_id, {})
        return entry.get("analysis_mode", "full")

    def get_processed_count(self) -> int:
        return len(self._data["processed_videos"])

    def get_last_refresh(self) -> str | None:
        return self._data.get("last_refresh")
