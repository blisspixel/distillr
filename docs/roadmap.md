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
- Goal-aware discovery as the front door when the user has a research goal rather than a keyword query (`distill discover` now spans papers, videos, and curated website seeds; next: trusted-site discovery for official docs and watch integration for goal files)
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

**Competitive context (May 2026).** The "local-first LLM Wiki" space exploded
post-Karpathy (April 2026). SwarmVault (~400★, desktop app + RAG), obsidian-wiki
(~1,000★, skill-based agent integration), and Lacuna-wiki (MCP-first, DuckDB) are
the closest tools. Distillr's differentiators are goal-aware multi-source discovery,
structured per-item insights + cross-source synthesis, and strict no-database
pure-Markdown discipline. The biggest risk is getting out-marketed on ease-of-agent-
integration; the biggest opportunity is doubling down on researcher rigor that
GUI/RAG-heavy tools can't match. See [`../ROADMAP.md#competitive-landscape-may-2026`](../ROADMAP.md#competitive-landscape-may-2026) for the full analysis.

Legend: `[ ]` not started, `[~]` partial / in progress, `[x]` shipped (item will
be moved to `CHANGELOG.md` on next release).

### 1. Make "Stay Current" a first-class workflow

- [~] Proactive freshness alerts after catch-up or scheduled refresh. CLI-native watch-alert digests persist to `library/watch_alerts.md`, and the same alert stream is exposed via MCP at `distill://watch-alerts`. Outbound channels (email, Slack) are still pending.
- [ ] Unified watch model that blends creator monitoring and topic discovery when needed, while keeping the distinction legible in the UX
- [~] Trend radar and evolution timelines so users can see trajectory over time, not just the latest snapshot

### 2. Build a real dashboard and cost surface

- [~] Projected next-run cost by workflow, not just historical spend
- [~] Rolling cost by topic and source type so users can see where spend is going
- [~] Surface stale corpora, failed runs, thin transcripts, and crawl drift in one place
- [~] Cost anomaly detection and budget guardrails per topic or workflow so expensive runs are predictable
- [~] Interactive library browser (TUI first or lightweight local web view) for scanning topics, channels, videos, pages, and artifacts at scale
- [ ] Live mixed-source run progress so long `discover` / `report` / site-heavy jobs show current phase, current item, completed/failed counts, and where time is going without making the user inspect the filesystem
- [ ] **Per-prompt token telemetry.** Log prompt-input length, output length, and elapsed time *per call* (not just per run) to `library/cost_log.jsonl` — needed to make context-engineering improvements (chunked paper analysis, report-pipeline compaction) measurable. Surface a "biggest prompts" view in `distill costs` so prompt budget regressions are visible.

### 3. Productize the core workflow

- [~] Make the command model more intent-first around staying current, learning fast, and reporting
- [~] Intent-first aliases or a lightweight wizard for recurring jobs such as monitor, ramp-up, and report
- [ ] Make source-set inputs feel first-class instead of relying on one-off command choreography
- [ ] First-class research profiles for "prefer these channels + these trusted domains + this goal file" workflows so recurring analyst use cases (for example Microsoft-only research) do not require rebuilding the same command and seed setup by hand
- [ ] Clarify corpus outputs and how to inspect or export them for downstream use
- [~] Export / handoff presets for downstream agent roles and RAG pipelines (for example zipped MD/JSON bundles with clean metadata, confidence tags, and structured fields that consuming agents can act on without parsing prose)

### 4. Tighten the YouTube experience

- [ ] Live cost ticker during runs (estimated from token counts)
- [ ] Total content stats in discovery ("Found 88 videos + 12 Shorts, ~47 hours of content")
- [~] Research history — track how findings evolve over time, diff between runs
- [ ] Multi-pass escalation on demand so catch-up can stay cheap by default and selectively deepen only the highest-signal items
- [ ] Persist creator voice / bias cards so synthesis can account for recurring framing, reliability, and drift over time
- [ ] Retry / backoff / resume-friendly subtitle handling so transcript-rate-limit failures (`HTTP 429`, extractor churn) degrade gracefully during long mixed-source runs instead of leaving the user to infer what happened from sparse output

### 5. Finish website productization

- [ ] Website UX polish — checked-in examples, cleaner crawl defaults, better attachment discovery, less one-off command choreography
- [ ] Trusted-site discovery for docs-heavy research workflows — given allowlisted domains (for example `learn.microsoft.com`, `microsoft.com`), enumerate candidate pages from TOCs, landing pages, sitemaps, and shallow section crawls before the LLM rerank so users do not have to hand-curate every page seed
- [ ] Better crawl boundary controls — keep site batches close to the intended section or branch by default
- [~] Attachment ingestion — inventory embedded PDFs/videos and optionally pull PDF text or supported embedded-video transcripts into website runs
- [ ] Mixed exact-page and shallow-crawl workflows that are easier to understand and safer by default
- [ ] Better website candidate identity in preview/approval flows — show page-level titles, URLs, section labels, and freshness hints instead of collapsing multiple seeds under one collection label
- [~] Section-aware freshness so website refreshes focus on changed branches instead of re-crawling everything

