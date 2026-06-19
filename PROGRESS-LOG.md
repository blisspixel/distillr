# Progress Log

## 2026-06-19

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
