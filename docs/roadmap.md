# Full roadmap (detail)

The short public summary lives at [`../ROADMAP.md`](../ROADMAP.md). This file is the un-trimmed backlog with priority breakdowns by area — useful if you're considering contributing or want to see how something specific is prioritized.

Shipped work lives in [`CHANGELOG.md`](CHANGELOG.md) (the 0.1.0 entry covers the initial public release; the "Pre-release Development" section covers everything built before that).

## Current Direction

Distill is a source-to-intelligence platform with three active source types:

- YouTube for staying current on channels and topics
- Websites for vendor, lab, and research-corpus distillation
- arXiv papers, using the same capture -> analyze -> synthesize -> report pipeline

Current UX priorities:

- Make the website workflow feel first-class instead of command-by-command
- Keep the YouTube "stay current" path fast and obvious
- Goal-aware discovery as the front door when the user has a research goal rather than a keyword query (`distill discover` shipped; next: websites in the source pool, watch integration for goal files)
- Improve handoff and notification paths so Distill works as a daily-driver research system, not just a batch CLI
- Move the corpus toward an Obsidian-native "living wiki" shape (see section 10)

## Next Up

The work ahead is ordered around the product's three core jobs:

1. Stay current on fast-moving topics
2. Learn a source set quickly
3. Build a reusable corpus for deeper reporting and agent workflows

The broader direction is for Distill to work well as the research-and-corpus layer
in multi-agent systems — a tool other agents can query via MCP to get grounded,
structured intelligence without duplicating ingestion work. The priorities below
build toward that: tighter outputs, cleaner handoffs, and interoperability with
orchestration layers.

Legend: `[ ]` not started, `[~]` partial / in progress, `[x]` shipped (item will
be moved to `CHANGELOG.md` on next release).

### 1. Make "Stay Current" a first-class workflow

- [x] Recurring topic-watch objects with daily or weekly cadence
- [x] Topic-watch ranking modes (freshness, balanced, popularity)
- [x] "What changed" outputs between topic-watch runs so recurring monitoring is more useful than rerunning `latest`
- [~] Proactive freshness alerts after catch-up or scheduled refresh. CLI-native watch-alert digests persist to `library/watch_alerts.md`, and the same alert stream is exposed via MCP at `distill://watch-alerts`. Outbound channels (email, Slack) are still pending.
- [ ] Unified watch model that blends creator monitoring and topic discovery when needed, while keeping the distinction legible in the UX
- [~] Trend radar and evolution timelines so users can see trajectory over time, not just the latest snapshot

### 2. Build a real dashboard and cost surface

- [x] `distill` with no args is a dashboard for tracked topics, tracked channels, recent runs, failures, and outputs
- [~] Projected next-run cost by workflow, not just historical spend
- [~] Rolling cost by topic and source type so users can see where spend is going
- [~] Surface stale corpora, failed runs, thin transcripts, and crawl drift in one place
- [~] Cost anomaly detection and budget guardrails per topic or workflow so expensive runs are predictable
- [~] Interactive library browser (TUI first or lightweight local web view) for scanning topics, channels, videos, pages, and artifacts at scale
- [ ] **Per-prompt token telemetry.** Log prompt-input length, output length, and elapsed time *per call* (not just per run) to `library/cost_log.jsonl` — needed to make context-engineering improvements (chunked paper analysis, report-pipeline compaction) measurable. Surface a "biggest prompts" view in `distill costs` so prompt budget regressions are visible.

### 3. Productize the core workflow

- [~] Make the command model more intent-first around staying current, learning fast, and reporting
- [~] Intent-first aliases or a lightweight wizard for recurring jobs such as monitor, ramp-up, and report
- [x] Checked-in seed-file example for site batches (`configs/example_seeds.json`; user-local `configs/*_seeds.json` are git-ignored)
- [x] Multi-topic, context-shaped briefings and syntheses (`distill research-brief` + `distill synthesize`) with a TEMPLATE context file so user context files stay local
- [ ] Make source-set inputs feel first-class instead of relying on one-off command choreography
- [ ] Clarify corpus outputs and how to inspect or export them for downstream use
- [~] Export / handoff presets for downstream agent roles and RAG pipelines (for example zipped MD/JSON bundles with clean metadata, confidence tags, and structured fields that consuming agents can act on without parsing prose)

### 4. Tighten the YouTube experience

