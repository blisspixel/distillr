# Contributing to Distill

Thanks for your interest. This document covers the bare minimum needed to get a dev environment running, run the tests, and open a PR that's likely to merge.

## Dev setup

```bash
git clone https://github.com/blisspixel/distillr.git
cd distillr
python -m venv venv
source venv/bin/activate           # Windows: venv\Scripts\activate
pip install -e ".[dev]"            # installs distill + pytest, ruff, bandit, pip-audit, pre-commit, build, twine
playwright install chromium
cp .env.example .env               # then add API keys if you want to run live
distill doctor
```

You only need `XAI_API_KEY` and `GEMINI_API_KEY` for end-to-end runs. The test suite itself (default mode) doesn't hit real APIs — integration tests are gated behind `-m integration`.

## Running tests

```bash
pytest -q                          # default — unit + contract tests, no network
pytest -m integration              # hits real YouTube, arXiv, etc. Needs keys and bandwidth.
pytest --cov=distill               # with coverage
```

## Quality gates

CI enforces the following on every push. Before opening a PR, at least run:

```bash
pytest -q                          # unit + contract tests pass
ruff check .                       # lint clean
ruff format --check .              # formatting clean
bandit -r distill/ -c pyproject.toml --severity-level medium   # no MEDIUM+ security issues
```

The first three are cheap; run them locally. Bandit is cheap too. `pip-audit --strict` runs in CI against the installed distribution and catches known CVEs in transitive dependencies.

### Pre-commit hooks

The fastest way to stay green: install the pre-commit hooks once, and ruff/bandit/whitespace/yaml/toml checks run automatically on every `git commit`.

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files         # one-time baseline pass
```

If a hook modifies your files (e.g. ruff auto-fixes something), re-`git add` the changes and commit again.

### Tool stack

| Tool | Purpose | Runs in CI? |
|---|---|---|
| **ruff** | Lint (900+ rules) + formatter, replaces flake8 / black / isort | Yes, blocking |
| **pytest** | Unit + contract tests | Yes, blocking (integration tests gated behind `-m integration`) |
| **bandit** | Python security scanner | Yes, blocking on MEDIUM+ |
| **pip-audit** | Known-CVE scanner for dependencies | Yes, blocking |
| **pyright** | Static type checker | Yes, advisory (non-blocking while the codebase is incrementally typed) |
| **pre-commit** | Local enforcement wrapper | Runs locally; CI re-validates |

Ruff config, ruff rules, bandit config, and pyright config all live in `pyproject.toml`. Ruff's rule set is opinionated but not onerous; fix what it flags or, for a genuine exception, add a narrow `# noqa: <code>` with a comment explaining why.

## Repository layout

- `distill/` — the Python package (all production code)
- `tests/` — automated tests (unit + contract + integration)
- `docs/` — long-form documentation; `docs/briefing-contexts/TEMPLATE.md` is the starting point for briefing prompts
- `configs/` — sample config files for site batches (`example_seeds.json`) and other inputs
- `scripts/setup.py` — end-user installer (interactive API key setup)
- `private/` — drop any personal or client-specific files here (briefing contexts, custom seed files, scratch notes). The directory's contents are git-ignored except for `private/README.md`, which documents the convention
- `library/`, `output/`, `tmp/` — git-ignored runtime directories; populated when you run distill locally

## Project shape — what's in scope

Distill is a **source-to-intelligence platform**. Roughly: it discovers content across source types (YouTube, websites, arXiv, and more coming), captures it, analyzes it into per-item insights, synthesizes across items and topics, and produces reports and briefings. The output is a local markdown vault designed to be openable in Obsidian and similar tools, and queryable via MCP for agent workflows.

In scope for contributions:

- New source types (podcasts, RSS, conference talks) that fit the same capture → analyze → synthesize → report shape
- Obsidian-native output features (wiki-linking, frontmatter, concept/entity extraction — see ROADMAP section 10)
- Prompt quality improvements (especially where existing outputs feel thin or generic)
- Cost/telemetry improvements
- MCP server additions (new tools, resources, prompts)
- Test coverage, especially for paths that currently rely on live API behavior

Probably out of scope (please open an issue to discuss before building):

- A built-in graph-view UI (Obsidian/Logseq/Dendron already do this well)
- A hosted cloud version
- A proprietary database or non-markdown storage format
- Features that couple distill tightly to a single vendor beyond the current xAI/Google mix

## PR expectations

- Keep PRs focused. One behavior change or one capability per PR.
- If you're adding a new command, update `README.md` usage and `ROADMAP.md` where applicable.
- If you're changing prompts or model routing, note the behavior change in `CHANGELOG.md` (so users running refresh flows know why outputs may shift).
- Avoid introducing a new top-level dependency without a clear reason. distill tries to stay pip-installable with a small dependency graph.

## Questions or proposals

Open a GitHub issue before doing significant work on something new. A short description of what you want to build and why is enough — I'd rather talk through shape early than ask you to rework a finished PR.

## License

By contributing, you agree that your contributions will be licensed under the same MIT License that covers the rest of the project (see `LICENSE`).
