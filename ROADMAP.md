# Roadmap

High-level direction. Shipped work lives in [`docs/CHANGELOG.md`](docs/CHANGELOG.md). The full, area-by-area backlog (un-trimmed, with priority breakdowns) lives in [`docs/roadmap.md`](docs/roadmap.md).

## Current shape

Distill is a source-to-intelligence platform covering three source types:

- **YouTube** — channels, topic searches, videos, Shorts
- **Websites** — vendor sites, research hubs, curated URL sets
- **arXiv papers** — phrase-matched search, full-PDF extraction, cross-paper synthesis

`distill discover` is the goal-aware front door across papers, videos, and curated website seed files. The next refinement for docs-heavy research is app-native trusted-site discovery on allowlisted domains, so workflows like "prefer Microsoft docs + Microsoft channels" do not require hand-curated page seeds.

Everything produces plain markdown in a local `library/` directory. An MCP server exposes the corpus to AI assistants and agent systems.

Distillr is designed to be the **persistent structured memory layer** for AI agent workflows. It's the corpus that [Deepr](https://github.com/blisspixel/deepr) experts query for grounded intelligence, that coding agents consult via MCP for domain context, and that humans browse in Obsidian for navigable knowledge. The ingestion pipeline is the input mechanism; the real product is the always-current, always-queryable corpus.

## Competitive landscape (May 2026)

The space exploded after Karpathy's "LLM Wiki" gist (April 2026). Hundreds of local-first Markdown knowledge-base / AI second-brain / agent-memory projects now exist. Most follow the same core loop: raw sources → LLM extract/synthesize → persistent interlinked Markdown vault → optional MCP or RAG layer. Distillr is not alone, but it occupies a specific axis that most competitors do not.

**Closest tools and where they differ:**

| Tool | Stars | Approach | Key difference from distillr |
|------|-------|----------|------------------------------|
| SwarmVault | ~400 | Full LLM Wiki + hybrid RAG (SQLite FTS + embeddings) + desktop app | Adds DB/RAG (breaks pure-Markdown), broader ingestion, GUI-first |
| obsidian-wiki (Ar9av) | ~1,000 | Skill-based framework — symlinks skills into Claude Code/Cursor/etc. | "Install skills into your agent" model, less automated discovery |
| Lacuna-wiki | ~24 | Pure MCP-first — single tool, DuckDB index, agent-driven maintenance | Minimalist MCP surface, uses DuckDB, no standalone CLI pipeline |
| personal-knowledge-base | ~9 | Clip URLs + Claude Code as librarian, D3.js graph viz | Manual feeding only, no goal-aware discovery or cross-source synthesis |

Plus the ecosystem around Obsidian Web Clipper + Defuddle (now does YT transcripts natively) + Claude Code / local LLMs for wiki compilation, and a dozen MCP servers for Markdown vaults.

**Where distillr stands out:**

1. **Goal-aware multi-source discovery.** Most tools assume you feed them URLs or files. Distillr searches YT + arXiv + web, reranks for relevance/complementarity against a research goal, then ingests. This is rare and genuinely useful.
2. **Structured per-item insights + cross-source synthesis.** Not just entity pages or summaries — explicit `_Insights.md` with claims/limitations, plus dedicated `Topic_Synthesis` and `Corpus_Synthesis` files mixing all sources. Most competitors stop at entity extraction + wikilinks.
3. **Strict no-database, pure-Markdown discipline.** Stable slugs, source receipts, YAML provenance, cost tracking, git-friendly. Many others sneak in SQLite or vector stores.
4. **CLI-first + MCP for power users.** Researchers who want reusable corpora that agents can drive without GUI lock-in.

**Strategic implications for the roadmap:**

- Wiki-links + provenance + stable slugs are now table-stakes (every competitor has some form). 0.7 must ship these clean.
- Discovery + structured synthesis remain the clearest differentiators. Protect and deepen them (0.9).
- The "ease of agent integration" gap (Ar9av's setup.sh, Lacuna's single-tool MCP) is real but is a 1.0 polish concern, not a 0.7 concern.
- The traction gap vs. GUI-heavy tools is about marketing/onboarding, not missing features. 1.0's presentation pass addresses this.
- Pure-Markdown / no-DB is a defensible niche for serious researchers. Don't compromise it.

