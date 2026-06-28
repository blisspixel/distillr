# Architecture

How Distill works under the hood. Read this if you're contributing, debugging, or deciding whether the tool fits your use case.

## Data flow

```
  Discover (optional)         Source inputs                Capture               Per-item analysis         Synthesis               Report / briefing / synthesis
 ┌──────────────────┐       ┌──────────────────┐     ┌────────────────┐     ┌──────────────────────┐    ┌────────────────┐   ┌─────────────────────────────────┐
 │ distill discover │       │ YouTube channels │     │ yt-dlp         │     │ grok-4.3             │    │ Per-channel    │   │ distill report                  │
 │   goal → queries │──────▶│ YouTube search   │ ──▶ │ YouTube cap.   │ ──▶ │  2-pass full video   │─┐  │ synthesis      │   │  Gemini DR + Grok 4-phase       │
 │   goal rerank    │       │ arXiv search     │     │ Playwright     │     │  1-pass Short        │ │  │ Per-topic      │   │                                 │
 │   cross-source   │       │ Website seeds    │     │ pypdf (papers) │     │ grok-4.3 (1M ctx)    │ │─▶│ synthesis      │─▶ │ distill research-brief          │
 │   shortlist      │       │ Single URL/paper │     │ Scribe (fall.) │     │  per-page / per-paper│ │  │ Mixed-source   │   │  Gemini Deep Research (grounded)│
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

Everything between the source inputs and the final outputs is plain markdown in a local `library/` directory. No database, no cloud storage, no proprietary format.

## Discovery phase

`distill discover "<goal>"` (also accepts `--goal-file PATH`) sits **in front of** the capture → analyze → synthesize pipeline. It exists because a keyword query is not the same thing as a research goal. "Music theory deep learning" as a keyword returns physics and pure-math papers alongside music ones; "help an AI become a great music composer, computer-only" as a *goal* can be used to rerank candidates for whether they actually serve that goal.

The discover command does four things:

1. **Query generation.** Grok reads the goal and emits two sets of search queries - one for arXiv, one for YouTube - that complement each other (different angles of the goal, not just rephrasings).
2. **Candidate fan-out.** Runs all arXiv queries via `search_arxiv_multi` (3.5s spaced, deduped by `paper_id`) and all YouTube queries via the existing browser/yt-dlp path. Typically returns 20-40 deduped candidates per source.
3. **Unified goal-aware rerank.** One Grok call sees *all* candidates (papers and videos mixed) and the full goal text. Scores each on `goal_fit` / `depth_score` / `complementarity_score` / `final_score`. Papers and videos rank in the same pool - a substantive paper outranks a shallow video on the same topic and vice versa. The prompt explicitly asks for *complementarity*, so the shortlist covers different angles rather than five items making the same point.
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

### Transcript fallback chain

Transcription uses a 3-tier strategy:

1. **YouTube captions** (free, instant) - yt-dlp downloads `.vtt` subtitles, cleaned to plain text. Works for most videos.
2. **Scribe local transcription** (free, local) - If captions aren't available, Distill calls scribe as a subprocess for local Whisper-based transcription. Requires `SCRIBE_PATH` in `.env`.
3. **Skip with error** - If both fail, the video is logged as failed in the post-run summary. The transcript file isn't created, so `--refresh` retries on the next run.

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

This keeps the [charter invariant](invariants.md) load-bearing rather than incidental: the per-source `_Insights.md` (and the raw `_Content` / `_Paper` / `_Transcript` beside them) are the source of truth; `claims.jsonl` is a derived, disposable index over them; and each `_Synthesis.md` is a *view compiled from that index*, re-extractable from the Markdown at any time. The consequence is that a synthesis cannot silently drift from its evidence - you never hand-edit `_Synthesis.md`; if it is wrong or stale you fix or re-extract the claims and regenerate, so the prose can't diverge from what the sources say (the "confident misinformation" failure mode a hand-maintained wiki is prone to). Append-only-then-regenerate is also concurrency-safe: appending claim rows and regenerating a view never hits the multi-writer conflict that editing one shared Markdown file in place would.

Single-pass synthesis stays the default until the 1.0 golden-eval gate validates two-pass quality. See [`../ROADMAP.md`](../ROADMAP.md) for the surrounding milestones (0.9.0 two-pass, the 0.9.2 audit contradictions map, 0.10 stale-detection).

### Security hardening

- All `urllib.request.urlopen` calls route through `distill.net.safe_urlopen`, which rejects non-`https` schemes.
- arXiv XML parsing uses `defusedxml` instead of `xml.etree.ElementTree` to prevent XML-based attacks.
- SHA-1 used for content dedup is annotated `usedforsecurity=False` to make the non-cryptographic intent explicit.
- Subprocess calls to `yt-dlp` / `scribe` pass arguments as lists (not shell strings), avoiding injection.

## Context engineering principles

Distill treats the prompt context window as a scarce, actively managed resource - not a place to dump everything. This is the same posture the 2025-2026 context-engineering literature converged on (Mei et al.'s 1,400-paper survey; Anthropic's compaction guidance; the ACE framework on evolving playbooks; LangChain's write/select/compress/isolate taxonomy). The lens is useful because it names *why* certain decisions in distillr are the way they are, and where the system is heading.

**Library is external memory, the prompt is working memory.** Every artifact lives on disk as plain markdown - `library/topics/<topic>/...` is the durable store; the prompt window is what we hydrate at inference time from that store. The same logic underpins the refresh-first design (only re-process what's new) and the watch lists (state lives in `library/watch_state.json`, not in chat history). This maps to the "Write" pillar: persist outside the model so the active window stays lean.

**Just-in-time hydration over preloading.** `distill discover` pulls papers + videos *against a goal* and reranks before ingesting; `distill papers` expands and reranks before per-paper analysis; channel watches load only delta videos since the last run. The system never asks "load everything for this topic and let the model figure it out" - it asks "what's the smallest sufficient set for this query?" This is the "Select" pillar.

**Workload-tuned model routing trades fidelity against context budget.** Routing is by workload tag, not a single hard-coded model: analysis, synthesis, site/paper, and report-section workloads each resolve through `distill/llm/router.py`. On the cloud floor those tags currently all resolve to `grok-4.3` (1M-token window; the cheaper grok-4-fast tiers retired 2026-05-15 and now redirect to it), while report Phase 1 routes to Gemini Deep Research for web-grounded retrieval. Keeping the tags distinct even when they collapse to one cloud model is deliberate: the routing seam is where a local model or a different provider can take a specific workload, such as bulk transcripts on local compute or harder mid-length synthesis on cloud, so each workload gets the model whose effective context window and cost fit it best, not the largest claimed window. The cross-provider, cost-aware version of that choice is what `distill eval` measures (see [`../ROADMAP.md`](../ROADMAP.md), "Looking beyond 1.0").

**Confidence labels and source tagging keep provenance in-band.** `[Confirmed]` / `[Reported]` / `[Estimated]` / `[Speculated]` / `[Analysis]` aren't decorative - they're how downstream prompts (synthesis, report, briefing) avoid laundering uncertainty across handoffs. This is the "Provenance" criterion from Vishnyakova's production-grade context-engineering rubric.

**Where distillr is still naive about context.** Two known gaps that the roadmap ([`../ROADMAP.md`](../ROADMAP.md)) explicitly addresses:

1. *MCP tool returns* hand the consuming agent full markdown files - Anthropic's published example shows ~98% token savings from switching to filtered/path-based returns instead. Fix (0.5): paths-not-payloads with a drill-down second tool call.
2. *4-phase report pipeline* carries full prior-section context forward to enforce no-repeat. Fix (0.6): high-recall-then-precision compaction; opaque continuation items where the API supports them.

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

- **No database / SQLite index.** The "no database" principle is load-bearing. `find_insights` (0.5) handles search via ranked path+preview returns. Semantic dedup (0.10) will use embeddings as an implementation detail, not a user-facing store.
- **No `src/` layout.** The flat `distill/` package is standard for single-package projects and works fine with the current build tooling. Revisit only if namespace collisions emerge.
- **No full PromptRegistry / A/B framework.** Prompt versioning via `prompt_id` in frontmatter (0.7) provides reproducibility. A registry class is premature until the prompt surface stabilizes post-0.8.
- **Import-linter enforces dependency direction in CI.** "Risk of creeping imports" is not a gap - violations fail the build.

A note on paper analysis: the previous roadmap flagged "100K-char PDF in a single prompt" as a fidelity risk. In 2026, cloud models (Grok 4.3 at 1M tokens, Gemini 3.1 Pro at 1M tokens) handle this comfortably - a 100K-char paper is roughly 25K tokens, well within the effective attention range of these models. The lost-in-the-middle concern applies primarily to local models with 8K-32K context windows. The fix (0.6) is adaptive: the router knows each provider's context window and only chunks when the content exceeds it. Cloud users get single-pass analysis with no overhead; local-model users get section-aware chunking with per-category rerank.

## Package layout (0.4.0)

```
distill/                           # Python package - layered subpackage architecture
├── cli.py                         # ≤150-line Typer wiring module (entry point)
├── _cli_impl.py                   # Business logic (migrated from the original cli.py)
├── _bootstrap.py                  # UTF-8 stdio side-effect import
├── _logging.py                    # Structured logging (configure_logging, --debug)
├── config.py                      # Settings (Pydantic) - SecretStr API keys, model pins
│
├── commands/                      # One Typer command group per file
│   ├── _helpers.py                # Cross-command UI helpers (from cli_shared.py)
│   ├── costs.py                   # distill costs
│   ├── dashboard.py               # distill dashboard, distill status
│   ├── discover.py                # distill discover, learn, explore, search, monitor, ramp-up
│   ├── doctor.py                  # distill doctor, health, cleanup, migrate
│   ├── latest.py                  # distill latest, run, catch-up, reanalyze, channel, video
│   ├── library.py                 # distill add, remove, library, videos, show, open, etc.
│   ├── papers.py                  # distill paper, papers, corpus
│   ├── report.py                  # distill report, brief, export
│   ├── research_brief.py          # distill research-brief
│   ├── serve.py                   # distill serve
│   ├── site.py                    # distill site, site-batch
│   ├── synthesize.py              # distill synthesize, resynthesize
│   ├── topic.py                   # distill topic create/preview/update/brief/report/show/export/watch
│   ├── topic_watch.py             # distill topic-watch *
│   └── watch.py                   # distill watch *
│
├── ingestors/                     # Capture layer - one source per subpackage
│   ├── youtube/
│   │   ├── discovery.py           # VideoInfo, discover_videos, search_videos
│   │   ├── transcripts.py         # get_transcript, _vtt_to_text
│   │   └── browser_search.py      # search_youtube_results (Playwright)
│   ├── sites/
│   │   ├── scraper.py             # SitePage, SiteSeed, crawl_site
│   │   └── attachments.py         # PDF/video attachment ingestion
│   ├── papers/
│   │   └── arxiv.py               # PaperRecord, search_arxiv_papers, PDF extraction
│   └── net.py                     # URL safety helpers (safe_urlopen)
│
├── pipeline/                      # Orchestration layer
│   ├── analysis/
│   │   ├── video.py               # 2-pass full video + 1-pass Shorts
│   │   ├── site.py                # Per-page insights + site synthesis
│   │   └── paper.py               # Per-paper insights + paper synthesis
│   ├── synthesis/
│   │   ├── topic.py               # Per-channel / per-topic synthesis
│   │   └── corpus.py              # Cross-source corpus synthesis
│   ├── report/
│   │   ├── deep_research.py       # Gemini Deep Research
│   │   ├── accordion.py           # 4-phase report orchestrator
│   │   ├── brief.py               # Multi-topic Deep Research briefing
│   │   ├── briefing.py            # Lightweight single-topic brief
│   │   ├── synthesize.py          # Multi-topic Grok single-call synthesis
│   │   └── file_search.py         # Gemini File Search store management
│   ├── costs.py                   # Token/cost tracking (CostTracker)
│   ├── dashboard_data.py          # Shared dashboard data functions
│   ├── discovery.py               # Goal-aware cross-source discovery
│   ├── ranking.py                 # Video + paper reranking
│   └── summary.py                 # Post-run summary display
│
├── prompts/                       # All prompt templates centralized
│   ├── analysis.py                # pass1, pass2, shorts, scan, channel context
│   ├── synthesis.py               # channel, topic, corpus, site, paper synthesis
│   ├── report.py                  # deep research, accordion, brief prompts
│   ├── discover.py                # query expansion, rerank, discover prompts
│   └── shared.py                  # anti-hallucination, provenance rules
│
├── library/                       # Filesystem corpus layer (foundational)
│   ├── paths.py                   # Artifact path resolution + frontmatter
│   ├── state.py                   # Library + ChannelState management
│   └── export.py                  # Markdown → DOCX
│
├── llm/                           # LLM router (foundational, no changes in 0.4)
│   ├── router.py                  # Workload-to-provider dispatch
│   ├── cost.py                    # Unified cost registry
│   ├── telemetry.py               # Per-prompt telemetry
│   └── providers/                 # xAI, Gemini, Ollama, LM Studio, Agent
│
├── mcp/                           # MCP server
│   ├── server.py                  # Transport, registration, lifecycle
│   ├── resources.py               # All resource handlers
│   ├── prompts.py                 # MCP-protocol prompt definitions
│   └── tools/                     # One file per tool group
│       ├── discover.py            # learn_topic, search_videos
│       ├── topics.py              # process_video_url
│       ├── watch.py               # catch_up, watch_add, watch_remove
│       ├── reports.py             # generate_report, resynthesize_topic
│       └── gaps.py                # research_gaps
│
└── web/                           # Local dashboard (FastAPI + Jinja2 + HTMX)
    ├── server.py
    ├── routes/
    ├── templates/
    └── static/