- [ ] Live cost ticker during runs (estimated from token counts)
- [ ] Total content stats in discovery ("Found 88 videos + 12 Shorts, ~47 hours of content")
- [x] `distill diff <topic>` — show what changed since the last watch run or fallback window (new videos, pages, papers, refreshed outputs)
- [x] Trend detection across recorded topic change windows (`distill trends`)
- [~] Research history — track how findings evolve over time, diff between runs
- [ ] Multi-pass escalation on demand so catch-up can stay cheap by default and selectively deepen only the highest-signal items
- [ ] Persist creator voice / bias cards so synthesis can account for recurring framing, reliability, and drift over time

### 5. Finish website productization

- [x] Generic website distillation — single URL or curated URL list input, browser-first crawl, per-page insights, site/topic synthesis, Deep Research report assembly
- [x] Model policy by workload — keep cheap bulk-video defaults while using premium Grok models for website/page distillation where higher fidelity matters
- [ ] Website UX polish — checked-in examples, cleaner crawl defaults, better attachment discovery, less one-off command choreography
- [ ] Better crawl boundary controls — keep site batches close to the intended section or branch by default
- [~] Attachment ingestion — inventory embedded PDFs/videos and optionally pull PDF text or supported embedded-video transcripts into website runs
- [ ] Mixed exact-page and shallow-crawl workflows that are easier to understand and safer by default
- [~] Section-aware freshness so website refreshes focus on changed branches instead of re-crawling everything

### 6. Papers as a first-class source type

- [x] arXiv discovery with ranking by topic fit. `distill papers` now expands the user query into up to six arXiv search variants, dedupes by `paper_id`, LLM-reranks with `RankedPaper` (relevance / depth / novelty / credibility), and supports `--preview` before ingestion. Multi-word phrase-match brittleness was fixed (2 words phrase, 3+ AND-joined).
- [ ] Semantic Scholar and Google Scholar integration for recency + citation-weighted ranking signals beyond arXiv.
- [x] Paper ingestion pipeline — PDF/text extraction (pypdf, 100K char cap, surrogate-sanitized), paper-specific analysis via Grok 4.20, per-paper insights, paper-level and mixed-source corpus synthesis
- [x] Paper-specific storage and metadata conventions that match the existing corpus model
- [x] Paper-first workflows for "learn this research area fast" — `distill papers <query> --topic <name> --limit N` pulls LLM-ranked arXiv papers, extracts full PDF text, runs structured analysis, and produces per-topic paper synthesis without forcing YouTube- or website-shaped commands
- [ ] **Chunk-and-rerank paper analysis (effective-context-aware).** Today the full PDF (truncated at 100K chars) is dumped into a single Grok prompt, which is exactly the "Dump Truck" anti-pattern that LongBench v2 / RULER / ∞Bench / STRING benchmarks show degrades sharply when relevant evidence sits mid-document. Replace with: section-aware chunker (use PDF headings; fall back to page+window slicing); per-category rerank ("which chunks matter for *Methods*, *Limits*, *Open Questions*?"); small-window analysis loop assembling `<paper-slug>_Insights.md` from focused passes. Outcome: better fidelity on long papers without higher token spend; per-prompt token counts as a first-class telemetry surface.
- [ ] **Lift the 100K char cap once chunking is in place.** The cap was a defensive band-aid for the dump-truck pattern; once analysis runs over chunks, full long papers can be processed without prompt blowups.

### 7. Strengthen corpus quality and reuse

- [ ] Stale detection — flag insights generated with old prompt versions, suggest re-analysis
- [ ] Auto-reanalysis triggers when prompts, models, or quality heuristics change materially
- [ ] Duplicate detection — catch same video under multiple slugs (re-uploads, title changes)
- [ ] Semantic deduplication across videos, pages, and papers so near-duplicates do not pollute synthesis.
  Note: source-origin attribution is handled in synthesis/report prompts without collapsing repeated claims; any future dedup work should stay artifact-preserving.
- [~] Insights quality check — heuristic validation (all expected sections present? suspiciously short?)
- [~] Transcript validation — flag suspiciously short transcripts (<500 chars for a 30-minute video) as likely failed captions
- [ ] Structured logging — proper log levels, log to file for post-run review, debug mode flag

### 8. Expand cross-source intelligence

