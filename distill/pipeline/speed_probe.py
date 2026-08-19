# pyright: strict
"""Measure local model inference speed from the provider's own counters.

Local runtimes report three phases separately: loading weights, prefilling the
prompt, and decoding output. Only the last two are rates, and mixing the load in
understates decode by 20x or more on a cold call -- measured here at 1.22 tok/s
against a true 24.51 on the same request.

Two calls per model:

1. A warm-up that exists only to pay, and report, the cold load.
2. One measured call whose single response carries both rates.

One measured call rather than separate prefill and decode probes is deliberate.
The context window is sized per request, and changing it forces the runtime to
reload the weights -- a reload measured at 4.8s on an already-resident model.
Two probes would silently pay that and attribute it to the model.

The prompt is prefixed with a nonce because prefix caching will otherwise return
a cached prefill and report a physically impossible rate (28,637 tok/s observed
on a repeat of an identical prompt).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from distill.llm.types import LLM_Response

__all__ = ["ModelSpeed", "build_probe_prompt", "release_model", "speed_from_response"]

# Below this, the runtime answered from resident weights rather than reloading.
# Measured separation on real hardware: 0.31s warm against 4.79s for a reload.
logger = logging.getLogger(__name__)

WARM_LOAD_SECONDS = 1.0
_RELEASE_TIMEOUT_SECONDS = 10.0

# Roughly four characters per token; the exact ratio does not matter because the
# rate is computed from the token count the server reports, not from this guess.
_CHARS_PER_TOKEN = 4

_FILLER = (
    "Knowledge graphs represent entities and the relations between them. "
    "Temporal knowledge graphs add a time dimension so that a fact holds over "
    "an interval rather than forever. Retrieval over such a graph must respect "
    "that interval or it will surface facts that were true once and are not now. "
)


@dataclass(frozen=True)
class ModelSpeed:
    """One machine's measured rates for one model."""

    model: str
    provider: str
    # "pp" (prompt processing) and "tg" (text generation) in llama.cpp's
    # vocabulary, which the local-inference ecosystem uses as its lingua franca.
    prefill_tokens: int = 0
    prefill_seconds: float = 0.0
    decode_tokens: int = 0
    decode_seconds: float = 0.0
    # Time to first usable runner. This is load *plus* scheduler queue wait
    # and any eviction of another model -- the provider measures it from
    # request entry, so calling it pure weight-load time would overstate it.
    cold_load_seconds: float = 0.0
    num_ctx: int = 0
    reloaded_during_measure: bool = False
    outcome: str = "success"
    error: str = ""

    @property
    def prefill_tokens_per_second(self) -> float:
        return self.prefill_tokens / self.prefill_seconds if self.prefill_seconds > 0 else 0.0

    @property
    def decode_tokens_per_second(self) -> float:
        """Decode rate over all generated tokens.

        Divides by the full token count, matching Ollama's own reported rate.
        llama.cpp and vLLM divide by count-1 because their first token falls out
        of the prompt batch, so their numbers run slightly higher on short runs.
        """
        return self.decode_tokens / self.decode_seconds if self.decode_seconds > 0 else 0.0

    @property
    def usable(self) -> bool:
        """True when both rates were measured on a run we can stand behind."""
        return (
            self.outcome == "success"
            and self.prefill_tokens_per_second > 0
            and self.decode_tokens_per_second > 0
            and not self.reloaded_during_measure
        )


def build_probe_prompt(prefill_tokens: int) -> str:
    """A prompt of roughly ``prefill_tokens`` tokens that cannot be cache-hit.

    The nonce leads, because prefix caching matches from the start -- a trailing
    nonce would leave the whole body cacheable and the measurement meaningless.
    """
    nonce = uuid.uuid4().hex
    target_chars = max(prefill_tokens, 1) * _CHARS_PER_TOKEN
    body = (_FILLER * (target_chars // len(_FILLER) + 1))[:target_chars]
    return f"{nonce}\n{body}\nSummarize the passage above in complete sentences."


def speed_from_response(
    model: str,
    provider: str,
    *,
    warmup: LLM_Response,
    measured: LLM_Response,
) -> ModelSpeed:
    """Turn a warm-up and a measured response into one honest result."""
    return ModelSpeed(
        model=model,
        provider=provider,
        prefill_tokens=measured.input_tokens,
        prefill_seconds=measured.prefill_seconds,
        decode_tokens=measured.output_tokens,
        decode_seconds=measured.decode_seconds,
        cold_load_seconds=warmup.load_seconds,
        num_ctx=measured.num_ctx,
        # A reload during the measured call means its timings include work that
        # is not inference, so the rates are not publishable.
        reloaded_during_measure=measured.load_seconds >= WARM_LOAD_SECONDS,
    )


async def release_model(base_url: str, model: str, *, trust_env: bool = False) -> None:
    """Unload one model so the next measurement starts from a clean machine.

    A benchmark must hold exactly one model at a time. Leaving the previous one
    resident lets the two compete for memory, which shows up as a slower rate
    for whichever loaded second -- an artefact of the sweep, not a property of
    the model. Sending ``keep_alive: 0`` with no prompt is the runtime's own
    unload primitive; it generates nothing.

    Best-effort by design: a failed unload costs a slightly noisier next sample,
    which is not worth failing a sweep over.
    """
    import httpx

    try:
        async with httpx.AsyncClient(
            timeout=_RELEASE_TIMEOUT_SECONDS, trust_env=trust_env
        ) as client:
            await client.post(
                f"{base_url}/api/generate",
                json={"model": model, "keep_alive": 0},
            )
    except Exception as exc:
        logger.debug("Could not release Ollama model '%s': %s", model, exc)
