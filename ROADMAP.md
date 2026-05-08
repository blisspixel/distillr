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

## What shipped in 0.1.0

Initial public release as `distillr` on PyPI (2026-04-20). Core capabilities:

- Full capture → analyze → synthesize → report pipeline for all three source types
- 4-phase Deep Research report generation (Gemini + Grok) with QA rewriting
- Multi-topic research briefings (`distill research-brief`) and single-call deep synthesis (`distill synthesize`) with user-supplied context files
- Recurring topic-watch with budget guardrails and per-run "what changed" outputs
- Channel watch + catch-up with custom per-channel extraction instructions
- MCP server with 8 tools, 12 resources, 4 prompts
- Local web dashboard (`distill serve`)
- DOCX export with cover page, TOC, confidence badges
- Post-run summary panels, cost history, refresh-first state tracking
- Security hardening: URL-scheme validation, `defusedxml`, bandit/pip-audit in CI

See [`docs/CHANGELOG.md`](docs/CHANGELOG.md) for the full 0.1.0 entry plus consolidated pre-release history.

## What shipped in 0.2.0

Released 2026-04-27. Discovery loop hardening: the goal-aware front door is in,
yt-dlp ergonomics are solid, and the preview → approve → ingest workflow now
respects what the user actually asked for.

- **Goal-aware `distill discover`.** Generates paper + video queries from a natural-language goal (or `--goal-file`), fans out to arXiv and YouTube, runs a unified goal-aware LLM rerank across both source types, shows one ranked cross-source table, and ingests the shortlist after confirmation. `distill papers` was brought to parity with `distill latest` in the same pass (query expansion, LLM rerank, `--preview`).
- **`--papers-only` / `--videos-only` for discover.** Mutually exclusive, short-circuits the LLM query-generation call for the disabled side so spend matches intent.
- **`--top-by-date` for `distill latest`.** Strict "last N uploads in the window" semantics — bypasses both LLM rerank and the heuristic mix, sorts purely by upload date. Channel cap still applies.
- **Preview-mode cost logging.** Iterative preview cycles (probe, retune, re-probe) now land in `cost_log.jsonl` as `<command>_preview` rows so they're visible separately from ingest spend in `distill costs`.
- **yt-dlp staleness preflight + `distill doctor --update`.** Zero-network version-age check on entry; caches for 24h; honors `DISTILL_NO_PREFLIGHT=1` for CI. After a successful upgrade attempt, doctor reports "(latest available release)" instead of nagging again. Discovery errors that match extractor-failure patterns print a one-line hint pointing at the fix.
- **Windows cp1252 console crash fix.** Stdio is reconfigured to UTF-8 at startup so the preflight `⚠` glyph (now also softened to an ASCII `!` as belt-and-suspenders) doesn't crash on default Windows consoles.

See [`docs/CHANGELOG.md#020--2026-04-27`](docs/CHANGELOG.md) for the complete entry.

## Path to 1.0

The goal of 1.0 is a stable, MCP-first research tool that an external agent can drive without surprises and that a human can run as a daily-driver knowledge system. Milestones are ordered by dependency, not by calendar — each one unblocks the next. Four themes run through every version:

- **MCP-first.** Every workflow has a clean tool surface for agents, not just a CLI for humans. CLI commands are thin wrappers over the same library calls the MCP server uses.
- **Effective-context-aware.** Cloud models in 2026 have 1M+ context windows — a 100K paper fits whole. Chunking is not a universal concern; it is a local-model concern. The system should be adaptive: send content whole when the provider's window allows it, chunk intelligently when it does not (local models with 8K-32K windows). The 2025-2026 context-engineering literature (lost-in-the-middle, ACE-style playbooks, just-in-time retrieval) informs the design, but the implementation targets where it actually matters.
- **Local-first all the way down.** "Local Markdown corpus" is meaningless if every analysis call goes to a paid cloud API. When ingestion is basically free, you use it more — more sources, more frequent refreshes, richer corpus. Local doesn't mean lower quality; it means the economics don't punish thoroughness. If a workload can't meet the quality bar locally, it stays on cloud. Tested on RTX 4090 (Windows) and M1 Mac; should work on any Ollama/LM Studio compatible hardware.
- **Built to last.** Module-size caps, dependency-direction enforcement, ruff/Pyright/coverage gates, and structured logging are established as conventions in 0.3 and apply to every later milestone — so 1.0 lands at the quality bar without a backfill scramble.

