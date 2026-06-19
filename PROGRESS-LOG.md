# Progress Log

## 2026-06-19

### Cycle 33 - Biggest Prompt Cost Surface

- External spend: `$0.00`.
- Added a biggest-prompts view to `distill costs` from
  `library/.distill/telemetry.jsonl`.
- `distill costs --json` now includes `biggest_prompts` even when run-level
  cost history is absent, so external loops can inspect prompt regressions
  without scraping console output.
- The local web costs page now shows the same biggest-prompts telemetry beside
  topic, source, and recent-run cost data.
- Hardened `top_n_by_tokens()` so telemetry rows with non-numeric token counts
  are skipped instead of breaking cost inspection.
- Updated README, ROADMAP, detailed roadmap, usage docs, changelog, and loop
  skills to keep the run-level `cost_log.jsonl` and per-call
  `telemetry.jsonl` boundary explicit.
- Targeted validation:
  - `uv run pytest -q tests\unit\llm\test_telemetry.py::test_invalid_token_type_lines_are_skipped tests\unit\commands\test_cli_wiring.py::TestExportOpenCostsAndStatus::test_costs_reads_log_and_shows_breakdown tests\unit\commands\test_cli_json.py::TestJsonCosts::test_costs_json_includes_biggest_prompts tests\unit\web\test_web_server.py::test_web_routes_render_dashboard_topic_channel_video_and_watchlist` passed: 4 passed, 1 warning.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed: 445 files already formatted.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed: 2497
    passed, 8 deselected, 1 warning, 82.48% coverage.

### Next

- Continue with local roadmap items that do not depend on unavailable adapter
  support statements: likely live mixed-source progress, report pipeline
  compaction measurement, or trusted-site discovery.

### Cycle 34 - Context Engineering Contributor Rules

- External spend: `$0.00`.
- Added a `docs/CONTRIBUTING.md` context-engineering section so prompt, MCP,
  report, pipeline, and loop changes have concrete contribution rules.
- The new rules cover paths before payloads, provenance in context,
  biggest-prompts telemetry for prompt-budget measurement, evidence-preserving
  compaction, structured deltas, stale intermediate-context clearing, and
  model-owned semantic judgment.
- Marked the detailed roadmap context-engineering documentation item complete.
- Updated changelog and loop skills so future cycles reuse the same posture.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed: 445 files already formatted.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed: 2497
    passed, 8 deselected, 1 warning, 82.48% coverage.

### Next

- Continue local roadmap work with either tool-result clearing in iterative
  loops, effective-context regression tests, or live batch progress.

### Cycle 35 - Batch Progress for Papers and Site Batch

- External spend: `$0.00`.
- Added `BatchProgress` for long non-video CLI loops.
- `distill papers` now prints per-paper phase, item count, completed count,
  failed count, running spend, and ETA when enough items have completed.
- `distill site-batch` now prints the same seed-level progress surface.
- `distill site-batch` now isolates unexpected seed-level exceptions as
  structured `site-ingest` run issues and continues with later seeds. The spend
  cap remains a hard stop.
- Marked the live mixed-source progress roadmap item partial, with `discover`,
  `latest`, and `catch-up` still remaining.
- Targeted validation:
  - `uv run ruff check distill\commands\_site_batch.py distill\commands\discover.py distill\pipeline\summary.py distill\commands\papers.py tests\unit\pipeline\test_summary.py tests\unit\commands\test_cli_wiring.py` passed.
  - `uv run pytest -q tests\unit\test_module_sizes.py::test_no_module_exceeds_cap_except_shrinking_allowlist tests\unit\pipeline\test_summary.py::test_batch_progress_formats_item_status_and_spend tests\unit\commands\test_cli_wiring.py::TestWatchCommands::test_papers_command_searches_and_writes_synthesis tests\unit\commands\test_cli_wiring.py::TestWatchCommands::test_site_batch_progress_continues_after_seed_failure` passed: 4 passed.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed: 446 files already formatted.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed: 2499
    passed, 8 deselected, 1 warning, 82.61% coverage.

### Next

- Extend the same batch progress surface to `discover`, `latest`, and
  `catch-up`, then consider a verbosity dial once all loops share the helper.

### Cycle 0 - Orientation and Doc Truth-Up

- External spend: `$0.00`.
- Read tracked Markdown inventory and the controlling roadmap/design docs.
- Verified that `README.md` and `docs/mcp.md` matched the live 24-tool MCP
  surface.
- Fixed stale roadmap wording that still described the earlier 22 to 21 MCP
  consolidation count.
- Ran quality gates after the doc fix:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed after rerun
    with a longer timeout: 2358 passed, 8 deselected, total coverage 81.92%.

### Cycle 1 - Cost-Policy Foundation

- External spend: `$0.00`.
- Committed as `7e66102` (`Add no-metered cost policy foundation`).
- Selected the first 0.19 implementation slice: rule-owned no-metered cost-mode
  parsing and router enforcement.
- Added a pure route-policy module for `auto`, `no-metered`, and `paid-ok`.
- Wired `DISTILL_COST_MODE` through `DistillConfig` and `RouterConfig`.
- Made router validation fail closed before provider calls when `no-metered`
  would use API-billed or ambiguous routes.
- Documented the behavior in README, cost docs, changelog, roadmap, and
  `.env.example`.
- Targeted validation:
  - `uv run pytest -q tests/unit/test_cost_policy.py tests/test_config.py tests/unit/llm/test_router.py` passed.
  - `uv run pytest -q tests/unit/test_cost_policy.py tests/test_config.py tests/unit/llm/test_router.py tests/unit/llm/test_integration.py::test_no_external_distill_imports_in_llm tests/unit/llm/test_integration.py::test_module_size_cap` passed after moving the helper under `distill.llm` and trimming `router.py` below the 500-line cap.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed: 2377 passed,
    8 deselected, coverage 81.95%.

### Next

- Continue with CLI `--cost-mode` overrides, profile-run state, and zero-dollar
  ledger rows.

### Cycle 2 - CLI Cost-Mode Override

- External spend: `$0.00`.
- Committed as `96a9744` (`Add CLI cost mode override`).
- Added a shared `_apply_cost_mode_override` helper that validates
  `auto|no-metered|paid-ok` through the same policy enum as the router.
- Added top-level `distill --cost-mode <mode>` so loops can apply a one-run
  route policy without editing `.env`.
- Updated profile preview command generation so no-metered profiles emit replay
  commands like `distill --cost-mode no-metered site ...`.
- Targeted validation:
  - `uv run ruff check distill\commands\_helpers.py distill\commands\_logic.py distill\pipeline\profile_preview.py tests\unit\pipeline\test_profile_preview.py tests\unit\commands\test_profile_command.py` passed.
  - `uv run ruff format --check distill\commands\_helpers.py distill\commands\_logic.py distill\pipeline\profile_preview.py tests\unit\pipeline\test_profile_preview.py tests\unit\commands\test_profile_command.py` passed after formatting.
  - `uv run pytest -q tests\unit\pipeline\test_profile_preview.py tests\unit\commands\test_profile_command.py tests\unit\commands\test_helpers.py::TestDetectRampSource tests\unit\llm\test_router.py::test_no_metered_blocks_api_billed_route_before_key_validation` passed: 13 passed.
