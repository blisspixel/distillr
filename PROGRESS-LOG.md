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

- Run targeted tests for cost policy, config, and router.
- Run the full repo quality gate.
- Commit the doc truth-up and cost-policy foundation once green.
- Continue with CLI `--cost-mode` overrides, profile-run state, and zero-dollar
  ledger rows.
