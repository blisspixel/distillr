"""Doctor check + probe helpers, extracted from the _logic monolith.

Pure-ish validators the `distill doctor` command (and the init wizard + MCP
doctor tool) call: retired-model detection, provider auth-error classification,
and live key validation. Kept in the `distill.doctor` package (beside hardware /
recommendations / quality_gate) so the command layer and the MCP layer share one
canonical implementation and cannot drift. No console output here -- callers
present the results.
"""

# pyright: strict

from __future__ import annotations

import json
import logging
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic
from typing import Any, Literal, Protocol, cast

from distill.config import DistillConfig
from distill.llm.cost_policy import route_block_reason
from distill.llm.providers._ollama_registry import model_can_complete
from distill.llm.providers._usage import conservative_usage, usage_or_conservative
from distill.pipeline.costs import (
    BudgetExceededError,
    CostTracker,
    TokenUsage,
    save_run_log,
)

logger = logging.getLogger(__name__)

type DoctorKeyStatus = Literal[
    "ok",
    "invalid",
    "unknown",
    "missing",
    "not_set",
    "skipped",
]

_DOCTOR_TRACKER: ContextVar[CostTracker | None] = ContextVar(
    "distill_doctor_tracker",
    default=None,
)
_DOCTOR_COMMAND = "doctor"
_DOCTOR_CALL_TYPE = "doctor-key-validation"
_PROBE_PROMPT = "hi"
_LMSTUDIO_MODELS_RESPONSE_BYTES = 1024 * 1024
_LMSTUDIO_MAX_MODELS = 256
_LMSTUDIO_MAX_MODEL_FIELDS = 32
_LMSTUDIO_MAX_MODEL_ID_CHARS = 512
_LMSTUDIO_MODELS_TOTAL_SECONDS = 10.0


@contextmanager
def doctor_key_validation_session(config: DistillConfig) -> Generator[CostTracker, None, None]:
    """Aggregate live key-probe usage into one durable doctor ledger row."""

    active = _DOCTOR_TRACKER.get()
    if active is not None:
        yield active
        return

    tracker = CostTracker(budget=config.cost_workflow_budgets_usd.get(_DOCTOR_COMMAND))
    token = _DOCTOR_TRACKER.set(tracker)
    try:
        yield tracker
    finally:
        try:
            if tracker.entries:
                save_run_log(
                    config.library_dir,
                    _DOCTOR_COMMAND,
                    tracker,
                    metadata={
                        "workflow": _DOCTOR_COMMAND,
                        "operation": "key-validation",
                    },
                )
        finally:
            _DOCTOR_TRACKER.reset(token)


def check_retired_models(config: DistillConfig) -> list[str]:
    """Check all model config fields against the retired-model registry.

    Returns a list of warning strings for any configured model that is retired.
    Each warning includes the field name, model name, retirement date, and replacement.
    """
    from distill.llm.router import RETIRED_MODELS, RETIREMENT_DATE

    model_fields = [
        "xai_fast_model",
        "xai_premium_model",
        "xai_analysis_model",
        "xai_rerank_model",
        "xai_synthesis_model",
        "xai_site_model",
        "accordion_section_model",
    ]
    warnings: list[str] = []
    for field in model_fields:
        value = getattr(config, field, "")
        if value and value in RETIRED_MODELS:
            replacement = RETIRED_MODELS[value]
            warnings.append(
                f"{field} uses retired model '{value}' "
                f"(retiring {RETIREMENT_DATE}); replace with '{replacement}'"
            )
    return warnings


