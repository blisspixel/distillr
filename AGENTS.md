# Repository Agent Instructions

These instructions apply to the whole repository.

## Style and attribution

- Do not add emojis to docs, code comments, commit messages, or PR text.
- Do not add em dashes to new prose.
- Do not add machine attribution, generated-with-tool lines, assistant credit
  lines, or tool credit trailers.

## Working model

- Keep `main` clean and releasable. Do not create long-lived branches unless the
  human explicitly asks for one.
- If you change code or docs, run the relevant quality gate before handing off.
  For normal repo work, that means `uv run ruff check .`,
  `uv run ruff format --check .`, and
  `uv run pytest -q --cov=distill --cov-fail-under=86`.
- Treat generated corpus files as outputs. Fix the pipeline or rerun the
  command instead of hand-editing generated `_Insights.md`, syntheses,
  `CLAUDE.md`, or generated topic `AGENTS.md` files.

## Provider truth

- Local mode still uses current sources. `DISTILL_PROVIDER=ollama` or
  `DISTILL_PROVIDER=lmstudio` changes the model that analyzes fetched receipts;
  it does not turn Distill into an offline answer from model memory. Discovery
  and ingest still fetch current public sources such as arXiv, YouTube, feeds,
  sites, repos, and local files.
- Implemented analysis routes today are the calibrated cloud routes and local
  Ollama or LM Studio routes. Plan-quota CLIs are candidate external workers,
  not live Distill providers until an adapter doctor, support statement, usage
  ledger, scratch manifest, and eval gate exist.
- GitHub Copilot CLI is a possible future external worker, but treat it as
  credit-metered unless a support statement proves no incremental cost. Do not
  put it in the no-metered default route ladder.
- Never claim a route is no-metered unless Distill can prove it. Local inference
  is no-metered by topology. Subscription or plan-quota CLI usage is
  no-metered only after adapter preflight proves included-plan auth rather than
  API billing.
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
