"""Local preference and explicit, priced OpenRouter editorial routes."""

from __future__ import annotations

from distill.editorial.perspective import Perspective
from distill.llm.cost import has_known_pricing
from distill.llm.cost_policy import CostPolicyError, classify_provider, local_provider_endpoint
from distill.llm.router import RouterConfig


def local_available(provider: str, model: str) -> bool:
    import httpx

    if not model or classify_provider(provider) != "local":
        return False
    base = local_provider_endpoint(provider).rstrip("/")
    url = base + ("/api/tags" if provider == "ollama" else "/models")
    try:
        response = httpx.get(url, timeout=3, follow_redirects=False, trust_env=False)
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("models" if provider == "ollama" else "data", [])
        return any(
            isinstance(row, dict) and row.get("name" if provider == "ollama" else "id") == model
            for row in rows
        )
    except (httpx.HTTPError, ValueError, AttributeError, TypeError):
        return False


def select_routes(
    perspective: Perspective, base: RouterConfig, *, paid_only: bool = False
) -> tuple[dict[str, RouterConfig], str]:
    routes = perspective.routes
    use_local = not paid_only and local_available(routes.local_provider, routes.local_model)
    if use_local:
        provider = routes.local_provider
        models = dict.fromkeys(("research", "writer", "refiner", "critic"), routes.local_model)
        reason = "Configured local model is available on a loopback endpoint."
    else:
        if base.cost_mode == "no-metered" or not perspective.budget.allow_metered:
            raise CostPolicyError(
                "No configured local model is available. Set routes.local_model or explicitly "
                "enable budget.allow_metered. Quota CLI adapters are not yet qualified."
            )
        provider = "openrouter"
        models = {
            "research": routes.research_model,
            "writer": routes.writer_model,
            "refiner": routes.refinement_model,
            "critic": routes.critic_model,
        }
        if not all(has_known_pricing(model) for model in models.values()):
            raise CostPolicyError(
                "Every metered editorial model must have registered token pricing"
            )
        reason = "Explicit OpenRouter opt-in under per-run and persistent weekly dollar ceilings."
    configs = {}
    for role, model in models.items():
        config = base.model_copy(
            update={
                "provider": provider,
                "model": model,
                "report_provider": provider,
                "cost_mode": "no-metered" if use_local else "paid-ok",
                "fallback_provider": "",
                "fallback_model": "",
                "openrouter_zdr": True,
            }
        )
        config.validate_config("report")
        configs[role] = config
    return configs, reason
