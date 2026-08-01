# Output reference

What distill writes to disk. Every artifact is plain Markdown, text, or JSON under a local `library/` directory.

New Markdown artifacts use globally descriptive filenames and YAML frontmatter so they work well in Markdown knowledge-base tools and AI assistants. Older generic filenames such as `insights.md` and `topic_synthesis.md` are still readable for backwards compatibility, but new writes use names like `<paper-slug>_Insights.md` and `<topic>_Corpus_Synthesis.md`.

Synthetic sample shapes appear later on this page. A real, unedited example
corpus (6 papers on claim verification) ships in
[`examples/`](../examples/README.md).

## Directory layout

```
library/
├── library.json                   # Master index
├── .distill/                      # Local operational records
│   ├── cost_log.jsonl             # Model-using run cost history
│   ├── telemetry.jsonl            # Per-provider-call token and timing rows
│   └── phase_telemetry.jsonl      # Content-free correlated phase timing
└── topics/<topic>/
    ├── <topic>_Topic_Synthesis.md # Cross-channel video synthesis
    ├── <topic>_Site_Synthesis.md  # Cross-site website synthesis
    ├── <topic>_Corpus_Synthesis.md# Mixed-source view (when multiple source types exist)
    ├── <topic>_Paper_Synthesis.md # Cross-paper synthesis (when papers exist)
    ├── <topic>_Research.md        # Deep Research Phase 1 output
    ├── <topic>_Report.md          # Full 4-phase report
    ├── <topic>_Brief.md           # Lightweight brief
    ├── <topic>_Watch_Update.md    # Last topic-watch delta
    ├── <topic>_Topic_Diff.md      # Latest change report
    ├── <topic>_Topic_Trends.md    # Momentum summary
    ├── change_history.jsonl       # Timestamped change counts
    ├── channels/<channel>/        # Per-channel artifacts
    │   └── state.json             # Processed-video and refresh state
    ├── sites/<hostname>/          # Per-site artifacts
    ├── papers/<paper-slug>/       # Per-paper artifacts
    ├── x/<handle>/posts/<post>/   # Per-X-post artifacts
    ├── repos/<repo-slug>/         # Per-GitHub-repo artifacts
    ├── podcasts/<show>/           # Podcast episode artifacts
    ├── newsletters/<publication>/ # Feed-post artifacts
    └── local/<document>/          # Local document and media artifacts
```

`library.json` contains topics, channels, and recurring watch state. Distill
updates it and each channel `state.json` through a bounded strict-JSON,
cross-process read-modify-write transaction. Hidden sibling lock files
coordinate writers. If existing state is corrupt, Distill preserves it as
`.bak`, `.bak.1`, and so on before rebuilding; it refuses the rebuild when the
backup cannot be created.

## Per video (full-length, >3 min) - 2-pass analysis

- **`<video-slug>_Transcript.txt`** - Full transcript from YouTube captions,
  the local-first Whisper ladder, or a configured legacy Scribe fallback
- **`metadata.json`** - Video ID, title, upload date, duration, URL
- **`<video-slug>_Insights.md`** - Deep structured insight document shaped by
  the topic's analysis lens. The neutral `general` lens covers the summary,
  key points, details and evidence, the creator's argument, and notable
  specifics. `research`, `practitioner`, and `academic` select their own
  calibrated section sets. Business Value Signals, Vendor Watch, and Customer
  Conversation Starters appear only under the `competitive` lens.

## Per Short (≤3 min) - 1-pass extraction

- **`<video-slug>_Transcript.txt`** - Full transcript
- **`metadata.json`** - Video metadata
- **`<video-slug>_Insights.md`** - Lightweight quick insight:
  - Quick Take - 1-2 sentence signal summary
  - News & Updates - breaking announcements
  - Hot Take - creator's opinion or reaction
  - Key Claims - bullet list with confidence tags (`[Confirmed]`, `[Reported]`, `[Speculated]`)
  - Signal Strength - HIGH / MEDIUM / LOW with justification

## Per video (scan mode) - 1-pass triage

Used by `distill catch-up`. Custom per-channel instructions shape the output.

- **`<video-slug>_Transcript.txt`** - Full transcript
- **`metadata.json`** - Video metadata (`analysis_mode: "scan"`)
- **`<video-slug>_Insights.md`** - Fast scan output with optional custom extraction

