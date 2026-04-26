# Architecture

How Distill works under the hood. Read this if you're contributing, debugging, or deciding whether the tool fits your use case.

## Data flow

```
  Discover (optional)         Source inputs                Capture               Per-item analysis         Synthesis               Report / briefing / synthesis
 ┌──────────────────┐       ┌──────────────────┐     ┌────────────────┐     ┌──────────────────────┐    ┌────────────────┐   ┌─────────────────────────────────┐
 │ distill discover │       │ YouTube channels │     │ yt-dlp         │     │ Grok 4.1 Fast        │    │ Per-channel    │   │ distill report                  │
 │   goal → queries │──────▶│ YouTube search   │ ──▶ │ YouTube cap.   │ ──▶ │  2-pass full video   │─┐  │ synthesis      │   │  Gemini DR + Grok 4-phase       │
 │   goal rerank    │       │ arXiv search     │     │ Playwright     │     │  1-pass Short        │ │  │ Per-topic      │   │                                 │
 │   cross-source   │       │ Website seeds    │     │ pypdf (papers) │     │ Grok 4.20 Reasoning  │ │─▶│ synthesis      │─▶ │ distill research-brief          │
 │   shortlist      │       │ Single URL/paper │     │ Scribe (fall.) │     │  per-page / per-paper│ │  │ Mixed-source   │   │  Gemini Deep Research (grounded)│
 └──────────────────┘       └──────────────────┘     └────────────────┘     └──────────────────────┘─┘  │ corpus synth.  │   │                                 │
         │                          │                       │                          │                 └────────────────┘   │ distill synthesize              │
         │                          ▼                       ▼                          ▼                                      │  Grok 4.20 single large-context │
         │                  library/topics/<topic>/…  transcript.txt /                                                         └─────────────────────────────────┘
         │                  (all artifacts as         content.md / paper.md                                                                    │
         │                   plain markdown)          + metadata.json +                                                                        ▼
         └─ (also feeds ingestion                     insights.md                                                                    output/report-*.md
            directly via the same                                                                                                    output/briefing-*.md
            paper + video pipelines)                                                                                                 output/synthesis-*.md
                                                                                                                                     output/*.docx
```

Everything between the source inputs and the final outputs is plain markdown in a local `library/` directory. No database, no cloud storage, no proprietary format.

## Discovery phase

`distill discover "<goal>"` (also accepts `--goal-file PATH`) sits **in front of** the capture → analyze → synthesize pipeline. It exists because a keyword query is not the same thing as a research goal. "Music theory deep learning" as a keyword returns physics and pure-math papers alongside music ones; "help an AI become a great music composer, computer-only" as a *goal* can be used to rerank candidates for whether they actually serve that goal.

The discover command does four things:

1. **Query generation.** Grok reads the goal and emits two sets of search queries — one for arXiv, one for YouTube — that complement each other (different angles of the goal, not just rephrasings).
2. **Candidate fan-out.** Runs all arXiv queries via `search_arxiv_multi` (3.5s spaced, deduped by `paper_id`) and all YouTube queries via the existing browser/yt-dlp path. Typically returns 20–40 deduped candidates per source.
3. **Unified goal-aware rerank.** One Grok call sees *all* candidates (papers and videos mixed) and the full goal text. Scores each on `goal_fit` / `depth_score` / `complementarity_score` / `final_score`. Papers and videos rank in the same pool — a substantive paper outranks a shallow video on the same topic and vice versa. The prompt explicitly asks for *complementarity*, so the shortlist covers different angles rather than five items making the same point.
4. **Execution.** Confirms (interactive prompt or `--yes`), then routes papers through the existing paper pipeline (`fetch_arxiv_paper` → `analyze_paper` → `_write_paper_artifacts`) and videos through the existing learning-video pipeline (`_process_learning_selection`). Runs the same syntheses on finish.

The same goal-aware rerank pattern also lives inside `distill papers` at a smaller scale (single source, query-grounded rather than goal-grounded): query expansion + `RankedPaper` rerank replaced the old "literal query, newest-first, blind top-N" behavior.

### arXiv query policy

The arXiv API's default parser OR's bare terms, so `temporal knowledge graph` returns anything mentioning any of those words. Previously we wrapped multi-word queries in quotes for phrase match, but that was too strict for 3+ word LLM-generated queries (`"symbolic music transformer composition"` as a literal phrase returns zero even when the target papers exist). The current policy in `_build_search_query`:

- 1 word → single-term search
- 2 words → phrase match (naturally phrasal: `"music transformer"`, `"agent memory"`)
- 3+ words → AND-join tokens so every term must appear but not necessarily adjacent
- Pre-operator input (quotes, `AND`, `OR`, parens) passes through untouched

This is the sweet spot between OR-flood noise and phrase-match brittleness.

## How reports get built

A single LLM call cannot sustain analytical depth across a long document — it compresses, generalizes, and runs out of steam. Distill's report pipeline splits gathering facts from writing prose, then writes section-by-section with full context.

