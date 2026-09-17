# Repository Agent Instructions

These instructions apply to the whole repository.

Distillr is a Python research desk: capture current sources, analyze and verify
receipts, and maintain an inspectable plain-Markdown corpus. Native corpus
files are authoritative; MCP, agent packages, exports, and indexes are views.

## Orient before editing

- Read [README.md](README.md), the active and next rows in [ROADMAP.md](ROADMAP.md),
  and the relevant [research-desk doctrine](docs/design/research-desk-doctrine.md),
  [architecture](docs/architecture.md), tests, and recent history. The detailed
  backlog supports the public roadmap; it does not independently set scope.
- Source, tests, configuration, lockfiles, and release history outrank stale
  prose. Distinguish planned, implemented, tested, shipped, and live-validated
  behavior. A green historical CI run does not validate a new working tree.
- Check current primary documentation before changing SDKs, providers,
  protocols, billing assumptions, or commands. Preserve the established Python
  architecture and locked stack unless evidence warrants a bounded change.
- Use the existing gitignored `.agent/` for scratch work and resumable state.
  Its optional `codegraph/` can guide impact analysis only after checking
  freshness against the working tree; inspect source before editing. Keep
  secrets out. Disposable cognition stays in `.agent/`; promote durable
  decisions, specifications, and records into tracked files.
- Combine README, roadmap, architecture docs, tests, and git history with
  structural code intelligence so sessions build on existing knowledge rather
  than rediscovering the repository from scratch.

## Style and attribution

- Do not add emojis to docs, code comments, commit messages, or PR text.
- Do not add em dashes or en dashes to new prose.
- Do not add machine attribution, generated-with-tool lines, assistant credit
  lines, or tool credit trailers.

## Working model

- Keep `main` clean and releasable. Do not create long-lived branches unless the
  human explicitly asks for one.
- Follow the core operating loop: orient in the working tree and tests, research
  current external reality, bound the task, implement through canonical seams,
  verify mechanically, inspect failures honestly, fix root causes, adversarially
  self-review, prove behavior with evidence, and update durable project state.
- Bound the change by its outcome and acceptance evidence. Do not make
  verification pass by weakening the mechanism that found a problem: avoid broad
  `# type: ignore` directives, vague escape-hatch types (`Any`), unsafe casts,
  disabled linter rules, swallowed exceptions, weakened `@deal` contracts, or
  lowered coverage thresholds. Fix the underlying code or types instead.
- If you change code or docs, run the relevant quality gate before handing off.
  Check `uv lock --check`, sync with `uv sync --frozen`, then run:

  ```text
  uv run --frozen ruff check .
  uv run --frozen ruff format --check .
  uv run --frozen pyright --warnings distill/
  uv run --frozen lint-imports
  uv run --frozen pytest -q --cov=distill --cov-fail-under=95
  ```

  The floor is 95% branch coverage. Preserve package/module strictness ratchets;
  Pyright warnings also fail the gate. The remaining security, contract,
  distribution, build, and platform checks are in
  [CONTRIBUTING.md](docs/CONTRIBUTING.md#quality-gates) and
  [CI](.github/workflows/ci.yml). Local hooks cover only a subset.
- Default tests must not spend or depend on developer services. Preserve the
  credential and socket guards in `tests/conftest.py`; mock local model and
  hardware probes unless that boundary is the subject of the test. Live
  journeys need explicit cost authority and separate receipts.
- Treat generated corpus files as outputs. Fix the pipeline or rerun the
  command instead of hand-editing generated `_Insights.md`, syntheses,
  `CLAUDE.md`, or generated topic `AGENTS.md` files.
- Regenerate agent distributions from their canonical skills and scripts;
  use [interoperability.md](docs/interoperability.md) for the package boundary.
  After meaningful changes, update affected docs, `Unreleased`, roadmap
  evidence, and applicable snapshots. Record unresolved work outside chat.
- Publishing, sending, deployment, and irreversible writes require the user's
  applicable authority. Instruction maintenance alone does not authorize
  commits, pushes, or releases. Markdown instructions cannot enforce a spend
  cap or substitute for runtime authorization gates.

## Canonical implementation paths

- Keep CLI and MCP entry points thin. Reuse `distill/pipeline/` and the
  `claims`, `concepts`, and `library` domain owners; preserve the dependency
  directions enforced by import-linter in `pyproject.toml`.
- Use `distill/config.py` for application configuration and `distill/llm/`
  for routing, call execution, retry, pricing, and cost policy. Run accounting
  belongs in `distill/pipeline/costs.py`; do not create off-ledger calls or a
  second provider fallback ladder.
- Preserve confined filesystem operations in `distill/library/`, durable
  append rules in `distill/jsonl.py`, and child-process controls in
  `distill/process_security.py`. Validate untrusted input at boundaries and
  retain atomic publication, exact identity, and complete-history semantics.
  Follow [SECURITY.md](docs/SECURITY.md) for fetching and credential boundaries.
- Inspect existing callers before adding shared infrastructure. Preserve lazy
  CLI imports and source-specific capture. Report sections and artifact
  publication remain sequential; bounded paper-analysis workers are a
  deliberate exception, not a general concurrency policy.
- Keep dependencies minimal and intentional. Check whether the standard
  library, locked dependencies, or a few clear lines of local code solve the
  need before proposing new packages. Avoid duplicate HTTP, parsing, or CLI
  stacks.
- When an error class recurs, fix the system (types, contracts, schemas,
  static analysis, tests, or docs) so the entire failure class becomes harder
  to repeat.

## Provider truth

- Local mode still uses current sources. `DISTILL_PROVIDER=ollama` or
  `DISTILL_PROVIDER=lmstudio` changes the model that analyzes fetched receipts;
  it does not turn Distill into an offline answer from model memory. Discovery
  and ingest still fetch current public sources such as arXiv, YouTube, feeds,
  sites, repos, and local files.
- Implemented analysis routes today are xAI and Gemini cloud routes, explicit
  opt-in Anthropic and OpenRouter API routes, and local Ollama or LM Studio
  routes. Anthropic and OpenRouter are metered and are not calibrated defaults;
  OpenAI remains a reserved route. Plan-quota CLIs are candidate external
  workers, not live Distill providers until an adapter doctor, support
  statement, usage ledger, scratch manifest, and eval gate exist.
- GitHub Copilot CLI is a possible future external worker, but treat it as
  credit-metered unless a support statement proves no incremental cost. Do not
  put it in the no-metered default route ladder.
- Never claim a route is no-metered unless Distill can prove it. Proven
  on-device inference is no-metered; a loopback endpoint alone is insufficient
  because a local daemon can forward cloud models. Subscription or plan-quota
  CLI usage is no-metered only after adapter preflight proves included-plan
  auth rather than API billing.
- Metered APIs are allowed only when the user, config, or cost mode permits
  them. In no-metered mode, fail closed on ambiguous billing.

## Agentic balance

- Use deterministic rules only for structure or ground truth: schema parsing,
  URL and path safety, exact receipt checks, cost refusal, action ids, approval
  classes, and verifier stop conditions.
- Use model judgment for semantic questions: source fit, novelty, quality,
  faithfulness, rumor likelihood, synthesis planning, and contradiction
  interpretation.
- For irreversible actions, let models produce per-criterion verdicts and let
  Python aggregate, record, and gate the decision.
