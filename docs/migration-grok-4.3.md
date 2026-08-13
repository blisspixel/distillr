# Grok 4.3 Migration Guide

xAI retired several models from the API effective **May 15, 2026 at 12:00pm
PT**. At retirement, xAI redirected those slugs to `grok-4.3` or the named
non-reasoning replacement and billed at the redirect target's rates. Current
Distill releases now substitute retired reasoning slugs to the `grok-4.6`
default before dispatch. See the [Grok 4.6 default migration](migration-grok-4.6.md)
for the current registry.

## Retired Models

| Retired Model | Replacement | Use Case |
|---|---|---|
| `grok-4-1-fast-reasoning` | `grok-4.6` | Reasoning workloads |
| `grok-4-1-fast-non-reasoning` | `grok-4.20-0309-non-reasoning` | Non-reasoning workloads |
| `grok-4-fast-reasoning` | `grok-4.6` | Reasoning workloads |
| `grok-4-fast-non-reasoning` | `grok-4.20-0309-non-reasoning` | Non-reasoning workloads |
| `grok-4-0709` | `grok-4.6` | Reasoning workloads |
| `grok-code-fast-1` | `grok-4.6` | Code generation |
| `grok-3` | `grok-4.6` | General reasoning |
| `grok-imagine-image-pro` | `grok-imagine-image` | Image generation |

## What distillr does automatically

Starting in **0.5.0**, distillr handles the transition gracefully:

1. **Default model policy updated.** All xAI default model references now point to `grok-4.6`. No action needed if you use defaults.
2. **Automatic fallback.** If your `.env` still references a retired model, distillr logs a deprecation warning and automatically substitutes the recommended replacement. Your runs will not break.
3. **`distill doctor` warns you.** Running `distill doctor` will flag any retired models in your configuration with the retirement date and recommended replacement.

## What you need to do

### If you use default settings (most users)

Nothing. The defaults are already updated to `grok-4.6`.

### If you have explicit model overrides in `.env`

Check your `.env` for any of these variables:

```bash
XAI_FAST_MODEL=...
XAI_PREMIUM_MODEL=...
XAI_ANALYSIS_MODEL=...
XAI_RERANK_MODEL=...
XAI_SYNTHESIS_MODEL=...
XAI_SITE_MODEL=...
ACCORDION_SECTION_MODEL=...
```

If any of them reference a retired model, update them:

```bash
# Before (will stop working May 15, 2026)
XAI_FAST_MODEL=grok-4-1-fast-reasoning
ACCORDION_SECTION_MODEL=grok-4-1-fast-reasoning

# After
DISTILL_FAST_MODEL=grok-4.6
DISTILL_ACCORDION_MODEL=grok-4.6
```

The older variable names remain accepted as migration aliases. A matching
`DISTILL_*` route variable takes precedence.

### Verify with `distill doctor`

```bash
distill doctor
```

If you have retired models configured, you'll see:

```
WARNING: xai_fast_model uses retired model 'grok-4-1-fast-reasoning'
   (retired May 15, 2026); replace with 'grok-4.6'
```

## Grok 4.3 Highlights

- **1 million token context window** - a 100K-char paper fits whole, no chunking needed
- **Priced at $1.25 / 1M input and $2.50 / 1M output** - cheaper than the models it replaces for most workloads
- **3 reasoning effort levels** - low, medium, high (configurable per workload)

## Reasoning Effort Configuration

Grok 4.3 supports three reasoning effort levels that trade off latency/cost against reasoning depth. distillr lets you configure this per workload via environment variables:

```bash
# Pattern: DISTILL_{WORKLOAD}_REASONING_EFFORT=low|medium|high

# Examples
DISTILL_ANALYSIS_REASONING_EFFORT=medium    # default for fast-tier
DISTILL_RERANK_REASONING_EFFORT=low         # speed up reranking
DISTILL_SITE_REASONING_EFFORT=high          # default for premium-tier
DISTILL_REPORT_REASONING_EFFORT=high        # default for premium-tier
DISTILL_SYNTHESIS_REASONING_EFFORT=medium   # default for fast-tier
```

### Defaults by tier

| Tier | Workloads | Default Effort |
|------|-----------|----------------|
| Premium | `site`, `report` | `high` |
| Fast | `analysis`, `rerank`, `synthesis`, `brief`, `accordion`, `maintenance` | `medium` |

Invalid values are silently ignored and the tier default applies.

## Pricing Comparison

| Model | Input (per 1M tokens) | Output (per 1M tokens) |
|-------|----------------------|------------------------|
| `grok-4.3` | $1.25 | $2.50 |
| `grok-4.20-0309-non-reasoning` | $1.25 | $2.50 |
| `grok-4-1-fast-reasoning` (retired) | $0.20 | $0.50 |
| `grok-4-fast-reasoning` (retired) | $0.50 | $1.50 |
| `grok-3` (retired) | $3.00 | $9.00 |

`grok-4.3` remains available as an explicit override. The current default is
`grok-4.6` at $2/$6 per 1M short-context tokens with a 500K context window.
Requests at or above 200K prompt tokens use $4/$12 long-context rates. Use `distill eval`
on representative fixtures instead of inferring quality from the model number.

## Cost Impact

For a typical 20-paper research run:
- **Before** (grok-4-1-fast-reasoning at $0.20/$0.50): ~$0.15-$0.30
- **Current default** (`grok-4.6` at short-context $2/$6): run the current command estimate;
  the result depends on the input/output token mix and calibration history.

The current default has a 500K context window. A 100K-character paper is
still comfortably below that limit, and Distill uses adaptive chunking when a
source exceeds the active route's window.

## Timeline

- **Now**: Update your `.env` if you have explicit model overrides
- **May 15, 2026 12:00pm PT**: Retired models stop accepting requests
- **After May 15**: If you haven't updated, distillr's automatic fallback keeps things working (with a warning)