### Phase 1: Research (Gemini Deep Research)

Upload all insights and syntheses to a File Search store, then ask Deep Research (`deep-research-pro-preview-12-2025`, built on Gemini 3.1 Pro) to validate, cross-reference, and extend using web sources. The output is raw structured facts across 8 categories: validated announcements, market data, competitive positioning, enterprise adoption, pricing/economics, corrections, coverage gaps, and forward signals.

Citations must reference primary sources (not Wikipedia, not numbered `[cite: N]` formats). Creator estimates are explicitly tagged as such, never promoted to confirmed facts.

### Phase 2: Section writing (Grok 4.1 Fast Reasoning)

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

### Phase 4: QA review (Grok 4.1 Fast Reasoning)

Read research + assembled report together. Score each section (PASS / FLAG / FAIL) checking for:

- Hallucinated claims — statistics or data not present in the research dossier (most critical check)
- Numbered citations — `[cite: N]` format that should be descriptive references
- Wikipedia as source — should cite primary sources
- Creator opinions labeled as facts — creator estimates labeled `[Confirmed]` instead of `[Estimated]`
- Inherited bias — sections that amplify creator bullishness/bearishness without counterweight
- Cross-section repetition — same facts restated instead of cross-referenced
- Wall-of-text paragraphs — paragraphs over ~80 words that need breaking up
- Missing confidence labels
- Contradictions between sections or with the research
- Voice drift — reference sections that sound like sales pitches, or vice versa

Any section that scores FAIL gets automatically rewritten with QA feedback injected. One retry per section max. Then re-assemble and export to both Markdown and DOCX.

## Key design decisions

### Library-first organization

Topics group channels and sources by what you care about, not by who made the content. Research at the topic level is where the strongest findings come from — multiple perspectives on the same space, cross-referenced and validated.

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
| Bulk YouTube analysis, reranking, synthesis, briefs | `grok-4-1-fast-reasoning` ($0.20/$0.50 per 1M) | High volume, cost-sensitive |
| Website/page distillation, paper analysis, multi-topic deep synthesis | `grok-4.20-0309-reasoning` ($2.00/$6.00 per 1M) | Higher fidelity on messy content |

Gemini Deep Research (`deep-research-pro-preview-12-2025`) handles report Phase 1 and `distill research-brief`.

See [cost.md](cost.md) for the full cost model.

### Transcript fallback chain

Transcription uses a 3-tier strategy:

1. **YouTube captions** (free, instant) — yt-dlp downloads `.vtt` subtitles, cleaned to plain text. Works for most videos.
2. **Scribe local transcription** (free, local) — If captions aren't available, Distill calls scribe as a subprocess for local Whisper-based transcription. Requires `SCRIBE_PATH` in `.env`.
3. **Skip with error** — If both fail, the video is logged as failed in the post-run summary. The transcript file isn't created, so `--refresh` retries on the next run.

Skipped videos surface in the "Failed" section of the run summary so they're visible rather than silently dropped.

### Source quality and bias controls

- Deep Research is instructed to cite primary sources (press releases, SEC filings, official blogs), not Wikipedia.
- Creator opinions and extrapolations are tagged `[Estimated]` or `[Speculated]`, never `[Confirmed]`.
- When creators share a systematic bias (e.g. uniformly bullish on a vendor category), the report flags it rather than amplifying it.
- Report prompts enforce readability: paragraphs under 80 words, markdown tables for comparisons, no em-dashes, no numbered citation artifacts.

### Confidence labels

Throughout the pipeline, claims are attributed to their source and labeled by confidence:

- `[Confirmed]` — Validated against official sources by Deep Research
- `[Reported]` — Claimed by a creator, not independently verified
- `[Estimated]` — Approximation based on available data
- `[Speculated]` — Prediction or hypothesis
- `[Analysis]` — Distill's own synthesis

The DOCX export renders these as color-coded badges for quick scanning.

### Refresh-first design

State tracking is built in. `--refresh` is the expected workflow — run on a cadence, process only what's new, let per-channel/topic synthesis update from the delta. Avoids re-processing items that haven't changed.

### Security hardening

- All `urllib.request.urlopen` calls route through `distill.net.safe_urlopen`, which rejects non-`https` schemes.
- arXiv XML parsing uses `defusedxml` instead of `xml.etree.ElementTree` to prevent XML-based attacks.
- SHA-1 used for content dedup is annotated `usedforsecurity=False` to make the non-cryptographic intent explicit.
- Subprocess calls to `yt-dlp` / `scribe` pass arguments as lists (not shell strings), avoiding injection.

## Context engineering principles

