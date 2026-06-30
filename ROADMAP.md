# Roadmap

High-level direction. Shipped work lives in [`docs/CHANGELOG.md`](docs/CHANGELOG.md). The full, area-by-area backlog (un-trimmed, with priority breakdowns) lives in [`docs/roadmap.md`](docs/roadmap.md).

> ## No brittle junk. Read [`docs/design/agentic-balance.md`](docs/design/agentic-balance.md) before adding ANY rule, gate, score, or agentic surface.
>
> This is the single most repeated and most damaging mistake in this codebase: reaching for a deterministic keyword / regex / length / cosine / threshold heuristic where a **semantic judgment** belongs. It *looks* rigorous, it measures surface form, and as a **gate** it actively makes the product worse - it blocks good outputs (punishes paraphrase) and passes bad ones (rewards keyword-stuffing). We keep walking back into this trap. Stop.
>
> **The test (charter, verbatim):** a decision is a **Rule** only when it is *structural or has ground truth* - does the JSON parse? is the URL public? is the cited span in the source? is the score over the threshold? Anything that judges **"is this good / faithful / on-topic / substantive / robust / a rumor / which lens?"** is **semantic** and goes to a **model** (cloud OR local - use what the user has), with Python only aggregating and thresholding the model's *per-criterion* verdicts.
>
> **The dual trap - do not over-correct.** "No brittle junk" does **not** mean "rip out every deterministic check." A structural / ground-truth gate is *correct* and stays: number-in-source, JSON-parses, URL-public, fixtures-in-sync, scorer-discrimination on data we control. The brittle thing is specifically a deterministic **scorer faking a semantic *quality* judgment** (keyword coverage, length-as-depth, cosine-as-robustness, a bootstrap over 3 points). Reflexively purging the legitimate structural checks is the same mistake pointed the other way. The question is never "is this deterministic?" - it is "is this *structural*, or am I faking a *judgment*?"
>
> **Hard rules for this roadmap - a proposed item is rejected if it:**
> - **gates** anything (CI, a write, a migration, a release) on a deterministic quality/faithfulness/robustness *score*. Those gates are model-judged; the deterministic part is at most a cheap discrimination tripwire and an advisory diagnostic, never the bar.
> - cites a framework/metric (METAL, cosine-similarity, BLEU/ROUGE, a kappa floor, a magic constant) as the justification instead of `distill eval` showing it catches a real regression.
> - dresses a tiny/meaningless sample in statistics (a bootstrap CI over 3 fixtures) to look rigorous.
> - replaces a brittle rule with a model used in the *wrong mode* - a fine-grained absolute "quality score" is just a new brittle proxy wearing a model's clothing (eval-gate #3 case study).
> - when no model is available, returns a keyword score *dressed as* a ranking instead of an honest, labeled order.
>
> Keep this doc and its remediation ledger [`docs/design/model-judgment-vs-brittle-fallbacks.md`](docs/design/model-judgment-vs-brittle-fallbacks.md) current as you go. If you are about to write a scorer, stop and ask: is this structural, or am I faking a judgment?

## Current shape

Distill is a source-to-intelligence platform covering eight source types, all on the same capture -> analyze -> verify -> synthesize -> audit path:

- **YouTube** (stable) - channels, topic searches, videos, Shorts, with caption retry and local-first Whisper fallback
- **Websites** (stable) - vendor sites, research hubs, curated URL sets, attachment-aware crawls
- **arXiv papers** (stable) - query expansion, LLM rerank, full-PDF extraction, DOI metadata when arXiv supplies it, cross-paper synthesis, BibTeX/RIS export
- **X posts** (beta) - `distill ingest <tweet-url>` via the public syndication endpoint, with local-first Whisper transcription for native video
- **GitHub repos** (new adapter) - `distill ingest <github-url>` captures repo metadata, README, and releases into structured maturity / when-to-use insights
- **Podcasts** (new adapter) - RSS-first ingestion, publisher transcripts preferred before audio transcription
- **Newsletters / feeds** (new adapter) - full feed bodies when available, routed by substance rather than attached narration
- **Local files and media** (new adapter) - PDF / Markdown / text / HTML documents, plus local audio/video through the transcription ladder

`distill discover` is the goal-aware front door across papers, videos, curated website seed files, and trusted-site page expansion. Docs-heavy workflows can pass repeated `--trusted-site` domains or section URLs so Distill enumerates public same-host candidates from sitemaps, TOC/navigation links, and landing-page links before the goal-aware rerank, instead of requiring every page seed by hand. Selected website candidates ingest exact pages by default, with opt-in bounded shallow crawls for operators who want one section hop. Website preview rows now include exact URL, section label, discovery source, and sitemap freshness date when known. Website batch seed files can mix explicit exact-page and shallow-crawl modes, and `distill site-batch --preview` shows the resolved crawl plan before writes. With global `--json`, that preview emits the same plan as loop-readable rows. MCP `site_batch` honors the same JSON seed modes for relative seed files inside the library root, and `preview=true` returns the plan even in read-only deployments.

Everything produces plain markdown in a local `library/` directory. An MCP server exposes the corpus to AI assistants and agent systems.