## Per channel

- **`channel_context.md`** - Auto-generated profile: who they are, what they cover, perspective/bias
- **`<topic>_<channel>_Synthesis.md`** - Cross-video knowledge base that evolves on each refresh
- **`state.json`** - Tracks what's been processed (enables `--refresh`)

## Per topic

- **`<topic>_Topic_Synthesis.md`** - Cross-channel video synthesis
- **`<topic>_Site_Synthesis.md`** - Cross-site website synthesis
- **`<topic>_Corpus_Synthesis.md`** - Mixed-source view built from channel, site, and paper synthesis inputs (this is what `distill discover` produces by default once its shortlist finishes ingesting)
- **`<topic>_Brief.md`** - Lightweight "what matters now" brief

## Per website page

- **`metadata.json`** - URL, final URL, canonical URL, page type, title, links, embedded video links, PDF links, crawl depth
- **`<page-slug>_Content.md`** - Normalized visible page content
- **`<page-slug>_Transcript.txt`** - Optional transcript when a page exposes one
- **`attachments.json`** - Structured attachment inventory
- **`attachments/*.txt`** - Optional extracted PDF text or embedded-video transcript
- **`<page-slug>_Insights.md`** - Structured page-level analysis

Website output URLs retain public scheme, authority, and path but omit
credentials, queries, and fragments. The hidden page-owner receipt stores that
safe URL plus a domain-separated digest of the complete canonical request URL,
so distinct page identities do not require persisting bearer parameters.

## Per site / site batch

- **`site.json`** - Manifest of processed pages (includes section-level crawl state)
- **`<topic>_<site>_Site_Update.md`** - Section change summary between runs
- **`<topic>_<site>_Site_Synthesis.md`** - Cross-page synthesis
- **`<topic>_Site_Synthesis.md`** - Cross-site rollup stored at the topic root;
  it has a verification receipt distinct from the video topic synthesis

## Per arXiv paper

- **`metadata.json`**: arXiv ID, title, authors, categories, DOI when arXiv supplies one, abstract URL, PDF URL
- **`<paper-slug>_Paper.md`**: Full paper document (abstract + extracted PDF text, up to 200 pages) with DOI frontmatter when available
- **`<paper-slug>_Insights.md`**: Structured per-paper insight with `source_mode: full_pdf | abstract_only` frontmatter indicating whether full text was available

Papers ingested via `distill papers` or `distill discover` pass through the same artifact shape. The discover command also produces an additional pre-ingest signal: the **goal-ranked shortlist** printed to the terminal. `--preview` saves the exact shortlist under `library/.preview_cache/<id>.json`; replay it with `distill discover --from-preview <id> --topic <topic>` to ingest precisely what was reviewed without repeating query generation or reranking.

## Per X post

- **`<handle>_<post-id>_Tweet.md`** - Public post text, long-form body when available, source URL, and attachment metadata
- **`<handle>_<post-id>_Transcript.txt`** - Optional transcript for attached video
- **`<handle>_<post-id>_Insights.md`** - Structured analysis with the same verification sidecar contract as other source types

X posts are direct-ingest sources, not `distill discover` search candidates.
The one-pass corpus aggregator does not consume X insights. Use
`distill resynthesize <topic> --two-pass` when X must contribute to the
cross-source synthesis.

Citation exports are local and read from existing paper artifacts:

- **`output/citations-<topic>.bib`**: BibTeX from `distill export <topic> --what citations --format bibtex`
- **`output/citations-<topic>.ris`**: RIS from `distill export <topic> --what citations --format ris`

## Reports (any scope)

- **`<scope>_Research.md`** - Phase 1 output: structured raw facts from Deep Research with descriptive citations and confidence levels
- **`<topic>_Report.md`** - The capstone. Typically 30-50 pages for a full multi-source topic, though actual length varies. Sections adapt to scope:

### Single-channel reports (10 sections)

1. Executive Briefing
2. Validated Technology Landscape
3. Vendor Competitive Battleground
4. Enterprise Adoption Reality Check
5. Corrections, Nuances & Hype Check
6. Creator Signal vs. Noise
7. Coverage Gaps & Blind Spots
8. Predictions & 90-Day Outlook
9. Customer Conversation Playbook
10. Strategic Synthesis

