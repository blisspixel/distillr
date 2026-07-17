# Architecture

How Distill works under the hood. Read this if you're contributing, debugging, or deciding whether the tool fits your use case.

## Data flow

```
  Discover (optional)         Source inputs                Capture               Per-item analysis         Synthesis               Report / briefing / synthesis
 ┌──────────────────┐       ┌──────────────────┐     ┌────────────────┐     ┌──────────────────────┐    ┌────────────────┐   ┌─────────────────────────────────┐
 │ distill discover │       │ YouTube channels │     │ yt-dlp         │     │ grok-4.3             │    │ Per-channel    │   │ distill report                  │
 │   goal → queries │──────▶│ YouTube search   │ ──▶ │ YouTube cap.   │ ──▶ │  2-pass full video   │─┐  │ synthesis      │   │  Gemini DR + Grok 4-phase       │
 │   goal rerank    │       │ arXiv search     │     │ Playwright     │     │  1-pass Short        │ │  │ Per-topic      │   │                                 │
 │   cross-source   │       │ Website seeds    │     │ pypdf (papers) │     │ configured route     │ │─▶│ synthesis      │─▶ │ distill research-brief          │
 │   shortlist      │       │ Single URL/paper │     │ Whisper ladder │     │  per-page / per-paper│ │  │ Mixed-source   │   │  Gemini Deep Research (grounded)│
 └──────────────────┘       └──────────────────┘     └────────────────┘     └──────────────────────┘─┘  │ corpus synth.  │   │                                 │
         │                          │                       │                          │                 └────────────────┘   │ distill synthesize              │
         │                          ▼                       ▼                          ▼                                      │  grok-4.3 single-call corpus    │
         │                  library/topics/<topic>/…  <slug>_Transcript.txt /                                              └─────────────────────────────────┘
         │                  (all artifacts as         <slug>_Content.md / <slug>_Paper.md                                                   │
         │                   frontmatter markdown)    + metadata.json +                                                                        ▼
         └─ (also feeds ingestion                     <slug>_Insights.md                                                            output/report-*.md
            directly via the same                                                                                                    output/briefing-*.md
            paper + video pipelines)                                                                                                 output/synthesis-*.md
                                                                                                                                     output/*.docx
```

Corpus content stays in plain Markdown or text under a local `library/`
directory, with JSON and JSONL used for metadata, append-only derived rows, and
operational evidence. No database or cloud store is the system of record. The
diagram names the normal cloud defaults; `DISTILL_PROVIDER=ollama` or
`DISTILL_PROVIDER=lmstudio` changes the model that analyzes the same freshly
captured public receipts.

## Discovery phase

`distill discover "<goal>"` (also accepts `--goal-file PATH`) sits **in front of** the capture → analyze → synthesize pipeline. It exists because a keyword query is not the same thing as a research goal. "Music theory deep learning" as a keyword returns physics and pure-math papers alongside music ones; "help an AI become a great music composer, computer-only" as a *goal* can be used to rerank candidates for whether they actually serve that goal.

The discover command does four things:

1. **Query generation.** The configured model route reads the goal and emits
   two sets of search queries, one for arXiv and one for YouTube, that complement
   each other rather than merely rephrasing the goal.
2. **Candidate fan-out.** Runs all arXiv queries via `search_arxiv_multi` (3.5s spaced, deduped by `paper_id`) and all YouTube queries via the existing browser/yt-dlp path. Typically returns 20-40 deduped candidates per source.
3. **Unified goal-aware rerank.** One call through the configured rerank route
   sees *all* candidates and the full goal text. It scores each on `goal_fit` /
   `depth_score` / `complementarity_score` / `final_score`. Papers and videos
   rank in the same pool, and the prompt asks for complementarity so the
   shortlist covers different angles rather than repeating one point.
4. **Execution.** Confirms (interactive prompt or `--yes`), then routes papers through the existing paper pipeline (`fetch_arxiv_paper` → `analyze_paper` → `_write_paper_artifacts`) and videos through the existing learning-video pipeline (`_process_learning_selection`). Runs the same syntheses on finish.

The same goal-aware rerank pattern also lives inside `distill papers` at a smaller scale (single source, query-grounded rather than goal-grounded): query expansion + `RankedPaper` rerank replaced the old "literal query, newest-first, blind top-N" behavior.

### arXiv query policy