### Milestones at a glance

- **0.3 Internal foundations — SHIPPED** (0.3.0-0.4.0). Split `cli.py`, LLM router abstraction, per-prompt telemetry, structured logging, layered subpackage architecture, SecretStr, import-linter, quality conventions.
- **0.5 MCP-first surface — SHIPPED** (0.5.0). JIT context (`find_insights` / `read_insight`), `--json` everywhere, MCP tools mirror CLI commands, token-efficient tool descriptions, Grok 4.3 migration.
- **0.6 Local-control + adaptive context — SHIPPED** (0.6.0). Ollama / LM Studio providers, adaptive chunking, multi-pass analysis, report compaction, hardware detection, `--model` override, Docker.
- **0.7 Living wiki — SHIPPED** (0.7.0-0.7.1). Obsidian-native wiki-links, artifact provenance in frontmatter, CLI decomposition (finish `_cli_impl.py` to `commands/`), path/slug centralization, legacy bridge removal, report-phase retry hardening.
- **0.8 Concept playbook** (next build) — ACE-style concept/entity notes with delta merges and contradiction surfacing.
- **0.9 Discovery loop and synthesis depth** — preview-as-default, cliff detection, `--rigor`, synthesis register styles.
- **0.10 Operational polish** — scheduled refresh, semantic dedup, stale-detection, budget guardrails.
- **1.0 Stability commitment + quality bar** — versioned CLI / MCP / library / frontmatter contracts, test coverage, Pyright strict, blocking lint/security CI, performance baseline, presentation pass.

Detail for each milestone follows. The "[intentionally not in scope](#intentionally-not-in-scope)" section at the bottom is the deliberate exclusions list.

### 0.3 — Internal foundations (SHIPPED)

Delivered across 0.3.0 through 0.4.0. Everything listed below is done and in production.

The 6.5K-line `cli.py` and the flat package layout were the chief brakes on every other improvement. This milestone paid the structural debt and set the conventions every later milestone is held to.

**Restructure (done).**

