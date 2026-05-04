# Changelog

All notable changes to this project will be documented in this file.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Planned

- Obsidian-native output: wiki-style cross-linking and `distill open --vault` hint. See ROADMAP section 10 (Tier 1).
- LLM-maintained concept and entity notes, intelligent merging on refresh, contradiction flagging. See ROADMAP section 10 (Tier 2).
- Goal-file refresh hook for `distill watch`: re-run discover against a saved goal file on a schedule so goal-driven topics stay current the same way keyword topics do.
- Discovery-loop hardening (rerank determinism, rigor knob, real cost estimator, preview-as-primary UX, synthesis register styles). See ROADMAP section 12.

## 0.4.0 — 2026-07-14

Package restructure: flat `distill/` → layered subpackage architecture.

### Added

- **Layered subpackage architecture.** The flat `distill/` package is now organized into focused subpackages: `commands/` (one Typer command group per file), `ingestors/` (YouTube, sites, papers), `pipeline/` (analysis, synthesis, report orchestration), `library/` (filesystem corpus layer), `prompts/` (all prompt templates), and `mcp/` (MCP server split by concern).
- **Structured logging.** `configure_logging()` with `--debug` CLI flag. Console handler emits WARNING+ by default, DEBUG with `--debug`. File handler always writes DEBUG to `library/.distill/distill.log`.
- **SecretStr for API keys.** `xai_api_key`, `gemini_api_key`, and `openai_api_key` in `DistillConfig` now use Pydantic `SecretStr` — keys are masked as `'**********'` in logs, repr, and debug output.
- **import-linter dependency direction enforcement.** Three contracts in `pyproject.toml` enforce that foundational layers (`library/`, `prompts/`) never import from higher layers, ingestors don't import from commands/pipeline/mcp, and pipeline doesn't import from commands/mcp. Run `lint-imports` to verify.
- **Mirrored test layout.** Test directory structure under `tests/unit/` mirrors the source layout (`tests/unit/commands/`, `tests/unit/ingestors/youtube/`, `tests/unit/pipeline/analysis/`, etc.). Integration tests live in `tests/integration/`.

### Changed

- **`cli.py` reduced to ≤65 lines.** All business logic lives in `_cli_impl.py`; command groups are thin Typer wrappers in `distill/commands/`.
- **`mcp_server.py` split into `mcp/` subpackage.** Transport in `server.py`, tools in `tools/`, resources in `resources.py`, prompts in `prompts.py`.
- **`prompts.py` split into domain-specific files.** `prompts/analysis.py`, `prompts/synthesis.py`, `prompts/report.py`, `prompts/discover.py`, `prompts/shared.py`.
- **Backward-compatible shims removed.** Old flat-file import paths (`distill.artifacts`, `distill.discovery`, `distill.analysis`, etc.) are no longer available. Use the canonical subpackage paths.
- **`router_config_from_distill()` updated** to call `.get_secret_value()` on SecretStr fields.
- **Pre-push checklist** now includes `lint-imports` step.

## 0.3.1 — 2026-05-03

LLM router abstraction and model upgrade.

- **LLM router package** (`distill/llm/`). Centralized workload-to-provider dispatch replaces 26 scattered LLM call sites across 11 modules. Single entry point (`distill.llm.call()`) with per-prompt telemetry, unified cost registry, and provider caching.
- **Grok 4.3 default.** Both fast and premium tiers now default to `grok-4.3` ($1.25/$2.50 per 1M tokens) — better quality at roughly half the cost of the previous `grok-4.20-0309-reasoning`.
- **Multi-provider architecture.** Provider protocol (`typing.Protocol`, async-ready) supports xAI (Grok), Google (Gemini), and Agent/Skill mode. Anthropic, OpenAI, and Ollama stubs registered for future milestones. Per-workload provider overrides via `DISTILL_{WORKLOAD}_PROVIDER` env vars.
- **Agent/Skill provider.** Zero-cost deferred execution mode for users with agentic assistants. Writes structured task files with SHA-256 prompt hashing for idempotent lookup.
- **Per-prompt telemetry.** Every LLM call emits a `Telemetry_Record` to `library/.distill/telemetry.jsonl` with model, workload tag, token counts, elapsed time, run_id, and outcome.
- **Unified cost registry** (`distill/llm/cost.py`). Single source of truth for all model pricing. `distill/costs.py` delegates to it. Supports per-token and per-query pricing models.
- **Ops_Dir separation.** Operational data (telemetry, cost logs, task queues) moved to `library/.distill/` — a hidden dotdir that keeps the corpus clean for any markdown tool. Existing `cost_log.jsonl` auto-migrated on first run.
- **Quality conventions established.** `distill/llm/` ships with `# pyright: strict`, 400-line module cap, C901 complexity enforcement, 80%+ test coverage, and 11 Hypothesis property-based tests. Pyright blocking in CI for the new package.
- **Backward-compatible configuration.** All existing `.env` variables continue to work unchanged. New `DISTILL_PROVIDER` and per-workload provider overrides are additive.

## [0.3.0] — 2026-04-28

