# Cost model

Distill runs on a mix of free and paid stages. YouTube captions and local PDF extraction are free. Model calls are metered per-token by xAI (Grok) and per-query by Google (Gemini Deep Research).

Figures below are at the **`grok-4.3` default** ($1.25/$2.50 per 1M tokens, the current flagship since April 2026). They are derived from representative per-stage token volumes (`_STAGE_TOKENS` in `distill/pipeline/costs.py`) × the model's pricing, so they track the model rather than a fixed table — and the pre-run estimate self-calibrates against your actual `cost_log.jsonl` history. The retired `grok-4-1-fast` tier ($0.20/$0.50) was ~5× cheaper and is still selectable via `.env` if you prefer bulk-cheap over fidelity.

## Per-stage cost

| Stage | Typical cost | Basis (@ grok-4.3) |
|---|---|---|
| YouTube caption extraction | **$0** | yt-dlp pulls auto-generated captions |
| arXiv PDF download + text extraction | **$0** | pypdf, local |
| Per-video analysis — full (2 passes) | **~$0.03** | ~13K input + ~6K output |
| Per-video analysis — Short (1 pass) | **~$0.002** | ~800 input + ~500 output |
| Per-video analysis — scan (1 pass) | **~$0.004** | ~1.5K input + ~800 output (lightweight triage) |
| Per-page analysis (website) | **~$0.02–0.05** | Varies with page length |
| Per-paper analysis (full PDF) | **~$0.03–0.05** | ~20K input + ~3K output |
| Channel synthesis | **~$0.035** | ~20K input + ~4K output |
| Topic synthesis | **~$0.035** | Similar to channel synthesis |
| Paper synthesis (per topic) | **~$0.20** | ~150K input + ~5K output |
| **Paper query expansion (`distill papers`)** | **~$0.01** | One call to generate up to 6 search variants |
| **Paper rerank (`distill papers`)** | **~$0.01–0.03** | One call scoring 20–40 paper candidates pre-ingest |
| **Discover query generation (`distill discover`)** | **~$0.01** | One call generating paper + video queries from a goal |
| **Discover rerank (`distill discover`)** | **~$0.02–0.05** | One call scoring combined paper+video candidates against the goal |
| Report Phase 1 (Gemini Deep Research) | **~$2–3** | 1 Deep Research query, variable search depth |
| Report Phase 2 (sections) | **~$0.29** | ~150K input + ~40K output |
| Report Phase 4 (QA + rewrites) | **~$0.03** | ~20K input + ~2K output |
| `distill research-brief` | **~$3–5** | 1 Gemini Deep Research query with custom File Search store |
| `distill synthesize` | **~$0.20–0.40** | 1 Grok 4.3 call over the gathered corpus |

## Example runs

**Full channel run (400 videos + report):**

| Component | Calculation | Cost |
|---|---|---|
| 182 full videos × 2 passes | 182 × $0.03 | ~$5.70 |
| 187 Shorts × 1 pass | 187 × $0.002 | ~$0.42 |
| Channel synthesis | 1 × $0.035 | ~$0.035 |
| Report Phase 1 (Gemini) | 1 query | ~$2–3 |
| Report Phase 2 (sections) | 1 × Grok | ~$0.29 |
| Report Phase 4 (QA + rewrites) | 1–3 × Grok | ~$0.03 |
| **Total** | | **~$8.5–9.5** |

**100 arXiv papers across 5 topics + one cross-topic synthesis:**

| Component | Calculation | Cost |
|---|---|---|
| 100 papers × full-PDF analysis | 100 × $0.0325 | ~$3.25 |
| 5 × (query expansion + rerank) | 5 × $0.03 | ~$0.15 |
| 5 paper syntheses | 5 × $0.20 | ~$1.00 |
| One `distill synthesize` across all 5 topics | 1 × $0.30 | ~$0.30 |
| **Total** | | **~$4.70** |

Add `distill research-brief` (~$3–5) only if you want web-augmented cross-topic Deep Research on top.

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

Previewing first (`--preview`) stops after the rerank step and costs **~$0.04–0.06**. That's the point of preview — sanity-check the shortlist for pennies before committing. The fresh-topic sizing menu shows each option's spend so you can size against the real cost before approving.

The pre-run estimate shown under a discover preview (and per option in the fresh-topic sizing menu) is **metadata-aware and self-calibrating**: per-video cost scales with the candidate's duration, and the per-source rates are derived from clean single-source runs in your own `cost_log.jsonl` (falling back to the defaults above when history is thin). It's reported as an honest range, e.g. `~$0.42 (est; $0.29-$0.63)`, that narrows as calibration data accrues — so the number tracks *your* model and content mix rather than a fixed table.

## Budget guidance

- Bulk video analysis is cheap but not free on grok-4.3: ~$0.03/video, so 1,000 videos costs ~$31. (On the retired `grok-4-1-fast` tier it was ~$6 — set `XAI_FAST_MODEL=grok-4-1-fast-reasoning` in `.env` if you want that trade-off.)
- Gemini Deep Research dominates the bill at $2–3 per report.
- `distill synthesize` is the cheapest way to get dense cross-topic synthesis because it's single-call Grok with no Deep Research involvement.
- Budget ~$15–20 per topic per quarter as a safe upper bound for a channel-heavy workflow on grok-4.3.

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
| `grok-4-1-fast-reasoning` | $0.20/1M | $0.50/1M | 2M | Legacy fast tier (still supported via env override) |
| `grok-4.20-0309-reasoning` | $2.00/1M | $6.00/1M | 2M | Legacy premium tier (still supported via env override) |
| `deep-research-preview-04-2026` | pay-as-you-go | ~$2–5/query | N/A | Report Phase 1, `distill research-brief` |
| `gemini-3.5-flash` | $1.50/1M | $9.00/1M | 1M | Optional Gemini-provider chat model (GA 2026-05-19) |

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

# Multi-provider support (added in 0.3.1)
# Implemented providers: xai, gemini, agent, ollama, lmstudio.
# anthropic/openai are reserved names and are not implemented in this release.
DISTILL_PROVIDER=xai                    # xai | gemini | agent | ollama | lmstudio
DISTILL_ANALYSIS_PROVIDER=              # per-workload provider override
DISTILL_SYNTHESIS_PROVIDER=
```

Leave the narrow overrides blank to use the broader `XAI_FAST_MODEL` / `XAI_PREMIUM_MODEL` defaults. Both default to `grok-4.3` since 0.3.1.
