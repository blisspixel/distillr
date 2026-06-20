# Full roadmap (detail)

> **No brittle junk.** Every item here is bound by the rule at the top of [`../ROADMAP.md`](../ROADMAP.md) and the charter [`design/agentic-balance.md`](design/agentic-balance.md): a decision is a deterministic **Rule** only when it is *structural or has ground truth*; any "is this good / faithful / on-topic / substantive / robust?" judgment is a **model** call (Python only aggregates per-criterion verdicts), and nothing gates on a deterministic quality/faithfulness/robustness *score*. If a backlog item below smells like a keyword/regex/length/cosine/threshold heuristic standing in for a semantic call, it is wrong as written - fix it to model-judged or cut it. We keep walking back into this trap; the rule exists to stop it.

The short public summary lives at [`../ROADMAP.md`](../ROADMAP.md). This file is the un-trimmed backlog with priority breakdowns by area - useful if you're considering contributing or want to see how something specific is prioritized.

Shipped work lives in [`CHANGELOG.md`](CHANGELOG.md) (the 0.1.0 entry covers the initial public release; the "Pre-release Development" section covers everything built before that).

## Current Direction

Distill is a source-to-intelligence platform with eight source types on one trust pipeline:

- YouTube for staying current on channels and topics
- Websites for vendor, lab, and research-corpus distillation
- arXiv papers, with query expansion, LLM rerank, full-PDF extraction, and cross-paper synthesis
- X posts via `distill ingest <tweet-url>`
- GitHub repos via `distill ingest <github-url>`
- Podcasts via RSS-first `distill ingest <feed-url>`
- Newsletters / feed posts via the same feed dispatcher
- Local files and media via `distill ingest <path>`

Current UX priorities:

- Make the website workflow feel first-class instead of command-by-command
- Keep the YouTube "stay current" path fast and obvious
- Goal-aware discovery as the front door when the user has a research goal rather than a keyword query
- Add OKF export/validation so verified corpora can move into other agent systems
- Make audit/gap/staleness output loop-readable so external agents can steward a corpus without scraping console prose
- Add recurring research profiles for ongoing topics such as AI developer news,
  live agentic dev, and vendor docs watch
- Add no-metered-cost routing so local inference and explicitly configured
  subscription-plan CLIs can be used without surprise API billing
- Continue the Obsidian-native living-wiki shape while keeping Distill's native corpus as the source of truth

## Next Up

The work ahead is ordered around the product's three core jobs:

1. Stay current on fast-moving topics
2. Learn a source set quickly
3. Build a reusable corpus for deeper reporting and agent workflows

The broader direction is for Distill to work well as the research-and-corpus layer
in multi-agent systems - a tool other agents can query via MCP to get grounded,
structured intelligence without duplicating ingestion work. The priorities below
build toward that: tighter outputs, cleaner handoffs, and interoperability with
orchestration layers.

The direction is **more agentic**, but not more self-certifying. Open-ended
judgment moves toward models: source fit, query expansion, analysis lensing,
synthesis planning, contradiction interpretation, and future deep-synthesis
loops. Structural and irreversible boundaries stay rule-owned: schemas, path
and URL safety, cost-mode refusal, action ids, exact commands, audit rollups,
approval class, receipts, and verifier stop conditions. Each backlog item
should be legible as one of three shapes:

- **Agentic judgment:** a model decides something semantic because rules would
  fake it.
- **Rule-owned structure:** Python validates something with ground truth or
  explicit configuration.
- **Judgment-then-rule:** a model returns per-criterion verdicts, then Python
  aggregates, thresholds, records, and gates.

That split is product direction, not implementation trivia. "More agentic" means
more model judgment where flexibility helps, plus tighter rule-owned boundaries
around writes, spend, ingestion, and completion.