Knowledge-base artifact contract: generated Markdown now behaves like a durable PKM / AI-native corpus instead of a pile of repeated generic filenames.

### Added

- Globally descriptive artifact names for new Markdown and text outputs, such as `<video-slug>_Insights.md`, `<paper-slug>_Paper.md`, `<topic>_Topic_Synthesis.md`, `<topic>_Report.md`, and `<topic>_Topic_Diff.md`.
- Standard YAML frontmatter on generated Markdown artifacts, including fields such as `title`, `type`, `topic`, `source`, `source_id`, `url`, `date`, `authors`, `tags`, `confidence`, and artifact-specific metadata.
- Shared artifact helpers for modern filename generation, frontmatter writing, and legacy fallback reads.

### Changed

- Video, paper, website, synthesis, briefing, report, topic-watch, MCP, dashboard, and web routes now read through the shared artifact layer.
- Existing libraries with legacy names such as `insights.md`, `paper.md`, `content.md`, `synthesis.md`, and `topic_synthesis.md` remain readable, but new writes use the knowledge-base naming contract.
- README and output docs now frame Distill as a local corpus engine for Markdown tools, MCP clients, and AI assistants rather than an Obsidian-only integration.
- ROADMAP pulls the stable slug/frontmatter work forward into the 0.3 build and leaves wiki-links/concept notes for the later living-wiki milestones.

### Fixed

- Stale or missing local installs now work cleanly when reinstalled from the current checkout.
- CI formatting drift from the artifact naming work was normalized with `ruff format`.

## [0.2.0] — 2026-04-27

Discovery loop hardening: goal-aware cross-source front door, yt-dlp robustness, and a clean preview → approve → ingest workflow that surfaces costs and respects what the user actually asked for.

### Added

- **`distill discover "<goal>" --topic X`** — goal-aware cross-source front door. Takes a natural-language research goal, has Grok generate paper + video search queries, fans out to arXiv and YouTube, runs a unified *goal-aware* LLM rerank across both source types (scores on goal_fit / depth / complementarity), shows a single ranked table of mixed papers and videos, and — after interactive confirmation — ingests the shortlist through the existing paper and video pipelines. Flags: `--topic/-t`, `--paper-limit`, `--video-limit`, `--papers-only`, `--videos-only`, `--days`, `--shorts/--no-shorts`, `--preview`, `--yes/-y`, `--goal-file`.
- **`--goal-file` for `distill discover`** — mirrors the `--context-file` pattern from `research-brief` and `synthesize`. The goal argument can now be loaded from a markdown file, enabling reusable, goal-driven topic refreshes (e.g. save `private/ai-composer-goal.md` and re-run discover against it on a cadence without retyping).
- **`distill discover --papers-only` / `--videos-only`.** Mutually exclusive flags that explicitly skip one source type. Skipping a side short-circuits the LLM query-generation call for that side so you don't pay for queries the run will throw away. Useful when a topic has thin or unrigorous YouTube coverage (run papers-only) or is dominated by talks/lectures with little formal-paper presence (run videos-only).
- **`distill latest --top-by-date`.** Strict "last N uploads in the window" semantics — bypasses both the LLM rerank and the heuristic relevance/depth mix and sorts the final pick purely by upload date (most recent first). Channel cap still applies so one prolific uploader can't monopolize the slate. Implies `--no-rerank` so query-expansion spend doesn't get billed for output that's then ignored. Use when you literally want "what got uploaded recently" rather than "what's most relevant in the window."
- **`distill papers` query expansion, LLM rerank, and `--preview`** — brings `distill papers` to parity with `distill latest`. One user query now expands into up to six arXiv search variants (heuristic + Grok), results are deduped by `paper_id` across variants, and a Grok-based rerank (`RankedPaper` with relevance / depth / novelty / credibility scores) picks the top-N *before* per-paper PDF analysis. `--preview` short-circuits to the ranked table for inspection without ingestion. New flags: `--preview`, `--sort relevance|date` (new default: relevance), `--expand/--no-expand`, `--rerank/--no-rerank`. arXiv multi-query calls are spaced 3.5s apart to respect rate limits.
- **yt-dlp staleness preflight.** Commands that rely on yt-dlp (`channel`, `search`, `explore`, `learn`, `latest`, `discover`, `topic update`, `catch-up`, `topic-watch run`, `ramp-up`) run a cheap version-age check on entry. yt-dlp uses date-stamped releases (`2026.3.17`), so the check parses the version locally with no network call. If the install is more than 14 days old, a single non-blocking warning points at `distill doctor --update`. Result is cached for 24h in `library/.preflight.json`; honors `DISTILL_NO_PREFLIGHT=1` for CI/scripted runs.
- **`distill doctor --update`** upgrades yt-dlp via `pip install --upgrade yt-dlp` and invalidates the preflight cache so the next run re-validates. The doctor's Tools section now shows yt-dlp age (`(3d old)` green, or yellow with a hint when stale, or "(latest available release)" in dim when an update was just attempted and pypi has nothing newer).
- **Extractor-failure hint in discovery errors.** When yt-dlp raises an extractor-style error in `discover_videos` or `search_videos` (matched on patterns like `extractor`, `unable to extract`, `sign in to confirm`, `HTTP error 4xx`), Distill prints a one-line hint pointing at `distill doctor --update` so users can connect the symptom to the fix.
- **Preview-mode cost logging.** `distill discover --preview`, `latest --preview`, `papers --preview`, `search`, `explore`, `topic-watch run --preview`, and `monitor --preview` now write a separate `<command>_preview` row to `library/cost_log.jsonl`. Iterative preview cycles (probe, retune, re-probe to size a real run) used to disappear from cost telemetry; they're now visible in `distill costs` and can be summed independently of ingest spend.
- **`log_preview_cost` helper in `distill.summary`.** Lightweight call site for any future preview path: `log_preview_cost(tracker, log_dir, command, metadata=...)`. No-ops on empty trackers so preview paths can call it unconditionally without producing zero-row noise.

