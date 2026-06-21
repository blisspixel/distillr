# Current State Analysis

Status note from the autonomous roadmap loop on 2026-06-19.

## Read Scope

I read the tracked Markdown inventory through the repository index, headings,
priority markers, and the full source docs that control near-term work:
`README.md`, `ROADMAP.md`, `docs/roadmap.md`, `docs/design/agentic-balance.md`,
`docs/design/model-judgment-vs-brittle-fallbacks.md`,
`docs/design/recurring-profiles-cost-routing.md`,
`docs/design/cli-adapter-runbook.md`, `docs/design/okf-loop-readiness.md`,
`docs/design/version-architecture.md`, `docs/design/how-we-build.md`,
`docs/design/logic-decomposition.md`, and `docs/architecture.md`. I also
inspected the tracked generated example corpus files as outputs, not edit
targets.

## Alignment Summary

The project is aligned around one product promise: Distill is the verified,
plain-Markdown research-corpus layer for humans and agents. It is not a memory
layer, a generic RAG store, a hosted app, a scheduler, or a graph UI. The
README, roadmap, architecture, cost docs, and agentic-balance charter all point
to the same spine:

- Acquire current public sources from eight source types.
- Analyze and synthesize from captured receipts.
- Verify before committing durable corpus artifacts.
- Expose the corpus through files, MCP, `ask`, OKF export, and loop-readable
  next actions.
- Keep orchestration external while making Distill commands safe for unattended
  loops.

## Agentic Balance

The governing rule is clear and internally consistent: model judgment belongs
on semantic questions, while Python owns structure, safety, cost policy,
bookkeeping, thresholds, verifiers, and final accept or refuse decisions.
Specifically:

- Agentic judgment: source fit, novelty, relevance, synthesis planning,
  contradiction interpretation, analysis lensing, and faithfulness verdicts.
- Rule-owned structure: schemas, paths, URLs, cost-mode refusal, action ids,
  exact argv arrays, approval class, dedup bookkeeping, receipts, ledgers, and
  verifier stop conditions.
- Judgment then rule: a model emits per-criterion verdicts, then Python
  aggregates, thresholds, records, and gates.

The main trap to avoid is deterministic quality scoring by keyword, length,
cosine, or other surface proxies. The dual trap is ripping out legitimate
structural checks. Number-in-source checks, parseability, URL safety, path
confinement, and ledger policy are correct rule-owned gates.

## Roadmap State

The shipped center of gravity is strong: write-time verification, audit,
entailment tier, ask/save, OKF export and validation, next-action JSON, profile
schema, profile examples, and profile preview are already present. The current
near-term dependency chain is:

1. Finish 0.19 recurring-profile run and no-metered-cost routing.
2. Finish local route policy and zero-dollar ledger accounting.
3. Add adapter doctor and support-statement checks before any plan-quota route
   can be trusted.
4. Extend cross-route eval before recommending any adapter.
5. Continue `_logic.py` decomposition and 1.0 quality ratchets in parallel.

## Implementation State Found

The live code already had:

- `distill profile preview <name|path>`.
- Profile schema and checked-in examples with `cost_mode: no-metered`.
- Local/provider availability helpers that ask the router rather than checking
  only `XAI_API_KEY`.
- An `AgentProvider`, adapter doctor scaffold, strict manifest parser, and local
  config auth-marker scanning, but without official installed-session auth
  proof, support statement, adapter-specific workload wiring, native usage
  signals, and eval proof needed for no-metered routing.

One documentation inconsistency was fixed before this file was created: roadmap
notes still described an old MCP count of 22 to 21 tools, while the live code,
README, and MCP docs count 24 tools.

## First Implementation Slice

The safest first atomic work is the rule-owned cost-policy foundation. Profile
run and plan-quota adapters are dangerous without it because they can otherwise
turn recurring loops into surprise API spend. Cost policy is structural, so it
does not violate agentic balance. The slice in this branch:

- Parses `DISTILL_COST_MODE=auto|no-metered|paid-ok`.
- Classifies provider routes conservatively.
- Allows local Ollama and LM Studio in `no-metered`.
- Blocks cloud APIs and unproven adapter routes in `no-metered`.
- Keeps plan-quota CLIs blocked until adapter doctor, support statement,
  included-plan auth proof, adapter-specific workload wiring, ledger, and eval
  proof exist.