tests/                             # Mirrored test layout
├── conftest.py
├── test_config.py
├── unit/
│   ├── commands/                  # CLI command tests
│   ├── ingestors/youtube/         # YouTube ingestor tests
│   ├── ingestors/sites/           # Site ingestor tests
│   ├── ingestors/papers/          # Paper ingestor tests
│   ├── pipeline/analysis/         # Analysis pipeline tests
│   ├── pipeline/synthesis/        # Synthesis pipeline tests
│   ├── pipeline/report/           # Report pipeline tests
│   ├── library/                   # Library layer tests
│   ├── prompts/                   # Prompt tests
│   ├── mcp/                       # MCP server tests
│   └── llm/                       # LLM router tests
└── integration/                   # Full-pipeline tests (gated behind -m integration)

library/                           # Per-user data (git-ignored)
├── library.json                   # Master index
├── .distill/                      # Ops data (telemetry, cost logs, distill.log)
├── cost_log.jsonl                 # Run cost history
└── topics/<topic>/…               # Per-topic artifacts
```

### Dependency direction

Foundational layers (`library/`, `llm/`, `prompts/`) have zero imports from other `distill.*` subpackages. `ingestors/` imports only from foundational layers. `pipeline/` imports from ingestors and foundational layers. `commands/` and `mcp/` sit on top. Enforced by `import-linter` in CI.
