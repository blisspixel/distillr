# Roadmap

High-level direction. Shipped work lives in [`docs/CHANGELOG.md`](docs/CHANGELOG.md). The full, un-trimmed backlog with priority breakdowns lives in [`docs/roadmap.md`](docs/roadmap.md).

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

See [`docs/CHANGELOG.md`](docs/CHANGELOG.md) for the full 0.1.0 entry plus consolidated pre-release history.

## Recently shipped (Unreleased)

**yt-dlp staleness preflight + `distill doctor --update`.** yt-dlp ships date-stamped releases (`2026.3.17`) and breaks frequently when YouTube changes things, so commands that touch it now do a zero-network version-age check on entry — locally parses the version, warns once if older than 14 days, caches the result for 24h, honors `DISTILL_NO_PREFLIGHT=1` for CI. `distill doctor --update` shells `pip install --upgrade yt-dlp` and invalidates the cache. Discovery errors that match extractor-failure patterns now print a one-line hint pointing at the fix.

**Goal-aware discover phase.** Closed the front-door gap. `distill discover "<goal>"` (or `--goal-file PATH`) generates paper + video queries from a goal, runs them, LLM-reranks candidates *against the goal* across both source types, shows one unified ranked table, and ingests the shortlist after confirmation. `distill papers` was brought up to parity with `distill latest` in the same pass (query expansion, LLM rerank, `--preview`). See CHANGELOG Unreleased.

## What's next

The 2025–2026 research consensus on context engineering — that *effective* context window is much smaller than claimed, that lost-in-the-middle and context rot dominate failures on long inputs, that just-in-time retrieval beats pre-loading, and that ACE-style evolving "playbooks" beat one-shot summarization — gives the next phase of distillr a sharper frame. Distillr already does several of these instinctively (library-first external memory, refresh-first state tracking, model routing by workload), but three priorities directly extend that posture.

**1. Effective-context-aware paper analysis (chunk-and-rerank).** Today `distill papers` truncates each PDF at 100K chars and stuffs the whole thing into a single Grok prompt — exactly the "Dump Truck" anti-pattern that benchmarks like LongBench v2, RULER, and ∞Bench show degrades sharply when the relevant evidence sits in the middle of a long input. The fix is a section-aware chunker, per-category rerank (which chunks matter for *Methods*, *Limits*, *Open Questions*?), and a small-window analysis loop that assembles the per-paper `insights.md` from focused passes. Outcome: better fidelity on long papers without higher token spend, and a per-prompt token telemetry surface that makes regressions visible.

**2. Concept playbook layer (ACE-inspired, not just a wiki).** Extract named techniques, architectures, people, and vendors mentioned across 3+ insights into canonical `library/concepts/<slug>.md` notes — but the structure follows the ACE framework rather than freeform summaries: each concept note is an itemized, metadata-tagged playbook (`source_id`, `helpful_count`, `harmful_count`, `last_seen`, `provenance`), updated by deterministic delta merges on refresh rather than wholesale rewrites. This avoids the context-collapse failure mode (an 18K-token playbook compressed to 122 tokens with major recall loss). Contradictions surface as flagged entries rather than being silently averaged out. Carries confidence labels through to downstream synthesis and report prompts.

**3. Just-in-time MCP context (paths, not payloads).** Today `distill-mcp` returns full markdown files — a 50KB `synthesis.md` blows the consuming agent's working window for what may be a one-line lookup. Anthropic's published example reduced a comparable workflow from ~150K to ~2K tokens (98.7% saving) by switching tool returns from raw payloads to structured summaries plus paths the agent drills into via a second tool call. distillr's MCP server should adopt the same pattern: `find_insights(topic, query)` returns ranked paths with one-line previews; `read_insight(path, section?)` fetches only the requested section. Plus richer export presets, gap-detection tools, native watch-alert notification channels, and a goal-file refresh hook for `distill watch`.

**4. Obsidian-native output (the artifact layer for the above).** Wiki-style cross-linking (`[[papers/<slug>/insights|Title]]`), standardized YAML frontmatter with tags and confidence labels, `distill open --vault`. Interop with Obsidian / Logseq / Dendron — no new UI to build. Naturally pairs with the concept playbook layer above (concept notes become first-class vault citizens with backlinks).

**5. Compaction in the 4-phase report pipeline.** Today each report phase carries the full prior-section context forward to enforce no-repeat. Switching to high-recall-then-precision compaction (the Anthropic pattern) and OpenAI-style opaque continuation items would significantly cut token spend on long reports, with no loss of cross-section coherence. Includes adding per-phase token telemetry so we can see the savings.

Plus ongoing polish: live cost tickers, better crawl-boundary controls, semantic dedup across sources, structured logging, scheduled refresh via cron/task scheduler, and continued quality hardening (raising typing coverage, paying down CLI monolith debt, and moving Pyright toward a blocking gate).

Full priority breakdown by area (stay-current, dashboard, papers, cross-source intelligence, etc.) lives in [`docs/roadmap.md`](docs/roadmap.md). Design principles drawn from the context-engineering literature are summarized in [`docs/architecture.md#context-engineering-principles`](docs/architecture.md#context-engineering-principles).
