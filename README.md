# Distill

[![CI](https://github.com/blisspixel/distillr/actions/workflows/ci.yml/badge.svg)](https://github.com/blisspixel/distillr/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/distillr.svg)](https://pypi.org/project/distillr/)
[![Python](https://img.shields.io/pypi/pyversions/distillr.svg)](https://pypi.org/project/distillr/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)

> Point Distill at a research goal. It finds papers, talks, and pages from
> operator-trusted sites, captures supplied repos, podcasts, feeds, posts, and
> local files, analyzes each into structured insights with source receipts,
> verifies claims before write, and synthesizes a plain-Markdown corpus on your
> disk. Browse it in Obsidian, query it over MCP, ask cited questions that can
> re-enter the corpus, and refresh on a cadence instead of going stale.

*PyPI package [`distillr`](https://pypi.org/project/distillr/); CLI is `distill`
(plus `distill-mcp`).*

## Install and first run

```bash
uv tool install distillr
distill --cost-mode no-metered init
distill --cost-mode no-metered papers "temporal knowledge graph" --topic tkg --limit 5 --preview
```

`no-metered` only allows routes Distill can prove are not API-billed. Preview
builds a current arXiv shortlist without ingesting. When the shortlist looks
right:

```bash
distill --cost-mode paid-ok papers "temporal knowledge graph" --topic tkg --limit 20
```

![distill papers CLI demo with synthetic paper titles, progress lines, cost summary, and Markdown corpus artifacts](docs/assets/cli-papers-demo.png)

*Illustrative demo (synthetic titles and paths). Real runs use current arXiv
results and your configured model route. Mid-sized paper runs on the
`grok-4.3` default are typically single-digit minutes and well under a dollar.*

Alternate installers, keys, local models, and updates:
[`docs/install.md`](docs/install.md). Full command reference:
[`docs/usage.md`](docs/usage.md).

## What you get

One local `library/` of plain Markdown: no database, no cloud lock-in. Same
pipeline shape for every source (capture → analyze → verify → synthesize), with
a write-time verify gate.

| Source | Entry point |
|---|---|
| YouTube | `distill latest`, `distill video`, `distill discover` |
| Websites | `distill site`, `distill site-batch` |
| arXiv | `distill papers` |
| X, repos, podcasts, newsletters, local files | `distill ingest <url-or-path>` |

Plus `distill ask` (cited answers from the corpus), `distill audit` (free trust
report), MCP for agents, and optional recurring profiles. Artifact layout and
samples: [`docs/outputs.md`](docs/outputs.md). Real example corpus:
[`examples/`](examples/README.md).

How Distill differs from Deep Research tools, notebooks, and Markdown wikis:
[`docs/positioning.md`](docs/positioning.md).

## Docs

| Doc | For |
|---|---|
| [`docs/README.md`](docs/README.md) | Full documentation index |
| [`docs/usage.md`](docs/usage.md) | Commands, flags, first recipes |
| [`docs/install.md`](docs/install.md) | Install, providers, local models |
| [`docs/cost.md`](docs/cost.md) | Cost model and guardrails |
| [`docs/mcp.md`](docs/mcp.md) | MCP tools and agent paths |
| [`docs/outputs.md`](docs/outputs.md) | What every artifact contains |
| [`docs/architecture.md`](docs/architecture.md) | Data flow and routing |
| [`docs/invariants.md`](docs/invariants.md) | Design charter |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Trust boundaries and disclosure |
| [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) | Dev setup and quality gates |
| [`docs/CHANGELOG.md`](docs/CHANGELOG.md) | What shipped |
| [`ROADMAP.md`](ROADMAP.md) | What is next |

## Status

Active beta with a broad working surface (sources, discovery, verify, synthesis,
ask, audit, MCP, dashboard, profiles, bounded workers). Every change still
clears the same release gate (95% branch coverage, ruff, pyright, import-linter,
bandit, pip-audit, supported Python matrix, build provenance). Public contracts
remain open to evidence-backed improvement; pin versions if you integrate on
MCP schemas or frontmatter. 1.0 is a future stability commitment, not a
calendar date: [`ROADMAP.md`](ROADMAP.md#100---stability-commitment--quality-bar).

## License

Apache 2.0. See [`LICENSE`](LICENSE).
