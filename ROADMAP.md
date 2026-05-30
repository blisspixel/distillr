# Roadmap

High-level direction. Shipped work lives in [`docs/CHANGELOG.md`](docs/CHANGELOG.md). The full, area-by-area backlog (un-trimmed, with priority breakdowns) lives in [`docs/roadmap.md`](docs/roadmap.md).

## Current shape

Distill is a source-to-intelligence platform covering three source types:

- **YouTube** — channels, topic searches, videos, Shorts
- **Websites** — vendor sites, research hubs, curated URL sets
- **arXiv papers** — phrase-matched search, full-PDF extraction, cross-paper synthesis

`distill discover` is the goal-aware front door across papers, videos, and curated website seed files. The next refinement for docs-heavy research is app-native trusted-site discovery on allowlisted domains, so workflows like "prefer Microsoft docs + Microsoft channels" do not require hand-curated page seeds.

Everything produces plain markdown in a local `library/` directory. An MCP server exposes the corpus to AI assistants and agent systems.

Distillr is designed to be the **persistent structured memory layer** for AI agent workflows. It's the corpus that [Deepr](https://github.com/blisspixel/deepr) experts query for grounded intelligence, that coding agents consult via MCP for domain context, and that humans browse in Obsidian for navigable knowledge. The ingestion pipeline is the input mechanism; the real product is the always-current, always-queryable corpus.

## Competitive landscape (May 2026)

The space exploded after Karpathy's "LLM Wiki" gist (April 2026). Hundreds of local-first Markdown knowledge-base / AI second-brain / agent-memory projects now exist. Most follow the same core loop: raw sources → LLM extract/synthesize → persistent interlinked Markdown vault → optional MCP or RAG layer. Distillr is not alone, but it occupies a specific axis that most competitors do not.

**Closest tools and where they differ:**

| Tool | Stars | Approach | Key difference from distillr |
|------|-------|----------|------------------------------|
| SwarmVault | ~400 | Full LLM Wiki + hybrid RAG (SQLite FTS + embeddings) + desktop app | Adds DB/RAG (breaks pure-Markdown), broader ingestion, GUI-first |
| obsidian-wiki (Ar9av) | ~1,000 | Skill-based framework — symlinks skills into Claude Code/Cursor/etc. | "Install skills into your agent" model, less automated discovery |
| Lacuna-wiki | ~24 | Pure MCP-first — single tool, DuckDB index, agent-driven maintenance | Minimalist MCP surface, uses DuckDB, no standalone CLI pipeline |
| personal-knowledge-base | ~9 | Clip URLs + Claude Code as librarian, D3.js graph viz | Manual feeding only, no goal-aware discovery or cross-source synthesis |

Plus the ecosystem around Obsidian Web Clipper + Defuddle (now does YT transcripts natively) + Claude Code / local LLMs for wiki compilation, and a dozen MCP servers for Markdown vaults.

**Where distillr stands out:**

1. **Goal-aware multi-source discovery.** Most tools assume you feed them URLs or files. Distillr searches YT + arXiv + web, reranks for relevance/complementarity against a research goal, then ingests. This is rare and genuinely useful.
2. **Structured per-item insights + cross-source synthesis.** Not just entity pages or summaries — explicit `_Insights.md` with claims/limitations, plus dedicated `Topic_Synthesis` and `Corpus_Synthesis` files mixing all sources. Most competitors stop at entity extraction + wikilinks.
3. **Strict no-database, pure-Markdown discipline.** Stable slugs, source receipts, YAML provenance, cost tracking, git-friendly. Many others sneak in SQLite or vector stores.
4. **CLI-first + MCP for power users.** Researchers who want reusable corpora that agents can drive without GUI lock-in.

**Strategic implications for the roadmap:**

- Wiki-links + provenance + stable slugs are now table-stakes (every competitor has some form). 0.7 must ship these clean.
- Discovery + structured synthesis remain the clearest differentiators. Protect and deepen them (0.9).
- The "ease of agent integration" gap (Ar9av's setup.sh, Lacuna's single-tool MCP) is real but is a 1.0 polish concern, not a 0.7 concern.
- The traction gap vs. GUI-heavy tools is about marketing/onboarding, not missing features. 1.0's presentation pass addresses this.
- Pure-Markdown / no-DB is a defensible niche for serious researchers. Don't compromise it.

**Why not "just make it an MCP skill"?** Distillr already *is* an MCP server (8 tools, 12 resources, 4 prompts since 0.5). But a thin MCP wrapper or agent skill would be useless for what distillr actually does — long-running batch ingestion, persistent corpus maintenance, and compounding knowledge across sessions are exactly what interactive agents (Claude Code, Cursor, Windsurf) are terrible at. The architecture is separation of concerns: distillr is the dedicated memory layer; agents query it via MCP when they need grounded knowledge. It's "and," not "or."

## Path to 1.0

The goal of 1.0 is a stable, MCP-first research tool that an external agent can drive without surprises and that a human can run as a daily-driver knowledge system. Milestones are ordered by dependency, not by calendar — each one unblocks the next. Four themes run through every version:

- **MCP-first.** Every workflow has a clean tool surface for agents, not just a CLI for humans. CLI commands are thin wrappers over the same library calls the MCP server uses.
- **Effective-context-aware.** Cloud models in 2026 have 1M+ context windows — a 100K paper fits whole. Chunking is not a universal concern; it is a local-model concern. The system should be adaptive: send content whole when the provider's window allows it, chunk intelligently when it does not (local models with 8K-32K windows). The 2025-2026 context-engineering literature (lost-in-the-middle, ACE-style playbooks, just-in-time retrieval) informs the design, but the implementation targets where it actually matters.
- **Local-first all the way down.** "Local Markdown corpus" is meaningless if every analysis call goes to a paid cloud API. When ingestion is basically free, you use it more — more sources, more frequent refreshes, richer corpus. Local doesn't mean lower quality; it means the economics don't punish thoroughness. If a workload can't meet the quality bar locally, it stays on cloud. Tested on RTX 4090 (Windows) and M1 Mac; should work on any Ollama/LM Studio compatible hardware.
- **Built to last.** Module-size caps, dependency-direction enforcement (import-linter), ruff/Pyright/coverage gates, and structured logging are established as conventions in 0.3 and apply to every later milestone. 0.8.3 hardens the supporting toolchain so these conventions are reproducibly *enforced* rather than aspirational — a committed `uv.lock` plus `uv sync --frozen` ends dependency float (the typer 0.26 upgrade that silently turned a green `main` red is the cautionary case), Dependabot surfaces upgrades as reviewable PRs that run CI before merge, import-linter and pip-audit move into CI, and coverage switches to a branch-metric ratchet. So 1.0 lands at the quality bar without a backfill scramble.

### Milestones at a glance

Previously shipped: **0.1 through 0.8.4** (initial release, internal foundations, MCP-first surface, local inference, living wiki, synthesis-quality patch, concept playbook, frontmatter-field rename, playbook recovery surface, reproducible toolchain, agent-discoverable library). Per-release detail lives in [`docs/CHANGELOG.md`](docs/CHANGELOG.md).

In flight and ahead:

