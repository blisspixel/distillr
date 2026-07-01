# Cost model

Distill runs on a mix of free and paid stages. YouTube captions and local PDF extraction are free. Model calls are metered per-token by xAI, Anthropic, and Gemini chat routes, and per-query by Google Gemini Deep Research.

Figures below are at the **`grok-4.3` default** ($1.25/$2.50 per 1M tokens, the current flagship since April 2026). They are derived from representative per-stage token volumes (`_STAGE_TOKENS` in `distill/pipeline/costs.py`) × the model's pricing, so they track the model rather than a fixed table - and the pre-run estimate self-calibrates against your actual `cost_log.jsonl` history. grok-4.3 is the **cloud floor**: xAI retired the cheaper fast tiers (grok-4-1-fast, grok-4-fast, grok-3, …) on 2026-05-15, and those slugs now redirect to grok-4.3 and bill at grok-4.3 rates ([migration guide](migration-grok-4.3.md)). To go cheaper than grok-4.3 you run analysis on a **local model** (Ollama/LM Studio, $0 marginal) - measure the tradeoff first with `distill eval --models grok-4.3,<local-model>`, which scores quality and cost over frozen fixtures and recommends the cheapest model that clears your bar.

Local analysis is not stale-source analysis. When `DISTILL_PROVIDER=ollama` or
`DISTILL_PROVIDER=lmstudio` is set, Distill still searches and fetches current
public sources before analysis. The local model reads those receipts. Its
pretraining may be old, but the evidence under the insight is whatever Distill
just captured from arXiv, YouTube, feeds, sites, repos, or local files.

## Route classes

| Route class | Implemented today | Cost meaning | Notes |
|---|---:|---|---|
| Deterministic fetch, parse, audit, and local extraction | Yes | No model bill | Still uses network for public sources when the command asks for them. |
| Local model servers, Ollama and LM Studio | Yes | No incremental vendor API bill | Uses local hardware, electricity, and time. Quality must clear `distill eval` before a workload should default to it. |
| Calibrated cloud routes, xAI and Gemini | Yes | Metered API spend | Default quality floor for analysis and Deep Research style work. |
| Opt-in Anthropic API route | Yes | Metered API spend | Claude Sonnet 5 is wired for explicit opt-in use, but it is not a calibrated default. |
| Reserved OpenAI analysis route | No | Metered API spend when implemented | OpenAI is not a live analysis provider yet. OpenAI Whisper transcription is separate. |
| Plan-quota CLI routes, such as Codex CLI, Claude Code, Grok Build, Gemini CLI, and Antigravity `agy` | Planned | Included quota only if proven | Not live providers yet. Adapter doctor preflights, structured support-statement details checked against current 2026-06-30 vendor docs, local config auth-marker scanning, strict `adapter-workload.v1` input packages, strict `adapter-result.v1` manifest checks with quota-stop metadata, a scratch-only runner primitive, a checked workload runner, a native result writer, adapter-specific native usage capture, a manifest-to-ledger helper, and blocked read-only command planners exist. No plan-quota support statement is current for no-metered routing yet because paid credits, overages, API-key modes, gateway routes, or unproved session auth remain possible. Routes still need included-plan auth proof, native schema enforcement where the CLI supports it, real installed-session validation, and `distill eval` evidence. |
| Credit-metered CLI routes, such as GitHub Copilot CLI | Planned | Explicit paid or credit policy | Supportable later, but not a no-metered default because Copilot usage is tied to AI credits and usage limits. |

## Cost modes

`DISTILL_COST_MODE` accepts:

- `auto` - the default. Use the configured route behavior and normal budget
  gates.
- `no-metered` - refuse routes that would bill an API or have ambiguous billing
  semantics. Today that allows local Ollama and LM Studio routes, and blocks xAI,
  Gemini, OpenAI, Anthropic, `agent`, and unproven adapter routes.
- `paid-ok` - allow metered provider routes, subject to explicit workflow caps.

This is a route-policy guard, not a quality judgment. Local routes still need
`distill eval` evidence before becoming a recommended default for a workload.
Plan-quota CLIs remain blocked in `no-metered` until adapter doctor, a current
structured support statement, included-plan auth proof, real installed-session
validation, proof that paid credits, overages, gateways, or API-backed modes are
not active, native schema enforcement where the CLI supports it, command
templates, and eval proof exist.

When a route is blocked, Distill reports the blocked provider, workload, route
cost class, reason, required proof when applicable, and the next allowed action.
Metered API routes point to `distill --cost-mode paid-ok <same command>` only
after the operator has confirmed the spend cap.