### 6. Papers as a first-class source type

- [ ] Semantic Scholar and Google Scholar integration for recency + citation-weighted ranking signals beyond arXiv.
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
- [ ] **`distill audit` — one bundled health surface with a report artifact and action menu** (the self-maintaining-audit milestone). Today the pieces are scattered and console-only: `distill health` walks stale syntheses / thin artifacts / contested concepts, `distill doctor --links` runs the broken-backlink check separately, and `research_gaps(topic)` (MCP) computes coverage gaps but isn't wired in. Compose them into a single `distill audit <topic|all>` that (a) runs all of the above plus artifact-level stale-detection, (b) writes the result to a `<topic>_Audit.md` artifact instead of only printing, and (c) offers a phase-2 action menu (apply link/style fixes, draft missing concept-note stubs, hand gaps to gap-driven `discover`). `--report-only` for scheduled runs. This is the Karpathy "monthly health check" pattern; near-zero new capability, high packaging value against GUI-heavy competitors.
- [ ] **Output->input loop (`distill ask`)** (0.10, gated on the run-time verify hook). Every output today (`report`, `research-brief`, `synthesize`) is terminal — nothing re-ingests it, and there's no lightweight query verb. Add `distill ask "<q>" --topic <t>`: query the corpus via the `find_insights` path, write a provenance-stamped `_Answer.md` with `[[backlinks]]`, and `--save` to re-ingest a liked answer as a first-class source so the corpus compounds with use. Re-ingest **must** run the verify hook first (refuse/quarantine unsupported load-bearing claims) — this is what prevents the "answer quietly builds on a mistake" failure the pattern is prone to. MCP `ask` tool for parity.

### 8. Expand cross-source intelligence

- [~] Mixed-source topic synthesis that treats YouTube, websites, and papers as one corpus. `distill corpus` is live, MCP exposes `distill://topics/{topic}/corpus` and `distill://topics/{topic}/sources`, and `resynthesize_topic` refreshes corpus synthesis; deeper cross-source reasoning and dedup are still pending.
- [ ] Trusted-domain website discovery inside `discover` — let the app expand "prefer Microsoft docs / vendor docs / official learn pages" into real page candidates from allowlisted domains, then rerank those page candidates with videos/papers in the same pool
- [ ] `distill watch` integration for goal files — re-run discover against a saved goal on a cadence so goal-driven topics refresh the same way keyword topics do.
- [ ] Multi-topic channels — same channel filed under multiple topics with shared transcripts
- [ ] More source types — podcasts, RSS feeds, conference talks (same pipeline, different discovery)

### 9. Ongoing operation and access