- Fixed the CLI test to restore `DISTILL_COST_MODE` after exercising the global
  override, and kept `distill/commands/_logic.py` at the 1,512-line ratchet.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed: 2379 passed,
    8 deselected, coverage 81.94%.

### Next

- Continue with profile-run state and zero-dollar ledger rows.

### Cycle 3 - Profile Run State

- External spend: `$0.00`.
- Added `distill profile run <name|path>` as an approval-gated runner over the
  existing profile preview command list.
- `profile run` without `--yes` returns a human or JSON plan and does not
  execute commands or write state.
- `profile run --yes` executes the generated `distill ...` argv rows with
  shell disabled, captures exit codes plus stdout and stderr tails, and writes
  state under `.distill/profiles/<profile>/run_state.json`.
- Exact feed items and exact YouTube videos are marked complete on success.
  Standing seeds such as feeds, channels, domains, repositories, and saved
  queries remain repeatable so recurring profiles keep checking for new
  material.
- Targeted validation:
  - `uv run ruff check distill\pipeline\profile_run.py distill\commands\profile.py tests\unit\pipeline\test_profile_run.py tests\unit\commands\test_profile_command.py` passed.
  - `uv run ruff format --check distill\pipeline\profile_run.py distill\commands\profile.py tests\unit\pipeline\test_profile_run.py tests\unit\commands\test_profile_command.py` passed after formatting `distill\commands\profile.py`.
  - `uv run pytest -q tests\unit\pipeline\test_profile_run.py tests\unit\commands\test_profile_command.py` passed: 8 passed.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed after rerun
    with a longer timeout: 2384 passed, 8 deselected, coverage 81.84%.

### Next

- Continue with complete usage ledger rows for no-metered and zero-dollar
  profile usage.

### Cycle 4 - Zero-Dollar Usage Ledger

- External spend: `$0.00`.
- Extended `save_run_log` rows with provider breakdowns, route-class
  breakdowns, no-metered LLM call counts, local transcription counts, and a
  `usage_ledger` object.
- Updated `CostTracker.summary_dict()` to surface metered and no-metered call
  counts plus provider usage.
- Made approved `profile run` executions write a zero-dollar `profile-run`
  orchestration row with profile, topic, cost mode, selected, skipped,
  succeeded, and failed counts.
- Targeted validation:
  - `uv run ruff check distill\pipeline\costs.py distill\pipeline\profile_run.py tests\unit\pipeline\test_costs.py tests\unit\pipeline\test_profile_run.py` passed.
  - `uv run ruff format --check distill\pipeline\costs.py distill\pipeline\profile_run.py tests\unit\pipeline\test_costs.py tests\unit\pipeline\test_profile_run.py` passed after formatting `distill\pipeline\costs.py` and `tests\unit\pipeline\test_costs.py`.
  - `uv run pytest -q tests\unit\pipeline\test_costs.py tests\unit\pipeline\test_profile_run.py` passed: 33 passed.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed after a final
    post-format rerun: 2385 passed, 8 deselected, coverage 81.87%.

### Next

- Continue with richer blocked-route reporting or profile next-action handoff.

### Cycle 5 - Structured Route-Block Reports

- External spend: `$0.00`.
- Completed richer no-metered route-block reporting for the cost-policy layer.
- Extended route-policy decisions with workload, recovery hint, and proof
  requirements.
- Added a structured `route_block_report` helper for loop-readable provider,
  workload, cost class, reason, requirements, and message fields.
- Updated blocked router errors so no-metered failures show the blocked
  provider, workload, cost class, required proof when relevant, and a paid-ok
  retry hint for intentional metered runs.
- Updated README, cost docs, roadmap, changelog, current-state notes, and loop
  skills to mark the no-metered-cost mode slice complete.
- Targeted validation:
  - `uv run ruff check distill\llm\cost_policy.py tests\unit\test_cost_policy.py tests\unit\llm\test_router.py` passed.
  - `uv run ruff format --check distill\llm\cost_policy.py tests\unit\test_cost_policy.py tests\unit\llm\test_router.py` initially requested formatting for `tests\unit\llm\test_router.py`; after formatting, the full format gate passed.
  - `uv run pytest -q tests\unit\test_cost_policy.py tests\unit\llm\test_router.py::test_no_metered_blocks_api_billed_route_before_key_validation tests\unit\llm\test_router.py::test_no_metered_blocks_unproven_agent_route tests\unit\llm\test_router.py::test_no_metered_reports_plan_quota_proof_for_reserved_cli_route` passed: 20 passed.
- Full validation before this log entry:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed: 2388
    passed, 8 deselected, coverage 81.91%.

### Next

- Continue with profile next-action handoff rows or adapter doctor preflight
  scaffolding.

### Cycle 6 - Profile Loop Handoff Rows

- External spend: `$0.00`.
- Extracted the audit next-action dataclasses into
  `distill.pipeline.next_actions` so audit and profile surfaces share one
  structural action contract.
- Added `next_actions` rows to `profile-run.v1` JSON for approval-required
  profile plans and retryable failed profile runs.
- Profile action rows include stable ids, argv commands, approval class,
  estimated cost, expected write scope, verifier command, and loop metadata.
- Preserved explicit YAML profile references in emitted action commands so
  loops can rerun the same profile target without guessing its library name.
- Updated README, usage docs, roadmap, changelog, current-state notes, design
  success criteria, and loop skills.
- Targeted validation:
  - `uv run ruff check distill\pipeline\next_actions.py distill\pipeline\audit.py distill\pipeline\profile_run.py distill\commands\profile.py tests\unit\pipeline\test_audit.py tests\unit\pipeline\test_profile_run.py tests\unit\commands\test_profile_command.py` passed.
  - `uv run ruff format --check distill\pipeline\next_actions.py distill\pipeline\audit.py distill\pipeline\profile_run.py distill\commands\profile.py tests\unit\pipeline\test_audit.py tests\unit\pipeline\test_profile_run.py tests\unit\commands\test_profile_command.py` passed.
  - `uv run pytest -q tests\unit\pipeline\test_audit.py::TestNextActionPlan tests\unit\pipeline\test_profile_run.py tests\unit\commands\test_profile_command.py` passed: 12 passed.

### Next

- Continue with audit-visible profile health or adapter doctor preflight
  scaffolding.

### Cycle 7 - Audit-Visible Profile Health

- External spend: `$0.00`.
- Added deterministic recurring profile health to `distill audit all` through
  the library audit rollup.
- Profile health now reports invalid profile files, missing goal files, missing
  or stale run state, recorded profile command failures, invalid run state, and
  profiles whose local corpus is thin relative to their saved source plan.
