# Grok 4.6 default migration

As verified on 2026-08-13, xAI documents `grok-4.6` as its flagship text and
code model. Distill uses it as the default for analysis, reranking, synthesis,
site and paper work, briefs, and ordered report section writing.

This is a default change, not a forced migration. Existing environment and
per-workload overrides keep their configured model IDs. A user who pinned
`grok-4.5` or `grok-4.3` continues to use that model and its registered price.

## Current registry facts

| Model | Short input per 1M | Short output per 1M | Long input per 1M | Long output per 1M | Context | Distill status |
|---|---:|---:|---:|---:|---:|---|
| `grok-4.6` | $2.00 | $6.00 | $4.00 | $12.00 | 500K | Default |
| `grok-4.5` | $2.00 | $6.00 | $4.00 | $12.00 | 500K | Supported explicit override |
| `grok-4.3` | $1.25 | $2.50 | $2.50 | $5.00 | 1M | Supported explicit override |
| `grok-4.20` family | $1.25 | $2.50 | $2.50 | $5.00 | 1M | Supported explicit override |

xAI applies the long-context rates to every token in a request once its prompt
reaches 200K tokens. Distill now applies that boundary per provider call in
estimates, authorization, budget enforcement, and the usage ledger. Cached
input can cost less at the provider, but Distill does not yet receive a
provider-accurate cached-token count, so its authorization estimate uses the
uncached rate.

The source of truth for availability and context is the
[xAI model catalog](https://docs.x.ai/developers/models). The
[xAI pricing table](https://docs.x.ai/developers/pricing) is authoritative for
the short and long token rates. Distill keeps pricing and context metadata in
code so estimates, budget authorization, chunk sizing, and provider selection
move together.

## What changes automatically

- New default configuration resolves xAI workloads to `grok-4.6`.
- `distill eval` uses `grok-4.6` as the xAI reference when no model is supplied.
- Cold-start cost estimates use the `grok-4.6` token rates.
- Single requests at or above 200K prompt tokens use xAI's long-context rates.
- Chunk planning uses the documented 500K context window.
- Configured reasoning effort is sent to `grok-4.6`, `grok-4.5`, and supported
  `grok-4.3` overrides.

The short-context rates are unchanged from Grok 4.5, so ordinary cold-start
estimates retain the same dollar values. A real run can still use a different
number of tokens because model tokenization and output behavior may differ.

## What does not change automatically

- Existing `.env` model overrides are not rewritten.
- Historical cost rows keep their recorded model ID and registry price.
- No quality claim is inferred from a newer model number. A paid
  `distill eval` is optional and should run only with an explicit budget.
- Gemini Deep Research remains separate from the default corpus report. The
  accordion and deep-research profiles keep the current
  `deep-research-preview-04-2026` agent ID.

## Pinning the previous model

To retain Grok 4.5 deliberately:

```dotenv
DISTILL_FAST_MODEL=grok-4.5
DISTILL_PREMIUM_MODEL=grok-4.5
DISTILL_SITE_MODEL=grok-4.5
DISTILL_ACCORDION_MODEL=grok-4.5
```

Legacy `XAI_*` model variables and `ACCORDION_SECTION_MODEL` remain supported
as migration aliases. Prefer the `DISTILL_*` names for new configuration.

`distill provider show`, `distill provider list xai`, public-contract checks,
and the default test suite do not call a model provider. If you choose to run
`distill eval`, inspect its estimate and approve metered work only when the
projected budget fits.