- **0.8.2 Playbook recovery surface** (shipped 2026-05-29) — `distill concepts log/diff/rollback` (topic-first positional, e.g. `distill concepts diff <topic> <slug> [ts_a] [ts_b]`) over the `.history/` snapshots 0.8 already writes, plus MCP `concept_history` / `concept_diff`. Extraction moved to `distill concepts build <topic>` so `concepts` became a command group. See [`docs/CHANGELOG.md`](docs/CHANGELOG.md).
- **0.8.3 Reproducible toolchain and engineering baseline** (shipped) — make the build harness deterministic and self-enforcing before more feature surface lands on top of it. Full migration to `uv` (committed `uv.lock`, `uv sync --frozen` in CI, `uv_build` backend), Dependabot, Python 3.12–3.14 support matrix, import-linter and pip-audit promoted into CI, branch-coverage ratchet, `pre-commit` made identical to CI, SBOM + PEP 740 provenance attestations on release. No business logic; "the harness gets stricter, the code meets it at 1.0." Motivated directly by the 0.8.2 release where an unpinned `typer` floated to 0.26 and broke CI on green code.
- **0.8.4 Agent-discoverable library** (shipped) — auto-generated `CLAUDE.md` orientation files in every topic directory (and at the library root) so when an agent (Claude Code, Cursor, any tool that auto-loads `CLAUDE.md`) `cd`s into a topic, it gets immediate orientation without needing the MCP server. Regenerated on every refresh off the synthesis writers; `distill claude-md --all` backfills. Tiny patch; turns each topic into a self-describing directory.
- **0.9 Discovery loop, synthesis depth, and local-file ingest** — preview-as-default, cliff detection, `--rigor`, synthesis register styles (PhD/exec/pop/landscape) with an anti-AI-slop register guard, gap-driven discovery (the existing `research_gaps` signal feeds auto-generated discover queries), two-pass synthesis with a structured claim intermediate (the same append-only-JSONL pattern 0.8 used for mentions, applied to claims), `distill ingest <path>` for local PDFs / markdown / clipped articles.
- **0.9.1 Source breadth and audio capability** — five-adapter pass to close the most common "I want to add this to my corpus" gaps. X (already in via the 0.9.0 validation run), podcasts (RSS to .mp3 to Whisper), GitHub repos (README and structured issues/discussions subset), generic audio/video files via `distill ingest <path-to-.mp3-or-.mp4>`, and Substack/newsletter posts (RSS-driven site ingest). Each follows a documented adapter contract; further sources defer to the post-1.0 plugin system.
- **0.9.2 Self-maintaining audit** — upgrade the existing console-only `distill health` into `distill audit <topic>`: one bundled run (link-check, stale syntheses, contested concepts, coverage gaps) that emits a single human-readable report artifact plus an action menu (apply link/style fixes, draft missing notes, ingest gap-filling sources). The demoable packaging win that turns scattered quality signals into one self-maintaining surface.
- **0.10 Operational polish + run-time verify** — scheduled refresh (now also schedules `distill audit`), semantic dedup, artifact-level stale-detection, budget guardrails. Plus a new run-time verify hook on every analysis emit (the Agent SDK's `gather context -> act -> verify` loop, applied to distillr's writes), the `distill ask` output->input loop (query the corpus, write a provenance-stamped answer, optionally re-ingest it, gated on the verify hook), and a `find_insights_summary` MCP tool sized for sub-agent delegation.
- **1.0 Stability commitment + quality bar** — versioned CLI / MCP / library / frontmatter contracts, test coverage, Pyright strict, blocking lint/security CI, golden-corpus eval gate (now also covering concept extraction outputs from 0.8), performance baseline, presentation pass, and a documented prompt-revision cadence (contracts are stable; prompts are versioned and revised on a schedule).

Detail for each in-flight milestone follows. The "[intentionally not in scope](#intentionally-not-in-scope)" section at the bottom is the deliberate exclusions list.

### 0.8.2 — Playbook recovery surface (shipped 2026-05-29)

0.8 shipped `.history/<slug>/<iso-timestamp>.md` snapshots on every overwrite, but nothing read them. That was snapshot-without-recovery — half a feature. This patch added the read-and-restore surface. As built (a topic is required to locate a note, so every verb is topic-first positional, consistent with the rest of the CLI):

- **`distill concepts diff <topic> <slug> [ts_a] [ts_b]`** — diff a note across versions. No timestamps: most recent snapshot vs the live note; one: that snapshot vs live; two: snapshot vs snapshot. Frontmatter surfaces as a structured diff (which evidence rows joined/left, polarity flips, how each interval bound shifted, contested/scalar changes); the body diffs as text. Answers "why did this concept's `helpful_evidence` widen on the last refresh?"
- **`distill concepts rollback <topic> <slug> <timestamp>`** — atomically restore a prior version from `.history/`. The current version is snapshot into `.history/` first (so rollback is also reversible), the chosen snapshot becomes the live note, and the `concepts.jsonl` / `entities.jsonl` rollup row is rebuilt from the restored note's frontmatter. `--yes` skips the confirmation prompt.
- **`distill concepts log <topic> <slug>`** — list snapshots with timestamps and a one-line summary of what changed at each step (sources added/removed, interval shifts, contested flips). The audit trail that 0.8's `mentions.jsonl` gives at the input layer, mirrored at the output layer.
- MCP companion tools: `concept_history(topic, slug)`, `concept_diff(topic, slug, ts_a, ts_b)`.
- **Interface change:** extraction moved from `distill concepts <topic>` to **`distill concepts build <topic>`** so `concepts` could become a command group hosting the recovery verbs. A Click group can't also carry a positional `topic` argument (it would swallow the subcommand name), so `build` is the explicit extraction verb. Pre-1.0, documented in the changelog.

As built: recovery logic is pure functions in `distill/concepts/recovery.py` (filesystem IO only, injected `now_iso`); rollback **reconstructs the rollup row from the snapshot's frontmatter rather than re-running the merge** (the append-only `mentions.jsonl` would otherwise reproduce the current state, not the requested snapshot). Tested in `tests/unit/concepts/test_recovery.py` plus CLI and MCP coverage.

Why this version: separated from 0.8.0 because the playbook PR shipped the storage and stopped at the storage. The read surface needed its own design and tests (diff formatting, atomic-rollback semantics, MCP shape) and shouldn't have blocked the merge logic landing. Small and tightly scoped: pure presentation + filesystem moves over data 0.8 already produces.

### 0.8.3 — Reproducible toolchain and engineering baseline

*Shipped 2026-05-30.* The 0.8.2 release shipped clean code and still broke CI: an unpinned `typer>=0.9.0` floated to typer 0.26, which now vendors its own `click`, so `typer.Exit` stopped being `click.exceptions.Exit` and five exit-path tests plus a filesystem-timing flake went red on `main`. Nothing in the codebase changed; the *environment* changed underneath it. Distillr had no lockfile, so every CI run re-resolved the whole dependency tree against the latest compatible release of everything. That is the gap this release closed.

This was a deliberately **no-business-logic** release. The principle is "the harness gets stricter; the code meets it at 1.0." It hardened the toolchain and moved already-written-but-unenforced contracts into the blocking path, so the deeper code-level rigor scheduled for 1.0 (full Pyright-strict, Pydantic-strict boundaries) lands on a foundation that is already reproducible instead of being bolted on at the end. It ships before the 0.8.4 feature work and 0.9 onward deliberately: every later milestone then builds and tests deterministically from day one.

