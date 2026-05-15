# Changelog

All notable changes to this project will be documented in this file.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Planned

- LLM-maintained concept and entity notes, intelligent merging on refresh, contradiction flagging. See ROADMAP section 10 (Tier 2).
- Goal-file refresh hook for `distill watch`: re-run discover against a saved goal file on a schedule so goal-driven topics stay current the same way keyword topics do.
- Discovery-loop hardening (rerank determinism, rigor knob, real cost estimator, preview-as-primary UX, synthesis register styles). See ROADMAP section 12.

## 0.8.0.1 - 2026-05-15

Build-config fix. **0.8.0 on PyPI was broken**: the explicit `[tool.setuptools] packages` allowlist in `pyproject.toml` was missing the new `distill.concepts`, `distill.doctor`, and `distill.cli_support` subpackages, so the published wheel was missing those packages and every CLI path that touched them (`distill concepts`, `distill doctor`, the local-inference recommendations in doctor output) crashed with `ModuleNotFoundError` on a fresh install. Caught during a post-release validation install.

- Switch from explicit packages allowlist to `[tool.setuptools.packages.find]` with `include = ["distill*"]`. New subpackages now auto-discovered; the class of bug is eliminated.
- Verified the 0.8.0.1 wheel bundles `distill/concepts/`, `distill/doctor/`, and `distill/cli_support/` before publishing.

No source code or behavior changes -- this is a packaging-only patch.

## 0.8.0 - 2026-05-15

**Concept playbook.** Per-topic concept and entity notes that accumulate evidence across the corpus. When the 21st paper on a topic mentions a technique, distillr strengthens what it knows about that technique instead of just appending another insight file. This is the qualitative shift the roadmap has been pointing at: distillr stops being a batch processor and starts maintaining a knowledge base.

### What's new

- **New subpackage `distill/concepts/`.** Per-insight LLM extraction (one call per `_Insights.md`), append-only `mentions.jsonl` audit log, pure-Python deterministic merge, ACE-style itemized playbook notes at `library/topics/<topic>/concepts/<slug>.md` and `library/topics/<topic>/entities/<slug>.md`, JSONL rollups at `concepts.jsonl` / `entities.jsonl`.
- **Credal-interval evidence bounds.** Frontmatter stores `helpful_evidence: [lower, upper]` and `harmful_evidence: [lower, upper]` where the lower bound counts unambiguous evidence and the upper bound additionally counts neutral mentions. The width is the disagreement / ambiguity margin. Scalar `helpful_count` / `harmful_count` derived views ship alongside in `concepts.jsonl` for ergonomic reads.
- **Deterministic delta merges.** The merge layer is pure Python: commutative under source ordering, idempotent under repeated application, monotonic-widening when new sources arrive. Property tests at 200 examples each pin the invariants.
- **`.history/` versioning.** Before overwriting an existing concept note, the prior content is snapshot to `library/topics/<topic>/.history/<slug>/<iso-timestamp>.md`. Idempotent: re-running the pipeline on an unchanged corpus writes nothing.
- **Contradiction surfacing.** Contested concepts (both polarities present) lift into `distill health <topic>` output, grouped by topic with helpful/harmful counts and source totals.

### CLI

- **`distill concepts <topic>`** — standalone command, idempotent. Flags: `--refresh` (re-extract over every insight), `--threshold N` (minimum distinct sources to emit, default 3), `--json` (envelope output).
- **`--concepts` opt-in flag** on `distill papers`, `distill latest`, `distill site-batch` so a single ingest produces concept notes in the same run. Best-effort: extraction failures don't fail the ingest.
- **`distill health <topic>`** extended with a "Contested concepts" section listing each contested concept with its helpful / harmful evidence counts and source totals, grouped by topic.

### MCP surface

