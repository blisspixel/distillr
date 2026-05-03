# pyright: strict
"""distill.llm — LLM router, provider abstraction, and telemetry.

Why this design: distill/llm/ is a foundational layer in the ROADMAP 0.3
restructure.  It has zero imports from other distill.* packages — configuration
is injected as a plain dataclass, not imported from distill.config.  This
enforces the dependency direction (nothing above llm/ is reachable from llm/)
and makes the package independently testable.  The Provider protocol uses
structural typing (typing.Protocol) so new backends require only a new module,
not inheritance.  11 correctness properties are verified via Hypothesis PBT.

Public API:
    call()              — dispatch an LLM call through the configured provider
    LLM_Response        — uniform response type from any provider
    RouterConfig        — configuration dataclass (injected, not imported)
    Provider            — structural protocol for provider backends
    ConfigurationError  — raised when router configuration is invalid
    PendingTaskError    — raised when an Agent mode task is awaiting processing
    LLMRouterError      — base exception for the LLM router package
"""

from distill.llm.providers import Provider
from distill.llm.router import (
    ConfigurationError,
    LLM_Response,
    LLMRouterError,
    PendingTaskError,
    RouterConfig,
    call,
)

__all__ = [
    "ConfigurationError",
    "LLMRouterError",
    "LLM_Response",
    "PendingTaskError",
    "Provider",
    "RouterConfig",
    "call",
]