External spend used so far: `$0.00`.

## Loop refresh (2026-06-21)

Re-read README, ROADMAP, `docs/roadmap.md`, agentic-balance charter, and
`docs/design/okf-loop-readiness.md`. Alignment confirmed: no semantic quality
gates were added; chunk selection follows structural-first then model-judgment
then honest positional order; OKF export remains a read-only projection.

Cycle 71 ships effective-context-aware paper multipass analysis.
`distill/pipeline/analysis/chunk_selection.py` owns the selection plan:
structural heading match on captured metadata, at most one batched model rerank
when gaps remain, positional spread as the labeled no-model order, and keyword
fallback only for legacy `INSIGHT_CATEGORIES` names. `multipass.py` runs three
paper passes and merges into the existing artifact shape. `async_compat.py`
closes nested-event-loop safety on Windows. Local metadata uses
`LOCAL_FALLBACK_CONTEXT_WINDOW = 32_768` when Ollama/LM Studio is unreachable.

Cycle 72 ships OKF producer follow-ons from the Google OKF blog gaps:
`Concept Playbook` and `Entity Playbook` types, wikilink to bundle-relative
Markdown links, grouped `index.md`, living `log.md` from profile run state and
cost log, optional `llms.txt` pointer, and `okf_export: true` on approved
profile runs. `docs/roadmap.md` backlog checkboxes updated for chunk-and-rerank
and OKF concept/entity projection.