- `find_concepts(topic, query, kind, contested_only, limit)` — ranked concept-row search across per-topic concepts.jsonl + entities.jsonl. Filters by name substring, kind, contested flag. Returns JIT shape (path + scalar fields + count).
- `read_concept(path)` — library-relative concept playbook reader with path containment and concepts/entities subdirectory enforcement.
- `list_contested(topic, limit)` — convenience wrapper for contested-only retrieval.

### Architecture and routing

- New `concepts` workload tag in the LLM router. Routes to `fast_model` by default; per-workload override via `DISTILL_CONCEPTS_MODEL` / `DISTILL_CONCEPTS_PROVIDER` like every other workload.
- Concept extraction cost surfaces in `cost_log.jsonl` with `call_type="concepts_extract"`, separable from analysis spend in `distill costs`.

### Tests + coverage

- 152 new tests across the 0.8 surface: unit (records, normalize, merge, notes, exports, extract, contradictions), property-based (commutativity, idempotency, monotonic widening, lower<=upper invariant), CLI (CliRunner), MCP (3 tools), and end-to-end integration against a 5-paper fixture corpus.
- Coverage on `distill/concepts/` is 98% (well above the 90% bar for new subpackages).
- Total project coverage 82.75%, up from 82.07%.

### Out of scope (deferred)

The roadmap's original 0.8 entry bundled five items; this release ships only the playbook core. The other two land in follow-up patches per the revised roadmap:

- `confidence:` -> `synthesis_scope:` frontmatter rename + migration -> 0.8.1.
- `distill ingest <path>` for local PDFs / markdown / clipped articles -> 0.9 alongside discovery-loop and synthesis-depth work.

This keeps the playbook PR focused and the synthesis-rename / local-ingest changes properly scoped on their own.

## 0.7.2 - 2026-05-14

Patch release: synthesis-quality rewrite plus SSRF hardening on the PDF-attachment path.

### Synthesis quality

- Rewrite `paper_topic_synthesis_prompt` to demand cross-paper claims, a comparison matrix, concrete disagreements, and shared methodological blind spots. The previous prompt was producing topic-clustered capsule summaries that duplicated the per-paper Insights files; the new prompt explicitly calls out that anti-pattern and requires multi-paper attribution on every claim.
- Skip `synthesize_corpus` when the only source section is paper synthesis. Running corpus synthesis over a single section was a summary-of-a-summary with zero new signal; the paper synthesis already is the corpus synthesis for papers-only topics.

### Security

- PDF attachment ingestion now disables auto-redirects and re-validates every redirect target (max 5 hops) through `is_public_web_url`. Closes the redirect-bypass gap in the SSRF/size-cap hardening shipped in 0.7.1's security pass — a redirect to `127.0.0.1` or RFC1918 is now rejected before the fetch.

### Tests + coverage

- Added unit coverage across costs, router, MCP tools, attachment redirect handling, scraper, learning flow, preflight, and report pipelines. Total coverage is now 82%+ on `distill/`.

## 0.7.1 - 2026-05-08

Patch release with hardening fixes found during QA.

- Fix: Windows reserved device names (NUL, CON, PRN, etc.) in slugs now prefixed with underscore to avoid filesystem errors.
- Fix: Wiki-link display titles now strip pipe, bracket, and newline characters that would break Obsidian syntax or markdown rendering.
- Fix: `scan_legacy_artifacts` skips hidden directories (.git, .hypothesis, etc.).
- Fix: `distill doctor --links --json` uses the standard JsonEnvelope wrapper for consistency with other commands.
- Fix: Global `--json` flag is respected in `doctor --links` mode.
- Fix: Path comparison in migration uses `Path.is_relative_to()` instead of string prefix matching.
- Fix: `emit_wiki_link` validates that `corpus_dir` is a directory before globbing.
- Fix: Artifact type fallback in WikiLink handles hyphens correctly (e.g., `custom-type` becomes `Custom_Type`).

## 0.7.0 — 2026-05-07