- Kept audit local-only and no-spend. Feed, channel, and domain reachability
  checks remain outside this deterministic audit pass.
- Updated README, usage docs, roadmap, changelog, current-state notes, and loop
  skills.
- Targeted validation:
  - `uv run ruff check distill\pipeline\audit.py tests\unit\pipeline\test_library_hygiene.py` passed.
  - `uv run ruff format --check distill\pipeline\audit.py tests\unit\pipeline\test_library_hygiene.py` passed after formatting.
  - `uv run pytest -q tests\unit\pipeline\test_library_hygiene.py tests\unit\pipeline\test_audit.py::test_audit_command_next_actions_json` passed: 9 passed.

### Next

- Continue with adapter doctor preflight scaffolding.

### Cycle 8 - Adapter Doctor Scaffold

- External spend: `$0.00`.
- Added `distill.doctor.adapters`, a pure read-only preflight layer for
  candidate CLI adapter routes.
- Added `distill doctor --adapters` with human and JSON output.
- The adapter report now classifies Codex, Claude, Grok, Gemini CLI,
  Antigravity, and Copilot candidates by binary presence, version/help probes,
  required structured-output flags, API-key environment blockers, route class,
  support-statement status, and no-metered eligibility.
- The scaffold is fail-closed. Planned support statements keep plan-quota
  candidates blocked until auth classification, scratch-manifest enforcement,
  native usage signals, and eval evidence exist. Copilot is reported as a
  credit-metered candidate, not a no-metered default.
- Updated README, usage docs, roadmap, changelog, current-state notes, and loop
  skills.
- Targeted validation:
  - `uv run ruff check distill\doctor\adapters.py distill\commands\doctor.py tests\unit\doctor\test_adapters.py tests\unit\commands\test_cli_json.py` passed.
  - `uv run ruff format --check distill\doctor\adapters.py distill\commands\doctor.py tests\unit\doctor\test_adapters.py tests\unit\commands\test_cli_json.py` passed after formatting.
  - `uv run pytest -q tests\unit\doctor\test_adapters.py tests\unit\commands\test_cli_json.py::TestJsonDoctor::test_doctor_json_adapter_report` passed: 4 passed.

### Next

- Continue adapter doctor auth classification and support-statement fixtures.

### Cycle 9 - Adapter Result Manifest Boundary

- External spend: `$0.00`.
- Added `distill.doctor.adapter_manifest`, a strict parser for future
  `adapter-result.v1` CLI adapter manifests.
- The manifest boundary enforces known adapters, auth class, command class,
  cost mode, prompt and source hashes, elapsed time, usage signals, declared
  read and write paths, output payload, and policy state.
- The parser rejects unsafe scratch-relative write paths, missing usage
  signals, unknown fields, unknown adapters, and no-metered results that carry
  metered auth, API-key blockers, or metered usage allowance.
- `distill doctor --adapters` JSON now includes the manifest contract so
  external loops and future adapter runners can inspect the required shape.
- Updated README, usage docs, roadmap, changelog, current-state notes,
  adapter runbook, and loop skills.
- Targeted validation:
  - `uv run ruff check distill\doctor\adapter_manifest.py distill\doctor\adapters.py distill\commands\doctor.py tests\unit\doctor\test_adapter_manifest.py tests\unit\doctor\test_adapters.py tests\unit\commands\test_cli_json.py` passed.
  - `uv run ruff format --check distill\doctor\adapter_manifest.py distill\doctor\adapters.py distill\commands\doctor.py tests\unit\doctor\test_adapter_manifest.py tests\unit\doctor\test_adapters.py tests\unit\commands\test_cli_json.py` passed after formatting.
  - `uv run pytest -q tests\unit\doctor\test_adapter_manifest.py tests\unit\doctor\test_adapters.py tests\unit\commands\test_cli_json.py::TestJsonDoctor::test_doctor_json_adapter_report` passed: 15 passed.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed: 429 files already formatted.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed: 2405
    passed, 8 deselected, 1 warning, 81.93% coverage.

### Next

- Continue adapter doctor installed-session auth classification and runner-side
  manifest enforcement.

### Cycle 10 - Adapter Auth Marker Classification

- External spend: `$0.00`.
- Added local config auth-marker scanning to `distill doctor --adapters`.
- Adapter doctor now parses known TOML and JSON config files for Codex, Claude,
  Grok, Gemini CLI, and Antigravity, reporting marker names and display paths
  without exposing secret values.
- API-key environment variables and API-key config fields classify the adapter
  auth mode as metered and keep no-metered claims blocked.
- Session markers are reported as evidence only. They do not make a route
  eligible without support statements, runner-side manifest enforcement,
  native usage signals, and eval proof.
- Fixed the adapter doctor test seam so `environ={}` means an empty
  environment instead of falling back to the process environment.
- Updated README, usage docs, roadmap, cost docs, changelog, current-state
  notes, adapter runbook, and loop skills.
- Targeted validation:
  - `uv run ruff check distill\doctor\adapters.py distill\commands\doctor.py tests\unit\doctor\test_adapters.py tests\unit\commands\test_cli_json.py` passed.
  - `uv run ruff format --check distill\doctor\adapters.py distill\commands\doctor.py tests\unit\doctor\test_adapters.py tests\unit\commands\test_cli_json.py` passed after formatting.
  - `uv run pytest -q tests\unit\doctor\test_adapters.py tests\unit\commands\test_cli_json.py::TestJsonDoctor::test_doctor_json_adapter_report` passed: 7 passed.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed: 429 files already formatted.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed: 2408
    passed, 8 deselected, 1 warning, 81.98% coverage.

### Next

- Continue official installed-session auth proof and runner-side manifest
  enforcement.

### Cycle 11 - Adapter Scratch Write Checks

- External spend: `$0.00`.
- Added before/after scratch workspace write-check helpers to
  `distill.doctor.adapter_manifest`.
- Future adapter runners can snapshot staged source files before execution,
  parse `adapter-result.v1` afterward, and reject missing declared outputs or
  unexpected new scratch files.
- The manifest contract exposed by `distill doctor --adapters` now advertises
  the workspace write-check requirements.
- Updated README, usage docs, roadmap, cost docs, changelog, current-state
  notes, adapter runbook, and loop skills.
- Targeted validation:
  - `uv run ruff check distill\doctor\adapter_manifest.py tests\unit\doctor\test_adapter_manifest.py` passed.
  - `uv run ruff format --check distill\doctor\adapter_manifest.py tests\unit\doctor\test_adapter_manifest.py` passed.
  - `uv run pytest -q tests\unit\doctor\test_adapter_manifest.py` passed: 13 passed.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed: 429 files already formatted.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed: 2410
    passed, 8 deselected, 1 warning, 81.99% coverage.

### Next

- Continue official installed-session auth proof and read-only adapter runner
  integration.

