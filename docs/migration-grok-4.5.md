# Grok 4.5 default migration

This is the historical guide for the 2026-08-13 move to Grok 4.5. xAI now
documents Grok 4.6 as its flagship model, and current Distill releases default
to `grok-4.6`. See the [Grok 4.6 default migration](migration-grok-4.6.md) for
the active registry, pricing, context, and override behavior.

This is a default change, not a forced migration. Existing environment and
per-workload overrides keep their configured model IDs. A user who has pinned
`grok-4.3` continues to use `grok-4.3` and its registry price.

## Current registry facts

| Model | Input per 1M | Output per 1M | Context | Distill status |
|---|---:|---:|---:|---|
| `grok-4.5` | $2.00 | $6.00 | 500K | Supported explicit override |
| `grok-4.3` | $1.25 | $2.50 | 1M | Supported explicit override |
| `grok-4.20` family | $1.25 | $2.50 | 1M | Supported explicit override |

The source of truth for xAI model availability and pricing is the
[xAI model catalog](https://docs.x.ai/developers/models). Distill keeps pricing
and context metadata in code so estimates, budget authorization, chunk sizing,
and provider selection move together.

## What changed in that release

- New default configuration resolved xAI workloads to `grok-4.5`.
- `distill eval` used `grok-4.5` as the xAI reference when no model was supplied.
- Cold-start cost estimates used the `grok-4.5` token rates.
- Chunk planning uses the documented 500K context window.
- Configured reasoning effort is sent to both `grok-4.5` and supported
  `grok-4.3` overrides.

## What does not change automatically

- Existing `.env` model overrides are not rewritten.
- Historical cost rows keep the price associated with their recorded model.
- No quality claim is inferred from a newer model number. Run `distill eval`
  over representative fixtures before changing an explicitly calibrated route.
- Gemini Deep Research remains separate from the default corpus report. The
  accordion and deep-research profiles keep the current
  `deep-research-preview-04-2026` agent ID.

## Historical pinning example

To retain the prior xAI default deliberately:

```dotenv
DISTILL_FAST_MODEL=grok-4.3
DISTILL_PREMIUM_MODEL=grok-4.3
DISTILL_SITE_MODEL=grok-4.3
DISTILL_ACCORDION_MODEL=grok-4.3
```

Legacy `XAI_*` model variables and `ACCORDION_SECTION_MODEL` remain supported
as migration aliases. Prefer the `DISTILL_*` names for new configuration.

Run `distill doctor`, `distill eval`, and a dry-run estimate after changing any
route. Approve metered work only when the projected budget still fits.