Living Wiki. The corpus shifts from a directory of artifacts to a navigable knowledge base interoperable with Obsidian, Logseq, and Dendron. Also ships critical code-health prerequisites that prevent compounding debt in later milestones.

### Wiki-link discipline and Obsidian interop

- **Wiki-style cross-linking.** Synthesis, brief, report, and research-brief outputs now emit `[[slug_Insights|Title]]` references instead of plain-text citations. Obsidian's backlink panel and graph view work out of the box.
- **Stable slug discipline.** `slugify_title` is deterministic, filesystem-safe on all platforms (including Windows reserved names like NUL/CON), and handles collision disambiguation via `.source_meta.json`.
- **`distill doctor --links`.** Scans the corpus for broken wiki-links. Supports `--json` for structured output and `--fix` to replace broken links with plain-text citations.
- **`distill open --vault`.** Opens the library directory in your default editor or Obsidian. Respects `DISTILL_VAULT_EDITOR` env var. Supports `--path` for subdirectories.
- **Backfill / migration tooling.** `distill doctor --migrate-links` scans for legacy-named artifacts (`insights.md`, `synthesis.md`, etc.) and proposes renames to the modern `<slug>_Insights.md` convention. Dry-run by default; `--apply` executes.

### Artifact provenance in frontmatter

- Every generated artifact now records `model`, `model_version`, `temperature`, and `prompt_id` in YAML frontmatter. This is the foundation for reproducibility — outputs can be compared across model versions and prompt iterations.
- All pipeline stages (video analysis, paper analysis, site analysis, synthesis, brief, report, research-brief) write provenance fields.

### CLI decomposition

- `_cli_impl.py` reduced from ~6,800 lines to 22 lines (re-export shim). All business logic moved to `distill/commands/_logic.py`.
- `cli_support/` absorbed into `commands/` package (`_learning.py`, `_learning_flow.py`, `_topic_changes.py`).
- CLI interface unchanged: all command names, flags, arguments, and help text preserved.

### Path and slug centralization

- `slugify_title`, `sanitize_path_component`, and `site_name_from_url` moved from `config.py` to `distill/library/paths.py` (architecturally correct foundational layer).
- Old imports from `distill.config` emit `DeprecationWarning` and delegate.

### Legacy router bridge removal

- Deleted `router_config_from_distill` and `apply_model_override` from `config.py`.
- `RouterConfig` is now a Pydantic `BaseSettings` subclass reading env vars directly (API keys from canonical names, routing from `DISTILL_` prefix).
- `config.py` has zero imports from `distill.llm`.

### Report-phase retry hardening

- The 3-failure circuit breaker in the report accordion now uses exponential backoff with jitter (base 2s, up to 50% jitter).
- `LLMCall` dataclass (`distill/llm/call.py`) captures full request/response metadata for debugging.
- `distill/llm/retry.py` provides reusable `retry_with_backoff` and `compute_delay` functions.
- Failed and retry-success attempts are logged with structured `LLMCall` records.

### Quality

- 12 correctness properties validated via Hypothesis property-based testing (slug determinism, filesystem safety, collision disambiguation, wiki-link format, frontmatter round-trip, provenance completeness, retry delay bounds, RouterConfig env mapping, link integrity, migration correctness).
- 1,275 tests passing. New modules at 84–100% coverage.
- Import-linter: 3 contracts kept, 0 broken.
- Ruff zero-warning. Pyright zero-error on `distill/llm/`.

## 0.6.0 — 2026-05-06

Local inference with adaptive context. When ingestion is basically free (local models), you use it more — more sources, more frequent refreshes, richer corpus. Quality bar is the same as cloud.

### Added