**Why not "just make it an MCP skill"?** Distillr already *is* an MCP server (8 tools, 12 resources, 4 prompts since 0.5). But a thin MCP wrapper or agent skill would be useless for what distillr actually does — long-running batch ingestion, persistent corpus maintenance, and compounding knowledge across sessions are exactly what interactive agents (Claude Code, Cursor, Windsurf) are terrible at. The architecture is separation of concerns: distillr is the dedicated memory layer; agents query it via MCP when they need grounded knowledge. It's "and," not "or."

## Path to 1.0

The goal of 1.0 is a stable, MCP-first research tool that an external agent can drive without surprises and that a human can run as a daily-driver knowledge system. Milestones are ordered by dependency, not by calendar — each one unblocks the next. Four themes run through every version:

- **MCP-first.** Every workflow has a clean tool surface for agents, not just a CLI for humans. CLI commands are thin wrappers over the same library calls the MCP server uses.
- **Effective-context-aware.** Cloud models in 2026 have 1M+ context windows — a 100K paper fits whole. Chunking is not a universal concern; it is a local-model concern. The system should be adaptive: send content whole when the provider's window allows it, chunk intelligently when it does not (local models with 8K-32K windows). The 2025-2026 context-engineering literature (lost-in-the-middle, ACE-style playbooks, just-in-time retrieval) informs the design, but the implementation targets where it actually matters.
- **Local-first all the way down.** "Local Markdown corpus" is meaningless if every analysis call goes to a paid cloud API. When ingestion is basically free, you use it more — more sources, more frequent refreshes, richer corpus. Local doesn't mean lower quality; it means the economics don't punish thoroughness. If a workload can't meet the quality bar locally, it stays on cloud. Tested on RTX 4090 (Windows) and M1 Mac; should work on any Ollama/LM Studio compatible hardware.
- **Built to last.** Module-size caps, dependency-direction enforcement, ruff/Pyright/coverage gates, and structured logging are established as conventions in 0.3 and apply to every later milestone — so 1.0 lands at the quality bar without a backfill scramble.

### Milestones at a glance

Previously shipped: **0.1 through 0.8.0** (initial release, internal foundations, MCP-first surface, local inference, living wiki, synthesis-quality patch, concept playbook). Per-release detail lives in [`docs/CHANGELOG.md`](docs/CHANGELOG.md).

In flight and ahead:

- **0.8.1 Frontmatter rename + migration** (next build) — rename `confidence:` → `synthesis_scope:` in synthesis emitters with a one-shot migration over existing artifacts. Isolated cleanup that 0.8 deferred to keep the playbook PR scoped.
- **0.9 Discovery loop, synthesis depth, and local-file ingest** — preview-as-default, cliff detection, `--rigor`, synthesis register styles (PhD/exec/pop/landscape), two-pass synthesis with a structured claim intermediate (the same append-only-JSONL pattern 0.8 used for mentions, applied to claims), `distill ingest <path>` for local PDFs / markdown / clipped articles.
- **0.10 Operational polish** — scheduled refresh, semantic dedup, artifact-level stale-detection, budget guardrails.
- **1.0 Stability commitment + quality bar** — versioned CLI / MCP / library / frontmatter contracts, test coverage, Pyright strict, blocking lint/security CI, golden-corpus eval gate (now also covering concept extraction outputs from 0.8), performance baseline, presentation pass.

Detail for each in-flight milestone follows. The "[intentionally not in scope](#intentionally-not-in-scope)" section at the bottom is the deliberate exclusions list.

### 0.8.1 — Frontmatter rename + migration

Isolated cleanup. Rename `confidence:` → `synthesis_scope:` in synthesis emitters (`paper_synthesis`, `topic_synthesis`, `corpus_synthesis`, report sections). The current field name invites downstream consumers to treat a routing label (`single-paper` vs `corpus-consensus`) as a calibrated number; it isn't one. Ships a one-shot migration over existing artifacts that mirrors the `scan_legacy_artifacts` / `apply_migration` pattern from 0.7.

