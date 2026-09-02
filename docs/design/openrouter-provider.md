# OpenRouter provider

## Decision

Distill supports OpenRouter as an explicit metered analysis provider. It is an
escape hatch for operators who lack direct-provider quota or suitable local
inference and want access to multiple model families through one API key. It is
not a default route and does not enter an automatic fallback ladder.

## Route contract

Set `OPENROUTER_API_KEY`, select `DISTILL_PROVIDER=openrouter`, and supply one
concrete lowercase `author/model` slug. Dynamic router ids, moving `-latest`
aliases, and colon endpoint variants are refused. Stable identity is required
for evaluation, pricing, receipts, and comparisons across repeated runs.

The adapter uses OpenRouter's OpenAI-compatible chat endpoint with hidden SDK
retries disabled. Its provider preferences require supported parameters, deny
data-collection endpoints, sort eligible endpoints by price, permit same-model
upstream fallback, and request Zero Data Retention by default. Operators may set
`DISTILL_OPENROUTER_ZDR=false`, but doing so intentionally broadens the eligible
upstream pool. That setting only stops Distill from requiring ZDR on the
request. It cannot disable a stricter account-level or guardrail-level ZDR
policy.

Before inference, the adapter reads OpenRouter's no-cost endpoint capability
catalog and caches it for the provider instance. It filters capabilities by the
selected model, ZDR policy, endpoint health, reasoning support, and registered
price ceiling. The result selects `max_tokens` or `max_completion_tokens` and
omits an optional temperature only when no eligible endpoint advertises it.
`require_parameters=true` remains enabled, so OpenRouter cannot silently route
the request to an endpoint that ignores a requested parameter. If metadata is
unavailable, conservative model-family defaults are used and OpenRouter's own
strict routing remains the final gate.

Distill sends a one-way hash of the run UUID as OpenRouter's `session_id` so
related calls prefer the same upstream endpoint for prompt-cache locality
without disclosing the local correlation id. Router metadata is enabled, and
the officially selected endpoint is the primary source for the recorded
upstream provider. Distill does not opt into OpenRouter's beta response caching.
That feature can retain complete responses temporarily, while Distill
prioritizes fresh source analysis and predictable privacy behavior.

## Cost contract

OpenRouter is always a metered API route. `DISTILL_COST_MODE=no-metered` refuses
it before key or model validation. With a hard workflow or MCP budget, Distill
requires the underlying model to have registered pricing, conservatively
authorizes the prompt and maximum output, disables Distill retries for that
attempt, and sends the registered per-token prices as an upstream ceiling.

After a response, OpenRouter's finite nonnegative billed cost is authoritative
for the ledger. Token-derived registered pricing remains the fallback when
billed-cost metadata is absent or invalid. The resolved model and selected
upstream provider are retained in usage and provider telemetry.

HTTP 402 is treated as a permanent billing failure and is never retried. The
no-inference key doctor uses OpenRouter's key metadata endpoint and reports the
configured key spending limit and remaining allowance when they are available.

## Validation gate

Hermetic tests cover route validation, privacy and price preferences, exact
cost propagation, retry evidence, budget refusal, key diagnosis, configuration,
and eval routing. A release candidate also needs a live key check, a bounded
single-call smoke test, and representative `distill eval` evidence under an
operator-approved spend cap. Live provider checks are evidence, not CI gates.