### Cycle 12 - Scratch-Only Adapter Runner Primitive

- External spend: `$0.00`.
- Added `distill.doctor.adapter_runner`, a generic scratch-only runner
  primitive for future CLI adapter integrations.
- The runner accepts exact argv arrays, runs with shell disabled, strips known
  metered API-key environment variables, enforces a timeout, captures bounded
  stdout and stderr tails, parses `adapter-result.v1`, and applies scratch
  write checks.
- The runner is not wired into provider routing and does not make any
  plan-quota CLI route eligible. It is a rule-owned boundary for future
  adapter-specific workload wiring and eval fixtures.
- Updated README, usage docs, roadmap, cost docs, changelog, current-state
  notes, adapter runbook, and loop skills.
- Targeted validation:
  - `uv run ruff check distill\doctor\adapter_runner.py tests\unit\doctor\test_adapter_runner.py tests\unit\doctor\test_adapter_manifest.py` passed.
  - `uv run ruff format --check distill\doctor\adapter_runner.py tests\unit\doctor\test_adapter_runner.py tests\unit\doctor\test_adapter_manifest.py` passed after formatting.
  - `uv run pytest -q tests\unit\doctor\test_adapter_runner.py tests\unit\doctor\test_adapter_manifest.py` passed: 18 passed.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed: 431 files already formatted.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed: 2415
    passed, 8 deselected, 1 warning, 81.98% coverage.

### Next

- Continue official installed-session auth proof and adapter-specific read-only
  workload wiring.

### Cycle 16 - Adapter Workload Package Boundary

- External spend: `$0.00`.
- Added `distill.doctor.adapter_workload`, a strict `adapter-workload.v1`
  parser for future CLI adapter input packages.
- The package boundary validates scratch-relative prompt paths, source paths,
  output-schema paths, result-manifest paths, allowed write paths, workload
  kind, command class, cost mode, positive limits, and metadata shape.
- `distill doctor --adapters` JSON now exposes both the result-manifest
  contract and the workload-package contract for external loops.
- Tightened adapter result-manifest path normalization so raw `.` path segments
  cannot be normalized away before validation.
- This does not execute any plan-quota workload. It creates the checked input
  boundary needed before read-only adapter prototypes can be wired safely.
- Updated README, usage docs, roadmap, cost docs, changelog, current-state
  notes, adapter runbook, recurring profile design notes, and loop skills.
- Targeted validation:
  - `uv run ruff check distill\doctor\adapter_workload.py distill\doctor\adapter_manifest.py distill\doctor\adapters.py tests\unit\doctor\test_adapter_workload.py tests\unit\doctor\test_adapter_manifest.py tests\unit\doctor\test_adapters.py tests\unit\commands\test_cli_json.py` passed.
  - `uv run ruff format --check distill\doctor\adapter_workload.py distill\doctor\adapter_manifest.py distill\doctor\adapters.py tests\unit\doctor\test_adapter_workload.py tests\unit\doctor\test_adapter_manifest.py tests\unit\doctor\test_adapters.py tests\unit\commands\test_cli_json.py` passed after formatting.
  - `uv run pytest -q tests\unit\doctor\test_adapter_workload.py tests\unit\doctor\test_adapter_manifest.py tests\unit\doctor\test_adapters.py tests\unit\commands\test_cli_json.py::TestJsonDoctor::test_doctor_json_adapter_report` passed: 37 passed.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed: 435 files already formatted.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed: 2435
    passed, 8 deselected, 1 warning, 82.09% coverage.

### Next

- Continue official installed-session auth proof and adapter-specific read-only
  workload execution.

### Cycle 17 - Checked Adapter Workload Runner

- External spend: `$0.00`.
- Added `distill.doctor.adapter_workload_runner`, which composes a checked
  `adapter-workload.v1` package with the scratch-only adapter runner.
- The workload runner executes exact argv arrays only in scratch and blocks
  result manifests that read outside the declared workload package, write
  outside declared outputs, or report a different cost mode.
- Tightened `adapter-result.v1` so read-only result manifests cannot declare
  written files.
- This still does not make any plan-quota route live. It is the checked
  execution primitive needed before adapter-specific command templates and
  eval fixtures can be wired.
- Updated README, usage docs, roadmap, cost docs, changelog, current-state
  notes, adapter runbook, recurring profile design notes, and loop skills.
- Targeted validation:
  - `uv run ruff check distill\doctor\adapter_manifest.py distill\doctor\adapter_workload.py distill\doctor\adapter_workload_runner.py tests\unit\doctor\test_adapter_manifest.py tests\unit\doctor\test_adapter_workload.py tests\unit\doctor\test_adapter_workload_runner.py tests\unit\doctor\test_adapter_runner.py` passed.
  - `uv run ruff format --check distill\doctor\adapter_manifest.py distill\doctor\adapter_workload.py distill\doctor\adapter_workload_runner.py tests\unit\doctor\test_adapter_manifest.py tests\unit\doctor\test_adapter_workload.py tests\unit\doctor\test_adapter_workload_runner.py tests\unit\doctor\test_adapter_runner.py` passed after formatting.
  - `uv run pytest -q tests\unit\doctor\test_adapter_manifest.py tests\unit\doctor\test_adapter_workload.py tests\unit\doctor\test_adapter_workload_runner.py tests\unit\doctor\test_adapter_runner.py` passed: 41 passed.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed: 437 files already formatted.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed: 2441
    passed, 8 deselected, 1 warning, 82.05% coverage.

### Next

- Continue official installed-session auth proof and adapter-specific command
  templates for read-only workload prototypes.

### Cycle 18 - Blocked Codex Command Planner

- External spend: `$0.00`.
- Added `distill.doctor.adapter_commands`, a command-plan layer for future CLI
  adapter workload runs.
- The first template records the future Codex read-only argv:
  `codex exec --sandbox read-only --ephemeral --json --output-schema ... --output-last-message result.txt -`.
- The plan deliberately remains blocked until native `adapter-result.v1`
  manifest writing, current support proof, installed-session auth proof, and
  eval evidence exist. It also inherits adapter doctor blockers such as missing
  flags or ineligible cost mode.
- Updated README, usage docs, roadmap, cost docs, changelog, current-state
  notes, adapter runbook, recurring profile design notes, and loop skills.
- Targeted validation:
  - `uv run ruff check distill\doctor\adapter_commands.py tests\unit\doctor\test_adapter_commands.py distill\doctor\adapter_workload.py tests\unit\doctor\test_adapter_workload.py` passed.
  - `uv run ruff format --check distill\doctor\adapter_commands.py tests\unit\doctor\test_adapter_commands.py distill\doctor\adapter_workload.py tests\unit\doctor\test_adapter_workload.py` passed after import fixing.
  - `uv run pytest -q tests\unit\doctor\test_adapter_commands.py tests\unit\doctor\test_adapter_workload.py` passed: 16 passed.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed: 439 files already formatted.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed: 2445
    passed, 8 deselected, 1 warning, 82.08% coverage.

