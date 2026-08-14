# Cost model

Distill runs on a mix of free and paid stages. YouTube captions and local PDF
extraction are free. xAI, Anthropic, and Gemini model calls are token-metered.
Google bills Deep Research for its underlying model inference and tool usage.
Google no longer publishes a typical dollar range for the current agents and
does not expose a request-side dollar ceiling. Distill may show a non-binding
$2.50 standard or $5.00 Max planning placeholder, but it never records that
placeholder as actual spend. A Deep Research run with a hard workflow or MCP
budget fails closed before client construction, File Search store creation,
upload, or provider contact. Run it only without a dollar cap as an explicit
metered choice, or use `corpus-report` for enforceable token-based budgeting.

Cold-start figures below use the **`grok-4.6` default** at $2 input and $6
output per 1M short-context tokens. They are derived from representative per-stage token
volumes in `distill/pipeline/cost_estimates.py`, so the estimate follows the
selected model rather than a fixed dollar table. When sufficient clean history
exists, the pre-run estimate self-calibrates against the actual
`cost_log.jsonl` rows. Use `distill eval --models grok-4.6,<candidate>` before
moving a workload to a cheaper cloud or local model.

Local analysis is not stale-source analysis. When `DISTILL_PROVIDER=ollama` or
`DISTILL_PROVIDER=lmstudio` is set, Distill still searches and fetches current
public sources before analysis. The local model reads those receipts. Its
pretraining may be old, but the evidence under the insight is whatever Distill
just captured from arXiv, YouTube, feeds, sites, repos, or local files.

## Route classes

| Route class | Implemented today | Cost meaning | Notes |
|---|---:|---|---|
| Deterministic fetch, parse, audit, and local extraction | Yes | No model bill | Still uses network for public sources when the command asks for them. |
| Local model servers, Ollama and LM Studio | Yes | No incremental vendor API bill only for strict loopback endpoints | Uses local hardware, electricity, and time. Remote or malformed endpoint overrides are classified as unknown, not local. Quality must clear `distill eval` before a workload should default to it. |
| Calibrated cloud routes, xAI and Gemini | Yes | Metered API spend | Default quality floor for analysis and Deep Research style work. |
| Opt-in Anthropic API route | Yes | Metered API spend | Claude Sonnet 5 is wired for explicit opt-in use, but it is not a calibrated default. |
| Reserved OpenAI analysis route | No | Metered API spend when implemented | OpenAI is not a live analysis provider yet. OpenAI Whisper transcription is separate. |
| Remote Ollama or LM Studio adapter | Yes in `auto` or `paid-ok` | External cost unavailable | Distill records attempts but cannot prove host billing or price the external service. Eval refuses these unpriced routes. |
| Deferred `agent` task-file route plus active host worker | Yes, explicit handoff | Host-managed; external cost unavailable | This writes a structured task, lets an already active agent session claim it into scratch through `distill worker`, and accepts only a validated result plus receipt. Distill does not execute the assistant or inspect its auth, so the route remains blocked in `no-metered`. |
| Plan-quota CLI routes, such as Codex CLI, Claude Code, Grok Build, Gemini CLI, and Antigravity `agy` | Planned | Included quota only if proven | Not live providers yet. Adapter doctor preflights, structured support-statement details checked against current 2026-06-30 vendor docs, local config auth-marker scanning, strict `adapter-workload.v1` input packages, strict `adapter-result.v1` manifest checks with quota-stop metadata, a scratch-only runner primitive, a checked workload runner, a native result writer, adapter-specific native usage capture, a manifest-to-ledger helper, and blocked read-only command planners exist. No plan-quota support statement is current for no-metered routing yet because paid credits, overages, API-key modes, gateway routes, or unproved session auth remain possible. Routes still need included-plan auth proof, native schema enforcement where the CLI supports it, real installed-session validation, and `distill eval` evidence. |
| Credit-metered CLI routes, such as GitHub Copilot CLI | Planned | Explicit paid or credit policy | Supportable later, but not a no-metered default because Copilot usage is tied to AI credits and usage limits. |