- [~] Mixed-source topic synthesis that treats YouTube, websites, and papers as one corpus. `distill corpus` is live, MCP exposes `distill://topics/{topic}/corpus` and `distill://topics/{topic}/sources`, and `resynthesize_topic` refreshes corpus synthesis; deeper cross-source reasoning and dedup are still pending.
- [x] **Goal-aware cross-source discovery** — `distill discover "<goal>"` (or `--goal-file`) generates paper + video queries from a natural-language goal, fans out, and runs a unified goal-aware rerank *across source types* before ingestion. Closes the front-door gap between "I have a keyword" and "I have a research goal."
- [ ] Extend discover to include website seeds alongside papers + videos.
- [ ] `distill watch` integration for goal files — re-run discover against a saved goal on a cadence so goal-driven topics refresh the same way keyword topics do.
- [ ] Multi-topic channels — same channel filed under multiple topics with shared transcripts
- [x] MCP-powered research-gap discovery so external agents can ask Distill what is missing and trigger follow-on ingestion
- [ ] More source types — podcasts, RSS feeds, conference talks (same pipeline, different discovery)

### 9. Ongoing operation and access

- [ ] Scheduled refresh — cron/task-scheduler integration for hands-off weekly updates
- [ ] Native notification integrations for daily briefings, weekly digests, and important-change alerts
- [ ] Web UI — browse the library, read insights, compare channels in a browser

### 10. Living Wiki Corpus (Obsidian-native, LLM-maintained)

Distill's corpus is already a directory of plain-text markdown artifacts with
structured frontmatter. Two convergent signals push toward treating that directory
as a *living wiki* rather than a filing cabinet:

- Obsidian (and the broader markdown-vault ecosystem: Logseq, Dendron, Foam) gives users a free graph view, backlink panel, and fuzzy search the moment the corpus uses `[[wiki-style links]]` and consistent frontmatter.
- Karpathy's early-April-2026 "LLM Wiki" pattern shows that an LLM agent curating a concept-indexed markdown knowledge base produces something qualitatively different from one-shot RAG: knowledge that compounds across ingestion runs rather than evaporating after each session.

The goal is for the corpus to be interoperable, compounding, and self-maintaining,
without locking users into any particular viewer or requiring bespoke tooling.

*Tier 1 — Obsidian-native output (low-effort, immediate ecosystem lift)*

- [ ] Wiki-style cross-linking in synthesis, brief, report, and research-brief outputs: when an artifact cites a paper/video/page, emit `[[<slug>_Insights|Paper Title]]` instead of a plain citation. Prompt-level change; file paths are already known at generation time.
- [x] Standardized YAML frontmatter across generated Markdown artifacts: `type`, `topic`, `source`, `date`, `authors`, `tags`, `confidence`. Concept/entity-specific tags such as `#technique/tkg` and contested/corpus-consensus labels continue in Tier 2.
- [ ] `distill open --vault` (or equivalent hint in `distill dashboard`): launch the user's default markdown editor pointed at `library/`, so the free graph view and backlinks come with zero install steps.
- [ ] Stable slug/link discipline: enforce one canonical URL per artifact so renames don't break backlinks. Link-check pass available via `distill doctor --links`.

*Tier 2 — LLM-maintained concept layer (Karpathy + ACE)*

This tier follows the Agentic Context Engineering (ACE) framework's
architectural choice: concept notes are evolving structured *playbooks*, not
prose summaries. ACE empirically outperforms compressed-summary approaches
(Dynamic Cheatsheet, GEPA) on agent benchmarks specifically because itemized
deltas avoid the *context-collapse* failure mode (the documented case where
an 18K-token playbook compressed to 122 tokens lost most of its recall).

- [ ] Concept extraction pass: after each ingestion run, detect named techniques, architectures, people, vendors, and methodologies mentioned across 3+ insights. Emit `library/concepts/<slug>.md` stubs as *itemized playbook entries* (not freeform prose), each with stable `id`, `[[backlinks]]` to every source that mentioned the concept, and metadata fields (`first_seen`, `last_seen`, `helpful_count`, `harmful_count`, `provenance`). Updates are deterministic delta merges (append / modify / dedup-via-embedding), never wholesale rewrites.
- [ ] Entity notes for people and vendors: `library/entities/<slug>.md` with role, affiliation, the sources that discuss them, and stable backlinks. Same playbook-entry shape as concept notes.
- [ ] Intelligent merging on refresh: when a new source mentions an existing concept, the agent issues a *delta update* — appends a new entry with provenance, increments `helpful_count` if the new source corroborates an existing entry, adds a `[contested]` annotation if it contradicts. Prior versions stay in `.history/` (append-only). No monolithic rewrites.
- [ ] Contradiction flagging: when two sources make incompatible claims about a concept/entity, surface the disagreement as a flagged `[contested]` entry on the concept note rather than averaging the claims, and lift it into `distill health` so stewards see it. This matches the ACE framework's explicit handling of `harmful_count` and the production-grade context-engineering "Provenance" criterion (Vishnyakova 2026).
- [ ] Concept/entity graph export: a `concepts.jsonl` and `entities.jsonl` suitable for programmatic downstream use (agents, RAG pipelines, external graph DBs) — parallel to the existing handoff exports. Entries carry the same metadata shape so consumers can reason about confidence and provenance.
- [ ] Optional: `distill ingest <path>` takes a local file (PDF, markdown, clipped article) and routes it through the same capture -> analyze -> integrate pipeline, mirroring how Obsidian's Web Clipper feeds Karpathy's wiki.