### Changed

- **`distill papers` default behavior.** Previously: literal query, newest-first by submission date, all top-N ingested blindly. Now: expanded, reranked, relevance-sorted, top-N picked by LLM. The old behavior is still available via `--no-expand --no-rerank --sort date`. This fixes the failure mode where generic queries (e.g. "music theory deep learning", "automatic harmonization") pulled in unrelated subfields (physics, image processing) because arXiv's tokenizer has no concept of research intent.
- **`distill doctor --update` post-upgrade reporting.** When pip reports `Requirement already satisfied` (i.e. you're already on the latest published yt-dlp release), doctor now says "yt-dlp v… is already the latest published release" instead of falsely claiming "upgraded to v…". In the same run, the Tools section suppresses the "X days old; run `distill doctor --update`" nag — pypi simply doesn't have a newer release yet — and shows "(latest available release)" instead.
- **Preflight banner uses an ASCII marker.** The `⚠` glyph in the yt-dlp staleness banner has been replaced with `!` so the warning still prints even on terminals that somehow bypass the UTF-8 stdio bootstrap.
- **API: `update_ytdlp()` returns `(ok, detail, was_noop)`** instead of `(ok, detail)`. Callers (only the `doctor` CLI command in-tree) updated. Lets the doctor distinguish a real upgrade from a no-op.

### Fixed

- **Windows cp1252 console crash.** A default Windows console encodes stdout as cp1252, which raised `UnicodeEncodeError` on the `⚠` glyph in the yt-dlp staleness preflight banner — every Distill command that touched yt-dlp would crash on first run if the install was older than 14 days. Fixed by reconfiguring `sys.stdout` and `sys.stderr` to UTF-8 with `errors="replace"` at process startup via a side-effect import of `distill._bootstrap`. Idempotent and silent under pytest capsys / pipes / redirected streams.
- **`distill topic show` corpus counts.** `_count_paper_corpus(config, topic)` and `_count_site_corpus(config, topic)` were called with a single string but expected `list[str]`, so the count iterated character-by-character and almost always returned 0 (and the site call interpolated a `(0, 0)` tuple into the Corpus line). Now passes `[topic]` and unpacks to a clean "N site(s) / M page(s)" line.
- **`distill doctor` yt-dlp version probe.** The previous code accessed `yt_dlp.version.__version__` (an indirect submodule attribute pyright already flagged). If yt-dlp ever restructures, doctor would falsely report "yt-dlp not found." Switched to `importlib.metadata.version("yt-dlp")`.
- **`yt_dlp.utils.DateRange` constructed inside the try/except in `discover_videos`.** The dict was previously built before the `try:` block, so any future yt-dlp restructuring of the `utils` namespace would crash discover before the safety net catches it. Now the construction is inside the `try:`.
- **CI green across the board.** Three test failures, the security scan, and lint were all failing on Linux runners while passing locally on Windows. Fixes: `getattr(os, "startfile", None)` so the `open` command can be exercised cross-platform; `console.legacy_windows` check no longer gated by `os.name == "nt"`; `console.print` + `typer.Exit(2)` instead of `typer.BadParameter` for `site --report` + `--scrape-only` validation (Typer 0.24's rich-formatted error broke the substring assertion in CI); `pip-audit --skip-editable --ignore-vuln CVE-2026-3219` (the editable self-install is not on PyPI under this name yet, and pip 26.0.1 has an unfixed CVE upstream); pyright `reportAttributeAccessIssue`/`reportArgumentType`/`reportAssignmentType`/`reportReturnType`/`reportIndexIssue`/`reportPossiblyUnboundVariable` demoted to warnings (dominated by third-party stub gaps in mcp/yt-dlp/python-docx and typer Optional artifacts).
- **arXiv query building no longer phrase-matches 3+ word queries.** `_build_search_query` used to wrap any multi-word query in quotes for strict phrase matching. That was too strict for LLM-generated queries like `"symbolic music transformer composition"`, which returned zero results as a literal phrase even when the target papers existed. New policy: 1 word → single-term; 2 words → phrase match (naturally phrasal); 3+ words → AND-joined tokens so every term must appear but not necessarily adjacent. Pre-operator input (quotes, AND/OR, parens) still passes through untouched.

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