When Ollama reports a different resident model, Distill waits with bounded
asynchronous backoff instead of submitting a competing model load. It never
silently substitutes the resident model. The wait uses the same local ceiling
value as inference, configurable with `DISTILL_LOCAL_TIMEOUT`, but the semantics
differ: contention uses a total wait bound, while streaming inference uses a
per-read idle timeout and may run longer while tokens keep arriving. If the
contention bound is reached, the command returns a network-class failure with
the active model and retry guidance so an external loop can reschedule it. If
the requested model is already resident, Distill submits normally and lets
Ollama serialize work for that model. In `--json` mode the timeout payload uses
`code: provider_busy`, `retryable: true`, and `terminal: false`, so a harness
does not have to classify the error message.

## Cost modes

`DISTILL_COST_MODE` accepts:

- `auto` - the default. Use the configured route behavior and normal budget
  gates.
- `no-metered` - refuse routes that would bill an API or have ambiguous billing
  semantics. Today that allows Ollama and LM Studio only at strict loopback
  HTTP(S) endpoints, and blocks remote or malformed endpoint overrides, xAI,
  Gemini, OpenAI, Anthropic, `agent`, and unproven adapter routes.
- `paid-ok` - allow metered provider routes, subject to explicit workflow caps.

When a remote Ollama or LM Studio compatible endpoint is permitted, the local
ledger reports known direct Distill spend separately and labels external cost as
unavailable. It does not substitute a zero or an unrelated fallback price.
Recent-cost projections are withheld while that unknown external spend is in
the projection window.

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

Cost mode applies to every provider edge, including live credential probes,
cloud speech-to-text, Gemini Deep Research, and Gemini File Search maintenance.
Under `no-metered`, those routes refuse before duration probing, client
construction, file upload, or a provider call. `distill doctor` reports a cloud
key as `skipped` when live validation is blocked by policy; it does not treat the
key as valid. `distill cleanup` also refuses before constructing a Gemini client.
Local transcription remains allowed.