### Cycle 19 - Native Adapter Result Writer

- External spend: `$0.00`.
- Added `distill.doctor.adapter_result_writer`, a native writer for strict
  `adapter-result.v1` scratch manifests.
- The writer hashes the workload prompt and source files, reads captured CLI
  output from scratch, requires caller-supplied token or native usage signals,
  records quota-stop metadata when present, validates the payload through the
  manifest boundary, and writes stable JSON to the workload's manifest path.
- Extended the workload runner so read-only command templates can declare
  capture files such as `result.txt` while still blocking undeclared scratch
  writes.
- Updated the Codex command planner blocker from missing manifest writer to
  missing adapter-specific capture wiring, keeping the route ineligible until
  auth proof, native usage collection, support proof, and eval evidence exist.
- Updated README, usage docs, roadmap, cost docs, changelog, current-state
  notes, adapter runbook, recurring profile design notes, and loop skills.
- Targeted validation:
  - `uv run ruff check distill\doctor\adapter_result_writer.py distill\doctor\adapter_workload_runner.py distill\doctor\adapter_commands.py tests\unit\doctor\test_adapter_result_writer.py tests\unit\doctor\test_adapter_workload_runner.py tests\unit\doctor\test_adapter_commands.py` passed.
  - `uv run ruff format --check distill\doctor\adapter_result_writer.py distill\doctor\adapter_workload_runner.py distill\doctor\adapter_commands.py tests\unit\doctor\test_adapter_result_writer.py tests\unit\doctor\test_adapter_workload_runner.py tests\unit\doctor\test_adapter_commands.py` passed: 6 files already formatted.
  - `uv run pytest -q tests\unit\doctor\test_adapter_result_writer.py tests\unit\doctor\test_adapter_workload_runner.py tests\unit\doctor\test_adapter_commands.py` passed: 16 passed.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed: 441 files already formatted.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed: 2452
    passed, 8 deselected, 1 warning, 82.14% coverage.

### Next

- Continue adapter-specific capture wiring and native usage collection for
  read-only command templates.

### Cycle 20 - Command-Plan Capture Metadata

- External spend: `$0.00`.
- Extended `AdapterCommandPlan` with staged prompt path, result capture path,
  and allowed scratch capture files so future runner wiring can compose command
  plans with the workload runner without guessing filesystem side effects.
- Updated the Codex read-only plan to expose its `prompt.md` stdin path and
  `result.txt` capture file, and shifted its hard blocker to native usage
  collection.
- Added a blocked Grok read-only command planner using
  `grok --no-auto-update --prompt-file prompt.md --output-format json` with
  no web search, no subagents, no memory, and a single-turn limit.
- Kept all planned adapter routes ineligible. Command plans still require an
  adapter doctor probe and remain blocked until native usage collection,
  support proof, auth proof, and eval evidence exist.
- Updated README, usage docs, roadmap, cost docs, changelog, current-state
  notes, adapter runbook, recurring profile design notes, and loop skills.
- Targeted validation:
  - `uv run ruff check distill\doctor\adapter_commands.py tests\unit\doctor\test_adapter_commands.py` passed.
  - `uv run ruff format --check distill\doctor\adapter_commands.py tests\unit\doctor\test_adapter_commands.py` passed: 2 files already formatted.
  - `uv run pytest -q tests\unit\doctor\test_adapter_commands.py` passed: 5 passed.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed: 441 files already formatted.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed: 2453
    passed, 8 deselected, 1 warning, 82.16% coverage.

### Next

- Continue native usage collection and remaining adapter-specific command
  templates.

### Cycle 21 - Blocked Claude Command Planner

- External spend: `$0.00`.
- Checked the installed Claude CLI help locally with `claude --version` and
  `claude -p --help`; no paid model call was made.
- Extended `AdapterCommandPlan` with `schema_path` so command templates can
  record output-schema inputs even when the adapter needs a future wrapper to
  inline schema JSON.
- Added a blocked Claude read-only command plan using `claude -p` with text
  stdin, JSON output, tools disabled, and session persistence disabled.
- Kept the Claude plan blocked until schema inlining and native usage
  collection exist, and preserved the adapter doctor, support, auth, and eval
  blockers.
- Updated README, usage docs, roadmap, cost docs, changelog, current-state
  notes, adapter runbook, recurring profile design notes, and loop skills.
- Targeted validation:
  - `uv run ruff check distill\doctor\adapter_commands.py tests\unit\doctor\test_adapter_commands.py` passed.
  - `uv run ruff format --check distill\doctor\adapter_commands.py tests\unit\doctor\test_adapter_commands.py` passed: 2 files already formatted.
  - `uv run pytest -q tests\unit\doctor\test_adapter_commands.py` passed: 6 passed.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed: 441 files already formatted.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed: 2454
    passed, 8 deselected, 1 warning, 82.15% coverage.

### Next

- Continue schema inlining, native usage collection, and remaining command
  templates.

### Cycle 22 - Claude Schema Inlining

- External spend: `$0.00`.
- Added `inline_adapter_command_schema()` for deterministic Claude command-plan
  materialization.
- The inliner loads a staged scratch schema file, requires a JSON object,
  inserts compact sorted JSON before Claude's `--tools` argument, rejects
  scratch path escapes, and removes only the schema-inlining blocker.
- Claude command plans still remain blocked on native usage collection plus
  adapter doctor, support, auth, and eval gates.
- Updated README, usage docs, roadmap, changelog, current-state notes, adapter
  runbook, recurring profile design notes, and loop skills.
- Targeted validation:
  - `uv run ruff check distill\doctor\adapter_commands.py tests\unit\doctor\test_adapter_commands.py` passed.
  - `uv run ruff format --check distill\doctor\adapter_commands.py tests\unit\doctor\test_adapter_commands.py` passed: 2 files already formatted.
  - `uv run pytest -q tests\unit\doctor\test_adapter_commands.py` passed: 9 passed.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed: 441 files already formatted.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed: 2457
    passed, 8 deselected, 1 warning, 82.15% coverage.

### Next

- Continue native usage collection and remaining command templates.

### Cycle 23 - Adapter Native Usage Contract

- External spend: `$0.00`.
- Added `distill.doctor.adapter_native_usage`, a strict
  `adapter-native-usage.v1` parser for future CLI adapter usage signals.
- Adapter doctor JSON now exposes the usage contract alongside the workload
  and result-manifest contracts.
- The native result writer can load a validated scratch usage file when writing
  an `adapter-result.v1` manifest.
- Codex, Claude, and Grok command plans now record a standard
  `native-usage.json` capture path while remaining blocked on
  adapter-specific native usage capture, support proof, auth proof, and eval
  evidence.
