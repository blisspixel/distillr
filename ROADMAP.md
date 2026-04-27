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

## What's next

The 2025–2026 research consensus on context engineering — that *effective* context window is much smaller than claimed, that lost-in-the-middle and context rot dominate failures on long inputs, that just-in-time retrieval beats pre-loading, and that ACE-style evolving "playbooks" beat one-shot summarization — gives the next phase of distillr a sharper frame. Distillr already does several of these instinctively (library-first external memory, refresh-first state tracking, model routing by workload), but three priorities directly extend that posture.

**1. Effective-context-aware paper analysis (chunk-and-rerank).** Today `distill papers` truncates each PDF at 100K chars and stuffs the whole thing into a single Grok prompt — exactly the "Dump Truck" anti-pattern that benchmarks like LongBench v2, RULER, and ∞Bench show degrades sharply when the relevant evidence sits in the middle of a long input. The fix is a section-aware chunker, per-category rerank (which chunks matter for *Methods*, *Limits*, *Open Questions*?), and a small-window analysis loop that assembles the per-paper `insights.md` from focused passes. Outcome: better fidelity on long papers without higher token spend, and a per-prompt token telemetry surface that makes regressions visible.

**2. Concept playbook layer (ACE-inspired, not just a wiki).** Extract named techniques, architectures, people, and vendors mentioned across 3+ insights into canonical `library/concepts/<slug>.md` notes — but the structure follows the ACE framework rather than freeform summaries: each concept note is an itemized, metadata-tagged playbook (`source_id`, `helpful_count`, `harmful_count`, `last_seen`, `provenance`), updated by deterministic delta merges on refresh rather than wholesale rewrites. This avoids the context-collapse failure mode (an 18K-token playbook compressed to 122 tokens with major recall loss). Contradictions surface as flagged entries rather than being silently averaged out. Carries confidence labels through to downstream synthesis and report prompts.

**3. Just-in-time MCP context (paths, not payloads).** Today `distill-mcp` returns full markdown files — a 50KB `synthesis.md` blows the consuming agent's working window for what may be a one-line lookup. Anthropic's published example reduced a comparable workflow from ~150K to ~2K tokens (98.7% saving) by switching tool returns from raw payloads to structured summaries plus paths the agent drills into via a second tool call. distillr's MCP server should adopt the same pattern: `find_insights(topic, query)` returns ranked paths with one-line previews; `read_insight(path, section?)` fetches only the requested section. Plus richer export presets, gap-detection tools, native watch-alert notification channels, and a goal-file refresh hook for `distill watch`.

**4. Obsidian-native output (the artifact layer for the above).** Wiki-style cross-linking (`[[papers/<slug>/insights|Title]]`), standardized YAML frontmatter with tags and confidence labels, `distill open --vault`. Interop with Obsidian / Logseq / Dendron — no new UI to build. Naturally pairs with the concept playbook layer above (concept notes become first-class vault citizens with backlinks).

**5. Compaction in the 4-phase report pipeline.** Today each report phase carries the full prior-section context forward to enforce no-repeat. Switching to high-recall-then-precision compaction (the Anthropic pattern) and OpenAI-style opaque continuation items would significantly cut token spend on long reports, with no loss of cross-section coherence. Includes adding per-phase token telemetry so we can see the savings.

**6. Preview-first research workflow with quality-cliff detection and spend approval.** `distill discover --preview` already surfaces a goal-ranked plan, but right-sizing the real run still puts the burden on the user: read the table, eyeball where the score cliff falls, mentally do the cost arithmetic, re-run with adjusted limits. The pattern that surfaces naturally during real research sessions is: probe the candidate pool wide, detect the rerank-score cliff, and present "top N excellent" / "top M including good" / "everything ≥ threshold" sizing options with per-option ballpark cost *before* the user commits. Three concrete pieces: (a) cliff detection in the rerank output (largest score gap, or score < cutoff) so we can suggest a defensible N rather than asking for one; (b) a unified papers+videos preview (today `discover` and `latest` are separate commands that hit the same `--topic` from different doors); (c) a "rigor / fuzziness" knob — `--rigor strict|balanced|loose` — so a topic with thin academic coverage but rich video coverage (or vice versa) can relax the goal-fit bar on one source type without dragging the other down. Output: a single approval prompt that quotes spend per sizing option, not a flag the user has to guess.

Plus ongoing polish: live cost tickers, better crawl-boundary controls, semantic dedup across sources, structured logging, scheduled refresh via cron/task scheduler, and continued quality hardening (raising typing coverage, paying down CLI monolith debt, and moving Pyright toward a blocking gate).

Full priority breakdown by area (stay-current, dashboard, papers, cross-source intelligence, etc.) lives in [`docs/roadmap.md`](docs/roadmap.md). Design principles drawn from the context-engineering literature are summarized in [`docs/architecture.md#context-engineering-principles`](docs/architecture.md#context-engineering-principles).