The usage ledger records zero-dollar and unknown-external-cost usage too.
Cost-log rows include provider and route-class breakdowns, no-metered LLM call
counts, host-managed call counts, local transcription counts, and profile-run
orchestration rows even when `actual_cost` is `0.0`. For a host-managed result,
`actual_cost` covers Distill's direct charges only, `external_cost_status` is
`unavailable`, and the route is neither counted as metered API nor proven
no-metered. A recurring profile receipt containing host-managed usage is marked
unverified so its budget runner fails closed rather than treating unknown
external cost as zero.
Direct `distill concepts build` and `distill synthesize` runs flush every
non-empty tracker in a `finally` path, so successful and failed calls remain on
the ledger while true no-op runs do not create empty rows.

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
deserves operator review. Preview rows are excluded from spike comparisons.
Malformed, negative, non-finite, unreadable, or omitted valid evidence makes
completeness-sensitive totals, anomaly checks, projections, calibration, and
budget rollups unavailable instead of being ignored or treated as zero. Valid
retained rows remain visible for diagnosis.

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
DISTILL_COST_WORKFLOW_BUDGETS="ask=0.25,report=5,discover=2,eval=1,ingest=1,paper=1,papers=2,video=1,channel=2,catch-up=2,reanalyze=2,resynthesize=1,site=3,site-batch=3,corpus=1,topic-brief=1,synthesize=1,synthesis=1"
```

Workflow budgets serve three roles. First, direct CLI workflows with credible
pre-run estimates can refuse before the estimated work starts. `distill ask`
checks its bounded corpus-excerpt estimate after no-coverage retrieval and
before the QA model call; `distill paper` checks one full-PDF analysis plus the
known paper and corpus synthesis tail before model preflight; non-preview
`distill papers` checks the requested limit as an upper bound before model
preflight, then re-checks the selected-paper count plus known synthesis tail
after search, dedup, rerank, and preview selection but before full-PDF analysis;
`distill site` and `distill site-batch` check their resolved maximum page count
plus known synthesis and optional report tail before model preflight, while
preview and scrape-only paths stay free; `distill eval` checks its fixture-aware estimate before model
execution; `distill video`, `distill channel`, `distill catch-up`,
`distill reanalyze`, and `distill resynthesize` runs check known video-analysis
and synthesis estimates before their model work starts; `distill corpus` checks
one synthesis-call estimate before model preflight only when the topic has
corpus source sections, preserving empty and paper-only no-synthesis paths;
`distill report` checks its selected profile before any provider call. The
default corpus profile prices only the configured sequential writer. The
accordion and deep-research profiles carry planning placeholders, but any hard
dollar budget refuses their unbounded Google agent stage before remote setup.
`distill research-brief` uses the same fail-closed rule; direct `distill
synthesize`, `distill topic brief`, and on-demand
`distill synthesis` generation check their known synthesis-call estimates before
model execution; and `distill discover` checks saved preview estimates and
freshly ranked ingest-plan estimates before ingest. Second, direct xAI, Gemini
chat, and Anthropic calls on a budgeted tracker are admitted one attempt at a
time. Distill conservatively bounds the prompt and maximum configured output,
atomically reserves that amount, and does so before provider-client
construction. Hidden provider retries are disabled while a dollar cap is
active; an eligible router fallback is a separate attempt with a separate
admission decision. A registered price is required, so a budgeted custom
metered model fails closed before contact if its price is unknown. Projected
stops exit with code `6`; JSON mode emits a structured `budget_exceeded`
envelope with `projected: true` and `projected_usd`. A provider-unbounded
refusal also exits `6` and sets `unbounded_external_cost: true` without
inventing a numeric projection.

Cloud transcription reserves its verified duration price around each provider
attempt. Deep Research cannot be reserved against a hard dollar cap because
Google provides no request-side ceiling. Nested reservations for bounded calls
reuse already-held workflow or item headroom, while concurrent workers cannot
authorize the same remaining dollars independently.

Provider-reported usage is still the ledger source of truth after a call.
Distill records conservative maximum usage when a provider omits valid usage
metadata. An exceptional provider response that violates the admitted token
bound is recorded and then raises a budget crossing. Deep Research is
different: Google runs an autonomous token-and-tool loop without a
provider-side dollar cap. Distill therefore refuses that stage whenever a hard
workflow or MCP budget is active.
Third, `distill costs`, the CLI dashboard, JSON cost output, and the local web
dashboard use the same caps to flag historical over-budget ledger rows.

Use the user-facing command key for the cap. Common keys include `ask`,
`catch-up`, `channel`, `concepts`, `corpus`, `discover`, `eval`, `ingest`,
`paper`, `papers`, `reanalyze`, `report`, `research-brief`, `resynthesize`,
`run`, `site`, `site-batch`, `synthesize`, `synthesis`, `topic-brief`, and
`video`.

Estimate-bearing workflows resolve the active route for each model stage. Ask,
paper, site, discovery, synthesis, topic-watch, and video-family work assigned
to Ollama or LM Studio contributes `$0.00` incremental model cost to the
displayed estimate, workflow-budget preflight, and saved run row. A metered
per-workload override or an eligible metered fallback is still priced, so a
mixed local and cloud workflow is not labeled free. Unknown paper sizes price
the costlier eligible single-pass or multipass route until analysis determines
which path runs. Gemini Deep Research also remains metered when the surrounding
analysis is local.

Workflow budgets do not replace `DISTILL_COST_MODE=no-metered`, topic-watch
max-run/monthly budgets, or MCP per-call spend caps. Cost mode is the pre-call
route policy. Topic-watch budgets are projected-run controls for recurring
topic watches. MCP caps are per-tool-call controls for agent-facing write
tools.

Workflow caps are per command, not one cumulative campaign budget. For a hard
ceiling across discovery, several direct ingests, synthesis, and evaluation,
use `no-metered` for the campaign or allocate separate command caps whose sum
fits the ceiling, then inspect `distill costs` between phases. Distill does not
currently reserve or atomically enforce one shared dollar allowance across
several independent CLI processes.

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

| Stage | Planning cost or status | Basis at grok-4.6 |
|---|---|---|
| YouTube caption extraction | **$0** | yt-dlp pulls auto-generated captions |
| arXiv PDF download + text extraction | **$0** | pypdf, local |
| Per-video analysis - full (2 passes) | **~$0.062** | ~13K input + ~6K output |
| Per-video analysis - Short (1 pass) | **~$0.005** | ~800 input + ~500 output |
| Per-video analysis - scan (1 pass) | **~$0.008** | ~1.5K input + ~800 output (lightweight triage) |
| Per-page analysis (website) | **~$0.042** | ~12K input + ~3K output |
| Per-paper analysis (full PDF) | **~$0.058** | ~20K input + ~3K output |
| Channel synthesis | **~$0.064** | ~20K input + ~4K output |
| Topic synthesis | **~$0.064** | Similar to channel synthesis |
| Paper synthesis (per topic) | **~$0.33** | ~150K input + ~5K output |
| **Paper query expansion (`distill papers`)** | **~$0.02** | One call to generate up to 6 search variants |
| **Paper rerank (`distill papers`)** | **~$0.02-0.06** | One call scoring 20-40 paper candidates pre-ingest |
| **Discover query generation (`distill discover`)** | **~$0.02** | One call generating paper + video queries from a goal |
| **Discover rerank (`distill discover`)** | **~$0.04-0.09** | One call scoring combined paper+video candidates against the goal |
| Default `corpus-report` | **~$0.99** | ~420K input + ~25K output across ordered sections, full-document QA, and a likely rewrite |
| Accordion Phase 1 (Gemini Deep Research) | **External cost unavailable** | $2.50 is a non-binding Distill planning placeholder, not a provider quote or cap |
| Accordion ordered writing + QA | **~$0.90** | ~360K input + ~30K output across the sequential report spine |
| `deep-research` profile | **External cost unavailable** | One standard agent run; token and tool use is reported by Google after submission |
| `distill research-brief` | **External cost unavailable** | One standard agent run with a custom File Search store; hard dollar budgets refuse before remote setup |
| `distill synthesize` | **~$0.33-0.65** | 1 Grok 4.6 call over the gathered corpus; prompts at 200K tokens or more use long-context rates |

## Example runs

**Full channel run (400 videos + report):**

| Component | Calculation | Cost |
|---|---|---|
| 182 full videos × 2 passes | 182 × $0.062 | ~$11.28 |
| 187 Shorts × 1 pass | 187 × $0.0046 | ~$0.86 |
| Channel synthesis | 1 × $0.064 | ~$0.06 |
| Accordion Phase 1 (Gemini) | 1 query | External, not included |
| Accordion ordered writing + QA | registry-backed projection | ~$0.90 |
| **Known Distill direct total** | | **~$13.10 plus Google external cost** |

**100 arXiv papers across 5 topics + one cross-topic synthesis:**

| Component | Calculation | Cost |
|---|---|---|
| 100 papers × full-PDF analysis | 100 × $0.058 | ~$5.80 |
| 5 × (query expansion + rerank) | 5 × $0.06 | ~$0.30 |
| 5 paper syntheses | 5 × $0.33 | ~$1.65 |
| One `distill synthesize` across all 5 topics | 1 × $0.45 | ~$0.45 |
| **Total** | | **~$8.20** |

Add `distill research-brief` only if you want web-augmented cross-topic Deep
Research on top and accept that its external cost cannot be hard-capped by
Distill.

**Single `distill discover` run (goal-driven, ~8 papers + ~8 videos):**

| Component | Calculation | Cost |
|---|---|---|
| Discover query generation | 1 × $0.02 | ~$0.02 |
| Discover goal-aware rerank | 1 × $0.06 avg | ~$0.06 |
| 8 papers × full-PDF analysis | 8 × $0.058 | ~$0.46 |
| 8 videos × full 2-pass analysis | 8 × $0.062 | ~$0.50 |
| Per-channel syntheses + topic synthesis | ~6 × $0.064 | ~$0.38 |
| Paper synthesis + corpus synthesis | $0.33 + $0.18 | ~$0.51 |
| **Total** | | **~$1.93** |

Previewing first (`--preview`) stops after the rerank step and typically costs
**~$0.06-0.12** at the default route. The fresh-topic sizing menu shows each
option's projected spend before approval.

The pre-run estimate shown under a discover preview (and per option in the fresh-topic sizing menu) is **metadata-aware and self-calibrating**: per-video cost scales with the candidate's duration, and the per-source rates are derived from clean single-source runs in your own `cost_log.jsonl` (falling back to the defaults above when history is thin). It's reported as an honest range, e.g. `~$0.42 (est; $0.29-$0.63)`, that narrows as calibration data accrues - so the number tracks *your* model and content mix rather than a fixed table.

## Budget guidance

- Bulk video analysis is cheap but not free on grok-4.6: the cold-start
  estimate is about $0.062 per full video, so 1,000 videos is about $62 before
  calibration. To drive marginal API cost toward $0, use a local model only
  after `distill eval` confirms it clears the workload quality bar.
- Gemini Deep Research can dominate the bill. Google bills underlying model and
  tool use and publishes no current typical range or request-side dollar cap.
  Distill's $2.50 and $5.00 values are planning placeholders only. A configured
  hard budget refuses the agent before any remote setup.
- `distill synthesize` is the cheapest way to get dense cross-topic synthesis
  because it is a single call on the configured synthesis route with no Deep
  Research stage.
- Use the command's current estimate and an explicit workflow budget. Do not
  carry forward a fixed quarterly allowance from an older model price.

Use `distill costs` to see actual cost history with per-run token breakdowns
and the correlated command, provider, and phase performance evidence available
for newer runs. Exact `run_id` joins are forward-only; legacy rows without an ID
are counted but never guessed from timestamps. A schema-invalid row that still
names a run makes that run's affected phase, provider, or cost rollup incomplete
and therefore `null`; an unreadable provider or cost log does the same for each
selected run. Missing logs remain complete empty evidence, and an explicit valid
zero remains zero. Model-using runs log estimated vs actual costs to
`library/.distill/cost_log.jsonl` for calibration; true no-spend no-ops do not
create empty cost rows.

Cost-ledger appends share a per-file cross-process lock with the one-time
legacy migration. A partial final row is terminated before the next row, and a
new cost row is `fsync`-flushed before profile receipt state advances. Provider
top-N and local/cloud calculations stream `telemetry.jsonl` with a 1 MiB
per-row ceiling and strict finite nonnegative measurements; malformed rows are
skipped and named in the human cost view instead of crashing the command.
Structured cost and telemetry histories are not rotated or compacted until a
lossless archive and receipt-continuity design is approved.

Every cost-ledger consumer uses one strict coverage contract. Reads are
no-follow and side-effect-free, cap each encoded row at 1 MiB, cap confined
input at 16 MiB, and retain at most 10,000 valid rows. A valid cost row has a
finite nonnegative actual cost, an optional finite nonnegative estimate, and a
valid ISO timestamp. Coverage reports malformed rows, valid rows omitted by
the retention ceiling, invalid timestamps, and read errors. Valid retained
rows remain available for diagnosis, but incomplete coverage suppresses
totals, rolling spend, projections, estimator calibration, budget claims, and
surprise-cost warnings that require complete history.

## Topic-watch guardrails

```bash
distill topic-watch add "..." --max-run-cost 1.50 --monthly-budget 12
distill topic-watch budget <topic> --max-run-cost 2.00 --monthly-budget 15
distill topic-watch run <topic> --ignore-budget       # explicit override
```

- `--max-run-cost` skips a topic-watch when the projected next run exceeds the cap
- `--monthly-budget` skips a topic-watch when projected rolling 30-day spend would exceed budget
- One batch lock serializes budget evaluation with topic execution. A second
  concurrent batch refuses before provider work instead of racing the same
  budget evidence.
- The ledger is rescanned before every non-paused topic, so spend recorded by
  an earlier entry affects the next entry's decision.
- Incomplete cost coverage blocks a budgeted watch before provider work.
  `--ignore-budget` is the explicit operator override for that uncertainty.

## Model pricing (source of truth)

| Model | Input | Output | Context | Used for |
|---|---|---|---|---|
| `grok-4.6` | $2.00/1M | $6.00/1M | 500K | Default for analysis, reranking, synthesis, briefs, papers, sites, and report section writing |
| `grok-4.5` | $2.00/1M | $6.00/1M | 500K | Supported explicit override and previous default |
| `grok-4.3` | $1.25/1M | $2.50/1M | 1M | Supported explicit override and historical default |
| `grok-4-1-fast-reasoning` | - | - | - | **Retired 2026-05-15**; Distill substitutes the current `grok-4.6` default. The historical registry price remains for old ledger rows. |
| `grok-4.20-0309-non-reasoning` | $1.25/1M | $2.50/1M | 1M | Supported explicit non-reasoning override |
| `grok-4.20-0309-reasoning` | $1.25/1M | $2.50/1M | 1M | Supported explicit override |
| `deep-research-preview-04-2026` | token and tool based | External cost unavailable; $2.50 Distill planning placeholder | N/A | Accordion dossier, `deep-research` profile, `distill research-brief`; hard budgets refuse before remote setup |
| `deep-research-max-preview-04-2026` | token and tool based | External cost unavailable; $5 Distill planning placeholder | N/A | Explicit deeper-research override; hard budgets refuse before remote setup |
| `gemini-3.7-flash` | $0.75/1M through 2026-12-31, then $1.50/1M | $3.75/1M through 2026-12-31, then $7.50/1M | 1M | Preferred optional Gemini-provider chat model; doctor probe default |
| `gemini-3.6-flash` | $0.75/1M through 2026-12-31, then $1.50/1M | $3.75/1M through 2026-12-31, then $7.50/1M | 1M | Supported previous Gemini-provider chat default |
| `gemini-3.5-flash` | $1.50/1M | $9.00/1M | 1M | Optional Gemini-provider chat model (GA 2026-05-19); still selectable |
| `gemini-3.5-flash-lite` | $0.30/1M | $2.50/1M | 1M | High-throughput optional Gemini chat model (GA 2026-07-21) |
| `gemini-3.1-pro-preview` | $2.00/1M | $12.00/1M | 1M | Optional Gemini model; prompts over 200K use $4/$18 rates |
| `claude-sonnet-5` | $2.00/1M | $10.00/1M | 1M | Optional Anthropic-provider chat model; Anthropic cancelled the previously announced increase |
| `claude-opus-5` | $5.00/1M | $25.00/1M | 1M | Optional Anthropic model |
| `claude-fable-5` | $10.00/1M | $50.00/1M | 1M | Optional Anthropic model; highest widely available capability tier |
| `gpt-5.6-sol` | $5.00/1M | $30.00/1M | 1.05M | Reserved metadata only; OpenAI analysis route is not implemented |
| `gpt-5.6` | $5.00/1M | $30.00/1M | 1.05M | Reserved alias for Sol; OpenAI analysis route is not implemented |
| `gpt-5.6-terra` | $2.50/1M | $15.00/1M | 1.05M | Reserved metadata only; OpenAI analysis route is not implemented |
| `gpt-5.6-luna` | $1.00/1M | $6.00/1M | 1.05M | Reserved metadata only; OpenAI analysis route is not implemented |

As of 2026-08-13, both xAI tiers default to `grok-4.6`. Explicit model
overrides remain available and are costed by the same registry.

xAI's short-context prices above apply below 200K prompt tokens. At 200K or
more, Grok 4.6 and 4.5 cost $4 input and $12 output per 1M tokens, while Grok
4.3 and the registered Grok 4.20 family cost $2.50 input and $5 output. The
threshold applies per provider request, not to a run's aggregate tokens.
Distill prices each ledger entry at the applicable tier and keeps sequential
report estimates split across their representative calls.

Gemini 3.1 Pro Preview changes from $2/$12 to $4/$18 when a prompt exceeds
200K tokens. The reserved GPT-5.6 family changes to 2x input and 1.5x output
when a prompt exceeds 272K tokens. These thresholds are registered even though
OpenAI is not yet a routable Distill analysis provider, so future estimates
cannot inherit a known undercount.

The registry was reverified on 2026-08-13. `distill provider show` and
`distill provider list <provider>` expose the same review date and source URL
without making a network call. Authoritative pricing and capability sources are the
[xAI model catalog](https://docs.x.ai/developers/models),
[xAI pricing table](https://docs.x.ai/developers/pricing),
[Gemini pricing page](https://ai.google.dev/gemini-api/docs/pricing),
[Gemini Deep Research guide](https://ai.google.dev/gemini-api/docs/deep-research),
[Anthropic model overview](https://platform.claude.com/docs/en/about-claude/models/overview),
[Anthropic pricing guide](https://platform.claude.com/docs/en/about-claude/pricing),
[OpenAI model catalog](https://developers.openai.com/api/docs/models),
[OpenAI API pricing](https://developers.openai.com/api/docs/pricing),
[xAI speech-to-text pricing](https://docs.x.ai/developers/models/speech-to-text),
and [OpenAI Whisper pricing](https://developers.openai.com/api/docs/models/whisper-1).

## Overriding models

All model defaults are overridable via `.env`:

```bash
DISTILL_FAST_MODEL=grok-4.6
DISTILL_PREMIUM_MODEL=grok-4.6
DISTILL_ANALYSIS_MODEL=
DISTILL_SITE_MODEL=
DISTILL_SYNTHESIS_MODEL=
DISTILL_ACCORDION_MODEL=

