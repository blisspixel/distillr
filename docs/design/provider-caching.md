# Provider Caching Policy

Checked against current provider documentation on 2026-06-30.

Distill must treat provider-side prompt and context caches as an economic hint, not
as durable application state. Local durable intermediate caches remain a separate
feature because Distill owns those files, can inspect them, can invalidate them,
and can include them in reproducible audits. Provider caches are opaque,
provider-retained, TTL-bound, and may carry write, storage, rate-limit, or data
retention semantics that differ by route.

## Decision

Distill can use provider-side caching only after a provider adapter declares a
cache policy with these fields:

- Provider, platform, model family, and API surface.
- Cache mode: automatic, explicit breakpoint, explicit context object, sticky
  routing key, or unsupported.
- Minimum token threshold and cacheable prompt sections.
- TTL or retention policy, including whether the command can set it.
- Pricing classes for cache writes, cache reads, storage, and ordinary input.
- Usage telemetry fields for cached tokens, cache reads, cache writes, storage,
  and cache misses.
- Rate-limit effect, including whether cached tokens still count toward TPM.
- Retention and data residency statement from the provider docs.
- Cleanup semantics, including whether Distill can delete the cache or only wait
  for expiration.

Until that declaration exists, `no-metered` mode must treat provider caching as
irrelevant. A cache discount does not make an API route no-metered. A cached
token read still belongs in the usage ledger.

## Provider Snapshot

| Provider surface | Current behavior | Distill policy |
|---|---|---|
| Anthropic Claude API | Supports top-level automatic caching and explicit content-block breakpoints with `cache_control`; default TTL is 5 minutes, optional 1-hour TTL costs more; cache writes cost more than ordinary input and cache reads cost less. Usage reports `cache_creation_input_tokens` and `cache_read_input_tokens`. | Opt in only when the adapter can place breakpoints at stable prefixes, choose TTL, and ledger write and read tokens separately. Do not cache volatile per-request receipt text behind a breakpoint. |
| Amazon Bedrock | Optional prompt caching on supported on-demand models uses cache checkpoints, model-specific minimums, up to model-specific checkpoint limits, usually 5-minute TTL with some 1-hour support, and Bedrock-specific usage fields such as cache read and write tokens. Nova also has automatic prompt caching, but AWS recommends explicit caching for cost savings and consistency. | Treat Bedrock as its own policy, not as plain Anthropic. The adapter must use Bedrock field names, Bedrock TTL support, and Bedrock pricing before exposing a cache knob. Cross-region inference can reduce cache effectiveness or increase writes, so the ledger must record platform and region behavior. |
| OpenAI API | Prompt caching is automatic for supported recent models when prompts reach the token threshold. It supports `prompt_cache_key`, in-memory retention, and extended retention on supported models. Usage exposes `usage.prompt_tokens_details.cached_tokens`; cached tokens still count toward rate limits. | No generic enable flag is needed. Distill may add stable routing keys only after the adapter can log `cached_tokens`, selected retention, and rate-limit effect. Retention must be an explicit policy choice when the API supports it. |
| Azure OpenAI in Microsoft Foundry | Prompt caching is enabled by default for supported Azure OpenAI models, supports in-memory or extended retention where available, exposes `prompt_cache_retention`, requires identical first 1,024 tokens for hits, records `cached_tokens`, and does not share caches across Azure subscriptions. | Treat Azure OpenAI separately from OpenAI because retention defaults, regional behavior, deployment type discounts, and subscription isolation are Azure-specific. Provider config must include deployment type and retention policy. |
| Gemini generateContent API | Implicit caching is enabled for Gemini 2.5 and newer models. The generateContent API also supports explicit `cachedContents` resources with TTL, defaulting to 1 hour when TTL is not set, and explicit caches can be retrieved, patched for expiration, or deleted. Caching cost depends on token size and duration. | Explicit caches require lifecycle ownership. Distill may create them only for a command-scoped static prefix, must set a bounded TTL, must delete when possible, and must ledger cache creation, storage window, cached reads, and cleanup outcome. |
| Gemini Interactions API | Current Interactions API docs recommend the newer surface and support implicit caching only. Explicit cache objects are not supported there. Cached token hits appear in usage metadata. | Do not expose explicit-cache controls on Interactions routes. Stable-prefix shaping is allowed, but the adapter must ledger cache-hit telemetry when present. |
| Gemini Enterprise Agent Platform | Supports implicit caching and explicit context caches with TTL update and delete operations. Explicit cache reads receive provider discounts, but caches interact with implicit caching and can create additional retention unless caching is disabled or avoided. | Enterprise routes need a stricter retention profile: location, model, provider, TTL, delete result, and whether implicit caching was disabled. Do not reuse a cache across commands unless a future user-approved durable cache manifest exists. |
| xAI API | Prompt caching is automatic when consecutive requests share an exact starting message prefix. xAI recommends `x-grok-conv-id` for Chat Completions or `prompt_cache_key` for Responses to improve cache hits. Usage exposes cached-token fields, cached tokens are billed at a reduced rate, and entries can be evicted at any time. | Current xAI routes can benefit from stable prefix ordering, but Distill must not promise a cache hit or durable retention. Add routing keys only when the adapter records cached token counts and the selected key scope without leaking corpus identity. |

