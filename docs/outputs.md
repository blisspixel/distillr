# Output reference

What distill writes to disk. Every artifact is plain Markdown, text, or JSON under a local `library/` directory.

New Markdown artifacts use globally descriptive filenames and YAML frontmatter so they work well in Markdown knowledge-base tools and AI assistants. Older generic filenames such as `insights.md` and `topic_synthesis.md` are still readable for backwards compatibility, but new writes use names like `<paper-slug>_Insights.md` and `<topic>_Corpus_Synthesis.md`.

## Directory layout

```
library/
├── library.json                   # Master index
├── cost_log.jsonl                 # Per-run cost history
└── topics/<topic>/
    ├── <topic>_Topic_Synthesis.md # Cross-source synthesis for the topic
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
    ├── sites/<hostname>/          # Per-site artifacts
    └── papers/<paper-slug>/       # Per-paper artifacts
```

## Per video (full-length, >3 min) — 2-pass analysis

- **`<video-slug>_Transcript.txt`** — Full transcript (YouTube captions → scribe fallback)
- **`metadata.json`** — Video ID, title, upload date, duration, URL
- **`<video-slug>_Insights.md`** — Deep structured insight document:
  - Summary — core argument and why it matters
  - Key Announcements — products, policies, personnel, with status tags
  - Technical Insights — architecture, benchmarks, specific numbers
  - Business Value Signals — ROI, adoption patterns, competitive dynamics
  - Vendor Watch — competitive positioning (only vendors actually discussed)
  - Creator's Take — full analytical argument, frameworks, predictions
  - Customer Conversation Starters — grounded in actual video content

## Per Short (≤3 min) — 1-pass extraction

- **`<video-slug>_Transcript.txt`** — Full transcript
- **`metadata.json`** — Video metadata
- **`<video-slug>_Insights.md`** — Lightweight quick insight:
  - Quick Take — 1–2 sentence signal summary
  - News & Updates — breaking announcements
  - Hot Take — creator's opinion or reaction
  - Key Claims — bullet list with confidence tags (`[Confirmed]`, `[Reported]`, `[Speculated]`)
  - Signal Strength — HIGH / MEDIUM / LOW with justification

## Per video (scan mode) — 1-pass triage

Used by `distill catch-up`. Custom per-channel instructions shape the output.

- **`<video-slug>_Transcript.txt`** — Full transcript
- **`metadata.json`** — Video metadata (`analysis_mode: "scan"`)
- **`<video-slug>_Insights.md`** — Fast scan output with optional custom extraction

## Per channel

- **`channel_context.md`** — Auto-generated profile: who they are, what they cover, perspective/bias
- **`<topic>_<channel>_Synthesis.md`** — Cross-video knowledge base that evolves on each refresh
- **`state.json`** — Tracks what's been processed (enables `--refresh`)

## Per topic

- **`<topic>_Topic_Synthesis.md`** — Cross-source knowledge base
- **`<topic>_Corpus_Synthesis.md`** — Mixed-source view when videos, sites, and papers contribute to the same topic (this is what `distill discover` produces by default once its shortlist finishes ingesting)
- **`<topic>_Brief.md`** — Lightweight "what matters now" brief

## Per website page

- **`metadata.json`** — URL, final URL, canonical URL, page type, title, links, embedded video links, PDF links, crawl depth
- **`<page-slug>_Content.md`** — Normalized visible page content
- **`<page-slug>_Transcript.txt`** — Optional transcript when a page exposes one
- **`attachments.json`** — Structured attachment inventory
- **`attachments/*.txt`** — Optional extracted PDF text or embedded-video transcript
- **`<page-slug>_Insights.md`** — Structured page-level analysis

## Per site / site batch

- **`site.json`** — Manifest of processed pages (includes section-level crawl state)
- **`<topic>_<site>_Site_Update.md`** — Section change summary between runs
- **`<topic>_<site>_Site_Synthesis.md`** — Cross-page synthesis

## Per arXiv paper

