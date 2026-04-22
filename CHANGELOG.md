# Changelog

All notable changes to this project will be documented in this file.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **`distill discover "<goal>" --topic X`** — new goal-aware cross-source front door. Takes a natural-language research goal, has Grok generate paper + video search queries, fans out to arXiv and YouTube, runs a unified *goal-aware* LLM rerank across both source types (scores on goal_fit / depth / complementarity), shows a single ranked table of mixed papers and videos, and — after interactive confirmation — ingests the shortlist through the existing paper and video pipelines. Flags: `--topic/-t`, `--paper-limit`, `--video-limit`, `--days`, `--shorts/--no-shorts`, `--preview`, `--yes/-y`, `--goal-file`. See ROADMAP for context on why this closes the front-door gap that previously existed between per-source commands.
- **`--goal-file` for `distill discover`** — mirrors the `--context-file` pattern from `research-brief` and `synthesize`. The goal argument can now be loaded from a markdown file, enabling reusable, goal-driven topic refreshes (e.g. save `private/ai-composer-goal.md` and re-run discover against it on a cadence without retyping).
- **`distill papers` query expansion, LLM rerank, and `--preview`** — brings `distill papers` to parity with `distill latest`. One user query now expands into up to six arXiv search variants (heuristic + Grok), results are deduped by `paper_id` across variants, and a Grok-based rerank (`RankedPaper` with relevance / depth / novelty / credibility scores) picks the top-N *before* per-paper PDF analysis. `--preview` short-circuits to the ranked table for inspection without ingestion. New flags: `--preview`, `--sort relevance|date` (new default: relevance), `--expand/--no-expand`, `--rerank/--no-rerank`. arXiv multi-query calls are spaced 3.5s apart to respect rate limits.

### Changed

- **`distill papers` default behavior.** Previously: literal query, newest-first by submission date, all top-N ingested blindly. Now: expanded, reranked, relevance-sorted, top-N picked by LLM. The old behavior is still available via `--no-expand --no-rerank --sort date`. This fixes the failure mode where generic queries (e.g. "music theory deep learning", "automatic harmonization") pulled in unrelated subfields (physics, image processing) because arXiv's tokenizer has no concept of research intent.

### Fixed

- **arXiv query building no longer phrase-matches 3+ word queries.** `_build_search_query` used to wrap any multi-word query in quotes for strict phrase matching. That was too strict for LLM-generated queries like `"symbolic music transformer composition"`, which returned zero results as a literal phrase even when the target papers existed. New policy: 1 word → single-term; 2 words → phrase match (naturally phrasal); 3+ words → AND-joined tokens so every term must appear but not necessarily adjacent. Pre-operator input (quotes, AND/OR, parens) still passes through untouched.

### Planned

- Obsidian-native output: wiki-style cross-linking, standardized YAML frontmatter, `distill open --vault` hint. See ROADMAP section 10 (Tier 1).
- LLM-maintained concept and entity notes, intelligent merging on refresh, contradiction flagging. See ROADMAP section 10 (Tier 2).
- Goal-file refresh hook for `distill watch`: re-run discover against a saved goal file on a schedule so goal-driven topics stay current the same way keyword topics do.

## [0.1.0] — 2026-04-20

Initial public release as `distillr` on PyPI.

### Added

- **arXiv paper ingestion** (`distill papers <query>`) — phrase-matched search, latest-N selection by submission date, full-PDF text extraction (pypdf, 100K char cap, unicode-surrogate sanitized), per-paper structured insights, paper-level cross-paper synthesis.
- **Multi-topic research briefings** (`distill research-brief`) — Gemini Deep Research over one or more topic corpora with a user-supplied context file (`--context-file`). Web-augmented; writes `output/briefing-{name}.md`.
- **Multi-topic deep synthesis** (`distill synthesize`) — single Grok 4.20 call over the gathered corpus with user-supplied context. No web augmentation; writes `output/synthesis-{name}.md`.
- **Briefing context template** — `docs/briefing-contexts/TEMPLATE.md` showing the shape for audience, corpus expectation, required structure, and rules.
- **`private/` convention** — user-local files (client-specific seeds, personal context files, scratch notes) live under `private/`; directory contents are git-ignored except for `private/README.md`, which documents the pattern.
- **Model pinning** — xAI premium/site workload defaults pinned to `grok-4.20-0309-reasoning`; fast workload defaults to `grok-4-1-fast-reasoning`. Overrides via `.env` (see `.env.example`).

