# Loop Skills

## Repository Reading

- Treat tracked Markdown as source, but treat generated example corpus artifacts
  as outputs. Do not hand-edit generated `_Insights.md`, generated syntheses,
  generated `CLAUDE.md`, or generated topic `AGENTS.md`.
- Use `git ls-files "*.md"` for the authoritative Markdown inventory. Avoid
  `.venv`, `tmp`, and untracked generated artifacts unless the task explicitly
  requires them.
- Re-read `README.md`, `ROADMAP.md`, `docs/roadmap.md`, and
  `docs/design/agentic-balance.md` at the start of each cycle.

## Agentic Balance

- Before adding any scorer, gate, or agentic surface, classify the decision:
  structural rule, semantic judgment, or judgment then rule.
- Structural examples: schemas, paths, URLs, exact receipts, cost policy,
  action ids, ledgers, argv arrays, approval classes, and verifier stop
  conditions.
- Exact duplicate video detection is structural when it keys on normalized
  source identities such as `video_id` or YouTube URLs. Semantic duplicate
  meaning remains a model judgment or an advisory near-duplicate signal.
- Thin transcript detection is structural when it compares video duration and
  transcript character count to catch likely capture failures. Do not present
  it as content quality scoring.
- Citation export is structural when it renders local paper metadata into
  BibTeX or RIS. Do not present DOI presence as a paper quality signal.
- Discovery video content stats are structural when they aggregate free
  metadata such as candidate count, duration, and Shorts classification. Do not
  present them as relevance or quality scoring.
- Trusted-site discovery is structural when it expands operator-trusted domains
  or section URLs into public same-host page candidates from sitemaps,
  TOC/navigation links, and landing-page links. Goal fit and page usefulness
  remain model-judged in the existing discover rerank.
- Discover website crawl depth is structural when it is an explicit operator
  flag, with exact-page ingest as the default and trusted-site generated seeds
  staying section-scoped. Do not infer crawl breadth from page quality.
- Website candidate identity is structural when it shows exact URL, section
  label, discovery source, and sitemap freshness hints. Do not use those fields
  as semantic quality scores.
- Semantic examples: relevance, novelty, source fit, faithfulness in prose,
  synthesis quality, contradiction interpretation, and route quality.
- If no model route exists for a semantic task, label the fallback as structural
  ordering. Do not present keyword or length heuristics as quality ranking.
- Judge in the mode the evidence supports: coarse absolute faithfulness
  (faithful/minor/unfaithful, anchor-free) for GROUNDING, pairwise comparison for
  RANKING among the faithful. Never a fine-grained absolute "quality score" and
  never argmax over judge scores; that is the brittle proxy wearing a model's
  clothing (see `docs/design/model-judgment-vs-brittle-fallbacks.md`).
- Pairwise is where self-preference bias is large, so a pairwise judge must be
  neutral (a different family than every candidate it compares). For
  correct-then-verify shapes (maker-checker), do not pairwise-rank at all: the
  cross-family correction is the deliverable, so verify it with the
  family-bias-resistant faithfulness floor. Reserve pairwise for picking among
  independent candidates (ensemble), and only with a neutral judge.

## Testing and Coverage

- Pick coverage targets from a fresh `pytest --cov=distill --cov-branch
  --cov-report=json` measurement, lowest-covered CORE module first (`pipeline/`,
  `library/`, `concepts/`, `llm/`, `ingestors/`); the roadmap accepts thinner
  coverage on presentation code (`web/`, dashboards). Write tests that assert
  real behavior, never coverage-padding, and stop before contriving a test for
  an unreachable branch.
- Test import-guarded provider ladders by injecting a fake module into
  `sys.modules` (e.g. a stand-in `faster_whisper` exposing `WhisperModel` /
  `BatchedInferencePipeline`) and patching the module's own `_pick_device` /
  `_pick_batch_size` helpers to isolate the routing under test. Set
  `sys.modules["dep"] = None` to force the ImportError branch.