def _doctor_key_auth_rejected(exc: Exception) -> bool:
    """True if ``exc`` is a provider auth rejection (HTTP 401/403).

    Tells a genuine bad-key rejection apart from a transient failure
    (offline / timeout / rate-limit / provider 5xx): only the former means the
    key is dead. Handles the openai (``status_code``), google-genai (``code``),
    and httpx (``response.status_code``) exception shapes.
    """
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(exc, "code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return status in (401, 403)


def doctor_validate_key(
    provider: str,
    config: DistillConfig,
    *,
    live: bool = True,
    model: str = "",
) -> tuple[DoctorKeyStatus, str]:
    """Return provider-key health, optionally probing one exact model."""
    if not live:
        return _doctor_key_presence(provider, config)
    tracker = _DOCTOR_TRACKER.get()
    if tracker is not None:
        return _doctor_validate_key(provider, config, tracker, model=model)
    with doctor_key_validation_session(config) as owned_tracker:
        return _doctor_validate_key(provider, config, owned_tracker, model=model)


def _doctor_key_presence(provider: str, config: DistillConfig) -> tuple[DoctorKeyStatus, str]:
    fields = {
        "xai": "xai_api_key",
        "gemini": "gemini_api_key",
        "anthropic": "anthropic_api_key",
        "openai": "openai_api_key",
    }
    field = fields.get(provider)
    if field is None:
        raise ValueError(f"unknown provider: {provider}")
    if not getattr(config, field):
        return ("missing" if provider == "xai" else "not_set", "")
    return (
        "unknown",
        "Configured but not live-validated through MCP; run `distill doctor` locally.",
    )


def _doctor_validate_key(
    provider: str,
    config: DistillConfig,
    tracker: CostTracker,
    *,
    model: str = "",
) -> tuple[DoctorKeyStatus, str]:  # pyright: ignore[reportUnusedFunction] "called through the public doctor_validate_key seam"
    """Live-validate one provider's API key with a minimal request.

    Returns ``(status, detail)`` where ``status`` is one of:

    - ``"ok"`` -- the key is present and accepted by the provider
    - ``"invalid"`` -- the key is present but the provider rejected it with an
      auth error (401/403: revoked, expired, wrong project)
    - ``"unknown"`` -- the key is present but could not be verified due to a
      transient error (offline, timeout, rate limit, provider 5xx); ``detail``
      carries the error. This is NOT a key failure and must not be reported as
      "rejected" -- doing so was a false alarm on every flaky-network run.
    - ``"skipped"`` -- the key is present, but the active cost policy refuses
      a live provider request. ``detail`` carries the policy refusal.
    - ``"missing"`` -- a required key (xai) is unset
    - ``"not_set"`` -- an optional key (gemini/anthropic/openai) is unset

    On ``"ok"``, ``detail`` is the human label shown next to the key.

    Both the human and ``--json`` doctor paths call this so they cannot drift.
    Presence alone is not health -- a revoked key is *present* but dead -- and
    it was exactly a presence-only ``--json`` check disagreeing with the live
    human check that let a dead key report as healthy.
    """
    if provider == "xai":
        return _validate_xai_key(config, tracker, model=model)
    if provider == "gemini":
        return _validate_gemini_key(config, tracker, model=model)
    if provider == "anthropic":
        return _validate_anthropic_key(config, tracker, model=model)
    if provider == "openai":
        return _validate_openai_key(config, tracker, model=model)
    raise ValueError(f"unknown provider: {provider}")


def _key_error_status(exc: Exception) -> DoctorKeyStatus:
    return "invalid" if _doctor_key_auth_rejected(exc) else "unknown"


def _cost_policy_skip(
    provider: str,
    config: DistillConfig,
) -> tuple[DoctorKeyStatus, str] | None:
    """Return an explicit skip result when a live key probe is not allowed."""

    blocked = route_block_reason(
        cost_mode=config.distill_cost_mode,
        provider=provider,
        workload="doctor-key-validation",
    )
    if not blocked:
        return None
    return ("skipped", blocked)


def _probe_usage(
    *,
    provider: str,
    model: str,
    max_tokens: int,
    input_value: object,
    output_value: object,
) -> TokenUsage:
    input_tokens, output_tokens, estimated = usage_or_conservative(
        input_value,
        output_value,
        prompt=_PROBE_PROMPT,
        output_text="",
        max_tokens=max_tokens,
    )
    return TokenUsage(
        prompt_tokens=input_tokens,
        completion_tokens=output_tokens,
        model=model,
        call_type=_DOCTOR_CALL_TYPE,
        provider_name=provider,
        provider_type="cloud",
        usage_source="conservative" if estimated else "reported",
    )


def _conservative_probe_usage(
    *,
    provider: str,
    model: str,
    max_tokens: int,
    outcome: str,
    error_type: str = "",
) -> TokenUsage:
    input_tokens, output_tokens = conservative_usage(
        prompt=_PROBE_PROMPT,
        max_tokens=max_tokens,
    )
    return TokenUsage(
        prompt_tokens=input_tokens,
        completion_tokens=output_tokens,
        model=model,
        call_type=_DOCTOR_CALL_TYPE,
        provider_name=provider,
        provider_type="cloud",
        usage_source="conservative",
        outcome=outcome,
        error_type=error_type,
    )


def _authorize_probe(
    tracker: CostTracker,
    *,
    provider: str,
    model: str,
    max_tokens: int,
) -> tuple[DoctorKeyStatus, str] | None:
    try:
        tracker.authorize_token_usage(
            _conservative_probe_usage(
                provider=provider,
                model=model,
                max_tokens=max_tokens,
                outcome="authorized",
            )
        )
    except BudgetExceededError as exc:
        return ("skipped", str(exc))
    return None


def _record_probe_failure(
    tracker: CostTracker,
    *,
    provider: str,
    model: str,
    max_tokens: int,
    exc: BaseException,
) -> None:
    tracker.record(
        _conservative_probe_usage(
            provider=provider,
            model=model,
            max_tokens=max_tokens,
            outcome="error",
            error_type=type(exc).__name__,
        )
    )


def _openai_compatible_probe_usage(
    response: object,
    *,
    provider: str,
    model: str,
    max_tokens: int,
) -> TokenUsage:
    usage = getattr(response, "usage", None)
    return _probe_usage(
        provider=provider,
        model=model,
        max_tokens=max_tokens,
        input_value=getattr(usage, "prompt_tokens", None),
        output_value=getattr(usage, "completion_tokens", None),
    )


def _validate_xai_key(
    config: DistillConfig,
    tracker: CostTracker,
    *,
    model: str = "",
) -> tuple[DoctorKeyStatus, str]:
    if not config.xai_api_key:
        return ("missing", "")
    if skipped := _cost_policy_skip("xai", config):
        return skipped
    model = model or config.xai_model_for("analysis")
    max_tokens = 5
    if refused := _authorize_probe(
        tracker,
        provider="xai",
        model=model,
        max_tokens=max_tokens,
    ):
        return refused
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=config.xai_api_key.get_secret_value(),
            base_url="https://api.x.ai/v1",
            max_retries=0,
        )
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": _PROBE_PROMPT}],
            max_completion_tokens=max_tokens,
        )
    except BaseException as exc:
        _record_probe_failure(
            tracker,
            provider="xai",
            model=model,
            max_tokens=max_tokens,
            exc=exc,
        )
        if isinstance(exc, Exception):
            return (_key_error_status(exc), str(exc))
        raise
    tracker.record(
        _openai_compatible_probe_usage(
            response,
            provider="xai",
            model=model,
            max_tokens=max_tokens,
        )
    )
    return ("ok", model)