- **Ollama provider.** Full implementation using httpx for the Ollama HTTP API. Retry with exponential backoff, connection error handling with descriptive messages, context window detection via `/api/show`, model listing via `/api/tags`.
- **LM Studio provider.** OpenAI-compatible client pointed at `localhost:1234/v1`. Supports `LMSTUDIO_BASE_URL` env var override.
- **Provider metadata.** `ProviderMetadata` dataclass with context window, provider type (local/cloud), and provider name. Automatic resolution for both local (queried from API) and cloud (lookup table) providers.
- **Adaptive chunking.** Section-aware content splitting when content exceeds the provider's context window. Preserves heading context in each chunk. Passthrough when content fits. Automatic based on provider metadata — users don't configure this.
- **Per-category reranking.** Keyword-based scoring of chunks by relevance to each insight category (Key Findings, Methods, Limits, Open Questions). Top-k selection within context window. Skips categories where all chunks score below threshold.
- **Multi-pass analysis.** Focused per-category passes over chunked content, merged into a unified insight matching the same structure as single-pass cloud analysis. Deduplication of overlapping insights.
- **Report compaction.** High-recall summaries (25% of original) between report pipeline phases, preserving all named entities and quantitative claims. Precision second pass (10%) when first pass still exceeds window. Applied universally (cloud and local).
- **Hardware detection.** `distill doctor` detects NVIDIA GPUs (via nvidia-smi), Apple Silicon (via sysctl), system RAM, and container environments.
- **Model recommendations.** Hardware-tier-based model suggestions (4090 → qwen3.5:27b, M1 16GB → qwen3.5:14b). Configurable via JSON file. Includes pull commands for missing models.
- **Quality gate (stub).** `EvalResult` dataclass and `run_eval_suite()` interface ready for Phase 9 baselines.
- **Cost display — local/cloud split.** `distill costs` shows cloud spend (USD) and local inference time (seconds, tokens/second) separately.
- **`--model` CLI override.** Global `-m`/`--model` flag forces all workloads to a specific model for the invocation.
- **Docker support.** `Dockerfile` with Playwright deps and `docker-compose.yml` with Ollama GPU passthrough, library volume mount, and MCP server port exposure.
- **Telemetry extension.** `provider_type`, `provider_name`, and `tokens_per_second` fields in telemetry records. Backward compatible with existing JSONL.

### Changed

- Router imports `LOCAL_PROVIDERS` from metadata module for provider type classification.
- `_emit_telemetry()` accepts and passes provider metadata fields.
- Paper analysis pipeline checks provider metadata and invokes chunker when content exceeds context window.

### Quality

- 1069 tests passing (unit + integration).
- 13 property-based tests for local inference: response parsing, model passthrough, retry count, provider classification, chunk size invariant, content preservation, chunking decision, heading context, compaction length, entity preservation, telemetry round-trip, token estimation, router resolution.
- `ruff check`, `ruff format`, and `lint-imports` all pass cleanly.

## 0.5.0 — 2026-05-06

MCP-first surface + Grok 4.3 migration. The MCP server becomes the primary product surface, and all model references are updated ahead of the May 15 xAI retirement deadline.

### Added

- **JIT context retrieval.** New `find_insights(topic, query)` MCP tool returns ranked `(path, preview, score)` tuples — agents get paths and one-line previews instead of full file payloads (~96% token savings). `read_insight(path, section?)` drills down into specific artifacts or sections.
- **Structured CLI output.** Global `--json` flag on every command produces machine-readable `JsonEnvelope` output to stdout. Diagnostics go to stderr. `NO_COLOR` is respected.
- **Stable exit codes.** Documented exit codes (0–5) for success, runtime error, usage error, config error, network error, and not-found. Available in `docs/usage.md`.
- **New MCP tools.** `papers`, `discover`, `site_batch`, `synthesize`, `costs`, `doctor` mirror their CLI counterparts with progress events and structured results.
- **Progress events.** Long-running MCP tools emit progress notifications (per-paper, per-page, per-stage) so clients can display status and detect stalls.
- **Token-efficient tool descriptions.** All tool descriptions ≤100 chars, all parameter descriptions ≤50 chars. Reduces context window consumption when agents load multiple MCP servers.
- **`distill alerts` command.** CLI command to display watch-alert digest (Rich or JSON). MCP resource `distill://watch-alerts` returns clear message when no alerts exist.
- **Grok 4.3 as default model.** All workloads now default to `grok-4.3` (1M context window, $1.25/$2.50 per 1M tokens).
- **Reasoning effort configuration.** Per-workload `DISTILL_{WORKLOAD}_REASONING_EFFORT` env vars (low/medium/high). Premium workloads default to "high", fast-tier to "medium".
- **Retired model fallback.** If a retired model is configured, the router logs a deprecation warning and automatically substitutes the recommended replacement.
- **`distill doctor` retired-model check.** Warns when configured models are on the retirement list with specific replacement guidance.
- **Migration guide.** `docs/migration-grok-4.3.md` documents all 8 retired models, their replacements, and reasoning effort configuration.

