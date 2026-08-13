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
- Track the final MCP 2026-07-28 spec and run a near-term compatibility spike
  while Distill's 1.0 MCP surface remains a candidate
- Keep the candidate CLI, MCP, library, frontmatter, OKF, next-action, and
  profile contracts open to evidence-backed refinement after that checkpoint
- Finish the Pyright strict-mode, boundary-type, and deterministic-core
  verification ratchets while preserving the branch-coverage floor
- Continue the Obsidian-native living-wiki shape while keeping Distill's native corpus as the source of truth
- Publish the 1.0 performance baseline and optimize measured whole workflows
  before considering first-party native code
- Complete the 1.0 presentation and contributor-onboarding pass

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
gate at 0.11, and OKF/loop-readiness before any future stability commitment. See
[`../ROADMAP.md#competitive-landscape-june-2026`](../ROADMAP.md#competitive-landscape-june-2026) for the full analysis.

Legend: `[ ]` not started, `[~]` partial / in progress, `[x]` shipped (item will
be moved to `CHANGELOG.md` on next release).

### 0. OKF interop and loop-ready stewardship

- [x] **OKF export.** Export `topic` or `all` into a conformant OKF v0.2 bundle with generated `index.md`, date-grouped `log.md`, standard `generated` and `sources` frontmatter, receipt copies, Markdown links, lifecycle fields, and truthful verification projection. Clean sidecars become `verified` only when they have usable coverage and bind to the exact artifact digest; flagged, invalid, incomplete, and stale sidecars remain audit receipts without elevating trust. This is a read-only projection; the native `library/` layout remains authoritative. Shipped as `distill export <topic|all> --format okf`.
- [x] **OKF validation.** Validate any OKF bundle or Distill-generated export for parseable frontmatter, non-empty `type`, v0.2 provenance/trust/lifecycle family shapes, Attested Computation runtime, reserved-file structure, and link warnings. Follow OKF's permissive consumer posture: missing optional fields and broken links warn, they do not invalidate the bundle. Shipped as `distill okf validate <path>`.
- [x] **Interop baselines and portable package boundary.** Track Agent Plugins 1.0.0 Working Draft, the current Agent Skills specification, and OKF v0.2 against authoritative sources in one maintained standards document. Release a strict Agent Plugins archive separately from the universal client-compatibility bundle, validate its manifest offline against the immutable canonical schema, and keep MCP activation outside the skill package.
- [x] **Loop-readable next-action plans.** `distill audit <topic|all> --next-actions --json` emits bounded actions with ids, exact commands, approval class, write scope, loop metadata, and verifier/stop condition. The first shipped surface covers broken links, missing orientation, prompt staleness with routable sources, synthesis freshness, coverage gaps, missing corpus synthesis, diffs, and trends. This is rule-owned structure over existing findings, not a semantic priority scorer.
- [x] **No scheduler inside Distill.** Documented the contract for Codex, Claude Code, Grok Build, cron, GitHub Actions, and human operators: Distill emits state and safe commands; the external loop chooses what to run, where to run it, how to gate spend, and when to stop.
- [x] **Loop contract fixtures.** Added a small fixture set for next-action JSON so future changes cannot accidentally remove the fields external loops depend on.

### 0a. Report profiles and document-level quality

- [x] **One report facade with explicit profiles.** `distill report` defaults to
  `corpus-report`, which writes from existing syntheses, insights, and receipt
  paths without mandatory Gemini spend. `accordion` adds a Gemini Deep Research
  dossier before the same ordered writer, and `deep-research` preserves the
  single-provider path. Profile-aware estimates run before provider work and
  price a proven local writer at zero direct API cost.
- [x] **Sequential report spine.** One-section writing, retry and refusal,
  progress, batch policy, full-document review, and ordered rewrites are
  separate functions. Section writing remains sequential by design, carries
  recent-section context, and stops after three consecutive failures.
- [x] **Post-assembly quality and structural refusal.** QA reviews the complete
  document for contradictions, near duplicates, source independence, and
  terminology drift. Failed sections are rewritten in order with full-report
  context, then reassembled. A final structural audit refuses unresolved
  numbered citations and missing, duplicated, or reordered headings.
- [x] **Versioned section data.** Section copy lives in strict versioned JSON.
  Typed Python owns schema validation, profile selection, and scope rules.
- [ ] **Bounded ingest concurrency remains forward work.** Current paper and
  video batch loops remain sequential. The first safe fan-out must isolate
  per-item writes and progress, serialize shared state, and make budget
  authorization atomic before concurrent model calls. Report chapters are not
  a concurrency target.

### 0b. MCP 2026-07-28 compatibility spike

- [x] **Pre-final SDK containment.** Bound production installs to
  `mcp>=1.27.2,<2` so the breaking SDK v2 line cannot enter fresh installs
  before the final-spec compatibility spike explicitly graduates it. The lock,
  wheel metadata, and package-metadata regression test carry the same boundary.
- [x] **Freeze-ready 1.0 public contract snapshots (covered surfaces).**
  Deterministic snapshots cover the full CLI tree, MCP tools/resources/prompts,
  artifact filename and base frontmatter contracts, core config, and core state
  schemas. Status is `freeze-ready` after the MCP 2026-07-28 checkpoint (0.19.48).
  Compatibility policy: [`contracts/COMPATIBILITY.md`](contracts/COMPATIBILITY.md).
  Remaining uncovered slices (router env surface, artifact-specific schemas,
  full legacy migration automation) stay separate and may expand additively.
- [x] **MCP 2026-07-28 compatibility spike (inventory + phase 1).** Completed
  against the final published spec; the decision record is
  [`design/mcp-2026-07-28-adoption.md`](design/mcp-2026-07-28-adoption.md).
  Findings: Distill uses no removed or deprecated protocol feature (no
  handshake or session dependence, no roots/sampling/logging/elicitation),
  `server/discover` and cache metadata are SDK-owned and arrive with the v2
  port, tool schemas are already Draft 2020-12 without external `$ref`
  dereferencing, MCP Apps is classified as dashboard/review-flow exploration
  rather than 1.0 scope, and the Tasks extension is the right shape for the
  long-running ingest and report tools once the stable SDK exposes it.
  Shipped alongside the inventory: complete tool behavior hints held to the
  `write_tool` registry by regression tests, a frozen deterministic
  `tools/list` order, distillr-version server identity, a docs tool-count
  drift guard, and tests moved off private SDK internals onto the public
  listing API.
- [x] **SDK v2 graduation (phase 2).** Shipped in 0.19.48: the dependency
  is `mcp>=2.0.0,<3`, `distill/mcp/server.py` runs on
  `mcp.server.mcpserver.MCPServer` with the telemetry seam, guardrails,
  sorted listings, first-class server version, and deliberate cache hints
  (static listings and `server/discover` fresh one hour at private scope;
  `resources/read` uncached so corpus reads stay fresh). Dual-era operation
  proven over real Windows stdio: a modern client negotiates 2026-07-28
  through `server/discover` with cache metadata, and a genuine v1.28.1
  client completes the legacy initialize handshake. The MCP contract
  snapshot was byte-identical across the SDK swap, the OpenTelemetry
  dependency is api-only with no exporter (no-op, no egress), and the CLI
  startup path never imports the SDK. Evidence in the design doc.
- [ ] **Tasks extension for long-running tools (phase 3).** After the v2
  port: advertise `io.modelcontextprotocol/tasks`, return durable task
  handles only to clients that declare the capability, persist the task
  registry under `library/.distill/`, and surface budget and read-only
  refusals as structured task failures. Blocked on stable SDK support for
  the extension; tracked in the design doc.
- [x] **MCP surface refinement debt (0.19.47 bug-hunt pass; closed in 0.19.48).**
  Absolute host paths no longer leave the MCP surface: `okf_export` returns
  workspace-relative `output/okf-*` paths, `doctor` reports the library root
  as `.` and `yt-dlp` by basename only, and incomplete cost-history messages
  use library-relative ledger labels (tools and `distill://costs`).
  `DISTILL_MCP_INGEST_ALLOWLIST` now also re-checks stored watch URLs on
  `catch_up`, while docs and the gate docstring state the intentional scope:
  URL entry points plus stored-URL refresh, not query-shaped open-world
  discovery (`discover`, `papers`, `learn_topic`, `search_videos`).

### 0.19 Recurring research profiles and no-metered-cost routing

Design: [`design/recurring-profiles-cost-routing.md`](design/recurring-profiles-cost-routing.md).

- [x] **Research profile schema.** Store recurring source plans as versioned files: topic, goal file, trusted feeds including Substack-class newsletters, YouTube channels, domains, repos, queries, freshness policy, output preferences, and cost mode. Shipped as the pure `distill.library.profiles` parser and validator.
- [x] **Checked-in example profiles.** Ship `ai-developer-news`, `live-agentic-dev`, and `vendor-docs-watch` examples that use public sources, newsletter/feed sources such as Latent Space-class posts, and preview-only defaults.
- [x] **Fresh-source local mode documentation.** Make user-facing docs and agent instructions explicit that local Ollama/LM Studio analysis still starts from current fetched receipts, not stale model memory.
- [x] **Profile preview.** Add `distill profile preview <name>` to resolve candidate updates from feeds, YouTube channel Atom feeds, trusted domains, repos, and saved queries before analysis writes anything. Rules own fetch, parse, identity, freshness, caps, and no-metered refusal; models own source fit, novelty, rumor classification, and priority. If no eligible no-metered model route exists, preview returns labeled structural order rather than a fake keyword quality rank.
- [x] **Profile run.** `distill profile run <name>` plans approved preview commands, requires `--yes` before execution, runs the existing `distill ...` ingest and analysis paths, captures per-command exits, emits loop-readable next actions, writes resume state under `.distill/profiles/<profile>/run_state.json`, and surfaces local profile health in `distill audit all`. Exact feed items and YouTube videos complete once; standing seeds stay repeatable.
- [x] **No-metered-cost mode.** Add `DISTILL_COST_MODE=auto|no-metered|paid-ok` plus `--cost-mode`. Core config/router parsing, top-level CLI override, fail-closed refusal, no-metered profile replay commands, profile-run execution of those commands, zero-dollar route/provider ledger rows, and structured blocked-route reporting are wired: `no-metered` allows local Ollama/LM Studio and blocks API-billed, credit-metered, unproven plan-quota, or ambiguous routes before provider calls. `distill doctor` now reports the active cost mode and warns when `auto` mode has metered API keys configured, without exposing key values.
- [~] **Local and plan-quota routing.** Prefer deterministic work, local model servers, and explicitly configured plan-quota CLIs such as Codex CLI, Claude Code, Grok Build, Gemini CLI, and Antigravity when their adapter support statement is current and they pass `distill eval`. `distill doctor --json` now emits portable local route availability for Ollama and LM Studio, and route pools can require live availability proof for local routes as well as included-plan adapters. `distill doctor --adapters` now reports read-only binary/help/flag/env/config/auth-command readiness, structured support-statement details checked against current 2026-06-30 vendor docs, the strict `adapter-workload.v1` input package contract, the strict `adapter-native-usage.v1` usage contract, the strict `adapter-result.v1` scratch manifest contract with quota-stop metadata, before/after scratch write checks, a scratch-only exact-argv runner primitive with shell disabled and API-key env stripping, a native result writer for captured CLI output plus explicit native usage metadata or a validated usage file, Codex, Claude, Grok, Gemini CLI, and Antigravity capture writers, a generic stdout capture writer for adapters with separate native usage files, and a workload runner that can invoke post-process capture hooks before verifying manifest reads, writes, and cost mode against the package. Blocked Codex, Claude, Grok, Gemini, and Antigravity read-only command planners record future argv shapes plus staged prompt, schema, result capture, and native usage capture metadata, Claude schema paths can be inlined from scratch JSON schema files, and Antigravity now probes the current `agy` CLI plus the `~/.gemini/antigravity-cli/settings.json` config path. Gemini and Antigravity fail closed on `GOOGLE_API_KEY` as well as `GEMINI_API_KEY`. All planned support statements stay blocked because `no_metered_current` is false. GitHub Copilot CLI can be supported as an explicit credit-metered route, but it is not a no-metered default.
- [~] **Billing preflights.** Fail closed when route cost is ambiguous. Adapter doctor reports metered environment blockers, local config markers, and selected JSON auth-command markers for candidate plan-quota CLIs, including API-key, gateway, cloud-provider, and credential-backed routes such as `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_USE_VERTEX`, `GOOGLE_API_KEY`, and `GOOGLE_APPLICATION_CREDENTIALS`, plus required support-statement evidence for paid-credit, overage, gateway, or API-backed route refusal, and the workload, usage, and manifest boundaries reject unsafe scratch paths, no-metered results that carry metered auth, API-key blockers, metered-route blockers, missing usage signals, missing declared files, unexpected new scratch files, and workload result drift. Native usage collection and capture wiring for Grok, Gemini, and Antigravity completed (parsers, capture writers, runner defaults + tests). `distill.eval.graduation` now combines adapter doctor readiness with model-judged eval evidence and fails closed on missing judge signal, unfaithful output, errored fixtures, weaker faithfulness than the anchor, missing no-metered proof, credit-metered routes, and missing live adapter analyzers. `distill.eval.route_pool` now consumes those graduation decisions for pure route-pool admission, so unproven plan-quota adapters cannot enter a selected pool. Doctor check coverage now locks retired-model warnings, provider key validation paths, Ollama fallback behavior, and LM Studio reachability outcomes. Adapter command-plan coverage now locks ready probes, uninstalled-probe blocker de-duplication, scratch-write blockers, missing-schema blockers, schema inlining, invalid schema files, marker-missing schema insertion, and Codex, Claude, Grok, Gemini, and Antigravity blocked-plan boundaries. Remaining: installed-session auth proof where no command or config proof exists; live workload integration for graduated adapter routes; and adapter-specific machine checks for provider overage settings when those CLIs expose them locally.
- [~] **Complete usage ledger.** Cost-log rows now record provider breakdowns, route-class breakdowns, no-metered call counts, local transcription counts, and zero-dollar `profile-run` orchestration rows. The adapter manifest contract has a strict `quota_stop` field for rate-limit and quota exhaustion, verified native usage files can feed manifest writing, Codex JSONL and Claude JSON usage can be normalized and written to scratch manifests from workload capture hooks, and verified manifests can be converted into included-plan cost-tracker rows. Adapter-specific native usage parsing and capture for Grok, Gemini, and Antigravity output shapes are wired, with strict rejection of boolean or non-integer token counts on Gemini-family usage fields. Route-pool admission now carries allowed and blocked entries as a loop-readable ledger, and `distill.eval.route_availability` normalizes local service status, installed local models, portable quota windows, stale evidence, and manifest quota stops so a selected pool can evict exhausted routes. Portable `route-availability.v1` snapshots reject account-bearing quota metadata, and focused boundary tests now cover open signals, missing-model local evidence, no-quota manifests, JSON loading, nested identity metadata, and invalid quota rows. Remaining: wiring live workload manifests and optional external quota snapshots into route availability signals during orchestration.
- [x] **Provider caching research.** Provider-side prompt and context caching policy is documented in [`design/provider-caching.md`](design/provider-caching.md). The gate is provider-specific, cost-mode aware, and lifecycle-bound: cache writes, storage TTL, retention policy, cached-token telemetry, rate-limit behavior, and cleanup semantics differ across Anthropic, OpenAI, Azure OpenAI in Microsoft Foundry, Gemini, Bedrock, and xAI. Provider cache discounts do not make a route no-metered, and local durable intermediate caches stay separate from opaque provider caches.
- [x] **Loop handoff.** Emit profile-related next-action rows compatible with the 0.17 schema so external loops can steward recurring topics without scraping console output.

### 1. Make "Stay Current" a first-class workflow

- [~] Proactive freshness alerts after catch-up or scheduled refresh. CLI-native watch-alert digests persist to `library/watch_alerts.md`, and the same alert stream is exposed via MCP at `distill://watch-alerts`. Outbound channels (email, Slack) are still pending.
- [ ] Unified watch model that blends creator monitoring and topic discovery when needed, while keeping the distinction legible in the UX
- [~] Trend radar and evolution timelines so users can see trajectory over time, not just the latest snapshot

### 2. Build a real dashboard and cost surface

- [x] Shared dashboard data source for CLI and web. The CLI home dashboard now
  renders from `dashboard_snapshot()`, so terminal and web views share counts,
  spend rollups, topic changes, budget warnings, and corpus health warnings.
- [~] Projected next-run cost by workflow, not just historical spend.
  `distill eval` now refuses before model execution when its fixture-aware
  estimate exceeds the configured `eval` workflow cap. Saved preview replay and
  freshly ranked `distill discover` ingest plans now refuse before ingest when
  their projected ingest estimate exceeds the configured `discover` cap.
  `distill report` now refuses on a profile-aware projection before its first
  provider call. The default corpus profile prices its resolved writer route;
  accordion prices Gemini Deep Research plus ordered writing and QA; the
  deep-research profile prices one Gemini job. `distill research-brief` still
  refuses before its Gemini Deep Research call. `distill ask` now refuses
  after corpus retrieval but before
  the QA model call when the bounded excerpt projection exceeds the configured
  `ask` cap, while no-coverage asks remain free. `distill site` and
  `distill site-batch` now refuse before model preflight when the resolved
  max-page, synthesis, and optional report-tail projection exceeds the
  configured workflow cap, while preview and scrape-only paths remain free.
  `distill paper` now refuses before model preflight when one full-PDF analysis
  plus the known synthesis tail exceeds the configured `paper` cap.
  Non-preview `distill papers` now refuses before model preflight when the
  requested limit upper bound exceeds the configured `papers` cap, then
  re-checks after search, dedup, rerank, and preview selection but before
  full-PDF analysis using the selected-paper analysis plus known synthesis tail.
  `distill video`,
  `distill channel`, `distill catch-up`,
  `distill reanalyze`, and `distill resynthesize` now refuse before known
  video-analysis or synthesis model work when the projected workflow spend
  exceeds the configured cap. `distill corpus` now refuses before model
  preflight when corpus source sections exist and the known single synthesis
  call exceeds the configured `corpus` cap, while empty and paper-only topics
  keep their existing no-synthesis path. Direct `distill synthesize`, `distill topic
  brief`, and on-demand `distill synthesis` generation now refuse before known
  synthesis-call work when projected spend exceeds the configured cap.
  Remaining: extend the same pre-run guard to
  additional direct commands once they expose credible estimates before their
  billable phase.
- [x] **Estimator calibration accountability** - shipped 0.12.3: estimate-of-record lands in `cost_log.jsonl`, and `distill costs` reports median absolute error, signed bias, and trend for comparable runs.
- [~] Rolling cost by topic and source type so users can see where spend is going
- [~] Surface stale corpora, failed runs, thin transcripts, and crawl drift in one place. Thin long-video transcript warnings now appear in `distill health` and the durable `distill audit` report; the broader dashboard rollup remains partial.
- [~] Cost anomaly detection and budget guardrails per topic or workflow so
  expensive runs are predictable. `distill costs`, JSON cost output, the CLI
  dashboard, and the local web dashboard now flag high daily spend, daily or
  comparable-run spikes, configured per-workflow budget overruns, and any
  recorded xAI media-generation model ids from the cost ledger. Warning
  thresholds and workflow-budget caps are configurable through environment or
  `.env` settings. Budgeted direct CLI trackers now stop on recorded-spend
  cap crossings for writer workflows, including `topic brief` and auto-generated
  `synthesis` read fallbacks, and the installed CLI maps those stops to a clean
  budget exit in human and JSON modes. Estimate-bearing `eval`, `discover`,
  `report`, `research-brief`, `ask`, `paper`, `papers`, `site`, `site-batch`,
  `corpus`, `video`, `channel`, `catch-up`, `reanalyze`, and `resynthesize` workflows now
  stop before the estimated work starts when projected spend exceeds the
  configured workflow cap.
  Synthesis-call workflows
  including `synthesize`, `topic-brief`, and on-demand `synthesis` now refuse
  before their known single synthesis call when the projection exceeds the cap.
  Remaining: broader
  pre-run projected spend checks for direct one-off CLI commands before their
  billable phase where a reliable estimate exists.
- [~] Interactive library browser (TUI first or lightweight local web view) for scanning topics, channels, videos, pages, and artifacts at scale
- [x] Live mixed-source run progress so long `discover` / `report` / site-heavy jobs show current phase, current item, completed/failed counts, and where time is going without making the user inspect the filesystem. `papers`, `site-batch`, `discover` paper/site ingestion, and default `report` show phase/item/completed/failed/spend output, with ETA when enough items have completed. Video-backed loops used by `latest`, `catch-up`, and the video branch of `discover` print persistent per-video completed/failed/spend progress after each item and include spend in live phase labels. Global `--quiet` / `--verbose` output controls and recurring-workflow help examples are now wired.
- [x] **Preview-table rendering at narrow widths** - fixed 0.9.31 (stacked layout below 110 columns); detail in [`CHANGELOG.md`](CHANGELOG.md).
- [x] **Library `CLAUDE.md` source counts wrong for legacy-layout topics** - fixed 0.9.29: source counting covers modern, lowercase, and legacy insight patterns, skips derived subtrees, and no longer hides older corpora from the generated index.
- [x] **Per-prompt token telemetry.** Every LLM router call writes prompt-input length, output length, elapsed time, provider, workload, call type, run id, and outcome to `library/.distill/telemetry.jsonl`, keeping per-call telemetry separate from run-level `cost_log.jsonl`. `distill costs` and the local web costs page now surface a "biggest prompts" view so prompt budget regressions are visible before context-engineering changes such as chunked paper analysis or report-pipeline compaction ship.

### 3. Productize the core workflow

- [~] Make the command model more intent-first around staying current, learning fast, and reporting
- [~] Intent-first aliases or a lightweight wizard for recurring jobs such as monitor, ramp-up, and report
- [ ] Make source-set inputs feel first-class instead of relying on one-off command choreography
- [x] **Zero-key tour / demo path** (from external QA 2026-06-11): a documented first-run that works before any API key - e.g. `--preview` against bundled example seeds plus the public example corpus from the proof-artifacts pass - so evaluation doesn't require setup. Constraint: no new verb (keep-surface-small); this is docs + bundled fixtures + existing flags, not a `demo` command. Added dedicated section in docs/usage.md.
- [~] First-class research profiles for "prefer these channels + these trusted domains + this goal file" workflows. Versioned profile files, `profile preview`, approval-gated `profile run`, resume state, and health checks in `audit all` shipped in 0.19. Remaining: use the goal file for semantic source-fit and novelty ranking, and add exact mixed-source manifests without command choreography.
- [x] Clarify corpus outputs and how to inspect or export them for downstream use. `docs/outputs.md` now maps source receipts, insights, syntheses, indexes, cost logs, preview caches, and export surfaces to their on-disk paths and commands.
- [~] Export / handoff presets for downstream agent roles and RAG pipelines (for example zipped MD/JSON bundles with clean metadata, confidence tags, and structured fields that consuming agents can act on without parsing prose)

### 4. Tighten the YouTube experience

- [~] Live cost visibility during runs. Mixed-source and video loops report running spend, and completed model calls record token-derived estimates. Remaining: a true in-call ticker for long single requests.
- [x] Total content stats in discovery - shipped 0.16.13: `distill discover`
  candidate output now summarizes full videos, Shorts, and known watch time
  from free YouTube metadata before preview approval or ingest.
- [~] Research history - track how findings evolve over time, diff between runs
- [ ] Multi-pass escalation on demand so catch-up can stay cheap by default and selectively deepen only the highest-signal items
- [ ] Persist creator voice / bias cards so synthesis can account for recurring framing, reliability, and drift over time
- [x] Retry / backoff / resume-friendly subtitle handling - shipped 0.12.11: caption fetch retries transient failures with backoff (a clean download with no `.vtt` is permanent captionless, not retried), and captionless videos route through the local-first Whisper ladder (bestaudio download + `transcribe_media` with a title/uploader vocabulary hint) before the legacy scribe fallback; detail in [`CHANGELOG.md`](CHANGELOG.md).

### 5. Finish website productization

- [ ] Website UX polish - checked-in examples, cleaner crawl defaults, better attachment discovery, less one-off command choreography
- [x] Trusted-site discovery for docs-heavy research workflows - `distill discover --trusted-site` now enumerates public same-host candidates from sitemaps, TOC/navigation links, and landing-page links for operator-trusted domains or section URLs, then feeds seeds into the existing LLM rerank. Sitemap `lastmod` values now surface as freshness hints in previews when available. Selected website candidates ingest exact pages by default, with opt-in bounded shallow crawls through `--site-crawl-depth` and `--site-crawl-pages`.
- [~] Better crawl boundary controls - keep site batches close to the intended section or branch by default. Trusted-site section URLs now carry a path prefix into selected shallow crawls, `distill site` accepts `--crawl-prefix`, and JSON site batches can set `crawl_prefix` on URL objects or collections. Remaining: richer section freshness and broader branch defaults for recurring site profiles.
- [~] Attachment ingestion - inventory embedded PDFs/videos and optionally pull PDF text or supported embedded-video transcripts into website runs
- [~] Mixed exact-page and shallow-crawl workflows that are easier to understand and safer by default. `distill site-batch --preview` now shows the resolved exact-page versus shallow-crawl plan before any model check, crawl, or write, global `--json` returns that plan as loop-readable rows, MCP `site_batch(preview=true)` returns the same plan even in read-only deployments, MCP `site_batch` honors JSON seed modes, and JSON URL objects or collections can declare `mode: "exact-page"` or `mode: "shallow-crawl"`. Remaining: broader site workflow polish and profile-level branch defaults.
- [x] Better website candidate identity in preview/approval flows - preview rows now show page-level labels, exact URLs, section labels, discovery source hints, and sitemap freshness hints when available.
- [~] Section-aware freshness so website refreshes focus on changed branches instead of re-crawling everything

### 6. Papers as a first-class source type

- [ ] OpenAlex (CC0, free dumps) and/or Ai2 Asta Scientific Corpus MCP integration for recency + citation-weighted ranking signals beyond arXiv. (Previously scoped as Semantic Scholar + Google Scholar; the classic Semantic Scholar API has been changelog-silent since late 2024 with restrictive keys, so OpenAlex/Asta are the durable paths.)
- [x] **Citation identity + export** - shipped 0.16.12: arXiv DOI values are captured into paper metadata and frontmatter when the feed supplies them, and `distill export <topic|all> --what citations --format bibtex|ris` writes local citation files for Zotero and reference managers.
- [ ] **PubMed / bioRxiv / medRxiv adapters** (same finding): arXiv-only excludes life-sciences labs entirely. Post-0.11 candidates on the adapter contract; OpenAlex metadata (above) is the shared discovery layer.
- [x] **Chunk-and-rerank paper analysis (effective-context-aware).** Shipped: structural heading match first, at most one batched model rerank when gaps remain, honest positional order when no model is available, and tier-4 keyword fallback only for legacy insight category names. Three focused paper passes assemble `<paper-slug>_Insights.md`; `chunk_selection_modes` is recorded in frontmatter for auditability. Design follows [`design/agentic-balance.md`](design/agentic-balance.md).
- [x] **Lift the 100K char cap once chunking is in place.** Shipped: arXiv PDF extraction no longer truncates at 100K chars; page limit raised to 200 with download-byte cap unchanged. Local PDF ingest matches. Multipass chunking owns prompt sizing when the provider window requires it.

### 7. Strengthen corpus quality and reuse

- [x] Stale detection - shipped 0.12.2: the prompt-version registry + per-topic staleness rollup in the audit (current / stale / no-provenance / unknown-family); detail in [`CHANGELOG.md`](CHANGELOG.md).
- [x] Auto-reanalysis trigger - shipped 0.12.6: the audit action menu prints per-artifact re-analysis commands resolved from each stale artifact's frontmatter (spend printed, never auto-run); detail in [`CHANGELOG.md`](CHANGELOG.md).
- [x] Synthesis stale-flag - shipped 0.12.8: source-relative freshness (synthesis older than the sources it synthesizes, shadowed legacy syntheses) in the audit, the dashboard health list, and the generated CLAUDE.md/AGENTS.md; detail in [`CHANGELOG.md`](CHANGELOG.md).
- [x] Library-level hygiene rollup - shipped 0.12.12: `distill audit all` writes `Library_Audit.md` at the library root (empty / unreadable / orientation-less directories as findings, test-suggesting names informationally) plus a one-line console rollup; detail in [`CHANGELOG.md`](CHANGELOG.md).
- [x] Duplicate detection - exact YouTube identity groups now ship in `distill audit` so same-source videos filed under multiple slugs are flagged without semantic scoring; detail in [`CHANGELOG.md`](CHANGELOG.md).
- [x] Semantic deduplication - shipped 0.12.4 (shingle-Jaccard near-duplicate groups in the audit, artifact-preserving, embedding-free); detail in [`CHANGELOG.md`](CHANGELOG.md).
- [~] Insights quality check - **NOT a heuristic quality score.** "Is this analysis good / substantive?" is a semantic judgment and belongs to the verify/eval model judges (faithfulness + coverage against the source), never to a section-presence + length heuristic (that brittle proxy fails good paraphrase and rewards padding - see [`design/agentic-balance.md`](design/agentic-balance.md)). The only deterministic part allowed here is a *structural* sanity tripwire (did the writer emit the required frontmatter / a parseable artifact at all), surfaced advisory in `distill audit`, not a quality gate.
- [x] Transcript validation - shipped 0.16.11: `distill audit` now flags long videos with suspiciously short transcript receipts in a dedicated advisory section. This catches likely capture failures by duration and character count; it is not a content-quality score.
- [x] Structured logging - shipped 0.16.10: the `distill` logger stays at DEBUG, console verbosity is controlled by handler levels, `--debug` and `--verbose` show DEBUG on stderr, and `library/.distill/distill.log` captures DEBUG records for post-run review across reused CLI processes.
- [x] **`distill audit`** - shipped 0.10.2 with the verify-sidecar coverage rollup, report artifact, and spend-safe action menu; grown through 0.12.x (staleness, near-duplicates, re-analysis commands); scheduling recipes shipped 0.12.1. Detail in [`CHANGELOG.md`](CHANGELOG.md).
- [x] **Output->input loop (`distill ask`)** - shipped 0.12.0 with strict-by-definition `--save` promotion and the MCP `ask` tool; design in [`design/ask-loop.md`](design/ask-loop.md), detail in [`CHANGELOG.md`](CHANGELOG.md).
- [x] **Hallucination-pattern eval expansion.** `distill eval` now includes an
  `ask` workload with false-premise, no-evidence, citation-request trap,
  unsupported-number, and route-disagreement fixtures. The expected behavior is
  not forced refusal: the model judge decides whether the output corrected the
  premise, stated uncertainty, cited only real evidence, and avoided laundering
  unsupported claims. Python owns fixture loading, structural golden citation
  checks against declared source stems, verdict aggregation, and the gate.
- [~] **Citation and source existence hardening.** Treat citation handles, claim
  ids, source ids, exported bibliography keys, and `distill ask` citations as
  structural references that must resolve to real local artifacts or receipt
  rows before an answer, synthesis, report section, or export is promoted. This
  is a rule-owned identity check, separate from semantic faithfulness. Initial
  slice: `distill ask --save` now refuses promotion when an answer cites an
  unknown bracketed source stem or cites no retrieved source stem; two-pass
  corpus synthesis now refuses invented claim handles before writing the
  synthesis artifact; BibTeX and RIS citation exports now refuse records whose
  local paper artifact or metadata receipt path no longer exists; accordion
  report section writes and QA rewrites now refuse unresolved numbered report
  citations such as `[cite: 1]` instead of stripping them; lightweight topic
  briefs now refuse the same unresolved numbered citations before writing a
  corpus brief; single-call synthesis now refuses them before writing output
  files; cached sub-agent query summaries now refuse uncited output or unknown
  source stems instead of caching an overbroad source list; MCP `ask` now
  returns `status: refused` when the underlying answer has unknown or missing
  source-stem citations instead of presenting it as a normal answer; Gemini
  Deep Research reports and multi-topic research briefs now refuse unresolved
  numbered report citations before writing artifacts.
- [~] **Uncertainty routing and disagreement surfacing.** Promote
  low-confidence, single-source, contradicted, or multi-route-disagreed claims
  into explicit reviewable findings instead of smoothing them into confident
  prose. Model judges own whether uncertainty is warranted; Python records the
  finding, preserves the evidence handles, and keeps review actions bounded.
  Initial slice: `distill eval` now carries hallucination-risk fixture labels
  into eval rows, append-only JSONL results, and report artifacts, and emits
  review findings from existing judge signals for unfaithful, minor,
  unjudged-risk, and route-disagreement rows.

### 8. Expand cross-source intelligence

- [~] Mixed-source topic synthesis that treats YouTube, websites, and papers as one corpus. `distill corpus` is live, MCP exposes `distill://topics/{topic}/corpus` and `distill://topics/{topic}/sources`, and `resynthesize_topic` refreshes corpus synthesis; near-duplicate detection shipped 0.12.4 (audit-surfaced). Direct-ingest sources such as X can join through the two-pass resynthesis path, but one-pass corpus synthesis does not yet include every source type. Deeper cross-source reasoning is still pending.
- [x] Trusted-domain website discovery inside `discover` - `--trusted-site` expands operator-trusted domains or section URLs into real page candidates from public same-host sitemaps, TOC/navigation links, and landing-page links, then reranks those page candidates with videos and papers in the same pool.
- [x] Goal-file watch hook - shipped 0.12.7: goal-driven discover runs persist their goal<->topic association (`.distill/goals.json`, goal text + file + seeds), and `catch-up` surfaces each topic's exact `--preview` refresh command on the cadence; spend surfaced, never auto-committed. Detail in [`CHANGELOG.md`](CHANGELOG.md).
- [ ] Multi-topic channels - same channel filed under multiple topics with shared transcripts
- [~] More source types - podcasts and feed/newsletter ingestion shipped in 0.11; conference talks and additional community adapters move behind the post-1.0 plugin boundary unless a dogfooded need promotes one.

### 9. Ongoing operation and access

- [x] Scheduled refresh + scheduled audit - recipes shipped 0.12.1 (`docs/usage.md` "Running on a schedule": Task Scheduler + cron lines for `catch-up`, `audit all --report-only`, gap-fill previews); the scheduler stays external by design. Remaining: the goal-file refresh hook for `distill watch` (see §8).
- [ ] Native notification integrations for daily briefings, weekly digests, and important-change alerts
- [x] Local web UI for browsing the library, reading rendered insights, drilling into topics, channels, and videos, and reviewing costs and watch status. It is served on loopback by `distill serve` and reads the file corpus directly.

### 9b. Engineering foundation - reproducible toolchain and quality gates

The build harness, not the corpus. The adopted/adapted/declined rationale lives in [`../ROADMAP.md`](../ROADMAP.md#engineering-standards-adopted-adapted-declined); the shipped toolchain releases (0.8.3 and the harden series) are in [`CHANGELOG.md`](CHANGELOG.md). This is the itemized backlog of what remains.

- [x] **Hypothesis deadline flakes under load** -- diagnosed and fixed 0.12.0: three full-suite runs each dropped a *different* property test that passed in isolation (llm migration/telemetry batch, ollama passthrough, paths/agent) with `DeadlineExceeded`; root cause was Hypothesis's 200ms wall-clock per-example deadline firing under coverage instrumentation on a loaded machine. Suite-wide `deadline=None` profile in `tests/conftest.py` (these suites test correctness, not latency). Residual watch item: if non-deadline order-dependent failures ever appear, suspect `load_dotenv` env leakage from CLI-invoking tests.
- [x] **Container runtime follows the Python floor.** The Dockerfile now uses the same Python 3.12 floor declared in `pyproject.toml`, includes `LICENSE` in the build context for package metadata, and ships a `.dockerignore` that keeps local runtime state, caches, and agent scratch out of image builds. Focused tests guard the base-image floor and context hygiene.
- [x] **Finish the `_logic.py` decomposition, with removal criteria**. `distill/commands/_logic.py` was the center of gravity - one ~9k-line module holding the full implementation of every CLI command, with `_cli_impl` as a compatibility alias. External code QA (2026-06-11) called it the largest maintainability risk visible from the code surface, and it was the original 0.7 code-health item. Twenty-two command modules and paper/site/concept/version/display/video/learning/discover support helpers are now out, the root callback and concepts app construction live in owned command modules, private compatibility exports live in `distill._cli_impl`, and `distill/commands/_logic.py` is deleted. No production command module imports the monolith, no command sub-apps remain inside, and the module-size allowlist is empty. Per-slice plan and history: [`docs/design/logic-decomposition.md`](design/logic-decomposition.md).
- [x] **Branch coverage ratchet** (0.8.3 -> 1.0) - `[tool.coverage.run] branch = true`; the enforced full-suite floor is now 95%, and the 0.19.33 release gate measures 95.01% branch coverage across 4,152 passing tests. The ratchet reached the 1.0 target through focused boundary coverage across configuration, providers, commands, MCP, ingestion, library state, deterministic verification, and the contract-snapshot surface.
- [~] **Full Pyright-strict ratchet** (1.0) - CI already runs the complete
  `distill/` package surface and blocks on every diagnostic. `distill/llm/` is
  centrally strict, all MCP modules carry strict directives, and promoted files
  elsewhere opt into strict mode individually. Parts of `prompts/`, `pipeline/`,
  `commands/`, `library/`, and other packages still rely on the blocking basic
  gate, so full strict promotion remains open. No `# type: ignore` is accepted
  without an inline reason.
- [~] **Parse, don't validate - strict domain types at every boundary** (1.0) - parse every external input (MCP tool arguments, frontmatter, adapter/local-file ingest, LLM structured outputs) once at the boundary into a rich domain type (`strict=True, extra='forbid'` Pydantic model, `NewType`, or frozen dataclass); core logic never sees raw primitives. The discovery helper now turns query-plan and rerank LLM JSON into typed object dictionaries before query strings, ids, or numeric scores are used; the broader rerank response parsers now turn LLM JSON rows into typed object dictionaries before ranking logic reads ids or scores; gap analysis now parses metadata plus inventory and summary payloads into typed structures before audit, MCP, or discovery consumes them; the audit health surface parses verify sidecars into typed flag rows and stale prompt records before rendering or action planning; shared dashboard data parses cost logs, latest-run payloads, topic-change history, dashboard snapshots, and site manifests into typed records before CLI or web rendering; shared command helpers preserve typed metadata-writing and duration-formatting contracts before artifact writes; topic diff, trend, watch-alert, and change-history command paths parse their detail rows and count records before artifact writes or command rendering; and File Search corpus assembly for reports and research briefings parses video, site, and paper metadata before titles or URLs enter uploaded documents.
- [~] **Verification depth on the deterministic core** (1.0, "formally contracted where it matters") - Design by Contract via `deal` on the merge/normalize/recovery invariants (idempotent + order-independent merge, round-tripping rollback, non-inverting intervals; `deal` also generates Hypothesis tests from the contracts); mutation testing (`mutmut`) of `concepts/` + `library/` + `pipeline` verify/dedup core on a cadence to prove test efficacy; a Hypothesis state machine over the playbook lifecycle (append -> merge -> notes -> snapshot -> rollback -> re-merge); and fault-injection at the external boundaries (malformed LLM JSON, truncated transcripts, network/yt-dlp failures) proving clean degradation and that no-silent-error-swallowing holds under turbulence. Scoped to the deterministic core and external boundaries, not blanket. Distill's primary concurrency model is I/O plus external workers, with subprocesses, thread-backed helpers, and synchronous phases also present. Async safety is the current focus; a future native or free-threaded path must add its own shared-state and race testing.

### 9c. Measured performance and implementation boundaries

The governing policy and current evidence live in
[`design/performance-and-language-admission.md`](design/performance-and-language-admission.md).
Distill is Python-first, not Python-only. Optimize accepted, verified artifacts
per unit of time and cost, not language-level throughput in isolation.

- [~] **Phase telemetry and run correlation.** CLI and MCP entry points now
  establish non-empty context-local run ids; `.distill/phase_telemetry.jsonl`,
  provider-call rows, cost rows, and run artifacts share that join key.
  `RunSummary` execution and accordion report work emit initial coarse phase
  spans with wall time, CPU time, process peak memory, artifact and byte counts,
  and wait classification. `distill costs` now reads that evidence, anchors only
  on command rows, joins provider and cost logs by exact `run_id`, and reports
  legacy, schema-invalid, unreadable, unanchored, and excluded-observer coverage
  without timestamp backfill. Command-envelope metrics and optional workflow
  artifact summaries remain separate, while provider time, process CPU, and
  peak-RSS limits are labeled explicitly. Per-run phase, provider, and cost
  completeness flags keep schema-invalid named rows or unreadable logs from
  turning a valid subset into an understated aggregate; affected rollups remain
  unknown, while complete no-row evidence and explicit valid zeroes remain
  distinct. Broader stable phase coverage across
  complete acquisition, provider, queue, subprocess, filesystem, deterministic
  CPU, and write paths remains pending; aggregate command and workflow rows use
  `mixed`.
- [~] **Deterministic scale generator and offline replay.** The initial
  repository-only `benchmarks/corpus_scale/` harness generates a disposable,
  fixed-seed mixed-source corpus and measures discovery, search, links,
  near-duplicates, and dashboard reads with versioned JSON samples plus
  before/after corpus-integrity digests. Version 2 runs every sample in a fresh
  child process with a timeout, records the worker PID and source fingerprint,
  labels the warmed filesystem state honestly, and withholds p95 below 20
  successful samples. Generate the canonical fixed-seed corpora at 100, 500,
  1,000, and 10,000 insights with controlled sizes, duplicate density,
  threshold-edge pairs, malformed frontmatter, broken links, and path edge
  cases. Replay paper, video, site, synthesis, verification, profile, and report
  workflows with frozen receipts and provider responses.
- [~] **Published 1.0 baseline.** First offline evidence published as
  [`performance/baseline-0.19.50.md`](performance/baseline-0.19.50.md)
  (Windows scale-100 corpus-scale suite, n=20, plus CLI `--version` process
  start). Still open: scale 500/1k/10k, multi-host history, frozen workflow
  replays, export/install metrics, and live 20-paper / 50-video / site-batch
  reference journeys with full hardware and cost metadata.
- [ ] **Honest regression policy.** Keep live provider, network, and hardware
  journeys as scheduled or release evidence. Allow deterministic offline
  benchmarks to block only after at least five comparable runs characterize
  runner variance, and only for a reproduced regression that exceeds both a
  relative and meaningful absolute budget. Correctness and resource ceilings
  remain blocking immediately.
- [ ] **One-pass corpus manifest.** Reuse a read-only inventory of paths,
  identities, sizes, mtimes, hashes, links, and optional lexical data within a
  command. Any persisted accelerator lives under `.distill/`, is git-ignored,
  rebuildable, non-authoritative, and paired with a direct-file fallback.
- [x] **Algorithm before translation, first seam.** Shipped 0.19.34: an
  ephemeral rare-first prefix index replaced all-pairs near-duplicate candidate
  generation while preserving exact Jaccard verification, deterministic
  grouping, ordering, threshold edges, and errors. At 1,000 fixed-seed insights
  it reduced 499,500 possible pairs to 150 candidates and kept the result
  digest stable. Repeated scans, file reads, connection setup, and subprocess
  startup remain Python optimization work before any native spike.
- [x] **Zero-work CLI startup, first pass.** Shipped 0.19.45: `-X importtime`
  attributed most of a 2.4-second `import distill.cli` to third-party
  libraries imported at module scope, led by the google-genai SDK and its
  transitive `mcp` dependency at roughly 1.1 seconds, then python-docx,
  yt-dlp, requests, and httpx. Each now loads at first real use behind a
  patch-compatible module `__getattr__`, a lazy bind that never overwrites an
  existing attribute, or a call-time module import. Measured on the
  development machine: import about 0.8 seconds, `distill --version` about
  0.95 seconds median from roughly 3.0-3.3 seconds, `--help` about 1.0
  second. A subprocess regression test keeps those libraries off the import
  path. Remaining cold-start cost is config-model construction and
  CLI-framework import; a cross-platform published number is still owed.
- [ ] **Bounded concurrency where safe.** Current paper and video batch loops
  are sequential. Parallelize independent capture and analysis only after URL
  pinning, cancellation, provider limits, local-model contention, atomic budget
  authorization, isolated per-item writes and progress, shared-state
  serialization, and failure isolation are explicit and tested. Record queue
  time and contention rather than hiding them behind aggregate wall time.
  Sequential report sections and ordered report rewrites stay out of scope.
- [ ] **Conditional Rust spike.** Start only if a representative profile still
  shows a narrow deterministic seam consuming at least 10 percent of workflow
  time and 250 ms p95, or violating an explicit memory, safety, or reliability
  budget. Require algorithmic work first, at least a 3x component target plus a
  material whole-workflow or memory improvement, differential/property/fuzz
  tests, a compiler-free reference path or optional accelerator package,
  cross-platform artifacts, dependency audit, SBOM coverage, and rollback.

No first-party Go service belongs inside the current product: job scheduling,
leases, backpressure, and cross-machine execution remain external-runner work.
A separately released Go runner may consume frozen Distill contracts if that
operational product becomes real. No Mojo code enters without an owned measured
tensor or accelerator kernel; evaluating MAX as a provider route uses the
existing doctor, ledger, cost-policy, and `distill eval` gates. Python 3.14t is
an optional compatibility and benchmark lane, not a supported default, until
whole-workflow evidence and stress testing justify it.

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
- [x] OKF projection of concept/entity playbooks: exported concept docs map to `Concept Playbook` and `Entity Playbook` OKF types, wikilinks rewrite to bundle-relative Markdown links, grouped `index.md` navigation, living `log.md` from profile run state and cost history, optional `llms.txt` pointer, and `okf_export: true` on profile runs.

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

- [~] **Just-in-time MCP context (paths-not-payloads)** - *promoted into the agent-legible 0.9 pass (see `../ROADMAP.md`); current status: `find_insights` (ranked path/preview/score) + `read_insight(path, section?)` are shipped and the default shape; `list_contested` is folded into `find_concepts(contested_only=True)`; the current tool count is maintained in `mcp.md`; remaining work is collapsing overlapping action tools.* Explicit resource and artifact reads may still return a requested full body, but query-first tools no longer make that the default. Anthropic's published example reduced a comparable workflow from ~150K to ~2K tokens (98.7% saving) by switching tool returns from raw payloads to structured summaries plus paths. At ~500-1,000 schema tokens per always-loaded tool, the remaining consolidation matters as much as response shape.
- [~] **Compaction in the profiled sequential report pipeline.** Bounded corpus hydration and recent-section excerpts reduce report context while preserving continuity, and per-prompt telemetry exposes the result. Remaining work is production-shaped before/after measurement and provider-native opaque continuation items where supported, with no loss of cross-section coherence.
- [ ] **Effective-context regression tests.** Add a small fixture suite that runs
  paper-analysis / synthesis / report prompts against representative long
  inputs and asserts the output covers known mid-document evidence, edge
  evidence, and deliberately placed disconfirming evidence. The deterministic
  fixture owns evidence placement and receipt existence; semantic success
  belongs to a model-judge verdict in `distill eval`, not a keyword gate. Wire
  the structural smoke tests into CI so context-position regressions surface in
  PRs rather than user reports.
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

- [x] **Page-level candidate identity for website-heavy discover runs.**
  Preview rows for site seeds now show the seed label or host+path-derived
  title, exact URL, section label, discovery source, and sitemap freshness hint
  when available.
- [x] **Trusted-site discovery for official-doc workflows.** `--site-seeds`
  still works for curated files, and `distill discover --trusted-site` now adds
  constrained page enumeration for operator-trusted domains or section URLs.
  The shipped slice reads public same-host sitemaps, TOC/navigation links, and
  landing-page links. It keeps generated seeds exact-page by default, persists
  trusted-site refresh commands, and sends those candidates through the existing
  goal-aware rerank.
  Sitemap `lastmod` values now surface as freshness hints when available.
  Operators can opt into bounded shallow crawls with `--site-crawl-depth` and
  `--site-crawl-pages`; trusted-site generated seeds remain section-scoped.
- [~] **Long-run visibility and failure surfacing.** The Agent365 mixed-source
  run kept working but emitted very little live output after planning, forcing
  filesystem inspection to confirm progress. Long `discover` / `report` runs
  should show current phase, current item, completed/failed counts by source
  type, and explicit reasons when a source stalls or skips (for example
  transcript rate limiting, empty crawl, reuse of unchanged site insights).
  Site ingest now reports analyzed-page and unchanged-page counts as structural
  outcomes, and MCP `site_batch` includes those counts in JSON. Remaining:
  richer skip reasons for transcript acquisition and other video-backed stalls.