### Multi-channel reports (10 sections)

Section 6 becomes "Creator Consensus & Contrarian Views" (cross-creator agreement/disagreement). Others match the single-channel list.

### Exports

- **`output/report-{topic}-{channel}.md`** - Markdown copy
- **`output/report-{topic}-{channel}.docx`** - Professional DOCX with cover page, TOC, page numbers, color-coded confidence badges

## Research briefings and deep syntheses

- **`output/briefing-{name}.md`** - Output of `distill research-brief` (Gemini Deep Research, web-augmented, multi-topic)
- **`output/synthesis-{name}.md`** - Output of `distill synthesize` (grok-4.3 single call, corpus-only, multi-topic)

## Package Latest (agent handoff)

- **`output/latest-{channel}.md`** or **`output/latest-{topic}.md`** - One markdown file with the N most recent videos (links, dates, durations, full insights). Designed for feeding into downstream agents or RAG pipelines.

## Topic watch artifacts

- **`library/topics/<topic>/<topic>_Watch_Update.md`** - Per-watch delta summary
- **`library/topics/<topic>/<topic>_Topic_Diff.md`** - Topic-level change report
- **`library/topics/<topic>/<topic>_Topic_Trends.md`** - Momentum over recent diff windows
- **`library/topics/<topic>/change_history.jsonl`** - Timestamped change counts
- **`library/library_Latest_Changes.md`** - Library-level rollup
- **`library/library_Watch_Alerts.md`** - Digest of notable changes

## Operator and derived-state receipts

- **`library/run_log.jsonl`** - Append-only run summaries with a stable `run_id`, command, results, issues, outputs, timing, and metadata.
- **`library/latest_run.json`** and **`library/latest_run_errors.md`** - Correlated projections of the same latest run. One serialized update writes both projections; on projection failure Distill restores the prior pair and keeps the completed run-log row as diagnostic evidence.
- **`library/.distill/eval/results.jsonl`** - Durable batches of model-evaluation results used for drift review.
- **`library/topics/<topic>/change_history.jsonl`** - Durable topic-change observations used by diff and trend views.
- **`library/topics/<topic>/.distill/quality-history.jsonl`** - Strict bounded audit snapshots. Invalid history remains untouched and makes trend comparison unavailable; the current point-in-time audit still renders without inventing a baseline or delta.
- **`library/topics/<topic>/.claims/claims.jsonl`** and **`.claims/extracted_sources.json`** - Strict bounded claim evidence plus the durable source-completion ledger. Claim rows are durable before completion advances.
- **`library/topics/<topic>/.concepts/mentions.jsonl`** and **`.concepts/extracted_sources.json`** - Strict bounded grounded mentions plus the durable source-completion ledger. A repair marker rebuilds derived playbook notes and exports after an interrupted partial update.

Claims, mentions, quality snapshots, eval results, topic changes, and run rows
serialize cooperating writers. Canonical knowledge histories validate the
complete file and enforce row, row-size, and file-size ceilings before append,
so a successful write cannot make its own reader reject the history.
New claim and mention source IDs share a 16 KiB UTF-8 ceiling with completion
ledgers and podcast GUID parsing. Bounded legacy rows from 0.19.38 remain
readable and are preserved when a completion ledger later merges current IDs.

## Verification sidecars and audit reports (0.10)

