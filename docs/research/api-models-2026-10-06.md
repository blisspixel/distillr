# API model and SDK audit, October 6, 2026

## Decision and scope

Update current selectable analysis models, context limits, pricing, and SDK
compatibility through the existing router, cost registry, and provider adapters.
Keep the research desk's Python architecture and default routes. A newer model
becomes a default only after the `0.20.7` research-quality evaluation gate
demonstrates source faithfulness, receipt verification, uncertainty preservation,
and useful disagreement handling at an acceptable cost.

This review covers Distill's xAI, Gemini, Anthropic, and curated OpenRouter
analysis routes, the reserved OpenAI registry, and their installed SDK and
capture dependencies. It does not claim an exhaustive catalog of all models,
media-generation products, private previews, or account-specific availability.
Local model inventories remain discovered from the configured provider.

Evidence is dated October 6, 2026: public vendor documentation, the
unauthenticated OpenRouter catalog, published package metadata, and the installed
SDK types. No metered model call or developer service was used. Offline tests
prove request construction, response parsing, accounting, and refusal behavior;
they do not prove live access or research quality. Prices and aliases can change
after this review.

## Direct analysis routes

Prices below are standard uncached text input/output USD per million tokens.
Cached discounts, batch rates, tool charges, and media billing are separate.

| Provider | Current candidate | Context tokens | Input/output | Existing default |
| --- | --- | ---: | --- | --- |
| xAI | `grok-4.7` | 500,000 | $2/$6; $4/$12 for the full request at 200,000 or more input tokens | `grok-4.6` |
| Google | `gemini-3.8-flash` | 1,048,576 | $0.75/$3.75 through December 31, 2026; $1.50/$7.50 from January 1, 2027 | `gemini-3.7-flash` |
| Anthropic | `claude-sonnet-5-5` | 1,000,000 | $2/$10 | `claude-sonnet-5` |
| Anthropic | `claude-opus-5-5` | 1,000,000 | $4/$20 | Explicit selection |
| Anthropic | `claude-fable-5-1` | 1,000,000 | $10/$50 | Explicit selection; already registered |

