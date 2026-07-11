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

from typing import Literal

from distill.config import DistillConfig
from distill.llm.cost_policy import route_block_reason

type DoctorKeyStatus = Literal[
    "ok",
    "invalid",
    "unknown",
    "missing",
    "not_set",
    "skipped",
]


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


def doctor_validate_key(provider: str, config: DistillConfig) -> tuple[DoctorKeyStatus, str]:
    """Public API-key validation seam for CLI and MCP doctor surfaces."""
    return _doctor_validate_key(provider, config)


def _doctor_validate_key(provider: str, config: DistillConfig) -> tuple[DoctorKeyStatus, str]:  # pyright: ignore[reportUnusedFunction] "called via doctor command (commands/doctor.py and mcp) through dynamic lookup; not direct in this module"
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
        return _validate_xai_key(config)
    if provider == "gemini":
        return _validate_gemini_key(config)
    if provider == "anthropic":
        return _validate_anthropic_key(config)
    if provider == "openai":
        return _validate_openai_key(config)
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


def _validate_xai_key(config: DistillConfig) -> tuple[DoctorKeyStatus, str]:
    if not config.xai_api_key:
        return ("missing", "")
    if skipped := _cost_policy_skip("xai", config):
        return skipped
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=config.xai_api_key.get_secret_value(),
            base_url="https://api.x.ai/v1",
        )
        client.chat.completions.create(
            model=config.xai_model_for("analysis"),
            messages=[{"role": "user", "content": "hi"}],
            max_completion_tokens=5,
        )
        return ("ok", config.xai_model_for("analysis"))
    except Exception as e:
        return (_key_error_status(e), str(e))


def _validate_gemini_key(config: DistillConfig) -> tuple[DoctorKeyStatus, str]:
    if not config.gemini_api_key:
        return ("not_set", "")
    if skipped := _cost_policy_skip("gemini", config):
        return skipped
    try:
        from google import genai

        client = genai.Client(api_key=config.gemini_api_key.get_secret_value())
        client.models.generate_content(model="gemini-3.5-flash", contents="hi")  # pyright: ignore[reportUnknownMemberType] "third-party google-genai stub is partially untyped; consistent with other providers in llm/"
        return ("ok", "Deep Research")
    except Exception as e:
        return (_key_error_status(e), str(e))


def _validate_anthropic_key(config: DistillConfig) -> tuple[DoctorKeyStatus, str]:
    if not config.anthropic_api_key:
        return ("not_set", "")
    if skipped := _cost_policy_skip("anthropic", config):
        return skipped
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
                "model": "claude-sonnet-5",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "hi"}],
                "output_config": {"effort": "low"},
            },
            timeout=30,
        )
        response.raise_for_status()
        return ("ok", "claude-sonnet-5")
    except Exception as e:
        return (_key_error_status(e), str(e))


def _validate_openai_key(config: DistillConfig) -> tuple[DoctorKeyStatus, str]:
    if not config.openai_api_key:
        return ("not_set", "")
    if skipped := _cost_policy_skip("openai", config):
        return skipped
    try:
        from openai import OpenAI

        client = OpenAI(api_key=config.openai_api_key.get_secret_value())
        client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=5,
        )
        return ("ok", "optional")
    except Exception as e:
        return (_key_error_status(e), str(e))


def check_ollama_status() -> tuple[str, list[str]]:
    """Public local-provider probe for CLI and MCP doctor surfaces."""
    return _check_ollama_status()


def _check_ollama_status() -> tuple[str, list[str]]:  # pyright: ignore[reportUnusedFunction] "called via public check_ollama_status seam and tests through dynamic lookup"
    """Check if Ollama server is running and list available models.

    Returns (status, model_names) where status is "running" or "unavailable".
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
        model_names = [m.get("name", "") for m in models_data if m.get("name")]
        return ("running", model_names)
    except (ConnectionError, Exception):
        return ("unavailable", [])


def check_lmstudio_status() -> str:
    """Public LM Studio probe for CLI and MCP doctor surfaces."""
    return _check_lmstudio_status()


def _check_lmstudio_status() -> str:  # pyright: ignore[reportUnusedFunction] "called via public check_lmstudio_status seam and tests through dynamic lookup"
    """Check if LM Studio server is running. Returns 'running' or 'unavailable'."""
    import httpx

    try:
        import os

        url = os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
        with httpx.Client(timeout=3) as client:
            resp = client.get(f"{url}/models")
            if resp.status_code == 200:
                return "running"
    except Exception:
        return "unavailable"
    return "unavailable"
