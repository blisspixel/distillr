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

from distill.config import DistillConfig


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


def _doctor_validate_key(provider: str, config: DistillConfig) -> tuple[str, str]:  # pyright: ignore[reportUnusedFunction] "called via doctor command (commands/doctor.py and mcp) through dynamic lookup; not direct in this module"
    """Live-validate one provider's API key with a minimal request.

    Returns ``(status, detail)`` where ``status`` is one of:

    - ``"ok"`` -- the key is present and accepted by the provider
    - ``"invalid"`` -- the key is present but the provider rejected it with an
      auth error (401/403: revoked, expired, wrong project)
    - ``"unknown"`` -- the key is present but could not be verified due to a
      transient error (offline, timeout, rate limit, provider 5xx); ``detail``
      carries the error. This is NOT a key failure and must not be reported as
      "rejected" -- doing so was a false alarm on every flaky-network run.
    - ``"missing"`` -- a required key (xai) is unset
    - ``"not_set"`` -- an optional key (gemini/openai) is unset

    On ``"ok"``, ``detail`` is the human label shown next to the key.

    Both the human and ``--json`` doctor paths call this so they cannot drift.
    Presence alone is not health -- a revoked key is *present* but dead -- and
    it was exactly a presence-only ``--json`` check disagreeing with the live
    human check that let a dead key report as healthy.
    """
    if provider == "xai":
        if not config.xai_api_key:
            return ("missing", "")
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
            return (("invalid" if _doctor_key_auth_rejected(e) else "unknown"), str(e))
    if provider == "gemini":
        if not config.gemini_api_key:
            return ("not_set", "")
        try:
            from google import genai

            client = genai.Client(api_key=config.gemini_api_key.get_secret_value())
            client.models.generate_content(model="gemini-3.5-flash", contents="hi")  # pyright: ignore[reportUnknownMemberType] "third-party google-genai stub is partially untyped; consistent with other providers in llm/"
            return ("ok", "Deep Research")
        except Exception as e:
            return (("invalid" if _doctor_key_auth_rejected(e) else "unknown"), str(e))
    if provider == "openai":
        if not config.openai_api_key:
            return ("not_set", "")
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
            return (("invalid" if _doctor_key_auth_rejected(e) else "unknown"), str(e))
    raise ValueError(f"unknown provider: {provider}")


def _check_ollama_status() -> tuple[str, list[str]]:  # pyright: ignore[reportUnusedFunction] "called via doctor command through dynamic lookup; not direct in this module"
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


def _check_lmstudio_status() -> str:  # pyright: ignore[reportUnusedFunction] "called via doctor command through dynamic lookup; not direct in this module"
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
        pass
    return "unavailable"
