# Roadmap

High-level direction. Shipped work lives in [`CHANGELOG.md`](CHANGELOG.md). The full, un-trimmed backlog with priority breakdowns lives in [`docs/roadmap.md`](docs/roadmap.md).

## Current shape

Distill is a source-to-intelligence platform covering three source types:

- **YouTube** — channels, topic searches, videos, Shorts
- **Websites** — vendor sites, research hubs, curated URL sets
- **arXiv papers** — phrase-matched search, full-PDF extraction, cross-paper synthesis

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

See [`CHANGELOG.md`](CHANGELOG.md) for the full 0.1.0 entry plus consolidated pre-release history.

## Recently shipped (Unreleased)

**Goal-aware discover phase.** Closed the front-door gap. `distill discover "<goal>"` (or `--goal-file PATH`) generates paper + video queries from a goal, runs them, LLM-reranks candidates *against the goal* across both source types, shows one unified ranked table, and ingests the shortlist after confirmation. `distill papers` was brought up to parity with `distill latest` in the same pass (query expansion, LLM rerank, `--preview`). See CHANGELOG Unreleased.

## What's next

Three priority directions for the next minor releases:

**1. Obsidian-native output.** Wiki-style cross-linking between artifacts (`[[papers/<slug>/insights|Title]]`), standardized YAML frontmatter with tags and confidence labels, and `distill open --vault`. Interop with the existing markdown-vault ecosystem (Obsidian, Logseq, Dendron) — no new UI to build.

**2. LLM-maintained concept layer.** Extract named techniques, architectures, people, and vendors mentioned across 3+ insights into canonical `library/concepts/<slug>.md` notes with backlinks. Intelligent merging on refresh. Contradiction flagging. This is the Karpathy "LLM Wiki" pattern applied to the corpus.

**3. Tighter handoff to agent workflows.** Richer export presets (zipped MD/JSON bundles with metadata and confidence tags), more MCP tools around gap detection and scheduled ingestion, native notification channels for watch alerts. Includes a goal-file refresh hook for `distill watch` so goal-driven topics stay current the same way keyword topics do.

Plus ongoing polish: live cost tickers, better crawl-boundary controls, semantic dedup across sources, structured logging, scheduled refresh via cron/task scheduler.

Full priority breakdown by area (stay-current, dashboard, papers, cross-source intelligence, etc.) lives in [`docs/roadmap.md`](docs/roadmap.md).