Use `distill --cost-mode no-metered <command>` for a one-run override without
editing `.env`. Recurring profile previews include that global override in
generated replay commands when the profile declares `cost_mode: no-metered`.
`distill profile run <name> --yes` executes those commands through the existing
ingest, analysis, verify, and cost-log paths, with resume state under
`library/.distill/profiles/`.

The usage ledger records zero-dollar usage too. Cost-log rows include provider
and route-class breakdowns, no-metered LLM call counts, local transcription
counts, and profile-run orchestration rows even when `actual_cost` is `0.0`.

## Cost warnings

`distill costs`, JSON cost output, the CLI dashboard, and the local web
dashboard read the same ledger and surface structural surprise-cost warnings.
The warnings are based only on recorded facts:

- daily spend at or above the current attention threshold
- a latest daily total that is much higher than the recent daily baseline
- a latest comparable command/topic run that is much higher than its recent
  baseline
- any recorded xAI media-generation model id, such as `grok-imagine-image`

These warnings do not decide whether a run was useful. They point to spend that
deserves operator review. Preview rows are excluded from spike comparisons, and
malformed or non-finite cost values are ignored.

The default warning policy is:

```bash
DISTILL_COST_WARNING_DAILY_USD=10
DISTILL_COST_WARNING_SPIKE_MULTIPLIER=2.5
DISTILL_COST_WARNING_RUN_SPIKE_MIN_USD=1
DISTILL_COST_WORKFLOW_BUDGETS=
```

Set `DISTILL_COST_WORKFLOW_BUDGETS` to comma-separated command caps when a
workflow should draw attention above a known spend ceiling:

```bash
DISTILL_COST_WORKFLOW_BUDGETS="ask=0.25,report=5,discover=2,eval=1,video=1,channel=2,catch-up=2,reanalyze=2,resynthesize=1,site=3,site-batch=3,topic-brief=1,synthesize=1,synthesis=1"
```

Workflow budgets serve three roles. First, direct CLI workflows with credible
pre-run estimates can refuse before the estimated work starts. `distill ask`
checks its bounded corpus-excerpt estimate after no-coverage retrieval and
before the QA model call; `distill site` and `distill site-batch` check their
resolved maximum page count plus known synthesis and optional report tail before
model preflight, while preview and scrape-only paths stay free; `distill eval` checks its
fixture-aware estimate before model execution; `distill video`,
`distill channel`, `distill catch-up`, `distill reanalyze`, and
`distill resynthesize` runs check known video-analysis and synthesis estimates
before their model work starts; `distill report` and `distill research-brief`
check their Deep Research estimates before the Gemini call; direct
`distill synthesize`, `distill topic brief`, and on-demand `distill synthesis`
generation check their known synthesis-call estimates before model execution; and
`distill discover` checks saved preview estimates and freshly ranked
ingest-plan estimates before ingest. Second, direct CLI workflows that create a
budgeted tracker stop when
their recorded spend crosses the configured cap. The crossing model call has
already happened and stays in the ledger, then the installed `distill` command
exits with code `6`; JSON mode emits a structured `budget_exceeded` envelope.
Projected stops add `projected: true` and `projected_usd` to that envelope.
Third, `distill costs`, the CLI dashboard, JSON cost output, and the local web
dashboard use the same caps to flag historical over-budget ledger rows.

Use the user-facing command key for the cap. Common keys include `ask`,
`catch-up`, `channel`, `concepts`, `corpus`, `discover`, `eval`, `ingest`,
`paper`, `papers`, `reanalyze`, `report`, `research-brief`, `resynthesize`,
`run`, `site`, `site-batch`, `synthesize`, `synthesis`, `topic-brief`, and
`video`.

Workflow budgets do not replace `DISTILL_COST_MODE=no-metered`, topic-watch
max-run/monthly budgets, or MCP per-call spend caps. Cost mode is the pre-call
route policy. Topic-watch budgets are projected-run controls for recurring
topic watches. MCP caps are per-tool-call controls for agent-facing write
tools.

## Provider-side caches

Provider-side prompt and context caches are metered-route optimizations, not
proof that a route is no-metered. A cached OpenAI, Anthropic, Gemini, Bedrock,
Foundry, or xAI token still belongs in the usage ledger, and a cache discount
does not change the route cost class.

The provider cache policy is in
[`docs/design/provider-caching.md`](design/provider-caching.md). In short:

- Distill must keep opaque provider caches separate from local durable
  intermediate caches.