- Targeted validation:
  - `uv run ruff check distill\doctor\adapter_native_usage.py distill\doctor\adapter_result_writer.py distill\doctor\adapter_commands.py distill\doctor\adapters.py tests\unit\doctor\test_adapter_native_usage.py tests\unit\doctor\test_adapter_result_writer.py tests\unit\doctor\test_adapter_commands.py tests\unit\doctor\test_adapters.py tests\unit\commands\test_cli_json.py` passed.
  - `uv run ruff format --check distill\doctor\adapter_native_usage.py distill\doctor\adapter_result_writer.py distill\doctor\adapter_commands.py distill\doctor\adapters.py tests\unit\doctor\test_adapter_native_usage.py tests\unit\doctor\test_adapter_result_writer.py tests\unit\doctor\test_adapter_commands.py tests\unit\doctor\test_adapters.py tests\unit\commands\test_cli_json.py` passed after formatting two files.
  - `uv run pytest -q tests\unit\doctor\test_adapter_native_usage.py tests\unit\doctor\test_adapter_result_writer.py tests\unit\doctor\test_adapter_commands.py tests\unit\doctor\test_adapters.py tests\unit\commands\test_cli_json.py::TestJsonDoctor::test_doctor_json_adapter_report` passed: 28 passed.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed: 443 files already formatted.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed: 2464
    passed, 8 deselected, 1 warning, 82.24% coverage.

### Next

- Continue adapter-specific native usage capture from real CLI outputs and
  remaining command templates.

### Cycle 24 - Codex JSONL Usage Parser

- External spend: `$0.00`.
- Checked official Codex non-interactive documentation and local
  `codex exec --help`; no Codex model call was made.
- Added `codex_jsonl_native_usage()` to parse `codex exec --json` stdout,
  extract `turn.completed.usage`, sum token fields, preserve cached and
  reasoning token metadata, and return an `adapter-native-usage.v1` record.
- Updated the Codex command-plan blocker to say JSONL usage capture is not yet
  wired into the runner, rather than claiming no parser exists.
- Updated README, usage docs, roadmap, changelog, current-state notes, adapter
  runbook, and loop skills.
