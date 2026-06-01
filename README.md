# Distill

*Installed as [`distillr`](https://pypi.org/project/distillr/) on PyPI; the CLI is `distill`.*

[![CI](https://github.com/blisspixel/distillr/actions/workflows/ci.yml/badge.svg)](https://github.com/blisspixel/distillr/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/distillr.svg)](https://pypi.org/project/distillr/)
[![Python](https://img.shields.io/pypi/pyversions/distillr.svg)](https://pypi.org/project/distillr/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)

> Turn YouTube, websites, and arXiv papers into a durable, AI-ready research corpus — all plain Markdown on your disk, with stable filenames, YAML metadata, and source receipts.

```bash
pip install distillr
distill papers "temporal knowledge graph" --topic tkg --limit 20
```

That one command searches arXiv, downloads 20 PDFs, extracts full text, runs structured analysis on each, and writes a cross-paper synthesis. For a 20-paper run like the example below, expect single-digit minutes and under a dollar in model spend on the `grok-4.3` default. Terminal output during the run looks like this:

```
Papers: temporal knowledge graph
Topic: tkg | Selected papers: 20

  [1/20] Time is Not a Label: Continuous Phase Rotation for Temporal Knowledge
         Graphs and Agentic Memory
  [2/20] Inductive Reasoning for Temporal Knowledge Graphs with Emerging Entities
  ...

  6m 47s  ~$0.58 (391,278 in / 38,117 out)

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

Four source types, same pipeline shape (capture -> analyze -> synthesize -> report):

- **YouTube** — channels, topic searches, videos, Shorts
- **Websites** — vendor sites, research hubs, curated URL sets (browser-first crawl with PDF/embedded-video ingestion)
- **arXiv papers** — phrase-matched search, full-PDF extraction, structured per-paper insights, cross-paper synthesis
- **X (Twitter) posts** — via `distill ingest <tweet-url>`; uses the public syndication embed endpoint (no anti-bot scraping). When a tweet has a native video attachment, the audio is transcribed via local-first Whisper (`faster-whisper` on GPU/CPU, OpenAI Whisper as cloud fallback) with a vocabulary hint derived from the source metadata to keep proper nouns intact.

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

Or run locally with Ollama (no API keys needed for ingestion):

```bash
ollama pull qwen3.5:27b         # download recommended model for 24GB GPU
echo "DISTILL_PROVIDER=ollama" >> .env
distill doctor                  # verify local setup
```

Then try any of:

```bash
# Goal-aware cross-source discovery (papers + videos + curated sites, reranked against a goal)
distill discover "help an AI become a great music composer" --topic music --preview
distill discover --goal-file private/my-goal.md --topic research --yes
distill discover --goal-file private/agent365-goal.md --topic agent365 --site-seeds private/agent365_sites.json --site-limit 10 --preview

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
synthesis_scope: "single-paper"
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

## MCP server, and agent-discoverable directories

Distillr is built for two parallel agent-integration paths:

**Path 1 — MCP (structured queries).** Claude Desktop / Claude Code config:

```json
{ "mcpServers": { "distill": { "command": "distill-mcp" } } }
```

Distill exposes 22 tools, 12 resources, and 4 prompts. See [`docs/mcp.md`](docs/mcp.md) for the list.

**Path 2 — file system (the corpus IS the interface).** When a coding agent `cd`s into `library/topics/<your-topic>/`, the directory is plain Markdown with stable filenames and YAML frontmatter, so `grep`, `cat`, `ls`, and `find` are first-class query primitives — no schema to learn, no MCP setup required. From 0.8.4 forward, every topic directory ships an auto-generated `CLAUDE.md` orientation file that agents which auto-load it (Claude Code, Cursor, others) pick up automatically. This matches what Anthropic's Agent SDK material recommends for agent design: file system + composable tools as the substrate, with structured APIs layered on top when they help, not as the only entry point.

## Cost

On the `grok-4.3` default ($1.25/$2.50 per 1M tokens), bulk video analysis runs ~$0.03/video and a full paper ~$0.03; Gemini Deep Research dominates paid reports (~$2–3/report); `distill synthesize` is ~$0.20–0.40 for a multi-topic corpus pass. (The retired `grok-4-1-fast` tier was ~5× cheaper at ~$0.006/video and is still selectable via `.env` if you want bulk-cheap over fidelity.) Every run logs actual vs estimated cost to `cost_log.jsonl`, and the pre-run estimate self-calibrates against that history; `distill costs` shows it.

Full cost model in [`docs/cost.md`](docs/cost.md).

## Docs

- [`docs/usage.md`](docs/usage.md) — full command reference
- [`docs/invariants.md`](docs/invariants.md) — design charter: what distill is, is not, and the rules that don't bend
- [`docs/architecture.md`](docs/architecture.md) — data flow, 4-phase report pipeline, model routing, security hardening
- [`docs/outputs.md`](docs/outputs.md) — what every artifact contains
- [`docs/cost.md`](docs/cost.md) — cost model, examples, guardrails
- [`docs/mcp.md`](docs/mcp.md) — MCP tools, resources, prompts
- [`docs/migration-grok-4.3.md`](docs/migration-grok-4.3.md) — Grok 4.3 migration guide (model retirement May 15, 2026)
- [`docs/briefing-contexts/TEMPLATE.md`](docs/briefing-contexts/TEMPLATE.md) — starting point for `--context-file` prompts
- [`private/README.md`](private/README.md) — where personal/client-specific files go (git-ignored)

## Roadmap and changelog

- [`docs/CHANGELOG.md`](docs/CHANGELOG.md) — what shipped
- [`ROADMAP.md`](ROADMAP.md) — what's next

**Recent: 0.8.7 Security hardening (shipped 2026-05-30).** Indirect-prompt-injection resistance threaded into every per-source analysis prompt (ingested sources are treated as untrusted data, not instructions), and the local dashboard's rendered HTML is now sanitized (`nh3`) to close a stored-XSS vector — see the [Security posture](ROADMAP.md#security-posture) section for the threat model and what's deliberately out of scope. Recent work also includes **0.8.4 Agent-discoverable library** (auto-generated per-topic and library-root `CLAUDE.md`; `distill claude-md --all` backfills — see [`ROADMAP.md`](ROADMAP.md#084--agent-discoverable-library)) and **0.8.5–0.8.6** (Gemini model refresh + cost-tracking completeness).

**Recent: 0.9.1–0.9.4 Discovery-loop close-out (shipped 2026-06-01).** The pre-run spend estimate now scales per-video cost by duration and self-calibrates against `cost_log.jsonl` history, reporting an honest range (0.9.1); `discover --preview` saves the exact ranked shortlist under an id so `discover --from-preview <id>` ingests precisely what you previewed (0.9.2); on a fresh topic `discover` leads with a size-then-approve menu — Excellent / Including good / Everything worthwhile, each with its own spend — instead of silently auto-ingesting (0.9.3); and `--rigor` now works across `discover`/`papers`/`latest` on per-command calibrated thresholds (0.9.4). See [`docs/CHANGELOG.md`](docs/CHANGELOG.md).

**Next: source breadth + audio capability** — the five-adapter set (podcasts, GitHub repos, generic audio/video files, Substack, X hardening — see [`ROADMAP.md`](ROADMAP.md#091--source-breadth-and-audio-capability)). Then the self-maintaining audit (`distill audit` bundles the health/link/gap checks into one report + action menu), and 0.10 (operational polish + run-time verify hook + the `distill ask` output->input loop + sub-agent-friendly MCP tools).

## Contributing

See [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) for dev setup, quality gates, and scope. Security disclosures go through [`docs/SECURITY.md`](docs/SECURITY.md).

## License

MIT — see [`LICENSE`](LICENSE).
