"""Is a usable model configured for a workload? (cloud key OR local provider).

The one question features should ask before deciding model-vs-fallback or
blocking a command: not "is XAI_API_KEY set?" but "does the router have a model
for this workload?". A keyless local provider (Ollama / LM Studio) counts, so a
local-only user is neither blocked nor silently dropped to a heuristic. See
docs/design/model-judgment-vs-brittle-fallbacks.md ("use what they have, never
assume a cloud key").
"""

from __future__ import annotations

from distill.llm.router import ConfigurationError, RouterConfig

__all__ = ["model_available"]


def model_available(workload: str = "") -> bool:
    """True when a model is configured and usable for ``workload``.

    Usable means the router's ``validate_config`` passes for the workload's
    resolved provider: a keyless local provider (ollama/lmstudio/agent), or a
    cloud provider whose key is present. Configuration level only -- a configured
    but unreachable local provider still returns True, and the caller's own
    error handling degrades gracefully at call time.
    """
    try:
        RouterConfig().validate_config(workload)
    except ConfigurationError:
        return False
    return True