Quality gate: 2689 passed, 84% coverage, ruff clean. External spend: `$0.00`.
Remaining near-term: audit next-action for stale OKF re-export, MCP OKF
export/validate tools, 100K char cap lift once multipass is dogfooded, 1.0
quality ratchets (branch coverage, Pyright-strict, parse-don't-validate).

## Subsequent Implementation Updates

Cycle 2 added the top-level `distill --cost-mode <mode>` override and made
no-metered profile preview commands carry that override explicitly. That keeps
loop runners from depending on ambient `.env` state.

Cycle 3 added `distill profile run <name|path>` as the next structural slice.
The command plans by default and requires `--yes` before execution. When
approved, it executes the generated `distill ...` argv rows through the
existing ingest and analysis commands, records per-command outcomes, and writes
resume state under `.distill/profiles/<profile>/run_state.json`. Exact feed
items and YouTube videos complete once. Standing seeds remain repeatable so
recurring profiles keep checking for new material.

Cycle 4 added the first complete zero-dollar ledger slice: cost-log rows now
record `usage_ledger`, `by_provider`, and `by_route_class`, and approved profile
runs write zero-dollar `profile-run` orchestration rows.

Cycle 5 completed richer no-metered route-block reporting: blocked policy
messages and reports now include provider, workload, cost class, required proof
when applicable, and paid-ok retry guidance for intentional metered runs.

Cycle 6 added profile loop handoff rows: `profile-run.v1` JSON now emits
`next_actions` entries using the same structural action contract as audit,
including argv commands, approval class, write scope, verifier, and loop
metadata.

Cycle 7 added audit-visible recurring profile health to `distill audit all`.
The audit remains deterministic and local-only: it reports invalid profile
files, missing goals, missing or stale run state, recorded profile command
failures, invalid state, and profiles whose local corpus is thin relative to
their saved source plan.

Cycle 8 started adapter doctor scaffolding with `distill doctor --adapters`.
The check is read-only and fail-closed: it reports candidate adapter binary
presence, version/help probes, required structured-output flags, API-key
environment blockers, route class, and support-statement status without running
adapter workloads.

Cycle 9 added the strict `adapter-result.v1` manifest boundary for future CLI
adapter runs. The parser rejects unknown fields, missing usage signals, unsafe
scratch-relative paths, unknown adapters, and no-metered results that report
metered auth, API-key blockers, or metered usage allowance. The adapter doctor
JSON report now publishes that contract so external loops can inspect it before
any route graduates.

Cycle 10 added local config auth-marker scanning to adapter doctor. It parses
known TOML and JSON config files, reports matched marker names and display
paths only, classifies API-key environment variables and API-key config fields
as metered blockers, and reports session markers as evidence without making
routes eligible.

Cycle 11 added before/after scratch workspace write checks for future adapter
runners. A runner can snapshot staged source files before execution, parse the
`adapter-result.v1` manifest afterward, and reject missing declared outputs or
unexpected new scratch files.

Cycle 12 added the generic scratch-only adapter runner primitive. It runs exact
argv arrays with shell disabled, strips known metered API-key environment
variables, enforces a timeout, captures bounded output tails, parses the result
manifest, and applies scratch write checks.

Cycle 13 structured adapter support statements as data instead of prose-only
status. Adapter doctor reports now include checked date, source URLs, required
evidence, no-metered current status, and notes for each candidate route. Planned
plan-quota routes remain blocked because their support records are not current,
and Copilot remains a credit-metered candidate rather than a no-metered default.

Cycle 14 added structured `quota_stop` metadata to the future
`adapter-result.v1` manifest boundary. Quota and rate-limit stop reasons now
require a reached flag and reason, preventing adapter runners from hiding quota
exhaustion in free-text stop output.

Cycle 15 added an adapter ledger bridge. Verified `adapter-result.v1` manifests
can now produce cost-tracker token rows and metadata, with included-plan auth
classified as zero-dollar usage and rolled up separately from local and metered
routes. This is an accounting primitive only; it does not select or enable any
adapter route.

Cycle 16 added the strict `adapter-workload.v1` input package boundary and
exposed it through adapter doctor JSON. Future read-only adapter prototypes now
have a checked scratch-relative package shape before any CLI receives prompts
or source files. The same cycle tightened manifest path normalization so raw
`.` path segments cannot be normalized away.

Cycle 17 added a checked adapter workload runner that composes
`adapter-workload.v1` packages with the scratch adapter runner. It runs exact
argv arrays only in scratch and blocks result manifests that read outside the
declared package, write outside declared outputs, or report a different cost
mode. The manifest parser now also rejects read-only results that declare
written files.

Cycle 18 added a blocked adapter command planner. It records the future Codex
read-only `codex exec --sandbox read-only` argv shape, inherits adapter doctor
blockers, and remains ineligible until the later manifest writer and remaining
route gates exist.

Cycle 19 added a native adapter result writer. It writes validated
`adapter-result.v1` scratch manifests from captured CLI output, workload input
hashes, and caller-supplied native usage metadata, and the workload runner now
allows declared capture files such as `result.txt` while blocking undeclared
scratch writes.

Cycle 20 added command-plan capture metadata and a blocked Grok read-only
template. Codex and Grok plans now record future argv shapes plus staged prompt
paths, result capture paths, and allowed scratch capture files, while remaining
ineligible until native usage collection, support proof, auth proof, and eval
evidence exist.

Cycle 21 added schema-path command-plan metadata and a blocked Claude read-only
template based on local `claude -p --help` output. Codex, Claude, and Grok
plans now record staged prompt paths, schema paths, result capture paths, and
allowed scratch capture files, while Claude remains blocked until schema
inlining, native usage collection, support proof, auth proof, and eval evidence
exist.

Cycle 22 added deterministic Claude schema inlining for command plans. The
inliner loads a staged scratch JSON schema object, inserts compact sorted JSON
before Claude's `--tools` argument, rejects non-object schemas and path escapes,
and removes only the schema-inlining blocker. Claude still remains blocked on
native usage collection and route gates.

Cycle 23 added the strict `adapter-native-usage.v1` boundary. Adapter doctor
JSON now exposes the usage contract, command plans record the standard native
usage capture path, and the native result writer can consume validated scratch
usage files when writing `adapter-result.v1` manifests. The parser requires
token counts or native usage metadata and rejects unknown adapters, unknown
fields, absolute paths, and scratch path escapes. This is still not route
graduation; adapter-specific wrappers must collect real CLI usage before any
plan-quota route can run.

Cycle 24 added a Codex-specific JSONL usage parser. The parser consumes
`codex exec --json` stdout, extracts `turn.completed.usage`, sums token fields,
preserves cached and reasoning token metadata, and returns an
`adapter-native-usage.v1` record. It is based on the official Codex
non-interactive JSONL event contract and local `codex exec --help`; no Codex
model call was made. Codex command plans still remain blocked until runner
capture wiring, auth proof, support proof, and eval evidence exist.

Cycle 25 added the Codex capture writer. Given captured Codex JSONL stdout and
the planned `result.txt`, it writes a validated `native-usage.json` file and
then writes an `adapter-result.v1` manifest through the shared result writer.
This closes the post-process capture primitive for Codex fixtures without
running Codex or enabling the route. The remaining Codex-specific gap is wiring
the workload runner to call the capture writer after process exit and then
apply the existing manifest and scratch-write checks.

Cycle 26 added workload-runner capture hooks. The low-level scratch runner can
invoke a post-process callback after a successful exact-argv process and before
manifest loading, and the workload runner binds that callback to the parsed
`adapter-workload.v1` package. Tests now run a simulated Codex JSONL process
through the real Codex capture writer and verify the resulting
`native-usage.json`, `adapter-result.v1` manifest, and scratch write check.
Capture failures become explicit blocked reasons and do not bypass manifest
validation.

Cycle 27 added a blocked Gemini CLI read-only command plan. Local Gemini CLI
0.46.0 help exposes headless `--prompt`, `--output-format json`, and
`--approval-mode plan`, so Distill now records the future argv shape with
staged prompt, schema, result capture, and native usage capture metadata. The
plan remained blocked at that point because the runner still needed staged
prompt stdin, stdout-to-`result.txt` capture, native schema enforcement was not
exposed by the local help, native usage capture was not implemented, and the
support, auth, and eval gates remained closed. Cycle 31 later removed the
staged-stdin blocker. The same cycle tightened Gemini-family billing preflights
so `GOOGLE_API_KEY` blocks no-metered Gemini and Antigravity claims alongside
`GEMINI_API_KEY`.

Cycle 28 added a blocked Antigravity read-only command plan. Local Antigravity
1.107.0 help exposes `antigravity chat --mode ask -`, so Distill now records
the future argv shape with staged prompt, schema, result capture, native usage
capture, and allowed scratch capture metadata. The plan remains blocked because
local help exposes no headless JSON output, no native schema enforcement, and no
native usage signal. The adapter doctor now also probes Antigravity chat help
for mode support. This closes the current command-template set for the five
planned included-plan adapters without making any route eligible.

Cycle 29 added a generic stdout capture writer. For CLIs without a native
result-file flag, `write_stdout_captured_result()` writes captured stdout to
`result.txt` and then writes the same validated `adapter-result.v1` manifest
from an existing `adapter-native-usage.v1` scratch file. The shared result
writer now rejects native usage files whose adapter name does not match the
manifest adapter, so a Codex usage file cannot accidentally ledger a Grok,
Gemini, Claude, or Antigravity result. This closes the generic result-capture
primitive without inventing non-Codex usage signals or enabling any route.

Cycle 30 added Claude Code native usage capture. The parser accepts captured
Claude JSON or stream JSON stdout, extracts `usage` objects, preserves cache,
duration, turn, cost, session, and stop metadata, and writes a strict
`adapter-native-usage.v1` record. The Claude capture writer extracts the
structured result, writes `result.txt`, writes `native-usage.json`, and then
uses the shared manifest writer so prompt/source hashes, policy, and scratch
paths are still enforced. The command planner no longer carries the obsolete
Claude native-usage blocker after schema inlining, but Claude remains
route-blocked by support, auth, and eval gates.

Cycle 31 added staged stdin support to the adapter runner boundary. A workload
run spec can now name a scratch-relative `stdin_path`; the workload runner reads
that file, rejects path escapes, and passes the content to the exact-argv
runner without shell piping. The low-level subprocess runner sends that text on
stdin. This removes the obsolete Gemini stdin blocker while leaving Gemini
blocked on native schema enforcement, native usage capture, support, auth, and
eval gates.

Cycle 32 added JSON auth-command probes to adapter doctor. Claude can now run a
read-only `claude auth status --json` probe and Grok can run
`grok inspect --json`; both are parsed for configured marker names only. The
doctor can classify API-key command evidence separately from session command
evidence without recording secret values or account identifiers. This is still
not route graduation because support statements remain non-current and eval
gates remain closed.

Remaining near-term gaps are current official no-metered support statements,
installed-session auth proof where no command or config proof exists, native
usage collection and capture wiring for Grok, Gemini, and Antigravity, and
eval-gated route graduation.

Cycle 33 closed the per-prompt telemetry cost-surface gap. Per-call router
telemetry already wrote token counts and elapsed time to
`library/.distill/telemetry.jsonl`; this cycle exposed the largest prompt calls
in `distill costs`, `distill costs --json`, and the local web costs page. The
run-level `cost_log.jsonl` remains reserved for run summaries, estimates, and
provider breakdowns. The telemetry reader now skips rows with non-numeric token
counts so a malformed line cannot take down cost inspection.

Cycle 34 closed the contributor-guide context-engineering item. The
contributor guide now tells prompt, MCP, report, pipeline, and loop changes to
prefer paths before payloads, preserve provenance in context, measure prompt
budget with biggest-prompts telemetry, compact evidence before wording, keep
durable knowledge as structured deltas, clear stale intermediate context, and
leave semantic judgment to model verdicts rather than deterministic proxy
scores.

Cycle 35 partially closed the live batch progress roadmap item. A shared
`BatchProgress` helper now formats phase, item, completed, failed, running
spend, and ETA for non-video loops. `distill papers` uses it for per-paper
analysis progress, and `distill site-batch` uses it for per-seed progress.
`site-batch` now also records unexpected seed-level exceptions as structured
`site-ingest` issues and continues with later seeds, while `BudgetExceededError`
still stops the run. At the end of that cycle, `discover`, `latest`, and
`catch-up` still needed the same surface.

Cycle 36 extended the same progress posture to video-backed loops. `ETATracker`
now records failed items, can include running spend in phase labels, and
`process_video` prints a persistent per-video progress line after success or
failure. This covers `latest`, `catch-up`, and the other shared video paths
without changing ranking, analysis, or synthesis behavior. The remaining named
batch-progress gap is `discover`.

Cycle 37 closes that named `discover` gap. The paper branch and curated-site
branch now use `BatchProgress`, so mixed discovery shows phase, item count,
completed count, failed count, running spend, and ETA for selected papers and
site seeds. The video branch already flows through the shared learning path
from Cycle 36. The larger CLI-UX item remains partial only because report-phase
visibility and the verbosity dial are separate follow-ons. The implementation
also moved the paper and site ingest bodies into `distill.commands._discover_ingest`
so `_logic.py` stays below the module-size ratchet instead of absorbing new
loop code.

Cycle 39 closes the report-phase side of the same visibility thread. The
default accordion report now uses `BatchProgress` for report phases, section
writing, and QA rewrites, so users can see current phase, current item,
completed count, failed count, running spend, and ETA where available. The
default report method label now says 4-phase, matching the research, section
writing, assembly, and QA pipeline. The live progress item is now complete; the
remaining CLI-UX follow-on is the verbosity dial.

Cycle 40 ships that verbosity dial. The top-level callback now accepts
`--quiet` / `-q` to suppress the shared human console for one invocation, and
`--verbose` / `-v` as the debug-logging alias. The output-mode setup lives in
`distill.commands._helpers`, so `_logic.py` stays under the lowered 1444-line
ratchet. `--json` still owns stdout purity separately; quiet mode suppresses
human console output without changing JSON emission.

Cycle 41 closes the remaining recurring-workflow help-example pass. Command
help now shows concrete preview, approve, discovery commit, single-target
ingest, audit next-action, OKF export, and OKF validation examples on the
commands that own those workflows. This is a CLI legibility change only: no
semantic ranking, ingest behavior, audit logic, or export contract changed.

Cycle 42 resumes `_logic.py` decomposition. The watch-owned
`_show_latest_insights` and `_print_goal_refreshes` helpers now live in
`distill.commands.watch`, and the goal-refresh test imports that canonical
owner. `distill.cli._format_date` remains available by re-exporting
`cli_shared.format_date`, while `_logic.py` drops to the 1355-line ratchet.

Cycle 43 moves site-ingest ownership out of `_logic.py`. `process_site_seed`,
site content hashing, and section-change summaries now live in
`distill.commands._site_ingest`; CLI, MCP, discover, and tests patch that
canonical owner. `distill.cli` keeps compatibility re-exports for the private
site helper names, and `_logic.py` is down to the 1077-line ratchet.

Cycle 44 crosses the sub-1000 `_logic.py` milestone. Paper artifact writing now
lives in `distill.commands._paper_artifacts`; paper CLI, MCP paper tools,
discover ingestion, and verify tests use the new canonical owner. `_logic.py`
keeps only the private compatibility alias for old `_cli_impl` imports, dead
scaffold comments were removed, and the module-size allowlist is empty because
`_logic.py` is now 981 lines.

Cycle 45 moves the post-ingest concept playbook hook out of `_logic.py`.
`run_concepts_after_ingest` now lives in `distill.commands._concept_ingest`;
paper, learn, and discover commands use that canonical owner, and `_logic.py`
keeps only the private compatibility alias. `_logic.py` is now 949 lines.

Cycle 46 moves installed package version lookup out of `_logic.py`. The
canonical helper is now `distill._version.get_version`; dashboard, doctor,
maintain, and version tests import that owner directly, while `_logic.py` keeps
only the private compatibility alias. `_logic.py` is now 936 lines.

Cycle 47 moves channel-list display truncation out of `_logic.py`.
`_truncate_channel_list` now lives in `distill.commands._helpers`; dashboard
tests call that canonical owner directly, while `_logic.py` keeps only the
private compatibility alias. `_logic.py` is now 919 lines.

Cycle 48 moves the shared video helper wrappers out of `_logic.py`.
`_ensure_channel_context`, `_process_video`, and `_run_scope_report` now resolve
directly to `distill.commands._helpers` owners; process, watch, discover, and
learning tests call or patch those canonical owners. `_logic.py` keeps only the
private compatibility aliases and is now 838 lines.

Cycle 49 moves learning query expansion and video selection out of `_logic.py`.
`_expand_learning_queries`, `_expand_paper_queries`, and
`_select_learning_videos` now live in `distill.commands._learning`; learning and
CLI wiring tests call or patch that canonical owner. `_logic.py` keeps only the
private compatibility aliases and is now 704 lines.

Cycle 50 moves learning-flow injection wrappers out of `_logic.py`.
`_preview_learning_selection`, `_run_learning_command`,
`_process_learning_selection`, and `_generate_and_export_topic_brief` now live
in `distill.commands._learning`; learn, discover, topic, topic-watch, and CLI
wiring tests call or patch that canonical owner. `_logic.py` keeps only the
private compatibility aliases and is now 470 lines.

Cycle 51 moves the remaining discover helper body out of `_logic.py`.
Discovery query generation, YouTube candidate fetch, rerank display, sizing
menu, confirmation, and mixed-source ingest bridges now live in
`distill.commands._discover_flow`, with command-level helpers re-exported
through `distill.commands.discover`; discover and ingest tests patch the owning
module. `_logic.py` keeps compatibility aliases only and is now 201 lines.

Cycle 52 moves the root callback and last direct command-module imports out of
`_logic.py`. The bare `distill` callback, eager `--version`, output-mode setup,
cost-mode override, and home-screen banner now live in
`distill.commands.root`. The `concepts` Typer app now lives in
`distill.commands.concepts`. `ask`, `audit`, `claude-md`, `ingest`, `eval`,
`process`, and `view` import canonical helper owners directly, and their tests
patch those owners instead of `_logic` or `_cli_impl`. `_logic.py` is now a
113-line `_cli_impl` compatibility target only; no production command module
imports it.

Cycle 53 deletes the remaining `distill.commands._logic` facade. The private
compatibility export surface now lives directly in `distill._cli_impl`, while
command implementations remain in focused `distill.commands.*` owners. Import
sanity checks confirm `distill._cli_impl` still exports `get_config` and `main`,
`distill.cli.app` still points at the shared Typer app, and
`distill.commands._logic` no longer resolves.

Cycle 54 consolidates the CLI home dashboard onto the shared
`dashboard_snapshot()` source already used by the web dashboard. The command
module now formats a snapshot instead of rebuilding counts, cost rollups,
topic changes, budget warnings, and corpus health warnings inline. A focused
home-screen test patches `_dashboard_snapshot` directly to prove the CLI uses
the shared data contract.

Cycle 55 adds exact video duplicate detection to `distill audit` through
`distill.pipeline.audit_video_duplicates`. This is a rule-owned source identity
check over `metadata.json`: prefer `video_id`, fall back to normalized YouTube
watch, shorts, embed, live, v, youtu.be, and youtube-nocookie URLs, then group
artifact directories that point at the same source video. It deliberately does
not score semantic similarity; near-duplicate insight detection and model
judgment remain separate.

Cycle 56 closes the structured logging roadmap item by making the documented
file-log invariant true. The `distill` logger now stays at DEBUG while the
console handler owns warning-only versus DEBUG visibility. File handlers are
added late when an ops directory becomes available, and reused CLI processes
retarget `library/.distill/distill.log` to the current library instead of
keeping a stale handler. This is structural run plumbing, so deterministic
logging rules are the right boundary.

Cycle 57 moves transcript validation from a dashboard-only warning into the
durable audit report. `distill.pipeline.audit_transcripts` owns the rule:
videos at least 1800 seconds long with transcript receipts under 500 stripped
characters are flagged as likely capture failures. The check is advisory and
structural, not a content-quality score, and `distill health` reuses the same
collector so dashboard and audit wording stay aligned.

Cycle 58 closes the paper citation identity and export slice. arXiv DOI values
now travel through `PaperRecord`, metadata JSON, the paper receipt, and
frontmatter when the feed supplies them. `distill.library.citations` reads local
paper artifacts and renders BibTeX or RIS. The command
`distill export <topic|all> --what citations --format bibtex|ris` writes the
files under `output/`. This is structural metadata export for reference
managers, not a paper-quality signal.

Cycle 59 adds structural video content stats to `distill discover` candidate
output. The helper in `distill.pipeline.discovery` summarizes full videos,
Shorts, known watch time, and unknown-duration candidates from free YouTube
metadata. The discover command prints that summary before reranking or preview
approval, so users and loops see the size of a video candidate set without any
new model judgment or ingest behavior.

Cycle 60 adds the first trusted-site discovery slice for website-heavy
`distill discover` runs. The new site ingestor helper expands repeated
`--trusted-site` domains or section URLs into exact-page `SiteSeed` candidates
from public same-host sitemaps and landing-page links, with section scope
preserved when the operator supplies a section URL. The discover command
combines those generated seeds with curated `--site-seeds`, persists the
trusted-site inputs in goal refresh metadata, and sends the resulting website
pool through the existing model rerank. This is structural URL enumeration over
an operator allowlist, not a page quality or goal-fit scorer.

Cycle 61 makes those website candidates legible before approval. Site seeds now
carry structural preview identity: section label, discovery source, and
freshness hint. Trusted-site discovery fills those fields from sitemap or
landing-page provenance and sitemap `lastmod` values when available, and the
discover rerank/display path surfaces exact URL, section, source, and freshness
in the prompt and preview table. This is identity and freshness metadata, not a
semantic ranking signal.

Cycle 62 adds TOC/navigation extraction to trusted-site discovery. The landing
page parser now marks links found inside structural navigation or table of
contents containers as `toc link`, lists them before generic landing links, and
promotes duplicate URLs when a generic link is later found in the TOC. Same-host
scope, public URL policy, section scope, exact-page seeds, and the existing
model rerank still own the boundary between candidate enumeration and goal-fit
judgment.

Cycle 63 adds explicit shallow website crawl controls to `distill discover`.
The default remains exact-page ingest for every selected website candidate.
Operators can pass `--site-crawl-depth` and `--site-crawl-pages` to opt into a
bounded crawl, and trusted-site generated seeds remain same-section scoped.
Preview snapshots and goal refresh commands carry the crawl choice so replayed
runs preserve the operator's explicit boundary instead of inferring crawl
breadth from page metadata or model scores.

Cycle 64 starts the remaining long-run visibility work by making site ingest
return structural result counts: pages crawled, pages analyzed, and unchanged
pages reused. Discover and site-batch progress lines can now distinguish
completed work from unchanged-page reuse, and MCP `site_batch` JSON carries the
same counts for external loops. This is a receipt-level skip reason, not a page
quality or relevance judgment.

Cycle 65 starts the crawl-boundary roadmap item with explicit site seed
`crawl_prefix` support. Trusted-site section URLs carry their source path into
selected shallow crawls, direct `distill site` runs can pass `--crawl-prefix`,
and JSON site batches can set `crawl_prefix` on URL objects or collections.
This is rule-owned URL scope control, not source relevance scoring.

Cycle 66 starts the mixed website workflow item with structural batch planning.
JSON site seed URL objects and collections can now declare `mode: "exact-page"`
or `mode: "shallow-crawl"`, with `crawl: false` and `crawl: true` as boolean
aliases. `distill site-batch --preview` resolves the same final seeds a real
run would use, then prints exact-page versus shallow-crawl mode, page caps,
depth, and boundary before any model check, crawl, or write. Unsupported mode
names fail during seed-file loading instead of silently widening crawl scope.
This is run-plan visibility and explicit operator intent, not page quality or
relevance judgment.

Cycle 67 makes that same site-batch preview loop-readable under global JSON
mode. `distill --json site-batch <seeds> --preview` now returns the resolved
topic, seed count, write intent, and exact per-seed plan rows in the standard
JSON envelope while still skipping model checks, crawls, and writes. This keeps
external runners on structured plan data instead of console scraping. It is a
structural workflow handoff surface, not a semantic ranking or source-quality
judgment.

Cycle 68 brings the same mixed website seed contract to the MCP write surface.
MCP `site_batch` now expands relative JSON seed files inside the library root
through the CLI seed parser, so `mode`, `crawl`, `crawl_prefix`, and unsupported
mode handling match `distill site-batch`. Direct URL lists and TXT seed files
stay exact-page by default. The MCP ingest allowlist still checks every expanded
seed URL before processing. This is structural input parsing and guardrail
parity for agent tools, not a source-fit or page-quality judgment.

Cycle 69 makes that MCP site-batch plan inspection usable in read-only agent
deployments. `site_batch(preview=true)` now resolves direct URLs, TXT seed files,
and JSON seed files into the same plan payload as CLI JSON preview, then exits
before model checks, crawling, writes, spend, progress, or run logs. The
read-only bypass is opt-in at the write-tool wrapper and only applies to tools
that declare preview as structurally non-mutating. This is a loop planning
surface, not a model judgment or completion claim.

Cycle 70 opens the maximum-performance quality-bar loop with a startup re-read
and a validation pass. I re-internalized the bible: README, the reorganized
ROADMAP (milestone map, the No-brittle-junk charter, the 1.0 quality bar),
`docs/design/agentic-balance.md`, `docs/design/model-judgment-vs-brittle-fallbacks.md`,
`docs/CONTRIBUTING.md`, and `SKILLS.md`. Alignment is confirmed: there is no
separate CODE-QUALITY-STANDARDS file; the standard is those documents, and the
supreme rule is that no quality, faithfulness, or robustness gate may be a
deterministic score - every decision is classified structural rule, semantic
judgment, or judgment-then-rule before any scorer or gate is written.

State is validated, not assumed. Every shipped claim across 0.1-0.17 was
re-checked against the implementation and its tests (28 load-bearing claims,
all verified - `run_verify_hook` on every emit path, router-based
`model_available()` replacing the `xai_api_key` gate, `_looks_like_rumor_query`
and `infer_lens` deleted tree-wide, no `eval/stats.py` bootstrap, the `nh3`
dashboard sanitizer), and a live grok-4.3 run ($0.06) exercised
capture -> analyze -> verify -> synthesize end to end, writing schema-v2
`_Verify.json` sidecars whose synthesis sidecar grounded 15/15 claims against
its receipts. 0.17.0 was cut, tagged `v0.17.0`, and published to PyPI; the
roadmap was reorganized so shipped detail points to the changelog and the
forward map foregrounds the genuine remaining distance.

That remaining distance is the 1.0 quality bar, not new feature surface: branch
coverage 80 -> >=95% (ratcheted up-only), Pyright-strict beyond `distill/llm/`,
parse-don't-validate strict domain types at every boundary, verification depth
on the deterministic core (`deal` contracts, mutation testing, Hypothesis
stateful tests, fault injection), the contract freeze, and the presentation
pass. The loop advances these as atomic, test-first, locally-validated cycles,
keeping external spend within the $5 budget (spent this session: $0.06). The
0.19 no-metered graduation stays gated on external vendor support statements,
so it is opportunistic rather than the critical path.
