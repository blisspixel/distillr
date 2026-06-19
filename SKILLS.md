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
- Semantic examples: relevance, novelty, source fit, faithfulness in prose,
  synthesis quality, contradiction interpretation, and route quality.
- If no model route exists for a semantic task, label the fallback as structural
  ordering. Do not present keyword or length heuristics as quality ranking.

## Cost Policy

- External spend budget for this loop is `$5.00`; current spend is `$0.00`.
- Default to local tests and static checks. Do not make cloud/API calls unless
  the task truly requires them.
- Use the global one-run form as `distill --cost-mode no-metered <command>`.
  Profile preview commands should carry this form when the profile declares
  `cost_mode: no-metered`.
- In `no-metered`, local Ollama and LM Studio are allowed by topology.
  API-billed routes and ambiguous adapter routes must fail closed.
- Plan-quota CLI routes are not no-metered defaults until adapter doctor,
  support statement, complete usage ledger, scratch manifest, and eval proof
  exist.

## Validation

- For code or docs changes, run:
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run pytest -q --cov=distill --cov-fail-under=80`
- If the full coverage run exceeds a short command timeout, rerun with a longer
  timeout before treating it as a failure.
