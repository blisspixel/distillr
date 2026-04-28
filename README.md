# Distill

*Installed as [`distillr`](https://pypi.org/project/distillr/) on PyPI; the CLI is `distill`.*

[![CI](https://github.com/blisspixel/distillr/actions/workflows/ci.yml/badge.svg)](https://github.com/blisspixel/distillr/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/distillr.svg)](https://pypi.org/project/distillr/)
[![Python](https://img.shields.io/pypi/pyversions/distillr.svg)](https://pypi.org/project/distillr/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)

> Turn YouTube, websites, and arXiv papers into a durable, AI-ready research corpus — all plain Markdown on your disk, with stable filenames, YAML metadata, and source receipts.

```bash
pip install distillr
distill papers "temporal knowledge graph" --topic tkg --limit 20
```

That one command searches arXiv, downloads 20 PDFs, extracts full text, runs structured analysis on each, and writes a cross-paper synthesis. For a 20-paper run like the example below, expect single-digit minutes and roughly ~$1 in model spend. Terminal output during the run looks like this:

```
Papers: temporal knowledge graph
Topic: tkg | Selected papers: 20

  [1/20] Time is Not a Label: Continuous Phase Rotation for Temporal Knowledge
         Graphs and Agentic Memory
  [2/20] Inductive Reasoning for Temporal Knowledge Graphs with Emerging Entities
  ...

  6m 47s  ~$1.01 (391,278 in / 38,117 out)

  time_is_not_a_label_260411544_Paper.md     90.4 KB
  time_is_not_a_label_260411544_Insights.md   8.1 KB
  ...
  tkg_Paper_Synthesis.md  11.8 KB
  tkg_Corpus_Synthesis.md 10.5 KB
```

## Why not just ask Deep Research?

ChatGPT, Gemini Deep Research, and Perplexity are excellent oracles: ask a question, get an answer. Distill is an engine. It automates the tedious ingestion layer, keeps the raw transcripts and paper text next to the analysis, and turns each run into a permanent local corpus that future tools can reuse.

That matters when you are doing thesis work, competitive analysis, technical due diligence, or building a startup knowledge base. You can verify the receipts, refresh the corpus over time, query it through MCP from Claude Desktop / Cursor / other agents, and open the same Markdown folder in Obsidian, Logseq, VS Code, Notion import, or plain filesystem search.

## What you get

One local `library/` directory of plain Markdown. No database, no cloud lock-in, no proprietary format. Files use globally descriptive names plus YAML frontmatter so knowledge-base tools, Dataview-style plugins, and AI coding assistants can understand them without guessing from generic `insights.md` tabs.

Three source types, same pipeline shape (capture → analyze → synthesize → report):

- **YouTube** — channels, topic searches, videos, Shorts
- **Websites** — vendor sites, research hubs, curated URL sets (browser-first crawl with PDF/embedded-video ingestion)
- **arXiv papers** — phrase-matched search, full-PDF extraction, structured per-paper insights, cross-paper synthesis

Plus an MCP server so AI assistants and agent systems can query the library directly.

## Quick start

```bash
pip install distillr
playwright install chromium     # for YouTube search + website capture
distill doctor                  # verify API keys + system health
```

Set two keys in `.env` (copy from `.env.example`):

```bash
XAI_API_KEY=xai-...             # Grok models
GEMINI_API_KEY=AIza...          # Gemini Deep Research (reports + briefings)
```

Then try any of:

```bash
# Goal-aware cross-source discovery (papers + videos, reranked against a goal)
distill discover "help an AI become a great music composer" --topic music --preview
distill discover --goal-file private/my-goal.md --topic research --yes

# Get smart on a YouTube topic, fast
distill latest "Microsoft Fabric best practices" --limit 10 --report

# Discover and ingest arXiv papers — expands the query, LLM-reranks candidates,
# picks the top N (use --preview to see the shortlist without ingesting)
distill papers "agent memory systems" --topic memory --limit 20
distill papers "agent memory systems" --topic memory --limit 20 --preview

# Distill a vendor/research site
distill site-batch configs/example_seeds.json --topic example --seed-only
```

The full command reference lives in [`docs/usage.md`](docs/usage.md).

## Mental model

```
library/
  └── topics/<topic>/
       ├── channels/<creator>/videos/<video>/
       │     ├── <video-slug>_Transcript.txt
       │     └── <video-slug>_Insights.md
       ├── sites/<hostname>/pages/<page>/
       │     ├── <page-slug>_Content.md
       │     └── <page-slug>_Insights.md
       ├── papers/<paper>/
       │     ├── <paper-slug>_Paper.md
       │     └── <paper-slug>_Insights.md
       ├── <topic>_Topic_Synthesis.md      # cross-source
       └── <topic>_Corpus_Synthesis.md     # mixed-source view
```

You build a topic library over time. Ingest once, refresh on a cadence, generate a report or briefing when you need one. Older `insights.md`-style libraries are still readable, but new Markdown writes use the stable knowledge-base naming scheme.

See [`docs/outputs.md`](docs/outputs.md) for what every artifact contains.

## Sample output

A cross-paper `<topic>_Paper_Synthesis.md` (excerpt):

```markdown
## Strongest Research Signals

- Append-only temporal representations improve long-horizon extrapolation:
  RoMem (arXiv:2604.11544), EST (arXiv:2602.12389v3), and CID-TKG converge on
  persistent or dual-view entity state over destructive overwriting, with
  consistent MRR/Hits@K gains on ICEWS and GDELT.

- Semantic gating scales better than manual relation tagging: RoMem's Semantic
  Speed Gate and EST's energy-barrier gate both learn relational volatility
  from text embeddings rather than schema tags…
```

<details>
<summary>Per-paper <code>&lt;paper-slug&gt;_Insights.md</code> excerpt (click to expand)</summary>

```markdown
---
title: "Time is Not a Label: Continuous Phase Rotation for Temporal Knowledge Graphs"
type: "insights"
topic: "tkg"
source: "arxiv"
source_id: "2604.11544v1"
url: "https://arxiv.org/abs/2604.11544v1"
authors: ["Alice Example", "Bob Example"]
tags: ["distill/tkg", "source/arxiv", "cs.AI"]
confidence: "single-paper"
analyzed_by: grok-4.20-0309-reasoning
source_mode: full_pdf
---

### Core Contribution
1. Continuous functional rotation θ_r(τ) = s · α_r · τ · ω instead of discrete
   timestamp lookup tables. Zero-shot interpolation of unseen dates.
2. Semantic Speed Gate: MLP that reads only text embedding ϕ(r) and outputs α_r.
   Learns relational volatility from data.
3. Geometric shadowing in complex space: obsolete facts rotated out of phase so
   the correct fact outranks contradictions via the scoring function alone.

### Methods and Evidence
- On ICEWS05-15, RoMem-ChronoR reaches 72.6 MRR (vs vanilla ChronoR 68.4).
- Zero-shot domain transfer to FinTMMBench: 0.728 MRR, 0.673 R@5.
- All baselines use identical answer LLM and judge for fairness.

### Limits and Open Questions
- Computational cost at millions-of-facts scale is motivation but no latency,
  memory, or throughput numbers are reported.
- Gate pretrained only on ICEWS05-15 political events; generalization to
  highly ambiguous relations is not quantified.
```

</details>

For **multi-topic** literature reviews, stakeholder briefings, or agent grounding, `distill research-brief` (Gemini Deep Research, web-augmented) and `distill synthesize` (Grok 4.20 single-call, corpus-only) take a user-written context file that shapes the output. See [`docs/usage.md#research-briefings-and-deep-synthesis`](docs/usage.md#research-briefings-and-deep-synthesis).

## Dashboard

```bash
distill                         # terminal home screen
distill serve                   # local web dashboard at http://127.0.0.1:8899
```

The terminal home screen shows tracked topics, channel and topic watches, recent runs, failures, and rolling spend. The web dashboard adds clickable drill-downs to per-topic, per-channel, and per-video views with rendered markdown, plus cost history and watchlist status. Both auto-refresh and read directly from library files — no database.

## MCP server

Claude Desktop / Claude Code config:

```json
{ "mcpServers": { "distill": { "command": "distill-mcp" } } }
```

Distill exposes 8 tools, 12 resources, and 4 prompts. See [`docs/mcp.md`](docs/mcp.md) for the list.

## Cost

Bulk video analysis is essentially free (~$0.006/video). Gemini Deep Research dominates paid reports (~$2–3/report). `distill synthesize` is ~$0.50 for a multi-topic corpus pass. Every run logs actual vs estimated cost to `library/cost_log.jsonl`; `distill costs` shows the history.

Full cost model in [`docs/cost.md`](docs/cost.md).

## Docs

- [`docs/usage.md`](docs/usage.md) — full command reference
- [`docs/architecture.md`](docs/architecture.md) — data flow, 4-phase report pipeline, model routing, security hardening
- [`docs/outputs.md`](docs/outputs.md) — what every artifact contains
- [`docs/cost.md`](docs/cost.md) — cost model, examples, guardrails
- [`docs/mcp.md`](docs/mcp.md) — MCP tools, resources, prompts
- [`docs/briefing-contexts/TEMPLATE.md`](docs/briefing-contexts/TEMPLATE.md) — starting point for `--context-file` prompts
- [`private/README.md`](private/README.md) — where personal/client-specific files go (git-ignored)

## Roadmap and changelog

- [`docs/CHANGELOG.md`](docs/CHANGELOG.md) — what shipped in `0.1.0`
- [`ROADMAP.md`](ROADMAP.md) — what's next

## Contributing

See [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) for dev setup, quality gates, and scope. Security disclosures go through [`docs/SECURITY.md`](docs/SECURITY.md).

## License

MIT — see [`LICENSE`](LICENSE).
