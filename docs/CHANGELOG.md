# Changelog

All notable changes to this project will be documented in this file.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Planned

- **1.0 verification depth** — Design by Contract (`deal`) on the deterministic core, mutation testing, Hypothesis stateful testing of the playbook lifecycle, and fault-injection at external boundaries; "parse, don't validate" strict domain types at every boundary. See the 1.0 quality bar in [`ROADMAP.md`](../ROADMAP.md#100--stability-commitment--quality-bar).
- LLM-maintained concept and entity notes, intelligent merging on refresh, contradiction flagging. See ROADMAP section 10 (Tier 2).
- Goal-file refresh hook for `distill watch`: re-run discover against a saved goal file on a schedule so goal-driven topics stay current the same way keyword topics do.
- Discovery-loop hardening (rerank determinism, rigor knob, real cost estimator, preview-as-primary UX, synthesis register styles). See ROADMAP section 12.

## 0.9.5 - 2026-06-01

**Cost estimates and budget guardrails recalibrated to the actual default model.** The pricing *registry* (`distill/llm/cost.py`) was already correct and current (verified against June-2026 rates: grok-4.3 $1.25/$2.50, grok-4.20 $2/$6, gemini-3.1-pro $2/$12, gemini-3.5-flash $1.50/$9, Deep Research ~$2.50/$5), but the cost *estimates* still used the retired `grok-4-1-fast` rate (~$0.006/video) while `config.py` defaults every workload to `grok-4.3` (~$0.03/video). So pre-run estimates — including the `--max-run-cost` / `--monthly-budget` projections — under-counted real spend ~5×, and the budget guard fired too late.

- **Estimates now derive from the pricing registry, not hard-coded dollars.** New `_STAGE_TOKENS` + `estimate_stage_cost(stage)` in `distill/pipeline/costs.py` compute each stage's cost from representative token volumes × the current default model's pricing, so the estimate tracks the model and can never silently drift again. Rewired `estimate_run_cost`, `estimate_discover_cost` defaults, `estimate_topic_watch_cost` / `estimated_topic_watch_sweep` (the budget-guard projection), and `display_estimate`.
- **Net effect:** budget projections are now accurate on grok-4.3 (a 10-video watch projects ~$0.31 + report, not ~$0.06 + report), so `--max-run-cost` and `--monthly-budget` actually protect. The 0.9.1 self-calibrating estimator still overrides these with measured rates once a topic has history; these are the model-accurate cold-start fallback.
- **Docs:** `cost.md` per-stage table, example runs, and budget guidance recomputed at grok-4.3; README cost section and sample-run figure corrected (the $1.01 sample was grok-4.20 pricing; at the grok-4.3 default the same run is ~$0.58). The retired fast tier remains selectable via `XAI_FAST_MODEL` for users who want bulk-cheap over fidelity.

## 0.9.4 - 2026-06-01

**`--rigor` across `discover` / `papers` / `latest`, on calibrated thresholds.** The quality-bar knob that only `discover` had now works on the single-source commands too — drops reranked candidates below a `final_score` floor before the per-source limit. This completes the 0.9 discovery-loop close-out.

- **Calibrated per command, not copy-pasted.** The three rerank prompts score on different criteria, so the thresholds differ: discover (cross-source goal-fit gate) 0.70/0.50/0.30; papers 0.65/0.45/0.30; latest 0.60/0.40/0.25. The calibration is grounded in a documented case — discover rated 0/33 videos worth ingesting on a topic where `latest` surfaced 5 strong picks — and the rationale (curation gate vs. single-source relevance ranker) is written up in `docs/architecture.md` ("Rigor calibration"). New `PAPER_RIGOR_THRESHOLDS` / `VIDEO_RIGOR_THRESHOLDS` + `source_rigor_threshold(source, rigor)` in `distill/pipeline/discovery.py`.
- **Opt-out, never surprising.** On `papers` / `latest` the default is `off` (keep the rerank's top picks exactly as before); the bar engages only when you ask for `strict`/`balanced`/`loose`. `discover` keeps its `balanced` default (unchanged since 0.8.12).
- **Honest about scope.** Rigor scores on the *LLM rerank*, so under `--no-rerank` (or chronological `--top-by-date`) an explicit bar is skipped with a warning rather than applied to heuristic scores on a different scale. When a bar is applied, a `kept X/Y` line shows what it dropped. `papers`/`latest` rerank the full candidate pool before the limit when a bar is set, so the threshold has something to cut.

## 0.9.3 - 2026-06-01

**Preview-as-default sizing on fresh topics.** `distill discover "<goal>" --topic <new>` no longer auto-applies a fixed `--rigor` bar and ingests; on a topic with no artifacts yet it now shows the reranked candidates and a **size-then-approve menu** — "Excellent / Including good / Everything worthwhile" — each line carrying its source breakdown and its own 0.9.1 spend estimate, so you choose the depth against the real quality cliff and the real cost before committing. This is the preview-as-primary-flow the roadmap (section 12) was built around.

- New pure `build_sizing_options` + `SizingOption` in `distill/pipeline/discovery.py`: derives a nested ladder from the score cliff (`detect_score_cliff`) and the balanced/loose rigor thresholds, caps each cut by the per-source limits, de-duplicates cuts that resolve to the same set, and attaches a per-option `CostEstimate`. Fully tested, no IO.
- The chosen set is saved to the 0.9.2 preview cache and its id printed, so any selection is re-runnable verbatim with `--from-preview`.
- **Behavior is opt-out, never surprising.** `--yes` keeps the non-interactive path (rigor filter + auto-ingest); `--preview` and `--from-preview` are unchanged. Topics that already have artifacts keep the single-confirm flow unless you pass the new `--size` flag to force the menu.

## 0.9.2 - 2026-06-01

**Commit-by-id preview replay (`discover --from-preview <id>`).** The discover rerank is a judgment call, so the set you previewed could differ from the set a real run ingests. Now `discover --preview` saves the exact goal-ranked shortlist and prints an id; `discover --from-preview <id> --topic <t>` replays that set verbatim — skipping query-generation and the rerank entirely — so you commit to precisely what you saw. temperature=0 (0.8.12) makes a re-rank reproducible; replay guarantees it. Closes the cached-commit-by-id follow-on left open by 0.8.12 / 0.9.0.

- New `distill/pipeline/preview_cache.py` (pure functions, injected `now_iso`): `save_preview` writes `library/.preview_cache/<id>.json` under a **content-addressed** id (a hash of goal + model + rigor + member identifiers, so the same selection always gets the same id); `load_preview` faithfully reconstructs each `PaperRecord` / `VideoInfo` / `SiteSeed` so replay ingests identically. Unknown / malformed / corrupt ids raise `PreviewCacheError` with an actionable message — never a silent failure.
- The discover ingest path was extracted into a shared `_discover_ingest_set` helper (plus focused per-source sub-helpers), so the live flow and `--from-preview` replay ingest through one code path. `--from-preview` is mutually exclusive with `--from-gaps` / `--preview`.
- MCP parity is tracked separately: the MCP `discover` tool already returns candidates without ingesting (a preview by nature) and now carries the 0.9.1 `cost_estimate`; a dedicated replay arg follows when the MCP tool gains an ingest path.

## 0.9.1 - 2026-06-01

**Metadata-aware, self-calibrating discover cost estimate.** The pre-run spend line under a `discover` preview was a flat `count x constant`; it now reads free candidate metadata and calibrates against real history, and reports a range instead of a single point.

- **Per-video duration scaling.** Transcript-analysis cost tracks runtime, so each candidate video's share now scales linearly around a nominal 15-minute average (clamped 0.3x..4x); unknown duration assumes nominal. Papers keep a flat per-item rate (PDF page count is not fetched at discovery — it would need a network call), as do site seeds.
- **Self-calibrating rates.** `load_cost_calibration(log_dir)` derives per-paper / per-video / per-site USD rates from *clean single-source* runs in `cost_log.jsonl` (a paper-only run prices papers, etc.), so a mixed `discover` run never cross-contaminates a rate. `_preview` rows are skipped and a source type with fewer than 3 ingested items keeps its default constant. The rates improve as history accrues.
- **Honest range.** The estimate now prints `~$0.42 (est; $0.29-$0.63)` — an asymmetric band (overruns are more common than underruns) that widens to 0.5x..2.0x when no calibration exists yet and narrows to 0.7x..1.5x once it does.
- New `CostCalibration` / `CostEstimate` dataclasses, `load_cost_calibration`, and `estimate_discover_items` in `distill/pipeline/costs.py`; the count-based `estimate_discover_cost` stays (now calibration-aware) for simple callers. The MCP `discover` tool gains a `cost_estimate` field for parity. Closes the duration/length-aware calibration follow-on left open by 0.8.12 / 0.9.0.

## 0.9.0 - 2026-05-30

**Two-pass synthesis with a structured claim intermediate (opt-in).** The headline of the 0.9 milestone: synthesis can now run over an extracted *claim set* instead of re-reading every insight into one prompt.

- **New `distill/claims/` layer**, structured exactly like the 0.8 `distill/concepts/` playbook layer (frozen `Claim` records, a `ClaimRole` StrEnum — background / method / result / limitation / conclusion, LLM-produces-rows / Python-parses-rows split, deterministic JSONL round-trip).
  - Pass 1 — `run_claims(topic, ...)` walks every `_Insights.md`, extracts atomic claims (one cheap LLM call per not-yet-seen source, tagged `claims_extract` for separate cost tracking), and appends them to an append-only `<topic>/.claims/claims.jsonl`. Already-extracted sources are skipped, so refresh is cheap.
  - Each claim carries an optional subject/predicate/object triple, optional dataset/metric, an `evidence_type`, and a `role_confidence` score. The extractor chooses granularity per claim; low-confidence role tags are surfaced downstream rather than dropped. Claim ids are content-addressed (`source_id` + normalized-text hash) so re-extraction is stable and downstream scoring can cache by id.
  - Pass 2 — a new `claim_synthesis_prompt` clusters claims by what they assert, names contradictions between sources explicitly, cites every statement back to specific claim handles (`[C7]`), and flags low-confidence / single-source claims as the corpus's soft spots.
- **Opt-in wiring.** `distill resynthesize <topic> --two-pass` and the MCP `synthesize` tool's `two_pass` arg route the corpus synthesis through the claim set. Single-pass synthesis remains the default; two-pass falls back to single-pass when a topic has no extractable claims, so the flag never silently produces an empty synthesis.
- **Shared insight discovery.** The `_Insights.md` walk (`discover_insights` / `derive_source_id`) was lifted to a foundational `distill/library/insights.py` so the concept and claim layers share one implementation; a new import-linter contract keeps both knowledge layers below commands/mcp/web/ingestors.

Deferred to 1.0 (noted in the roadmap, not built here): per-claim fitness caching by `(claim_id, evaluator_id)`, the golden-eval gate that validates two-pass and flips the default, and metamorphic robustness checks.

## 0.8.12 - 2026-05-30

**Discovery-loop UX.** Makes `distill discover` a confident size-then-approve loop.

- **`--rigor strict|balanced|loose`** drops reranked candidates below a goal-fit threshold (0.7 / 0.5 / 0.3) before the per-source limits, so the shortlist reflects the quality bar you ask for.
- **Score-cliff sizing** — the shortlist now reports how many top items sit above the largest rerank-score drop (the "clearly-excellent" set), so you can size the ingest against the natural cliff.
- **Pre-run cost estimate** — a free-metadata estimate (`estimate_discover_cost`, count-based per source type) is shown before you commit, no extra network fetches.
- **Deterministic rerank** — the discover rerank LLM call now runs at `temperature=0`, so the previewed order is reproducible.

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

**Security hardening.** Closes the two genuinely-relevant security gaps for an API-consumer tool that ingests untrusted public sources. (The broader "AI security" surface — model poisoning, extraction, inversion, DP, enclaves — is out of scope by architecture: distillr trains and serves no models. See the new "Security posture" section in [`ROADMAP.md`](../ROADMAP.md#security-posture).)

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

- **Per-topic `library/topics/<topic>/CLAUDE.md`** — one-line summary (topic-synthesis lede), source counts (papers / videos / pages), a wikilink to the topic synthesis, "Ask me about" example queries from the corpus's named entities and concepts, and the read-surface MCP tool listing.
- **Library-root `library/CLAUDE.md`** — an index of every topic with one-line summaries and source counts.
- **Automatic regeneration** on every topic refresh: the synthesis writers (`synthesize_topic` / `synthesize_corpus`) regenerate the affected topic's file and the library index, best-effort so a failure never fails a synthesis.
- **`distill claude-md [<topic>] [--all]`** — manual regeneration / backfill for existing topics.

### Design notes

- All generation logic is pure functions in `distill/library/claude_md.py` (foundational layer): reads existing artifacts and the `concepts.jsonl` / `entities.jsonl` rollups as raw JSON (no `distill.concepts` import), injects `now_iso` for deterministic tests. `CLAUDE.md` is plain Markdown with no frontmatter. No new LLM calls, no new dependencies, no cost.

### Tests

`tests/unit/library/test_claude_md.py` (source counting, lede extraction, top concepts/entities, rendering, atomic write, library index, empty-topic skip) plus `tests/unit/commands/test_claude_md.py` for the CLI command.

## 0.8.3 - 2026-05-30

**Reproducible toolchain and engineering baseline.** A no-business-logic release that makes the build harness deterministic and self-enforcing. Motivated directly by 0.8.2, which shipped clean code yet broke CI when an unpinned `typer>=0.9.0` floated to typer 0.26 (it now vendors its own `click`, so `typer.Exit` stopped being `click.exceptions.Exit`). distillr had no lockfile, so every CI run re-resolved the whole dependency tree against the latest release of everything. This release closes that gap.

### What's new

- **`uv` as the sole toolchain.** Migrated from pip + setuptools to `uv`: a committed `uv.lock`, `uv sync --frozen` in CI for deterministic environments, `build-backend = "uv_build"`, and `[dependency-groups]` dev tooling replacing the `.[dev]` extra. The editable-install workflow is preserved (`uv sync` / `uv run`).
- **Python 3.12–3.14 support matrix.** Floor raised from 3.10 (EOL Oct 2026) to `requires-python = ">=3.12"`; classifiers updated; CI runs `[3.12, 3.13, 3.14]`; ruff and Pyright target 3.12. Deliberately not 3.14-only — distillr is a published library.
- **Dependabot** (`.github/dependabot.yml`): weekly grouped patch/minor updates with majors flagged; every bump runs full CI against the lock before merge.
- **Contracts now enforced in CI.** `import-linter` (dependency-direction layer contracts, previously configured but never run) and `pip-audit` are blocking lanes; `xfail_strict` and `--strict-markers` are on.
- **Branch coverage.** Coverage switched from line to branch metric, gated at the measured baseline (floor 79) and ratcheted up-only toward the 1.0 target of 95.
- **`pre-commit` identical to CI.** Lint/type/security/test hooks run via `uv run --frozen` (the exact locked versions CI uses); Pyright and import-linter added; full pytest on the pre-push stage.
- **Supply chain.** A CycloneDX SBOM ships as a build artifact, and PyPI publishing emits PEP 740 build-provenance attestations over the existing OIDC trusted-publishing channel.

### Incidental modernizations

The `py312` target surfaced two `(str, Enum)` enums (now `StrEnum`) and one generic function (now PEP 695 type-parameter syntax). Behavior-identical, verified by the suite.

### Verification

Full suite green across the 3.12 / 3.13 / 3.14 matrix (1633 tests each); ruff, ruff-format, Pyright (`distill/llm/`), import-linter (3/3 contracts), pip-audit, and `uv build` (wheel confirmed to bundle `distill/web` templates + static assets) all pass.

## 0.8.2 - 2026-05-29

**Playbook recovery surface.** 0.8 wrote `.history/<slug>/<iso-timestamp>.md` snapshots on every concept-note overwrite, but nothing could read or restore them — snapshot-without-recovery. This release adds the read and restore surface over data 0.8 already produces (no new LLM calls, no new dependencies).

### What's new

- **`distill concepts` is now a command group.** Extraction moved from `distill concepts <topic>` to **`distill concepts build <topic>`** so the group can host the recovery subcommands. (Pre-1.0 interface change; flags are otherwise identical.)
- **`distill concepts log <topic> <slug>`** — list a note's history snapshots, newest first, each annotated with a one-line summary of what changed at that step (sources added/removed, evidence-interval shifts, contested flips).
- **`distill concepts diff <topic> <slug> [ts_a] [ts_b]`** — diff a note across versions. No timestamps: most recent snapshot vs the live note. One timestamp: that snapshot vs live. Two: snapshot vs snapshot. Frontmatter changes surface as a structured delta (which evidence rows joined/left, how each interval bound moved, contested/scalar shifts); the body diffs as text.
- **`distill concepts rollback <topic> <slug> <timestamp>`** — atomically restore a prior snapshot. The current version is snapshot into `.history` first (so rollback is itself reversible), the chosen snapshot becomes the live note, and the matching `concepts.jsonl` / `entities.jsonl` rollup row is rebuilt from the restored note's frontmatter. `--yes` skips the confirmation prompt.
- **MCP companion tools** — `concept_history(topic, slug)` and `concept_diff(topic, slug, ts_a, ts_b)` expose the same read surface to agents, mirroring the existing `find_concepts` / `read_concept` shape.

### Design notes

- Rollback **reconstructs, never recomputes**: it restores the note and its rollup row from the snapshot's own frontmatter rather than re-running the merge, because `mentions.jsonl` is append-only and re-merging would reproduce the current state, not the requested snapshot.
- All recovery logic lives in pure functions in `distill/concepts/recovery.py` (filesystem IO only, injected `now_iso` for deterministic tests); the CLI and MCP layers are thin presentation over it.

### Tests

`tests/unit/concepts/test_recovery.py` (timestamp round-trips, snapshot enumeration/resolution, typed frontmatter parsing, structured diff, transition summaries, rollback incl. rollup rewrite / reversible backup / no-op / deleted-note recreation) plus CLI and MCP tests for the three commands and two tools. Overall coverage ≥80%.

## 0.8.1 - 2026-05-16

**Frontmatter rename.** The synthesis emitters wrote a `confidence:` field whose values (`single-paper`, `corpus-consensus`, `interpretation`, …) were always scope/routing labels, never calibrated confidence numbers. Renamed to `synthesis_scope:` so downstream consumers (Obsidian Dataview queries, MCP agents, custom scripts) don't mis-interpret the routing label as a numeric grade.

### What's new

- **`synthesis_scope:` everywhere** — `distill/library/paths.py::base_frontmatter` now writes `synthesis_scope:` instead of `confidence:`. Every emitter (per-paper insights, per-video insights, per-page insights, channel/topic/corpus synthesis, paper synthesis, site synthesis, accordion/briefing/deep-research reports, watch alerts, topic diffs, topic trends) updated to pass `synthesis_scope=…` instead of `confidence=…`.
- **`distill doctor --migrate-frontmatter [--apply]`** — one-shot migration over existing artifacts. Dry-run by default, lists each file that needs rewriting and the value being migrated. `--apply` executes the rewrite in place. Mirrors the `--migrate-links` pattern from 0.7. Idempotent: re-running on an already-migrated corpus is a no-op. Drops orphaned `confidence:` lines if a file ended up with both fields from a partial prior run.

### Migration

```bash
distill doctor --migrate-frontmatter            # dry-run, shows what would change
distill doctor --migrate-frontmatter --apply    # execute the rewrite
```

The migration scans `library/**/*.md` excluding hidden directories (`.history/`, `.distill/`, `.concepts/`) so versioned snapshots and operational artifacts stay untouched. New artifacts written after this release already use `synthesis_scope:` — the migration is only for pre-0.8.1 corpora.

### Tests

Eight new tests across the migration surface (scan/apply/idempotent/dropped-orphan-field/format-preservation). Coverage still ≥80%.

### Also fixed

- **`canonicalize` idempotency.** Hypothesis caught `canonicalize("000ss") == "000s"` but `canonicalize("000s") == "000"` — the plural-stripping regex `(\w{3})s\b` matched the inner three chars + terminal `s`, leaving the result still ending in `s` to be stripped again on a second pass. Tightened to `(\w{2}[^\Ws])s\b` so the char preceding the terminal `s` must itself be a non-`s` word char. Preserves `-ss` endings (`address`, `pass`, `less`) and short acronyms (`css`, `ml`). Failing example pinned via `@example(s="000ss")`.
- **Property-test HealthCheck flakes under coverage.** `tests/unit/library/test_paths_props.py`, `test_wikilinks_props.py`, `test_frontmatter_props.py`, `tests/unit/llm/providers/test_agent.py`, and one test in `tests/unit/llm/test_router.py` were hitting `HealthCheck.too_slow` (and occasionally `filter_too_much`) under `pytest --cov`'s tracing overhead. Strategies that map through `slugify_title` or that filter heavily via `assume()` are slow enough under instrumentation to exceed hypothesis's 2-second input-generation budget. Suppressed the relevant health checks. Tests still run at `max_examples=100`; the property semantics are unchanged.

### Out of scope (scope choice)

The per-source `Insights.md` values (`single-source`, `single-paper`, `source-content`) are also renamed, not just the cross-source synthesis values. The roadmap entry listed "synthesis emitters" but the rationale ("the field is a routing label, not a number") applies uniformly — partial renames would leave the same misnomer in the per-source files. Consistent rename now is cheaper than two migrations.

## 0.8.0.3 - 2026-05-16

Follow-up hardening on top of 0.8.0.2. Two bugs fixed, one stale annotation cleaned up.

### Security

- **`read_concept` absolute-path-parts bypass (medium).** 0.8.0.2 replaced the substring-based concept/entity guard with a check on `full_path.parts` — but `full_path` is the *absolute* resolved path, so its parts include ancestors outside `library_dir`. A user with `DISTILL_OUTPUT_DIR` configured under a directory named `concepts` or `entities` (e.g. `/home/alice/concepts/library`) satisfied the guard for every file in the library, letting an MCP caller read non-playbook artifacts (synthesis output, `.distill/tasks/` task artifacts, etc.). Fix: enforce the layout on the *library-relative* path — require exactly `topics/<topic>/(concepts|entities)/<file>.md` — instead of inspecting absolute parts. Regression tests cover library directories under `concepts` and `entities` ancestors, plus shape edge cases (history-snapshot paths, non-`.md` sidecars, top-level files).

### Correctness

- **Search artifact-type misclassification under ancestor-named library paths.** `pipeline/search.py::_detect_artifact_type` walked `path.parts` of the absolute path when classifying artifacts as `paper` vs `insights` for ranking. A library configured under a `papers/` or `sites/` ancestor would mis-label every artifact. Today the score table doesn't weight those types differently, so the user-visible effect is bounded to the `artifact_type` field, but the bug is the same class as the `read_concept` issue and would become a ranking-skew bug if `_TYPE_BOOST` is extended. Fix: classify against the library-relative path. Regression test pins the behavior.

### Docs

- **ROADMAP package-layout annotations.** `# 0.8 — local-file ingest` / `# 0.8 — local-file routing` corrected to `# 0.9` to match the milestone description (the entry was moved from 0.8 to 0.9 in an earlier edit but the inline `#` comments were missed).

No public API breaks. Existing 0.8.0.2 regression tests still pass; three new tests across the touched layers.

## 0.8.0.2 - 2026-05-16

Security + correctness hardening over 0.8.0/0.8.0.1. Four bugs fixed from a post-release scan:

### Security

- **`read_concept` path-bypass (medium).** The concept/entity restriction in the MCP `read_concept` tool did a substring check on the *unnormalized* input path, so an input like `topics/tkg/concepts/../secret.md` passed the guard while resolving to a non-concept file inside `library_dir`. Library-root containment still held (no OS-wide file read), but the tool's narrower contract was bypassable, exposing private corpus files or `.distill/` task artifacts. Fix: check the *resolved* path's directory parts for a `concepts` or `entities` segment, not the raw input string. Regression tests cover `concepts/../secret.md` and `.distill` traversal.

### Correctness

- **Concept slug collisions overwriting playbooks.** `MergedConcept.slug` is intentionally lossy (`"a b"`, `"a/b"`, `"a-b"` all collapse to `"a_b"`), but the writer assumed any existing file at `<slug>.md` belonged to the same concept and overwrote it. Fix: writer reads the existing note's `normalized_name` from frontmatter; if identities differ, suffix-bumps to `<slug>__2.md`. Idempotent self-rewrites still hit the same file. Added `normalized_name` to playbook frontmatter as the authoritative identity field.
- **Order-dependent same-source aggregation.** When extraction produced duplicate mentions for `(source_id, canonical_name)`, the normalize layer's representative selection for `claim_excerpt`, `evidence_type`, `artifact_path`, and `normalized_name` depended on input order — the commutativity property tests didn't catch it because they only compared `source_id` sets and evidence counts. Fix: every selected field now uses an order-independent rule (longest claim, lex-min path, majority-vote kind, etc.); the property tests were strengthened to vary those fields and check the full SourceEvidence set.
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
