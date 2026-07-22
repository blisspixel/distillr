# Distill

[![CI](https://github.com/blisspixel/distillr/actions/workflows/ci.yml/badge.svg)](https://github.com/blisspixel/distillr/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/distillr.svg)](https://pypi.org/project/distillr/)
[![Python](https://img.shields.io/pypi/pyversions/distillr.svg)](https://pypi.org/project/distillr/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)

> Point distill at a research goal; it finds papers, talks, and pages from operator-trusted sites worth reading, and it captures supplied repos, podcasts, feeds, posts, and local files. It analyzes each into structured insights with source receipts, verifies the claims against those receipts before writing, and synthesizes across them into a durable plain-Markdown corpus on your disk. You browse it in Obsidian, your agents read it as files or query it over MCP, you ask it questions and the cited answers can re-enter the corpus - and it refreshes on a cadence instead of going stale.

*Installed as [`distillr`](https://pypi.org/project/distillr/) on PyPI; the CLI command is `distill` (plus `distill-mcp`).*

```bash
uv tool install distillr
distill --cost-mode no-metered init
distill --cost-mode no-metered papers "temporal knowledge graph" --topic tkg --limit 5 --preview
```

The preview asks Distill to build a current arXiv shortlist without ingesting
papers or writing corpus artifacts. `no-metered` permits only routes Distill can
prove are not API-billed and refuses ambiguous billing. It does not substitute
stale model memory for current sources. When the shortlist looks right, run the
full workflow with an explicit limit and cost policy:

```bash
distill --cost-mode paid-ok papers "temporal knowledge graph" --topic tkg --limit 20
```

That full command searches arXiv, selects and downloads up to 20 PDFs, extracts full text, runs structured analysis on each, and writes a cross-paper synthesis. For a 20-paper run like the example below, expect single-digit minutes and under a dollar in model spend on the `grok-4.3` default. Terminal output during the run looks like this (illustrative run; see the labelled sample-output note below):

```
Papers: temporal knowledge graph
Topic: tkg | Sort: relevance | Expand: on | Rerank: on | Limit: 20

Analyzing 20 paper(s)

  paper 1/20 | phase analyze | completed 0/20 | failed 0 | spent $0.0000 Time is Not a Label: Continuous Phase Rotation for Temporal Knowledge Graphs and Agentic Memory
  paper | phase done | completed 1/20 | failed 0 | spent $0.03 | ~6m left
  paper 2/20 | phase analyze | completed 1/20 | failed 0 | spent $0.03 Inductive Reasoning for Temporal Knowledge Graphs with Emerging Entities
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

- **Deep Research oracles** (ChatGPT, Gemini, Perplexity) are excellent at one-shot answers - and the work evaporates after each session. No corpus, no receipts you can re-check, nothing that compounds. Distill is the engine under that pattern: every run leaves transcripts, extracted paper text, per-source insights, and cross-source synthesis on disk, refreshable on a cadence.
- **Grounded notebooks** (NotebookLM) keep a persistent corpus, but in a silo: you find and feed the sources by hand, and the corpus exports to Google Docs/Sheets only. Distill *finds* the sources against your goal, and the corpus is plain files you own.
- **LLM-wiki maintainers** (the post-Karpathy wave of agent-curated Markdown vaults) assume you already have the content and tidy it. Distill is the acquisition half they leave out - goal-aware discovery across papers, videos, and operator-trusted sites, direct ingestion for X and other supplied sources, transcript-grade capture, and provenance on every claim - producing exactly the kind of vault those tools maintain.
- **Academic literature tools** (Elicit, Semantic Scholar, scite, Consensus) are stronger for pure paper search, citation graphs, and systematic review. Distill treats papers as one source type inside a broader corpus that also holds talks, vendor docs, and posts.

The short version: those are **report and search layers**; distill is the **corpus layer underneath repeated research** - capture, per-source insights, cross-source synthesis, refresh, receipts. And plain Markdown is the substrate, not the moat: anyone can write Markdown. The moat is the acquisition-and-maintenance loop that fills it and keeps it current.

That matters when you are doing thesis work, competitive analysis, technical due diligence, or building a startup knowledge base: you can verify the receipts, watch how a topic evolves, query the same folder through MCP from Claude Desktop / Cursor / other agents, and open it in Obsidian, Logseq, VS Code, or plain filesystem search. Reports and briefs export to Word for stakeholder delivery (`distill export <topic> --what report`), and paper topics export to BibTeX or RIS for Zotero and reference managers (`distill export <topic> --what citations`). Nothing is locked in anything.

One honest scoping note: distill is a terminal tool for people comfortable installing a Python CLI and configuring one permitted model route, either a cloud key or a local provider plus an exact model. If you want a one-click app, this isn't that - and the corpus it builds is plain files precisely so the tools you already use can be the interface.

## What you get

One local `library/` directory of plain Markdown. No database, no cloud lock-in, no proprietary format. Files use globally descriptive names plus YAML frontmatter so knowledge-base tools, Dataview-style plugins, and AI coding assistants can understand them without guessing from generic `insights.md` tabs.

Eight source types, same pipeline shape (capture -> analyze -> verify -> synthesize -> report), every one behind the same write-time verify gate:

| Source | Entry point | Notes |
|---|---|---|
| YouTube | `distill latest`, `distill video`, `distill discover` | channels, topic searches, videos, Shorts |
| Websites | `distill site`, `distill site-batch` | browser-first crawl; PDF/embedded-video ingestion |
| arXiv papers | `distill papers` | query expansion, LLM rerank, full-PDF extraction, DOI metadata when arXiv supplies it, cross-paper synthesis, BibTeX/RIS export |
| X (Twitter) posts | `distill ingest <tweet-url>` | public syndication endpoint (no anti-bot scraping); attached video transcribed via local-first Whisper |
| GitHub repos | `distill ingest <repo-url>` | metadata + README + releases into a structured maturity/when-to-use insight |
| Podcasts | `distill ingest <rss-url>` | RSS-first; publisher transcripts preferred over paid audio transcription |
| Newsletters (Substack-class) | `distill ingest <feed-url>` | full post text from the feed itself; routed by substance, narration audio ignored |
| Local files | `distill ingest <path>` | PDF/Markdown/text/HTML documents, plus audio/video through the Whisper ladder; tracked cloud fallback uses `ffprobe` to account for duration |

Plus an MCP server so AI assistants and agent systems can query the library directly, and `distill ask` to query it yourself - answers grounded only in your corpus, every claim cited, with `--save` promoting a verified answer back into the corpus so it compounds.

## Quick start

### Recommended path: `uv tool`

[`uv`](https://docs.astral.sh/uv/) installs the CLI into an isolated, on-PATH environment in one command - no venv to activate, no PATH surgery:

```bash
uv tool install distillr
distill --version
distill --cost-mode no-metered init
distill --cost-mode no-metered papers "temporal knowledge graph" --topic tkg --limit 5 --preview
```

`init` creates `.env`, guides the cloud or local provider choice, installs
Chromium when needed, and ends with a ready or not-ready verdict. The
recommended invocation permits local validation and refuses API-billed or
ambiguous provider checks. If you choose a cloud API, run `distill --cost-mode
paid-ok init` only when you intend its minimal live key-validation request. That
request can be billed and is recorded in the local ledger. Local readiness
requires a successful loopback provider probe and an exact configured model in
the provider inventory. Both setup paths are no-TTY-safe.

The final command is preview-first: it can fetch current public candidates and
use an allowed model route to rank them, but it does not ingest papers or write
corpus artifacts. `no-metered` fails closed if no proven no-metered analysis
route is available. Remove `--preview`, choose an explicit limit, and permit a
metered route only when you are ready to commit the run.

**Updating:** `distill update` upgrades to the latest release in place - it detects how you installed (uv tool / pipx / pip) and runs the right upgrade for you; `distill update --check` just reports whether a newer version exists. Distill also prints a one-line nudge when a new release is published (cached daily, silence with `DISTILL_NO_UPDATE_CHECK=1`).

Want to try it before installing? `uvx --from distillr distill --help` runs the CLI in a throwaway environment. Ingestion needs the one-time Chromium install, so `uv tool install` is the path for real runs.

**Distill runs on Windows, macOS, and Linux** (Python 3.12+). Local models run on consumer GPUs via Ollama or LM Studio.

<details>
<summary>Other supported install paths</summary>

### Repository installers

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/blisspixel/distillr/main/scripts/install.ps1 | iex"
```

macOS / Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/blisspixel/distillr/main/scripts/install.sh | bash
```

These commands download and execute the current installer from this repository.
Review the linked script first when your environment requires pinned or audited
installation input. Open a new terminal after the installer finishes.

### Virtual environment or source checkout

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
distill --cost-mode no-metered doctor
```

### pipx

```bash
pipx install distillr
playwright install chromium
distill --cost-mode no-metered doctor
```

### Bare pip

```bash
pip install distillr
playwright install chromium
distill --cost-mode no-metered doctor
```

**Windows note (common gotcha):** If you use a system Python (e.g. under `C:\Program Files\Python...`) without admin rights, bare `pip` installs to your user directory. The CLI (`distill.exe`) may land in a Scripts folder that is not on `PATH`. Use the venv or pipx method above, or add `%APPDATA%\Python\Python312\Scripts` (adjust version) to your user PATH and restart the terminal.

</details>

The corpus lands in `~/.distill/library/` by default (`<repo>/library/` when running from a source checkout); override with `DISTILL_OUTPUT_DIR`. Cloud routes read keys from `.env` in your working directory (copy from `.env.example`); set only the providers you intend to use:

```bash
XAI_API_KEY=xai-...             # Grok models (default analysis)
GEMINI_API_KEY=AIza...          # Gemini analysis route + Deep Research reports
```

Pick or change the analysis route with the CLI (writes `.env` only on `set`):

```bash
distill provider                              # show active provider + model
distill provider list gemini                  # known models + prices
distill provider set gemini gemini-3.6-flash  # persist default route
distill --provider gemini --model gemini-3.5-flash-lite papers "..." --limit 5
```

Or run locally with Ollama (no API keys needed for ingestion):

```bash
ollama pull qwen3.5:27b         # download recommended model for 24GB GPU
distill provider set ollama qwen3.5:27b
distill --cost-mode no-metered doctor  # verify local setup without cloud probes
```

Local mode still uses fresh sources. `DISTILL_PROVIDER=ollama` or
`DISTILL_PROVIDER=lmstudio` changes the model that analyzes the fetched
receipts; it does not answer from the model's pretraining alone. `distill
discover`, `distill latest`, `distill papers`, and `distill ingest` still fetch
current public sources such as arXiv, YouTube, feeds, sites, repos, and local
files, then ask the configured model to analyze that captured evidence.

**Shell completions** (optional): `distill --install-completion` wires tab-completion for your shell (bash/zsh/fish/PowerShell), including live topic-name completion; `distill --show-completion` prints the script to inspect or source manually.

**No outbound analytics.** Distill phones home for no product analytics or usage beacons. Your research, your keys, and your run history stay on your disk. Operational logs and prompt telemetry stay locally under `library/.distill/` so you can audit runs. The only outbound calls are the LLM or transcription APIs you configure, update checks you do not disable, and the public sources you ask it to fetch.

Then try any of:

```bash
# Goal-aware cross-source discovery (papers + videos + curated sites, reranked against a goal)
distill discover "help an AI become a great music composer" --topic music --preview
distill --cost-mode no-metered topic preview "agent memory systems" --topic memory --videos 10 --papers 10
distill discover --goal-file private/my-goal.md --topic research --yes
distill discover --goal-file private/agent365-goal.md --topic agent365 --site-seeds private/agent365_sites.json --site-limit 10 --preview
distill discover --goal-file private/agent365-goal.md --topic agent365 --trusted-site https://learn.microsoft.com/en-us/microsoft-365/agents-sdk/ --site-limit 10 --preview

# Get smart on a YouTube topic, fast
distill latest "Microsoft Fabric best practices" --limit 10 --report

# Preview an arXiv shortlist, refusing API-billed analysis routes
distill --cost-mode no-metered papers "agent memory systems" --topic memory --limit 5 --preview
# Then explicitly permit cloud model work and ingest a sized set when ready
distill --cost-mode paid-ok papers "agent memory systems" --topic memory --limit 20
distill export memory --what citations --format bibtex

# Distill a vendor/research site
distill site-batch configs/example_seeds.json --topic example --seed-only

# Ask the corpus a question -- grounded-only, every claim cited; --save promotes
# a verified answer back into the corpus
distill ask "which checker should the verify tier use?" --topic memory

# Trust report: verification coverage, prompt staleness, synthesis freshness,
# exact duplicate videos, thin long-video transcripts, near-duplicate insights, contested concepts,
# link integrity, coverage gaps --
# free, no model calls
distill audit memory --report-only
distill audit memory --next-actions --json   # bounded loop handoff plan
```

Long ingest and report runs print per-item or per-phase progress with
completed count, failed count, running spend, and ETA when enough items have
completed. For external loops that only need files, exit codes, or JSON, use
`distill --quiet <command>` to suppress human console output. DEBUG records are
kept in `library/.distill/distill.log` for post-run review; the file rolls at
8 MiB and retains three numbered backups. `distill --verbose <command>`
mirrors the same records to stderr while a command runs.
Deterministic preflight and recovery failures distinguish invalid input (2),
missing configuration (3), and missing local resources (5), so unattended
callers can remediate permanent refusals without retrying them as runtime
failures. Local command telemetry preserves those classes as structured
outcomes. The full reserved taxonomy is in
[`docs/usage.md`](docs/usage.md#exit-codes).
Site ingest progress also reports unchanged-page reuse and empty crawls as
structural outcomes, so repeated website runs show why work was skipped.
Discovery previews also summarize video candidate counts and known watch time
before approval, so broad goals reveal the size of the video corpus before
anything is ingested. Website-heavy discovery can expand operator-trusted
domains or section URLs with `--trusted-site`, using same-host sitemaps,
TOC/navigation links, and landing-page links before the normal goal-aware
rerank. Selected website candidates ingest exact pages by default; operators
can opt into bounded shallow crawls with `--site-crawl-depth` and
`--site-crawl-pages`. If a trusted site is a section URL, shallow crawls keep
followed links under that source path branch. Site preview rows show the exact
URL, section label, discovery source, and sitemap freshness date when
available, so official-doc page candidates stay legible before approval.
Website seed files can also mix `exact-page` and `shallow-crawl` modes, and
`distill site-batch --preview` shows the resolved pages, depth, and crawl
boundary before any crawl or write. With global `--json`, the same preview
emits loop-readable plan rows instead of console text.

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
doi: "10.5555/example-tkg"
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
distill --json                  # bounded dashboard.v2 operator snapshot
distill --json dashboard        # the same explicit dashboard contract
distill dashboard --web         # write a standalone local HTML dashboard
distill serve                   # local web dashboard at http://127.0.0.1:8899
```

The terminal home screen shows tracked topics, channel and topic watches, recent runs, failures, rolling spend, and the exact configured paths to local run evidence. Bare and explicit dashboard JSON return the same bounded `dashboard.v2` envelope with metrics, warnings, recent runs, and evidence paths. Its `spend.recent_usd` field is null when retained cost evidence cannot support a complete total. The web dashboard adds keyboard-accessible drill-downs to per-topic, per-channel, and per-video views with rendered markdown, plus cost history and watchlist status. Its scripts are same-origin static assets under a restrictive CSP. Every dashboard reads directly from library files - no database.

## MCP server, and agent-discoverable directories

Distillr is built for three parallel agent-integration paths:

**Path 1 - MCP (structured queries).** Claude Desktop / Claude Code config:

```json
{ "mcpServers": { "distill": { "command": "distill-mcp" } } }
```

Distill exposes a compact tool set, deliberately kept small and shrinking toward
workflow-shaped tools. The JIT read layer returns ranked
`path`/`preview`/`score` tuples with `read_insight` drill-down, never full
payloads by default; `ask` answers questions grounded only in the corpus, with
citations; and `find_insights_summary` returns a token-bounded brief for
sub-agents, cached so repeat calls are free. For agent-facing deployments, set
**`DISTILL_MCP_READ_ONLY=1`**: agents keep the full read surface while every
spend/ingest/mutation tool refuses with a clear message, so they cannot burn
budget or poison the corpus by tool call. Ingest happens via the CLI by a named
operator. Deployments that do expose write tools get two narrower guardrails:
`DISTILL_MCP_MAX_SPEND_PER_CALL` (per-call spend ceiling, enforced on actual
recorded spend) and `DISTILL_MCP_INGEST_ALLOWLIST` (URL ingest confined to
operator-approved domains). The MCP `site_batch` tool accepts bounded JSON
seed files only from `library/site-seeds/`, validates every entry as public
HTTPS, and cannot use an ordinary library file as a preview source. Its
`preview=true` mode returns the plan even in read-only deployments. See
[`docs/mcp.md`](docs/mcp.md) for the list.

**Path 2 - file system (the corpus IS the interface).** When a coding agent `cd`s into `library/topics/<your-topic>/`, the directory is plain Markdown with stable filenames and YAML frontmatter, so `grep`, `cat`, `ls`, and `find` are first-class query primitives - no schema to learn, no MCP setup required. Every topic directory (and the library root) ships auto-generated **`CLAUDE.md` and `AGENTS.md`** orientation files with identical content - `CLAUDE.md` for Claude Code, `AGENTS.md` for Codex, Cursor, Gemini CLI, and the 30+ tools on the cross-vendor AGENTS.md standard - so any agent that enters the directory gets oriented. This matches what Anthropic's Agent SDK material recommends for agent design: file system + composable tools as the substrate, with structured APIs layered on top when they help, not as the only entry point.

**Path 3 - active host session (bounded deferred work).** When an `agent`
provider call creates a pending task, an already active host session can
complete it through `distill worker`. The host claims one task into an isolated scratch workspace,
reads `prompt.md` and `task.json`, writes only `result.md`, and submits an
ownership-bound receipt. Distill validates the staged inputs, write set, result
size and hash, rechecks ownership at publication, then replays the result through its normal verification and
corpus-write path when the original command is rerun. A failed worker can
abandon its claim so a different host can take over; stale claims require an
explicit operator release.

```bash
distill --json worker list
distill --json worker claim --host worker-a
# Set DISTILL_WORKER_CLAIM_TOKEN through the host's secret environment.
distill --json worker submit <task-id>
```

This handoff does not invoke a vendor CLI, inspect its credentials, or prove its
billing path. The ledger labels it `host-managed`, separate from both metered
API calls and proven no-metered routes, and marks external cost unavailable.
Direct plan-quota adapters remain gated roadmap work.

The canonical **Agent Skill** at
[`skills/distill-corpus/`](skills/distill-corpus/) is also packaged as one
validated, self-contained plugin for Codex, Claude Code, Grok Build, and Gemini
CLI. It teaches receipt-backed corpus reading, safe CLI curation, and the full
worker claim, submit, abandon, and fleet-fallback procedure. It adds no model
provider and receives no credentials.

After installing Distill, the built-in lifecycle gives every client a verified
portable fallback without cloning this repository:

```bash
distill skill doctor
distill skill install --client codex --scope project       # preview only
distill skill install --client codex --scope project --yes # apply or update
distill skill export                                       # deterministic .skill + checksum
```

Native plugin or skill managers are preferred when they provide provenance and
updates. Use the direct `distill skill install` path when a native manager is
unavailable or when you deliberately want a project-local copy. Choose one
installation path per client so the same skill name is not discovered twice.
Direct installs are preview-first, integrity-checked, atomically replaced, and
owned by a local manifest. Distill refuses to overwrite divergent unmanaged
content or remove a modified installation. `distill skill doctor` is read-only:
it verifies the wheel bundle, reports client binary presence and direct target
state, and never invokes a host or treats login as billing proof.

| Host | Install |
|---|---|
| Codex CLI or app | `codex plugin marketplace add blisspixel/distillr --sparse .agents/plugins --sparse plugins/distill-corpus`, then `codex plugin add distill-corpus@distillr` |
| Claude Code | `claude plugin marketplace add blisspixel/distillr --sparse .claude-plugin plugins/distill-corpus`, then `claude plugin install distill-corpus@distillr` |
| Gemini CLI | `gemini extensions install https://github.com/blisspixel/distillr` for native updates, or install only the skill with `gemini skills install https://github.com/blisspixel/distillr.git --path skills/distill-corpus --scope user` |
| Grok Build | Use the Claude-compatible `distillr` marketplace, or load a checkout with `grok --plugin-dir ./plugins/distill-corpus` |
| Antigravity | Put the skill at `.agents/skills/distill-corpus`, or use `npx skills add blisspixel/distillr --skill distill-corpus --agent antigravity` |
| claude.ai | Upload `distill-corpus-<version>.zip` from the matching GitHub release |

Each release also includes a `.skill` archive, the universal plugin ZIP, and
SHA-256 checksums. The optional `npx skills` path can install the canonical
folder into many other Agent Skills clients. Native install paths remain
documented so that installer is never a dependency. See the
[`Agent Skill distribution design`](docs/design/agent-skill-distribution.md)
for the compatibility, lifecycle, behavioral eval, update, validation, and
billing contracts.

## Cost

On the `grok-4.3` default ($1.25/$2.50 per 1M tokens), bulk video analysis runs about $0.03/video and a full paper about $0.03; Gemini Deep Research dominates paid reports at about $2-3/report; `distill synthesize` is about $0.20-0.40 for a multi-topic corpus pass. grok-4.3 is the cloud floor: xAI retired the cheaper fast tiers (grok-4-1-fast etc.) on 2026-05-15, and those slugs now redirect to grok-4.3 and bill at grok-4.3 rates ([migration guide](docs/migration-grok-4.3.md)). The cheaper route Distill can prove today is analysis on a **local model** (Ollama/LM Studio). An active host session may consume included plan quota, credits, or API billing, so Distill records that cost as unavailable rather than calling it free. `distill eval --models grok-4.3,<local-model>` measures the cost x quality tradeoff over frozen fixtures and recommends the cheapest model that clears your quality bar before you switch. Model-using runs log actual vs estimated cost to `cost_log.jsonl` and per-call prompt telemetry to `library/.distill/telemetry.jsonl`. Top-level CLI commands and MCP tool calls with a resolved library write content-free timing to `library/.distill/phase_telemetry.jsonl`; the shared `run_id` joins whichever provider, cost, and phase rows a run produces. True no-spend no-ops do not create cost or provider rows. `distill costs` shows estimator accuracy, local/cloud split, the biggest prompts, and exact-ID command/provider/phase performance evidence with explicit legacy coverage. The estimator's goal is **accuracy**, not safe padding: a padded estimate discourages runs you would happily pay for, so calibration error is tracked and shrunk over time.

Performance history reads are bounded to the newest 16 MiB from each telemetry
source. Human and JSON coverage name any tail-limited log, and affected
completeness-sensitive rollups stay unknown rather than understating a run.
Cooperating phase, provider, and cost writers use one cross-process lock per
history. If an interrupted write leaves an unterminated tail, the next writer
starts on a new line so its valid row remains readable. Cost rows are flushed
with `fsync` before a profile receipt is marked written; phase and provider
telemetry remain fail-soft diagnostics. Biggest-prompt and local/cloud views
stream the full provider history with a 1 MiB per-row ceiling, retain only the
requested top rows in memory, and skip malformed rows without taking down the
CLI or web cost surface. JSON cost output includes provider call, malformed
row, and read-error status. Structured-history deletion and compaction remain
deferred until a lossless archive and receipt-continuity contract exists.

Cost-ledger readers enforce the same evidence boundary across the CLI,
dashboard, recurring watches, calibration, and MCP. Each JSONL row is limited
to 1 MiB, confined reads are limited to 16 MiB, and at most 10,000 valid rows
are retained. Monetary fields must be finite and nonnegative, and timestamps
must be valid ISO values. Coverage reports malformed, omitted, invalid-time,
and read-error counts. When coverage is incomplete, Distill keeps valid rows
visible but withholds totals, projections, calibration, budget claims, and
surprise-cost warnings that the retained evidence cannot support. Topic-watch
batches serialize their budget decision and rescan the ledger before each
entry; `--ignore-budget` is the explicit override for incomplete evidence.

**Cost modes.** `DISTILL_COST_MODE=auto|no-metered|paid-ok` (or `distill --cost-mode <mode> <command>` for one run) gates routes by billing: `no-metered` allows Ollama and LM Studio only when their configured HTTP(S) endpoint is strict loopback, and refuses API-billed, remote, malformed, or ambiguous routes before provider construction. xAI, Gemini, and opt-in Anthropic API routes plus Ollama and LM Studio routes are implemented today; OpenAI analysis remains a reserved route, not a live provider. Anthropic `claude-sonnet-5` is metered and explicit opt-in, not a calibrated default. Active-session worker results are implemented but host-managed and therefore not eligible for `no-metered`. The direct plan-quota CLI adapters (Codex CLI, Claude Code, Grok Build, Gemini/Antigravity) are roadmap, and only graduate once an adapter doctor proves included-plan auth, machine-readable output, scratch-only writes, usage ledgering, and `distill eval` quality. Every logged model-using run records provider and route class, including proven local zero-dollar runs and host-managed runs whose external cost is unavailable.

**Workflow caps.** `DISTILL_COST_WORKFLOW_BUDGETS="ask=0.25,report=5,discover=2,eval=1,paper=1,papers=2,video=1,channel=2,catch-up=2,reanalyze=2,resynthesize=1,site=3,site-batch=3,corpus=1,topic-brief=1,synthesize=1,synthesis=1"` caps direct CLI workflow spend. Estimate-bearing paths such as `distill ask`, `distill eval`, `distill paper`, `distill papers`, `distill site`, `distill site-batch`, `distill video`, `distill channel`, `distill catch-up`, `distill reanalyze`, `distill resynthesize`, `distill corpus`, `distill synthesize`, `distill topic brief`, `distill synthesis`, `distill report`, `distill research-brief`, and saved or freshly ranked `distill discover` ingest plans refuse before the estimated work starts when the projection exceeds the cap. `distill ask` estimates from the retrieved corpus excerpt size after no-coverage checks, so empty coverage stays free. `distill paper` estimates one full-PDF analysis plus the known paper and corpus synthesis tail before model preflight. `distill papers` estimates the requested limit as a preflight upper bound for non-preview runs, then re-checks the selected paper count plus known synthesis tail after search, dedup, rerank, and preview selection but before full-PDF analysis. `distill site` and `distill site-batch` estimate from resolved maximum pages plus the known synthesis and optional report tail before model preflight, while preview and scrape-only stay free. `distill corpus` checks one synthesis-call estimate before model preflight only when the topic has corpus source sections; empty topics and paper-only topics keep their existing no-synthesis path. Other tracked workflows stop when recorded spend crosses the cap; the crossing model call is recorded, then the installed CLI exits with budget code `6`. Global `--json` returns a `budget_exceeded` envelope. These caps complement `no-metered` mode and MCP per-call caps; they do not prove a route is free.

**Recurring profiles** track a topic over time. `distill profile run <name>` prints an approval plan; `--yes` executes it through the normal ingest, analyze, verify, and cost paths with resume state under `library/.distill/profiles/`, and `distill audit` surfaces profile staleness and health.

Full cost model, the route-class table, and per-stage costs: [`docs/cost.md`](docs/cost.md). Adapter and routing design: [`docs/design/cli-adapter-runbook.md`](docs/design/cli-adapter-runbook.md) and [`docs/design/recurring-profiles-cost-routing.md`](docs/design/recurring-profiles-cost-routing.md).

## Reliability and trust boundaries

**What's enforced** (every release clears the same CI gate): more than 6,100 tests at 95% **branch** coverage, ruff + import-linter dependency-direction contracts + pyright + bandit + pip-audit, pinned dependencies via a committed `uv.lock`, SHA-pinned Actions including the PyPI publish action, and PEP 740 build provenance on every PyPI release. Default tests mock all LLM and network boundaries; contributors never burn API spend, and live integration tests are marked and opt-in.

Mutable library and channel indexes use bounded strict-JSON reads and one
locked read-modify-write transaction. A writer reloads current disk state
before mutation, so cooperating processes cannot silently replace one
another's updates. Suspected corruption is rechecked under the writer lock,
preserved in a non-colliding backup, and surfaced through an actionable log;
failed quarantine or persistence never advances the in-memory state.

Append-only knowledge and operator receipts use serialized, no-follow batch
writes that isolate an interrupted tail before the next complete row. Claims
and mentions use strict typed, bounded reads; per-source completion advances
only after durable evidence publication. Incomplete cost evidence is shown as
Unavailable rather than zero or a misleading aggregate, and derived cost math
must remain finite before it reaches CLI, JSON, MCP, or web output.

Source URLs have separate request, persistence, and diagnostic views. Fetching
uses the complete operator-supplied URL only at the request boundary. Durable
artifacts, prompts, run evidence, and diagnostics omit credentials, queries,
and fragments, while domain-separated digests preserve full page identity.
YouTube channel and video identities are validated and canonicalized before
state mutation or discovery.

**Trust boundaries, stated plainly:** everything ingested (transcripts, pages, PDFs, tweets, READMEs, feeds) is treated as **untrusted input** - injection-resistance rules are threaded through first- and second-hop prompts, the dashboard sanitizes rendered HTML, and MCP file reads are confined to explicit namespaces, artifact classes, and byte limits (read-only mode available, above). Distill never bypasses login walls, captchas, or anti-bot defenses. Known-fragile edge: YouTube extraction depends on yt-dlp, which churns with YouTube's countermeasures - transient caption failures retry with backoff, captionless videos fall back to the local-first Whisper ladder, and remaining failures degrade with messages, not corrupted corpora.

**What verification means here:** analysis output is LLM-generated and can err; provenance fields on every artifact exist so you can check receipts, and distill checks them itself. A **write-time verify hook** grounds every numeric claim in every insight, on every source type, against its source receipt before the artifact is committed (`--verify warn|strict|off`; strict refuses to write a flagged insight). Answers from `distill ask` only re-enter the corpus if they pass that gate. The **entailment tier** (`pip install distillr[entailment]`) extends the same gate to prose claims: a small local cross-encoder (HHEM-2.1-Open, Apache 2.0, no cloud calls) scores every substantive sentence against the source receipt, and `--verify strict` refuses on prose flags too; without the extra installed, the deterministic tier stands alone. A **prompt-version registry** lets the audit flag artifacts produced by since-improved prompts instead of letting them age silently. **`distill audit <topic>`** rolls verification coverage, prompt staleness, synthesis freshness (a synthesis older than the sources under it is flagged in the report, the dashboard, and the topic's own orientation files, because confident prose is the most dangerous place for staleness to hide), exact duplicate video identities, health warnings, contested concepts, link integrity, and coverage gaps into a per-topic report artifact, free and deterministically. **`distill audit <topic|all> --next-actions --json`** returns the same findings as bounded actions with commands, approval class, write scope, loop metadata, and verifier stop conditions for external agents or schedulers. Full posture: [`docs/SECURITY.md`](docs/SECURITY.md) and the [security section of the roadmap](ROADMAP.md#security-posture).

## Docs

Start at the [documentation index](docs/README.md), which groups everything below by task (get started / how-to / reference / explanation). The high-traffic entries:

- [`docs/usage.md`](docs/usage.md) - full command reference
- [`docs/invariants.md`](docs/invariants.md) - design charter: what distill is, is not, and the rules that don't bend
- [`docs/architecture.md`](docs/architecture.md) - data flow, 4-phase report pipeline, model routing, security hardening
- [`docs/outputs.md`](docs/outputs.md) - what every artifact contains
- [`docs/cost.md`](docs/cost.md) - cost model, examples, guardrails
- [`docs/mcp.md`](docs/mcp.md) - MCP tools, resources, prompts
- [`docs/migration-grok-4.3.md`](docs/migration-grok-4.3.md) - Grok 4.3 migration guide (model retirement May 15, 2026)
- [`docs/briefing-contexts/TEMPLATE.md`](docs/briefing-contexts/TEMPLATE.md) - starting point for `--context-file` prompts
- [`private/README.md`](private/README.md) - where personal/client-specific files go (git-ignored)

## Project status and active refinement

Distillr is an active beta with a broad working surface: eight source types,
goal-aware discovery, write-time verification, cross-source synthesis, `ask`,
`audit`, MCP, a loopback dashboard, recurring profiles, and bounded deferred
workers. Every change still clears the same release gate: at least 95% branch
coverage, Ruff, Pyright, import-linter, Bandit, pip-audit, the supported Python
matrix, cross-platform smoke tests, and build provenance.

The current program is refinement, not a countdown to a contract freeze. No
freeze date is scheduled or implied. Existing workflows remain open to small,
evidence-backed improvements in UX, copy, security, reliability,
observability, accessibility, and documentation. Candidate contract snapshots
detect accidental drift today; they are review evidence, not a declaration
that the current shapes are final.

The priority order is current-surface quality: close validated security paths,
bound slow or oversized work end to end, make failures and recovery diagnostic,
remove onboarding ambiguity, verify accessible CLI and dashboard behavior, and
keep documentation aligned with what the product actually does. New feature
work stays secondary unless it is necessary to repair one of those workflows.

1.0 remains a future stability commitment. It becomes a sensible decision only
after the refinement backlog is materially reduced, representative user and
operator paths are repeatedly clean, compatibility and migration evidence is
published, the performance baseline exists, and the candidate public contracts
have survived real use. Those are readiness conditions, not a calendar plan.
Full definition: [`ROADMAP.md`](ROADMAP.md#100---stability-commitment--quality-bar).

Performance work follows an evidence gate, not a language quota. Distill stays
Python-first while repeated scans and algorithms can still deliver the larger
gain. The first measured scale fix uses an ephemeral exact-Jaccard candidate
index, and the repository benchmark runs each sample in a fresh child process
before any Rust, Go, Mojo, or free-threaded Python spike is considered. The
decision record and admission budgets are in
[`docs/design/performance-and-language-admission.md`](docs/design/performance-and-language-admission.md).

Practically: build on the `library/` plain files and the CLI today. If you
integrate against MCP schemas or frontmatter fields, pin the version and review
release notes because those candidate contracts can still improve.

## Roadmap and changelog

- [`docs/CHANGELOG.md`](docs/CHANGELOG.md) - what shipped
- [`ROADMAP.md`](ROADMAP.md) - what's next

Feature work is interleaved with recurring **bug-hunt + harden passes** - see the [release rhythm](ROADMAP.md#path-to-10) note in the roadmap.

## Contributing

See [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) for dev setup, quality gates, and scope. Security disclosures go through [`docs/SECURITY.md`](docs/SECURITY.md).

## License

Apache 2.0. See [`LICENSE`](LICENSE). Free to use, build on, fork, and share patterns.