Distill treats the prompt context window as a scarce, actively managed resource — not a place to dump everything. This is the same posture the 2025–2026 context-engineering literature converged on (Mei et al.'s 1,400-paper survey; Anthropic's compaction guidance; the ACE framework on evolving playbooks; LangChain's write/select/compress/isolate taxonomy). The lens is useful because it names *why* certain decisions in distillr are the way they are, and where the system is heading.

**Library is external memory, the prompt is working memory.** Every artifact lives on disk as plain markdown — `library/topics/<topic>/...` is the durable store; the prompt window is what we hydrate at inference time from that store. The same logic underpins the refresh-first design (only re-process what's new) and the watch lists (state lives in `library/watch_state.json`, not in chat history). This maps to the "Write" pillar: persist outside the model so the active window stays lean.

**Just-in-time hydration over preloading.** `distill discover` pulls papers + videos *against a goal* and reranks before ingesting; `distill papers` expands and reranks before per-paper analysis; channel watches load only delta videos since the last run. The system never asks "load everything for this topic and let the model figure it out" — it asks "what's the smallest sufficient set for this query?" This is the "Select" pillar.

**Workload-tuned model routing trades fidelity against context budget.** Bulk videos go to Grok 4.1 Fast Reasoning (cheap, fast, good enough on transcripts); messy mid-length artifacts (papers, sites, multi-topic syntheses) go to Grok 4.20 Reasoning where the larger working memory and higher fidelity matter; report Phase 1 goes to Gemini Deep Research for web-grounded retrieval. Each model gets the workload its effective context window handles best, not the largest claimed window.

**Confidence labels and source tagging keep provenance in-band.** `[Confirmed]` / `[Reported]` / `[Estimated]` / `[Speculated]` / `[Analysis]` aren't decorative — they're how downstream prompts (synthesis, report, briefing) avoid laundering uncertainty across handoffs. This is the "Provenance" criterion from Vishnyakova's production-grade context-engineering rubric.

**Where distillr is still naïve about context.** Three known gaps that the roadmap ([`../ROADMAP.md`](../ROADMAP.md)) explicitly addresses:

1. *Paper analysis* dumps a 100K-char PDF into a single Grok prompt — vulnerable to lost-in-the-middle on long methods/results sections. Fix: chunk-and-rerank by section.
2. *MCP tool returns* hand the consuming agent full markdown files — Anthropic's published example shows ~98% token savings from switching to filtered/path-based returns instead. Fix: paths-not-payloads with a drill-down second tool call.
3. *4-phase report pipeline* carries full prior-section context forward to enforce no-repeat. Fix: high-recall-then-precision compaction; opaque continuation items where the API supports them.

These aren't theoretical concerns — they're concrete token-budget and quality wins, with the research literature giving us the patterns to apply.

## Package layout

```
distill/                           # Python package
├── cli.py                         # CLI entry point (Typer, 35+ commands + dashboard)
├── cli_shared.py                  # Shared processing logic
├── mcp_server.py                  # MCP server
├── dashboard_data.py              # Shared dashboard data functions
├── banner.py                      # ASCII banner
├── config.py                      # Settings (Pydantic) — API keys, model pins
├── library.py                     # Topics, channels, site corpora, watch list
├── discovery.py                   # Channel listing, yt-dlp fallback search
├── browser_search.py              # Playwright YouTube search retrieval
├── ranking.py                     # Topic-video + paper reranking (RankedVideo, RankedPaper)
├── briefing.py                    # Lightweight single-topic brief
├── research_brief.py              # Multi-topic Deep Research briefing
├── synthesize.py                  # Multi-topic Grok single-call synthesis
├── site_scraper.py                # Browser-first website capture
├── site_analysis.py               # Per-page insights + site synthesis
├── site_attachments.py            # PDF/embedded-video attachment ingestion
├── paper_ingest.py                # arXiv search (per-word policy) + multi-query fan-out + full-PDF extraction
├── paper_analysis.py              # Per-paper insights + paper synthesis
├── transcripts.py                 # YouTube captions → scribe fallback
├── analysis.py                    # 2-pass full video + 1-pass Shorts
├── synthesis.py                   # Per-channel / per-topic synthesis
├── research.py                    # Gemini Deep Research (legacy + shared)
├── accordion.py                   # 4-phase report orchestrator
├── file_search.py                 # Gemini File Search store management
├── net.py                         # Shared URL-scheme-validating urlopen
├── costs.py                       # Token/cost tracking
├── summary.py                     # Post-run summary display
├── prompts.py                     # Core prompt templates
├── prompts_accordion.py           # Report prompt templates
├── state.py                       # Processed-video tracking
├── docx_export.py                 # Markdown → DOCX
└── web/                           # Local dashboard (FastAPI + Jinja2 + HTMX)
    ├── server.py
    ├── routes/                    # dashboard, topics, channels, videos, costs, watchlist
    ├── templates/                 # Jinja2 HTML
    └── static/                    # CSS + vendored HTMX

library/                           # Per-user data (git-ignored)
├── library.json                   # Master index
├── cost_log.jsonl                 # Run cost history
└── topics/<topic>/…               # Per-topic artifacts
```
