# pyright: strict
"""Provider usage records shared by cost tracking and reporting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from distill.llm.cost import has_known_pricing
from distill.llm.usage import MAX_USAGE_TOKENS, LLMUsageAttempt

NO_METERED_PROVIDER_TYPES: frozenset[str] = frozenset({"local", "included-plan"})
EXTERNAL_COST_UNAVAILABLE_PROVIDER_TYPES: frozenset[str] = frozenset({"host-managed", "unknown"})


@dataclass
class TokenUsage:
    """Token usage from a single API call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    call_type: str = ""
    provider_name: str = ""
    provider_type: str = ""
    usage_source: str = "reported"
    outcome: str = "success"
    error_type: str = ""
    attempt_id: str = ""
    attempts: tuple[LLMUsageAttempt, ...] = ()

    def __post_init__(self) -> None:
        normalized_prompt = _bounded_usage_count(self.prompt_tokens)
        normalized_completion = _bounded_usage_count(self.completion_tokens)
        if (
            normalized_prompt != self.prompt_tokens
            or normalized_completion != self.completion_tokens
        ):
            self.usage_source = "conservative"
        self.prompt_tokens = normalized_prompt
        self.completion_tokens = normalized_completion

    @classmethod
    def from_response(cls, response: Any, *, call_type: str = "") -> TokenUsage:
        """Build a usage row from an LLM router response."""
        return cls(
            prompt_tokens=response.input_tokens,
            completion_tokens=response.output_tokens,
            model=response.model,
            call_type=call_type,
            provider_name=getattr(response, "provider_name", ""),
            provider_type=getattr(response, "provider_type", ""),
            usage_source=getattr(response, "usage_source", "unknown"),
            attempts=getattr(response, "usage_attempts", ()),
        )

    def expanded(self) -> tuple[TokenUsage, ...]:
        """Return one provider-accurate ledger row per captured request attempt."""

        if not self.attempts:
            return (self,)
        return tuple(
            TokenUsage(
                prompt_tokens=attempt.input_tokens,
                completion_tokens=attempt.output_tokens,
                model=attempt.model,
                call_type=self.call_type,
                provider_name=attempt.provider_name,
                provider_type=attempt.provider_type,
                usage_source=attempt.usage_source,
                outcome=attempt.outcome,
                error_type=attempt.error_type,
                attempt_id=attempt.attempt_id,
            )
            for attempt in self.attempts
        )

    @property
    def no_metered_cost(self) -> bool:
        """True only when topology or proved auth class establishes no metered cost."""
        return self.provider_type in NO_METERED_PROVIDER_TYPES

    @property
    def external_cost_unavailable(self) -> bool:
        """True when usage is known but Distill has no trustworthy price contract."""

        return self.provider_type in EXTERNAL_COST_UNAVAILABLE_PROVIDER_TYPES or (
            self.provider_type == "cloud"
            and self.provider_name in {"xai", "gemini", "anthropic", "openai"}
            and not has_known_pricing(self.model)
        )


@dataclass
class TranscriptionUsage:
    """One cloud speech-to-text call's audio duration and estimated cost."""

    provider: str = ""
    model: str = ""
    duration_s: float = 0.0
    cost: float = 0.0
    outcome: str = "completed"


def _bounded_usage_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_USAGE_TOKENS:
        return MAX_USAGE_TOKENS
    return value
