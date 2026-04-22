# Output reference

What distill writes to disk. Every artifact is plain markdown or JSON under a local `library/` directory.

## Directory layout

```
library/
├── library.json                   # Master index
├── cost_log.jsonl                 # Per-run cost history
└── topics/<topic>/
    ├── topic_synthesis.md         # Cross-source synthesis for the topic
    ├── corpus_synthesis.md        # Mixed-source view (when multiple source types exist)
    ├── paper_synthesis.md         # Cross-paper synthesis (when papers exist)
    ├── research.md                # Deep Research Phase 1 output
    ├── report.md                  # Full 4-phase report
    ├── brief.md                   # Lightweight brief
    ├── watch_update.md            # Last topic-watch delta
    ├── topic_diff.md              # Latest change report
    ├── topic_trends.md            # Momentum summary
    ├── change_history.jsonl       # Timestamped change counts
    ├── channels/<channel>/        # Per-channel artifacts
    ├── sites/<hostname>/          # Per-site artifacts
    └── papers/<paper-slug>/       # Per-paper artifacts
```

## Per video (full-length, >3 min) — 2-pass analysis

- **`transcript.txt`** — Full transcript (YouTube captions → scribe fallback)
- **`metadata.json`** — Video ID, title, upload date, duration, URL
- **`insights.md`** — Deep structured insight document:
  - Summary — core argument and why it matters
  - Key Announcements — products, policies, personnel, with status tags
  - Technical Insights — architecture, benchmarks, specific numbers
  - Business Value Signals — ROI, adoption patterns, competitive dynamics
  - Vendor Watch — competitive positioning (only vendors actually discussed)
  - Creator's Take — full analytical argument, frameworks, predictions
  - Customer Conversation Starters — grounded in actual video content

## Per Short (≤3 min) — 1-pass extraction

- **`transcript.txt`** — Full transcript
- **`metadata.json`** — Video metadata
- **`insights.md`** — Lightweight quick insight:
  - Quick Take — 1–2 sentence signal summary
  - News & Updates — breaking announcements
  - Hot Take — creator's opinion or reaction
  - Key Claims — bullet list with confidence tags (`[Confirmed]`, `[Reported]`, `[Speculated]`)
  - Signal Strength — HIGH / MEDIUM / LOW with justification

## Per video (scan mode) — 1-pass triage

Used by `distill catch-up`. Custom per-channel instructions shape the output.

- **`transcript.txt`** — Full transcript
- **`metadata.json`** — Video metadata (`analysis_mode: "scan"`)
- **`insights.md`** — Fast scan output with optional custom extraction

## Per channel

- **`channel_context.md`** — Auto-generated profile: who they are, what they cover, perspective/bias
- **`synthesis.md`** — Cross-video knowledge base that evolves on each refresh
- **`state.json`** — Tracks what's been processed (enables `--refresh`)

## Per topic

- **`topic_synthesis.md`** — Cross-source knowledge base
- **`corpus_synthesis.md`** — Mixed-source view when videos, sites, and papers contribute to the same topic (this is what `distill discover` produces by default once its shortlist finishes ingesting)
- **`brief.md`** — Lightweight "what matters now" brief

## Per website page

- **`metadata.json`** — URL, final URL, canonical URL, page type, title, links, embedded video links, PDF links, crawl depth
- **`content.md`** — Normalized visible page content
- **`transcript.txt`** — Optional transcript when a page exposes one
- **`attachments.json`** — Structured attachment inventory
- **`attachments/*.txt`** — Optional extracted PDF text or embedded-video transcript
- **`insights.md`** — Structured page-level analysis

## Per site / site batch

- **`site.json`** — Manifest of processed pages (includes section-level crawl state)
- **`site_update.md`** — Section change summary between runs
- **`synthesis.md`** — Cross-page synthesis

## Per arXiv paper

- **`metadata.json`** — arXiv ID, title, authors, categories, abstract URL, PDF URL
- **`paper.md`** — Full paper document (abstract + extracted PDF text, up to 100K chars)
- **`insights.md`** — Structured per-paper insight with `source_mode: full_pdf | abstract_only` frontmatter indicating whether full text was available

Papers ingested via `distill papers` or `distill discover` pass through the same artifact shape. The discover command also produces an additional pre-ingest signal: the **goal-ranked shortlist** printed to the terminal (and short-circuited when `--preview` is set). The shortlist itself is not persisted as a file today — if you want to capture it, use `--preview` and copy the table, or re-run with `--yes` to commit directly to ingestion.

## Reports (any scope)

- **`research.md`** — Phase 1 output: structured raw facts from Deep Research with descriptive citations and confidence levels
- **`report.md`** — The capstone. Typically 30–50 pages for a full multi-source topic, though actual length varies. Sections adapt to scope:

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
- **`output/synthesis-{name}.md`** — Output of `distill synthesize` (Grok 4.20 single call, corpus-only, multi-topic)

## Package Latest (agent handoff)

- **`output/latest-{channel}.md`** or **`output/latest-{topic}.md`** — One markdown file with the N most recent videos (links, dates, durations, full insights). Designed for feeding into downstream agents or RAG pipelines.

## Topic watch artifacts

- **`library/topics/<topic>/watch_update.md`** — Per-watch delta summary
- **`library/topics/<topic>/topic_diff.md`** — Topic-level change report
- **`library/topics/<topic>/topic_trends.md`** — Momentum over recent diff windows
- **`library/topics/<topic>/change_history.jsonl`** — Timestamped change counts
- **`library/latest_changes.md`** — Library-level rollup
- **`library/watch_alerts.md`** — Digest of notable changes

## Sample insights.md (arXiv paper)

```markdown
---
paper_title: "Time is Not a Label: Continuous Phase Rotation for Temporal Knowledge Graphs"
paper_id: 2604.11544v1
source: arxiv
url: https://arxiv.org/abs/2604.11544v1
analyzed_by: grok-4.20-0309-reasoning
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

## Sample paper_synthesis.md excerpt

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
