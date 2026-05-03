# Roadmap

High-level direction. Shipped work lives in [`docs/CHANGELOG.md`](docs/CHANGELOG.md). The full, area-by-area backlog (un-trimmed, with priority breakdowns) lives in [`docs/roadmap.md`](docs/roadmap.md).

## Current shape

Distill is a source-to-intelligence platform covering three source types:

- **YouTube** — channels, topic searches, videos, Shorts
- **Websites** — vendor sites, research hubs, curated URL sets
- **arXiv papers** — phrase-matched search, full-PDF extraction, cross-paper synthesis

`distill discover` is the goal-aware front door across papers, videos, and curated website seed files. The next refinement for docs-heavy research is app-native trusted-site discovery on allowlisted domains, so workflows like "prefer Microsoft docs + Microsoft channels" do not require hand-curated page seeds.

Everything produces plain markdown in a local `library/` directory. An MCP server exposes the corpus to AI assistants and agent systems.

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

The goal of 1.0 is a stable, MCP-first research tool that an external agent can drive without surprises and that a human can run as a daily-driver knowledge system. Milestones are ordered by dependency, not by calendar — each one unblocks the next. Three themes run through every version:

- **MCP-first.** Every workflow has a clean tool surface for agents, not just a CLI for humans. CLI commands are thin wrappers over the same library calls the MCP server uses.
- **Effective-context-aware.** The 2025–2026 context-engineering literature (lost-in-the-middle, ACE-style playbooks, just-in-time retrieval) is treated as plumbing, not a marketing surface.
- **Local-first all the way down.** "Local Markdown corpus" is meaningless if every analysis call goes to a paid cloud API. Closing that gap is a 1.0 requirement.
- **Built to last.** Module-size caps, dependency-direction enforcement, ruff/Pyright/coverage gates, and structured logging are established as conventions in 0.3 and apply to every later milestone — so 1.0 lands at the quality bar without a backfill scramble.

### Milestones at a glance

- **0.3 Internal foundations** — split `cli.py`, LLM router abstraction, per-prompt telemetry, structured logging.
- **0.4 Long-input fidelity** — chunked paper analysis, report-pipeline compaction, lost-in-the-middle regression tests.
- **0.5 MCP-first surface** — JIT context (`find_insights` / `read_insight`), `--json` everywhere, MCP tools mirror CLI commands.
- **0.6 Local-control parity** — Ollama / LM Studio in the router, Docker, paid-vs-local cost split.
- **0.7 Living wiki** — Obsidian-native frontmatter and wiki-style cross-links; `distill open --vault`.
- **0.8 Concept playbook** — ACE-style concept/entity notes with delta merges and contradiction surfacing.
- **0.9 Discovery loop and synthesis depth** — preview-as-default, cliff detection, `--rigor`, synthesis register styles.
- **0.10 Operational polish** — scheduled refresh, semantic dedup, stale-detection, budget guardrails.
- **1.0 Stability commitment + quality bar** — versioned CLI / MCP / library / frontmatter contracts, ≥80% test coverage, Pyright strict, blocking lint/security CI, performance baseline, presentation pass.

Detail for each milestone follows. The "[intentionally not in scope](#intentionally-not-in-scope)" section at the bottom is the deliberate exclusions list.

### 0.3.0 — Internal foundations

The 6.5K-line `cli.py` and the flat package layout are the chief brakes on every other improvement. This milestone is mostly invisible to users; it pays the structural debt before it accumulates more, *and* it sets the conventions every later milestone is held to. The point is not just to split `cli.py` once — it's to put up the rules that prevent another one from forming.

**Restructure.**