## Implementation Rules

1. Provider caches are never shared global mutable state unless a future design
   introduces a tracked cache manifest with explicit user approval.
2. Cache controls must be opt in per provider and per workload. Automatic
   provider behavior can be observed, but Distill must not hide it from usage
   reports.
3. Pre-warming is blocked unless the command can prove projected savings are
   positive, bounded by the workflow spend cap, and visible in the ledger before
   the write occurs.
4. Background refresh is blocked unless the command owns the lifecycle and stops
   refresh work before exit.
5. Cache misses must be normal success paths. Caching cannot be required for
   correctness, only for cost or latency.
6. The prompt builder must put stable reusable material before dynamic receipts,
   timestamps, user text, and run-specific IDs.
7. Usage logging must capture both total prompt tokens and provider-specific
   cached-token fields. For providers that split read and write tokens, log both.
8. `no-metered` mode cannot become permissive because a provider offers cached
   token discounts. The cost class remains metered unless route proof says
   otherwise.
9. Provider retention must be visible in docs and config. If the route cannot
   prove retention behavior, Distill must fail closed before enabling explicit
   cache controls.
10. Local durable LLM intermediate caching should live in a separate design and
    eventual utility. It must not reuse provider-cache policy names.

## Sources

- Anthropic Claude prompt caching, checked 2026-06-30:
  <https://platform.claude.com/docs/en/build-with-claude/prompt-caching>
- Amazon Bedrock prompt caching, checked 2026-06-30:
  <https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html>
- OpenAI API prompt caching, checked 2026-06-30:
  <https://developers.openai.com/api/docs/guides/prompt-caching>
- Azure OpenAI prompt caching in Microsoft Foundry, last updated 2026-05-13,
  checked 2026-06-30:
  <https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/prompt-caching>
- Google AI Gemini generateContent context caching, checked 2026-06-30:
  <https://ai.google.dev/gemini-api/docs/generate-content/caching>
- Google AI Gemini Interactions context caching, checked 2026-06-30:
  <https://ai.google.dev/gemini-api/docs/caching>
- Google Gemini Enterprise context cache overview, checked 2026-06-30:
  <https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/context-cache/context-cache-overview>
- xAI API prompt caching, last updated 2026-03-16, checked 2026-06-30:
  <https://docs.x.ai/developers/advanced-api-usage/prompt-caching>
- xAI API prompt caching usage and pricing, last updated 2026-05-10, checked
  2026-06-30:
  <https://docs.x.ai/developers/advanced-api-usage/prompt-caching/usage-and-pricing>
- Lumer et al., "Don't Break the Cache: An Evaluation of Prompt Caching for
  Long-Horizon Agentic Tasks", arXiv 2601.06007, 2026-01-09:
  <https://arxiv.org/abs/2601.06007>