- Split `distill/` into the [target package layout](#target-package-layout-10): `commands/`, `ingestors/`, `llm/`, `pipeline/`, `prompts/`, `library/`, `mcp/`, `web/`.
- `cli.py` is now a ~150-line Typer wiring module with no business logic. `_cli_impl.py` holds the migrated business logic.
- `mcp/` split into `mcp/server.py` + `mcp/tools/` + `mcp/resources.py` + `mcp/prompts.py`, with one tool group per file mirroring the CLI command surface.
- `prompts/` split into `prompts/analysis.py`, `prompts/synthesis.py`, `prompts/report.py`, `prompts/discover.py`, `prompts/shared.py`.
- LLM router (`distill/llm/`) dispatches by workload tag (`analysis`, `rerank`, `synthesis`, `report`, `qa`) to configured provider+model. Provider stubs for xAI, Gemini, Anthropic, OpenAI, Ollama, and Agent mode.
- Tests mirror source layout: `tests/unit/{commands,ingestors,llm,pipeline,library,mcp}/` plus `tests/integration/`.

**Conventions (done, CI-enforced).**

- Module size cap (500 lines without justification). Ruff `C901` complexity. One responsibility per module.
- `__all__` on public modules; leading underscore for internals.
- Dependency direction enforced via `import-linter`: `commands -> pipeline -> ingestors / llm`, never reverse. `llm/` has no internal `distill.*` imports.
- Ruff zero-warning. Pyright gating on new subpackages. Coverage ratchet (>=80% on new subpackages).

**Config and observability (done).**

- `SecretStr` for API keys, narrower types, no global mutation.
- Per-prompt token telemetry logged to `cost_log.jsonl` per call. "Biggest prompts" view in `distill costs`.
- Structured logging with `--debug`. Rich-print for human-facing surfaces only.
- Knowledge-base file contract: globally descriptive filenames, standardized YAML frontmatter.
- `docs/CONTRIBUTING.md` captures all conventions.

### 0.5.0 — MCP-first surface (SHIPPED)

The agent-facing surface stops being a side door and becomes the primary product surface. This is the biggest user-facing value delivery remaining before 1.0.

- **JIT context retrieval.** `find_insights(topic, query)` returns ranked `(path, preview, score)` tuples; `read_insight(path, section?)` for drill-down. This is the 96% token savings pattern — agents get paths and previews instead of full file payloads. Existing whole-file tools stay for explicit "give me the file" calls but stop being the default response shape.
- **Structured CLI output.** Every CLI command exposes `--json` and respects `NO_COLOR`. Stable, documented exit codes.
- **MCP tool surface mirrors CLI.** Every long-running command has a matching tool with progress events and a clean done/cancel/error contract. Tool schemas are introspectable.
- **Research-gap discovery as an MCP tool** that an external agent can call without scraping the dashboard.
- **Token-efficient tool descriptions.** The research shows 10+ MCP servers lose 30-50% of context window to tool definitions alone. Distill's tool descriptions must be lean — short, precise, no redundant parameter documentation. This is a design constraint, not an afterthought.
- Native watch-alert notification channels (the `library/watch_alerts.md` stream is in; outbound email/Slack/webhook is not).

Why this version: this is the "MCP-first 2026 app" version. It defines how agents drive distillr from here on, so it should land before the corpus shape changes underneath it.

### 0.6.0 — Local-control + adaptive context

Local inference removes the cost barrier from staying current. When ingestion is basically free, you can afford to refresh topics more often, ingest more sources, and keep the corpus comprehensive — not because you're running 24/7, but because there's no reason *not* to run another pass when new papers drop or a channel posts. The corpus grows richer over time because the economics don't punish thoroughness.

The quality bar is the same as cloud. Local doesn't mean slop. A local insight that's thin or wrong pollutes the corpus and degrades everything downstream — synthesis, expert queries, reports. The system does more passes to compensate for smaller context windows, not fewer. If a local model can't produce output at the quality bar, that workload stays on cloud.

**Local providers.**

- Ollama / LM Studio as first-class providers in the LLM router (the stubs are already in place from 0.3.1). Per-workload model selection via config and `--model` overrides on individual commands.
- Cost log distinguishes paid-API spend from local-inference time; `distill costs` shows both axes so users can see what they're saving.
- Recommended models documented per workload (analysis, rerank, synthesis) with quality benchmarks against the cloud baseline. Only models that meet the bar get recommended.

**Model selection strategy.**

The router doesn't hardcode models — it takes whatever Ollama/LM Studio serves. But we document and test against specific models per hardware tier:

| Hardware | Primary Model | Context | Why |
|----------|--------------|---------|-----|
| RTX 4090 (24GB) | Qwen3.5-27B (Q4_K_M) | 128K | Best reasoning quality in the 24GB class; outperforms GPT-5 medium on agentic benchmarks. Dense architecture = predictable VRAM. |
| RTX 4090 (24GB) | Llama 4 Scout (Q4) | 128K+ | MoE (17B active / 109B total); fits 24GB at Q4. 10M native context. Good for long papers. |
| M1/M2 Mac (16GB) | Qwen3.5-14B or Gemma 4 12B | 32K–64K | Fits in unified memory with room for OS. Chunking pipeline handles the shorter context. |
| M-series Mac (32GB+) | Qwen3.5-27B or Gemma 4 27B | 128K | Full-size models in unified memory. |
| RTX 5090 / multi-GPU (32GB+) | Qwen3-32B or Llama 4 Scout (higher quant) | 128K+ | More VRAM = higher quantization = better quality. |

The design is **hardware-adaptive, not model-locked**:
- `distill doctor` detects available VRAM/RAM and suggests the best model for the hardware
- Users can override with `--model` or env vars per workload
- New models slot in without code changes — just update the recommendation docs
- Quality gate: if a model's output on the eval suite drops below 80% of cloud baseline, it's flagged as "not recommended" for that workload

**Context-aware adaptive processing.**

The router knows each provider's context window. The processing strategy adapts:

- For cloud models (Grok 4.3 at 1M, Gemini 3.1 Pro at 1M): no chunking. A 100K-char paper fits whole. Send it, analyze it in one pass.
- For local models (32K–128K context windows on current hardware): adaptive chunking with section-aware splitting. Per-category rerank ("which chunks matter for Methods vs Limits vs Open Questions?"). Small-window analysis loop assembles insights from focused passes. The output quality must match cloud — the system does more passes to get there, not fewer.
- The decision is automatic based on provider metadata — users do not configure this. If the content fits the window, it goes whole. If it does not, the system chunks intelligently.

**Quality equivalence, not degradation.** The local pipeline produces the same structured insights (same YAML frontmatter, same section headings, same depth) as the cloud pipeline. Property tests validate output equivalence. If a workload can't meet the bar locally, the router flags it and the user can choose to send it to cloud or skip it.

**Report pipeline compaction.** High-recall-then-precision summaries replace full-prior-section context between report phases. This benefits all providers but matters most for local models where the 4-phase pipeline would otherwise exceed the window.

**Operational.**

- Dockerfile + docker-compose with Playwright deps included. `distill doctor` knows it's running in a container and skips host-only checks.
- `distill doctor` reports local model availability, VRAM, and estimated throughput.
- Tested on: RTX 4090 (24GB VRAM, Windows), M1 Mac (16GB unified). Should work on any Ollama/LM Studio compatible hardware but these are the validated targets.
- Future hardware (RTX 5090 32GB, M-series with 64GB+, multi-GPU rigs, network GPU clusters) gets better quality automatically — more VRAM means higher quantization or larger models, which the router selects based on detected resources. No code changes needed; the model recommendation table just grows.

Why this version: when ingestion is free, you use it more. More sources ingested, more frequent refreshes, richer corpus. That's what makes the living wiki (0.7) and concept layer (0.8) practical — they need a comprehensive, current corpus to compound against. Local inference is the enabler, not the feature.

### 0.7.0 — Living wiki

The corpus shifts from "directory of artifacts" to "navigable knowledge base," using ecosystem tools (Obsidian, Logseq, Dendron) for visualization rather than building a graph view in distillr.

**Wiki-link discipline and Obsidian interop.**

- Wiki-style cross-linking in synthesis, brief, report, and research-brief outputs (`[[<paper-slug>_Insights|Title]]` instead of plain citations).
- Backfill / migration tooling for older `insights.md`-style libraries into the 0.3 knowledge-base naming contract.
- Stable link discipline. `distill doctor --links` for backlink integrity.
- `distill open --vault` opens the user's default markdown editor pointed at `library/`.

**Artifact provenance in frontmatter.** Every generated artifact records the exact model version, temperature, and prompt identifier used to produce it. This is the foundation for reproducibility — without it, research outputs cannot be trusted or compared across runs. Fields added to YAML frontmatter: `model`, `model_version`, `temperature`, `prompt_id`. Cost tracking (already present) stays alongside.

**CLI decomposition (finish the 0.3 intent).** `_cli_impl.py` (~1,200+ lines of private `_discover_*`, `_llm_expand_*`, and command helpers) is decomposed into the `commands/` subpackage. Each major command group gets its own module with a dedicated Typer app. `_cli_impl.py` is reduced to shared utilities only (target: <200 lines). This unblocks testability and makes the module-size cap enforceable without exceptions.

**Path/slug centralization.** Slugify and path-sanitization logic (currently in `config.py`) moves to `library/paths.py` where it belongs architecturally. Ingestors import from `library/paths` instead of `config`. This completes the separation of concerns between configuration and corpus management.

**Legacy migration bridge removal.** The `router_config_from_distill` bridge code in `config.py` (env parsing inside functions, import-side effects) is deleted. The Grok 4.3 migration (model retirement May 15, 2026) is the forcing function — once the old model is gone, the bridge serves no purpose.

**Report-phase retry hardening.** The 3-failure circuit breaker in the report pipeline gains exponential backoff with jitter. An `LLMCall` dataclass captures full request/response metadata for debugging transient failures.

Why this version: pure prompt + frontmatter + tooling + code-health work, no new model integrations. Lands before the concept layer because concept notes need stable link discipline, provenance, and clean path resolution to be worth building on. The CLI decomposition and bridge removal are included here because they're prerequisites for the 0.8 concept-extraction pass (which adds new commands and pipeline stages that would further bloat `_cli_impl.py` if it isn't decomposed first). Competitively, wiki-links + provenance + stable slugs are now table-stakes in this space (every post-Karpathy tool has some form) — shipping 0.7 clean is the minimum to stay credible alongside SwarmVault, obsidian-wiki, and Lacuna.