The arXiv API's default parser OR's bare terms, so `temporal knowledge graph` returns anything mentioning any of those words. Previously we wrapped multi-word queries in quotes for phrase match, but that was too strict for 3+ word LLM-generated queries (`"symbolic music transformer composition"` as a literal phrase returns zero even when the target papers exist). The current policy in `_build_search_query`:

- 1 word → single-term search
- 2 words → phrase match (naturally phrasal: `"music transformer"`, `"agent memory"`)
- 3+ words → AND-join tokens so every term must appear but not necessarily adjacent
- Pre-operator input (quotes, `AND`, `OR`, parens) passes through untouched

This is the sweet spot between OR-flood noise and phrase-match brittleness.

### Rigor calibration (`--rigor` across discover / papers / latest)

`--rigor strict|balanced|loose` drops reranked candidates below a `final_score`
threshold before the per-source limit applies. The thresholds are **calibrated per
command, not shared**, because the three rerank prompts (`prompts/discover.py`)
score on different criteria:

| Command | Rerank prompt scores on | strict / balanced / loose |
|---------|-------------------------|---------------------------|
| `discover` | cross-source `goal_fit`, `depth`, `complementarity` | 0.70 / 0.50 / 0.30 |
| `papers` | `relevance`, `depth`, `novelty`, `credibility` (single-source, query-grounded) | 0.65 / 0.45 / 0.30 |
| `latest` | `relevance`, `depth`, `practicality`, `freshness`, `credibility` | 0.60 / 0.40 / 0.25 |

The divergence is **intentional**, and the calibration follows a real observation: on
one topic, `discover` rated 0/33 candidate videos worth ingesting at its bar while
`latest` surfaced 5 strong picks (including lectures by authors of that session's
top-ranked papers). `discover` is a cross-source *curation gate* - it asks "does this
earn a slot in a goal-built corpus alongside everything else?", so it scores
conservatively and its bar is highest. `papers` and `latest` are single-source
*relevance rankers* - the user already chose the source type and wants the best of it,
so those prompts score on-topic items a little more generously and their bars sit a
notch lower to avoid discarding strong picks. Thresholds live in
`distill/pipeline/discovery.py` (`RIGOR_THRESHOLDS`, `PAPER_RIGOR_THRESHOLDS`,
`VIDEO_RIGOR_THRESHOLDS`; resolved via `source_rigor_threshold(source, rigor)`); they
are initial calibration points, revised under the same versioned-prompt cadence as the
prompts themselves.