Why this version: separated from 0.8.0 because it has nothing to do with the playbook layer. Migration tooling has a different testing surface and shouldn't slow the playbook release.

### 0.9.0 — Discovery loop, synthesis depth, and local-file ingest

The preview → approve → ingest workflow becomes the default front door, synthesis gets a structured intermediate that scales beyond a single prompt rewrite, and locally-held documents become first-class corpus sources.

**Discovery loop UX.**

- Preview-as-primary-flow UX: probe the candidate pool, detect the rerank-score cliff, present "top N excellent / top M including good / everything ≥ threshold" sizing options with per-option spend, then a single typed approval. Default behavior on a fresh topic.
- Rerank determinism: cached previewed shortlists (commit-by-ID) so the real ingest replays the exact set the user approved.
- Real cost estimator that reads candidate metadata before the run (arXiv abstract length + page count; yt-dlp duration; site content-length) and calibrates against historical `cost_log.jsonl`.
- `--rigor strict|balanced|loose` knob across discover/papers/latest. Audit and document the prompt divergence between commands.
- Trusted-site discovery and clearer source identity in preview: enumerate real page candidates from allowlisted docs domains (TOCs, sitemaps, landing pages) and show page-level titles/URL context instead of only collection labels.

**Synthesis depth.**

- **Two-pass synthesis with a structured intermediate.** Replace single-pass synthesis with: (1) claim-extraction pass over each per-source insight emitting `claim_id, source_id, claim_text, evidence_type, dataset, metric` rows into a per-topic `claims.jsonl`; (2) synthesis pass over the claim set that clusters, finds contradictions, and writes the narrative with explicit per-claim citations. The 0.7.2 prompt rewrite raised the quality contract but is still single-pass; the structured intermediate is what makes that contract reliably enforceable. Architecturally this is the same append-only-JSONL + pure-Python-merge pattern 0.8 used for `mentions.jsonl` — the playbook layer validated that the LLM-produces-rows / Python-merges-rows split works in production. Reusing that pattern means concepts can attach evidence to specific claim IDs (instead of whole insight files) once both layers exist.
- Synthesis register styles: `--style exec | pop | landscape | disagreements-only` selects emphasis, but every style honors the PhD-level contract shipped in 0.7.2 (cross-paper claims, comparison matrix, named disagreements, shared blind spots).

**Local-file ingest.**

- `distill ingest <path>` for local PDFs, markdown, and clipped articles. Routes through the same analysis pipeline as network ingestion: extract text, run the paper/site analysis prompt, emit `_Insights.md` with full provenance. Closes the gap where the playbook layer only updates from network ingestion. Supports `--topic` to attach to an existing topic, falls back to inferring from file metadata.

Why this version: most of these need 0.3's telemetry to estimate cost honestly and 0.5's MCP surface to expose the same flow to agents. Shipping earlier means re-doing it later.

### 0.10.0 — Operational polish

The "leave it running" version. Hands-off operation for a daily-driver research system.

- Scheduled refresh via cron / Task Scheduler; goal-file refresh hook for `distill watch`.
- Semantic dedup across videos, pages, and papers (artifact-preserving — source-origin attribution stays in the synthesis layer).
- Stale-detection and auto-reanalysis triggers when prompts or models change materially. **Artifact-level, not blanket.** Each artifact's frontmatter already records `prompt_id` and `model_version` (since 0.7); stale-detection inverts that index and re-analyzes only the artifacts on the critical path of the changed component. Blanket re-runs on every prompt bump don't scale once the corpus passes a few hundred artifacts.
- Cost anomaly detection and budget guardrails per topic and workflow.
- Live per-item progress plus resume-friendly failure handling for long mixed-source runs, so transcript-rate limits or slow site ingestion are visible without manual filesystem inspection.

Why this version: these features compound the value of everything above. They don't make sense to land before the corpus is structurally stable, which 0.8 secures.

### 1.0.0 — Stability commitment + quality bar