### 0.8.0 — Concept playbook

Where distillr stops being a batch processor and starts maintaining a knowledge base. Built directly on the 0.7 wiki conventions.

- Concept extraction pass: detect named techniques, architectures, people, vendors mentioned across 3+ insights. Emit `library/concepts/<slug>.md` and `library/entities/<slug>.md` as ACE-style itemized playbooks (`source_id`, `helpful_count`, `harmful_count`, `last_seen`, `provenance`) — not freeform summaries.
- Deterministic delta merges on refresh: new sources append entries with provenance, increment `helpful_count` on corroboration, add `[contested]` annotations on contradiction. Prior versions land in `.history/`. No monolithic rewrites.
- Contradiction surfacing: contested entries lifted into `distill health`. `concepts.jsonl` and `entities.jsonl` exports for downstream agents and graph DBs.
- `distill ingest <path>` for local files (PDF, markdown, clipped article) so the playbook layer doesn't only update from network ingestion.

Why this version: the qualitative shift the roadmap has been pointing at. Depends on stable artifact metadata (0.7) and the LLM router (0.3) to keep the merge step cheap.

### 0.9.0 — Discovery loop and synthesis depth

The preview → approve → ingest workflow becomes the default front door, and synthesis gets the register options it should already have.

- Preview-as-primary-flow UX: probe the candidate pool, detect the rerank-score cliff, present "top N excellent / top M including good / everything ≥ threshold" sizing options with per-option spend, then a single typed approval. Default behavior on a fresh topic.
- Rerank determinism: cached previewed shortlists (commit-by-ID) so the real ingest replays the exact set the user approved.
- Real cost estimator that reads candidate metadata before the run (arXiv abstract length + page count; yt-dlp duration; site content-length) and calibrates against historical `cost_log.jsonl`.
- `--rigor strict|balanced|loose` knob across discover/papers/latest. Audit and document the prompt divergence between commands.
- Trusted-site discovery and clearer source identity in preview: enumerate real page candidates from allowlisted docs domains (TOCs, sitemaps, landing pages) and show page-level titles/URL context instead of only collection labels.
- Synthesis register styles, with PhD-level (graduate cross-document analysis, per-claim source attribution) as the new default. `--style exec | pop | landscape | disagreements-only`.