- Cache writes, reads, TTL, retention, storage charges, rate-limit effects, and
  telemetry fields differ by provider.
- Explicit provider cache controls stay blocked until the adapter has a
  provider-specific policy, ledger fields, bounded lifecycle, and cleanup
  semantics.
- Pre-warming or background refresh is blocked unless the command owns the
  lifecycle and records a positive, bounded savings projection before the write.

## Per-stage cost

| Stage | Typical cost | Basis (@ grok-4.3) |
|---|---|---|
| YouTube caption extraction | **$0** | yt-dlp pulls auto-generated captions |
| arXiv PDF download + text extraction | **$0** | pypdf, local |
| Per-video analysis - full (2 passes) | **~$0.03** | ~13K input + ~6K output |
| Per-video analysis - Short (1 pass) | **~$0.002** | ~800 input + ~500 output |
| Per-video analysis - scan (1 pass) | **~$0.004** | ~1.5K input + ~800 output (lightweight triage) |
| Per-page analysis (website) | **~$0.02-0.05** | Varies with page length |
| Per-paper analysis (full PDF) | **~$0.03-0.05** | ~20K input + ~3K output |
| Channel synthesis | **~$0.035** | ~20K input + ~4K output |
| Topic synthesis | **~$0.035** | Similar to channel synthesis |
| Paper synthesis (per topic) | **~$0.20** | ~150K input + ~5K output |
| **Paper query expansion (`distill papers`)** | **~$0.01** | One call to generate up to 6 search variants |
| **Paper rerank (`distill papers`)** | **~$0.01-0.03** | One call scoring 20-40 paper candidates pre-ingest |
| **Discover query generation (`distill discover`)** | **~$0.01** | One call generating paper + video queries from a goal |
| **Discover rerank (`distill discover`)** | **~$0.02-0.05** | One call scoring combined paper+video candidates against the goal |
| Report Phase 1 (Gemini Deep Research) | **~$2-3** | 1 Deep Research query, variable search depth |
| Report Phase 2 (sections) | **~$0.29** | ~150K input + ~40K output |
| Report Phase 4 (QA + rewrites) | **~$0.03** | ~20K input + ~2K output |
| `distill research-brief` | **~$3-5** | 1 Gemini Deep Research query with custom File Search store |
| `distill synthesize` | **~$0.20-0.40** | 1 Grok 4.3 call over the gathered corpus |

## Example runs

**Full channel run (400 videos + report):**

| Component | Calculation | Cost |
|---|---|---|
| 182 full videos × 2 passes | 182 × $0.03 | ~$5.70 |
| 187 Shorts × 1 pass | 187 × $0.002 | ~$0.42 |
| Channel synthesis | 1 × $0.035 | ~$0.035 |
| Report Phase 1 (Gemini) | 1 query | ~$2-3 |
| Report Phase 2 (sections) | 1 × Grok | ~$0.29 |
| Report Phase 4 (QA + rewrites) | 1-3 × Grok | ~$0.03 |
| **Total** | | **~$8.5-9.5** |

**100 arXiv papers across 5 topics + one cross-topic synthesis:**

| Component | Calculation | Cost |
|---|---|---|
| 100 papers × full-PDF analysis | 100 × $0.0325 | ~$3.25 |
| 5 × (query expansion + rerank) | 5 × $0.03 | ~$0.15 |
| 5 paper syntheses | 5 × $0.20 | ~$1.00 |
| One `distill synthesize` across all 5 topics | 1 × $0.30 | ~$0.30 |
| **Total** | | **~$4.70** |

Add `distill research-brief` (~$3-5) only if you want web-augmented cross-topic Deep Research on top.

**Single `distill discover` run (goal-driven, ~8 papers + ~8 videos):**

| Component | Calculation | Cost |
|---|---|---|
| Discover query generation | 1 × $0.01 | ~$0.01 |
| Discover goal-aware rerank | 1 × $0.03 avg | ~$0.03 |
| 8 papers × full-PDF analysis | 8 × $0.0325 | ~$0.26 |
| 8 videos × full 2-pass analysis | 8 × $0.03 | ~$0.25 |
| Per-channel syntheses + topic synthesis | ~6 × $0.035 | ~$0.21 |
| Paper synthesis + corpus synthesis | $0.20 + $0.10 | ~$0.30 |
| **Total** | | **~$1.05** |

Previewing first (`--preview`) stops after the rerank step and costs **~$0.04-0.06**. That's the point of preview - sanity-check the shortlist for pennies before committing. The fresh-topic sizing menu shows each option's spend so you can size against the real cost before approving.