Distillr is the **persistent, verifiable research corpus** for AI agent workflows - the production CLI for the pattern Karpathy's ["LLM Wiki" gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) made famous: ingest sources, maintain an interlinked plain-Markdown corpus, let agents query it. It's the corpus that [Deepr](https://github.com/blisspixel/deepr) experts query for grounded intelligence, that coding agents consult via MCP or read directly as files, and that humans browse in Obsidian. The ingestion pipeline is the input mechanism; the real product is the always-current, always-queryable corpus.

We deliberately do **not** position this as a "memory layer." The agent-memory category (mem0, Zep, Letta, Cognee) is conversation-fact extraction - a different job, being commoditized from below by free native memory in Claude/ChatGPT/Gemini, and measured by benchmarks (LoCoMo et al.) that are both contested and irrelevant to a research corpus. Distillr is a research corpus / knowledge substrate; it competes with none of those tools on their turf and should not invite the comparison.

## Competitive landscape (June 2026)

*Refreshed 2026-06-11 from a primary-source research sweep; star counts verified directly against the GitHub API that day. The May 2026 analysis this replaces is in git history.*

**The architecture bet won the argument.** In the nine months to mid-2026, "plain files over RAG" went from contrarian to mainstream-endorsed: Anthropic's [context-engineering guidance](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) recommends just-in-time file retrieval over pre-built semantic indexes (semantic search: "less accurate, more difficult to maintain, and less transparent"), and every Anthropic memory surface - the memory tool, Claude Code auto-memory, managed-agent memory - is Markdown files. Letta, the MemGPT company that defined database-backed agent memory, publicly sunset its server-side memory tools for git-backed file "context repositories" (March 2026). Karpathy's April 2026 gist (~16M views on the announcement post) made the whole pattern famous. The pure-Markdown invariant no longer needs defending; it needs citing.

**But the generic wiki-maintenance niche saturated within weeks of the gist.** The May analysis tracked four small tools; the actual leaders emerged elsewhere:

| Tool | Stars (2026-06-11) | What it is | Relation to distillr |
|------|--------------------|------------|----------------------|
| [kepano/obsidian-skills](https://github.com/kepano/obsidian-skills) | 35.3k | Obsidian CEO's official Agent Skills for Markdown vaults | Validates skills-as-distribution and vault conventions; not an ingestion pipeline |
| [nashsu/llm_wiki](https://github.com/nashsu/llm_wiki) | 11.1k | Desktop LLM-wiki app + web clipper, "instead of traditional RAG", MCP + lint reports | The mass-market wiki maintainer |
| [claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian) | 6.5k | "Self-organizing second brain" conventions for Claude Code + Obsidian | Generic `/ingest`, no source-specific pipelines |
| [obsidian-wiki (Ar9av)](https://github.com/Ar9av/obsidian-wiki) | 1.8k | Skills-based vault agent (35 skills), session auto-capture | The "install skills into your agent" model |
| [SwarmVault](https://github.com/swarmclawai/swarmvault) | 538 | LLM wiki + hybrid SQLite/embeddings, typed graph with per-edge provenance, contradiction detection, installers for 10+ agent harnesses | The trust-features pacesetter, DB-backed |
| [Lacuna-wiki](https://github.com/Labhund/lacuna-wiki) | 32 | MCP-first DuckDB wiki | Stalled (no pushes since April 2026) |

Distillr should not chase that crowd - the vault-maintenance fight is lost to 35k/11k-star incumbents and the storage format is no longer a differentiator (everyone has Markdown now).

**OKF changes the interop story, not the product thesis.** Google Cloud introduced the [Open Knowledge Format](https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing) on 2026-06-12 as a vendor-neutral Markdown + YAML-frontmatter specification for agent-readable knowledge bundles; the [v0.1 spec](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) requires only parseable frontmatter with `type`, conventional `index.md` / `log.md`, Markdown links, and citations. That validates distillr's file-first bet, but it also means "plain Markdown" will become table stakes. The right move is not to rewrite the native corpus around OKF or build a graph viewer; it is to make distillr a high-quality OKF producer and validator so verified research corpora can move into other agent systems without losing receipts, audit state, or provenance.

**Where distillr's ground is uncrowded (verified June 2026):**

1. **The acquisition front-half.** Every tool above starts at "drop in sources you already have." None does goal-aware multi-source *discovery* (searching YouTube + arXiv + web against a research goal, reranking for fit and complementarity, then ingesting with transcript-grade pipelines). Adversarially verified: no mainstream product maintains a self-growing, user-owned, plain-file research corpus across runs. The closest proprietary convergence is NotebookLM - Deep Research reports now flow into persistent notebooks with Gemini-app sync (April 2026) - but it exports only to Google Docs/Sheets, a documented pain point to position against. The window is open but the idea is now famous; clones add pipelines weekly.
2. **Trust is the new quality frontier - and distillr's pipeline was built for it.** The leaders compete on contradiction detection (SwarmVault), lint/orphan reports (llm_wiki), and draft-then-promote review gates (WUPHF). The academic evidence is on distillr's side of the argument: deep-research agents fact-check their own citations at only 39-77% accuracy, degrading as retrieval scales ([arXiv 2605.06635](https://arxiv.org/abs/2605.06635)). Structured per-item insights with receipts, cross-source synthesis that preserves disagreements, the verify hook, and the audit surface are exactly this frontier - and the verification architecture is now settled practice (see the 0.10 milestone).
3. **Source white space.** No open-source tool does structured insight extraction from podcasts (the incumbents - Snipd, Podwise - are closed consumer apps), and repo understanding exists only in closed products (Cognition's DeepWiki, Copilot Spaces); OSS repo tools (Repomix, Gitingest) stop at concatenation. Distillr's per-item insight format applied to those sources is genuinely unoccupied ground.

**Agent legibility is distribution, and it is near-free (promoted out of "1.0 polish"):**

- **AGENTS.md won the cross-vendor baseline** (Linux Foundation / Agentic AI Foundation; supported in Codex, Cursor, Gemini CLI, and 30+ tools) - but Claude Code reads CLAUDE.md, so the corpus emits *both* per topic. `llms.txt` is not the core interface, but once OKF export ships it can become a thin optional pointer to the exported bundle for tools that look there.
- **SKILL.md went vendor-neutral** ([agentskills.io](https://agentskills.io), ~32 tools by March 2026), and the winning vendor pattern is exactly distillr's shape: *a CLI plus one skill teaching the agent to use it*. One canonical SKILL.md is one file, ~100 tokens until invoked - categorically different from the symlink-machinery model this roadmap still rejects.
- **The MCP server stays but slims.** Token-efficiency is now canon: Anthropic measured ~85% schema savings from deferred tool loading and large gains from [code-execution over tool calls](https://www.anthropic.com/engineering/code-execution-with-mcp); GitHub cut agentic-workflow tokens ~62% partly by replacing MCP calls with the `gh` CLI; Claude Code's own best practices call CLI tools "the most context-efficient way to interact with external services." At ~500-1,000 schema tokens per tool, 22 always-loaded tools is the pattern the ecosystem is punishing. Consolidate to a handful of workflow-shaped tools that return **paths into the corpus plus short previews, never full payloads** - the corpus being plain files makes this natural. The server remains the only route to claude.ai web/mobile and hosted agents, so it stays; it becomes a thin window onto the files.
- **Registries don't distribute.** MCP registry usage concentrates in ~10 famous servers (top 10 take ~46% of attention); skills marketplaces have a measured 13.4% critical-flaw rate (Snyk ToxicSkills, Feb 2026). The adoption levers that work: a good `uvx`-runnable CLI, agent-readable docs in the repo, and a self-describing corpus - plus the security story ("your research is local plain files; no third-party server in the loop"), which MCP's 2026 CVE record turned into a real selling point.

**Why not "just make it an MCP skill"?** Distillr already *is* an MCP server (MCP-first since 0.5). But a thin MCP wrapper or agent skill would be useless for what distillr actually does - long-running batch ingestion, persistent corpus maintenance, and compounding knowledge across sessions are exactly what interactive agents (Claude Code, Cursor, Windsurf) are terrible at. The architecture is separation of concerns: distillr is the dedicated research-corpus layer; agents query it via MCP or read it as files. Shipping one canonical SKILL.md that *teaches agents the CLI* is distribution for that architecture, not a replacement of it. It's "and," not "or."

## Path to 1.0

The longer horizon - what 1.0, 2.0, and 3.0 each *promise*, the maybe-later parking lot, and the design-doc ledger - lives in [`docs/design/version-architecture.md`](docs/design/version-architecture.md); this section remains the operational spine to 1.0.

The goal of 1.0 is a stable, MCP-first research tool that an external agent can drive without surprises and that a human can run as a daily-driver knowledge system. Milestones are ordered by dependency, not by calendar - each one unblocks the next. Six themes run through every version:

- **MCP-first.** Every workflow has a clean tool surface for agents, not just a CLI for humans. CLI commands are thin wrappers over the same library calls the MCP server uses.
- **Effective-context-aware.** Cloud models in 2026 have 1M+ context windows - a 100K paper fits whole. Chunking is not a universal concern; it is a local-model concern. The system should be adaptive: send content whole when the provider's window allows it, chunk intelligently when it does not (local models with 8K-32K windows). The 2025-2026 context-engineering literature (lost-in-the-middle, ACE-style playbooks, just-in-time retrieval) informs the design, but the implementation targets where it actually matters.
- **Local-first all the way down.** "Local Markdown corpus" is meaningless if every analysis call goes to a paid cloud API. When ingestion is basically free, you use it more - more sources, more frequent refreshes, richer corpus. Local doesn't mean lower quality; it means the economics don't punish thoroughness. If a workload can't meet the quality bar locally, it stays on cloud. Local execution should work on any Ollama/LM Studio compatible hardware that passes doctor checks and workload eval. The hardware trend bends toward more capable desktop and laptop local inference over time, so the default bias shifts toward local *whenever a workload clears the quality bar* - with `distill eval` (cost x quality over frozen fixtures) as the arbiter of "good enough" rather than vibes - and cloud stays the floor for what local can't yet match (long-context synthesis, web-grounded Deep Research). The router exists precisely so this ratio can move per-workload over time without touching pipeline code.
- **Loop-ready.** The 2026 shift from prompt-running to loop engineering (design the loop once; the work happens unattended and verified) is distillr's natural habitat - but distillr is the *loopable primitive and persistent state layer*, never the loop runner (no scheduler-orchestrator surface; the cron / agent-harness / stewardship layer above owns the loop). The contract every command must meet: safe to run unattended - non-interactive flags (`--yes`, `--report-only`), convergent re-runs (a converged corpus is a clean exit-0 no-op, shipped for `discover`/`papers` in 0.9.27), clean failure exits instead of tracebacks, resumability, and report artifacts rather than console-only output. The review question for any new flag or behavior: *can a recurring loop run this without a human?* The stricter admission test is: recurring work, automated verifier, bounded budget, usable tools, and persisted state. The minimum viable loop is trigger, reusable knowledge, state file, and gate. The metric that matters is cost per accepted change, not attempts or tokens. The verify hook (0.10) is the load-bearing piece - a loop without a verify gate scales slop, not work - which is why it precedes every autonomous-loop behavior on this spine. The deeper question underneath - *where distill is itself a deterministic workflow vs where it lets the model drive* - is settled in [`docs/design/agentic-balance.md`](docs/design/agentic-balance.md): agentic at the leaves (discovery, analysis, synthesis), Python-owned at the decisions (invariant #6), and completion checked against receipts plus faithfulness verdicts instead of a self-declared "done" flag (invariant #8). That charter, grounded in Anthropic's workflow-vs-agent framing, is the guardrail the more-agentic roadmap items (adaptive lenses, goal-driven discovery, the deep-synthesis loop) operate within. Its remediation arm - [`docs/design/model-judgment-vs-brittle-fallbacks.md`](docs/design/model-judgment-vs-brittle-fallbacks.md) - catalogs where deterministic keyword/regex heuristics still impersonate a semantic judgment (notably the discovery reranker's no-model gate and a rumor-keyword skeptical trip-wire) and stages the fix: route judgment to whatever model the user has (cloud *or* local - never assumed), and when there is none, degrade to a labeled recency order rather than fake quality with keyword scoring.
- **More agentic, with explicit rule boundaries.** The direction is more model-driven on open-ended surfaces: discovery query expansion, candidate judgment, analysis lensing, synthesis planning, contradiction interpretation, and future deep-synthesis loops. The rule-owned surfaces stay deterministic: URL and path safety, schema parsing, budget stops, dedup and merge bookkeeping, action ids, approval class, exact command emission, audit rollups, and verifier stop conditions. Every forward item should be readable as one of three shapes: agentic judgment, rule-owned structure, or judgment-then-rule where a model returns per-criterion verdicts and Python aggregates. If a feature judges quality, relevance, faithfulness, or completeness, it must use model judgment. If it gates an irreversible action, it must expose a structural verifier and a testable stop condition.
- **Built to last.** Module-size caps, dependency-direction enforcement (import-linter), ruff/Pyright/coverage gates, and structured logging are established as conventions in 0.3 and apply to every later milestone. 0.8.3 hardens the supporting toolchain so these conventions are reproducibly *enforced* rather than aspirational - a committed `uv.lock` plus `uv sync --frozen` ends dependency float (the typer 0.26 upgrade that silently turned a green `main` red is the cautionary case), dependency upgrades land as manually reviewed PRs that run CI before merge, import-linter and pip-audit move into CI, and coverage switches to a branch-metric ratchet. So 1.0 lands at the quality bar without a backfill scramble.

**Agentic surface map.** The roadmap intentionally moves more work into model judgment, but it does not move irreversible decisions into model self-certification.

| Area | More agentic | Rule-owned boundary |
|---|---|---|
| Discovery | Generate queries, judge source fit, interpret complementarity | Public URL checks, dedup, score-cliff sizing, preview ids, exact ingest commands |
| Analysis and synthesis | Extract insights, choose lens, synthesize conflicts, plan deeper synthesis | Required artifact schema, source receipts, verify sidecars, prompt ids, write refusal |
| Audit and next actions | Interpret findings for a human or external loop when needed | Stable action ids, command strings, approval class, spend estimate, verifier and stop condition |
| Recurring profiles | Adapt source mix and refresh strategy from the goal and recent findings | Profile schema, cost mode, allowlists, no-metered preflight, preview-before-ingest |
| Local and plan-quota routing | Judge whether a route is good enough through `distill eval` | Fail-closed billing rules, explicit provider selection, usage ledger, eval threshold |

**Release rhythm: feature passes interleaved with recurring harden passes.** The milestones below are feature-shaped and dependency-ordered, but they do not ship as one uninterrupted march. Every few feature releases, distillr runs a **bug-hunt + harden pass** - a release that adds no product surface and instead finds and fixes defects (security, SSRF/DoS and resource-exhaustion ceilings, crash-on-malformed-input, supply-chain) and then ratchets the quality gate. The 0.9.20-0.9.23 series is the worked example: an adversarial security review plus a parse-don't-crash sweep over untrusted and corruptible local state, the branch-coverage floor raised up-only, and every GitHub Action pinned to a commit SHA. This is deliberate sequencing, not interruption - hardening the surface a feature just added is cheaper than one end-of-line scramble before 1.0, and each pass feeds the 1.0 quality bar incrementally rather than as a backfill. Every release, feature or harden, clears the same CI gate (ruff, import-linter, bandit + pip-audit, pyright, and the 3.12-3.14 test matrix with its branch-coverage floor).

**Dogfood rhythm: every milestone starts with a distill-built corpus on its own problem domain.** Before designing a milestone, run the goal-aware discover -> preview -> ingest -> synthesis loop on that milestone's literature and let the findings land in the design docs. The worked example: the 0.10 verify hook's design cites a 6-paper claim-verification corpus distill built about itself for ~$0.21 (`library/topics/claim-verification/`), which settled the checker choice, made decomposition non-optional, and picked the eval fixture - and the same run caught a rendering bug and two trust-surface defects no test had. One sub-dollar run per milestone buys design evidence, real-use QA, and a public proof artifact at once; the 0.11 breadth pass starts with a corpus on podcast-ingestion and repo-analysis tooling.

### Milestones at a glance

Shipped: **0.1 through 0.19** (latest release 0.19.2, 2026-06-28). Per-release detail is the changelog's job, not the roadmap's: [`docs/CHANGELOG.md`](docs/CHANGELOG.md). Newest-first headlines:

- **0.19 Recurring research profiles + no-metered-cost routing** - saved profile artifacts (topic + goal + sources + rigor), the `auto|no-metered|paid-ok` cost-mode router with fail-closed refusal, `distill doctor --adapters` preflights, `distill profile run` handoff with resume state, and the route availability/pool primitives. The remaining route-graduation gates are vendor-gated (see Remaining to 1.0). Design: [`docs/design/recurring-profiles-cost-routing.md`](docs/design/recurring-profiles-cost-routing.md), [`docs/design/route-orchestration.md`](docs/design/route-orchestration.md).
- **0.18 Batch-run visibility** - the `_logic.py` monolith fully retired, per-item / per-phase progress with running cost and ETA on the long ingest and report loops, and `-q` / `-v` / `--json` verbosity controls before the CLI contracts freeze.
- **0.17 OKF interop + loop-ready stewardship** - `distill export --what bundle --format okf` and `distill okf validate` (OKF v0.1 bundles projected over the native corpus), plus `distill audit --next-actions --json` as the loop handoff surface. Design: [`docs/design/okf-loop-readiness.md`](docs/design/okf-loop-readiness.md).
- **0.13-0.16 Engineering legibility + CLI-UX** - the entailment tier + verify-on-every-synthesis (0.13), agent-grade `--json` / strict stdout-stderr split (0.14), in-place `distill update` (0.15), the blocking structural golden-corpus eval gate (0.16), and the full `_logic.py` monolith removal. Design: [`docs/design/logic-decomposition.md`](docs/design/logic-decomposition.md).
- **0.12 Compounding corpus** - the `distill ask` loop with strict-by-definition `--save` promotion, revision-cached sub-agent MCP summaries, read-only MCP + per-call spend caps + ingest allowlist, semantic dedup, the prompt-version registry + staleness rollup, and per-item failure isolation. Design: [`docs/design/ask-loop.md`](docs/design/ask-loop.md).
- **0.11 Source breadth + audio** - five adapters (GitHub repos, podcasts RSS-first, generic media, newsletters, X), every one verify-gated, plus YouTube caption-retry with backoff and the Whisper fallback.
- **0.10 Verified corpus** - the write-time claim-grounding hook on every analysis *and* synthesis emit path (`warn|strict|off`), and `distill audit` rolling verification coverage + health + links + gaps into a per-topic report.
- **0.9 Agent-legible corpus** - AGENTS.md beside CLAUDE.md per topic, one canonical SKILL.md, the paths-not-payloads MCP consolidation, the public example corpus, and the "research corpus, not memory layer" positioning refresh.
- **0.1-0.8 Foundations** - the MCP-first surface, local inference, the concept/entity playbook + recovery surface, the reproducible `uv` toolchain + engineering baseline, the discovery loop, two-pass synthesis, local-file ingest, and the X + Whisper adapter; interleaved with the 0.9.20-0.9.23 security/robustness hardening series.

**Remaining to 1.0.** The feature spine is complete through 0.19; the distance left is the quality bar, not new surface. Forward milestones, detail below:

- **1.0 Stability commitment + quality bar** - the real remaining distance: versioned and frozen CLI / MCP / library / frontmatter / OKF / next-action / profile contracts; Pyright-strict and "parse, don't validate" at every boundary (the per-package strict ratchet is well underway - `llm/`, `library/`, `prompts/`, the full `pipeline/` package, and the full `commands/` package are strict-clean; the command strict surface now includes the package marker, root callback, intent commands, `ask`, `audit`, `claude_md`, `okf`, `profile`, `process`, `ingest`, `eval`, `learn`, `maintain`, `init`, `concepts`, `dashboard`, `discover`, `doctor`, `reports`, `reprocess`, `papers`, `topic`, `watch`, `_concept_ingest`, `_discover_options`, `_paper_artifacts`, `_json`, `_discover_sites`, `_discover_flow`, `_discover_ingest`, `_learning`, `_learning_flow`, `_site_batch`, `_site_ingest`, `_helpers`, `_topic_changes`, `view`, `update`, and topic/channel plus topic-watch helper modules with typed public JSON, discover-flow, discover-ingest, adaptive-ingest, learning-flow selected-video, learning query expansion and candidate filtering, reprocess metadata, topic profile parsing, dashboard HTML rendering, watch latest-insight metadata, site-batch, site-ingest, trusted-site discovery, discover command orchestration, eval preflight, learning-preview, learning-ingest, init key-validation, doctor key-validation, local-provider probes, maintain cost-log parsing, status artifacts, migration tuples, dashboard rendering, command intent-loading, site-manifest loading, shared-helper metadata writing, preflight, dispatch, safe rendering, and ranking-strategy seams; the full `mcp/` package is now strict-clean across the server registration surface, optional progress contexts, package marker, prompt definitions, resources, `research_gaps`, `doctor`, JIT `find`, `costs`, `okf`, `topics`, `summaries`, `ask`, `reports`, `synthesize`, `papers`, `watch`, `site_batch`, `concepts`, and `discover` tools, with public config-loading, key-validation, path-resolution, library, tracker, cost-summary, markdown-resource, source-inventory, video-list, and markdown-stripping seams; the shared helper module, topic-change helper, and view command are strict-clean with typed metadata-writing, preflight, dispatch, safe-rendering, diff, trend, watch-alert, and history rows, the doctor command is strict-clean with public key-validation and local-provider probe seams plus a stable importlib metadata alias, the shared required-topic resolver is warning-clean, the adapter-runner timeout boundary normalizes text or bytes output before result construction, the maintain cost, status, migration, and dashboard boundaries are strict-clean, the YouTube yt-dlp boundary is warning-clean, and the library export plus python-docx renderer surfaces are warning-clean; the advisory package-surface Pyright run is at 0 warnings, and the blocking command-package Pyright run reports 0 errors); verification depth on the deterministic core; branch coverage 91 -> >=95%; and the presentation pass. [detail](#100--stability-commitment--quality-bar)
- **Provider breadth + plan-quota compute (committed, post-1.0)** - the eval-gated adapter contract across cloud APIs (xAI, Google, Anthropic and OpenAI in-tree, AWS Bedrock, Microsoft Foundry) and the plan-quota CLI class. This subsumes the 0.19 route-graduation tail, whose open gates are vendor-gated rather than effort-gated: current no-metered support statements, plan-quota auth proof, native schema enforcement where the CLI supports it, and `distill eval` route graduation. [detail](#looking-beyond-10)
- **Beyond 1.0 (exploratory)** - semantic alias resolution over `mentions.jsonl`, provider-aware prompt or context caching research, and shared LLM-intermediate caching as a load-bearing pattern. [detail](#looking-beyond-10)

A harden pass is slotted in whenever the surface a recent feature added warrants it (the 0.9.20-0.9.23 series is the precedent), so the sequence above is the feature spine, not the whole release stream. Detail for each forward milestone follows; shipped releases - and the design rationale behind them - are recorded in [`docs/CHANGELOG.md`](docs/CHANGELOG.md). The "[intentionally not in scope](#intentionally-not-in-scope)" section at the bottom is the deliberate exclusions list.

### Shipped milestone detail -> the changelog

The per-milestone detail for everything shipped (0.1-0.17) used to live here. It has moved to its system of record - per-release notes in [`docs/CHANGELOG.md`](docs/CHANGELOG.md), and design rationale in the design docs ([agentic-balance](docs/design/agentic-balance.md), [model-judgment-vs-brittle-fallbacks](docs/design/model-judgment-vs-brittle-fallbacks.md), [entailment-tier](docs/design/entailment-tier.md), [ask-loop](docs/design/ask-loop.md), [okf-loop-readiness](docs/design/okf-loop-readiness.md), [logic-decomposition](docs/design/logic-decomposition.md)). The roadmap below keeps only forward work. Minor follow-on slices inside shipped milestones (podcast diarization / Parakeet fast path, the repo issues-and-discussions subset, further MCP tool consolidation) are tracked in the [full backlog](docs/roadmap.md).

#### Validation (2026-06-20)

Before collapsing these, every "shipped" claim was re-checked against the code, not against its own annotation:

- **Static** - 28 load-bearing claims across the verify pipeline, the 0.12 compounding surface, the brittle-proxy remediation ledger (P1-P4), the five source adapters, the 0.18/0.19 CLI and loop surface, and the security hardening were each verified against the implementation and its tests. Spot evidence: `run_verify_hook` is wired into every analysis and synthesis emit path; `model_available()` (router-based) has replaced the `config.xai_api_key` gate across the CLI and MCP; `_looks_like_rumor_query` and `infer_lens` are confirmed deleted tree-wide; there is no `eval/stats.py` bootstrap machinery; the dashboard sanitizes through an `nh3` allowlist.
- **Live** - a real grok-4.3 run (`distill papers ... --limit 2`, $0.06) produced per-paper insights, a cross-paper synthesis, and three `_Verify.json` sidecars (schema v2; the synthesis sidecar grounded 15/15 claims against its receipts), proving the capture -> analyze -> verify -> synthesize path works end-to-end, not just in mocked tests.

Nothing in the shipped record failed to validate. The forward milestones below are what is genuinely left.

### 0.18 and 0.19 shipped -> the changelog

0.18 (batch-run visibility) and 0.19 (recurring research profiles + no-metered-cost routing) shipped through 0.19.2. Per the convention above, per-release detail lives in [`docs/CHANGELOG.md`](docs/CHANGELOG.md); the design rationale is in [`docs/design/recurring-profiles-cost-routing.md`](docs/design/recurring-profiles-cost-routing.md), [`docs/design/cli-adapter-runbook.md`](docs/design/cli-adapter-runbook.md), and [`docs/design/route-orchestration.md`](docs/design/route-orchestration.md).

What remains from the 0.19 theme is genuinely forward and sits after 1.0 - it gates on vendor policy and on the read-only adapter prototypes, not on near-term effort:

- **Plan-quota route graduation (vendor-gated).** A plan-quota CLI route (Codex CLI, Claude Code, Grok Build, Gemini CLI, Antigravity) becomes a live no-metered route only once an adapter doctor proves included-plan auth (not an API key), machine-readable output, scratch-only writes, complete usage ledgering, live availability, and `distill eval` quality. The doctor scaffolding, the strict `adapter-workload.v1` / `adapter-native-usage.v1` / `adapter-result.v1` scratch contracts, the capture writers, and the pure graduation decision are all in-tree; the open gates are current official no-metered support statements and installed-session auth proof, which are provider-specific and may change. GitHub Copilot CLI stays a credit-metered candidate under explicit paid policy.
- **Route orchestration strategies.** A strategy layer over several validated routes used together (ensemble best-of-N with a cross-family judge, maker-checker, bounded critic-refine), scored by `distill eval` on cost per accepted change, pool-aware. Buildable and testable against local + mock routes today. Design: [`docs/design/route-orchestration.md`](docs/design/route-orchestration.md).

### Trust hardening implications for the remaining spine

Recent hallucination failure-pattern review reinforces the existing direction:
Distill's advantage is not a better model guess, it is a verified source-to-corpus
workflow that makes unsupported certainty hard to write and easy to audit.

- Citation and source identity are structural truth. Handles, citation keys,
  source ids, exported bibliography rows, and generated answer citations should
  resolve to real local receipts or refuse promotion. Report section numbered
  citations now refuse promotion rather than being stripped when the handle
  cannot resolve.
- Premise truth, faithfulness, source fit, and appropriate uncertainty are
  semantic judgments. They belong in `distill eval` model-judge fixtures and
  write-time verdicts, with Python aggregating explicit per-criterion decisions.
- False-premise questions, no-evidence cases, citation-request traps,
  unsupported-number cases, and route-disagreement cases are now first-class
  `distill eval` ask fixtures. The correct behavior is to correct the premise,
  say the corpus does not support the claim, cite only real source stems, or
  route for operator review.
- Long-context reliability needs evidence-position regression tests, especially
  for local routes and report pipelines where relevant evidence can sit in the
  middle of a receipt.
- Multi-route agreement is only weak support. Disagreement is a strong
  uncertainty signal and should feed review queues, route-pool eviction, or
  low-confidence output labels rather than be averaged away.

### 1.0.0 - Stability commitment + quality bar

Public-API freeze plus a documented quality posture. The shape of distillr stops changing under users and agents, and the codebase ships at the polish bar a 1.0 release deserves.

**Stability.**

- CLI flags, MCP tool/resource/prompt schemas, library directory layout, and frontmatter fields are versioned. Breaking changes require a major-version bump and a documented migration.
- Documented backwards-compatibility policy for the `library/` directory (a 0.5 corpus opens cleanly in 1.0).
- Performance baseline published - wall-clock and token spend for a reference 20-paper run, a reference 50-video catch-up, a reference site-batch. CI flags regressions beyond a documented budget.

**Stability is about contracts, not about prompts. Prompt-revision cadence is separate.**

The 1.0 stability commitment freezes the *external contracts* (CLI flags, MCP schemas, library layout, frontmatter fields). It deliberately does **not** freeze the *prompts* that drive analysis, synthesis, concept extraction, and verification. Agent behavior changes as models change; distillr's prompts are no different. What works on one model version may regress on the next, and over-fitting prompts to the last validated model is its own kind of brittleness.

- **Prompts are versioned (`prompt_id`), not frozen.** Every artifact's frontmatter already records the `prompt_id` and `model_version` that produced it (since 0.7). 1.0 formalizes that this is the *only* required stability for prompts - the actual prompt body can revise without a major-version bump as long as the contract its output satisfies (frontmatter shape, claimed sections, golden eval gate pass) holds.
- **Documented revision trigger.** Prompts revise when a model change, eval result, or dogfood finding shows the current prompt is no longer the best implementation of the stable artifact contract.
- **Stale-detection is the user-facing consequence.** 0.10's stale-detection re-analyzes artifacts whose `prompt_id` or `model_version` falls behind the current floor. The cadence above is what defines the floor.
- **Distinction matters because users build on contracts, not prompts.** A downstream MCP consumer or Obsidian dataview depends on `synthesis_scope: "single-paper"` meaning the same thing it always meant - that's contract stability. It doesn't depend on the analysis prompt being literally identical to the 0.7 version - that's an implementation detail that *should* evolve as models improve.

**Quality bar (CI-enforced, not aspirational).**

- **Branch test coverage ≥95%**, ratcheted. 0.8.3 turns on branch coverage and starts the up-only climb from the measured baseline; 1.0 is where the gate reaches 95% across the surface. Branch (not line) is the metric, and the target is flat rather than tiered - the cost is real on presentation-heavy code (CLI rendering, web routes, dashboards), and that trade-off is accepted deliberately rather than hidden behind a per-package carve-out. Coverage is reported on every PR and can go up, not down.
- **Integration tests run by default** with mock LLMs so contributors run the full pipeline on every push without burning real spend.
- **Pyright strict** across the full surface, blocking - the completion of the per-package ratchet 0.8.3 begins (`distill/llm/` is already strict-blocking today). No `# type: ignore` without an inline reason comment.
- **Parse, don't validate - strict domain types at every boundary.** Every external input (MCP tool arguments, frontmatter parsing, local-file/adapter ingest, LLM structured outputs) is *parsed once* at the system boundary into a rich domain type (a Pydantic v2 model with `strict=True, extra='forbid'`, a `NewType`, or a frozen dataclass), not re-validated ad hoc deeper in. Core logic never receives raw primitives that could be invalid - illegal states are made unrepresentable, so malformed input fails at the boundary with a precise error instead of propagating. The audit health surface now parses verify sidecars into typed flag rows and stale prompt records before rendering or action planning. The shared dashboard data surface parses cost logs, latest-run payloads, topic-change history, and site manifests into typed records before CLI or web renderers read them. Shared command helpers now preserve typed metadata-writing and duration-formatting contracts before artifact writes. Topic diff, trend, watch-alert, and change-history command paths now use typed topic-change rows and typed count records before writing artifacts or rendering command output. Reinforces the verifiable-corpus thesis: the corpus is only as trustworthy as the parsing on what enters it.
- **Ruff** zero-warning under the project config, blocking. Cyclomatic complexity (`C901`) capped; `# noqa` requires an inline justification. Security rules (`S` / bandit) consolidated into the single ruff pass where practical.
- **Bandit + pip-audit** blocking in CI (both promoted in 0.8.3). Dependencies pinned via the committed `uv.lock`; CI installs with `uv sync --frozen` so the tested environment is the locked environment, a CycloneDX SBOM ships with each release, and PyPI publishing emits PEP 740 build-provenance attestations over the existing OIDC trusted-publishing channel (no stored credentials) so the chain from a reviewed `main` commit to the installed wheel is cryptographically verifiable.
- **import-linter** dependency-direction contracts blocking in CI (promoted in 0.8.3), so the layered architecture in [Target package layout](#target-package-layout-10) is enforced, not just documented.
- **Python 3.12-3.14 support matrix**, every version green on every PR. `requires-python = ">=3.12"`; the floor moves forward as old versions reach EOL, the ceiling tracks the current stable release.
- **Container runtime matches the Python floor.** The Dockerfile follows the same Python 3.12 minimum as the package metadata, and focused metadata tests keep the image base from drifting behind the supported runtime.
- **OS support matrix: Linux, macOS, and Windows are all first-class.** Shipped 2026-06-11: CI now runs the unit suite + CLI smoke on `macos-latest` and `windows-latest` (Python 3.12) alongside the full coverage-gated 3.12-3.14 matrix on ubuntu, so path handling, console rendering, and subprocess behavior are enforced on every platform users actually run - development happens on Windows, and before this the CI was ubuntu-only. 1.0 may widen the smoke jobs toward the full version matrix. This tool has to work for anyone, on whatever box they have - including local models on consumer GPUs.
- **No silent error swallowing.** Every `except` either re-raises or logs-then-raises. Audited and lint-rule-enforced where ruff supports it.
- **Golden corpus eval gate - STRUCTURAL offline gate; quality lives in `distill eval`, not CI.** Two things that must stay separate (the charter, [`docs/design/agentic-balance.md`](docs/design/agentic-balance.md)):
  - **The offline CI gate is structural and deterministic, and stays that way.** It runs with no API keys, so it *cannot* judge quality with a model. What it legitimately freezes (as `test_golden_gate.py` already does today): scorer **discrimination** (the hand-written golden scores high, a deliberately-degraded output scores low - proving the scorer isn't a rubber stamp), fixture↔golden **sync**, and prompt-builder **wiring** (the real per-workload prompts assemble with a mock LLM). Using the deterministic composite *here* is fine because it scores **fixed, hand-written goldens we control** to test discrimination - it does **not** score live model output. The hard rule: **never extend this gate to score *live* model output against composite floors** - that is the brittle trap (it would punish paraphrase and reward keyword-stuffing, gating every prompt change on a regex). The ~20-fixture scale-up grows the *fixtures*, not the gate's job.
  - **Live-output quality is judged by `distill eval`'s model judges** (faithfulness + coverage against the source), run on-demand against a real model. That is the only place a quality judgment belongs, and it is model-judged, not a deterministic score. It is not, and cannot be, an offline CI gate.
  - Still ahead: a structural golden for the concept-playbook pipeline (threshold/polarity discrimination, same shape), the ~20-fixture scale-up, an `eval_models` MCP tool. (Correction 2026-06-14: an earlier draft of this line wrongly called for a "model-judged offline gate" - impossible without keys in CI, and unnecessary since the gate is structural and live quality is `distill eval`'s job.)
- **Metamorphic robustness pass - CUT as fake-rigor (do not build).** The previous plan here (METAL templates; `SynonymReplacement` / `L33TChanging` perturbations; a Universal-Sentence-Encoder cosine ≥ 0.6 acceptance gate; kappa floors; ~30 variants) is **removed.** It perturbed surface tokens and asserted concept-set stability against cosine-similarity thresholds - measuring surface-token stability and calling it semantic robustness. That is a pile of deterministic thresholds dressed as science, the exact brittle-proxy pattern the charter ([`docs/design/agentic-balance.md`](docs/design/agentic-balance.md)) forbids, and as a CI gate it would block legitimate prompt changes on cosine numbers. If robustness-to-rephrasing ever genuinely needs testing, it is a **model judgment** ("do these equivalent inputs yield the same substantive concepts?"), not a cosine gate - and it earns its place only by `distill eval` showing it catches real regressions, not by citing a framework. Do not build the cosine/perturbation machinery.
- **Pre-commit hooks identical to CI checks** - no contributor surprises between local and remote.

**Verification depth (where it matters, not everywhere).** Phased implementation
plan and tool selection: [`docs/design/verification-depth.md`](docs/design/verification-depth.md).

The gates above prove *coverage* and *types*. These prove the tests and the code are actually correct under adversarial conditions. They are scoped to the layers where correctness is load-bearing - the deterministic pure-Python core (`concepts/` merge + normalize + recovery, `library/` slugs + frontmatter + links, evidence-interval arithmetic) and the external-service boundaries - not blanket across presentation code, because that is where the cost/value trade-off actually lands.

- **Design by Contract on the deterministic core.** Encode the merge/normalize/recovery invariants as executable pre/postconditions and class invariants (via the `deal` library, which also generates Hypothesis tests directly from the contracts) - for example: merge is idempotent and order-independent, a rollback's rebuilt rollup row round-trips the restored frontmatter, evidence intervals never invert. Contracts run in dev and CI and can be optimized out (`python -O`) where overhead matters. Applied to the same pure-Python layer the property tests already target, so the two compound rather than overlap.
  - Status 2026-06-28: merge interval/source-preservation contracts, path component confinement contracts, normalize canonicalization/grouping/threshold contracts, recovery frontmatter/rollup-row contracts, library frontmatter emit/merge contracts, wiki-link parse and link-check shape contracts, and generated contract tests for parser, canonicalization, path-sanitizer, grouping, threshold, merge, frontmatter, and wiki-link parse contracts are executable.
- **Mutation testing on the core packages.** A periodic `mutmut` (or equivalent) pass injects artificial regressions into `concepts/`, `library/`, and the `pipeline` verify/dedup core and asserts the test suite catches them - proving the suite's *efficacy*, not just its coverage percentage. Scoped to the core (mutation testing is too slow to run blanket on 14.5k lines) and run on a cadence, not every PR. Complements the structural golden-corpus gate and model-judged `distill eval`: those catch prompt and output drift, this catches dead tests.
  - Status 2026-06-28: Phase 2 is wired as a non-blocking manual plus weekly
    GitHub Actions diagnostic across contracted `concepts/`, `library/`, and
    `pipeline` verify/dedup core modules. The job copies the full package for
    import closure, reads its deterministic mutation-test slice from
    `[tool.mutmut]`, and reports mutation evidence without making mutation
    score a release or PR gate. The first local survivor triage targeted
    library path helpers and added deterministic tests for path-component
    rejection, default artifact filenames, frontmatter list and boolean
    emission, and nested atomic writes, improving the Linux diagnostic killed
    count from 1,217 to 1,258 while keeping the score advisory. The second
    survivor triage targeted `concepts.recovery`, tightened colon-bearing slug
    rejection, and added tests for fallback note lookup, snapshot timestamp
    normalization, malformed source filtering, rollup row replacement, entity
    rollup routing, and rollback sorting. A recovery-only Linux diagnostic
    improved from 407 killed / 178 survived to 439 killed / 159 survived.
- **Stateful property testing of the playbook lifecycle - shipped.** A Hypothesis state machine (`tests/unit/concepts/test_playbook_stateful.py`) models the concept layer's real lifecycle - append mentions to `mentions.jsonl`, merge, write notes, snapshot to `.history/`, roll back, re-merge - and asserts the invariants hold across arbitrary operation orderings (merge consistency, idempotence, order independence, rollback round-trip, evidence intervals never invert). This is the class of bug (ordering, accumulation, rollback-after-merge) that single-shot example tests miss.
- **Fault-injection at the external boundaries.** Deterministic tests that inject malformed LLM JSON, truncated/empty transcripts, network timeouts, and yt-dlp failures, asserting the pipeline degrades cleanly (resume-friendly, no half-written artifacts) and that the "no silent error swallowing" rule actually holds under turbulence - verified, not assumed. distillr's concurrency is asyncio IO, so the discipline that matters is async-safety (no blocking calls in async paths, correct cancellation), not the shared-memory thread-safety a free-threaded service would need.

**Polish.**

- Repo presentation pass: README screenshots/gifs (terminal dashboard, sample report, web UI, library in Obsidian), GitHub repo description and topics, and contributor onboarding that gets a new contributor from clone to a verified first contribution path.
- All public APIs documented (concise docstrings on the public surface; longer where the rationale isn't obvious from naming).
- `docs/CONTRIBUTING.md` covers the full quality posture above so contributors know the bar before they open a PR.

Why this version: 1.0 is a stability *and* quality claim. It's the version external systems can build on without expecting churn, and the version a new contributor can land a clean PR in without a long onboarding tail. Competitively, the agent-integration story now ships much earlier (the agent-legible 0.9 pass); 1.0's job is the presentation pass, onboarding docs, and stable contracts that convert "technically superior" into "actually adopted" - and by this point the story writes itself: verified, agent-legible, multi-source, user-owned.

## Looking beyond 1.0

Not committed. Notes on directions worth thinking about once 1.0 stability is in place.

- **Shareable goal-files / topic recipes.** A `discover` goal-file is already an executable description of a corpus - the same "idea file as a prompt you hand an agent" format Karpathy's gist popularized. The direction is making goal-files portable artifacts: publish or share a goal-file (with its `--site-seeds`) so someone else can reproduce or refresh a corpus from the research *intent*, not just receive the output. Plain Markdown like everything else, no lock-in, and it fits the post-1.0 plugin-boundary timing rather than the critical path.

- **Provider breadth + plan-quota compute on an eval-gated adapter contract (committed).** The `distill/llm` router already abstracts provider+model behind workload tags, and the provider directory is further along than the pitch admits: grok, gemini, ollama, and lmstudio are calibrated/wired today, while Anthropic and OpenAI are reserved post-1.0 cloud routes that must be implemented and calibrated before use. An `AgentProvider` already does deferred zero-cost execution via task files an external agent (Claude Code, Kiro) picks up. The committed post-1.0 work has three strands, all behind the same gate:

  - **Cloud API adapters**: complete the set - xAI and Google are live today; Anthropic, OpenAI, AWS Bedrock, and Microsoft Foundry are post-1.0 adapter work that must be implemented, calibrated, and eval-gated before use - so users on enterprise clouds run distill against the endpoints they are provisioned for. A default still ships (one calibrated cloud route + the local route); everything else is opt-in.
  - **Plan-quota compute (the "you're already paying for it" class).** Many users carry subscription plans with generous quotas - Claude (Pro/Max), OpenAI Codex, Gemini/Antigravity, Grok plans, OpenCode, Kiro - plus local hardware. Routing batch analysis through the **agent CLIs those plans license** (headless invocations, or the shipped `AgentProvider` task-file pattern when direct invocation isn't permitted) makes marginal ingestion cost approach zero for people already paying a flat fee. Two hard caveats are part of the design, not afterthoughts: (a) **plan terms and headless-automation policies churn** - vendors change what subscriptions permit for programmatic CLI use, so each harness adapter ships with a documented support statement and degrades to a clean message, never silent breakage or ToS-violating workarounds; (b) **"free" is not "usable"** - a plan-quota or local model graduates only by clearing `distill eval`'s cost x quality bar on the golden fixtures, exactly like any other backend. Plan-quota runs still record token volumes to the cost ledger (the no-off-ledger-spend invariant covers usage, not just dollars).
  - **The gate**: `distill eval` decides everything. A backend goes from "wireable" to "calibrated and eval-recommended" only by clearing the bar, and the same harness produces the cross-provider, cost-aware comparison that says which backend to use for which workload - and whether a plan-quota or local model now beats the cloud floor. Distillr ships no uncalibrated default, so breadth is added *without* abandoning the no-calibration-debt discipline (see [Intentionally not in scope](#intentionally-not-in-scope)). The eval gate is the thing that pays the calibration debt down cheaply instead of guessing.

- **Provider prompt and context caching policy.** The research spike is complete in [`docs/design/provider-caching.md`](docs/design/provider-caching.md). Before enabling provider-side prompt caching knobs, Distill must use provider-specific economics, not a generic "cache on" flag: Anthropic cache writes cost more than base input and 1-hour TTL costs more again, OpenAI and Azure OpenAI caching is automatic but still needs hit-rate telemetry and retention policy, Gemini explicit context caching can add storage-time charges, Bedrock cache checkpoints have platform-specific TTL and usage fields, and xAI cache hits are automatic and evictable. Any implementation must be opt in per provider, record cached token and storage metrics in the ledger, avoid pre-warming unless projected savings are positive, set explicit TTL or retention bounds when the API allows it, stop background cache refreshes when the command exits, and never claim no-metered savings unless the route proof and usage ledger show it.

- **Semantic alias resolution over `mentions.jsonl`.** 0.8's normalize layer canonicalizes mention names mechanically (case-folding, plural stripping, punctuation cleanup). That handles the easy cases. The hard cases - "rotational embeddings" / "rotation embedding" / "phase rotation" being three names for the same concept; "DeepMind" / "Google DeepMind" being one org; or, more painfully, two papers in the same field using entirely disjoint vocabularies ("SciBERT" + "BiLSTM-CRF" vs "SciEvent" + "Agent-Action-Object triples") - are out of reach of regex.

  *Architecture, grounded in the cross-document event coreference literature:* two paradigms are validated and complementary. (a) **Symbolic compression**: assign each mention a structured identifier from its arguments - borrowing X-AMR's PropBank-style roleset + ARG-0 (Agent) / ARG-1 (Patient) / ARG-Loc / ARG-Time decomposition - then cluster via connected components on identifier match. Linear in corpus size; falls back to mechanical canonicalization when arguments are missing. (b) **Semantic compression**: generate a short LLM elaboration per mention (1-2 sentences expanding what the mention refers to), then run small-model pairwise scoring + clustering on the elaborations. The 2406.02148 / 2404.08656 papers found these two paradigms have complementary failure modes - symbolic misses paraphrase, semantic misses precise argument structure - and that a staged pipeline (symbolic bucketing first, LLM elaboration for ambiguous clusters) outperforms either alone. That staging is the recommended target architecture.

  *Why now matters for the schedule:* the corpus consensus from the entity-resolution literature is that direct LLM-as-classifier ("just ask GPT-4 if these are the same concept") consistently underperforms hybrid pipelines. Distillr's general no-LLM-for-verification stance survives intact under this finding - LLMs go in the *elaboration* helper role, not the *decision* role. Connected-components clustering is the final-arbiter step and stays pure Python.

  *Evaluation yardstick:* the ECB+ corpus metric suite is the established baseline - MUC, B³, CEAF_e, and CoNLL F1 are what the field reports. distillr's golden eval corpus should produce these scores against hand-coded clusters so improvement is measurable.

  *Surface shape:* an offline `distill concepts resolve-aliases [<topic>]` command that proposes merges (candidate pairs above a confidence threshold) and asks for confirmation, not an automatic pass that silently reshapes the corpus. Confirmed aliases append to a per-topic `aliases.yml` that the normalize layer reads at canonicalization time. The right pattern for a knowledge layer the user inspects.

  *Validated as a real need, not speculative.* In a controlled internal validation run on two papers from the same task family ("scientific claim extraction"), the 0.8 concept layer surfaced 24 distinct mentions and zero cross-paper concepts at threshold=2 - every term was unique across the pair despite topical overlap. Mechanical canonicalization cannot bridge that vocabulary gap. The literature's two-paradigm answer is well-validated; what's left is the engineering integration, scoped to post-1.0 so it doesn't widen the 1.0 surface.

- **Caching as a load-bearing pattern across eval/synthesis/resolution layers.** The research areas above that depend on repeated model judgments (claim extraction, long synthesis, entity resolution) call out caching of LLM-derived intermediates as the engineering pattern that makes their approaches affordable at scale. distillr already has this implicitly in `mentions.jsonl` (cache extraction outputs), but `claims.jsonl`, model-judged eval runs, and alias-resolution passes need it as a deliberate design element, not a bolt-on. Worth a shared utility in `distill/llm/cache.py` rather than three independent implementations. Keep this distinct from provider-side prompt caches: local durable intermediate caches are files Distill owns and can inspect, while provider caches are opaque, TTL-bound, and may carry provider-specific cost or retention behavior.

## Target package layout (1.0)

The shape distillr is being refactored toward. 0.3 stands up the top-level subpackages and the conventions; later milestones populate them. `import-linter` and the module-size cap from 0.3 enforce this layout in CI - it is not aspirational.

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
│   ├── topic.py
│   ├── costs.py
│   ├── doctor.py
│   ├── serve.py
│   ├── dashboard.py
│   └── ingest.py            # 0.9 - local-file ingest
│
├── ingestors/               # capture layer - one source per subpackage
│   ├── youtube/             # search, download, transcript
│   ├── sites/               # scraper, attachments, browser
│   ├── papers/              # arxiv, pdf
│   └── local/               # 0.9 - local-file routing
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
│   │   ├── chunking.py      # 0.6 - adaptive section-aware (local models only)
│   │   └── rerank.py        # 0.6 - per-category chunk rerank (local models only)
│   ├── synthesis/
│   │   ├── topic.py
│   │   ├── corpus.py
│   │   └── register.py      # 0.9 - PhD / exec / pop styles
│   ├── report/              # 4-phase Deep Research pipeline
│   │   ├── phase1_research.py
│   │   ├── phase2_facts.py
│   │   ├── phase3_writing.py
│   │   ├── phase4_qa.py
│   │   └── compaction.py    # 0.6 - between-phase summaries
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
│   ├── slugs.py             # 0.7 - stable slug discipline
│   ├── frontmatter.py       # 0.7 - YAML read/write
│   └── links.py             # 0.7 - wiki-style cross-links + link-check
│
├── concepts/                # 0.8 - ACE-style concept/entity playbook layer
│   ├── extract.py
│   ├── merge.py
│   ├── notes.py
│   └── contradictions.py
│
├── mcp/                     # MCP server (split from today's mcp_server.py)
│   ├── server.py            # transport, registration, lifecycle
│   ├── tools/               # mirrors commands/ shape
│   │   ├── find.py          # 0.5 - find_insights / read_insight (JIT)
│   │   ├── discover.py
│   │   ├── topics.py
│   │   ├── watch.py
│   │   ├── gaps.py
│   │   └── costs.py
│   ├── resources.py
│   └── prompts.py           # MCP-protocol prompts (distinct from distill/prompts/)
│
├── notify/                  # 0.5 - outbound watch-alert channels
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

Once 0.3 lands, the canonical version of this layout - with rationale per subpackage - moves into [`docs/architecture.md`](docs/architecture.md). This roadmap section is the snapshot that 0.3 builds toward.

## Engineering standards: adopted, adapted, declined

The 0.8.3 and 1.0 quality posture above was pressure-tested against two general "elite Python standards" briefs - a baseline one (uv-everywhere, NASA Power-of-10, 3.14-only, 95% coverage, full OpenTelemetry) and a more advanced one (formal verification, Design by Contract, supply-chain provenance, pure-Python-first, free-threading). A standards memo is a useful forcing function, but applying one wholesale to a published library is how a project acquires cargo-cult gates that fit someone else's system and not its own. This section records the judgment calls so a future contributor (or a future revisit of the same brief) does not silently re-import the parts distillr deliberately rejected. It is the same discipline as "Intentionally not in scope" below, applied to engineering process rather than product surface.

**Adopted** (genuinely new, high-value, in scope at 0.8.3 / 1.0):

- `uv` as the sole toolchain, a committed `uv.lock`, and `uv sync --frozen` in CI - reproducible environments, and the direct fix for the dependency-float break that motivated 0.8.3.
- `import-linter` and `pip-audit` promoted into blocking CI; `pre-commit` made identical to CI; `xfail_strict`; branch coverage; SBOM on release. (Automated dependency update bots were trialed in 0.8.3 and deliberately dropped - dependency bumps are reviewed manually.)
- The full Pyright-strict ratchet and "parse, don't validate" strict domain types at every boundary (1.0).
- **PEP 740 build-provenance attestations** over the existing OIDC trusted-publishing channel (secretless), so the path from a reviewed `main` commit to the installed wheel is cryptographically verifiable. The cheap, high-value slice of the advanced brief's Sigstore/SLSA section.
- **Verification depth on the deterministic core** (1.0): Design by Contract (`deal`) on the merge/normalize/recovery invariants, mutation testing of the core packages, Hypothesis stateful testing of the playbook lifecycle, and fault-injection at the external-service boundaries. "Formally contracted where it matters" - scoped to the pure-Python core, not blanket.

**Adapted** (taken in spirit, tailored to this project):

- **Python 3.12 floor + 3.13/3.14 matrix, not 3.14-only.** distillr is a library other people install; the baseline optimizes for "good citizen to downstream consumers," not for access to runtime features (free-threading) an IO-bound tool will never exercise.
- **Pyright, not Astral `ty`.** `ty` is promising but too immature in mid-2026 to gate CI on; the strictness target is identical, the checker stays the one already wired in.
- **Structured-logging discipline, not full OpenTelemetry.** No-secrets, level-correct, file-capturable logging is the bar. Distributed tracing and OTel semantic conventions are service-grade observability for a single-user local CLI - overhead without a consumer.
- **`ruff` security rules consolidated, not the full unstable preview ruleset.** Fold bandit's `S` checks into the one ruff pass where practical; do not turn on preview rules wholesale, which churn between releases and would fight the reproducibility goal.
- **Static analysis at the floor (3.12), tested at the ceiling (3.14).** ruff and Pyright target 3.12 so a 3.13/3.14-only syntax or API can't slip past review and break a supported user; the test matrix still runs the newest. The advanced brief's "3.14 as the static-analysis baseline" would invert this and silently raise the real floor.
- **Design by Contract scoped to the deterministic core, not blanket.** `deal` contracts pay off on the pure-functional merge/normalize/recovery/interval layer where invariants are crisp; smeared across IO/orchestration/presentation code they become noise. "Where it matters" is doing the work in that phrase.
- **structlog with consistent semantic fields, not full OpenTelemetry tracing.** Adopt the field-naming discipline (stable keys, no secrets) without standing up a tracing backend a single-user local CLI has no consumer for.

**Declined** (wrong for this project):

- **3.14-only baseline** - breaks installs for the entire current downstream base; covered above.
- **Pure-Python-first / ban C extensions.** distillr's *own* code is pure-Python, but its dependency tree legitimately rests on compiled cores - `pydantic-core` (Rust, and the foundation of the strict-boundary parsing the brief itself wants), plus `playwright`, `uvloop`, `httptools`, `watchfiles`, `websockets`. Banning them is neither possible nor desirable. distillr's "purity" discipline is **no database, pure-Markdown corpus** - a product-architecture commitment - not "no compiled dependencies," which would be cargo-cult and would forbid the very tools that make the rest of the bar achievable.
- **Free-threaded (3.14t) build + shared-memory concurrency rules.** distillr is IO-bound (network, LLM, disk); free-threading buys nothing, and key deps (`pydantic-core`, `playwright`) are not cp314t-ready. Its concurrency is asyncio, so the relevant discipline is async-safety, not the message-passing/no-shared-mutable-state rules a free-threaded compute service needs.
- **Container / image scanning (trivy), full SLSA L3 generators** - distillr ships as a PyPI wheel, not an image. `pip-audit` + SBOM + PEP 740 attestations cover the actual supply-chain surface; the container-and-SLSA-L3 apparatus is for deployed services.
- **Auto `uv lock --upgrade` in CI.** A manually reviewed upgrade PR (running full CI against the new lock before merge) is strictly safer than CI silently re-resolving - the un-reviewed auto-upgrade is the same dependency-float failure mode 0.8.3 exists to kill, just relocated. (Automated bump bots are also declined; bumps are reviewed by hand.)
- **Power-of-10 hard gates that do not fit a Markdown pipeline** - two-asserts-per-function, fixed loop bounds, and no-recursion are flight-software rules for hard-real-time control loops. The in-character subset is already convention here: module-size caps, `C901` complexity caps, no silent error swallowing, narrowest-scope declarations. The rest would be ceremony, not safety.
- **Copier / portfolio template scaffolding** - a cross-project concern (how *many* repos share standards), not a property of distillr's own codebase. Out of scope for this roadmap.

## Security posture

distillr's threat model follows from what it actually is: a local-first CLI and MCP server that **consumes** third-party LLM APIs (xAI, Gemini) to turn untrusted public sources into a local Markdown corpus. It trains no models, serves no inference, holds no model weights, and is single-user. So the large body of "AI security" guidance aimed at *model builders and operators* - training-data poisoning and backdoors, model extraction / inversion / membership inference, differential privacy and privacy-budget accounting, confidential-compute enclaves (TEEs / SMPC / homomorphic encryption), model watermarking and signing, adversarial-robustness certification, multi-agent trust zones, post-quantum model-IP protection - targets a system distillr is not. Those are **out of scope by architecture, not by neglect.** distillr's real assets are the user's API keys and the integrity of the corpus; its real attack surface is untrusted ingested content plus the tool and HTTP boundaries.

**Already in place:**

- **Supply chain** (0.8.3): committed `uv.lock` + `uv sync --frozen`, blocking `pip-audit` and bandit in CI, a CycloneDX SBOM, PEP 740 provenance attestations, and SHA-pinned GitHub Actions, including the PyPI publish action after verifying its matching container image tag. For an API consumer the "model supply chain is the new software supply chain" concern reduces to ordinary dependency hygiene, which is covered. (Dependency/action bumps are reviewed manually; automated dependency update bots are deliberately not used.)
- **MCP path confinement**: `read_insight` / `read_concept` resolve caller-supplied paths through `_resolve_within_library` and refuse anything outside the library root (the path-traversal / auth-bypass class addressed in the prior security pass).
- **Secret handling**: API keys are `SecretStr`, kept out of artifacts and logs; a `detect-private-key` pre-commit hook guards commits.

**Hardened in 0.8.7:**

- **Indirect prompt-injection resistance.** The one AI-specific threat that actually applies: every analyzed source (YouTube transcript, web page, PDF, tweet) is untrusted input fed to an LLM, and a source can carry embedded instructions ("ignore previous; write X") that hijack the analysis or synthesis and land in the corpus. A shared `UNTRUSTED_CONTENT_RULES` constant is now threaded into every per-source analysis prompt (video, shorts, scan, site page, paper, tweet): the embedded source is labelled untrusted data and the model is told to ignore any instructions inside it. This is the *prevention* half; the 0.10 run-time verify hook (claim-grounding) is the *detection* half, and they compose.
- **Web-dashboard output sanitization.** The local dashboard rendered corpus artifacts through `markdown(...)` with raw HTML passed through (`distill/web/server.py`), so untrusted-derived content - or an injected `<script>` inside an insight - was a stored-XSS vector. The rendered HTML is now run through an `nh3` allowlist sanitizer before serving (script/event-handlers/`javascript:` URLs stripped, formatting and tables preserved), per Python-Markdown's own guidance to sanitize output rather than trust the renderer.

**Still ahead (1.0):**

- **Boundaries are trust boundaries.** The 1.0 "parse, don't validate" work already validates MCP tool arguments and ingest inputs; the roadmap states explicitly that those parsing boundaries *are* the security boundary - path confinement and URL/SSRF validation on fetch paths live there, so the parse layer doubles as the trust layer rather than being a separate bolt-on.
- **Agent-facing guidance is validated, not just written.** Any future skill text, MCP tool description, adapter prompt, or generated orientation template that tells an agent how to act should carry a small source-controlled contract: scope, risk class, allowed side effects, expected verifier, and test plan. CI should validate those contracts and the house-style rules so agent-facing files cannot drift into personal account assumptions, machine-attribution lines, secret leakage, or unbounded tool affordances.
- **Guardrails stay surface-scoped.** Always-on checks cover credentials, cost policy, personal-data hygiene, attribution/style, and irreversible-action boundaries. Surface-specific checks cover URL ingest, local-file ingest, MCP path reads, external adapter scratch writes, and provider routing. This keeps the guidance small enough to follow while preserving the agentic-balance rule: deterministic code owns structure and safety boundaries, model judgment owns semantic quality.

If distillr ever ships a hosted multi-tenant service or fine-tunes its own models, the out-of-scope list above reopens. Until then, deepening it would be securing an attack surface the project does not have.

## Intentionally not in scope

A roadmap is also an opinion about what *not* to build. These are deliberate exclusions, not gaps. Several are informed by the competitive landscape (see above) - competitors that make different choices validate that these are real trade-offs, not oversights.

- **No graph-view UI inside distill.** Obsidian / Logseq / Dendron already do this well; reimplementing duplicates effort without adding value. The Obsidian-native milestone (0.7) is the answer. (SwarmVault builds its own graph view; we get it free from the ecosystem.)
- **No proprietary editor, mobile app, or cloud-hosted SaaS.** The whole point is plain-text Markdown with no lock-in. A hosted version would create exactly the dependency the project exists to avoid.
- **No general-purpose RAG / vector-store / SQLite index.** distillr is opinionated about the corpus shape and the analysis pipeline. Embeddings are an implementation detail (used selectively for dedup, possibly inside `find_insights`), not a primary surface. Users who want a generic RAG toolkit have LangChain and LlamaIndex. (SwarmVault and Lacuna-wiki add SQLite/DuckDB; we deliberately avoid this - pure-Markdown + git-friendly is the defensible niche for serious researchers.)
- **No multi-user / auth / collaboration layer.** Single-user local tool. Shared corpora are a `git` problem, not a distillr problem.
- **No additional cloud LLM providers by default.** Each provider is calibration debt - prompts that work well on one model regress on another. Users can wire OpenAI / Anthropic / Mistral / etc. through the 0.3 router, but distillr won't ship default model policies for them. Local providers are the exception because they carry the local-first promise. (Transcription providers are not subject to this exclusion: speech-to-text carries no analysis-prompt calibration debt, so the Whisper transcription ladder ships a cloud tier - xAI Grok STT, reusing the already-required `XAI_API_KEY` - beneath the local-first default.) The exclusion is against *uncalibrated defaults*, not against provider reach: post-1.0, the eval-gated adapter contract (see [Looking beyond 1.0](#looking-beyond-10)) is the path by which a backend - local or cloud (Bedrock, Foundry, Anthropic, OpenAI, Google, xAI) - graduates to calibrated-and-recommended by passing `distill eval`, rather than being shipped blind.
- **No plugin / extension system before 1.0.** Premature abstraction. The right plugin boundaries become obvious only after the internal architecture from 0.3-0.5 has carried real workloads. Revisit post-1.0.
- **No real-time collaboration or sync service.** Markdown + git is the answer. distillr won't compete with Obsidian Sync, Logseq Sync, or Syncthing.
- **No "install skills into your agent" model.** obsidian-wiki (Ar9av) takes the approach of symlinking skill files into Claude Code / Cursor / etc. Distillr's architecture is separation of concerns: distillr is the dedicated memory layer, agents query it via MCP. A thin skill wrapper would be useless for long-running batch ingestion and persistent corpus maintenance - exactly what interactive agents are terrible at.
- **No anti-bot / paywall / login-walled scraping.** Playwright handles legitimate access; defeating hostile defenses is whack-a-mole that pulls focus from the analysis pipeline and creates legal/ethical surface area.
- **No "cheap mode" that compromises fidelity.** The product premise is "as good as we can possibly make it" regardless of whether inference runs locally or in the cloud. Local models exist to make the corpus *always current* at zero marginal cost, not to produce worse outputs faster. Cost reduction happens through local inference, compaction, and JIT context - never through cheaper prompts that produce worse outputs. A local insight must be good enough that synthesis and expert queries can trust it without qualification.

These exclusions are load-bearing, not permanent. They get revisited if the constraint that drives them changes.

## Full backlog

The area-by-area backlog (stay-current, dashboard, papers, cross-source intelligence, context engineering, discovery loop, etc.) lives in [`docs/roadmap.md`](docs/roadmap.md). Items there will be tagged with the milestone above where they land in a follow-up pass.

Design principles drawn from the context-engineering literature are summarized in [`docs/architecture.md#context-engineering-principles`](docs/architecture.md#context-engineering-principles).
