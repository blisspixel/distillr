# Distill

*Installed as [`distillr`](https://pypi.org/project/distillr/) on PyPI; the CLI command is `distill` (plus `distill-mcp`).*

[![CI](https://github.com/blisspixel/distillr/actions/workflows/ci.yml/badge.svg)](https://github.com/blisspixel/distillr/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/distillr.svg)](https://pypi.org/project/distillr/)
[![Python](https://img.shields.io/pypi/pyversions/distillr.svg)](https://pypi.org/project/distillr/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)

> Point distill at a research goal; it finds the papers, talks, repos, podcasts, and posts worth reading, analyzes each into structured insights with source receipts, verifies the claims against those receipts before writing, and synthesizes across them into a durable plain-Markdown corpus on your disk. You browse it in Obsidian, your agents read it as files or query it over MCP, you ask it questions and the cited answers can re-enter the corpus — and it refreshes on a cadence instead of going stale.

```bash
pip install distillr
distill papers "temporal knowledge graph" --topic tkg --limit 20
```

That one command searches arXiv, downloads 20 PDFs, extracts full text, runs structured analysis on each, and writes a cross-paper synthesis. For a 20-paper run like the example below, expect single-digit minutes and under a dollar in model spend on the `grok-4.3` default. Terminal output during the run looks like this (illustrative run; see the labelled sample-output note below):

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

## Where distill sits

Three kinds of tools orbit this space, and distill is deliberately none of them:

- **Deep Research oracles** (ChatGPT, Gemini, Perplexity) are excellent at one-shot answers — and the work evaporates after each session. No corpus, no receipts you can re-check, nothing that compounds. Distill is the engine under that pattern: every run leaves transcripts, extracted paper text, per-source insights, and cross-source synthesis on disk, refreshable on a cadence.
- **Grounded notebooks** (NotebookLM) keep a persistent corpus, but in a silo: you find and feed the sources by hand, and the corpus exports to Google Docs/Sheets only. Distill *finds* the sources against your goal, and the corpus is plain files you own.
- **LLM-wiki maintainers** (the post-Karpathy wave of agent-curated Markdown vaults) assume you already have the content and tidy it. Distill is the acquisition half they leave out — goal-aware discovery across papers, videos, sites, and X, transcript-grade capture, and provenance on every claim — producing exactly the kind of vault those tools maintain.
- **Academic literature tools** (Elicit, Semantic Scholar, scite, Consensus) are stronger for pure paper search, citation graphs, and systematic review. Distill treats papers as one source type inside a broader corpus that also holds talks, vendor docs, and posts.

The short version: those are **report and search layers**; distill is the **corpus layer underneath repeated research** — capture, per-source insights, cross-source synthesis, refresh, receipts. And plain Markdown is the substrate, not the moat: anyone can write Markdown. The moat is the acquisition-and-maintenance loop that fills it and keeps it current.

That matters when you are doing thesis work, competitive analysis, technical due diligence, or building a startup knowledge base — you can verify the receipts, watch how a topic evolves, query the same folder through MCP from Claude Desktop / Cursor / other agents, and open it in Obsidian, Logseq, VS Code, or plain filesystem search. Reports and briefs also export to Word for stakeholder delivery (`distill export <topic> --what report`). Nothing is locked in anything.

One honest scoping note: distill is a terminal tool for people comfortable installing a Python CLI and setting two API keys (or running a local model). If you want a one-click app, this isn't that — and the corpus it builds is plain files precisely so the tools you already use can be the interface.

## What you get

One local `library/` directory of plain Markdown. No database, no cloud lock-in, no proprietary format. Files use globally descriptive names plus YAML frontmatter so knowledge-base tools, Dataview-style plugins, and AI coding assistants can understand them without guessing from generic `insights.md` tabs.

Eight source types, same pipeline shape (capture -> analyze -> verify -> synthesize -> report), every one behind the same write-time verify gate:

| Source | Entry point | Notes |
|---|---|---|
| YouTube | `distill latest`, `distill video`, `distill discover` | channels, topic searches, videos, Shorts |
| Websites | `distill site`, `distill site-batch` | browser-first crawl; PDF/embedded-video ingestion |
| arXiv papers | `distill papers` | query expansion, LLM rerank, full-PDF extraction, cross-paper synthesis |
| X (Twitter) posts | `distill ingest <tweet-url>` | public syndication endpoint (no anti-bot scraping); attached video transcribed via local-first Whisper |
| GitHub repos | `distill ingest <repo-url>` | metadata + README + releases into a structured maturity/when-to-use insight |
| Podcasts | `distill ingest <rss-url>` | RSS-first; publisher transcripts preferred over paid audio transcription |
| Newsletters (Substack-class) | `distill ingest <feed-url>` | full post text from the feed itself; routed by substance, narration audio ignored |
| Local files | `distill ingest <path>` | PDF/Markdown/text/HTML documents, plus audio/video through the Whisper ladder |

Plus an MCP server so AI assistants and agent systems can query the library directly, and `distill ask` to query it yourself — answers grounded only in your corpus, every claim cited, with `--save` promoting a verified answer back into the corpus so it compounds.

## Quick start

**One-line install**

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/blisspixel/distillr/main/scripts/install.ps1 | iex"
```

**macOS / Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/blisspixel/distillr/main/scripts/install.sh | bash
```

After the installer finishes, open a **new** terminal and run `distill init`. It is a guided, one-command setup: it creates your `.env`, helps you pick the cloud or local provider, validates your key against the provider, installs the Playwright browser if it is missing, and ends with a ready/not-ready verdict and the first command to try. (`distill doctor` remains the read-only diagnostic; `distill init` is the one that *sets things up*.) Both are no-TTY-safe, so a scripted or agent-driven setup never hangs.

**Updating:** `distill update` upgrades to the latest release in place — it detects how you installed (uv tool / pipx / pip) and runs the right upgrade for you; `distill update --check` just reports whether a newer version exists. distill also prints a one-line nudge when a new release is published (cached daily, silence with `DISTILL_NO_UPDATE_CHECK=1`).

---

**Distill runs on Windows, macOS, and Linux** (Python 3.12+). Local models run on consumer GPUs via Ollama or LM Studio.

### Recommended: `uv tool` (the 2026 default for Python CLIs)

[`uv`](https://docs.astral.sh/uv/) installs the CLI into an isolated, on-PATH environment in one command — no venv to activate, no PATH surgery:

```bash
uv tool install distillr     # installs the `distill` + `distill-mcp` commands
distill --version            # confirm it's on PATH
playwright install chromium  # browser support for YouTube + web capture
distill doctor               # verify keys + environment
```

Want to try it before installing? `uvx --from distillr distill --help` runs the CLI in a throwaway environment (note: ingestion needs the one-time `playwright install chromium`, so `uv tool install` is the path for real runs).

### Alternative (virtual environment or pipx)

This is the cleanest way without uv and avoids common PATH problems.

```bash
# 1. Create a virtual environment
python -m venv .venv          # some systems: python3 -m venv .venv

# 2. Activate the environment
#   Windows (PowerShell):   .\.venv\Scripts\Activate.ps1
#   macOS / Linux:          source .venv/bin/activate

# 3. Install
pip install -e .              # from a source checkout, or: pip install distillr

# 4. Browser support (for YouTube + web capture)
playwright install chromium

# 5. Verify
distill doctor
```

**Even simpler alternative: pipx** (great for CLI tools):

```bash
pipx install distillr
playwright install chromium
distill doctor
```

### Fast path (bare pip)

```bash
pip install distillr
playwright install chromium
distill doctor
```

**Windows note (common gotcha):** If you use a system Python (e.g. under `C:\Program Files\Python...`) without admin rights, bare `pip` installs to your user directory. The CLI (`distill.exe`) may land in a Scripts folder that is not on `PATH`. Use the venv or pipx method above, or add `%APPDATA%\Python\Python312\Scripts` (adjust version) to your user PATH and restart the terminal.

The corpus lands in `~/.distill/library/` by default (`<repo>/library/` when running from a source checkout); override with `DISTILL_OUTPUT_DIR`. Set two keys in `.env` in your working directory (copy from `.env.example`):

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

Local mode still uses fresh sources. `DISTILL_PROVIDER=ollama` or
`DISTILL_PROVIDER=lmstudio` changes the model that analyzes the fetched
receipts; it does not answer from the model's pretraining alone. `distill
discover`, `distill latest`, `distill papers`, and `distill ingest` still fetch
current public sources such as arXiv, YouTube, feeds, sites, repos, and local
files, then ask the configured model to analyze that captured evidence.

**Shell completions** (optional): `distill --install-completion` wires tab-completion for your shell (bash/zsh/fish/PowerShell), including live topic-name completion; `distill --show-completion` prints the script to inspect or source manually.

**No telemetry.** Distill phones home for nothing — no analytics, no usage beacons. Your research, your keys, and your run history stay on your disk. The only outbound calls are the LLM/transcription APIs you configure and the public sources you ask it to fetch.

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

# Ask the corpus a question -- grounded-only, every claim cited; --save promotes
# a verified answer back into the corpus
distill ask "which checker should the verify tier use?" --topic memory

# Trust report: verification coverage, prompt staleness, synthesis freshness,
# near-duplicate insights, contested concepts, link integrity, coverage gaps --
# free, no model calls
distill audit memory --report-only
distill audit memory --next-actions --json   # bounded loop handoff plan
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
       ├── repos/<repo>/                    # GitHub:  _Repo.md + _Insights.md
       ├── podcasts/<show>/<episode>/       # podcasts: _Episode.md + _Transcript.txt + _Insights.md
       ├── newsletters/<pub>/<post>/        # newsletters: _Content.md + _Insights.md
       ├── answers/                         # distill ask: _Answer.md (+ promoted insights)
       ├── <topic>_Topic_Synthesis.md      # cross-source
       ├── <topic>_Corpus_Synthesis.md     # mixed-source view
       └── <topic>_Audit.md                # trust report from `distill audit`
```

You build a topic library over time. Ingest once, refresh on a cadence, generate a report or briefing when you need one. Older `insights.md`-style libraries are still readable, but new Markdown writes use the stable knowledge-base naming scheme.

See [`docs/outputs.md`](docs/outputs.md) for what every artifact contains.

## Sample output

*The excerpts below are synthetic examples: the file shapes, frontmatter fields, and section structure are exactly what distill writes, but the papers, authors, and numbers are invented for illustration. For a provenance-first tool that distinction matters, so it is stated. A **real, unedited example corpus** (6 papers on claim verification, $0.19 of analysis) ships in [`examples/`](examples/README.md).*

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
analyzed_by: grok-4.3
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

For **multi-topic** literature reviews, stakeholder briefings, or agent grounding, `distill research-brief` (Gemini Deep Research, web-augmented) and `distill synthesize` (grok-4.3 single-call, corpus-only) take a user-written context file that shapes the output. See [`docs/usage.md#research-briefings-and-deep-synthesis`](docs/usage.md#research-briefings-and-deep-synthesis).

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

Distill exposes 24 tools (a deliberately small surface, shrinking toward workflow-shaped tools — the JIT read layer returns ranked `path`/`preview`/`score` tuples with `read_insight` drill-down, never full payloads by default; `ask` answers questions grounded only in the corpus, with citations; `find_insights_summary` returns a token-bounded brief for sub-agents, cached so repeat calls are free), plus 12 resources and 4 prompts. For agent-facing deployments, set **`DISTILL_MCP_READ_ONLY=1`**: agents keep the full read surface while every spend/ingest/mutation tool refuses with a clear message — they can't burn budget or poison the corpus by tool call; ingest happens via the CLI by a named operator. Deployments that do expose write tools get two narrower guardrails: `DISTILL_MCP_MAX_SPEND_PER_CALL` (per-call spend ceiling, enforced on actual recorded spend) and `DISTILL_MCP_INGEST_ALLOWLIST` (URL ingest confined to operator-approved domains). See [`docs/mcp.md`](docs/mcp.md) for the list.

**Path 2 — file system (the corpus IS the interface).** When a coding agent `cd`s into `library/topics/<your-topic>/`, the directory is plain Markdown with stable filenames and YAML frontmatter, so `grep`, `cat`, `ls`, and `find` are first-class query primitives — no schema to learn, no MCP setup required. Every topic directory (and the library root) ships auto-generated **`CLAUDE.md` and `AGENTS.md`** orientation files with identical content — `CLAUDE.md` for Claude Code, `AGENTS.md` for Codex, Cursor, Gemini CLI, and the 30+ tools on the cross-vendor AGENTS.md standard — so any agent that enters the directory gets oriented. This matches what Anthropic's Agent SDK material recommends for agent design: file system + composable tools as the substrate, with structured APIs layered on top when they help, not as the only entry point.

There's also a canonical **Agent Skill** at [`skills/distill-corpus/SKILL.md`](skills/distill-corpus/SKILL.md) — one vendor-neutral file teaching an agent how to read the corpus and drive the CLI (drop it into `~/.claude/skills/` or `~/.agents/skills/`).

## Cost

On the `grok-4.3` default ($1.25/$2.50 per 1M tokens), bulk video analysis runs ~$0.03/video and a full paper ~$0.03; Gemini Deep Research dominates paid reports (~$2–3/report); `distill synthesize` is ~$0.20–0.40 for a multi-topic corpus pass. grok-4.3 is the cloud floor — xAI retired the cheaper fast tiers (grok-4-1-fast etc.) on 2026-05-15, and those slugs now redirect to grok-4.3 and bill at grok-4.3 rates ([migration guide](docs/migration-grok-4.3.md)). The only cheaper path is running analysis on a **local model** (Ollama/LM Studio) — `distill eval --models grok-4.3,<local-model>` measures the cost × quality tradeoff over frozen fixtures and recommends the cheapest model that clears your quality bar before you switch. Every run logs actual vs estimated cost to `cost_log.jsonl`, and the pre-run estimate self-calibrates against that history; `distill costs` shows it. The estimator's goal is **accuracy**, not safe padding — a padded estimate discourages runs you'd happily pay for, so calibration error is tracked and shrunk over time.

Route status today: xAI/Gemini cloud routes and Ollama/LM Studio local routes are implemented. `DISTILL_COST_MODE=no-metered` is wired as a fail-closed route policy, and `distill --cost-mode no-metered <command>` applies the same policy for one run: local Ollama/LM Studio are allowed, while API-billed or ambiguous routes are refused before provider calls. Profile previews include the cost-mode override in generated replay commands when the profile is no-metered. Anthropic and OpenAI providers ship in-tree as opt-in routes, but they are not calibrated defaults. Plan-quota CLI routes such as Codex CLI, Claude Code, Grok Build, and Gemini/Antigravity are roadmap adapters, not hidden providers. They only graduate when an adapter doctor can prove included-plan auth, machine-readable output, scratch-only writes, complete usage ledgering, and `distill eval` quality for the workload. GitHub Copilot CLI can be supported later as an explicit credit-metered route, but it is not a no-metered default because Copilot usage is tied to AI credits and usage limits. Until adapters exist, these CLIs can run Distill externally as operators, but Distill should not claim their quota as an internal model route.

Recurring profile runs use the same boundary. `distill profile run <name>`
prints an approval plan by default, and `distill profile run <name> --yes`
executes the generated `distill ...` commands through the existing ingest,
analysis, verify, and cost paths while recording resume state under
`library/.distill/profiles/`. Cost-log rows now record provider and route-class
usage for no-metered local calls and profile-run orchestration even when the
dollar cost is zero. Blocked no-metered routes report the provider, workload,
route cost class, proof requirements when applicable, and the paid-ok retry
hint needed for an intentional metered run. Profile run JSON also emits
`next_actions` rows with argv commands, approval class, write scope, verifier,
and loop metadata for external runners. `distill audit all` includes local
profile health from profile files and run state so stale profiles, failed
profile commands, missing goals, invalid state, and thin local corpora are
visible without network access. `distill doctor --adapters` adds read-only CLI
adapter preflights for candidate plan-quota and credit-metered routes, including
binary presence, version/help probes, required flags, API-key environment
blockers, local config API-key markers, route class, support-statement status,
structured support details, and the required `adapter-result.v1` scratch
manifest contract, including the before/after scratch write check future
runners must use. Support details record `checked_on`, source URLs, required
evidence, notes, and `no_metered_current`. The manifest contract now includes
structured quota-stop metadata for future rate-limit and quota exhaustion
handling. The reusable adapter runner
primitive can execute exact argv arrays in scratch with shell disabled and
API-key environment variables stripped. A ledger helper can convert verified
adapter manifests into zero-dollar included-plan usage rows and metadata, but
no plan-quota CLI route is live until auth proof, a current no-metered support
statement, adapter workload execution wiring, and eval gates clear. The doctor
JSON also exposes the `adapter-workload.v1` package contract for future
scratch-relative read-only adapter tasks.

Full cost model in [`docs/cost.md`](docs/cost.md).

## Reliability and trust boundaries

**What's enforced** (every release clears the same CI gate): ~2,300 tests at 81% **branch** coverage (floor ratchets up-only toward the 1.0 ≥95% gate), ruff + import-linter dependency-direction contracts + pyright + bandit + pip-audit, pinned dependencies via a committed `uv.lock`, SHA-pinned Actions, and PEP 740 build provenance on every PyPI release. Default tests mock all LLM and network boundaries — contributors never burn API spend; live integration tests are marked and opt-in.

**Trust boundaries, stated plainly:** everything ingested (transcripts, pages, PDFs, tweets, READMEs, feeds) is treated as **untrusted input** — injection-resistance rules are threaded through first- and second-hop prompts, the dashboard sanitizes rendered HTML, and MCP file access is confined to the library root (read-only mode available, above). Distill never bypasses login walls, captchas, or anti-bot defenses. Known-fragile edge: YouTube extraction depends on yt-dlp, which churns with YouTube's countermeasures — transient caption failures retry with backoff, captionless videos fall back to the local-first Whisper ladder, and remaining failures degrade with messages, not corrupted corpora.

**What verification means here:** analysis output is LLM-generated and can err; provenance fields on every artifact exist so you can check receipts, and distill checks them itself. A **write-time verify hook** grounds every numeric claim in every insight, on every source type, against its source receipt before the artifact is committed (`--verify warn|strict|off`; strict refuses to write a flagged insight). Answers from `distill ask` only re-enter the corpus if they pass that gate. The **entailment tier** (`pip install distillr[entailment]`) extends the same gate to prose claims: a small local cross-encoder (HHEM-2.1-Open, Apache 2.0, no cloud calls) scores every substantive sentence against the source receipt, and `--verify strict` refuses on prose flags too; without the extra installed, the deterministic tier stands alone. A **prompt-version registry** lets the audit flag artifacts produced by since-improved prompts instead of letting them age silently. **`distill audit <topic>`** rolls verification coverage, prompt staleness, synthesis freshness (a synthesis older than the sources under it is flagged in the report, the dashboard, and the topic's own orientation files, because confident prose is the most dangerous place for staleness to hide), health warnings, contested concepts, link integrity, and coverage gaps into a per-topic report artifact, free and deterministically. **`distill audit <topic|all> --next-actions --json`** returns the same findings as bounded actions with commands, approval class, write scope, loop metadata, and verifier stop conditions for external agents or schedulers. Full posture: [`docs/SECURITY.md`](docs/SECURITY.md) and the [security section of the roadmap](ROADMAP.md#security-posture).

## Docs

Start at the [documentation index](docs/README.md), which groups everything below by task (get started / how-to / reference / explanation). The high-traffic entries:

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

Feature work is interleaved with recurring **bug-hunt + harden passes** — see the [release rhythm](ROADMAP.md#path-to-10) note in the roadmap.

## Contributing

See [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) for dev setup, quality gates, and scope. Security disclosures go through [`docs/SECURITY.md`](docs/SECURITY.md).

## License

MIT — see [`LICENSE`](LICENSE).