The pre-run estimate shown under a discover preview (and per option in the fresh-topic sizing menu) is **metadata-aware and self-calibrating**: per-video cost scales with the candidate's duration, and the per-source rates are derived from clean single-source runs in your own `cost_log.jsonl` (falling back to the defaults above when history is thin). It's reported as an honest range, e.g. `~$0.42 (est; $0.29-$0.63)`, that narrows as calibration data accrues - so the number tracks *your* model and content mix rather than a fixed table.

## Budget guidance

- Bulk video analysis is cheap but not free on grok-4.3: ~$0.03/video, so 1,000 videos costs ~$31. There is no cheaper xAI cloud tier anymore (the fast tiers retired 2026-05-15); to drive bulk cost toward $0, run analysis on a local model (`DISTILL_PROVIDER=ollama`) once `distill eval` confirms it clears the quality bar.
- Gemini Deep Research dominates the bill at $2-3 per report.
- `distill synthesize` is the cheapest way to get dense cross-topic synthesis because it's single-call Grok with no Deep Research involvement.
- Budget ~$15-20 per topic per quarter as a safe upper bound for a channel-heavy workflow on grok-4.3.

Use `distill costs` to see actual cost history with per-run token breakdowns. Every run logs estimated vs actual costs to `library/cost_log.jsonl` for calibration.

## Topic-watch guardrails

```bash
distill topic-watch add "..." --max-run-cost 1.50 --monthly-budget 12
distill topic-watch budget <topic> --max-run-cost 2.00 --monthly-budget 15
distill topic-watch run <topic> --ignore-budget       # explicit override
```

- `--max-run-cost` skips a topic-watch when the projected next run exceeds the cap
- `--monthly-budget` skips a topic-watch when projected rolling 30-day spend would exceed budget

## Model pricing (source of truth)

| Model | Input | Output | Context | Used for |
|---|---|---|---|---|
| `grok-4.3` | $1.25/1M | $2.50/1M | 1M | Default for all workloads (analysis, reranking, synthesis, briefs, papers, sites, report section writing) |
| `grok-4-1-fast-reasoning` | - | - | - | **Retired 2026-05-15**; slug redirects to grok-4.3 and bills at grok-4.3 rates. distillr auto-substitutes it (the $0.20/$0.50 entry in the registry is kept only to price pre-retirement `cost_log.jsonl` rows). |
| `grok-4.20-0309-reasoning` | $2.00/1M | $6.00/1M | 2M | Still available; selectable via env override for higher-fidelity passes |
| `deep-research-preview-04-2026` | pay-as-you-go | ~$2-5/query | N/A | Report Phase 1, `distill research-brief` |
| `gemini-3.5-flash` | $1.50/1M | $9.00/1M | 1M | Optional Gemini-provider chat model (GA 2026-05-19) |
| `claude-sonnet-5` | $2.00/1M through 2026-08-31, then $3.00/1M | $10.00/1M through 2026-08-31, then $15.00/1M | 1M | Optional Anthropic-provider chat model; current intro-rate estimate, not a default route |

Since 0.3.1, both fast and premium tiers default to `grok-4.3`. The older models remain available via `.env` overrides for users who prefer them.

## Overriding models

All model defaults are overridable via `.env`:

```bash
XAI_FAST_MODEL=grok-4.3
XAI_PREMIUM_MODEL=grok-4.3
XAI_ANALYSIS_MODEL=
XAI_SITE_MODEL=
XAI_SYNTHESIS_MODEL=
ACCORDION_SECTION_MODEL=

# Multi-provider support
# Implemented providers: xai, gemini, anthropic, agent, ollama, lmstudio.
# openai is a reserved analysis route and is not implemented in this release.
ANTHROPIC_API_KEY=
DISTILL_PROVIDER=xai                    # xai | gemini | anthropic | agent | ollama | lmstudio
DISTILL_MODEL=                          # e.g. claude-sonnet-5 with DISTILL_PROVIDER=anthropic
DISTILL_ANALYSIS_PROVIDER=              # per-workload provider override
DISTILL_SYNTHESIS_PROVIDER=
```

Leave the narrow overrides blank to use the broader `XAI_FAST_MODEL` / `XAI_PREMIUM_MODEL` defaults. Both default to `grok-4.3` since 0.3.1.
Claude Sonnet 5 uses Anthropic adaptive thinking by default. Distill omits
explicit sampling parameters such as `temperature` for Sonnet 5 compatibility,
while still forwarding `DISTILL_<WORKLOAD>_REASONING_EFFORT` as
`output_config.effort` when explicitly set.