Primary evidence: [xAI Grok 4.7](https://docs.x.ai/developers/models/grok-4.7),
[xAI pricing](https://docs.x.ai/developers/pricing),
[Gemini models](https://ai.google.dev/gemini-api/docs/models),
[Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing), and
[Claude model overview](https://platform.claude.com/docs/en/models/overview).

Grok 4.7 accepts reasoning effort; the existing workload policy uses low,
medium, or high. Its additional xhigh level does not change that policy.
Google's [3.8 migration guidance](https://ai.google.dev/gemini-api/docs/generate-content/latest-model)
deprecates temperature, top-p, and top-k and disallows minimal thinking.
Distill omits sampling for this family. Claude 5.5 also rejects custom sampling;
the existing native Messages adapter already omits it for those families.
Anthropic native IDs use hyphens for `5-5`, while OpenRouter uses `5.5`.

## Curated OpenRouter routes

The public [models API](https://openrouter.ai/api/v1/models) supplied exact route
IDs, context limits, and prices. This initial snapshot is preserved below;
the October 7 UTC follow-up supersedes the two qualified DeepSeek prices.
The snapshot is public catalog evidence rather
than a guarantee of an account's allowed endpoints. Existing runtime capability,
data-policy, and price gates still decide admission.

| Exact route | Context tokens | Input/output USD per million |
| --- | ---: | --- |
| `deepseek/deepseek-v4.1-flash` | 1,048,576 | $0.30/$1.20; retained default |
| `deepseek/deepseek-v4-pro-0813` | 1,048,576 | $0.66/$1.98 |
| `deepseek/deepseek-v4-pro` | 1,048,576 | $0.2088/$0.4176 |
| `deepseek/deepseek-v4-flash` | 1,048,576 | $0.03/$1.28 |
| `deepseek/deepseek-v3.2` | 163,840 | $0.28/$0.42 |
| `deepseek/deepseek-chat` | 163,840 | $0.2574/$1.0287 |
| `deepseek/deepseek-r1` | 64,000 | $0.70/$2.50 |
| `x-ai/grok-4.7` | 500,000 | $2/$6; $4/$12 at 200,000 or more input tokens |
| `google/gemini-3.8-flash` | 1,048,576 | $0.75/$3.75 at review time |
| `anthropic/claude-sonnet-5.5` | 1,000,000 | $2/$10 |
| `anthropic/claude-opus-5.5` | 1,000,000 | $4/$20 |
| `z-ai/glm-5.3-flash` | 1,048,576 | $0.15/$0.50 |
| `z-ai/glm-5.3-flashx` | 1,048,576 | $0.37/$1.25 |
| `z-ai/glm-5.3` | 1,048,576 | $0.07/$7 |
| `z-ai/glm-5.3-prime` | 1,000,000 | $2.80/$8.80 |
| `qwen/qwen3.8-flash` | 1,000,000 | $0.15/$0.47 |
| `qwen/qwen3.8-max-0902` | 1,000,000 | $2/$6 |
| `qwen/qwen3.8-max-prime` | 1,000,000 | $4/$12 |
| `qwen/qwen3.8-omni-flash` | 1,000,000 | $0.15/$0.47 for text |

OpenRouter GLM and legacy DeepSeek rates differ materially from the existing
bare supplier estimates. Exact routed rates now resolve before stripping the
author prefix.
The previous bare entries remain distinguishable. More expensive variants do
not inherit a cheaper family's estimate. Gemini routes retain the existing
date-based introductory-price cutover as a conservative planning policy;
OpenRouter's January 2027 price will require its own review.

The existing Gemini Deep Research and Max agent IDs remain the current published
`deep-research-preview-04-2026` and `deep-research-max-preview-04-2026` routes.
Google's [supported versions](https://ai.google.dev/gemini-api/docs/deep-research)
confirm them. Their retained per-query values are nonbinding planning
placeholders, since actual billing is based on underlying tokens and tools.

New and current OpenRouter candidates have context metadata. Known provider
prefixes are normalized through the existing route policy, so these routes
avoid the unknown-model 4096-token fallback when planning chunks.

## Reserved OpenAI registry

OpenAI remains unimplemented as a Distill analysis provider. Metadata for the
current GPT-6 Astra, GPT-6.1 Sol, and GPT-6 Luna models supports estimates and
future routing without claiming a callable route.

| Model | Context tokens | Input/output USD per million | Full-request rates above 272,000 input tokens |
| --- | ---: | --- | --- |
| `gpt-6-astra` | 1,050,000 | $10/$50 | $20/$75 |
| `gpt-6.1-sol` | 1,050,000 | $2/$10 | $4/$15 |
| `gpt-6-luna` | 1,050,000 | $0.10/$0.50 | $0.20/$0.75 |

Evidence: [OpenAI model comparison](https://developers.openai.com/api/docs/models/compare),
[standard and long-context pricing](https://developers.openai.com/api/docs/pricing),
and [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol).
Previous GPT-5.6 registry rates remain historical estimates; the review date
does not assert that every retained legacy entry is a current supplier price.
Stored usage and cost receipts are not rewritten.
Recomputed estimates use the registry's current policy; they are not historical
billing receipts.

## October 7 UTC follow-up and pricing qualifications

A direct public catalog read during release verification exposed a scheduled
pricing qualification that the initial snapshot did not preserve. DeepSeek
V4 Pro 0813 advertises discounted and full rates in UTC windows. Its weekday
discount applies at 00:00-01:00, 04:00-06:00, and 10:00-24:00 UTC, with the full
rate at 01:00-04:00 and 06:00-10:00 UTC; weekends use the discount. The registry
now authorizes at the full rate in every window, preserving the discount as
source context rather than treating it as an unconditional budget guarantee.

| Route | Initial snapshot | Follow-up public API | Release registry ceiling |
| --- | --- | --- | --- |
| `deepseek/deepseek-v4-pro-0813` | $0.66/$1.98 | $1.32/$3.96, with the scheduled $0.66/$1.98 override | $1.32/$3.96 |
| `deepseek/deepseek-v4.1-flash` | $0.30/$1.20 | $0.05/$1.20 | $0.30/$1.20, conservative |

The [public API](https://openrouter.ai/api/v1/models) and
[model page](https://openrouter.ai/deepseek/deepseek-v4-pro-0813) also show
different aggregate endpoint prices. The page displayed $0.30/$4.20 while the
API supplied the rates above; endpoint rows include different provider prices
and promotions. This does not establish one universally available price.
Distill constrains both price dimensions and supported parameters with the
existing endpoint gate. A route can therefore be unavailable under its ceiling
or privacy policy. Reported billed cost still outranks the registry estimate.
Flash's lower public minimum alone does not establish a qualifying endpoint
under Distill's default ZDR policy, so its higher input ceiling is retained.

The follow-up covered all 19 curated routes. All registered ceilings cover the
current public prices and scheduled overrides, with Grok's existing long-prompt
threshold applied separately. All context lengths matched. The other 17 routes
required no price revision. The four reviewed SDK and extractor versions also
matched PyPI's latest published stable versions. These were free metadata reads,
not model calls or account-specific access checks.

## SDK and capture maintenance

| Package | Previous lock | Reviewed lock | Reason and compatibility boundary |
| --- | --- | --- | --- |
| `openai` | 2.38.0 | 3.26.0 | Current published SDK; xAI and LM Studio use its compatible Chat Completions surface. Use the SDK's supported `DefaultHttpxClient` for local transport. |
| `google-genai` | 2.7.0 | 2.28.0 | Current published SDK; optional interaction IDs now require refusal before polling. |
| `mcp` | 2.2.0 | 2.3.0 | Compatible 2.x update, including Windows stdio and protocol validation fixes. |
| `yt-dlp` | 2026.7.4 | 2026.8.19 | Current stable extractor release; preserve confined fetching and child-process boundaries. |

Published metadata:
[OpenAI 3.26.0](https://pypi.org/project/openai/3.26.0/),
[Google GenAI 2.28.0](https://pypi.org/project/google-genai/2.28.0/),
[MCP 2.3.0](https://pypi.org/project/mcp/2.3.0/), and
[yt-dlp 2026.8.19](https://pypi.org/project/yt-dlp/2026.8.19/).
SDK guidance: [OpenAI libraries](https://developers.openai.com/api/docs/libraries),
[Google SDK releases](https://github.com/googleapis/python-genai/releases/tag/v2.28.0),
[MCP releases](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.3.0),
and [yt-dlp releases](https://github.com/yt-dlp/yt-dlp/releases/tag/2026.08.19).

Required lock changes also update Google Auth, jiter, and MCP types. The OpenAI
SDK no longer pulls tqdm into the default install. The existing HTTP stacks
remain: OpenAI uses its supported httpx2 client, and other adapters retain their
established transports. No new shared fetching or model-discovery layer is added.

The supported OpenAI and Google SDK majors are bounded in package metadata.
Disabled SDK retries, disabled LM Studio redirects, loopback proxy refusal,
conservative error accounting, and File Search cleanup are preserved. HTTP
status errors retain their identity even when a provider message contains
"refused"; this text alone does not mean the local server is unreachable.
Missing research IDs produce an explicit refusal without another remote request
and keep the original submission receipt.

## Next product boundary

Maintenance release `0.20.5` closes the API, routed billing, SDK compatibility,
and dependency security defects in this audit. It is inserted under the
roadmap's blocker rule. The next feature release is `0.20.6`: retire removed
assertions after reanalysis and preserve the origin of derived material.
`0.20.7` evaluates research quality, including the two-source disagreement
and later-correction episode. Remaining release scopes shift intact.

Budget checks retain conservative pre-contact reservation, one admitted attempt
with SDK retries disabled, separate admission of fallback, and billed-cost
precedence, including zero cost. Versioned routed IDs retain their routed
rates before supplier aliases. A bare response echo of the requested model
retains its author so missing cost metadata cannot switch the ledger to supplier
pricing. Unpriced metered routes and unbounded Deep Research fail closed
under a hard budget. Gemini output accounting includes thinking tokens.
OpenRouter requests require supported parameters and enforce prompt/completion
price ceilings with zero per-request fees. See
[routing prices](https://openrouter.ai/docs/guides/routing/provider-selection#max-price),
[Gemini thinking](https://ai.google.dev/gemini-api/docs/thinking), and
[Deep Research billing](https://ai.google.dev/gemini-api/docs/deep-research#availability-and-pricing).
These checks bound Distill's supported requests; they do not cap unrelated
account activity, credit purchase fees, taxes, or a provider changing its contract.

## Local verification

Completed October 6 Pacific time, October 7 UTC, on Windows with CPython
3.12.13. The initial audit used the `0.20.4` tree plus maintenance; the final
release candidate retains those baseline receipts and adds the billing checks
above. Final hosted receipts are linked from the release and its pull request.

- Frozen lock check and environment sync passed. Ruff lint and formatting,
  Pyright with warnings treated as failures, and all four import contracts
  passed.
- The full default suite passed: **7,493 passed, 4 skipped, 9 deselected** in
  837.83 seconds. Branch-enabled coverage reached **95.45%**, clearing the
  unchanged 95% floor. One upstream Starlette deprecation warning remains;
  it concerns AnyIO's renamed BlockingPortal alias.
- Bandit found no medium-or-higher severity issue. `pip-audit --skip-editable`
  found no known dependency vulnerabilities, without advisory exclusions.
- Public contract snapshots and both corpus and editorial Agent Skill
  distributions were current. Source, wheel, and skill archives built.
- An isolated installed-wheel check passed for runtime assets, bundled skill,
  security floors, exact locked SDK versions, current model metadata, local
  client construction, editorial defaults, and PDF extraction.
- All 19 curated OpenRouter routes matched the dated public catalog's standard
  text prices and context lengths. Real SDK tests used mocked HTTP transports
  for successful responses, rate limits, and local redirect refusal. Missing
  research IDs refused polling while retaining the submission receipt.

The final release candidate passed **7,503 tests**, with **95.46% branch-enabled
coverage**, 4 skips, 9 deselections, and the same single upstream warning, in
719.02 seconds on Windows/Python 3.12.13. This supersedes the initial full-suite
receipt for release gating. It also passed 132 focused cost, call-execution, and
real-SDK tests after the scheduled-pricing correction. Its rebuilt wheel passed
the isolated installation checks. The six retained native plugin cases and
their reports match their recorded hashes; skills, references, evals, and
runtime skill content are byte-identical to the successfully evaluated
`0.20.1` package. Only distribution version metadata and generated package
instructions change. This reuses authorized native behavior evidence without
claiming a new native run or a model-quality evaluation of the new candidates.

Hosted CI remains a separate blocking release gate: Linux Python 3.12-3.14,
macOS and Windows, lint, typing, imports, security, and build must pass for the
exact main commit before its tag can publish. Publication receipts belong to
the [0.20.5 release](https://github.com/blisspixel/distillr/releases/tag/v0.20.5)
and its linked workflow. These receipts do not establish live model access or
research quality.
