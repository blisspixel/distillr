"""Honesty guards on the local speed probe.

Feature: local-speed
"""

from __future__ import annotations

from distill.llm.types import LLM_Response
from distill.pipeline.speed_probe import (
    WARM_LOAD_SECONDS,
    ModelSpeed,
    build_probe_prompt,
    speed_from_response,
)


def _response(
    *,
    input_tokens: int = 1024,
    output_tokens: int = 64,
    load: float = 0.0,
    prefill: float = 8.0,
    decode: float = 4.0,
) -> LLM_Response:
    return LLM_Response(
        text="x",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model="m",
        load_seconds=load,
        prefill_seconds=prefill,
        decode_seconds=decode,
        num_ctx=8192,
    )


class TestProbePrompt:
    """A cached prefill reports a physically impossible rate, so defeat it."""

    def test_nonce_leads_so_the_prefix_cache_misses(self) -> None:
        first, second = build_probe_prompt(256), build_probe_prompt(256)

        assert first != second
        # Prefix caching matches from the start; a trailing nonce would leave
        # the whole body cacheable and the measurement meaningless.
        assert first[:16] != second[:16]

    def test_prompt_scales_with_the_requested_size(self) -> None:
        assert len(build_probe_prompt(1024)) > len(build_probe_prompt(128))

    def test_degenerate_size_still_builds_a_prompt(self) -> None:
        assert build_probe_prompt(0)


class TestRates:
    def test_rates_come_from_phase_timings_not_wall_clock(self) -> None:
        speed = speed_from_response(
            "m", "ollama", warmup=_response(load=30.0), measured=_response()
        )

        assert speed.prefill_tokens_per_second == 1024 / 8.0
        assert speed.decode_tokens_per_second == 64 / 4.0
        assert speed.cold_load_seconds == 30.0
        assert speed.usable is True

    def test_missing_timings_yield_zero_not_a_division_error(self) -> None:
        """Every provider timing field is optional and absent when zero."""
        blank = _response(prefill=0.0, decode=0.0)
        speed = speed_from_response("m", "ollama", warmup=blank, measured=blank)

        assert speed.prefill_tokens_per_second == 0.0
        assert speed.decode_tokens_per_second == 0.0
        assert speed.usable is False


class TestReloadGuard:
    """A reload during the measured call is not inference time."""

    def test_reload_marks_the_sample_unusable(self) -> None:
        speed = speed_from_response(
            "m",
            "ollama",
            warmup=_response(load=30.0),
            measured=_response(load=WARM_LOAD_SECONDS + 0.1),
        )

        assert speed.reloaded_during_measure is True
        assert speed.usable is False  # rates exist but must not be published

    def test_a_warm_call_is_usable(self) -> None:
        speed = speed_from_response(
            "m",
            "ollama",
            warmup=_response(load=30.0),
            measured=_response(load=WARM_LOAD_SECONDS - 0.1),
        )

        assert speed.reloaded_during_measure is False
        assert speed.usable is True

    def test_an_errored_probe_is_never_usable(self) -> None:
        speed = ModelSpeed(model="m", provider="ollama", outcome="error", error="boom")

        assert speed.usable is False