def _validate_gemini_key(
    config: DistillConfig,
    tracker: CostTracker,
    *,
    model: str = "",
) -> tuple[DoctorKeyStatus, str]:
    if not config.gemini_api_key:
        return ("not_set", "")
    if skipped := _cost_policy_skip("gemini", config):
        return skipped
    model = model or "gemini-3.7-flash"
    max_tokens = 5
    if refused := _authorize_probe(
        tracker,
        provider="gemini",
        model=model,
        max_tokens=max_tokens,
    ):
        return refused
    try:
        from google import genai

        client = genai.Client(api_key=config.gemini_api_key.get_secret_value())
        response: Any = client.models.generate_content(  # pyright: ignore[reportUnknownMemberType] "third-party google-genai stub is partially untyped; consistent with other providers in llm/"
            model=model,
            contents=_PROBE_PROMPT,
            config={"max_output_tokens": max_tokens},
        )
    except BaseException as exc:
        _record_probe_failure(
            tracker,
            provider="gemini",
            model=model,
            max_tokens=max_tokens,
            exc=exc,
        )
        if isinstance(exc, Exception):
            return (_key_error_status(exc), str(exc))
        raise
    usage: Any = getattr(response, "usage_metadata", None)
    tracker.record(
        _probe_usage(
            provider="gemini",
            model=model,
            max_tokens=max_tokens,
            input_value=getattr(usage, "prompt_token_count", None),
            output_value=getattr(usage, "candidates_token_count", None),
        )
    )
    return ("ok", model)