### Changed

- Default `accordion_section_model` changed from `grok-4-1-fast-reasoning` to `grok-4.3`.
- Default `xai_site_model` changed from `grok-4.20-0309-reasoning` to `grok-4.3`.
- Cost table expanded with pricing for `grok-4.20-non-reasoning`, `grok-imagine-image`, and all 8 retired models (retained for historical cost computation).
- `RETIRED_MODELS` mapping and `RETIREMENT_DATE` constant added to `distill/llm/router.py`.

### Quality

- 960 tests passing (unit + integration).
- Property-based tests (Hypothesis) for: search ordering, limit bounds, preview format, section extraction, JSON round-trip, tool descriptions, schema validity, retired model fallback, reasoning effort override, cost table completeness, doctor output.
- `ruff check`, `ruff format`, and `lint-imports` all pass cleanly.

### Added

- **JIT context retrieval.** New `find_insights` and `read_insight` MCP tools enable agents to search the corpus by topic/query and receive ranked path/preview/score tuples, then drill down to specific sections — saving ~96% of tokens vs. full file payloads.
- **Search engine** (`distill/pipeline/search.py`). Term-frequency scoring with heading boost (2×) and type boost (1.5× for synthesis/corpus). Preview generation ≤120 chars. Section extraction by heading name.
- **Structured CLI output.** Global `--json` flag on all commands produces a `JsonEnvelope` (status/data/error) on stdout with diagnostics on stderr. No ANSI codes in JSON mode.
- **Stable exit codes.** 0=success, 1=runtime, 2=usage, 3=config, 4=network, 5=not-found. Documented in `docs/usage.md`.
- **6 new MCP tools.** `papers` (arXiv search + ingest), `discover` (goal-aware cross-source), `site_batch` (URL list scraping), `synthesize` (topic synthesis), `costs` (LLM spend history), `doctor` (environment health check).
- **Progress events.** Long-running MCP tools (`papers`, `discover`, `site_batch`, `synthesize`) emit MCP SDK progress notifications per-item.
- **Token-efficient descriptions.** All tool descriptions ≤100 chars, all parameter descriptions ≤50 chars. Semantic accuracy preserved.
- **`distill alerts` command.** Displays the watch-alert digest in Rich (default) or JSON (`--json`).
- **Property-based tests.** 12 Hypothesis properties covering search ordering, preview format, JSON round-trip, description limits, schema validity, and progress events.

### Changed

- **Tool descriptions rewritten.** All 9 existing tools + 8 new tools now have compressed descriptions within the character limits.
- **MCP server imports.** New tool modules (`find`, `papers`, `sites`, `synthesis`, `costs`, `doctor`) registered in `server.py`.

### Backward Compatibility

- All 9 existing tool input schemas preserved (no type/required/default changes).
- All 12 resource URIs respond unchanged.
- All 4 prompts retain their argument signatures.
- CLI output without `--json` is identical to 0.4.0 behavior.

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