- The branch-coverage floor (`--cov-fail-under` in `.github/workflows/ci.yml`)
  is ratcheted up-only but keeps ~1 point of headroom against per-run
  branch-selection jitter. Ubuntu CI measures lower than a local Windows run, so
  bump the floor from the CI log's "Total coverage" number, not the local one,
  and only when cumulative gains preserve the headroom.
- Keep the one `str -> SecretStr` config construction behind a single test
  helper rather than repeating it at each call site.
- For SSRF / retry network helpers, drive the retry state machine offline by
  patching the module's opener (`net._SSRF_SAFE_OPENER.open`) and `time.sleep`,
  and use a literal public-IP URL to pass the SSRF guard without DNS; force the
  fail-closed resolution branches by monkeypatching `socket.getaddrinfo` to
  raise `gaierror` or return private / unparseable addresses.

## Context Engineering

- Treat prompt context as working memory and the corpus as durable memory.
  Default agent-facing surfaces should return paths, ids, previews, or
  drill-down commands before full payloads.
- Preserve source identity, receipts, confidence labels, and sidecar paths in
  any context that carries claims into analysis, synthesis, reports, or loops.
- Use `distill costs` biggest-prompts telemetry to measure prompt-budget impact
  after prompt, MCP, report, or pipeline rewrites.
- Compact by keeping evidence first and trimming wording second. Do not drop
  provenance or confidence labels to save tokens.
- Prefer structured deltas, append logs, merge steps, and snapshots over opaque
  summary rewrites for durable knowledge.
- Clear stale intermediate context in iterative loops unless the current step
  still needs it.

## Cost Policy

- External spend budget for this loop is `$5.00`; current spend is `$0.06`.
- Default to local tests and static checks. Do not make cloud/API calls unless
  the task truly requires them.
- Use the global one-run form as `distill --cost-mode no-metered <command>`.
  Profile preview commands should carry this form when the profile declares
  `cost_mode: no-metered`.
- In `no-metered`, local Ollama and LM Studio are allowed by topology.
  API-billed routes and ambiguous adapter routes must fail closed.
- Blocked route reports include provider, workload, route cost class, reason,
  proof requirements when applicable, and a paid-ok retry hint for intentional
  metered runs.
- Plan-quota CLI routes are not no-metered defaults until adapter doctor,
  support statement, included-plan auth proof, adapter-specific workload
  wiring, complete usage ledger, and eval proof exist.
- Use `distill.eval.graduation.adapter_route_graduation_decision()` as the
  structural gate that combines adapter doctor readiness with model-judged eval
  evidence. It is still not live route selection by itself.
- Cost-log rows include `usage_ledger`, `by_provider`, and `by_route_class`.
  Keep no-metered local usage visible even when `actual_cost` is `0.0`.
- Per-call prompt telemetry belongs in `library/.distill/telemetry.jsonl`.
  `distill costs` should surface the biggest prompts from that file rather
  than mixing call-level rows into run-level `cost_log.jsonl`.
- Approved profile runs write a zero-dollar `profile-run` row so orchestration
  attempts show up even if child commands use local or deterministic paths.

## Recurring Profiles

- `distill profile preview <name>` is the non-mutating source resolver.
- `distill profile run <name>` is approval-gated. Without `--yes`, it returns
  the command plan and state path without executing or writing run state.
- With `--yes`, profile run executes generated `distill ...` argv rows through
  subprocesses with shell disabled and records command results under
  `.distill/profiles/<profile>/run_state.json`.
- Profile run JSON includes `next_actions` rows with argv commands, approval
  class, write scope, verifier, and loop metadata. External runners should use
  those rows instead of parsing console output.
- `distill audit all` includes local recurring profile health from profile
  files and run state: invalid YAML/schema, missing goals, missing or stale
  runs, recorded failures, invalid state, and thin local corpora.
- Exact feed items and YouTube videos can be marked complete after a successful
  run. Standing seeds such as feeds, channels, domains, repositories, and saved
  queries must stay repeatable.

## Batch Progress

- Use `distill.pipeline.summary.BatchProgress` for long non-video CLI loops
  instead of one-off progress strings.
- Use `ETATracker` for video loops. Its `progress_str(..., cost_tracker=...)`
  form carries completed count, failed count, running spend, and ETA without
  replacing the existing transcript and analysis phase labels.
