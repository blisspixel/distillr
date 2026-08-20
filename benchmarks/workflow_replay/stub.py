# pyright: strict
"""Deterministic LLM stub with optional simulated provider wait."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from benchmarks.workflow_replay.fixtures import REPLAY_MODEL
from distill.llm.types import LLM_Response


@dataclass
class ReplayCallLog:
    """Counts stubbed model calls and simulated provider wait."""

    calls: int = 0
    provider_wait_ns: int = 0
    prompts: list[str] = field(default_factory=lambda: list[str]())


def make_llm_call(
    log: ReplayCallLog,
    *,
    body: str,
    wait_ns: int = 0,
) -> Callable[..., LLM_Response]:
    """Return an ``llm_call`` replacement that never touches a live provider."""

    def _call(
        config: object,
        workload_tag: str,
        prompt: str,
        **kwargs: object,
    ) -> LLM_Response:
        del config, workload_tag, kwargs
        if wait_ns > 0:
            time.sleep(wait_ns / 1_000_000_000)
        log.calls += 1
        log.provider_wait_ns += max(0, wait_ns)
        log.prompts.append(prompt)
        return LLM_Response(
            text=body,
            input_tokens=max(1, len(prompt) // 4),
            output_tokens=max(1, len(body) // 4),
            model=REPLAY_MODEL,
            provider_name="replay",
            provider_type="stub",
            usage_source="replay",
        )

    return _call
