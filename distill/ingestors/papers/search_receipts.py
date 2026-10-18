"""Typed collection boundaries for bounded paper searches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

SearchStatus = Literal["successful", "successful-empty", "failed"]


@dataclass(frozen=True)
class SearchReceipt:
    query: str
    captured_at: str
    status: SearchStatus
    result_count: int
    reason: str = ""

    @classmethod
    def capture(cls, query: str, count: int, *, error: str = "") -> SearchReceipt:
        return cls(
            query=query,
            captured_at=datetime.now(UTC).isoformat(),
            status="failed" if error else ("successful" if count else "successful-empty"),
            result_count=count,
            reason=error[:240],
        )

    def to_row(self) -> dict[str, object]:
        return {
            "query": self.query,
            "captured_at": self.captured_at,
            "status": self.status,
            "result_count": self.result_count,
            "reason": self.reason,
        }

    @classmethod
    def from_row(cls, row: object) -> SearchReceipt:
        if not isinstance(row, dict):
            raise ValueError("Search receipt must be an object")
        query, captured, status, count, reason = (
            row.get("query"),
            row.get("captured_at"),
            row.get("status"),
            row.get("result_count"),
            row.get("reason", ""),
        )
        if not isinstance(query, str) or not isinstance(captured, str):
            raise ValueError("Search receipt query and time must be strings")
        if status not in ("successful", "successful-empty", "failed"):
            raise ValueError("Search receipt status is invalid")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("Search receipt count is invalid")
        if not isinstance(reason, str) or len(reason) > 240:
            raise ValueError("Search receipt reason is invalid")
        if (status == "successful" and count == 0) or (status != "successful" and count):
            raise ValueError("Search receipt status and count disagree")
        timestamp = datetime.fromisoformat(captured.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("Search receipt timestamp must include a timezone")
        if status == "successful":
            return cls(query, captured, "successful", count, reason)
        if status == "successful-empty":
            return cls(query, captured, "successful-empty", count, reason)
        return cls(query, captured, "failed", count, reason)