- Wire `discover` paper and site ingest through `BatchProgress`; its video
  branch inherits `ETATracker` through the shared learning flow.
- Wire default report phase progress, section writing progress, and QA rewrite
  progress through `BatchProgress`.
- Progress lines should expose phase, item count, completed count, failed
  count, running spend, and ETA when available.
- Site ingest result counts are structural: crawled pages, analyzed pages,
  unchanged-page reuse, and empty crawls. Surface them as skip/progress
  reasons, not page quality judgments.
- Use `distill --quiet <command>` for external loops that only need exit codes,
  artifacts, or JSON. Use `distill --verbose <command>` for debug logging.
- Keep the `distill` logger level at DEBUG. Console and file handler levels own
  visibility, so `library/.distill/distill.log` can capture DEBUG records even
  when console output stays warning-only.
- Keep recurring workflow examples in rendered command help for preview,
  approval, ingest, audit, next-action, and export paths.
- Preserve JSON stdout purity by routing human progress through the shared
  `distill._console.console`.
- Per-item failures should become structured run issues and the loop should
  continue when re-running is convergent. `BudgetExceededError` remains a hard
  stop.
- `_logic.py` is gone. New command code imports canonical owners directly, and
  tests patch those owners in the same slice. Do not add imports or patch strings
  for `distill.commands._logic`.
- CLI and web dashboard data flows through
  `distill.pipeline.dashboard_data.dashboard_snapshot`. Keep
  `distill.commands.dashboard` focused on presentation, and patch
  `_dashboard_snapshot` when testing CLI home-screen snapshot wiring.
- Site ingest now belongs to `distill.commands._site_ingest`; patch that module
  for crawl, analysis, attachment, hash, and site-synthesis behavior.
- Paper artifact writing now belongs to `distill.commands._paper_artifacts`;
  patch `write_paper_artifacts` there for paper receipt and insight emission.
- Post-ingest concept playbook wiring now belongs to
  `distill.commands._concept_ingest`; patch `run_concepts_after_ingest` there.
- Installed package version lookup now belongs to `distill._version`; import
  `get_version` there rather than reaching through `_logic`.
- Channel-list display truncation now belongs to `distill.commands._helpers`;
  import `_truncate_channel_list` there rather than reaching through `_logic`.
- Shared video helpers now belong to `distill.commands._helpers`; import or
  patch `ensure_channel_context`, `process_video`, and `run_scope_report` there.
- Learning query expansion and video selection now belong to
  `distill.commands._learning`; patch `_expand_learning_queries`,
  `_expand_paper_queries`, search/enrichment collaborators, rerank helpers, and
  `_select_learning_videos` there rather than through `_logic` or `_cli_impl`.
- Learning-flow wrappers now belong to `distill.commands._learning`; patch
  `_preview_learning_selection`, `_run_learning_command`,
  `_process_learning_selection`, and `_generate_and_export_topic_brief` there
  rather than through `_logic` or `_cli_impl`.
- Discover planning and ingest bridges now belong to
  `distill.commands._discover_flow`; command-level helper aliases are
  re-exported through `distill.commands.discover`. Patch
  `_discover_generate_queries`, `_discover_fetch_videos`, `_discover_rerank`,
  `_display_ranked_discover`, `_discover_sizing_flow`, and
  `_discover_ingest_set` on the command module when testing command routing.
  Patch paper/site analysis collaborators and `_process_learning_selection` on
  `_discover_flow` when testing helper internals.
- The bare `distill` root callback now belongs to `distill.commands.root`.
  Patch root-level `get_config`, `show_banner`, and shared console behavior on
  that module for home-screen tests rather than through `_logic` or
  `_cli_impl`.
- `ask`, `audit`, `claude-md`, `concepts`, `ingest`, `eval`, `process`, and
  `view` no longer import `_logic`; patch their own modules or canonical helper
  owners. Private legacy compatibility exports now live in `distill._cli_impl`.

## Validation