- Targeted validation:
  - `uv run ruff check distill\doctor\adapter_native_usage.py distill\doctor\adapter_commands.py tests\unit\doctor\test_adapter_native_usage.py tests\unit\doctor\test_adapter_commands.py` passed.
  - `uv run ruff format --check distill\doctor\adapter_native_usage.py distill\doctor\adapter_commands.py tests\unit\doctor\test_adapter_native_usage.py tests\unit\doctor\test_adapter_commands.py` passed after formatting one file.
  - `uv run pytest -q tests\unit\doctor\test_adapter_native_usage.py tests\unit\doctor\test_adapter_commands.py` passed: 20 passed.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed: 443 files already formatted.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` timed out at
    10 minutes, then passed on rerun with a longer timeout: 2469 passed,
    8 deselected, 1 warning, 82.21% coverage.

### Next

- Continue Codex capture writing, non-Codex native usage capture, and
  remaining command templates.

### Cycle 25 - Codex Capture Writer

- External spend: `$0.00`.
- Added `distill.doctor.adapter_capture`, starting with
  `write_codex_captured_result()` for post-process Codex capture.
- The helper writes a validated `native-usage.json` from captured Codex JSONL
  stdout, then writes an `adapter-result.v1` manifest from `result.txt`,
  workload hashes, and native usage through the shared result writer.
- Recorded that the Codex command-plan blocker still needed workload-runner
  wiring at this stage. Cycle 26 removes that blocker after the hook lands.
- Updated README, usage docs, roadmap, changelog, current-state notes, adapter
  runbook, and loop skills.
- Targeted validation:
  - `uv run ruff check distill\doctor\adapter_capture.py distill\doctor\adapter_commands.py tests\unit\doctor\test_adapter_capture.py tests\unit\doctor\test_adapter_commands.py` passed.
  - `uv run ruff format --check distill\doctor\adapter_capture.py distill\doctor\adapter_commands.py tests\unit\doctor\test_adapter_capture.py tests\unit\doctor\test_adapter_commands.py` passed after formatting one test file.
  - `uv run pytest -q tests\unit\doctor\test_adapter_capture.py tests\unit\doctor\test_adapter_commands.py` passed: 12 passed.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed: 445 files already formatted.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed: 2472
    passed, 8 deselected, 1 warning, 82.21% coverage.

### Next

- Continue non-Codex native usage capture and remaining command templates.

### Cycle 26 - Workload Runner Capture Hooks

- External spend: `$0.00`.
- Added an optional post-process capture hook to the scratch adapter runner.
  The hook runs only after a successful exact-argv process and before manifest
  loading, so captured CLI output can become the validated manifest the runner
  already checks.
- Threaded the hook through `run_adapter_workload()` as a workload-aware
  callback receiving the parsed `adapter-workload.v1` package.
- Added tests that run a simulated Codex JSONL process through the real
  `write_codex_captured_result()` helper, verifying `native-usage.json`,
  `adapter-result.v1`, and scratch write checks through the workload runner.
- Capture failures now surface as explicit blocked reasons and still require a
  valid result manifest before a run can pass.
- Removed the stale Codex command-plan blocker for workload-runner capture
  wiring. The route remains blocked by adapter doctor, support, auth, and eval
  gates.
- Updated README, usage docs, roadmap, changelog, current-state notes, adapter
  runbook, and loop skills.
- Targeted validation:
  - `uv run ruff check distill\doctor\adapter_runner.py distill\doctor\adapter_workload_runner.py distill\doctor\adapter_commands.py tests\unit\doctor\test_adapter_workload_runner.py tests\unit\doctor\test_adapter_commands.py` passed.
  - `uv run ruff format --check distill\doctor\adapter_runner.py distill\doctor\adapter_workload_runner.py distill\doctor\adapter_commands.py tests\unit\doctor\test_adapter_workload_runner.py tests\unit\doctor\test_adapter_commands.py` passed after formatting one file.
  - `uv run pytest -q tests\unit\doctor\test_adapter_runner.py tests\unit\doctor\test_adapter_workload_runner.py tests\unit\doctor\test_adapter_capture.py tests\unit\doctor\test_adapter_commands.py` passed: 26 passed.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed: 445 files already formatted.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed: 2474
    passed, 8 deselected, 1 warning, 82.23% coverage.

### Next

- Continue remaining adapter command templates, native usage collection for
  non-Codex CLI outputs, official auth proof, and eval-gated route graduation.

### Cycle 27 - Blocked Gemini Command Planner

- External spend: `$0.00`.
- Added a blocked Gemini CLI read-only command plan based on local Gemini CLI
  0.46.0 help output.
- The plan records `gemini --approval-mode plan --output-format json --prompt
  ""` plus staged prompt, schema, result capture, native usage capture, and
  allowed scratch capture metadata.
- The plan remains blocked on runner stdin prompt support, stdout
  `result.txt` capture, lack of observed native schema enforcement, native
  usage capture, and the normal support, auth, and eval gates.
- Tightened Gemini-family billing preflights so `GOOGLE_API_KEY` blocks
  no-metered Gemini and Antigravity claims alongside `GEMINI_API_KEY`.
- Updated README, usage docs, roadmap, changelog, current-state notes, adapter
  runbook, and loop skills.
- Targeted validation:
  - `uv run ruff check distill\doctor\adapters.py distill\doctor\adapter_commands.py tests\unit\doctor\test_adapters.py tests\unit\doctor\test_adapter_commands.py` passed.
  - `uv run ruff format --check distill\doctor\adapters.py distill\doctor\adapter_commands.py tests\unit\doctor\test_adapters.py tests\unit\doctor\test_adapter_commands.py` passed.
  - `uv run pytest -q tests\unit\doctor\test_adapters.py tests\unit\doctor\test_adapter_commands.py` passed: 18 passed.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed: 445 files already formatted.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed: 2477
    passed, 8 deselected, 1 warning, coverage above the 80% gate.

### Next

- Continue non-Codex native usage capture, official auth proof, and
  eval-gated route graduation.

### Cycle 28 - Blocked Antigravity Command Planner

- External spend: `$0.00`.
- Added a blocked Antigravity read-only command plan based on local
  Antigravity 1.107.0 `chat --help` output.
- The plan records `antigravity chat --mode ask -` plus staged prompt, schema,
  result capture, native usage capture, and allowed scratch capture metadata.
- The plan remains blocked on lack of observed headless JSON output, stdout
  `result.txt` capture, lack of native schema enforcement, native usage
  capture, and the normal support, auth, and eval gates.
- Added an adapter-doctor probe for `antigravity chat --help` mode support.
- Updated README, usage docs, roadmap, changelog, current-state notes, adapter
  runbook, and loop skills.
- Targeted validation:
  - `uv run ruff check distill\doctor\adapters.py distill\doctor\adapter_commands.py tests\unit\doctor\test_adapters.py tests\unit\doctor\test_adapter_commands.py` passed.
  - `uv run ruff format --check distill\doctor\adapters.py distill\doctor\adapter_commands.py tests\unit\doctor\test_adapters.py tests\unit\doctor\test_adapter_commands.py` passed.
  - `uv run pytest -q tests\unit\doctor\test_adapters.py tests\unit\doctor\test_adapter_commands.py` passed: 20 passed.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed: 445 files already formatted.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed: 2479
    passed, 8 deselected, 1 warning, coverage above the 80% gate.

### Next

- Continue native usage collection for non-Codex CLI outputs,
  adapter-specific capture wiring that supplies those usage files, official
  auth proof, and eval-gated route graduation.

### Cycle 29 - Generic Stdout Capture Writer

- External spend: `$0.00`.
- Added `write_stdout_captured_result()` for adapter CLIs that need captured
  stdout written to `result.txt` before manifest validation.
- The helper writes result text and then uses the shared result writer with an
  existing validated `adapter-native-usage.v1` file. It does not invent usage
  signals.
- Tightened the shared result writer so a native usage file must name the same
  adapter as the manifest being written.
- Removed the obsolete stdout result-capture blockers from Gemini and
  Antigravity command plans. They remain blocked on native usage, schema,
  auth, support, and eval gates.
- Updated README, usage docs, roadmap, changelog, current-state notes, adapter
  runbook, and loop skills.
- Targeted validation:
  - `uv run ruff check distill\doctor\adapter_capture.py distill\doctor\adapter_result_writer.py distill\doctor\adapter_commands.py tests\unit\doctor\test_adapter_capture.py tests\unit\doctor\test_adapter_result_writer.py tests\unit\doctor\test_adapter_commands.py` passed.
  - `uv run ruff format --check distill\doctor\adapter_capture.py distill\doctor\adapter_result_writer.py distill\doctor\adapter_commands.py tests\unit\doctor\test_adapter_capture.py tests\unit\doctor\test_adapter_result_writer.py tests\unit\doctor\test_adapter_commands.py` passed.
  - `uv run pytest -q tests\unit\doctor\test_adapter_capture.py tests\unit\doctor\test_adapter_result_writer.py tests\unit\doctor\test_adapter_commands.py` passed: 25 passed.

### Next

- Continue native usage collection for non-Codex CLI outputs, adapter-specific
  capture wiring that supplies those usage files, official auth proof, and
  eval-gated route graduation.

### Cycle 30 - Claude JSON Usage Capture

- External spend: `$0.00`.
- Added `claude_json_native_usage()` for captured Claude Code JSON or stream
  JSON stdout.
- The parser extracts Claude `usage` objects, preserves cache, duration, turn,
  cost, session, and stop metadata, and returns the strict
  `adapter-native-usage.v1` shape.
- Added `write_claude_captured_result()` to write `native-usage.json`,
  `result.txt`, and a validated `adapter-result.v1` manifest from captured
  Claude JSON stdout.
- Added workload-runner coverage proving a simulated Claude process can pass
  through the capture hook and existing manifest checks.
- Removed the obsolete Claude native-usage command-plan blocker. Claude still
  remains blocked by support proof, auth proof, and eval route gates.
- Updated README, usage docs, roadmap, changelog, current-state notes, adapter
  runbook, and loop skills.
- Targeted validation:
  - `uv run ruff check distill\doctor\adapter_native_usage.py distill\doctor\adapter_capture.py distill\doctor\adapter_commands.py tests\unit\doctor\test_adapter_native_usage.py tests\unit\doctor\test_adapter_capture.py tests\unit\doctor\test_adapter_commands.py tests\unit\doctor\test_adapter_workload_runner.py` passed.
  - `uv run ruff format --check distill\doctor\adapter_native_usage.py distill\doctor\adapter_capture.py distill\doctor\adapter_commands.py tests\unit\doctor\test_adapter_native_usage.py tests\unit\doctor\test_adapter_capture.py tests\unit\doctor\test_adapter_commands.py tests\unit\doctor\test_adapter_workload_runner.py` passed after formatting.
  - `uv run pytest -q tests\unit\doctor\test_adapter_native_usage.py tests\unit\doctor\test_adapter_capture.py tests\unit\doctor\test_adapter_commands.py tests\unit\doctor\test_adapter_workload_runner.py` passed: 47 passed.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed: 445 files already formatted.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed: 2490
    passed, 8 deselected, coverage 82.28%.

### Next

- Continue native usage collection and capture wiring for Grok, Gemini, and
  Antigravity, official auth proof, and eval-gated route graduation.

### Cycle 31 - Adapter Runner Stdin Support

- External spend: `$0.00`.
- Added `stdin_text` support to the low-level scratch adapter runner.
- Added `stdin_path` support to the checked workload runner so future adapter
  command plans can pass staged scratch prompt files without shell piping.
- The workload runner rejects stdin paths that escape the scratch workspace and
  passes the staged file content into the exact-argv runner.
- Removed the obsolete Gemini stdin blocker from the command planner. Gemini
  remains blocked by native schema enforcement, native usage capture, support
  proof, auth proof, and eval route gates.
- Updated README, usage docs, changelog, current-state notes, adapter runbook,
  and loop skills.
- Targeted validation:
  - `uv run ruff check distill\doctor\adapter_runner.py distill\doctor\adapter_workload_runner.py distill\doctor\adapter_commands.py tests\unit\doctor\test_adapter_runner.py tests\unit\doctor\test_adapter_workload_runner.py tests\unit\doctor\test_adapter_commands.py` passed.
  - `uv run ruff format --check distill\doctor\adapter_runner.py distill\doctor\adapter_workload_runner.py distill\doctor\adapter_commands.py tests\unit\doctor\test_adapter_runner.py tests\unit\doctor\test_adapter_workload_runner.py tests\unit\doctor\test_adapter_commands.py` passed after formatting.
  - `uv run pytest -q tests\unit\doctor\test_adapter_runner.py tests\unit\doctor\test_adapter_workload_runner.py tests\unit\doctor\test_adapter_commands.py` passed: 31 passed.

### Next

- Continue native usage collection and capture wiring for Grok, Gemini, and
  Antigravity, official auth proof, and eval-gated route graduation.

### Cycle 32 - Adapter Auth Command Probes

- External spend: `$0.00`.
- Added generic read-only JSON auth-command probes to adapter doctor.
- Claude now has a planned `claude auth status --json` marker probe, and Grok
  now has a planned `grok inspect --json` marker probe.
- Auth command output is parsed for configured marker names only. Secret values
  and account identifiers are not recorded.
- Adapter doctor can classify `api-key-command` separately from
  `session-command`, while support statements and eval gates still keep every
  plan-quota route blocked.
- Updated README, usage docs, roadmap, changelog, current-state notes, adapter
  runbook, and loop skills.
- Targeted validation:
  - `uv run ruff check distill\doctor\adapters.py tests\unit\doctor\test_adapters.py tests\unit\commands\test_cli_json.py` passed.
  - `uv run ruff format --check distill\doctor\adapters.py tests\unit\doctor\test_adapters.py tests\unit\commands\test_cli_json.py` passed.
  - `uv run pytest -q tests\unit\doctor\test_adapters.py tests\unit\commands\test_cli_json.py::TestJsonDoctor::test_doctor_json_adapter_report` passed: 10 passed.

### Next

- Continue native usage collection and capture wiring for Grok, Gemini, and
  Antigravity, current support statements, remaining auth proof, and eval-gated
  route graduation.

### Cycle 15 - Adapter Manifest Ledger Bridge

- External spend: `$0.00`.
- Added `distill.doctor.adapter_ledger`, a small bridge from verified
  `adapter-result.v1` manifests to cost-tracker rows plus cost-log metadata.
- Included-plan adapter manifests now produce zero-dollar `TokenUsage` rows,
  roll up under the `included-plan` route class, and preserve native usage and
  quota-stop metadata for future run logs.
- This does not make any plan-quota route live. It only closes the accounting
  primitive future adapter workloads will need after support, auth, and eval
  gates pass.
- Updated README, usage docs, roadmap, cost docs, changelog, current-state
  notes, adapter runbook, recurring profile design notes, and loop skills.
- Targeted validation:
  - `uv run ruff check distill\doctor\adapter_ledger.py distill\pipeline\costs.py tests\unit\doctor\test_adapter_ledger.py tests\unit\pipeline\test_costs.py` passed.
  - `uv run ruff format --check distill\doctor\adapter_ledger.py distill\pipeline\costs.py tests\unit\doctor\test_adapter_ledger.py tests\unit\pipeline\test_costs.py` passed after formatting.
  - `uv run pytest -q tests\unit\doctor\test_adapter_ledger.py tests\unit\pipeline\test_costs.py::test_save_run_log_records_route_usage_for_zero_dollar_calls` passed: 4 passed.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed: 433 files already formatted.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed: 2422
    passed, 8 deselected, 1 warning, 82.11% coverage.

### Next

- Continue official installed-session auth proof and adapter-specific read-only
  workload wiring.

### Cycle 14 - Adapter Quota-Stop Manifest Metadata

- External spend: `$0.00`.
- Added strict `quota_stop` metadata to the future `adapter-result.v1`
  manifest contract.
- The parser now rejects quota and rate-limit stop reasons unless the manifest
  includes `quota_stop.reached=true` with a reason. It also rejects negative
  retry-after values and mismatched quota-stop metadata on non-quota stops.
- This does not make any plan-quota adapter live. It closes another
  rule-owned boundary so future adapter runners can distinguish usable output
  from quota exhaustion before ledger and eval integration.
- Updated README, usage docs, roadmap, cost docs, changelog, current-state
  notes, adapter runbook, recurring profile design notes, and loop skills.
- Targeted validation:
  - `uv run ruff check distill\doctor\adapter_manifest.py tests\unit\doctor\test_adapter_manifest.py` passed.
  - `uv run ruff format --check distill\doctor\adapter_manifest.py tests\unit\doctor\test_adapter_manifest.py` passed.
  - `uv run pytest -q tests\unit\doctor\test_adapter_manifest.py` passed: 17 passed.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed: 431 files already formatted.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed on rerun:
    2419 passed, 8 deselected, 1 warning, 82.01% coverage.

### Next

- Continue official installed-session auth proof and adapter-specific read-only
  workload wiring.

### Cycle 13 - Structured Adapter Support Statements

- External spend: `$0.00`.
- Added `SupportStatement` records for candidate CLI adapters and included them
  in `distill doctor --adapters` JSON as `support_statement_detail`.
- Human doctor output now shows support statement status, checked date, and
  whether the statement is current for no-metered routing.
- Planned plan-quota routes remain blocked because their support statements are
  not current. Copilot remains a credit-metered candidate rather than a
  no-metered default.
- Updated README, usage docs, roadmap, cost docs, changelog, current-state
  notes, adapter runbook, recurring profile design notes, and loop skills.
- Targeted validation:
  - `uv run ruff check distill\doctor\adapters.py distill\commands\doctor.py tests\unit\doctor\test_adapters.py tests\unit\commands\test_cli_json.py` passed.
  - `uv run ruff format --check distill\doctor\adapters.py distill\commands\doctor.py tests\unit\doctor\test_adapters.py tests\unit\commands\test_cli_json.py` passed after formatting.
  - `uv run pytest -q tests\unit\doctor\test_adapters.py tests\unit\commands\test_cli_json.py::TestJsonDoctor::test_doctor_json_adapter_report` passed: 7 passed.
- Full validation:
  - `uv run ruff check .` passed.
  - `uv run ruff format --check .` passed: 431 files already formatted.
  - `uv run pytest -q --cov=distill --cov-fail-under=80` passed: 2415
    passed, 8 deselected, 1 warning, 81.98% coverage.

### Next

- Continue official installed-session auth proof and adapter-specific read-only
  workload wiring.