- **`uv` as the project toolchain.** Migrated from pip + setuptools to [`uv`](https://docs.astral.sh/uv/): a committed `uv.lock` for deterministic resolution, `build-backend = "uv_build"`, and `[dependency-groups]` dev tooling replacing the `[project.optional-dependencies].dev` extra. CI installs with `uv sync --frozen` so a run can never silently pick up a new transitive release; `publish.yml` builds with `uv build` and keeps its existing tag-ancestry / version-match / CI-success gates unchanged. The editable-install workflow the repo depends on is preserved (`uv sync` / `uv run`).
- **Dependabot** (`.github/dependabot.yml`): weekly, grouped updates — patch/minor batched, majors flagged for explicit review. Every bump opens a PR that runs the full CI matrix against the updated lock *before* merge. This is the exact control that would have caught typer 0.26 as a reviewable red PR instead of a red `main`.
- **Python 3.12–3.14 support matrix.** Raised the floor from 3.10 (EOL October 2026) to `requires-python = ">=3.12"`, updated classifiers, and run CI on `[3.12, 3.13, 3.14]`; ruff and Pyright target `py312`/`3.12`. Deliberately *not* the 3.14-only baseline some standards guides push — distillr is a published library, and a `>=3.14` floor would break installs for essentially every current downstream consumer while buying nothing (free-threading is irrelevant to an IO-bound LLM/file tool). Test against the newest, support a wide range. See [Engineering standards: adopted, adapted, declined](#engineering-standards-adopted-adapted-declined).
- **Enforce the contracts that already exist.** `import-linter` (the dependency-direction contracts already defined in `pyproject.toml`) and `pip-audit` got their own blocking CI lanes — the layering contracts were configured but never checked, and a "Built to last" pillar that does not run is decoration. Promoted `xfail_strict = true` and `--strict-markers` in the pytest config so a silently-passing xfail can never hide a regression.
- **Branch coverage on a ratchet.** Switched `[tool.coverage.run]` to `branch = true`, set `--cov-fail-under` to the measured branch baseline (~80%, floor 79), and ratchet it up-only toward the 1.0 target of 95. Branch coverage is stricter than the old line metric, so this is a real (and honest) reset of the number, climbed deliberately rather than asserted.
- **`pre-commit` identical to CI.** The lint/type/security/test hooks run through `uv run --frozen`, so they use the exact locked tool versions CI runs (Pyright and import-linter added; full pytest on the pre-push stage). A clean `pre-commit run --all-files` means a clean CI run.
- **Supply chain: SBOM + provenance.** A CycloneDX SBOM ships as a build artifact, and PyPI publishing emits PEP 740 build-provenance attestations over the existing OIDC trusted-publishing channel (no stored credentials), so the chain from a reviewed `main` commit to the installed wheel is verifiable.

*Deferred to 1.0 (deliberately out of 0.8.3 scope):* completing Pyright-strict across every package, adding Pydantic-strict "parse, don't validate" boundaries, and the verification-depth layer (Design by Contract, mutation testing, stateful + fault-injection tests). Those touch business logic and ride the golden-corpus eval gate, so they belong with the 1.0 quality push, not this toolchain release.

As shipped: the migration was verified green across the full 3.12 / 3.13 / 3.14 matrix (1633 tests each), with the `uv_build` wheel confirmed to bundle the `distill/web` templates and static assets. Two `(str, Enum)` enums became `StrEnum` and one generic moved to PEP 695 syntax as the `py312` target surfaced them — behavior-identical, verified by the suite.

### 0.8.4 — Agent-discoverable library

*Shipped 2026-05-30.* Distillr is positioned as the persistent memory layer for AI agent workflows. The MCP server makes the corpus queryable for agents that speak MCP, but a large and growing fraction of real agent traffic (Claude Code, Cursor, Codex CLI, generic coding agents) auto-loads `CLAUDE.md` files from the working directory as their default context-discovery mechanism. An agent that `cd`s into `library/topics/microsoft-fabric/` used to see only the artifact tree -- it had to enumerate files to figure out what the topic contained. This release removes that friction for free.

- **Per-topic `CLAUDE.md`** -- regenerated on every topic refresh from the topic's existing artifacts. Contents:
  - One-line topic summary (the lede of the topic synthesis, with generic section headers skipped)
  - Source counts (papers / videos / pages) and last-refresh timestamp
  - A wikilink to the existing `<topic>_Topic_Synthesis.md`
  - "Ask me about" -- example queries derived from the corpus's named entities and concepts (entities lead; falls back to a generic prompt when the concept layer is not built)
  - "Querying this corpus over MCP" -- the read-surface tool listing (`find_insights`, `read_insight`, `find_concepts`, `research_gaps`, `concept_history`, `concept_diff`) so the agent knows the structured surface exists alongside the filesystem
- **Per-library `CLAUDE.md` at the library root** -- an index of every topic with one-line summaries and source counts, so an agent dropped at `library/` sees the whole research scope at a glance.
- **No new format** -- `CLAUDE.md` is plain Markdown (no frontmatter), identical to every other artifact in the library; the only thing special is the filename convention agents already honor.

As built: the generator is pure functions in `distill/library/claude_md.py` (foundational layer -- reads artifacts + the `concepts.jsonl` / `entities.jsonl` rollups as raw JSON, no `distill.concepts` import; injected `now_iso` for deterministic tests). Automatic regeneration hangs off the **synthesis writers** (`synthesize_topic` / `synthesize_corpus`), the single convergence point every refresh path hits, best-effort so a failure never fails a synthesis -- rather than fragile per-command insertions. A `distill claude-md [<topic>] [--all]` command backfills or regenerates on demand. No new LLM calls, no new dependencies, no cost. Tested in `tests/unit/library/test_claude_md.py` and `tests/unit/commands/test_claude_md.py`.

Why this version: separated from 0.8.2 because it's a different concern (presentation for an external consumer vs. recovery for distillr's own writes). Mechanical -- pure templating over existing artifacts. Pairs naturally with 0.8.2's recovery work because both make the library more self-describing. The Agent SDK ecosystem just shipped (see the May 2026 Anthropic training material that motivated this milestone), and the friction of "agents can't orient in our directories" only gets worse the longer it waits.

### 0.9.0 — Discovery loop, synthesis depth, and local-file ingest

The preview → approve → ingest workflow becomes the default front door, synthesis gets a structured intermediate that scales beyond a single prompt rewrite, and locally-held documents become first-class corpus sources.

**Discovery loop UX.**

- Preview-as-primary-flow UX: probe the candidate pool, detect the rerank-score cliff, present "top N excellent / top M including good / everything ≥ threshold" sizing options with per-option spend, then a single typed approval. Default behavior on a fresh topic.
- Rerank determinism: cached previewed shortlists (commit-by-ID) so the real ingest replays the exact set the user approved.
- Real cost estimator that reads candidate metadata before the run (arXiv abstract length + page count; yt-dlp duration; site content-length) and calibrates against historical `cost_log.jsonl`.
- `--rigor strict|balanced|loose` knob across discover/papers/latest. Audit and document the prompt divergence between commands.
- Trusted-site discovery and clearer source identity in preview: enumerate real page candidates from allowlisted docs domains (TOCs, sitemaps, landing pages) and show page-level titles/URL context instead of only collection labels.
- **Gap-driven discovery.** Today `discover` is goal-driven: it starts from a user-written goal and fans out. The `research_gaps(topic)` MCP tool (shipped in 0.8) already computes the inverse signal — *what the corpus is thin on* (single-source coverage, too few channels, missing corpus synthesis) plus `next_actions`. Wire that signal forward: let an existing corpus's gap findings auto-generate the discover queries that fill them ("12 sources on synthesis depth, zero on error propagation — preview candidates?"). This is the corpus-gap-driven complement to goal-driven discovery, and it is the first half of the self-maintaining loop that 0.9.2's audit completes. Surface it both as a `--from-gaps` mode on `discover` and as the "ingest these" branch of 0.9.2's action menu.

**Synthesis depth.**

- **Two-pass synthesis with a structured intermediate.** Replace single-pass synthesis with: (1) claim-extraction pass over each per-source insight emitting structured rows into a per-topic `claims.jsonl`; (2) synthesis pass over the claim set that clusters, finds contradictions, and writes the narrative with explicit per-claim citations. The 0.7.2 prompt rewrite raised the quality contract but is still single-pass; the structured intermediate is what makes that contract reliably enforceable. Architecturally this is the same append-only-JSONL + pure-Python-merge pattern 0.8 used for `mentions.jsonl` — the playbook layer validated that the LLM-produces-rows / Python-merges-rows split works in production. Reusing that pattern means concepts can attach evidence to specific claim IDs (instead of whole insight files) once both layers exist.

  *Claim schema*, grounded in the argument-mining / scientific-claim-extraction literature: `claim_id, source_id, claim_text, rhetorical_role, subject, predicate, object, dataset, metric, evidence_type`. The `rhetorical_role` field (`background | method | result | limitation | conclusion`) is a precursor segmentation that both shipped systems treat as load-bearing — claims about methods compose differently than claims about results, and skipping the role makes cross-paper clustering on the synthesis side noisier than it needs to be. The `subject/predicate/object` triple is optional but recommended where the claim has a clean Agent-Action-Object structure (drawn from SciEvent's argument-role design); free-form `claim_text` stays as the fallback for narrative claims that don't decompose cleanly.

  *Granularity is not fixed in the schema.* Clause-level extraction works on dense biomedical-style text; sentence- or span-level works on narrative domains. The extraction prompt should let the LLM choose granularity per claim and the merge layer should tolerate both, because forcing one granularity globally is the documented failure mode in both reference implementations.

  *Error propagation from segmentation must be designed for, not hoped away.* Imperfect role tagging upstream feeds wrong clusters downstream. Mitigation: emit a `role_confidence` field on every claim, surface low-confidence claims in synthesis output instead of silently dropping them, and let `--rigor strict` mode require minimum confidence thresholds.

  *Fitness caching for cross-claim scoring.* Both downstream uses of `claims.jsonl` (synthesis clustering and 0.8 concept attachment) will re-score the same claims many times. The orchestrator should cache per-claim LLM judgments by `(claim_id, evaluator_id)` so re-runs amortize cost; this is the same caching pattern referenced metamorphic-testing implementations use to make 240+ test evaluations tractable.
- Synthesis register styles: `--style exec | pop | landscape | disagreements-only` selects emphasis, but every style honors the PhD-level contract shipped in 0.7.2 (cross-paper claims, comparison matrix, named disagreements, shared blind spots).
- **Anti-AI-slop register guard.** `prompts/shared.py` today carries `ANTI_HALLUCINATION_RULES`, `PROVENANCE_RULES`, and a one-line `FORMATTING_RULES` (no em-dashes). That covers *what is true* but not *how it reads* — a distinct concern for the human-read outputs (briefings, reports, synthesis register styles above). Add a `REGISTER_RULES` constant grounded in the Wikipedia "signs of AI writing" list (no filler superlatives, no "delve / it's worth noting / in conclusion" scaffolding, consistent UK/US spelling, no hedge-stacking) and thread it into the synthesis/report/brief prompts. Anti-hallucination keeps the corpus *correct*; this keeps the prose *publishable*. Low effort, no new dependency — a prompt-layer constant plus its wiring.

**Local-file ingest.**

- `distill ingest <path>` for local PDFs, markdown, and clipped articles. Routes through the same analysis pipeline as network ingestion: extract text, run the paper/site analysis prompt, emit `_Insights.md` with full provenance. Closes the gap where the playbook layer only updates from network ingestion. Supports `--topic` to attach to an existing topic, falls back to inferring from file metadata.

Why this version: most of these need 0.3's telemetry to estimate cost honestly and 0.5's MCP surface to expose the same flow to agents. Shipping earlier means re-doing it later.

### 0.9.1 — Source breadth and audio capability

The three-source baseline (YouTube, websites, arXiv) was calibrated to "sources with public APIs and existing transcript layers." A validation run against two X posts revealed two simultaneous gaps: X itself was unsupported, and any source with audio but no native captions (X-native video, podcasts, conference talks, Loom, Vimeo) had no transcription path. Both shipped during the 0.9 validation work — they're now the foundation a focused breadth pass builds on.

**What 0.9 left ready (do not re-design in 0.9.1):**

- `distill ingest <url>` thin dispatcher (routes by host to the right adapter; falls back to existing `distill site` / `distill latest` / `distill paper` for unknown hosts). Mirror of the local-file dispatcher 0.9 introduces for paths.
- X (Twitter) adapter via the public `cdn.syndication.twimg.com` embed endpoint — legitimate publisher path, not anti-bot evasion. Emits `Tweet.md` + `Transcript.txt` (when video attached) + `Insights.md` with standard frontmatter.
- Whisper transcription layer (`distill/ingestors/transcribe.py`) with **local-first provider routing**: `faster-whisper` on CUDA or CPU is the default, then a cloud ladder of xAI Grok STT (~$0.10/hr, reuses the existing `XAI_API_KEY`) before OpenAI Whisper-1 (~$0.36/hr) as the final fallback. Each cloud tier is skipped when its key is absent. Per-source `vocabulary_hint` derived from the source's own metadata (tweet text, author handle, paper title, page H1) biases proper-noun spelling (Whisper's `initial_prompt`, Grok STT's `keyterm`) — closes the "Claude Code → QuadCode" mistranscription class.
- `distill doctor` Transcription section: surfaces faster-whisper version, CUDA device count + supported compute types, cached Whisper models, and the routing line ("local-first → cloud fallback" vs. cloud-only vs. unavailable) so provider surprises are visible before a run.

**What 0.9.1 adds (the five-adapter set):**

- **Podcasts** — RSS feed ingestion, episode `.mp3` download via stdlib, Whisper transcription, standard analysis prompt tuned for interview/conversation shape. Closes the largest single content surface for primary practitioner audio. Reuses the transcribe.py provider routing wholesale.
- **GitHub repos** — README + structured subset of issues/discussions/releases, via the public REST API (no auth required at low rate, `GITHUB_TOKEN` lifts limits). Critical because for any OSS tool, the repo itself is the primary source — not the marketing page. Emits `Repo.md` + `Insights.md`.
- **Generic audio/video files** — `distill ingest <path-to-.mp3-or-.m4a-or-.mp4>` (or `.wav`, `.opus`) routed through the Whisper layer + a "raw media" analysis prompt that expects no native structure. Drops out almost free from the 0.9 local-file dispatcher + the Whisper layer; covers conference talks distributed as files, downloaded Loom recordings, voice memos, interview MP3s.
- **Substack / newsletter posts** — RSS-driven site ingest with the existing site scraper plus a small adapter for Substack's predictable per-post HTML structure (header, byline, body, footnotes). Most of the work is RSS feed enumeration and the per-post structural extraction; the analysis prompt is the existing site-page prompt.
- **X (already shipped in 0.9 validation)** — listed here for completeness; 0.9.1 hardens with: tests, MCP `find_insights`-style read tool, optional thread expansion (fetch parent + reply chain), and consolidated cost/run tracking through the standard `CostTracker` / `RunSummary` plumbing.

**Adapter contract (enforced by reviewer checklist, not lint):**

Every new adapter must implement these five behaviors so it composes with the rest of the system:

1. **Capture as a deterministic function of public input** — given the same URL or path, the captured artifact bytes are reproducible (modulo upstream changes). No login walls, no captcha defeat, no scraping that breaks if the site adds anti-bot. The X adapter's syndication-endpoint approach is the reference shape.
2. **Emit conventional artifacts** — at minimum a raw artifact (`Tweet.md` / `Episode.md` / `Repo.md` / `Page.md` / `Paper.md`) and an `_Insights.md`, both via `write_markdown_artifact` with `base_frontmatter` + `ProvenanceFields`. No new directory layouts or filename schemes — file under `library/topics/<topic>/<source>/<identity>/`.
3. **Pass source metadata to downstream model calls** — Whisper transcription gets a `vocabulary_hint` derived from the source's own text; analysis prompts get author/title/date in their context. The pattern that fixed proper-noun mistranscription for tweets generalizes: the source knows what's in it.
4. **Cost-track through `CostTracker`** — every LLM and transcription call records to the run tracker with a meaningful `call_type`. No off-ledger spend.
5. **MCP tool parity** — every CLI ingest verb has a matching MCP tool that takes the same arguments and produces the same artifacts. Agents and humans see the same affordance.

**Calibration debt — the real risk of "more sources" and how this scope bounds it:**

The roadmap excludes additional cloud LLM providers (see "[intentionally not in scope](#intentionally-not-in-scope)") precisely because each provider is calibration debt — prompts that work well on one regress on another. The same logic applies to sources: a paper-style analysis prompt under-extracts on a podcast (different structure, different signal density, different listener stance). 0.9.1 caps the breadth pass at five adapters with the contract above so the 1.0 golden-corpus eval gate stays tractable. Further sources — LinkedIn, Bluesky, Mastodon, HackerNews, Reddit, Discord exports, Slack archives, slide decks — defer to the post-1.0 plugin system the roadmap already gestures at. The cap is deliberate; if a community contribution wants to add a sixth adapter, the contract above is the gate, not the version number.

Why this version: the breadth pass needs 0.9's `distill ingest` dispatcher to exist as a real entry point, and 0.10's stale-detection + budget guardrails would mis-fire if applied to half-built adapters. Slotting between 0.9 and 0.10 lets each source land with its routing affordance and its budget plumbing both already in place. The Whisper layer + X adapter shipped in 0.9 are the cheap part; the four remaining adapters are the disciplined-execution part.

### 0.9.2 — Self-maintaining audit

The Karpathy "LLM Wiki" pattern that defines this space (see the competitive landscape above) leans on a once-a-month *health check*: a single skill that audits the whole knowledge base, reports contradictions and gaps and stale entries, and offers an action menu to fix them. Distillr already has every ingredient, but they are scattered and none of them produces the one-report-with-actions surface that makes the pattern compelling and demoable:

- `distill health` (shipped) walks topics for stale syntheses (>90d), thin transcripts/insights, and contested concepts — but it is **console-only**: no artifact, no action menu.
- `distill doctor --links` (shipped) runs the broken-backlink / orphaned-reference check — but **separately**, not as part of the audit.
- `research_gaps(topic)` (shipped, MCP) computes coverage gaps + `next_actions` — but is **MCP-only** and not wired into `health`.

0.9.2 composes these into one surface. No new analysis capability; this is a packaging milestone, and the roadmap is explicit that the gap vs GUI-heavy competitors is "marketing/onboarding, not missing features" (see competitive landscape). A single clean audit is exactly the kind of legible, screenshot-able artifact that closes that gap.

- **`distill audit <topic|all>`** — one run that bundles the three checks above plus artifact-level stale-detection (the `prompt_id` / `model_version` floor that 0.10 formalizes, read here when present). Supersedes the console-only `health` output; `health` becomes an alias or the fast/no-report path.
- **One report artifact** — write the audit to `<topic>_Audit.md` (standard frontmatter + provenance) instead of only printing it, so the result is itself a corpus artifact an agent or human can read later. This mirrors the video's "the health check lands a report in outputs" mechanic.
- **Phase-2 action menu** — after the report, offer the concrete follow-ups: apply link/style fixes, draft stubs for suggested-but-missing concept notes, and (the gap-filling branch) hand the `research_gaps` `next_actions` to gap-driven `discover` from 0.9.0 so "you're thin on X" becomes "preview candidates for X." Non-interactive (`--report-only`) for scheduled runs; interactive for hands-on review. Mirrors the video's two-phase "report, then choose what to action."

Why this version: it depends on 0.9.0's gap-driven discovery for the action menu's "ingest these" branch, and it reads 0.10's stale floor when present but does not block on it. It deliberately precedes the 0.10 output->input loop, because an audit surface you trust is the prerequisite for safely feeding generated answers back into the corpus — you want the contradiction/provenance check in place *before* you start re-ingesting your own outputs.

### 0.10.0 — Operational polish + run-time verify

The "leave it running" version. Hands-off operation for a daily-driver research system, plus the run-time verification gate that closes the agent-loop pattern Anthropic's Agent SDK material formalizes.

**Operational polish.**

- Scheduled refresh via cron / Task Scheduler; goal-file refresh hook for `distill watch`. The same scheduler also runs 0.9.2's `distill audit --report-only` on a cadence (the video's "monthly health check" automation), so corpus drift is caught without manual prompting and the audit report lands as a dated artifact.
- Semantic dedup across videos, pages, and papers (artifact-preserving — source-origin attribution stays in the synthesis layer).
- Stale-detection and auto-reanalysis triggers when prompts or models change materially. **Artifact-level, not blanket.** Each artifact's frontmatter already records `prompt_id` and `model_version` (since 0.7); stale-detection inverts that index and re-analyzes only the artifacts on the critical path of the changed component. Blanket re-runs on every prompt bump don't scale once the corpus passes a few hundred artifacts.
- Cost anomaly detection and budget guardrails per topic and workflow.
- Live per-item progress plus resume-friendly failure handling for long mixed-source runs, so transcript-rate limits or slow site ingestion are visible without manual filesystem inspection.

**Run-time verify hook.**

Anthropic's Agent SDK formalizes the agent loop as `gather context -> take action -> verify`. Distillr today does gather (discover) and act (analyze + synthesize) but has no run-time verify gate — if an analysis prompt hallucinates a paper title, a vendor positioning claim, or a benchmark number that wasn't in the source text, nothing catches it before the artifact is committed to the library. The golden-corpus eval gate in 1.0 is the *test-time* version of this; this milestone adds the *write-time* version:

- **Inline claim-grounding check on every analysis emit** — for every `_Insights.md` write, the orchestrator post-processes the structured output: extract each load-bearing claim (numbers, named products, dates, named people), grep the source artifact for verbatim or near-verbatim support, flag any unsupported claim in a small `_verify.json` sidecar with the same identity stem as the insights file.
- **Configurable severity** — `--verify warn` (default; surface to console, write anyway), `--verify strict` (refuse to write if any unsupported load-bearing claim is found; user can override per-run with `--verify off`). Mirrors the Agent SDK's "hooks" pattern — deterministic verification layered on top of stochastic model output.
- **Verifier is a small local-model pass when possible** — the verifier doesn't have to share the analysis model's biases. A cheap separate-process check (small local LLM, or even a regex-based first cut for the easy cases like "this section claims a number; does the number appear in the source") catches the regressions a self-judge prompt would miss.

**Output->input loop (`distill ask`).**

This is the mechanic the Karpathy "LLM Wiki" pattern is built around and the one half of the loop distillr does not yet have: you ask the corpus a question, you like the answer, and the answer *becomes corpus* so the next question starts from a richer base. Today distillr is excellent at `input -> corpus` (capture, analyze, synthesize) but every output (`report`, `research-brief`, `synthesize`) is a **terminal artifact** — nothing re-ingests it, and there is no lightweight query verb at all. The compounding "day 1 basic, day 100 an asset" behavior the pattern promises depends entirely on closing this loop.

- **`distill ask "<question>" --topic <t>`** — query the corpus (reuse the `find_insights` retrieval path), answer grounded only in the topic's artifacts, and write a provenance-stamped answer to an answers layer (`library/topics/<t>/answers/<slug>_Answer.md`, standard frontmatter, `[[backlinks]]` to every cited source). MCP parity: an `ask` tool with the same arguments.
- **Optional re-ingest** — `--save` (or a prompt) promotes a liked answer into the corpus so synthesis and future answers can build on it. This is the compounding step.
- **Gated on the verify hook — this is non-negotiable.** The video names the exact failure mode this risks: "the AI writes something slightly wrong, you save it back, and the next answer quietly builds on a mistake." Re-ingest therefore runs the run-time verify hook above on the answer first; an answer with an unsupported load-bearing claim is refused (or flagged and quarantined under `--verify warn`) rather than silently folded in. The verify hook is *why* this loop is safe in distillr and unsafe in the unguarded folder-and-CLAUDE.md version. It is also why this lands in 0.10 (after the hook) and after 0.9.2 (so an audit surface already exists to catch any contradiction that does slip through).

**Sub-agent-friendly MCP surface.**

Today's `find_insights(topic, query)` returns full artifact bodies. For a 50-paper corpus, an agent that queries this blows past most context windows. The Agent SDK's sub-agent pattern (delegate "do X over Y, here's bounded context, return result") needs a token-bounded query primitive:

- **`find_insights_summary(topic, query, max_tokens=4000)`** — same query, returns a synthesis sized to fit a sub-agent's context. Implementation: existing `find_insights` plus a one-shot LLM compression pass over the matching slice with the query as the focus. Cached by `(topic, query, max_tokens, corpus_revision)` so repeated sub-agent calls don't repay the compression cost.
- **`list_topic_summary(topic)`** — paragraph-length topic overview pulled from the topic synthesis frontmatter, used when a sub-agent is choosing which topic to query.

Why this version: stale-detection, semantic dedup, and run-time verify all need stable artifact identity and provenance, which 0.7 + 0.8 secure. The sub-agent MCP tools depend on the 0.9 two-pass synthesis claim intermediate (so the summary pass has structured inputs rather than re-extracting from prose). 0.10 is where these compound on top of everything underneath.

### 1.0.0 — Stability commitment + quality bar

Public-API freeze plus a documented quality posture. The shape of distillr stops changing under users and agents, and the codebase ships at the polish bar a 1.0 release deserves.

**Stability.**

- CLI flags, MCP tool/resource/prompt schemas, library directory layout, and frontmatter fields are versioned. Breaking changes require a major-version bump and a documented migration.
- Documented backwards-compatibility policy for the `library/` directory (a 0.5 corpus opens cleanly in 1.0).
- Performance baseline published — wall-clock and token spend for a reference 20-paper run, a reference 50-video catch-up, a reference site-batch. CI flags regressions beyond a documented budget.

**Stability is about contracts, not about prompts. Prompt-revision cadence is separate.**

The 1.0 stability commitment freezes the *external contracts* (CLI flags, MCP schemas, library layout, frontmatter fields). It deliberately does **not** freeze the *prompts* that drive analysis, synthesis, concept extraction, and verification. Anthropic's Agent SDK material is explicit on the principle: "expect to rewrite agent code every six months" as model capabilities change. Distillr's prompts are no different — what works on grok-4.3 doesn't necessarily work on grok-4.7, and over-fitting prompts to last quarter's model is its own kind of brittleness.

- **Prompts are versioned (`prompt_id`), not frozen.** Every artifact's frontmatter already records the `prompt_id` and `model_version` that produced it (since 0.7). 1.0 formalizes that this is the *only* required stability for prompts — the actual prompt body can revise without a major-version bump as long as the contract its output satisfies (frontmatter shape, claimed sections, golden eval gate pass) holds.
- **Documented revision cadence.** Prompts get a scheduled revision pass roughly every two model generations (so several times a year at current pace), and an unscheduled revision when the golden eval gate flags a regression that's load-bearing.
- **Stale-detection is the user-facing consequence.** 0.10's stale-detection re-analyzes artifacts whose `prompt_id` or `model_version` falls behind the current floor. The cadence above is what defines the floor.
- **Distinction matters because users build on contracts, not prompts.** A downstream MCP consumer or Obsidian dataview depends on `synthesis_scope: "single-paper"` meaning the same thing it always meant — that's contract stability. It doesn't depend on the analysis prompt being literally identical to the 0.7 version — that's an implementation detail that *should* evolve as models improve.

**Quality bar (CI-enforced, not aspirational).**

- **Branch test coverage ≥95%**, ratcheted. 0.8.3 turns on branch coverage and starts the up-only climb from the measured baseline; 1.0 is where the gate reaches 95% across the surface. Branch (not line) is the metric, and the target is flat rather than tiered — the cost is real on presentation-heavy code (CLI rendering, web routes, dashboards), and that trade-off is accepted deliberately rather than hidden behind a per-package carve-out. Coverage is reported on every PR and can go up, not down.
- **Integration tests run by default** with mock LLMs so contributors run the full pipeline on every push without burning real spend.
- **Pyright strict** across the full surface, blocking — the completion of the per-package ratchet 0.8.3 begins (`distill/llm/` is already strict-blocking today). No `# type: ignore` without an inline reason comment.
- **Parse, don't validate — strict domain types at every boundary.** Every external input (MCP tool arguments, frontmatter parsing, local-file/adapter ingest, LLM structured outputs) is *parsed once* at the system boundary into a rich domain type (a Pydantic v2 model with `strict=True, extra='forbid'`, a `NewType`, or a frozen dataclass), not re-validated ad hoc deeper in. Core logic never receives raw primitives that could be invalid — illegal states are made unrepresentable, so malformed input fails at the boundary with a precise error instead of propagating. Reinforces the verifiable-corpus thesis: the corpus is only as trustworthy as the parsing on what enters it.
- **Ruff** zero-warning under the project config, blocking. Cyclomatic complexity (`C901`) capped; `# noqa` requires an inline justification. Security rules (`S` / bandit) consolidated into the single ruff pass where practical.
- **Bandit + pip-audit** blocking in CI (both promoted in 0.8.3). Dependencies pinned via the committed `uv.lock`; CI installs with `uv sync --frozen` so the tested environment is the locked environment, a CycloneDX SBOM ships with each release, and PyPI publishing emits PEP 740 build-provenance attestations over the existing OIDC trusted-publishing channel (no stored credentials) so the chain from a reviewed `main` commit to the installed wheel is cryptographically verifiable.
- **import-linter** dependency-direction contracts blocking in CI (promoted in 0.8.3), so the layered architecture in [Target package layout](#target-package-layout-10) is enforced, not just documented.
- **Python 3.12–3.14 support matrix**, every version green on every PR. `requires-python = ">=3.12"`; the floor moves forward as old versions reach EOL, the ceiling tracks the current stable release.
- **No silent error swallowing.** Every `except` either re-raises or logs-then-raises. Audited and lint-rule-enforced where ruff supports it.
- **Golden corpus eval gate.** A frozen ~20-paper reference corpus ships with hand-checked golden insights (claims, methods, limits sections) plus hand-checked concept-playbook output (which concepts cross threshold, which polarities, which intervals). CI runs the full analysis + concepts pipeline against it with mock LLM responses fixed for reproducibility, and gates on per-section agreement with the golden output. Catches the regression class that the rest of the quality bar misses — prompt drift, model swaps, and silent degradation of section extraction or concept polarity assignment — none of which show up in coverage, type, or lint gates.
- **Metamorphic robustness pass on the eval gate.** Grounded in the LLM-metamorphic-testing literature (METAL framework + search-based MR selection): each fixture insight ships with semantically-equivalent rewrites generated from a fixed perturbation set, and the eval gate asserts that concept extraction over the rewrites produces the same set of `normalized_name` records (allowing `claim_excerpt` wording to differ).

  *Concrete perturbation set:* `SynonymReplacement`, `AddRandomWord`, `L33TChanging` (character-level), `SentenceReordering`, `ProseToBullets` (structural). Five canonical MR templates from the METAL framework — `Equivalence`, `Discrepancy`, `SetEquivalence`, `Distance`, `SetDistance` — define the satisfaction rule for each perturbation type. `Equivalence` is the relevant one for extraction: the perturbed input should produce the same canonical concept set.

  *Acceptance threshold:* the perturbed insight passes a `PerturbationQuality` check before it's used as an eval probe — cosine similarity ≥ 0.6 via Universal Sentence Encoder embeddings (the operating point both reference implementations converged on). Variants that drop below 0.6 are discarded as not actually equivalent. This prevents the eval gate from testing surface tokenization while pretending to test semantic stability.

  *Suite size:* 3–4 perturbed variants per fixture insight, with combinatorial composition (k ≤ 2) for breadth. The reference search-based papers show 240 single-level MRs is the right benchmark order of magnitude; for distillr's narrower extraction task, ~30 variants across ~10 fixture insights is a sufficient initial gate, scaling up post-1.0.

  *Cost amortization is non-optional.* Fitness evaluation (running concept extraction against each variant) caches by `(variant_hash, model_id)` so re-runs of the eval gate during model swaps or prompt revisions don't repay the full token cost. Both reference implementations call this out as the engineering pattern that makes the approach tractable; a metamorphic eval gate without caching would 4-10x CI time per release.

  *What this catches:* the regression class the mock-LLM golden-corpus check can't see. Mock responses fix what the LLM *would* say on a fixed input; metamorphic tests fix what the LLM *should* say across equivalent inputs. Property tests cover the merge layer's mathematical invariants. The three together close the loop the 1.0 stability claim depends on.
- **Pre-commit hooks identical to CI checks** — no contributor surprises between local and remote.

**Verification depth (where it matters, not everywhere).**

The gates above prove *coverage* and *types*. These prove the tests and the code are actually correct under adversarial conditions. They are scoped to the layers where correctness is load-bearing — the deterministic pure-Python core (`concepts/` merge + normalize + recovery, `library/` slugs + frontmatter + links, evidence-interval arithmetic) and the external-service boundaries — not blanket across presentation code, because that is where the cost/value trade-off actually lands.

- **Design by Contract on the deterministic core.** Encode the merge/normalize/recovery invariants as executable pre/postconditions and class invariants (via the `deal` library, which also generates Hypothesis tests directly from the contracts) — for example: merge is idempotent and order-independent, a rollback's rebuilt rollup row round-trips the restored frontmatter, evidence intervals never invert. Contracts run in dev and CI and can be optimized out (`python -O`) where overhead matters. Applied to the same pure-Python layer the property tests already target, so the two compound rather than overlap.
- **Mutation testing on the core packages.** A periodic `mutmut` (or equivalent) pass injects artificial regressions into `concepts/`, `library/`, and `llm/retry` and asserts the test suite catches them — proving the suite's *efficacy*, not just its coverage percentage. Scoped to the core (mutation testing is too slow to run blanket on 14.5k lines) and run on a cadence, not every PR. Complements the golden-corpus and metamorphic gates: those catch LLM-output drift, this catches dead tests.
- **Stateful property testing of the playbook lifecycle.** A Hypothesis state machine models the concept layer's real lifecycle — append mentions to `mentions.jsonl`, merge, write notes, snapshot to `.history/`, roll back, re-merge — and asserts the invariants hold across arbitrary operation orderings. This is the class of bug (ordering, accumulation, rollback-after-merge) that single-shot example tests miss.
- **Fault-injection at the external boundaries.** Deterministic tests that inject malformed LLM JSON, truncated/empty transcripts, network timeouts, and yt-dlp failures, asserting the pipeline degrades cleanly (resume-friendly, no half-written artifacts) and that the "no silent error swallowing" rule actually holds under turbulence — verified, not assumed. distillr's concurrency is asyncio IO, so the discipline that matters is async-safety (no blocking calls in async paths, correct cancellation), not the shared-memory thread-safety a free-threaded service would need.

**Polish.**

- Repo presentation pass: README screenshots/gifs (terminal dashboard, sample report, web UI, library in Obsidian), GitHub repo description and topics, contributor onboarding doc that takes a new contributor from clone to first PR in under 30 minutes.
- All public APIs documented (concise docstrings on the public surface; longer where the rationale isn't obvious from naming).
- `docs/CONTRIBUTING.md` covers the full quality posture above so contributors know the bar before they open a PR.

Why this version: 1.0 is a stability *and* quality claim. It's the version external systems can build on without expecting churn, and the version a new contributor can land a clean PR in without a long onboarding tail. Competitively, this is the version that closes the traction gap — the biggest risk is getting out-marketed on ease-of-agent-integration by GUI-heavy tools (SwarmVault, obsidian-wiki). The presentation pass, onboarding docs, and stable contracts are what convert "technically superior" into "actually adopted."

## Looking beyond 1.0

Not committed. Notes on directions worth thinking about once 1.0 stability is in place.

- **Semantic alias resolution over `mentions.jsonl`.** 0.8's normalize layer canonicalizes mention names mechanically (case-folding, plural stripping, punctuation cleanup). That handles the easy cases. The hard cases — "rotational embeddings" / "rotation embedding" / "phase rotation" being three names for the same concept; "DeepMind" / "Google DeepMind" being one org; or, more painfully, two papers in the same field using entirely disjoint vocabularies ("SciBERT" + "BiLSTM-CRF" vs "SciEvent" + "Agent-Action-Object triples") — are out of reach of regex.

  *Architecture, grounded in the cross-document event coreference literature:* two paradigms are validated and complementary. (a) **Symbolic compression**: assign each mention a structured identifier from its arguments — borrowing X-AMR's PropBank-style roleset + ARG-0 (Agent) / ARG-1 (Patient) / ARG-Loc / ARG-Time decomposition — then cluster via connected components on identifier match. Linear in corpus size; falls back to mechanical canonicalization when arguments are missing. (b) **Semantic compression**: generate a short LLM elaboration per mention (1-2 sentences expanding what the mention refers to), then run small-model pairwise scoring + clustering on the elaborations. The 2406.02148 / 2404.08656 papers found these two paradigms have complementary failure modes — symbolic misses paraphrase, semantic misses precise argument structure — and that a staged pipeline (symbolic bucketing first, LLM elaboration for ambiguous clusters) outperforms either alone. That staging is the recommended target architecture.

  *Why now matters for the schedule:* the corpus consensus from the entity-resolution literature is that direct LLM-as-classifier ("just ask GPT-4 if these are the same concept") consistently underperforms hybrid pipelines. Distillr's general no-LLM-for-verification stance survives intact under this finding — LLMs go in the *elaboration* helper role, not the *decision* role. Connected-components clustering is the final-arbiter step and stays pure Python.

  *Evaluation yardstick:* the ECB+ corpus metric suite is the established baseline — MUC, B³, CEAF_e, and CoNLL F1 are what the field reports. distillr's golden eval corpus should produce these scores against hand-coded clusters so improvement is measurable.

  *Surface shape:* an offline `distill concepts resolve-aliases [<topic>]` command that proposes merges (candidate pairs above a confidence threshold) and asks for confirmation, not an automatic pass that silently reshapes the corpus. Confirmed aliases append to a per-topic `aliases.yml` that the normalize layer reads at canonicalization time. The right pattern for a knowledge layer the user inspects.

  *Validated as a real need, not speculative.* In a controlled internal validation run on two papers from the same task family ("scientific claim extraction"), the 0.8 concept layer surfaced 24 distinct mentions and zero cross-paper concepts at threshold=2 — every term was unique across the pair despite topical overlap. Mechanical canonicalization cannot bridge that vocabulary gap. The literature's two-paradigm answer is well-validated; what's left is the engineering integration, scoped to post-1.0 so it doesn't widen the 1.0 surface.

- **Caching as a load-bearing pattern across eval/synthesis/resolution layers.** All three of the research areas above (claim extraction, metamorphic robustness, entity resolution) call out caching of LLM-derived intermediates as the engineering pattern that makes their approaches affordable at scale. distillr already has this implicitly in `mentions.jsonl` (cache extraction outputs), but the 0.9 `claims.jsonl` layer and the 1.0 metamorphic eval gate both need it as a deliberate design element, not a bolt-on. Worth a shared utility in `distill/llm/cache.py` rather than three independent implementations.

## Target package layout (1.0)

The shape distillr is being refactored toward. 0.3 stands up the top-level subpackages and the conventions; later milestones populate them. `import-linter` and the module-size cap from 0.3 enforce this layout in CI — it is not aspirational.

```text
distill/
├── __init__.py
├── _bootstrap.py            # early-import side effects (UTF-8 stdio, etc.)
├── cli.py                   # Typer app wiring; ≤100 lines, no business logic
├── config.py                # Pydantic Settings, SecretStr API keys, model policy
│
├── commands/                # one Typer command group per file
│   ├── _helpers.py          # cross-command UI helpers (formerly cli_shared.py)
│   ├── discover.py
│   ├── latest.py
│   ├── papers.py
│   ├── site.py
│   ├── synthesize.py
│   ├── research_brief.py
│   ├── report.py
│   ├── watch.py
│   ├── topics.py
│   ├── costs.py
│   ├── doctor.py
│   ├── serve.py
│   ├── dashboard.py
│   └── ingest.py            # 0.9 — local-file ingest
│
├── ingestors/               # capture layer — one source per subpackage
│   ├── youtube/             # search, download, transcript
│   ├── sites/               # scraper, attachments, browser
│   ├── papers/              # arxiv, pdf
│   └── local/               # 0.9 — local-file routing
│
├── llm/                     # provider abstraction + routing
│   ├── router.py            # workload-tag → provider+model dispatch
│   ├── cost.py              # pricing tables
│   ├── telemetry.py         # per-prompt token logging
│   └── providers/
│       ├── grok.py
│       ├── gemini.py
│       ├── ollama.py        # 0.6
│       └── lm_studio.py     # 0.6
│
├── pipeline/                # analysis / synthesis / report orchestration
│   ├── analysis/
│   │   ├── paper.py
│   │   ├── video.py
│   │   ├── site.py
│   │   ├── chunking.py      # 0.6 — adaptive section-aware (local models only)
│   │   └── rerank.py        # 0.6 — per-category chunk rerank (local models only)
│   ├── synthesis/
│   │   ├── topic.py
│   │   ├── corpus.py
│   │   └── register.py      # 0.9 — PhD / exec / pop styles
│   ├── report/              # 4-phase Deep Research pipeline
│   │   ├── phase1_research.py
│   │   ├── phase2_facts.py
│   │   ├── phase3_writing.py
│   │   ├── phase4_qa.py
│   │   └── compaction.py    # 0.6 — between-phase summaries
│   ├── discovery.py         # goal-aware cross-source fanout + rerank
│   └── ranking.py           # generic LLM rerank
│
├── prompts/                 # all prompt templates centralized
│   ├── analysis.py
│   ├── synthesis.py
│   ├── report.py
│   ├── discover.py
│   └── shared.py            # anti-hallucination + provenance rules
│
├── library/                 # filesystem corpus layer
│   ├── paths.py             # canonical artifact path resolution
│   ├── state.py             # library.json, watch_state.json
│   ├── slugs.py             # 0.7 — stable slug discipline
│   ├── frontmatter.py       # 0.7 — YAML read/write
│   └── links.py             # 0.7 — wiki-style cross-links + link-check
│
├── concepts/                # 0.8 — ACE-style concept/entity playbook layer
│   ├── extract.py
│   ├── merge.py
│   ├── notes.py
│   └── contradictions.py
│
├── mcp/                     # MCP server (split from today's mcp_server.py)
│   ├── server.py            # transport, registration, lifecycle
│   ├── tools/               # mirrors commands/ shape
│   │   ├── find.py          # 0.5 — find_insights / read_insight (JIT)
│   │   ├── discover.py
│   │   ├── topics.py
│   │   ├── watch.py
│   │   ├── gaps.py
│   │   └── costs.py
│   ├── resources.py
│   └── prompts.py           # MCP-protocol prompts (distinct from distill/prompts/)
│
├── notify/                  # 0.5 — outbound watch-alert channels
│   ├── email.py
│   ├── slack.py
│   └── webhook.py
│
└── web/                     # local web dashboard (already a subpackage)
    ├── server.py
    └── routes/
```

**Dependency direction** (enforced by `import-linter`):

```text
commands/  →  pipeline/, library/, mcp/, web/
mcp/       →  pipeline/, library/, commands/
pipeline/  →  ingestors/, llm/, library/, prompts/, concepts/
ingestors/ →  llm/, library/, prompts/
concepts/  →  library/, llm/, prompts/
web/       →  library/, pipeline/
notify/    →  library/

library/   →  (foundational; no internal distill.* imports)
llm/       →  (foundational; no internal distill.* imports)
prompts/   →  (foundational; no internal distill.* imports)
config.py  →  (foundational; no internal distill.* imports)
```

The four foundational layers (`library/`, `llm/`, `prompts/`, `config.py`) are the bottom of the import graph. Everything else builds on them; they don't import each other or anything above them. A new contributor can find any feature in two clicks: pick a layer by what it does, pick a file by which source/phase/command.

**Test layout mirrors source.**

```text
tests/
├── conftest.py
├── unit/
│   ├── commands/
│   ├── ingestors/{youtube,sites,papers,local}/
│   ├── llm/{providers/}
│   ├── pipeline/{analysis,synthesis,report}/
│   ├── library/
│   ├── concepts/
│   └── mcp/
├── integration/             # full-pipeline tests with mock LLMs
│   ├── test_paper_pipeline.py
│   ├── test_discover_cross_source.py
│   └── test_report_pipeline.py
└── fixtures/
    ├── papers/
    ├── transcripts/
    └── mock_llm.py
```

Once 0.3 lands, the canonical version of this layout — with rationale per subpackage — moves into [`docs/architecture.md`](docs/architecture.md). This roadmap section is the snapshot that 0.3 builds toward.

## Engineering standards: adopted, adapted, declined

The 0.8.3 and 1.0 quality posture above was pressure-tested against two general "elite Python standards" briefs — a baseline one (uv-everywhere, NASA Power-of-10, 3.14-only, 95% coverage, full OpenTelemetry) and a more advanced one (formal verification, Design by Contract, supply-chain provenance, pure-Python-first, free-threading). A standards memo is a useful forcing function, but applying one wholesale to a published library is how a project acquires cargo-cult gates that fit someone else's system and not its own. This section records the judgment calls so a future contributor (or a future revisit of the same brief) does not silently re-import the parts distillr deliberately rejected. It is the same discipline as "Intentionally not in scope" below, applied to engineering process rather than product surface.

**Adopted** (genuinely new, high-value, in scope at 0.8.3 / 1.0):

- `uv` as the sole toolchain, a committed `uv.lock`, and `uv sync --frozen` in CI — reproducible environments, and the direct fix for the dependency-float break that motivated 0.8.3.
- Dependabot weekly grouped updates; `import-linter` and `pip-audit` promoted into blocking CI; `pre-commit` made identical to CI; `xfail_strict`; branch coverage; SBOM on release.
- The full Pyright-strict ratchet and "parse, don't validate" strict domain types at every boundary (1.0).
- **PEP 740 build-provenance attestations** over the existing OIDC trusted-publishing channel (secretless), so the path from a reviewed `main` commit to the installed wheel is cryptographically verifiable. The cheap, high-value slice of the advanced brief's Sigstore/SLSA section.
- **Verification depth on the deterministic core** (1.0): Design by Contract (`deal`) on the merge/normalize/recovery invariants, mutation testing of the core packages, Hypothesis stateful testing of the playbook lifecycle, and fault-injection at the external-service boundaries. "Formally contracted where it matters" — scoped to the pure-Python core, not blanket.

**Adapted** (taken in spirit, tailored to this project):

- **Python 3.12 floor + 3.13/3.14 matrix, not 3.14-only.** distillr is a library other people install; the baseline optimizes for "good citizen to downstream consumers," not for access to runtime features (free-threading) an IO-bound tool will never exercise.
- **Pyright, not Astral `ty`.** `ty` is promising but too immature in mid-2026 to gate CI on; the strictness target is identical, the checker stays the one already wired in.
- **Structured-logging discipline, not full OpenTelemetry.** No-secrets, level-correct, file-capturable logging is the bar. Distributed tracing and OTel semantic conventions are service-grade observability for a single-user local CLI — overhead without a consumer.
- **`ruff` security rules consolidated, not the full unstable preview ruleset.** Fold bandit's `S` checks into the one ruff pass where practical; do not turn on preview rules wholesale, which churn between releases and would fight the reproducibility goal.
- **Static analysis at the floor (3.12), tested at the ceiling (3.14).** ruff and Pyright target 3.12 so a 3.13/3.14-only syntax or API can't slip past review and break a supported user; the test matrix still runs the newest. The advanced brief's "3.14 as the static-analysis baseline" would invert this and silently raise the real floor.
- **Design by Contract scoped to the deterministic core, not blanket.** `deal` contracts pay off on the pure-functional merge/normalize/recovery/interval layer where invariants are crisp; smeared across IO/orchestration/presentation code they become noise. "Where it matters" is doing the work in that phrase.
- **structlog with consistent semantic fields, not full OpenTelemetry tracing.** Adopt the field-naming discipline (stable keys, no secrets) without standing up a tracing backend a single-user local CLI has no consumer for.

**Declined** (wrong for this project):

- **3.14-only baseline** — breaks installs for the entire current downstream base; covered above.
- **Pure-Python-first / ban C extensions.** distillr's *own* code is pure-Python, but its dependency tree legitimately rests on compiled cores — `pydantic-core` (Rust, and the foundation of the strict-boundary parsing the brief itself wants), plus `playwright`, `uvloop`, `httptools`, `watchfiles`, `websockets`. Banning them is neither possible nor desirable. distillr's "purity" discipline is **no database, pure-Markdown corpus** — a product-architecture commitment — not "no compiled dependencies," which would be cargo-cult and would forbid the very tools that make the rest of the bar achievable.
- **Free-threaded (3.14t) build + shared-memory concurrency rules.** distillr is IO-bound (network, LLM, disk); free-threading buys nothing, and key deps (`pydantic-core`, `playwright`) are not cp314t-ready. Its concurrency is asyncio, so the relevant discipline is async-safety, not the message-passing/no-shared-mutable-state rules a free-threaded compute service needs.
- **Container / image scanning (trivy), full SLSA L3 generators** — distillr ships as a PyPI wheel, not an image. `pip-audit` + SBOM + PEP 740 attestations cover the actual supply-chain surface; the container-and-SLSA-L3 apparatus is for deployed services.
- **Auto `uv lock --upgrade` in CI.** Dependabot's reviewable upgrade PRs (each running full CI against the new lock before merge) are strictly safer than CI silently re-resolving — the un-reviewed auto-upgrade is the same dependency-float failure mode 0.8.3 exists to kill, just relocated.
- **Power-of-10 hard gates that do not fit a Markdown pipeline** — two-asserts-per-function, fixed loop bounds, and no-recursion are flight-software rules for hard-real-time control loops. The in-character subset is already convention here: module-size caps, `C901` complexity caps, no silent error swallowing, narrowest-scope declarations. The rest would be ceremony, not safety.
- **Copier / portfolio template scaffolding** — a cross-project concern (how *many* repos share standards), not a property of distillr's own codebase. Out of scope for this roadmap.

## Intentionally not in scope

A roadmap is also an opinion about what *not* to build. These are deliberate exclusions, not gaps. Several are informed by the competitive landscape (see above) — competitors that make different choices validate that these are real trade-offs, not oversights.

- **No graph-view UI inside distill.** Obsidian / Logseq / Dendron already do this well; reimplementing duplicates effort without adding value. The Obsidian-native milestone (0.7) is the answer. (SwarmVault builds its own graph view; we get it free from the ecosystem.)
- **No proprietary editor, mobile app, or cloud-hosted SaaS.** The whole point is plain-text Markdown with no lock-in. A hosted version would create exactly the dependency the project exists to avoid.
- **No general-purpose RAG / vector-store / SQLite index.** distillr is opinionated about the corpus shape and the analysis pipeline. Embeddings are an implementation detail (used selectively for dedup, possibly inside `find_insights`), not a primary surface. Users who want a generic RAG toolkit have LangChain and LlamaIndex. (SwarmVault and Lacuna-wiki add SQLite/DuckDB; we deliberately avoid this — pure-Markdown + git-friendly is the defensible niche for serious researchers.)
- **No multi-user / auth / collaboration layer.** Single-user local tool. Shared corpora are a `git` problem, not a distillr problem.
- **No additional cloud LLM providers by default.** Each provider is calibration debt — prompts that work well on one model regress on another. Users can wire OpenAI / Anthropic / Mistral / etc. through the 0.3 router, but distillr won't ship default model policies for them. Local providers are the exception because they carry the local-first promise. (Transcription providers are not subject to this exclusion: speech-to-text carries no analysis-prompt calibration debt, so the 0.9.1 ladder ships a cloud tier — xAI Grok STT, reusing the already-required `XAI_API_KEY` — beneath the local-first default.)
- **No plugin / extension system before 1.0.** Premature abstraction. The right plugin boundaries become obvious only after the internal architecture from 0.3–0.5 has carried real workloads. Revisit post-1.0.
- **No real-time collaboration or sync service.** Markdown + git is the answer. distillr won't compete with Obsidian Sync, Logseq Sync, or Syncthing.
- **No "install skills into your agent" model.** obsidian-wiki (Ar9av) takes the approach of symlinking skill files into Claude Code / Cursor / etc. Distillr's architecture is separation of concerns: distillr is the dedicated memory layer, agents query it via MCP. A thin skill wrapper would be useless for long-running batch ingestion and persistent corpus maintenance — exactly what interactive agents are terrible at.
- **No anti-bot / paywall / login-walled scraping.** Playwright handles legitimate access; defeating hostile defenses is whack-a-mole that pulls focus from the analysis pipeline and creates legal/ethical surface area.
- **No "cheap mode" that compromises fidelity.** The product premise is "as good as we can possibly make it" regardless of whether inference runs locally or in the cloud. Local models exist to make the corpus *always current* at zero marginal cost, not to produce worse outputs faster. Cost reduction happens through local inference, compaction, and JIT context — never through cheaper prompts that produce worse outputs. A local insight must be good enough that synthesis and expert queries can trust it without qualification.

These exclusions are load-bearing, not permanent. They get revisited if the constraint that drives them changes.

## Full backlog

The area-by-area backlog (stay-current, dashboard, papers, cross-source intelligence, context engineering, discovery loop, etc.) lives in [`docs/roadmap.md`](docs/roadmap.md). Items there will be tagged with the milestone above where they land in a follow-up pass.

Design principles drawn from the context-engineering literature are summarized in [`docs/architecture.md#context-engineering-principles`](docs/architecture.md#context-engineering-principles).