- For code or docs changes, run:
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run pytest -q --cov=distill --cov-fail-under=89`
- If the full coverage run exceeds a short command timeout, rerun with a longer
  timeout before treating it as a failure.

## Pyright Strict Ratchet

Advancing the 1.0 "Pyright strict across the full surface" gate, one module or
package at a time. CI blocks strict only on `distill/llm/`; everything else is
advisory until a module opts in with a top-of-file `# pyright: strict` (place it
after the module docstring, before `from __future__ import annotations`). Verify
a target with `uv run pyright <file>` after adding the marker.

The recurring fixes (all proven on `concepts/` and `claims/`):

- **Bare generics.** `dict` / `list` / `set` annotations need arguments. A
  `to_dict` is `dict[str, Any]`; a JSONL row list is `list[dict[str, Any]]`.
- **Empty literals lose their type.** `set()` in a typed-return branch is
  `set[Unknown]`; write `set[str]()`. Same for `dict`/`list` literals where the
  surrounding type is not inferable.
- **JSON boundaries.** `json.loads(...)` is `Any`; after an `isinstance(x, dict)`
  (or `list`) guard the value narrows to `dict[Unknown, Unknown]`. Bind it once:
  `row = cast("dict[str, Any]", x)` and use `row` for every downstream call
  (including any `repr`), so no `Unknown` propagates. Prefer making a typed
  reader actually filter+cast non-matching rows over scattering `isinstance`
  guards in each consumer - that makes the return type honest *and* keeps the
  malformed-input robustness.
- **dataclass `field(default_factory=list|dict)`** reads as `list[Unknown]`
  under strict. Use the house ignore with justification (see
  `doctor/adapters.py`): `# pyright: ignore[reportUnknownVariableType] dataclass
  default_factory appears as ... under strict; usage confirms ...`.
- **Redundant runtime `isinstance` on an already-typed param** is flagged
  (`reportUnnecessaryIsInstance`). Removing it is consistent with parse-don't-
  validate when the boundary already parsed the value; keep value-based guards.

These are type-honesty changes, not behavior changes - validate with the
module's own unit suite plus the full coverage gate before pushing.

## Adapter Doctor

- `distill doctor --adapters` is read-only. It may run version/help commands,
  but it must not run adapter workloads.
- Adapter config scanning reports marker names only. Never print provider
  config secret values in doctor output, docs, logs, or tests.
- Adapter JSON auth-command probes also report marker names only. Never print
  auth command secret values or account identifiers in doctor output, docs,
  logs, or tests.
- Future CLI adapters must write or emit the strict `adapter-result.v1`
  manifest shape from `distill.doctor.adapter_manifest`. Keep writes scratch
  relative, include a usage signal, and fail closed on metered auth in
  `no-metered`.
- Use `distill.doctor.adapter_result_writer.write_adapter_result_manifest()`
  when wrapping captured CLI output. It hashes workload inputs and writes the
  validated manifest, but the caller must supply real native usage signals or a
  validated `adapter-native-usage.v1` scratch file.
- Use `distill.doctor.adapter_native_usage.load_adapter_native_usage()` for
  scratch usage files. It requires token counts or native usage metadata and
  rejects unknown adapters, unknown fields, absolute paths, and path escapes.
- Use `distill.doctor.adapter_native_usage.codex_jsonl_native_usage()` for
  captured `codex exec --json` stdout. It parses `turn.completed` usage events
  into the native usage contract, but it does not make Codex route-eligible.
- Use `distill.doctor.adapter_native_usage.claude_json_native_usage()` for
  captured Claude Code JSON or stream JSON stdout. It parses Claude `usage`
  objects into the native usage contract, but it does not make Claude
  route-eligible.
- Use `distill.doctor.adapter_capture.write_codex_captured_result()` after a
  future Codex process exits to write `native-usage.json` and
  `adapter-result.json` from captured JSONL stdout plus `result.txt`. It is
  still not a route eligibility gate.
- Use `distill.doctor.adapter_capture.write_claude_captured_result()` after a
  future Claude process exits to write `native-usage.json`, `result.txt`, and
  `adapter-result.json` from captured JSON stdout. It is still not a route
  eligibility gate.