- [ ] Scheduled refresh — cron/task-scheduler integration for hands-off weekly updates
- [ ] **Scheduled audit** (0.10, depends on the self-maintaining audit) — the same scheduler runs `distill audit --report-only` on a cadence (the video's "monthly health check" automation), landing a dated audit artifact so corpus drift, contradictions, and gaps surface without manual prompting.
- [ ] Native notification integrations for daily briefings, weekly digests, and important-change alerts
- [ ] Web UI — browse the library, read insights, compare channels in a browser

### 9b. Engineering foundation — reproducible toolchain and quality gates

The build harness, not the corpus. The adopted/adapted/declined rationale lives in [`../ROADMAP.md`](../ROADMAP.md#engineering-standards-adopted-adapted-declined); the shipped toolchain releases (0.8.3 and the harden series) are in [`CHANGELOG.md`](CHANGELOG.md). This is the itemized backlog of what remains.

- [~] **Branch coverage ratchet** (0.8.3 → 1.0) — `[tool.coverage.run] branch = true`, `--cov-fail-under` set to the measured branch baseline (floor 79) and ratcheted up-only toward the 1.0 flat ≥95% gate.
- [ ] **Full Pyright-strict ratchet** (1.0) — complete the per-package climb 0.8.3 begins (`distill/llm/` already strict-blocking); no `# type: ignore` without an inline reason.
- [ ] **Parse, don't validate — strict domain types at every boundary** (1.0) — parse every external input (MCP tool arguments, frontmatter, adapter/local-file ingest, LLM structured outputs) once at the boundary into a rich domain type (`strict=True, extra='forbid'` Pydantic model, `NewType`, or frozen dataclass); core logic never sees raw primitives.
- [ ] **Verification depth on the deterministic core** (1.0, "formally contracted where it matters") — Design by Contract via `deal` on the merge/normalize/recovery invariants (idempotent + order-independent merge, round-tripping rollback, non-inverting intervals; `deal` also generates Hypothesis tests from the contracts); mutation testing (`mutmut`) of `concepts/` + `library/` + `llm/retry` on a cadence to prove test efficacy; a Hypothesis state machine over the playbook lifecycle (append -> merge -> notes -> snapshot -> rollback -> re-merge); and fault-injection at the external boundaries (malformed LLM JSON, truncated transcripts, network/yt-dlp failures) proving clean degradation and that no-silent-error-swallowing holds under turbulence. Scoped to the pure-Python core + boundaries, not blanket. distillr's concurrency is asyncio IO, so the discipline is async-safety, not free-threaded shared-memory rules.

### 10. Living Wiki Corpus (Obsidian-native, LLM-maintained)

Distill's corpus is already a directory of plain-text markdown artifacts with
structured frontmatter. Two convergent signals push toward treating that directory
as a *living wiki* rather than a filing cabinet:

- Obsidian (and the broader markdown-vault ecosystem: Logseq, Dendron, Foam) gives users a free graph view, backlink panel, and fuzzy search the moment the corpus uses `[[wiki-style links]]` and consistent frontmatter.
- Karpathy's early-April-2026 "LLM Wiki" pattern shows that an LLM agent curating a concept-indexed markdown knowledge base produces something qualitatively different from one-shot RAG: knowledge that compounds across ingestion runs rather than evaporating after each session.

The goal is for the corpus to be interoperable, compounding, and self-maintaining,
without locking users into any particular viewer or requiring bespoke tooling.

**Code-health prerequisites bundled into 0.7.** The wiki milestone also carries
confirmed technical debt that must be resolved before 0.8 adds new commands and
pipeline stages: `_cli_impl.py` decomposition into `commands/`, path/slug logic
centralization to `library/paths.py`, legacy `router_config_from_distill` bridge
deletion, artifact provenance fields in frontmatter, and report-phase retry
hardening (backoff + jitter + `LLMCall` dataclass). These are not new scope — they
are prerequisites that the concept-extraction pass (0.8) would otherwise inherit
as compounding debt.

*Tier 1 — Obsidian-native output (low-effort, immediate ecosystem lift)*

_All four Tier-1 items shipped — wiki-style cross-linking, standardized YAML frontmatter, `distill open --vault`, and stable slug/link discipline (`distill doctor --links`). See [`CHANGELOG.md`](CHANGELOG.md)._

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
ingest run on closed timelike curves and a later Microsoft Agent365 mixed-source
run: previewing the candidate pool, sizing the real run, approving spend,
watching costs accumulate across iterative preview cycles, seeing too little
live progress during long ingests, and noticing that site candidates and final
ingest selections were not always legible enough. The pieces shipped in 0.2.0
(preview cost-log differentiation, `--papers-only` / `--videos-only`,
`--top-by-date` for `latest`) closed the near-term gaps; the items below are the
deeper design questions that surfaced in those sessions and deserve their own
write-ups before implementation.

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
- [ ] **Page-level candidate identity for website-heavy discover runs.** In the
  Agent365 session, multiple official Microsoft pages previewed under the same
  collection label, which made it harder to decide what would actually be
  ingested. Preview rows for sites should show the real page title (or a
  synthesized title from URL + section), the hostname, freshness when known,
  and enough URL/section context that "approve this" is a meaningful action.
- [ ] **Trusted-site discovery for official-doc workflows.** The current
  `--site-seeds` support works, but it still makes the user curate every page
  manually. Add a constrained discovery mode where the user supplies trusted
  domains (for example `learn.microsoft.com`, `microsoft.com`) and Distill
  enumerates real candidate pages from TOCs, landing pages, sitemaps, and
  shallow section crawls before the goal-aware rerank. Keep this allowlist- and
  evidence-driven; this is not a license for arbitrary web search.
- [ ] **Long-run visibility and failure surfacing.** The Agent365 mixed-source
  run kept working but emitted very little live output after planning, forcing
  filesystem inspection to confirm progress. Long `discover` / `report` runs
  should show current phase, current item, completed/failed counts by source
  type, and explicit reasons when a source stalls or skips (for example
  transcript rate limiting, empty crawl, reuse of unchanged site insights).
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
- [ ] **Anti-AI-slop register guard** (0.9.0, companion to the register styles
  above). `prompts/shared.py` carries `ANTI_HALLUCINATION_RULES`,
  `PROVENANCE_RULES`, and a one-line `FORMATTING_RULES` (no em-dashes) — rules
  about *correctness*, not *prose register*. The human-read outputs (briefings,
  reports, the synthesis register styles) benefit from an explicit
  `REGISTER_RULES` constant grounded in the Wikipedia "signs of AI writing"
  list: no filler superlatives, no "delve / it's worth noting / in conclusion"
  scaffolding, consistent UK/US spelling, no hedge-stacking. Thread it into the
  synthesis/report/brief prompts. Anti-hallucination keeps the corpus correct;
  this keeps the prose publishable. Prompt-layer constant + wiring, no new
  dependency.