Public-API freeze plus a documented quality posture. The shape of distillr stops changing under users and agents, and the codebase ships at the polish bar a 1.0 release deserves.

**Stability.**

- CLI flags, MCP tool/resource/prompt schemas, library directory layout, and frontmatter fields are versioned. Breaking changes require a major-version bump and a documented migration.
- Documented backwards-compatibility policy for the `library/` directory (a 0.5 corpus opens cleanly in 1.0).
- Performance baseline published — wall-clock and token spend for a reference 20-paper run, a reference 50-video catch-up, a reference site-batch. CI flags regressions beyond a documented budget.

**Quality bar (CI-enforced, not aspirational).**

- **Test coverage ≥80% overall**, ≥90% on `distill/llm/`, `distill/pipeline/`, `distill/ingestors/`, `distill/commands/`, `distill/concepts/`. Coverage is reported on every PR and ratchets — it can go up, not down.
- **Integration tests run by default** with mock LLMs so contributors run the full pipeline on every push without burning real spend.
- **Pyright strict** across the full surface, blocking. No `# type: ignore` without an inline reason comment.
- **Ruff** zero-warning under the project config, blocking. Cyclomatic complexity (`C901`) capped; `# noqa` requires an inline justification.
- **Bandit + pip-audit** blocking in CI. Dev dependencies pinned and audited on a documented cadence.
- **No silent error swallowing.** Every `except` either re-raises or logs-then-raises. Audited and lint-rule-enforced where ruff supports it.
- **Golden corpus eval gate.** A frozen ~20-paper reference corpus ships with hand-checked golden insights (claims, methods, limits sections) plus hand-checked concept-playbook output (which concepts cross threshold, which polarities, which intervals). CI runs the full analysis + concepts pipeline against it with mock LLM responses fixed for reproducibility, and gates on per-section agreement with the golden output. Catches the regression class that the rest of the quality bar misses — prompt drift, model swaps, and silent degradation of section extraction or concept polarity assignment — none of which show up in coverage, type, or lint gates. Without this, the 1.0 stability claim covers structure but not output quality.
- **Pre-commit hooks identical to CI checks** — no contributor surprises between local and remote.

**Polish.**