Why this version: most of these need 0.3's telemetry to estimate cost honestly and 0.5's MCP surface to expose the same flow to agents. Shipping earlier means re-doing it later.

### 0.10.0 — Operational polish

The "leave it running" version. Hands-off operation for a daily-driver research system.

- Scheduled refresh via cron / Task Scheduler; goal-file refresh hook for `distill watch`.
- Semantic dedup across videos, pages, and papers (artifact-preserving — source-origin attribution stays in the synthesis layer).
- Stale-detection and auto-reanalysis triggers when prompts or models change materially.
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

- **Test coverage ≥80% overall**, ≥90% on `distill/llm/`, `distill/pipeline/`, `distill/ingestors/`, `distill/commands/`. Coverage is reported on every PR and ratchets — it can go up, not down.
- **Integration tests run by default** with mock LLMs so contributors run the full pipeline on every push without burning real spend.
- **Pyright strict** across the full surface, blocking. No `# type: ignore` without an inline reason comment.
- **Ruff** zero-warning under the project config, blocking. Cyclomatic complexity (`C901`) capped; `# noqa` requires an inline justification.
- **Bandit + pip-audit** blocking in CI. Dev dependencies pinned and audited on a documented cadence.
- **No silent error swallowing.** Every `except` either re-raises or logs-then-raises. Audited and lint-rule-enforced where ruff supports it.
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