- Use `distill.doctor.adapter_capture.write_grok_captured_result()` after a
  future Grok process exits to write `native-usage.json` and
  `adapter-result.json` from captured JSON stdout. It is still not a route
  eligibility gate.
- Use `distill.doctor.adapter_capture.write_gemini_cli_captured_result()` and
  `write_antigravity_captured_result()` for the Gemini-family and Antigravity
  plan-quota CLIs (same pattern, using their native usage parsers). Still not
  route eligibility.
- Use `distill.doctor.adapter_capture.write_stdout_captured_result()` for
  adapters that only expose useful stdout. It writes `result.txt` and the
  result manifest, but it requires a real validated `adapter-native-usage.v1`
  file and does not invent usage signals.
- If an adapter manifest reports `quota`, `rate_limit`, or `rate-limit`, it
  must include structured `quota_stop` metadata instead of relying on free text.
- Future adapter workloads must use the strict `adapter-workload.v1` package
  parser before any CLI receives source paths. Keep paths scratch relative and
  reject read-only workloads that declare writes.
- Future CLI adapter runners must snapshot scratch files before execution and
  use `check_adapter_workspace_writes()` after parsing the manifest. Missing
  declared outputs and unexpected new files are blockers.
- Use `distill.doctor.adapter_workload_runner.run_adapter_workload()` for
  scratch workload experiments. It composes `adapter-workload.v1` with the
  scratch runner and blocks read, write, or cost-mode drift. Use its
  `stdin_path` field when a command should receive a staged scratch file on
  stdin without shell piping.
- `distill.doctor.adapter_commands.plan_adapter_command()` may record future
  argv shapes, staged prompt paths, schema paths, result capture paths, and
  allowed scratch capture files, but a command plan is not eligible while
  blockers remain. Codex, Claude, Grok, Gemini, and Antigravity read-only
  plans are blocked until support proof, auth proof, native schema enforcement
  where the CLI supports it, and eval route gates exist.
- Use `distill.doctor.adapter_commands.inline_adapter_command_schema()` to
  materialize Claude schema paths into argv only after the schema file is
  staged inside scratch and parsed as a JSON object.
- Use `distill.doctor.adapter_runner.run_adapter_command()` for future adapter
  commands. It runs exact argv arrays with shell disabled, strips known
  metered API-key environment variables, enforces a timeout, and validates the
  manifest plus scratch writes. It is not a route graduation gate by itself.
- Use `distill.doctor.adapter_ledger.adapter_manifest_ledger_record()` only
  after a manifest has validated. It records included-plan usage as zero-dollar
  ledger data, not as route eligibility proof.
- Planned support statements remain blocked until official auth proof, adapter
  workload wiring, native usage ledger signals, and eval evidence exist.
- Treat `support_statement_detail.no_metered_current=false` as a hard block for
  plan-quota routing, even when local binary and config probes look usable.
- API-key environment blockers keep plan-quota candidates out of no-metered
  routing. Gemini-family routes must treat both `GEMINI_API_KEY` and
  `GOOGLE_API_KEY` as blockers.
- Website crawl boundaries are structural URL rules. Use `crawl_prefix` when a
  site seed should stay under a specific path branch, and do not replace source
  fit or page quality judgment with path heuristics.
- Site-batch preview and JSON `mode` fields are structural run planning. Use
  them to show exact-page versus shallow-crawl behavior before writes, not to
  judge whether a page is useful or relevant. Reject unsupported mode names
  during seed-file loading instead of widening crawl behavior silently.
- Global `--json` on `site-batch --preview` returns the same resolved plan rows
  in the standard JSON envelope. Keep it free, non-mutating, and aligned with
  the human preview.
- MCP `site_batch` accepts relative JSON seed files inside the library root and
  honors the same exact-page, shallow-crawl, crawl-prefix, and unsupported-mode
  handling as the CLI. Direct URL lists and TXT seed files stay exact-page by
  default.
- MCP `site_batch(preview=true)` is a structural, non-mutating plan inspection
  path. It skips model checks, crawling, writes, and spend, and it is allowed
  through read-only MCP mode.