class _JsonResponse(Protocol):
    def json(self) -> object: ...


def _anthropic_probe_counts(response: object) -> tuple[object, object]:
    try:
        raw_payload = cast(_JsonResponse, response).json()
    except Exception:
        return None, None
    if not isinstance(raw_payload, dict):
        return None, None
    payload = cast(dict[object, object], raw_payload)
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None, None
    usage = cast(dict[object, object], usage)
    return usage.get("input_tokens"), usage.get("output_tokens")


def _validate_anthropic_key(
    config: DistillConfig,
    tracker: CostTracker,
    *,
    model: str = "",
) -> tuple[DoctorKeyStatus, str]:
    if not config.anthropic_api_key:
        return ("not_set", "")
    if skipped := _cost_policy_skip("anthropic", config):
        return skipped
    model = model or "claude-sonnet-5"
    max_tokens = 1
    if refused := _authorize_probe(
        tracker,
        provider="anthropic",
        model=model,
        max_tokens=max_tokens,
    ):
        return refused
    try:
        import httpx

        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": config.anthropic_api_key.get_secret_value(),
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": _PROBE_PROMPT}],
                "output_config": {"effort": "low"},
            },
            timeout=30,
        )
        response.raise_for_status()
    except BaseException as exc:
        _record_probe_failure(
            tracker,
            provider="anthropic",
            model=model,
            max_tokens=max_tokens,
            exc=exc,
        )
        if isinstance(exc, Exception):
            return (_key_error_status(exc), str(exc))
        raise
    input_tokens, output_tokens = _anthropic_probe_counts(response)
    tracker.record(
        _probe_usage(
            provider="anthropic",
            model=model,
            max_tokens=max_tokens,
            input_value=input_tokens,
            output_value=output_tokens,
        )
    )
    return ("ok", model)


def _validate_openai_key(
    config: DistillConfig,
    tracker: CostTracker,
    *,
    model: str = "",
) -> tuple[DoctorKeyStatus, str]:
    if not config.openai_api_key:
        return ("not_set", "")
    if skipped := _cost_policy_skip("openai", config):
        return skipped
    model = model or "gpt-4.1-mini"
    max_tokens = 5
    if refused := _authorize_probe(
        tracker,
        provider="openai",
        model=model,
        max_tokens=max_tokens,
    ):
        return refused
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=config.openai_api_key.get_secret_value(),
            max_retries=0,
        )
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": _PROBE_PROMPT}],
            max_tokens=max_tokens,
        )
    except BaseException as exc:
        _record_probe_failure(
            tracker,
            provider="openai",
            model=model,
            max_tokens=max_tokens,
            exc=exc,
        )
        if isinstance(exc, Exception):
            return (_key_error_status(exc), str(exc))
        raise
    tracker.record(
        _openai_compatible_probe_usage(
            response,
            provider="openai",
            model=model,
            max_tokens=max_tokens,
        )
    )
    return ("ok", model)


def check_ollama_status() -> tuple[str, list[str]]:
    """Public local-provider probe for CLI and MCP doctor surfaces."""
    from distill.llm.cost_policy import classify_provider

    if classify_provider("ollama") != "local":
        return ("unavailable", [])
    return _check_ollama_status()


def _check_ollama_status() -> tuple[str, list[str]]:  # pyright: ignore[reportUnusedFunction] "called via public check_ollama_status seam and tests through dynamic lookup"
    """Check if Ollama server is running and list available models.

    Returns (status, model_names) where status is "running", "unavailable"
    (nothing answered) or "unreadable" (it answered, we could not use it).
    Collapsing the second and third into one status reported a registry-parse
    regression as "not running", sending operators to restart a healthy server.
    """
    import asyncio

    try:
        from distill.llm.providers.ollama import OllamaProvider

        provider = OllamaProvider()
        try:
            models_data = asyncio.run(provider.list_models())
        except RuntimeError:
            loop = asyncio.get_event_loop()
            models_data = loop.run_until_complete(provider.list_models())
        named = [m for m in models_data if m.get("name")]
        # Completion-capable models first. Callers that suggest "configure this
        # one" take the head of this list, and an embedding-only model there is
        # advice that cannot work -- doctor used to tell operators to set
        # DISTILL_MODEL=nomic-embed-text. Every installed model still appears,
        # so the inventory the operator sees stays complete.
        named.sort(key=lambda m: not model_can_complete(m))
        return ("running", [str(m.get("name", "")) for m in named])
    except ConnectionError:
        return ("unavailable", [])
    except Exception:
        # The server answered but the response was unusable. Log the cause and
        # say so distinctly: "not running" would point at the wrong problem.
        logger.warning("Ollama responded but its model list was unreadable", exc_info=True)
        return ("unreadable", [])