Two guardrails: rigor operates on the *LLM rerank* score, so under `--no-rerank` (or
chronological `--top-by-date`) an explicit bar is skipped with a warning rather than
applied to heuristic scores that live on a different scale; and on `papers`/`latest`
the default is `off` (keep the rerank's top-N as before), so the bar only engages when
asked for. `discover` keeps `balanced` as its default, unchanged since 0.8.12.

## How reports get built

A single LLM call cannot sustain analytical depth across a long document - it compresses, generalizes, and runs out of steam. Distill's report pipeline splits gathering facts from writing prose, then writes section-by-section with full context.

### Phase 1: Research (Gemini Deep Research)

Upload all insights and syntheses to a File Search store, then ask Deep Research (`deep-research-preview-04-2026`, built on Gemini 3.1 Pro) to validate, cross-reference, and extend using web sources. The output is raw structured facts across 8 categories: validated announcements, market data, competitive positioning, enterprise adoption, pricing/economics, corrections, coverage gaps, and forward signals.

File submission is not treated as indexing success. Only upload operations that
reach a successful terminal state count as grounded documents, and a zero-count
store cannot authorize a metered Deep Research interaction. Before any report,
dossier, or research briefing is accepted, the completed provider response must
contain a matched File Search call and result plus a file citation attached to
the final model output. Failed or timed-out uploads are excluded from the
grounding count, and missing or partial response evidence fails closed instead
of being described as grounded corpus use.

Citations must reference primary sources (not Wikipedia, not numbered `[cite: N]` formats). Creator estimates are explicitly tagged as such, never promoted to confirmed facts.

### Phase 2: Section writing (grok-4.3)

Sections are written sequentially, adapting to scope (single-channel vs multi-channel section lists). Each section receives:

- The full research output
- Tagged source material relevant to that section (e.g. vendor-specific insights for the Competitive Battleground)
- All previous sections for dedup (recent sections get 500 words of context, older get 150)
- Position guidance (opening / middle / closing tone)
- Voice guidance matching the section type:
  - **Reference** sections (Landscape, Gaps): factual, tables, no sales language
  - **Analytical** sections (Battleground, Corrections, Enterprise, Predictions): insight grounded in evidence
  - **Actionable** sections (Executive Briefing, Playbook, Synthesis): direct recommendations
- Temperature control: 0.3 for reference, 0.5 for analytical, 0.6 for actionable

A 3-consecutive-failure circuit breaker prevents wasting API calls if something goes wrong.

### Phase 3: Assembly

Sections get merged with header metadata, a table of contents, and section dividers. Any surviving numbered citation artifacts and word-count metadata are stripped.

### Phase 4: QA review (grok-4.3)

Read research + assembled report together. Score each section (PASS / FLAG / FAIL) checking for:

- Hallucinated claims - statistics or data not present in the research dossier (most critical check)
- Numbered citations - `[cite: N]` format that should be descriptive references
- Wikipedia as source - should cite primary sources
- Creator opinions labeled as facts - creator estimates labeled `[Confirmed]` instead of `[Estimated]`
- Inherited bias - sections that amplify creator bullishness/bearishness without counterweight
- Cross-section repetition - same facts restated instead of cross-referenced
- Wall-of-text paragraphs - paragraphs over ~80 words that need breaking up
- Missing confidence labels
- Contradictions between sections or with the research
- Voice drift - reference sections that sound like sales pitches, or vice versa

Any section that scores FAIL gets automatically rewritten with QA feedback injected. One retry per section max. Then re-assemble and export to both Markdown and DOCX.

## Key design decisions

The non-negotiable rules behind these decisions - what distill is, is not, and the
invariants that hold across versions (Markdown is the source of truth, any index is
derived and disposable, provenance on every artifact) - live in
[`invariants.md`](invariants.md). The decisions below are how this section's pipeline
implements that charter.

### Library-first organization

Topics group channels and sources by what you care about, not by who made the content. Research at the topic level is where the strongest findings come from - multiple perspectives on the same space, cross-referenced and validated.

### Everything captured, analysis weight varies

Full videos and Shorts both get processed, with different analysis weights:

- **Full videos (>3 min)**: 2-pass extraction (Pass 1 = facts, Pass 2 = synthesis)
- **Shorts (≤3 min)**: 1-pass extraction tuned for breaking news, quick takes, signal-strength rating
- **Scan mode** (watch/catch-up): 1-pass lightweight triage with custom per-channel instructions

All feed into channel synthesis, topic synthesis, and the report pipeline.

### Grounded analysis, no hallucination

Per-video prompts enforce strict grounding: the Vendor Watch and Customer Conversation Starters sections only reference products and services actually discussed in the video. Pass 1 captures the creator's full analytical frameworks and multi-part arguments. Pass 2 preserves the creator's reasoning chain rather than compressing into generic summaries.

Cross-channel and mixed-source synthesis distinguishes echoed claims from real corroboration: when several creators or source types appear to rely on the same originating post, repo, screenshot, or announcement, prompts tell the model to describe that as "widely repeated" rather than "independently corroborated."

Report prompts include explicit anti-hallucination rules: "NEVER invent statistics, studies, or data not in the research dossier." The QA phase checks for fabricated data as its highest-priority review item. Creator estimates and projections are labeled `[Estimated]` or `[Speculated]`, never `[Confirmed]`. Wikipedia is not accepted as a primary source.

### Model routing by workload

xAI model choice is separated by workload, overridable via `.env`:

| Workload | Default | Why |
|---|---|---|
| Bulk YouTube analysis, reranking, synthesis, briefs | `grok-4.3` ($1.25/$2.50 per 1M) | High volume, good quality at low cost |
| Website/page distillation, paper analysis, multi-topic deep synthesis | `grok-4.3` ($1.25/$2.50 per 1M) | Same model handles both tiers since 0.3.1 |

Gemini Deep Research (`deep-research-preview-04-2026`) handles report Phase 1 and `distill research-brief`.

See [cost.md](cost.md) for the full cost model.

MCP write tools have one deterministic accounting owner. The `write_tool`
boundary registers the tool's single cost tracker and persists it before a
success, ordinary failure, cancellation, or structured budget response crosses
the protocol boundary. A successful paid result fails closed if the ledger
cannot be written. If persistence fails while another terminal error is
already active, that original error remains authoritative and carries a safe
accounting-failure marker. This prevents retries, error conversion, and local
tool-specific cleanup from silently discarding provider usage.

The CLI uses the same terminal semantics at workflow boundaries. Credible
interactive estimates are checked before ingestion, a recorded budget crossing
must propagate past ordinary fallback handlers, and report tracker deltas are
persisted from one finalization path on every exit. Deep Research submission
interruptions are recorded conservatively as ambiguous after provider contact.
File Search store ownership begins as soon as creation returns a resource id;
every exceptional exit attempts remote deletion before the original error is
allowed to continue.

Live doctor probes and deferred-agent jobs follow the same admission rule.
Doctor preflight authorizes a conservative capped request before client
construction and aggregates all provider checks into one command receipt.
Deferred-agent usage has a stable attempt identity and is accepted before a
pending task becomes visible or a cached result is consumed. If admission or
durable accounting fails, the corresponding filesystem transition does not
occur.

An active host completes deferred work through a separate local queue boundary.
`distill worker claim` atomically publishes an ownership receipt, copies only
the task prompt and constrained metadata into identity-bound scratch, and
declares `result.md` as the only accepted write. Submission rechecks the pending
task, claim token, staged hashes, exact scratch file set, output bound, and
result hash before publishing a host receipt and replayable result. Abandonment
records an immutable event before releasing ownership, which lets another host
retry without sharing the first claim. Distill does not sandbox or launch the
active host, and it records that session as host-managed with unavailable
external cost.

### Transcript fallback chain

YouTube transcription uses a local-first fallback chain:

1. **YouTube captions** (free, instant) - yt-dlp downloads `.vtt` subtitles, cleaned to plain text. Works for most videos.
2. **Whisper provider ladder** - Captionless videos download bounded best-audio and use faster-whisper locally first, then tracked xAI Grok STT and OpenAI Whisper cloud fallbacks when configured and permitted by cost policy. The video's title and uploader provide a bounded vocabulary hint.
3. **Legacy Scribe fallback** - Installations with `SCRIBE_PATH` configured retain Scribe as a last-resort external fallback.
4. **Skip with error** - If every eligible route fails, the video is logged as failed in the post-run summary. The transcript file is not created, so a later refresh can retry.

Skipped videos surface in the "Failed" section of the run summary so they're visible rather than silently dropped.

### Source quality and bias controls

- Deep Research is instructed to cite primary sources (press releases, SEC filings, official blogs), not Wikipedia.
- Creator opinions and extrapolations are tagged `[Estimated]` or `[Speculated]`, never `[Confirmed]`.
- When creators share a systematic bias (e.g. uniformly bullish on a vendor category), the report flags it rather than amplifying it.
- Report prompts enforce readability: paragraphs under 80 words, markdown tables for comparisons, no em-dashes, no numbered citation artifacts.

### Confidence labels

Throughout the pipeline, claims are attributed to their source and labeled by confidence:

- `[Confirmed]` - Validated against official sources by Deep Research
- `[Reported]` - Claimed by a creator, not independently verified
- `[Estimated]` - Approximation based on available data
- `[Speculated]` - Prediction or hypothesis
- `[Analysis]` - Distill's own synthesis

The DOCX export renders these as color-coded badges for quick scanning.

### Refresh-first design

State tracking is built in. `--refresh` is the expected workflow - run on a cadence, process only what's new, let per-channel/topic synthesis update from the delta. Avoids re-processing items that haven't changed.

### Claim-based synthesis is a compiled view, not a hand-edited document

`distill resynthesize --two-pass` (and the MCP `synthesize` `two_pass` arg) splits corpus synthesis into two stages: a claim-extraction pass writes atomic claims from each per-source `_Insights.md` into an append-only `library/topics/<topic>/.claims/claims.jsonl`, then a synthesis pass clusters those claims, names contradictions, and writes `_Synthesis.md` with per-claim citations (`[C7]`).

This keeps the [charter invariant](invariants.md) load-bearing rather than incidental: the per-source `_Insights.md` (and the raw `_Content` / `_Paper` / `_Transcript` beside them) are the source of truth; `claims.jsonl` is a derived, disposable index over them; and each `_Synthesis.md` is a *view compiled from that index*, re-extractable from the Markdown at any time. The consequence is that a synthesis cannot silently drift from its evidence - you never hand-edit `_Synthesis.md`; if it is wrong or stale you fix or re-extract the claims and regenerate, so the prose can't diverge from what the sources say (the "confident misinformation" failure mode a hand-maintained wiki is prone to).

Atomic replacement prevents torn files, but it does not prevent two writers from
overwriting each other's complete updates. Claim appends and regenerated views
do not yet carry a per-topic lock or compare-and-swap token. Commands are
replay-safe, but external runners must serialize overlapping write scopes until
Distill ships an equivalent guard. Queues, leases, and backpressure remain the
external loop runner's responsibility.

Single-pass synthesis stays the default until the 1.0 golden-eval gate validates two-pass quality. See [`../ROADMAP.md`](../ROADMAP.md) for the surrounding milestones (0.9.0 two-pass, the 0.9.2 audit contradictions map, 0.10 stale-detection).

### Security hardening

- All `urllib.request.urlopen` calls route through `distill.net.safe_urlopen`, which rejects non-`https` schemes.
- arXiv XML parsing uses `defusedxml` instead of `xml.etree.ElementTree` to prevent XML-based attacks.
- SHA-1 used for content dedup is annotated `usedforsecurity=False` to make the non-cryptographic intent explicit.
- Subprocess calls use argument lists and resolve bare executable names to an
  absolute file from an absolute PATH entry. The current directory and
  relative PATH entries cannot supply package-manager or media-tool images.
- Package installation children run beside the active interpreter with Python
  path injection and provider credentials removed from their environment.
- Corpus reads exposed through MCP, local ingestion, cost history, and File
  Search use bounded no-follow regular-file validation. Linked, multiply
  linked, special, oversized, or identity-swapped files fail closed.
- Concept storage keys retain legacy short slugs, bound long components with a
  stable digest, avoid Windows device names, and key collision history by the
  resolved live filename rather than a shared lossy slug.
- Concept builds and rollbacks share a topic transaction lock across source
  admission, provider work, notes, histories, completion state, and rollups.
  Library latest-change updates use one library-wide lock, while atomic text
  writers and link repair share per-path write locks for complete
  read-derive-replace transactions.
- Release workflows use SHA-pinned GitHub Actions, including the PyPI publish action, while PyPI publishing stays on OIDC trusted publishing with PEP 740 attestations.

## Context engineering principles

Distill treats the prompt context window as a scarce, actively managed resource - not a place to dump everything. This is the same posture the 2025-2026 context-engineering literature converged on (Mei et al.'s 1,400-paper survey; Anthropic's compaction guidance; the ACE framework on evolving playbooks; LangChain's write/select/compress/isolate taxonomy). The lens is useful because it names *why* certain decisions in distillr are the way they are, and where the system is heading.

**Library is external memory, the prompt is working memory.** Every artifact lives on disk as plain markdown - `library/topics/<topic>/...` is the durable store; the prompt window is what we hydrate at inference time from that store. The same logic underpins the refresh-first design (only re-process what's new) and the watch lists (state lives in `library/watch_state.json`, not in chat history). This maps to the "Write" pillar: persist outside the model so the active window stays lean.

**Just-in-time hydration over preloading.** `distill discover` pulls papers + videos *against a goal* and reranks before ingesting; `distill papers` expands and reranks before per-paper analysis; channel watches load only delta videos since the last run. The system never asks "load everything for this topic and let the model figure it out" - it asks "what's the smallest sufficient set for this query?" This is the "Select" pillar.

**Workload-tuned model routing trades fidelity against context budget.** Routing is by workload tag, not a single hard-coded model: analysis, synthesis, site/paper, and report-section workloads each resolve through `distill/llm/router.py`. On the cloud floor those tags currently all resolve to `grok-4.3` (1M-token window; the cheaper grok-4-fast tiers retired 2026-05-15 and now redirect to it), while report Phase 1 routes to Gemini Deep Research for web-grounded retrieval. Anthropic `claude-sonnet-5` is also wired as an explicit opt-in metered route with a 1M-token window, but it is not a calibrated default until `distill eval` proves it for a workload. Keeping the tags distinct even when they collapse to one cloud model is deliberate: the routing seam is where a local model or a different provider can take a specific workload, such as bulk transcripts on local compute or harder mid-length synthesis on cloud, so each workload gets the model whose effective context window and cost fit it best, not the largest claimed window. The cross-provider, cost-aware version of that choice is what `distill eval` measures (see [`../ROADMAP.md`](../ROADMAP.md), "Looking beyond 1.0").

**Confidence labels and source tagging keep provenance in-band.** `[Confirmed]` / `[Reported]` / `[Estimated]` / `[Speculated]` / `[Analysis]` aren't decorative - they're how downstream prompts (synthesis, report, briefing) avoid laundering uncertainty across handoffs. This is the "Provenance" criterion from Vishnyakova's production-grade context-engineering rubric.

**Current context controls and remaining gaps.** Two earlier gaps now have
working first implementations:

1. MCP query tools default to paths, bounded previews, and explicit drill-down
   reads. Full bodies remain available only when the caller asks for a specific
   artifact or resource. Further action-tool consolidation remains roadmap work.
2. The 4-phase report pipeline uses high-recall compaction and an optional
   precision pass between phases. Prompt telemetry makes its token cost visible.
   Provider-native opaque continuation items and further measured compaction
   remain roadmap work.

## Known technical debt (resolved in 0.7)

The following items were present in the codebase prior to 0.7 and have been resolved in the 0.7.0/0.7.1 releases.

- **`_cli_impl.py` is oversized (~1,200+ lines).** The 0.3 restructure moved wiring to `cli.py` and created the `commands/` subpackage, but business logic (private `_discover_*`, `_llm_expand_*` helpers) stayed in `_cli_impl.py` as a migration holding area. 0.7 decomposes it into per-command modules.
- **Artifact provenance is incomplete.** YAML frontmatter records `analyzed_by` (model name) and cost, but not exact model version, temperature, seed, or prompt identifier. 0.7 adds full provenance fields.
- **Legacy migration bridge in `config.py`.** `router_config_from_distill` contains env-parsing inside functions and import-side effects from the pre-0.3 era. Scheduled for deletion in 0.7 (Grok 4.3 retirement May 15, 2026 is the forcing function).
- **Slugify/path logic lives in `config.py`.** `sanitize_path_component` and `slugify_title` belong in `library/paths.py`. 0.7 moves them.
- **Report-phase circuit breaker lacks backoff/jitter.** The 3-failure breaker retries immediately. 0.7 adds exponential backoff with jitter and an `LLMCall` dataclass for debugging.
- **Pyright is in basic mode.** New modules added in 0.7+ get `# pyright: strict`. Global strict enforcement is scheduled for 1.0.

### Deliberate design choices (not debt)

These are sometimes flagged in audits but are intentional:

- **No database of record.** Markdown and JSONL are load-bearing. A measured
  search or dedup accelerator may use a disposable index under `.distill/`, but
  it must be git-ignored, rebuildable, non-authoritative, and paired with a
  direct-file fallback. This is the same boundary defined in
  [`invariants.md`](invariants.md): derived index yes when justified; corpus
  authority never.
- **No `src/` layout.** The flat `distill/` package is standard for single-package projects and works fine with the current build tooling. Revisit only if namespace collisions emerge.
- **No full PromptRegistry / A/B framework.** Prompt versioning via `prompt_id` in frontmatter (0.7) provides reproducibility. A registry class is premature until the prompt surface stabilizes post-0.8.
- **Import-linter enforces dependency direction in CI.** "Risk of creeping imports" is not a gap - violations fail the build.

A note on paper analysis: the previous roadmap flagged "100K-char PDF in a single prompt" as a fidelity risk. In 2026, cloud models (Grok 4.3 at 1M tokens, Gemini 3.1 Pro at 1M tokens) handle this comfortably - a 100K-char paper is roughly 25K tokens, well within the effective attention range of these models. The lost-in-the-middle concern applies primarily to local models with 8K-32K context windows. The fix (0.6) is adaptive: the router knows each provider's context window and only chunks when the content exceeds it. Cloud users get single-pass analysis with no overhead; local-model users get section-aware chunking with per-category rerank.

## Current package layout

```
distill/                           # Python package
├── cli.py                         # Typer registration and entry point
├── _app.py                        # Top-level Typer app and command resolver
├── _cli_impl.py                   # Private compatibility exports only
├── cli_shared.py                  # Shared CLI state and helpers
├── config.py                      # Core settings and library paths
├── commands/                      # User-facing CLI ownership
│   ├── root.py                    # Global callback and help surface
│   ├── discover.py, learn.py      # Discovery and topic-learning workflows
│   ├── process.py, ingest.py      # YouTube and direct-source processing
│   ├── papers.py, reports.py      # Papers, briefs, reports, and exports
│   ├── reprocess.py, view.py      # Regeneration and read surfaces
│   ├── maintain.py, doctor.py     # Costs, status, health, and diagnostics
│   ├── eval.py, profile.py        # Model eval and recurring profiles
│   ├── audit.py, topic.py         # Trust reports and topic-first workflows
│   ├── watch.py, topic_watch.py   # Channel and topic watches
│   └── _*.py                      # Narrow shared parsers and renderers
├── ingestors/                     # Source capture adapters
│   ├── youtube/, sites/, papers/
│   └── transcribe.py              # Local-first speech-to-text ladder
├── pipeline/                      # Domain orchestration below CLI and MCP
│   ├── analysis/, synthesis/, report/
│   ├── costs.py                   # Cost tracker and usage ledger
│   ├── performance_history.py     # Exact-ID performance correlation
│   ├── discovery.py, ranking.py   # Candidate planning and model reranking
│   ├── profile_preview.py         # Recurring source-plan resolution
│   ├── profile_run.py             # Approved replay and resume state
│   └── audit.py, verify.py        # Deterministic trust and grounding layers
├── library/                       # Corpus paths, state, profiles, and exports
├── claims/, concepts/             # Derived knowledge layers
├── prompts/                       # Versioned prompt builders and lenses
├── llm/                           # Provider router, policy, and telemetry
│   └── providers/                 # xAI, Gemini, Anthropic, local, deferred agent
├── worker/                        # Deferred-task claim and scratch protocol
├── doctor/                        # Local and candidate-adapter readiness
├── eval/                          # Frozen fixtures, judges, and route admission
├── mcp/                           # FastMCP tools, resources, and prompts
└── web/                           # Loopback dashboard server and templates

library/                           # Per-user data (git-ignored)
├── library.json                   # Master index
├── .distill/                      # Local operational records
│   ├── cost_log.jsonl             # Model-using run cost history
│   ├── telemetry.jsonl            # Per-provider-call token and timing rows
│   ├── phase_telemetry.jsonl      # Content-free correlated phase timing
│   ├── tasks/pending/              # Deferred tasks and claim/result receipts
│   ├── tasks/work/                 # Per-claim scratch workspaces
│   └── distill.log                # Rotating diagnostic log
└── topics/<topic>/…               # Per-topic artifacts
```

### Dependency direction

The blocking `import-linter` contracts match the actual dependency boundaries:
`library/` and `prompts/` cannot import from commands, ingestors, pipeline, MCP,
or web; ingestors cannot import from commands, pipeline, or MCP; pipeline cannot
import from commands or MCP; and the concepts/claims knowledge layers cannot
import from commands, MCP, web, or ingestors. Commands and MCP remain the main
top-level adapters over those lower layers.

### Derived knowledge grounding

Concept extraction keeps semantic classification with the configured model,
but persistence admission is rule-owned. The version 2 extraction contract
returns an exact body quote containing the exact surface name. Python removes
frontmatter, links, fenced code, URLs, and markup-only controls from the
evidence view, then requires both spans to match before a mention can enter the
append-only log. Canonical identity is derived locally from the grounded
surface name, never accepted from model output. Cross-source thresholds
therefore count only receipt-bound mentions.

Repository insights carry the exact receipt filename and a SHA-256 digest of
its normalized body. The current repository receipt carries the same digest.
Shared insight discovery recomputes and compares both values before exposing a
GitHub insight to concepts, claims, freshness checks, ingestion indexes,
synthesis, or audit. A re-ingest therefore invalidates the prior generation
immediately when the new receipt is committed, even if strict verification
refuses the replacement insight or the
process stops between writes. The old file remains available for recovery but
cannot masquerade as analysis of the current receipt.

Topic-level synthesis identities preserve source modality. Cross-channel video
analysis writes `<topic>_Topic_Synthesis.md`; cross-site analysis writes
`<topic>_Site_Synthesis.md`; paper and mixed-corpus rollups keep their existing
dedicated artifacts. Each producer also owns a distinct verification receipt,
so producer order cannot replace another modality's evidence or provenance.