- Split `distill/` into the [target package layout](#target-package-layout-10) (full tree below). 0.3 stands up the top-level subpackages: `commands/`, `ingestors/`, `llm/`, `pipeline/`, `prompts/`, `library/`, `mcp/`, plus `web/` (already a subpackage). Later milestones add `notify/` (0.5) and `concepts/` (0.8) within the same shape; no later milestone changes the top-level layout.
- The current `cli.py` (6.5K lines) becomes a ~100-line Typer app that wires command groups together with no business logic. `cli_support/` is the seed of `commands/`; `cli_shared.py` becomes `commands/_helpers.py`.
- The current `mcp_server.py` (1.1K lines) splits into `mcp/server.py` + `mcp/tools/` + `mcp/resources.py` + `mcp/prompts.py`, with one tool group per file mirroring the CLI command surface.
- The current `prompts.py` (880 lines) splits into `prompts/analysis.py`, `prompts/synthesis.py`, `prompts/report.py`, `prompts/discover.py`, `prompts/shared.py` (anti-hallucination + provenance rules).
- Extract the LLM-call surface into a `distill/llm/` router that takes a workload tag (`analysis`, `rerank`, `synthesis`, `report`, `qa`) and returns the configured provider+model. Today's hard-coded Grok/Gemini routing becomes the default policy in this layer.
- Tests mirror source layout: `tests/unit/{commands,ingestors,llm,pipeline,library,mcp}/` plus `tests/integration/` for full-pipeline tests with mock LLMs.

**Conventions (so we don't grow another `cli.py`).**

- **Module size cap.** No module over 500 lines without an inline justification comment. CI-checked.
- **Function complexity cap.** Ruff `C901` cyclomatic complexity enforced on new subpackages.
- **One responsibility per module.** One Typer command group per file in `commands/`; one source per file in `ingestors/`; one phase per file in `pipeline/`.
- **Public surface explicit.** `__all__` declared in modules with importable callers; leading underscore for internals.
- **Dependency direction enforced** via `import-linter`: `commands → pipeline → ingestors / llm`, never reverse. `llm/` has no internal `distill.*` imports.
- **Ruff zero-warning** on new subpackages from day one. `# noqa` requires an inline justification.
- **Pyright** moves from warnings to a CI gate on the new subpackages first; the old surface follows as it gets touched.
- **Coverage ratchet.** New subpackages ship with ≥80% test coverage from day one. CI prevents regressions on every PR (pytest-cov fail-under per package). Later milestones extend the floor across the rest of the surface so 1.0 doesn't need a backfill scramble.

**Config and observability.**

- Tighten config: `SecretStr` for API keys, narrower types, no global `console`/`config` mutation.
- Per-prompt token telemetry (input length, output length, elapsed) logged to `cost_log.jsonl` per call, not per run. Surface a "biggest prompts" view in `distill costs`. Required to make every later context-engineering claim measurable.
- Structured logging with proper levels, file output, and a `--debug` flag. Rich-print stays for human-facing surfaces only.
- Pull forward the knowledge-base file contract from 0.7: new Markdown artifacts use globally descriptive filenames (`<slug>_Insights.md`, `<topic>_Corpus_Synthesis.md`) and standardized YAML frontmatter. Older generic paths remain readable as compatibility inputs, but new writes stop creating ambiguous Markdown basenames.

**Conventions documented.**

- `docs/CONTRIBUTING.md` captures all of the above so contributors know the bar before they open a PR. The 1.0 quality bar is a tightening of these conventions, not a different set of rules.

Why this version: every later milestone gets cleaner if the LLM router, command surface, and telemetry are in place — and the conventions set here make sure no later milestone re-creates the `cli.py` problem. Ship it before it becomes a bigger refactor.

### 0.4.0 — Long-input fidelity

The user-visible quality bar moves up here. Today's "stuff the whole PDF into one prompt" pattern is the largest known fidelity gap.

- Section-aware chunker for papers (PDF headings; page+window fallback). Per-category rerank ("which chunks matter for *Methods*, *Limits*, *Open Questions*?"). Small-window analysis loop assembles `<paper-slug>_Insights.md` from focused passes.
- Lift the 100K-char paper cap once chunking is in place.
- Compaction in the 4-phase report pipeline — high-recall-then-precision summaries replace full-prior-section context between phases.
- Effective-context regression tests in CI: a "lost-in-the-middle" smoke test on representative long inputs that asserts known mid-document evidence shows up in the output.

Why this version: chunking + compaction together change what the tool can do well. The 0.3 telemetry makes the wins visible; without it, this is a leap of faith.

### 0.5.0 — MCP-first surface

The agent-facing surface stops being a side door and becomes a primary product surface.

- Just-in-time MCP context. New: `find_insights(topic, query)` returns ranked `(path, one_line_preview, score)` tuples; `read_insight(path, section?)` for drill-down. Existing whole-file tools stay for explicit "give me the file" calls but stop being the default response shape.
- Every CLI command exposes structured output (`--json`) and respects `NO_COLOR`. Stable, documented exit codes.
- MCP tool surface mirrors the CLI command surface: every long-running command has a matching tool with progress events and a clean done/cancel/error contract. Tool schemas are introspectable.
- Research-gap discovery as an MCP tool that an external agent can call without scraping the dashboard.
- Native watch-alert notification channels (the `library/watch_alerts.md` stream is in; outbound email/Slack/webhook is not).

Why this version: this is the "MCP-first 2026 app" version. It defines how agents drive distillr from here on, so it should land before the corpus shape changes underneath it.

### 0.6.0 — Local-control parity

Closes the gap between the "local Markdown corpus" promise and the "every analysis call hits a paid cloud API" reality.

- Ollama / LM Studio as first-class providers in the LLM router from 0.3. Per-workload model selection via config and `--model` overrides on individual commands.
- Cost log distinguishes paid-API spend from local-inference time; `distill costs` shows both axes so users can size local vs. cloud trade-offs.
- Dockerfile + docker-compose with Playwright deps included. `distill doctor` knows it's running in a container and skips host-only checks.
- Documented quality/throughput trade-offs per workload — which steps degrade gracefully on smaller local models, which need cloud-grade reasoning.

Why this version: the audience that wants distillr the most is the audience that won't run it if it requires API keys. Shipping this before the wiki/concept layers means deeper corpus features land in a tool that can run fully on-device.

### 0.7.0 — Living wiki

The corpus shifts from "directory of artifacts" to "navigable knowledge base," using ecosystem tools (Obsidian, Logseq, Dendron) for visualization rather than building a graph view in distillr.

- Wiki-style cross-linking in synthesis, brief, report, and research-brief outputs (`[[<paper-slug>_Insights|Title]]` instead of plain citations).
- Backfill / migration tooling for older `insights.md`-style libraries into the 0.3 knowledge-base naming contract.
- Stable link discipline. `distill doctor --links` for backlink integrity.
- `distill open --vault` opens the user's default markdown editor pointed at `library/`.

Why this version: pure prompt + frontmatter + tooling work, no model changes. Lands before the concept layer because concept notes need stable link discipline to be worth building on.

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

Why this version: 1.0 is a stability *and* quality claim. It's the version external systems can build on without expecting churn, and the version a new contributor can land a clean PR in without a long onboarding tail.

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
│   │   ├── chunking.py      # 0.4 — section-aware
│   │   └── rerank.py        # 0.4 — per-category chunk rerank
│   ├── synthesis/
│   │   ├── topic.py
│   │   ├── corpus.py
│   │   └── register.py      # 0.9 — PhD / exec / pop styles
│   ├── report/              # 4-phase Deep Research pipeline
│   │   ├── phase1_research.py
│   │   ├── phase2_facts.py
│   │   ├── phase3_writing.py
│   │   ├── phase4_qa.py
│   │   └── compaction.py    # 0.4 — between-phase summaries
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

A roadmap is also an opinion about what *not* to build. These are deliberate exclusions, not gaps.

- **No graph-view UI inside distill.** Obsidian / Logseq / Dendron already do this well; reimplementing duplicates effort without adding value. The Obsidian-native milestone (0.7) is the answer.
- **No proprietary editor, mobile app, or cloud-hosted SaaS.** The whole point is plain-text Markdown with no lock-in. A hosted version would create exactly the dependency the project exists to avoid.
- **No general-purpose RAG / vector-store framework.** distillr is opinionated about the corpus shape and the analysis pipeline. Embeddings are an implementation detail (used selectively for dedup, possibly inside `find_insights`), not a primary surface. Users who want a generic RAG toolkit have LangChain and LlamaIndex.
- **No multi-user / auth / collaboration layer.** Single-user local tool. Shared corpora are a `git` problem, not a distillr problem.
- **No additional cloud LLM providers by default.** Each provider is calibration debt — prompts that work well on one model regress on another. Users can wire OpenAI / Anthropic / Mistral / etc. through the 0.3 router, but distillr won't ship default model policies for them. Local providers are the exception because they carry the local-first promise.
- **No plugin / extension system before 1.0.** Premature abstraction. The right plugin boundaries become obvious only after the internal architecture from 0.3–0.5 has carried real workloads. Revisit post-1.0.
- **No real-time collaboration or sync service.** Markdown + git is the answer. distillr won't compete with Obsidian Sync, Logseq Sync, or Syncthing.
- **No anti-bot / paywall / login-walled scraping.** Playwright handles legitimate access; defeating hostile defenses is whack-a-mole that pulls focus from the analysis pipeline and creates legal/ethical surface area.
- **No "cheap mode" that compromises fidelity.** The product premise is "expensive but right" for the analyst-in-a-loop workload. Cost reduction happens through chunking, compaction, local models, and JIT context — not through cheaper prompts that produce worse outputs.

These exclusions are load-bearing, not permanent. They get revisited if the constraint that drives them changes.

## Full backlog

The area-by-area backlog (stay-current, dashboard, papers, cross-source intelligence, context engineering, discovery loop, etc.) lives in [`docs/roadmap.md`](docs/roadmap.md). Items there will be tagged with the milestone above where they land in a follow-up pass.

Design principles drawn from the context-engineering literature are summarized in [`docs/architecture.md#context-engineering-principles`](docs/architecture.md#context-engineering-principles).
