# Contributing to Distill

Thanks for your interest. This document covers the bare minimum needed to get a dev environment running, run the tests, and open a PR that's likely to merge.

## Dev setup

distillr uses [uv](https://docs.astral.sh/uv/) as its sole toolchain (package manager, virtualenv, and Python-version manager). Install uv once, then:

```bash
git clone https://github.com/blisspixel/distillr.git
cd distillr
uv sync                            # creates .venv from uv.lock; installs distill (editable) + dev tools
uv run distill init                # guided setup: creates .env, validates your key, installs the browser
```

`distill init` replaces the old manual `cp .env.example .env` + `playwright install` + `distill doctor` dance; run it once and it does all three. To do it by hand instead:

```bash
uv run playwright install chromium
cp .env.example .env               # then add API keys if you want to run live
uv run distill doctor
```

`uv sync` reads `.python-version` (3.12) and auto-downloads the interpreter if you don't have it. distillr requires **Python 3.12+**. Run any command in the project env with `uv run <cmd>` (e.g. `uv run distill ...`), or activate `.venv` directly. The install is editable, so source edits apply without reinstalling.

You only need `XAI_API_KEY` and `GEMINI_API_KEY` for end-to-end runs. The test suite itself (default mode) doesn't hit real APIs - integration tests are gated behind `-m integration`.

## Running tests

```bash
uv run pytest -q                   # default - unit + contract tests, no network
uv run pytest -m integration       # hits real YouTube, arXiv, etc. Needs keys and bandwidth.
uv run pytest --cov=distill --cov-fail-under=93   # branch coverage gate
```

## Quality gates

CI enforces the following on every push. Before opening a PR, at least run:

```bash
uv run pytest -q                                              # unit + contract tests pass
uv run pytest --cov=distill --cov-fail-under=93               # branch coverage stays above the floor
uv run ruff check .                                           # lint clean
uv run ruff format --check .                                  # formatting clean
uv run bandit -r distill/ -c pyproject.toml --severity-level medium   # no MEDIUM+ security issues
uv run lint-imports                                           # dependency-direction contracts hold
```

Coverage is **branch** coverage (every conditional must exercise both arms) and is ratcheted up-only toward the 1.0 target of 95%; the floor only rises. `pip-audit --skip-editable` runs in CI against the locked dependency tree and catches known CVEs (it skips the editable distillr install itself).

### Pre-commit hooks

The fastest way to stay green: install the hooks once. The lint/type/security hooks run through `uv run --frozen`, so they use the exact locked tool versions CI runs - a clean `pre-commit run --all-files` means a clean CI run.

```bash
uv run pre-commit install --install-hooks       # ruff / bandit / import-linter / pyright on every commit
uv run pre-commit install --hook-type pre-push  # full test suite on every push
uv run pre-commit run --all-files               # one-time baseline pass
```

If a hook modifies your files (e.g. ruff auto-fixes something), re-`git add` the changes and commit again.

### Tool stack

| Tool | Purpose | Runs in CI? |
|---|---|---|
| **uv** | Package / venv / Python-version manager; lockfile-driven reproducible envs | Yes - `uv sync --frozen` everywhere |
| **ruff** | Lint (900+ rules) + formatter, replaces flake8 / black / isort | Yes, blocking |
| **pytest + coverage** | Unit + contract tests, plus a ratcheted branch-coverage floor | Yes, blocking (integration tests gated behind `-m integration`) |
| **import-linter** | Dependency-direction (layer) contracts | Yes, blocking |
| **bandit** | Python security scanner | Yes, blocking on MEDIUM+ |
| **pip-audit** | Known-CVE scanner for dependencies | Yes, blocking |
| **pyright** | Static type checker | Blocking on `distill/llm/`; advisory elsewhere (ratcheting toward strict-everywhere by 1.0) |
| **pre-commit** | Local enforcement wrapper; hooks call `uv run --frozen` so local == CI | Runs locally; CI re-validates |

uv config, ruff config, bandit config, pyright config, and the import-linter contracts all live in `pyproject.toml`; dependencies are pinned in `uv.lock`. Ruff's rule set is opinionated but not onerous; fix what it flags or, for a genuine exception, add a narrow `# noqa: <code>` with a comment explaining why.

## Repository layout

- `distill/` - the Python package (all production code)
- `tests/` - automated tests (unit + contract + integration)
- `docs/` - long-form documentation; `docs/briefing-contexts/TEMPLATE.md` is the starting point for briefing prompts
- `configs/` - sample config files for site batches (`example_seeds.json`) and other inputs
- `scripts/install.sh`, `scripts/install.ps1` - source installers that hand off first-run configuration to `distill init`
- `private/` - drop any personal or client-specific files here (briefing contexts, custom seed files, scratch notes). The directory's contents are git-ignored except for `private/README.md`, which documents the convention
- `library/`, `output/`, `tmp/` - git-ignored runtime directories; populated when you run distill locally

## Project shape - what's in scope

Distill is a **source-to-intelligence platform**. Roughly: it discovers content across source types (YouTube, websites, arXiv, and more coming), captures it, analyzes it into per-item insights, synthesizes across items and topics, and produces reports and briefings. The output is a local markdown vault designed to be openable in Obsidian and similar tools, and queryable via MCP for agent workflows.

In scope for contributions:

- New source types (podcasts, RSS, conference talks) that fit the same capture → analyze → synthesize → report shape
- Obsidian-native output features (wiki-linking, frontmatter, concept/entity extraction - see ROADMAP section 10)
- Prompt quality improvements (especially where existing outputs feel thin or generic)
- Cost/telemetry improvements
- MCP server additions (new tools, resources, prompts)
- Test coverage, especially for paths that currently rely on live API behavior

Probably out of scope (please open an issue to discuss before building):

- A built-in graph-view UI (Obsidian/Logseq/Dendron already do this well)
- A hosted cloud version
- A proprietary database or non-markdown storage format
- Features that couple distill tightly to a single vendor beyond the current xAI/Google mix

## Context engineering

Treat the model context window as working memory, not storage. Durable state
belongs in `library/`, `.distill/`, sidecars, frontmatter, and receipts. Prompts
should receive the smallest evidence set that can do the job, with paths back to
the durable corpus when more detail is needed.

When changing prompts, agent-facing tools, report flows, MCP responses, or
long-running loops, use these rules:

- Prefer paths, previews, ids, and drill-down commands over full artifact bodies
  in default agent-facing responses. Full bodies are fine only when the caller
  explicitly asks to read that file.
- Preserve provenance in the context you pass. If a prompt sees a claim, it
  should also see enough source identity, citation, receipt, or sidecar context
  to avoid laundering uncertainty in later synthesis.
- Measure prompt budget changes. Use `distill costs` and the biggest-prompts
  view from `library/.distill/telemetry.jsonl` before and after prompt or
  pipeline rewrites that can change token volume.
- Compact by retaining evidence first, then reducing wording. For report and
  synthesis work, high-recall source selection comes before precision trimming.
  Do not drop receipts or confidence labels just to save tokens.
- Use structured deltas for durable knowledge. Concept notes, run state, audit
  state, and next actions should append, merge, or snapshot explicit changes
  rather than rewriting opaque summaries that lose why something changed.
- Clear stale intermediate context in iterative loops. A later LLM call should
  not inherit old tool results, failed attempts, or preview rows unless they are
  still relevant to the current step.
- Keep semantic judgment model-owned. Relevance, faithfulness, novelty,
  synthesis quality, and source fit are not keyword, length, or cosine scores.
  Python may parse schemas, enforce budgets, aggregate model verdicts, and
  check receipts, but it must not fake a semantic quality gate.

Any PR that increases default prompt size, returns larger MCP payloads, changes
report context flow, or adds an agent loop should explain the context-budget
impact in the changelog or design note. For larger changes, add a focused test
or fixture that proves the smaller context still preserves the evidence the
output needs.

## Agentic and loop changes

Agentic surfaces in distill must be bounded production workflows, not open-ended
automation. Before adding or changing a model-driven step, recurring profile,
MCP write tool, adapter runner, or long-running loop, document the balance:
which part is rule-owned, which part is model-owned, and which verifier decides
whether the result is accepted.

Use this checklist for those changes:

- Keep each model call, tool, or worker focused on one responsibility. Split
  orchestration, judgment, validation, and writing when combining them would
  obscure failure modes.
- Version the durable contract that future runs depend on: prompt ids, schemas,
  tool arguments, eval fixtures, run-state shape, and adapter manifests.
- Bound execution with max attempts, timeouts, spend or token caps, and clear
  stop conditions. A model saying the work is complete is not a stop condition.
- Make side effects idempotent where possible. Writes should have stable paths
  or request ids, retries must not duplicate externally visible work, and
  partial failures need a recovery, resume, quarantine, or explicit refusal
  path.
- Keep irreversible or externally visible actions behind approval classes,
  allowlists, cost-mode gates, read-only modes, or other structural controls.
  Reasoning can be flexible; writes, spend, network access, and permissions
  need fixed boundaries.
- Log outcomes that operators can inspect without exposing raw private chain of
  thought: plans, commands, tool calls, state transitions, validation results,
  costs, blocked reasons, and accepted artifact paths.
- Test the real failure classes. Add focused coverage for prompt injection,
  tool-output injection, malformed structured output, duplicate execution,
  stale intermediate context, retry after partial write, and budget refusal
  when the change touches those risks.
- Prefer staged rollout for new autonomous behavior: preview or shadow first,
  then approval-gated execution, then unattended operation only after tests,
  audit output, and cost telemetry show the loop converges.

## PR expectations

- Keep PRs focused. One behavior change or one capability per PR.
- If you're adding a new command, update `README.md` usage and `ROADMAP.md` where applicable.
- If you're changing prompts or model routing, note the behavior change in `CHANGELOG.md` (so users running refresh flows know why outputs may shift).
- Avoid introducing a new top-level dependency without a clear reason. distill tries to stay pip-installable with a small dependency graph.

## Git and GitHub hygiene

- **One long-lived branch: `main`**, kept releasable (GitHub Flow). Do work on short-lived feature branches and open a PR; it squash-merges as one clean commit and the branch auto-deletes, so history stays linear and nothing stale accumulates. `main` is protected: the full CI gate must pass before merge, and force-pushes/deletions are blocked. Reviews are not required (0 approvals) and admins bypass the PR requirement, so a quick fix can still go straight to `main` when warranted - but the PR path is the default.
- **No machine attribution in history.** Commits and PR bodies carry no agent, assistant, generator, or tool credit lines. The author is the human who made the change; `git log` and blame stay honest.
- **Automated dependency update bots stay off, deliberately** (removed in 0.9.23 - see the ROADMAP "Engineering standards: adopted, adapted, declined" entry). `pip-audit` in the CI gate covers vulnerable-dependency alerts without bot PRs or bot branches.

## Pre-push checklist (release quality)

Before pushing to main or tagging a release, run the full gate locally. CI catches these, but catching them locally avoids embarrassing red badges on the repo.

```bash
# 1. Tests - including property-based tests (hypothesis)
uv run pytest -q --cov=distill --cov-fail-under=93

# 2. Lint - both check and format
uv run ruff check .
uv run ruff format --check .

# 3. Security
uv run bandit -r distill/ -c pyproject.toml --severity-level medium

# 4. Type check - blocking on distill/llm/, advisory elsewhere
uv run pyright distill/llm/

# 5. Dependency direction enforcement
uv run lint-imports

# 6. Build sanity - sdist + wheel build, web assets bundled
uv build

# 7. Verify nothing unwanted is staged
git diff --cached --stat
git status
```

Or just run `uv run pre-commit run --all-files` (with the pre-push hook installed) to cover 1-5 in one command.

Common mistakes that have burned us:

- **Forgetting to re-lock after a dependency change.** Dev tooling lives in the `[dependency-groups].dev` group and runtime deps in `[project.dependencies]`. After editing either, run `uv lock` and commit the updated `uv.lock` - CI installs with `uv sync --frozen` and will fail if the lock is stale or missing the new dependency.
- **`asyncio.get_event_loop()` on Linux.** Python 3.12+ on Linux has no default event loop in the main thread. Use `asyncio.run()` in tests, not `asyncio.get_event_loop().run_until_complete()`. It works on Windows locally but fails on CI.
- **Forgetting `ruff format` after `ruff check --fix`.** Auto-fixes can leave formatting inconsistent. Always run both.
- **Committing cache directories.** `.hypothesis/`, `__pycache__/`, `.ruff_cache/` must be in `.gitignore`. If you add a new tool that generates a cache dir, add it to `.gitignore` before running it.
- **PyPI version reuse.** PyPI will never accept a re-upload of the same version number. If a tagged release has already been published, you must bump the version - even for a one-line fix. There is no workaround.
- **Tag before verifying CI.** Don't tag a release until CI is green on the commit you're tagging. Force-pushing tags to fix failures creates noise and can trigger duplicate PyPI uploads.

## Questions or proposals

Open a GitHub issue before doing significant work on something new. A short description of what you want to build and why is enough - I'd rather talk through shape early than ask you to rework a finished PR.

## License

By contributing, you agree that your contributions will be licensed under the same Apache License 2.0 that covers the rest of the project (see [`../LICENSE`](../LICENSE)).