# Multi-provider support
# Routable provider names: xai, gemini, anthropic, agent, ollama, lmstudio.
# agent is a deferred task-file handoff, not a live plan-quota CLI adapter.
# openai is a reserved analysis route and is not implemented in this release.
ANTHROPIC_API_KEY=
DISTILL_PROVIDER=xai                    # xai | gemini | anthropic | agent | ollama | lmstudio
DISTILL_MODEL=                          # e.g. gemini-3.7-flash with DISTILL_PROVIDER=gemini
DISTILL_ANALYSIS_PROVIDER=              # per-workload provider override
DISTILL_SYNTHESIS_PROVIDER=
DISTILL_ACCORDION_PROVIDER=             # sequential report sections and QA
```

Prefer the CLI over hand-editing when changing the default route:

```bash
distill provider set gemini gemini-3.7-flash
distill --provider gemini --model gemini-3.5-flash-lite papers "..." --limit 5
```

Leave the narrow overrides blank to use the broader `DISTILL_FAST_MODEL` and
`DISTILL_PREMIUM_MODEL` defaults. Both default to `grok-4.6`. Legacy `XAI_*`
model variables and `ACCORDION_SECTION_MODEL` remain migration aliases; a
matching `DISTILL_*` variable takes precedence.
Claude Sonnet 5 uses Anthropic adaptive thinking by default. Distill omits
explicit sampling parameters such as `temperature` for Sonnet 5 compatibility,
while still forwarding `DISTILL_<WORKLOAD>_REASONING_EFFORT` as
`output_config.effort` when explicitly set.