def check_lmstudio_status() -> str:
    """Public LM Studio probe for CLI and MCP doctor surfaces."""
    from distill.llm.cost_policy import classify_provider

    if classify_provider("lmstudio") != "local":
        return "unavailable"
    return _check_lmstudio_status()


def _check_lmstudio_status() -> str:  # pyright: ignore[reportUnusedFunction] "called via public check_lmstudio_status seam and tests through dynamic lookup"
    """Check if LM Studio server is running. Returns 'running' or 'unavailable'."""
    import httpx

    try:
        import os

        url = os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
        with (
            httpx.Client(timeout=3, trust_env=False) as client,
            client.stream("GET", f"{url}/models") as response,
        ):
            if response.status_code == 200:
                return "running"
    except Exception:
        return "unavailable"
    return "unavailable"


def _reject_non_finite_json(value: str) -> object:
    raise ValueError(f"non-finite JSON constant: {value}")


def _validated_lmstudio_model_id(value: object) -> str:
    """Return one bounded model identifier, or empty for a non-string id."""

    if not isinstance(value, str):
        return ""
    model = value.strip()
    if len(model) > _LMSTUDIO_MAX_MODEL_ID_CHARS:
        raise ValueError("LM Studio model identifier is too long")
    if any(ord(character) < 32 or ord(character) == 127 for character in model):
        raise ValueError("LM Studio model identifier contains control characters")
    return model


def _parse_lmstudio_models(raw: bytes) -> list[str]:
    payload_obj: object = json.loads(
        raw.decode("utf-8"),
        parse_constant=_reject_non_finite_json,
    )
    if not isinstance(payload_obj, dict):
        raise ValueError("LM Studio model inventory must be an object")
    payload = cast(dict[str, object], payload_obj)
    data_obj = payload.get("data")
    if not isinstance(data_obj, list):
        raise ValueError("LM Studio model inventory has an invalid data list")
    data = cast(list[object], data_obj)
    if len(data) > _LMSTUDIO_MAX_MODELS:
        raise ValueError("LM Studio model inventory has an invalid data list")

    models: list[str] = []
    seen: set[str] = set()
    for entry_obj in data:
        if not isinstance(entry_obj, dict):
            continue
        entry = cast(dict[str, object], entry_obj)
        if len(entry) > _LMSTUDIO_MAX_MODEL_FIELDS:
            raise ValueError("LM Studio model entry has too many fields")
        model = _validated_lmstudio_model_id(entry.get("id"))
        if model and model not in seen:
            seen.add(model)
            models.append(model)
    return models


def check_lmstudio_models() -> tuple[str, list[str]]:
    """Check LM Studio and return a bounded list of exact loaded model ids."""
    import os

    import httpx

    from distill.llm.cost_policy import classify_provider

    if classify_provider("lmstudio") != "local":
        return ("unavailable", [])

    url = os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1").rstrip("/")
    started = monotonic()
    try:
        with (
            httpx.Client(timeout=3, trust_env=False) as client,
            client.stream("GET", f"{url}/models") as response,
        ):
            if response.status_code != 200:
                return ("unavailable", [])
            raw = bytearray()
            for chunk in response.iter_bytes():
                if monotonic() - started > _LMSTUDIO_MODELS_TOTAL_SECONDS:
                    return ("unavailable", [])
                if len(raw) + len(chunk) > _LMSTUDIO_MODELS_RESPONSE_BYTES:
                    return ("unavailable", [])
                raw.extend(chunk)
        return ("running", _parse_lmstudio_models(bytes(raw)))
    except Exception:
        return ("unavailable", [])