*Tier 3 — explicitly not in scope*

- Building a graph-view UI inside distill. The Obsidian/Logseq/Dendron graph views are already good; reimplementing would duplicate effort without adding value.
- A distill-proprietary editor, mobile app, or cloud-hosted wiki service. The whole point is plain-text markdown with no lock-in.
- Replacing the existing hierarchical folder layout. Obsidian works fine with subfolders; concept and entity notes layer on top of the existing structure rather than replacing it.

*Why this belongs on the roadmap*

The Obsidian + LLM-Wiki direction fits what distill already produces. Tier 1 is
mostly prompt and frontmatter edits — interop with an ecosystem that already solves
visualization. Tier 2 is where distill shifts from processing sources in batches to
maintaining a navigable knowledge base — the difference between "100 markdown files
about TKGs" and "a TKG concept note that cites every relevant source I've ingested,
updates on refresh, and flags when a new paper contradicts prior findings." The
ingestion, synthesis, and per-source provenance layers needed for that already
exist; the missing pieces are cross-linking conventions and a concept-extraction
pass.

### 11. Context engineering hardening

The 2025–2026 context-engineering literature (Mei et al.'s 1,400-paper survey;
Anthropic's compaction guidance; the ACE framework on evolving playbooks;
Vishnyakova's production-grade context-engineering criteria) makes three
empirical points distillr should act on: claimed context windows are not
effective windows, lost-in-the-middle dominates failures on long inputs, and
JSON handoffs strip semantic richness in ways that compound across phases.
Items below are concrete plumbing work that protects output quality and
controls token spend as the corpus grows. See [`architecture.md#context-engineering-principles`](architecture.md#context-engineering-principles)
for the principles these items derive from.

- [ ] **Just-in-time MCP context (paths-not-payloads).** Today `distill-mcp` returns full markdown files; a 50KB synthesis artifact blows the consuming agent's window for what may be a one-line lookup. Anthropic's published example reduced a comparable workflow from ~150K to ~2K tokens (98.7% saving) by switching tool returns from raw payloads to structured summaries plus paths. Add `find_insights(topic, query)` returning ranked `(path, one_line_preview, score)` tuples; add `read_insight(path, section?)` for drill-down. Existing tools that return full bodies stay (for explicit "give me the file" calls) but stop being the default response shape.
- [ ] **Compaction in the 4-phase report pipeline.** Phase 2 (section writing) and Phase 4 (QA) currently carry full prior-section context forward to enforce no-repeat. Switch to high-recall-then-precision compaction (the Anthropic pattern) and OpenAI-style opaque continuation items where the API supports them. Goal: significant token-spend reduction on long reports with no loss of cross-section coherence. Measure via the per-prompt token telemetry from section 2.
- [ ] **Effective-context regression tests.** Add a small fixture suite that runs paper-analysis / synthesis / report prompts against representative long inputs and asserts the output covers known mid-document evidence (a "lost-in-the-middle" smoke test). Wire into CI so regressions surface in PRs rather than user reports.
- [ ] **Tool-result clearing in iterative loops.** Long-running watch and discover loops accumulate tool-call results that are no longer relevant. Implement Anthropic's "clear stale tool results" pattern as a baseline compaction step before each new LLM call in those loops.
- [ ] **Document the principles in the contributor guide.** Add a "context engineering" section to `docs/CONTRIBUTING.md` so new prompt and pipeline work follows the same posture (just-in-time hydration, paths-not-payloads, structured deltas-not-rewrites).

### 12. Discovery loop hardening (preview → approve → ingest)

These items came out of real research-session friction during a multi-topic
ingest run on closed timelike curves: previewing the candidate pool, sizing the
real run, approving spend, and watching costs accumulate across iterative
preview cycles. The pieces shipped in 0.2.0 (preview cost-log differentiation,
`--papers-only` / `--videos-only`, `--top-by-date` for `latest`) closed the
near-term gaps; the items below are the deeper design questions that surfaced
in the same session and deserve their own write-ups before implementation.

- [ ] **Rerank determinism: preview → ingest commit-by-ID.** Previewing the
  goal-ranked shortlist and then running the real ingest can produce a different
  shortlist (LLM rerank is non-deterministic). For research-quality work, the
  user should be able to commit to *the exact set they previewed*. Two design
  options to evaluate: (a) cache the previewed shortlist by hash of (goal,
  model, candidates) under `library/.preview_cache/<id>.json` and add
  `--from-preview <id>` so the ingest replays the exact selection; (b) make
  the rerank deterministic via temperature=0 + a stable seed. (a) is more
  honest about the LLM rerank being a judgment call rather than a lookup; (b)
  is cheaper to implement but doesn't address the seed-drift between model
  releases. Likely answer: ship (a) and use (b) as a fallback when no preview
  cache exists.
- [ ] **Calibration: unify or differentiate the discover and latest rerank
  prompts.** A real session showed `discover --preview` ranking 0/33 candidate
  videos as worth ingesting on a topic, while `latest --preview` on the same
  topic surfaced 5 strong picks (including expert lectures by authors of the
  top-ranked papers in the same session). Both commands run the same Grok
  model with similar inputs; the divergence is in prompt calibration. Audit
  the two rerank prompts side by side, decide whether the divergence is
  intentional (discover = rigor-tuned, latest = relevance-tuned) or
  accidental, and either unify them or expose a `--rigor strict|balanced|loose`
  knob that callers can tune per source type. Without this, the "unified front
  door" promise of `discover` doesn't hold for any topic where strong videos
  exist but the rigor bar excludes them.
- [ ] **Real cost estimator that reads candidate metadata.** Today's pre-run
  estimate is a flat `$0.05/paper` × N rate that misses 2–3× actual on short
  papers and undershoots on long ones. Build an estimator that reads candidate
  metadata before the run: arXiv abstract length and PDF page count for papers,
  `yt-dlp --print duration` for videos, page count and content-length headers
  for sites. Calibrate against historical `cost_log.jsonl` rows so the estimate
  improves over time. Surface as the spend half of the unified preview-and-
  approval prompt described in `ROADMAP.md` "What's next" item 6.
- [ ] **Preview-as-primary-flow UX.** Today `--preview` is a flag the user adds
  to a command they're about to run anyway. The mental model that surfaces
  during real research is the opposite: probe the candidate pool, see the
  quality cliff, decide a sizing, see the cost, *then* commit. Reshape so the
  default flow on a fresh topic is: `distill discover "<goal>"` → goal-ranked
  table with cliff-detected sizing options ("3 excellent / 5 including good /
  7 including OK") and per-option spend → typed approval → ingest. Depends on
  the rerank-determinism work above (commit-by-ID) and the real cost estimator;
  builds on `ROADMAP.md` item 6.
- [ ] **Synthesis register styles, with PhD-level as the new default.** Today
  `distill synthesize` is a single-call Grok 4.20 corpus-only pass with a
  prompt calibrated for an executive-briefing register. The pattern that
  surfaced during the CTC research session — produce thorough per-source
  analyses first, then load *all* of them into one Grok 4.20 prompt and ask
  for graduate-level cross-document analysis (open questions, methodological
  tensions, citation-style claim attribution, evidence map, open-vs-settled
  scoreboard) — should be the *default* `distill synthesize` output, since
  it's what the corpus is actually built for. Demote the executive-briefing
  variant to an explicit opt-in (`--style exec` or `distill synth-exec`).
  Plan: (a) extract synthesis register prompts into a `--style` registry
  (`phd` default, `exec` for one-page briefing, `pop` for accessible
  explainer, room for more — `landscape`, `disagreements-only`, etc.); (b)
  context-budget preflight that enumerates what fits in Grok 4.20's ~256K
  window (typically 5–25 papers' worth of insights at 7–10 KB each), warns
  on overflow, and lets the user choose to drop low-confidence items rather
  than truncate; (c) per-claim source attribution in the PhD output so
  readers can trace each finding to a specific `_Insights.md` artifact; (d) distinct
  artifact filenames (`synthesis_phd.md` / `synthesis_exec.md` / etc.) so
  styles coexist and can be compared side by side. This is the opposite
  trade-off from `roadmap.md` item 6 (chunk-and-rerank): chunking handles
  "input is too long for one prompt"; deep synthesis handles "every claim
  needs to be visible at once for cross-document reasoning."