- **`<stem>_Verify.json`** - written beside every checked `_Insights.md` or synthesis: schema version, mode, checked/supported counts, and any unsupported numeric claims with token, kind, and context line. Positive evidence is recorded too, so "verified clean" is distinguishable from unverified. Synthesis and promoted-answer sidecars bind the exact current artifact filename and complete rendered-content digest. Artifact and sidecar publication share one transaction lock; an artifact failure restores the prior binding. Missing, legacy-unbound, malformed, or mismatched bindings count as unverified. A readable sidecar with zero numeric and entailment claims checked records no coverage and is not a passing result.
- **`library/topics/<topic>/<topic>_Audit.md`** - written by `distill audit`: verification-coverage rollup, prompt-staleness rollup (recorded `prompt_id` vs the central registry, with per-artifact re-analysis guidance represented as inert JSON argv records rather than shell text), synthesis-freshness rollup (a synthesis older than the sources it synthesizes, and shadowed legacy syntheses lingering beside their modern replacements - the same warning also rides the dashboard health list and the topic's generated CLAUDE.md/AGENTS.md), near-duplicate insight groups (shingle overlap, artifact-preserving), stale/thin warnings, contested concepts, broken wiki-links, and coverage gaps with suggested next actions. Standard frontmatter (`type: "audit"`, `findings: N`); deterministic, no model calls.

## Answers (`distill ask`, 0.12)

- **`library/topics/<topic>/answers/<slug>_Answer.md`** - one question, one grounded answer: every claim cites its source as a `[[wiki-link]]`, full provenance (`prompt_id: "ask.v1"`, model), plus a `_Verify.json` sidecar grounding the answer's numbers against the retrieved excerpts. "The corpus does not cover this" is a valid answer body.
- **`answers/<slug>/<slug>_Insights.md`** - only with `--save` and only when the answer passes the strict verify gate: the promoted answer as a first-class insight (`synthesis_scope: "derived-answer"`, `source: "distill-answer"`) that synthesis, concepts, audit, and future answers build on, verification record attached.

## Standard YAML frontmatter

Every generated Markdown artifact starts with a YAML block intended for Markdown knowledge-base tools, Dataview-style database plugins, importers, and AI assistants:

```yaml
---
title: "The real difference between Gemini 3 and ChatGPT 5.1"
type: "insights"
topic: "ai-agents"
source: "youtube"
source_id: "abc123"
url: "https://www.youtube.com/watch?v=abc123"
date: "2026-03-09"
tags: ["distill/ai_agents", "source/youtube"]
synthesis_scope: "single-source"
channel: "NateBJones"
---
```

## Sample `<paper-slug>_Insights.md` (arXiv paper)

```markdown
---
title: "Time is Not a Label: Continuous Phase Rotation for Temporal Knowledge Graphs"
type: "insights"
topic: "tkg"
source: arxiv
source_id: 2604.11544v1
url: https://arxiv.org/abs/2604.11544v1
doi: 10.5555/example-tkg
tags: ["distill/tkg", "source/arxiv"]
synthesis_scope: "single-paper"
analyzed_by: grok-4.3
source_mode: full_pdf
---

### Summary
The paper introduces RoMem, a drop-in temporal knowledge graph module that treats
time as a continuous geometric phase rotation in complex vector space rather than
discrete timestamp metadata…

### Core Contribution
1. **Continuous functional rotation** θ_r(τ) = s · α_r · τ · ω instead of discrete
   timestamp lookup tables…
2. **Semantic Speed Gate**: an MLP that reads only the text embedding ϕ(r) and
   outputs α_r…
3. **Geometric shadowing** in complex space: obsolete facts are rotated out of
   phase so the correct fact outranks contradictions…

### Methods and Evidence
- Entities and relations embedded in ℝ²ᵈ (treated as ℂᵈ). Rotation operator
  Rot(x, θ) = x ⊙ e^(iθ)…
- On ICEWS05-15 the RoMem-ChronoR variant reaches 72.6 MRR (vs vanilla ChronoR 68.4)…

### Limits and Open Questions
- Computational cost at millions-of-facts scale is mentioned as motivation but no
  latency, memory, or throughput numbers are reported…

### Confidence
Analysis derived from the full PDF. Quantitative claims traced to specific tables
and figures in the source.
```

## Sample `<topic>_Paper_Synthesis.md` excerpt

```markdown
## Strongest Research Signals

- **Append-only temporal representations improve long-horizon extrapolation**:
  multiple papers (RoMem arXiv:2604.11544, EST arXiv:2602.12389, CID-TKG) converge
  on persistent or dual-view entity state over destructive overwriting, with
  consistent MRR/Hits@K gains on ICEWS and GDELT.

- **Semantic gating scales better than manual relation tagging**: RoMem's
  Semantic Speed Gate and EST's energy-barrier gate both learn relational
  volatility from text embeddings rather than schema tags, enabling zero-shot
  transfer to unseen domains (RoMem FinTMMBench 0.728 MRR, EST cross-dataset
  consistency).

## Shared Themes Across Papers

All three papers reject destructive UPDATE/DELETE on knowledge-graph entities…
```