- **`metadata.json`**: arXiv ID, title, authors, categories, DOI when arXiv supplies one, abstract URL, PDF URL
- **`<paper-slug>_Paper.md`**: Full paper document (abstract + extracted PDF text, up to 100K chars) with DOI frontmatter when available
- **`<paper-slug>_Insights.md`**: Structured per-paper insight with `source_mode: full_pdf | abstract_only` frontmatter indicating whether full text was available

Papers ingested via `distill papers` or `distill discover` pass through the same artifact shape. The discover command also produces an additional pre-ingest signal: the **goal-ranked shortlist** printed to the terminal (and short-circuited when `--preview` is set). The shortlist itself is not persisted as a file today; use `--preview` and copy the table, or re-run with `--yes` to commit directly to ingestion.

Citation exports are local and read from existing paper artifacts:

- **`output/citations-<topic>.bib`**: BibTeX from `distill export <topic> --what citations --format bibtex`
- **`output/citations-<topic>.ris`**: RIS from `distill export <topic> --what citations --format ris`

## Reports (any scope)

- **`<scope>_Research.md`** — Phase 1 output: structured raw facts from Deep Research with descriptive citations and confidence levels
- **`<topic>_Report.md`** — The capstone. Typically 30–50 pages for a full multi-source topic, though actual length varies. Sections adapt to scope:

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

- **`output/report-{topic}-{channel}.md`** — Markdown copy
- **`output/report-{topic}-{channel}.docx`** — Professional DOCX with cover page, TOC, page numbers, color-coded confidence badges

## Research briefings and deep syntheses

- **`output/briefing-{name}.md`** — Output of `distill research-brief` (Gemini Deep Research, web-augmented, multi-topic)
- **`output/synthesis-{name}.md`** — Output of `distill synthesize` (grok-4.3 single call, corpus-only, multi-topic)

## Package Latest (agent handoff)

- **`output/latest-{channel}.md`** or **`output/latest-{topic}.md`** — One markdown file with the N most recent videos (links, dates, durations, full insights). Designed for feeding into downstream agents or RAG pipelines.

## Topic watch artifacts

- **`library/topics/<topic>/<topic>_Watch_Update.md`** — Per-watch delta summary
- **`library/topics/<topic>/<topic>_Topic_Diff.md`** — Topic-level change report
- **`library/topics/<topic>/<topic>_Topic_Trends.md`** — Momentum over recent diff windows
- **`library/topics/<topic>/change_history.jsonl`** — Timestamped change counts
- **`library/library_Latest_Changes.md`** — Library-level rollup
- **`library/library_Watch_Alerts.md`** — Digest of notable changes

## Verification sidecars and audit reports (0.10)

- **`<stem>_Verify.json`** — written beside every checked `_Insights.md`: schema version, mode, checked/supported counts, and any unsupported numeric claims with token, kind, and context line. Positive evidence is recorded too, so "verified clean" is distinguishable from "never checked".
- **`library/topics/<topic>/<topic>_Audit.md`** — written by `distill audit`: verification-coverage rollup, prompt-staleness rollup (recorded `prompt_id` vs the central registry, with per-artifact re-analysis commands in the action menu), synthesis-freshness rollup (a synthesis older than the sources it synthesizes, and shadowed legacy syntheses lingering beside their modern replacements — the same warning also rides the dashboard health list and the topic's generated CLAUDE.md/AGENTS.md), near-duplicate insight groups (shingle overlap, artifact-preserving), stale/thin warnings, contested concepts, broken wiki-links, and coverage gaps with suggested next actions. Standard frontmatter (`type: "audit"`, `findings: N`); deterministic, no model calls.

## Answers (`distill ask`, 0.12)

- **`library/topics/<topic>/answers/<slug>_Answer.md`** — one question, one grounded answer: every claim cites its source as a `[[wiki-link]]`, full provenance (`prompt_id: "ask.v1"`, model), plus a `_Verify.json` sidecar grounding the answer's numbers against the retrieved excerpts. "The corpus does not cover this" is a valid answer body.
- **`answers/<slug>/<slug>_Insights.md`** — only with `--save` and only when the answer passes the strict verify gate: the promoted answer as a first-class insight (`synthesis_scope: "derived-answer"`, `source: "distill-answer"`) that synthesis, concepts, audit, and future answers build on, verification record attached.

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
