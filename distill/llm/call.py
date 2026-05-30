"""LLMCall dataclass — full request/response metadata for debugging and retry logging."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

__all__ = ["LLMCall"]


@dataclass(slots=True)
class LLMCall:
    """Captures full request/response metadata for a single LLM API call.

    Used for structured logging, retry tracking, and post-run debugging.
    """

    model: str
    prompt_hash: str
    prompt_text: str = ""
    temperature: float = 0.0
    max_tokens: int = 0
    response_text: str = ""
    response_tokens: int = 0
    latency_ms: int = 0
    error_message: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    attempt: int = 1

    @property
    def succeeded(self) -> bool:
        """True when the call completed without error."""
        return not self.error_message

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict suitable for JSONL output (all values JSON-serializable)."""
        return asdict(self)