### Changed

- Package renamed from `distill` to `distillr` for PyPI distribution. Command (`distill`), Python imports (`import distill`), and repo identity remain `distill`.
- README opener rewritten to lead with the source-to-intelligence platform story rather than YouTube specifically; shields.io badge row and Table of Contents added so the long README is navigable.
- ROADMAP restructured: historical build phases moved here under "Pre-release Development"; ROADMAP section 10 added ("Living Wiki Corpus").

### Fixed

- arXiv search now phrase-matches multi-word queries (previously OR'd tokens, flooding results with unrelated papers).
- Paper ingestion now fetches and extracts the full PDF rather than analyzing the abstract only.
- PDF text extraction sanitizes lone surrogate codepoints that break JSON encoding for the API call.

### Infrastructure

- `LICENSE` added (MIT).
- `CONTRIBUTING.md` added with the full tool-stack and quality-gate documentation.
- `CHANGELOG.md` added.
- `SECURITY.md` added with vulnerability reporting flow.
- `.gitignore` rewritten with comprehensive coverage: Python build artifacts, virtual environments, test/coverage caches (`.coverage`, `htmlcov/`, `.ruff_cache/`, `.pytest_cache/`, `.mypy_cache/`), IDE/editor files, OS files, `.claude/`, `archive/`, logs, and distill runtime data (`library/`, `output/`, `tmp/`). `private/*` ignored except `private/README.md`.
- `.pre-commit-config.yaml` added (ruff, ruff-format, bandit, whitespace/yaml/toml/merge-conflict/private-key hooks).
- `.github/workflows/ci.yml` added with jobs for test (Python 3.10/3.11/3.12), lint (ruff check + format), security (bandit + pip-audit), types (pyright, advisory), and build (sdist + wheel artifact).
- GitHub templates: `.github/ISSUE_TEMPLATE/bug_report.md`, `.github/ISSUE_TEMPLATE/feature_request.md`, `.github/PULL_REQUEST_TEMPLATE.md`.
- `CODE_OF_CONDUCT.md` added (Contributor Covenant v2.1).
- Ruff rule set expanded: added `C4, PTH, RET, T20, A` with focused ignores; typer `Option`/`Argument` factories whitelisted from B008 globally via `extend-immutable-calls`.
- Security hardening: all `urllib.request.urlopen` calls route through a single `distill.net.safe_urlopen` helper that rejects non-`https` schemes; arXiv XML parsing switched from `xml.etree.ElementTree` to `defusedxml`; SHA-1 hash used for content dedup annotated `usedforsecurity=False`.
- Runtime deps: added `pypdf`, `requests`, `defusedxml` (previously relied on transitive deps; now explicit in `pyproject.toml`).
- Removed `requirements.txt`; `pyproject.toml` is the single source of truth for runtime and dev dependencies. CI's `pip-audit` scans the installed distribution directly.
- New `[project.optional-dependencies].dev` extra: `pytest`, `pytest-cov`, `ruff`, `bandit`, `pip-audit`, `pre-commit`, `build`, `twine`. Install with `pip install -e ".[dev]"`.

---

## Pre-release Development

The sections below consolidate the build history that predates the public 0.1.0
release. They are kept here for historical interest; individual commits and PRs
in the repository history tell the same story at finer resolution.

### Foundation

- Project scaffolding (`.env`, `config.py`, CLI skeleton)
- Library management (`library.json`, `add`/`remove`/`library` commands)
- Video discovery (yt-dlp channel listing, date filtering, metadata)
- State tracking (`state.json` per channel, skip already-processed)
- Transcript acquisition (YouTube auto-captions first, scribe fallback)

### Intelligence

- Prompt engineering (multi-category extraction, grounded synthesis, no vendor hallucination)
- Grok 4.1 integration (xAI API, retry logic with exponential backoff)
- Per-video analysis (2-pass pipeline: extraction -> synthesis -> `insights.md`)
- YouTube Shorts support (1-pass quick insight extraction, signal-strength rating)
- Channel context (auto-generated `channel_context.md`)

### Synthesis

- Per-channel synthesis (`synthesis.md` from all video insights including Shorts)
- Per-topic synthesis (`topic_synthesis.md` across channels)
- Refresh logic (`--refresh` flag, only new videos, regenerate synthesis)

### Reports

- Gemini Deep Research integration (File Search grounding, polling, auto-cleanup)
- 4-phase report generation (research -> section writing -> assembly -> QA)
- Scope-adaptive sections (single-channel vs multi-channel section lists)
- Voice-matched section types (reference, analytical, actionable) with temperature control
- Anti-hallucination prompting and QA checks
- Primary source citations required (not Wikipedia, not numbered `[cite: N]`)
- Creator estimate/opinion separation (`[Estimated]` vs `[Confirmed]`)
- Bias detection (QA flags inherited bullishness/bearishness without counterweight)
- Readability enforcement (short paragraphs, tables, subheadings)
- Cross-section dedup (full previous-section context, explicit no-repeat rules)
- Tagged source material (vendor insights, enterprise data, syntheses per section)
- DOCX export (professional report with cover page, TOC, page numbers, confidence badges)
- Report scoping (`--focus`, `--test`, `--legacy`, `--research-only`, `--sections`, `--no-qa`)
- File Search store bundling and cleanup (auto after run; `distill cleanup` for orphans)
- Report resume hardening (safe File Search upload staging, normalized operation polling, Windows-safe console output)

### Topic Discovery and Learning

- Human-readable video directories (slugified titles + `distill migrate`)
- Power commands: `distill video`, `distill channel`, `distill search`, `distill explore`, `distill latest`, `distill learn`, `distill brief`
- Browser-based YouTube search retrieval (Playwright) with fallback parsing
- Query expansion, metadata enrichment, and best-pick reranking for topic learning
- Exact-hour YouTube discovery windows (`--hours`) for stay-current workflows
- Skeptical multi-query selection for rumor-heavy and April 1 topic runs
- Topic diff and change-history artifacts (`distill diff`, `topic_diff.md`, `change_history.jsonl`)
- Trend detection over recorded diff windows (`distill trends`)

### Packaging and CLI

- `pyproject.toml` with `[project.scripts]` so `pip install -e .` exposes `distill` as a command
- Resolved module name collision (`distill.py` -> `distill/cli.py`)
- `.gitignore` and `.env.example` for clean project setup
- Cross-platform setup script (`setup_distill.py`): installs the package, Chromium, API keys, validates everything
- `setup_distill.py --check` mode for re-validation without changes
- Live API key testing with smart error categorization (auth vs rate-limit vs timeout)

### Post-Run Summary and Observability

- Rich summary panel after every command — items processed, time elapsed, actual cost, pass/fail counts
- Clickable `file://` links to outputs (insights, synthesis, report, DOCX)
- Failed-item list with reasons in the summary panel
- `distill open` — open topic/channel/output folders and files in the system file browser
- `distill` with no args shows a quick dashboard (topics, channels, counts, quick commands)
- Cost tracking — actual token usage per API call, per-call-type breakdowns
- `distill costs` command — cost-history table with per-run token/timing breakdowns
- `--dry-run` shows projected spend with full/Shorts breakdown
- Run cost log (`cost_log.jsonl`) — estimated vs actual costs for calibration
- Timeouts and retries on all API calls for transient-failure resilience

### UX and Testing

- Tab-completion for topic and channel names across all commands (Typer `autocompletion`)
- Smart `show` command accepts channel name as positional arg
- Contextual "what's next" hints after every command (file paths, navigation, follow-up commands)
- Rich progress bar with ETA during long runs
- Color-coded video status in `videos` listing
- Integration tests hitting real YouTube (`@pytest.mark.integration`, skipped by default)
- Contract tests validating yt-dlp field assumptions
- `distill doctor` tests API connectivity with live calls (not just key presence)

### MCP Server

- `distill/mcp_server.py` exposing core functionality via Model Context Protocol
- 8 tools: `catch_up`, `search_videos`, `learn_topic`, `process_video_url`, `watch_add`, `watch_remove`, `generate_report`, `resynthesize_topic`
- 7 resources: topics, watchlist, topic videos, topic/channel synthesis, video insights, costs
- 3 prompts: `daily_deals`, `morning_briefing`, `topic_research`
- `distill-mcp` entry point (stdio transport for Claude Desktop and IDE integrations)