- Repo presentation pass: README screenshots/gifs (terminal dashboard, sample report, web UI, library in Obsidian), GitHub repo description and topics, contributor onboarding doc that takes a new contributor from clone to first PR in under 30 minutes.
- All public APIs documented (concise docstrings on the public surface; longer where the rationale isn't obvious from naming).
- `docs/CONTRIBUTING.md` covers the full quality posture above so contributors know the bar before they open a PR.

Why this version: 1.0 is a stability *and* quality claim. It's the version external systems can build on without expecting churn, and the version a new contributor can land a clean PR in without a long onboarding tail. Competitively, this is the version that closes the traction gap — the biggest risk is getting out-marketed on ease-of-agent-integration by GUI-heavy tools (SwarmVault, obsidian-wiki). The presentation pass, onboarding docs, and stable contracts are what convert "technically superior" into "actually adopted."

## Target package layout (1.0)

The shape distillr is being refactored toward. 0.3 stands up the top-level subpackages and the conventions; later milestones populate them. `import-linter` and the module-size cap from 0.3 enforce this layout in CI — it is not aspirational.

```text
distill/
├── __init__.py
├── _bootstrap.py            # early-import side effects (UTF-8 stdio, etc.)
├── cli.py                   # Typer app wiring; ≤100 lines, no business logic
├── config.py                # Pydantic Settings, SecretStr API keys, model policy
│
├── commands/                # one Typer command group per file
│   ├── _helpers.py          # cross-command UI helpers (formerly cli_shared.py)
│   ├── discover.py
│   ├── latest.py
│   ├── papers.py
│   ├── site.py
│   ├── synthesize.py
│   ├── research_brief.py
│   ├── report.py
│   ├── watch.py
│   ├── topics.py
│   ├── costs.py
│   ├── doctor.py
│   ├── serve.py
│   ├── dashboard.py
│   └── ingest.py            # 0.8 — local-file ingest
│
├── ingestors/               # capture layer — one source per subpackage
│   ├── youtube/             # search, download, transcript
│   ├── sites/               # scraper, attachments, browser
│   ├── papers/              # arxiv, pdf
│   └── local/               # 0.8 — local-file routing
│
├── llm/                     # provider abstraction + routing
│   ├── router.py            # workload-tag → provider+model dispatch
│   ├── cost.py              # pricing tables
│   ├── telemetry.py         # per-prompt token logging
│   └── providers/
│       ├── grok.py
│       ├── gemini.py
│       ├── ollama.py        # 0.6
│       └── lm_studio.py     # 0.6
│
├── pipeline/                # analysis / synthesis / report orchestration
│   ├── analysis/
│   │   ├── paper.py
│   │   ├── video.py
│   │   ├── site.py
│   │   ├── chunking.py      # 0.6 — adaptive section-aware (local models only)
│   │   └── rerank.py        # 0.6 — per-category chunk rerank (local models only)
│   ├── synthesis/
│   │   ├── topic.py
│   │   ├── corpus.py
│   │   └── register.py      # 0.9 — PhD / exec / pop styles
│   ├── report/              # 4-phase Deep Research pipeline
│   │   ├── phase1_research.py
│   │   ├── phase2_facts.py
│   │   ├── phase3_writing.py
│   │   ├── phase4_qa.py
│   │   └── compaction.py    # 0.6 — between-phase summaries
│   ├── discovery.py         # goal-aware cross-source fanout + rerank
│   └── ranking.py           # generic LLM rerank
│
├── prompts/                 # all prompt templates centralized
│   ├── analysis.py
│   ├── synthesis.py
│   ├── report.py
│   ├── discover.py
│   └── shared.py            # anti-hallucination + provenance rules
│
├── library/                 # filesystem corpus layer
│   ├── paths.py             # canonical artifact path resolution
│   ├── state.py             # library.json, watch_state.json
│   ├── slugs.py             # 0.7 — stable slug discipline
│   ├── frontmatter.py       # 0.7 — YAML read/write
│   └── links.py             # 0.7 — wiki-style cross-links + link-check
│
├── concepts/                # 0.8 — ACE-style concept/entity playbook layer
│   ├── extract.py
│   ├── merge.py
│   ├── notes.py
│   └── contradictions.py
│
├── mcp/                     # MCP server (split from today's mcp_server.py)
│   ├── server.py            # transport, registration, lifecycle
│   ├── tools/               # mirrors commands/ shape
│   │   ├── find.py          # 0.5 — find_insights / read_insight (JIT)
│   │   ├── discover.py
│   │   ├── topics.py
│   │   ├── watch.py
│   │   ├── gaps.py
│   │   └── costs.py
│   ├── resources.py
│   └── prompts.py           # MCP-protocol prompts (distinct from distill/prompts/)
│
├── notify/                  # 0.5 — outbound watch-alert channels
│   ├── email.py
│   ├── slack.py
│   └── webhook.py
│
└── web/                     # local web dashboard (already a subpackage)
    ├── server.py
    └── routes/
```

**Dependency direction** (enforced by `import-linter`):

```text
commands/  →  pipeline/, library/, mcp/, web/
mcp/       →  pipeline/, library/, commands/
pipeline/  →  ingestors/, llm/, library/, prompts/, concepts/
ingestors/ →  llm/, library/, prompts/
concepts/  →  library/, llm/, prompts/
web/       →  library/, pipeline/
notify/    →  library/

library/   →  (foundational; no internal distill.* imports)
llm/       →  (foundational; no internal distill.* imports)
prompts/   →  (foundational; no internal distill.* imports)
config.py  →  (foundational; no internal distill.* imports)
```

The four foundational layers (`library/`, `llm/`, `prompts/`, `config.py`) are the bottom of the import graph. Everything else builds on them; they don't import each other or anything above them. A new contributor can find any feature in two clicks: pick a layer by what it does, pick a file by which source/phase/command.

**Test layout mirrors source.**

```text
tests/
├── conftest.py
├── unit/
│   ├── commands/
│   ├── ingestors/{youtube,sites,papers,local}/
│   ├── llm/{providers/}
│   ├── pipeline/{analysis,synthesis,report}/
│   ├── library/
│   ├── concepts/
│   └── mcp/
├── integration/             # full-pipeline tests with mock LLMs
│   ├── test_paper_pipeline.py
│   ├── test_discover_cross_source.py
│   └── test_report_pipeline.py
└── fixtures/
    ├── papers/
    ├── transcripts/
    └── mock_llm.py
```

Once 0.3 lands, the canonical version of this layout — with rationale per subpackage — moves into [`docs/architecture.md`](docs/architecture.md). This roadmap section is the snapshot that 0.3 builds toward.

## Intentionally not in scope

A roadmap is also an opinion about what *not* to build. These are deliberate exclusions, not gaps. Several are informed by the competitive landscape (see above) — competitors that make different choices validate that these are real trade-offs, not oversights.

- **No graph-view UI inside distill.** Obsidian / Logseq / Dendron already do this well; reimplementing duplicates effort without adding value. The Obsidian-native milestone (0.7) is the answer. (SwarmVault builds its own graph view; we get it free from the ecosystem.)
- **No proprietary editor, mobile app, or cloud-hosted SaaS.** The whole point is plain-text Markdown with no lock-in. A hosted version would create exactly the dependency the project exists to avoid.
- **No general-purpose RAG / vector-store / SQLite index.** distillr is opinionated about the corpus shape and the analysis pipeline. Embeddings are an implementation detail (used selectively for dedup, possibly inside `find_insights`), not a primary surface. Users who want a generic RAG toolkit have LangChain and LlamaIndex. (SwarmVault and Lacuna-wiki add SQLite/DuckDB; we deliberately avoid this — pure-Markdown + git-friendly is the defensible niche for serious researchers.)
- **No multi-user / auth / collaboration layer.** Single-user local tool. Shared corpora are a `git` problem, not a distillr problem.
- **No additional cloud LLM providers by default.** Each provider is calibration debt — prompts that work well on one model regress on another. Users can wire OpenAI / Anthropic / Mistral / etc. through the 0.3 router, but distillr won't ship default model policies for them. Local providers are the exception because they carry the local-first promise.
- **No plugin / extension system before 1.0.** Premature abstraction. The right plugin boundaries become obvious only after the internal architecture from 0.3–0.5 has carried real workloads. Revisit post-1.0.
- **No real-time collaboration or sync service.** Markdown + git is the answer. distillr won't compete with Obsidian Sync, Logseq Sync, or Syncthing.
- **No "install skills into your agent" model.** obsidian-wiki (Ar9av) takes the approach of symlinking skill files into Claude Code / Cursor / etc. Distillr's architecture is separation of concerns: distillr is the dedicated memory layer, agents query it via MCP. A thin skill wrapper would be useless for long-running batch ingestion and persistent corpus maintenance — exactly what interactive agents are terrible at.
- **No anti-bot / paywall / login-walled scraping.** Playwright handles legitimate access; defeating hostile defenses is whack-a-mole that pulls focus from the analysis pipeline and creates legal/ethical surface area.
- **No "cheap mode" that compromises fidelity.** The product premise is "as good as we can possibly make it" regardless of whether inference runs locally or in the cloud. Local models exist to make the corpus *always current* at zero marginal cost, not to produce worse outputs faster. Cost reduction happens through local inference, compaction, and JIT context — never through cheaper prompts that produce worse outputs. A local insight must be good enough that synthesis and expert queries can trust it without qualification.

These exclusions are load-bearing, not permanent. They get revisited if the constraint that drives them changes.

## Full backlog

The area-by-area backlog (stay-current, dashboard, papers, cross-source intelligence, context engineering, discovery loop, etc.) lives in [`docs/roadmap.md`](docs/roadmap.md). Items there will be tagged with the milestone above where they land in a follow-up pass.

Design principles drawn from the context-engineering literature are summarized in [`docs/architecture.md#context-engineering-principles`](docs/architecture.md#context-engineering-principles).