**Competitive context (June 2026).** The "local-first LLM Wiki" space saturated
within weeks of Karpathy's April gist (35k-star official Obsidian skills, an
11k-star desktop wiki app); the vault-maintenance fight is not distillr's to win.
What stayed uncrowded - verified in a June 2026 primary-source sweep - is the
acquisition front-half (goal-aware multi-source discovery, transcript-grade
pipelines) and *verified* trust (claim grounding against receipts, contradiction
surfacing). The plain-files-over-RAG architecture itself is now
mainstream-endorsed (Anthropic, Letta's pivot, Karpathy). Google Cloud's Open
Knowledge Format makes Markdown + YAML-frontmatter interop a formal ecosystem
target, which moves Distill's advantage from "plain files" to "verified corpus
producer." The spine was reordered accordingly: agent legibility promoted out of
1.0 polish, the verify hook pulled forward to 0.10, breadth behind the trust
gate at 0.11, and OKF/loop-readiness before the 1.0 contract freeze. See
[`../ROADMAP.md#competitive-landscape-june-2026`](../ROADMAP.md#competitive-landscape-june-2026) for the full analysis.

Legend: `[ ]` not started, `[~]` partial / in progress, `[x]` shipped (item will
be moved to `CHANGELOG.md` on next release).

### 0. OKF interop and loop-ready stewardship

- [x] **OKF export.** Export `topic` or `all` into a conformant OKF v0.1 bundle with generated `index.md`, `log.md`, `type` frontmatter, standard Markdown links, citations, and provenance-preserving references back to receipts and verify sidecars. This is a read-only projection; the native `library/` layout remains authoritative. Shipped as `distill export <topic|all> --format okf`.
- [x] **OKF validation.** Validate any OKF bundle or Distill-generated export for parseable frontmatter, non-empty `type`, structurally valid reserved files, and link warnings. Follow OKF's permissive consumer posture: broken links warn, they do not invalidate the bundle. Shipped as `distill okf validate <path>`.
- [x] **Loop-readable next-action plans.** `distill audit <topic|all> --next-actions --json` emits bounded actions with ids, exact commands, approval class, write scope, loop metadata, and verifier/stop condition. The first shipped surface covers broken links, missing orientation, prompt staleness with routable sources, synthesis freshness, coverage gaps, missing corpus synthesis, diffs, and trends. This is rule-owned structure over existing findings, not a semantic priority scorer.
- [x] **No scheduler inside Distill.** Documented the contract for Codex, Claude Code, Grok Build, cron, GitHub Actions, and human operators: Distill emits state and safe commands; the external loop chooses what to run, where to run it, how to gate spend, and when to stop.
- [x] **Loop contract fixtures.** Added a small fixture set for next-action JSON so future changes cannot accidentally remove the fields external loops depend on.

### 0.19 Recurring research profiles and no-metered-cost routing

Design: [`design/recurring-profiles-cost-routing.md`](design/recurring-profiles-cost-routing.md).

- [x] **Research profile schema.** Store recurring source plans as versioned files: topic, goal file, trusted feeds including Substack-class newsletters, YouTube channels, domains, repos, queries, freshness policy, output preferences, and cost mode. Shipped as the pure `distill.library.profiles` parser and validator.
- [x] **Checked-in example profiles.** Ship `ai-developer-news`, `live-agentic-dev`, and `vendor-docs-watch` examples that use public sources, newsletter/feed sources such as Latent Space-class posts, and preview-only defaults.
- [x] **Fresh-source local mode documentation.** Make user-facing docs and agent instructions explicit that local Ollama/LM Studio analysis still starts from current fetched receipts, not stale model memory.
- [x] **Profile preview.** Add `distill profile preview <name>` to resolve candidate updates from feeds, YouTube channel Atom feeds, trusted domains, repos, and saved queries before analysis writes anything. Rules own fetch, parse, identity, freshness, caps, and no-metered refusal; models own source fit, novelty, rumor classification, and priority. If no eligible no-metered model route exists, preview returns labeled structural order rather than a fake keyword quality rank.
- [x] **Profile run.** `distill profile run <name>` plans approved preview commands, requires `--yes` before execution, runs the existing `distill ...` ingest and analysis paths, captures per-command exits, emits loop-readable next actions, writes resume state under `.distill/profiles/<profile>/run_state.json`, and surfaces local profile health in `distill audit all`. Exact feed items and YouTube videos complete once; standing seeds stay repeatable.
- [x] **No-metered-cost mode.** Add `DISTILL_COST_MODE=auto|no-metered|paid-ok` plus `--cost-mode`. Core config/router parsing, top-level CLI override, fail-closed refusal, no-metered profile replay commands, profile-run execution of those commands, zero-dollar route/provider ledger rows, and structured blocked-route reporting are wired: `no-metered` allows local Ollama/LM Studio and blocks API-billed, credit-metered, unproven plan-quota, or ambiguous routes before provider calls.
- [~] **Local and plan-quota routing.** Prefer deterministic work, local model servers, and explicitly configured plan-quota CLIs such as Codex CLI, Claude Code, Grok Build, Gemini CLI, and Antigravity when their adapter support statement is current and they pass `distill eval`. `distill doctor --adapters` now reports read-only binary/help/flag/env/config/auth-command readiness, structured support-statement details, the strict `adapter-workload.v1` input package contract, the strict `adapter-native-usage.v1` usage contract, the strict `adapter-result.v1` scratch manifest contract with quota-stop metadata, before/after scratch write checks, a scratch-only exact-argv runner primitive with shell disabled and API-key env stripping, a native result writer for captured CLI output plus explicit native usage metadata or a validated usage file, Codex and Claude capture writers, a generic stdout capture writer for adapters with separate native usage files, and a workload runner that can invoke post-process capture hooks before verifying manifest reads, writes, and cost mode against the package. Blocked Codex, Claude, Grok, Gemini, and Antigravity read-only command planners record future argv shapes plus staged prompt, schema, result capture, and native usage capture metadata, and Claude schema paths can be inlined from scratch JSON schema files. Gemini and Antigravity fail closed on `GOOGLE_API_KEY` as well as `GEMINI_API_KEY`. All planned support statements stay blocked because `no_metered_current` is false. GitHub Copilot CLI can be supported as an explicit credit-metered route, but it is not a no-metered default.
- [~] **Billing preflights.** Fail closed when route cost is ambiguous. Adapter doctor reports API-key environment blockers, local config API-key markers, and selected JSON auth-command markers for candidate plan-quota CLIs, including `ANTHROPIC_API_KEY` for Claude Code and `GOOGLE_API_KEY` for Gemini-family CLIs, and the workload, usage, and manifest boundaries reject unsafe scratch paths, no-metered results that carry metered auth, API-key blockers, missing usage signals, missing declared files, unexpected new scratch files, and workload result drift. Remaining: current official no-metered support statements, installed-session auth proof where no command or config proof exists, native usage collection and capture wiring for Grok, Gemini, and Antigravity, and eval graduation.
- [~] **Complete usage ledger.** Cost-log rows now record provider breakdowns, route-class breakdowns, no-metered call counts, local transcription counts, and zero-dollar `profile-run` orchestration rows. The future adapter manifest now has a strict `quota_stop` field for rate-limit and quota exhaustion, verified native usage files can feed manifest writing, Codex JSONL and Claude JSON usage can be normalized and written to scratch manifests from workload capture hooks, and verified manifests can be converted into included-plan cost-tracker rows. Remaining: adapter-specific native usage collection from real non-Codex workloads beyond Claude and eval-gated route integration.
- [x] **Loop handoff.** Emit profile-related next-action rows compatible with the 0.17 schema so external loops can steward recurring topics without scraping console output.

### 1. Make "Stay Current" a first-class workflow

- [~] Proactive freshness alerts after catch-up or scheduled refresh. CLI-native watch-alert digests persist to `library/watch_alerts.md`, and the same alert stream is exposed via MCP at `distill://watch-alerts`. Outbound channels (email, Slack) are still pending.
- [ ] Unified watch model that blends creator monitoring and topic discovery when needed, while keeping the distinction legible in the UX
- [~] Trend radar and evolution timelines so users can see trajectory over time, not just the latest snapshot

### 2. Build a real dashboard and cost surface

- [x] Shared dashboard data source for CLI and web. The CLI home dashboard now
  renders from `dashboard_snapshot()`, so terminal and web views share counts,
  spend rollups, topic changes, budget warnings, and corpus health warnings.
- [~] Projected next-run cost by workflow, not just historical spend
- [x] **Estimator calibration accountability** - shipped 0.12.3: estimate-of-record lands in `cost_log.jsonl`, and `distill costs` reports median absolute error, signed bias, and trend for comparable runs.
- [~] Rolling cost by topic and source type so users can see where spend is going
- [~] Surface stale corpora, failed runs, thin transcripts, and crawl drift in one place
- [~] Cost anomaly detection and budget guardrails per topic or workflow so expensive runs are predictable
- [~] Interactive library browser (TUI first or lightweight local web view) for scanning topics, channels, videos, pages, and artifacts at scale
- [x] Live mixed-source run progress so long `discover` / `report` / site-heavy jobs show current phase, current item, completed/failed counts, and where time is going without making the user inspect the filesystem. `papers`, `site-batch`, `discover` paper/site ingestion, and default `report` show phase/item/completed/failed/spend output, with ETA when enough items have completed. Video-backed loops used by `latest`, `catch-up`, and the video branch of `discover` print persistent per-video completed/failed/spend progress after each item and include spend in live phase labels. Global `--quiet` / `--verbose` output controls and recurring-workflow help examples are now wired.
- [x] **Preview-table rendering at narrow widths** - fixed 0.9.31 (stacked layout below 110 columns); detail in [`CHANGELOG.md`](CHANGELOG.md).
- [x] **Library `CLAUDE.md` source counts wrong for legacy-layout topics** - fixed 0.9.29: source counting covers modern, lowercase, and legacy insight patterns, skips derived subtrees, and no longer hides older corpora from the generated index.
- [x] **Per-prompt token telemetry.** Every LLM router call writes prompt-input length, output length, elapsed time, provider, workload, call type, run id, and outcome to `library/.distill/telemetry.jsonl`, keeping per-call telemetry separate from run-level `cost_log.jsonl`. `distill costs` and the local web costs page now surface a "biggest prompts" view so prompt budget regressions are visible before context-engineering changes such as chunked paper analysis or report-pipeline compaction ship.

### 3. Productize the core workflow

- [~] Make the command model more intent-first around staying current, learning fast, and reporting
- [~] Intent-first aliases or a lightweight wizard for recurring jobs such as monitor, ramp-up, and report
- [ ] Make source-set inputs feel first-class instead of relying on one-off command choreography
- [ ] **Zero-key tour / demo path** (from external QA 2026-06-11): a documented first-run that works before any API key - e.g. `--preview` against bundled example seeds plus the public example corpus from the proof-artifacts pass - so evaluation doesn't require setup. Constraint: no new verb (keep-surface-small); this is docs + bundled fixtures + existing flags, not a `demo` command.
- [ ] First-class research profiles for "prefer these channels + these trusted domains + this goal file" workflows so recurring analyst use cases (for example Microsoft-only research) do not require rebuilding the same command and seed setup by hand
- [ ] Clarify corpus outputs and how to inspect or export them for downstream use
- [~] Export / handoff presets for downstream agent roles and RAG pipelines (for example zipped MD/JSON bundles with clean metadata, confidence tags, and structured fields that consuming agents can act on without parsing prose)

### 4. Tighten the YouTube experience

- [ ] Live cost ticker during runs (estimated from token counts)
- [ ] Total content stats in discovery ("Found 88 videos + 12 Shorts, ~47 hours of content")
- [~] Research history - track how findings evolve over time, diff between runs
- [ ] Multi-pass escalation on demand so catch-up can stay cheap by default and selectively deepen only the highest-signal items
- [ ] Persist creator voice / bias cards so synthesis can account for recurring framing, reliability, and drift over time
- [x] Retry / backoff / resume-friendly subtitle handling - shipped 0.12.11: caption fetch retries transient failures with backoff (a clean download with no `.vtt` is permanent captionless, not retried), and captionless videos route through the local-first Whisper ladder (bestaudio download + `transcribe_media` with a title/uploader vocabulary hint) before the legacy scribe fallback; detail in [`CHANGELOG.md`](CHANGELOG.md).

### 5. Finish website productization

- [ ] Website UX polish - checked-in examples, cleaner crawl defaults, better attachment discovery, less one-off command choreography
- [ ] Trusted-site discovery for docs-heavy research workflows - given allowlisted domains (for example `learn.microsoft.com`, `microsoft.com`), enumerate candidate pages from TOCs, landing pages, sitemaps, and shallow section crawls before the LLM rerank so users do not have to hand-curate every page seed
- [ ] Better crawl boundary controls - keep site batches close to the intended section or branch by default
- [~] Attachment ingestion - inventory embedded PDFs/videos and optionally pull PDF text or supported embedded-video transcripts into website runs
- [ ] Mixed exact-page and shallow-crawl workflows that are easier to understand and safer by default
- [ ] Better website candidate identity in preview/approval flows - show page-level titles, URLs, section labels, and freshness hints instead of collapsing multiple seeds under one collection label
- [~] Section-aware freshness so website refreshes focus on changed branches instead of re-crawling everything

### 6. Papers as a first-class source type

- [ ] OpenAlex (CC0, free dumps) and/or Ai2 Asta Scientific Corpus MCP integration for recency + citation-weighted ranking signals beyond arXiv. (Previously scoped as Semantic Scholar + Google Scholar; the classic Semantic Scholar API has been changelog-silent since late 2024 with restrictive keys, so OpenAlex/Asta are the durable paths.)
- [ ] **Citation identity + export** (June 2026 panel, research-scientist finding): DOI in paper frontmatter where resolvable, and a BibTeX/RIS export so insights can reach a bibliography - "without a path into Zotero, every insight file is a cul-de-sac." Cheap relative to its adoption impact in academic labs.
- [ ] **PubMed / bioRxiv / medRxiv adapters** (same finding): arXiv-only excludes life-sciences labs entirely. Post-0.11 candidates on the adapter contract; OpenAlex metadata (above) is the shared discovery layer.
- [ ] **Chunk-and-rerank paper analysis (effective-context-aware).** Today the full PDF (truncated at 100K chars) is dumped into a single Grok prompt, which is exactly the "Dump Truck" anti-pattern that LongBench v2 / RULER / ∞Bench / STRING benchmarks show degrades sharply when relevant evidence sits mid-document. Replace with: section-aware chunker (use PDF headings; fall back to page+window slicing); per-category rerank ("which chunks matter for *Methods*, *Limits*, *Open Questions*?"); small-window analysis loop assembling `<paper-slug>_Insights.md` from focused passes. Outcome: better fidelity on long papers without higher token spend; per-prompt token counts as a first-class telemetry surface.
- [ ] **Lift the 100K char cap once chunking is in place.** The cap was a defensive band-aid for the dump-truck pattern; once analysis runs over chunks, full long papers can be processed without prompt blowups.

### 7. Strengthen corpus quality and reuse

- [x] Stale detection - shipped 0.12.2: the prompt-version registry + per-topic staleness rollup in the audit (current / stale / no-provenance / unknown-family); detail in [`CHANGELOG.md`](CHANGELOG.md).
- [x] Auto-reanalysis trigger - shipped 0.12.6: the audit action menu prints per-artifact re-analysis commands resolved from each stale artifact's frontmatter (spend printed, never auto-run); detail in [`CHANGELOG.md`](CHANGELOG.md).
- [x] Synthesis stale-flag - shipped 0.12.8: source-relative freshness (synthesis older than the sources it synthesizes, shadowed legacy syntheses) in the audit, the dashboard health list, and the generated CLAUDE.md/AGENTS.md; detail in [`CHANGELOG.md`](CHANGELOG.md).
- [x] Library-level hygiene rollup - shipped 0.12.12: `distill audit all` writes `Library_Audit.md` at the library root (empty / unreadable / orientation-less directories as findings, test-suggesting names informationally) plus a one-line console rollup; detail in [`CHANGELOG.md`](CHANGELOG.md).
- [x] Duplicate detection - exact YouTube identity groups now ship in `distill audit` so same-source videos filed under multiple slugs are flagged without semantic scoring; detail in [`CHANGELOG.md`](CHANGELOG.md).
- [x] Semantic deduplication - shipped 0.12.4 (shingle-Jaccard near-duplicate groups in the audit, artifact-preserving, embedding-free); detail in [`CHANGELOG.md`](CHANGELOG.md).
- [~] Insights quality check - **NOT a heuristic quality score.** "Is this analysis good / substantive?" is a semantic judgment and belongs to the verify/eval model judges (faithfulness + coverage against the source), never to a section-presence + length heuristic (that brittle proxy fails good paraphrase and rewards padding - see [`design/agentic-balance.md`](design/agentic-balance.md)). The only deterministic part allowed here is a *structural* sanity tripwire (did the writer emit the required frontmatter / a parseable artifact at all), surfaced advisory in `distill audit`, not a quality gate.
- [~] Transcript validation - flag suspiciously short transcripts (<500 chars for a 30-minute video) as likely failed captions. (Legitimate structural check: this catches a *technical capture failure* by length-vs-duration, not a content-quality judgment - keep it, advisory.)
- [ ] Structured logging - proper log levels, log to file for post-run review, debug mode flag
- [x] **`distill audit`** - shipped 0.10.2 with the verify-sidecar coverage rollup, report artifact, and spend-safe action menu; grown through 0.12.x (staleness, near-duplicates, re-analysis commands); scheduling recipes shipped 0.12.1. Detail in [`CHANGELOG.md`](CHANGELOG.md).
- [x] **Output->input loop (`distill ask`)** - shipped 0.12.0 with strict-by-definition `--save` promotion and the MCP `ask` tool; design in [`design/ask-loop.md`](design/ask-loop.md), detail in [`CHANGELOG.md`](CHANGELOG.md).

### 8. Expand cross-source intelligence

- [~] Mixed-source topic synthesis that treats YouTube, websites, and papers as one corpus. `distill corpus` is live, MCP exposes `distill://topics/{topic}/corpus` and `distill://topics/{topic}/sources`, and `resynthesize_topic` refreshes corpus synthesis; near-duplicate detection shipped 0.12.4 (audit-surfaced), deeper cross-source reasoning still pending.
- [ ] Trusted-domain website discovery inside `discover` - let the app expand "prefer Microsoft docs / vendor docs / official learn pages" into real page candidates from allowlisted domains, then rerank those page candidates with videos/papers in the same pool
- [x] Goal-file watch hook - shipped 0.12.7: goal-driven discover runs persist their goal<->topic association (`.distill/goals.json`, goal text + file + seeds), and `catch-up` surfaces each topic's exact `--preview` refresh command on the cadence; spend surfaced, never auto-committed. Detail in [`CHANGELOG.md`](CHANGELOG.md).
- [ ] Multi-topic channels - same channel filed under multiple topics with shared transcripts
- [~] More source types - podcasts and feed/newsletter ingestion shipped in 0.11; conference talks and additional community adapters move behind the post-1.0 plugin boundary unless a dogfooded need promotes one.

### 9. Ongoing operation and access

- [x] Scheduled refresh + scheduled audit - recipes shipped 0.12.1 (`docs/usage.md` "Running on a schedule": Task Scheduler + cron lines for `catch-up`, `audit all --report-only`, gap-fill previews); the scheduler stays external by design. Remaining: the goal-file refresh hook for `distill watch` (see §8).
- [ ] Native notification integrations for daily briefings, weekly digests, and important-change alerts
- [ ] Web UI - browse the library, read insights, compare channels in a browser

### 9b. Engineering foundation - reproducible toolchain and quality gates

The build harness, not the corpus. The adopted/adapted/declined rationale lives in [`../ROADMAP.md`](../ROADMAP.md#engineering-standards-adopted-adapted-declined); the shipped toolchain releases (0.8.3 and the harden series) are in [`CHANGELOG.md`](CHANGELOG.md). This is the itemized backlog of what remains.

- [x] **Hypothesis deadline flakes under load** -- diagnosed and fixed 0.12.0: three full-suite runs each dropped a *different* property test that passed in isolation (llm migration/telemetry batch, ollama passthrough, paths/agent) with `DeadlineExceeded`; root cause was Hypothesis's 200ms wall-clock per-example deadline firing under coverage instrumentation on a loaded machine. Suite-wide `deadline=None` profile in `tests/conftest.py` (these suites test correctness, not latency). Residual watch item: if non-deadline order-dependent failures ever appear, suspect `load_dotenv` env leakage from CLI-invoking tests.
- [x] **Finish the `_logic.py` decomposition, with removal criteria**. `distill/commands/_logic.py` was the center of gravity - one ~9k-line module holding the full implementation of every CLI command, with `_cli_impl` as a compatibility alias. External code QA (2026-06-11) called it the largest maintainability risk visible from the code surface, and it was the original 0.7 code-health item. Twenty-two command modules and paper/site/concept/version/display/video/learning/discover support helpers are now out, the root callback and concepts app construction live in owned command modules, private compatibility exports live in `distill._cli_impl`, and `distill/commands/_logic.py` is deleted. No production command module imports the monolith, no command sub-apps remain inside, and the module-size allowlist is empty. Per-slice plan and history: [`docs/design/logic-decomposition.md`](design/logic-decomposition.md).
- [~] **Branch coverage ratchet** (0.8.3 → 1.0) - `[tool.coverage.run] branch = true`, `--cov-fail-under` set to the measured branch baseline (floor 79) and ratcheted up-only toward the 1.0 flat ≥95% gate.
- [ ] **Full Pyright-strict ratchet** (1.0) - complete the per-package climb 0.8.3 begins (`distill/llm/` already strict-blocking); no `# type: ignore` without an inline reason.
- [ ] **Parse, don't validate - strict domain types at every boundary** (1.0) - parse every external input (MCP tool arguments, frontmatter, adapter/local-file ingest, LLM structured outputs) once at the boundary into a rich domain type (`strict=True, extra='forbid'` Pydantic model, `NewType`, or frozen dataclass); core logic never sees raw primitives.
- [ ] **Verification depth on the deterministic core** (1.0, "formally contracted where it matters") - Design by Contract via `deal` on the merge/normalize/recovery invariants (idempotent + order-independent merge, round-tripping rollback, non-inverting intervals; `deal` also generates Hypothesis tests from the contracts); mutation testing (`mutmut`) of `concepts/` + `library/` + `llm/retry` on a cadence to prove test efficacy; a Hypothesis state machine over the playbook lifecycle (append -> merge -> notes -> snapshot -> rollback -> re-merge); and fault-injection at the external boundaries (malformed LLM JSON, truncated transcripts, network/yt-dlp failures) proving clean degradation and that no-silent-error-swallowing holds under turbulence. Scoped to the pure-Python core + boundaries, not blanket. distillr's concurrency is asyncio IO, so the discipline is async-safety, not free-threaded shared-memory rules.

### 10. Living Wiki Corpus (Obsidian-native, LLM-maintained)

Distill's corpus is already a directory of plain-text markdown artifacts with
structured frontmatter. Two convergent signals push toward treating that directory
as a *living wiki* rather than a filing cabinet:

- Obsidian (and the broader markdown-vault ecosystem: Logseq, Dendron, Foam) gives users a free graph view, backlink panel, and fuzzy search the moment the corpus uses `[[wiki-style links]]` and consistent frontmatter.
- Karpathy's early-April-2026 "LLM Wiki" pattern shows that an LLM agent curating a concept-indexed markdown knowledge base produces something qualitatively different from one-shot RAG: knowledge that compounds across ingestion runs rather than evaporating after each session.

The goal is for the corpus to be interoperable, compounding, and self-maintaining,
without locking users into any particular viewer or requiring bespoke tooling.

**Core shipped.** The Obsidian-native output layer shipped before the concept
playbook. The LLM-maintained concept/entity layer shipped in 0.8 with recovery
surfaces and JSONL rollups. Remaining work is no longer "create the concept
layer"; it is interoperability, scale, and better semantic resolution.

*Tier 1 - Obsidian-native output (low-effort, immediate ecosystem lift)*

_All four Tier-1 items shipped - wiki-style cross-linking, standardized YAML frontmatter, `distill open --vault`, and stable slug/link discipline (`distill doctor --links`). See [`CHANGELOG.md`](CHANGELOG.md)._

*Tier 2 - LLM-maintained concept layer (Karpathy + ACE)*

This tier follows the Agentic Context Engineering (ACE) framework's
architectural choice: concept notes are evolving structured *playbooks*, not
prose summaries. ACE empirically outperforms compressed-summary approaches
(Dynamic Cheatsheet, GEPA) on agent benchmarks specifically because itemized
deltas avoid the *context-collapse* failure mode (the documented case where
an 18K-token playbook compressed to 122 tokens lost most of its recall).

- [x] Concept extraction pass - shipped 0.8: per-insight LLM extraction, append-only `mentions.jsonl`, deterministic thresholded grouping, playbook notes under `concepts/`, and provenance fields.
- [x] Entity notes - shipped 0.8: people, vendors, organizations, datasets, and other entity-like concepts route to `entities/` with the same evidence model.
- [x] Intelligent merging on refresh - shipped 0.8: pure-Python deterministic merge, idempotent rewrites, `.history/` snapshots, and `concepts log/diff/rollback`.
- [x] Contradiction flagging - shipped 0.8: contested concepts/entities surface from helpful and harmful evidence and are visible in health/audit-facing surfaces.
- [x] Concept/entity graph export - shipped 0.8: `concepts.jsonl` and `entities.jsonl` rollups for downstream agent and programmatic consumption.
- [x] Local file ingest - shipped 0.9: `distill ingest <path>` handles PDF, Markdown, text, clipped HTML, and later local media through the same verified pipeline.
- [ ] Semantic alias resolution over `mentions.jsonl`: model-assisted grouping for cases mechanical normalization cannot safely resolve, with Python only owning graph assembly and invariant checks.
- [ ] OKF projection of concept/entity playbooks: exported concept docs should be conformant OKF concepts without weakening Distill's richer native frontmatter.

*Tier 3 - explicitly not in scope*

- Building a graph-view UI inside distill. The Obsidian/Logseq/Dendron graph views are already good; reimplementing would duplicate effort without adding value.
- A distill-proprietary editor, mobile app, or cloud-hosted wiki service. The whole point is plain-text markdown with no lock-in.
- Replacing the existing hierarchical folder layout. Obsidian works fine with subfolders; concept and entity notes layer on top of the existing structure rather than replacing it.

*Why this belongs on the roadmap*

The Obsidian + LLM-Wiki direction fits what distill already produces. Tier 1 is
mostly prompt and frontmatter edits - interop with an ecosystem that already solves
visualization. Tier 2 is where distill shifts from processing sources in batches to
maintaining a navigable knowledge base - the difference between "100 markdown files
about TKGs" and "a TKG concept note that cites every relevant source I've ingested,
updates on refresh, and flags when a new paper contradicts prior findings." The
ingestion, synthesis, and per-source provenance layers needed for that already
exist; the missing pieces are cross-linking conventions and a concept-extraction
pass.

### 11. Context engineering hardening

The 2025-2026 context-engineering literature (Mei et al.'s 1,400-paper survey;
Anthropic's compaction guidance; the ACE framework on evolving playbooks;
Vishnyakova's production-grade context-engineering criteria) makes three
empirical points distillr should act on: claimed context windows are not
effective windows, lost-in-the-middle dominates failures on long inputs, and
JSON handoffs strip semantic richness in ways that compound across phases.
Items below are concrete plumbing work that protects output quality and
controls token spend as the corpus grows. See [`architecture.md#context-engineering-principles`](architecture.md#context-engineering-principles)
for the principles these items derive from.

- [~] **Just-in-time MCP context (paths-not-payloads)** - *promoted into the agent-legible 0.9 pass (see `../ROADMAP.md`); current status: `find_insights` (ranked path/preview/score) + `read_insight(path, section?)` are shipped and the default shape; `list_contested` is folded into `find_concepts(contested_only=True)`; the live surface is 24 tools; remaining work is collapsing overlapping action tools.* Today `distill-mcp` returns full markdown files; a 50KB synthesis artifact blows the consuming agent's window for what may be a one-line lookup. Anthropic's published example reduced a comparable workflow from ~150K to ~2K tokens (98.7% saving) by switching tool returns from raw payloads to structured summaries plus paths. Add `find_insights(topic, query)` returning ranked `(path, one_line_preview, score)` tuples; add `read_insight(path, section?)` for drill-down. Existing tools that return full bodies stay (for explicit "give me the file" calls) but stop being the default response shape. At ~500-1,000 schema tokens per always-loaded tool, the consolidation matters as much as the response shape.
- [ ] **Compaction in the 4-phase report pipeline.** Phase 2 (section writing) and Phase 4 (QA) currently carry full prior-section context forward to enforce no-repeat. Switch to high-recall-then-precision compaction (the Anthropic pattern) and OpenAI-style opaque continuation items where the API supports them. Goal: significant token-spend reduction on long reports with no loss of cross-section coherence. Measure via the per-prompt token telemetry from section 2.
- [ ] **Effective-context regression tests.** Add a small fixture suite that runs paper-analysis / synthesis / report prompts against representative long inputs and asserts the output covers known mid-document evidence (a "lost-in-the-middle" smoke test). Wire into CI so regressions surface in PRs rather than user reports.
- [ ] **Tool-result clearing in iterative loops.** Long-running watch and discover loops accumulate tool-call results that are no longer relevant. Implement Anthropic's "clear stale tool results" pattern as a baseline compaction step before each new LLM call in those loops.
- [x] **Document the principles in the contributor guide.** `docs/CONTRIBUTING.md` now names the context-engineering rules for prompt, MCP, report, pipeline, and loop changes: paths before payloads, provenance in context, prompt-budget measurement through biggest-prompts telemetry, evidence-preserving compaction, structured deltas, stale intermediate-context clearing, and model-owned semantic judgment.

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

_Shipped from this section (detail in [`CHANGELOG.md`](CHANGELOG.md)): rerank
determinism / commit-by-ID + corpus-aware dedup (0.9.27 and prior); per-source
rigor calibration with the `--rigor` knob; the metadata-aware self-calibrating
cost estimator; preview-as-default sizing; synthesis register styles with PhD
default; the anti-AI-slop register guard._

- [~] **Page-level candidate identity for website-heavy discover runs.** Partly
  shipped: preview rows for site seeds now show the seed label or a
  host+path-derived title plus the hostname (`_site_candidate_title`).
  Remaining: freshness hints and section context when known.
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
