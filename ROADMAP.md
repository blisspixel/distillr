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
- **arXiv papers** (stable) - query expansion, LLM rerank, full-PDF extraction, cross-paper synthesis
- **X posts** (beta) - `distill ingest <tweet-url>` via the public syndication endpoint, with local-first Whisper transcription for native video
- **GitHub repos** (new adapter) - `distill ingest <github-url>` captures repo metadata, README, and releases into structured maturity / when-to-use insights
- **Podcasts** (new adapter) - RSS-first ingestion, publisher transcripts preferred before audio transcription
- **Newsletters / feeds** (new adapter) - full feed bodies when available, routed by substance rather than attached narration
- **Local files and media** (new adapter) - PDF / Markdown / text / HTML documents, plus local audio/video through the transcription ladder

`distill discover` is the goal-aware front door across papers, videos, and curated website seed files. The next refinement for docs-heavy research is app-native trusted-site discovery on allowlisted domains, so workflows like "prefer Microsoft docs + Microsoft channels" do not require hand-curated page seeds.

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
- **Local-first all the way down.** "Local Markdown corpus" is meaningless if every analysis call goes to a paid cloud API. When ingestion is basically free, you use it more - more sources, more frequent refreshes, richer corpus. Local doesn't mean lower quality; it means the economics don't punish thoroughness. If a workload can't meet the quality bar locally, it stays on cloud. Tested on RTX 4090 (Windows) and M1 Mac; should work on any Ollama/LM Studio compatible hardware. The hardware trend bends this way: consumer GPUs (4090/5090-class) already run capable 27B-70B models, and DGX Spark-class desktop and laptop machines arriving through late 2026 put much larger local models within reach on a single workstation. So the default bias shifts toward local *whenever a workload clears the quality bar* - with `distill eval` (cost x quality over frozen fixtures) as the arbiter of "good enough" rather than vibes - and cloud stays the floor for what local can't yet match (long-context synthesis, web-grounded Deep Research). The router exists precisely so this ratio can move per-workload over time without touching pipeline code.
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

Previously shipped: **0.1 through 0.16**. Most recent: the blocking **golden-corpus eval gate** (0.16) - the test-time complement to the verify hook, freezing what good extraction looks like; **agent-grade `--json` + a strict stdout/stderr split** (0.14) and in-place **`distill update`** (0.15); and the **entailment tier** plus **verify on every synthesis emit** (0.13). Before those, the **agent-legible corpus** pass (AGENTS.md + the canonical skill + the public example corpus + the MCP truth-up) and the **0.10 verified-corpus core**: the write-time claim-grounding hook on every analysis emit path with `warn|strict|off` modes, and `distill audit` rolling verification coverage + health + links + gaps into a per-topic report artifact (both validated live against real model output). Earlier: Initial release and internal foundations; the MCP-first surface; local inference; the living-wiki concept/entity playbook plus its recovery surface (`concepts log/diff/rollback`, MCP `concept_history`/`concept_diff`); the reproducible `uv` toolchain and engineering baseline; the agent-discoverable library (auto-generated `CLAUDE.md`); the **0.9 discovery loop** (preview-as-default, score-cliff sizing, `--rigor`, gap-driven discovery); **two-pass synthesis** with a structured claim intermediate; synthesis **register styles** + the anti-AI-slop guard; **local-file ingest** (`distill ingest <path>`); the **X + Whisper** adapter (local-first transcription); and the **goal-aware agentic slice** (adaptive analysis lenses + persisted `CorpusIntent` on every ingest entry point, the thesis/white-space synthesis rung, corpus-aware discovery dedup + reproducible plans). Interleaved with these: the **0.9.20-0.9.23 security/robustness hardening series** (yt-dlp SSRF, dashboard exfil beacon, ingest/MCP/syndication DoS ceilings, second-hop prompt-injection hardening, atomic-write durability, GitHub-Actions SHA-pinning, and a parse-don't-crash sweep over untrusted/corruptible local state) plus the 0.9.26 command-dispatch fix. Per-release detail lives in [`docs/CHANGELOG.md`](docs/CHANGELOG.md).

The full spine to 1.0 and beyond, ordered by dependency - each milestone unblocks the next, shipped ones shown for continuity and forward ones below them. *(Reordered 2026-06-11 after the June competitive-research sweep: the verify hook moved forward - it gates three later milestones, its architecture is now settled practice, and trust is the frontier the leaders compete on; agent legibility was promoted out of "1.0 polish" because it is distribution, it is near-free, and the window is now; source breadth lands behind the trust gate so a wider input funnel doesn't compound unverified content.)*

- **Agent-legible corpus (0.9 series)** - emit AGENTS.md alongside the per-topic CLAUDE.md, publish one canonical SKILL.md teaching agents the CLI, consolidate the MCP surface to a few workflow-shaped paths-not-payloads tools, and refresh positioning (research corpus, not "memory layer"). [detail](#agent-legible-corpus-09-series)
- **0.10 Verified corpus - shipped (0.10.0-0.10.2 core; entailment tier 0.13.0; synthesis-verify completed 0.13.1).** The deterministic claim-grounding hook on every emit path + `distill audit`, the **local entailment tier** (HHEM-2.1-Open behind `distillr[entailment]`, prose claims scored against receipts, sidecar schema v2 additive, strict refuses on prose flags too), and now **verify on every synthesis emit** (paper, channel, topic, corpus single- and two-pass, site, site-topic - each grounded against its own inputs; strict refuses; `distill audit` counts synthesis sidecars separately). Design: [`docs/design/entailment-tier.md`](docs/design/entailment-tier.md). [detail](#0100--verified-corpus-run-time-verify--self-maintaining-audit)
- **0.11 Source breadth and audio capability - shipped (0.11.0-0.11.2; YouTube-resilience margin closed 0.12.11).** All five adapters live (GitHub repos, podcasts RSS-first, generic media files, newsletters, plus the 0.9 X adapter) on the documented contract, every one behind the verify gate. The flagship YouTube path now retries transient caption failures with backoff and falls back to the same local-first Whisper ladder every other audio source uses. [detail](#0110--source-breadth-and-audio-capability)
- **0.12 Compounding corpus - named scope shipped (0.12.0-0.12.6).** The `distill ask` loop with strict-by-definition promotion, sub-agent MCP summaries (revision-cached), read-only MCP, scheduling recipes, semantic dedup, the prompt-version registry + staleness rollup + re-analysis trigger, estimator accountability. Goal-file watch hook shipped 0.12.7 (persisted goals + catch-up surfacing the exact preview refresh commands); synthesis stale-flag shipped 0.12.8 (source-relative freshness in audit + dashboard + orientation files, planned from a full review of the 53-topic dev library, which also caught and fixed paper-only topics never refreshing orientation files). MCP per-call spend caps + ingest-domain allowlist shipped 0.12.9; per-item failure isolation + the convergent resume hint shipped 0.12.10 - **every named 0.12 margin is now closed.** (The once-remaining margins - the 0.11 YouTube-resilience path and the parallel-track entailment tier - shipped in 0.12.11 and 0.13.0.) [detail](#0120--compounding-corpus)
- **Engineering legibility + CLI-UX (0.13 onward, in progress)** - the run between the named source/trust/compounding milestones and 1.0. *Shipped:* the entailment tier + verify-on-every-synthesis (0.13), agent-grade `--json` / stdout discipline (0.14), `distill update` (0.15), the blocking golden-corpus eval gate (0.16), the `_logic.py` monolith removal, progress with running spend on the named ingest and report loops, global `--quiet` / `--verbose` output controls, structured DEBUG file logging, and consistent `--help` examples for recurring workflows. *In progress:* batch-run visibility and the remaining quality ratchets before the 1.0 contract freeze. Design: [`docs/design/logic-decomposition.md`](docs/design/logic-decomposition.md), [`docs/design/how-we-build.md`](docs/design/how-we-build.md). [detail](#engineering-legibility--cli-ux-013-onward)
- **0.17 OKF interop + loop-ready stewardship surface** - export and validate distill corpora as OKF v0.1 bundles without replacing the native corpus layout; add a machine-readable next-action plan over audit/gap/staleness findings so external loops can decide, budget, run, and verify work without scraping console prose. Design: [`docs/design/okf-loop-readiness.md`](docs/design/okf-loop-readiness.md). [detail](#0170--okf-interop--loop-ready-stewardship-surface)
- **0.18 Batch-run visibility** - with `_logic.py` retired, finish settling batch progress, running cost, and global verbosity controls before the CLI contracts freeze. [detail](#0180--decomposition-finish--batch-run-visibility)
- **0.19 Recurring research profiles + no-metered-cost routing** - make recurring topics like "AI developer news" or "live agentic dev" first-class profiles, and add a cost policy that can refuse metered API calls while allowing local models or explicitly configured plan-quota CLIs such as Codex CLI, Claude Code, Grok Build, Gemini CLI, and Antigravity when they pass eval. GitHub Copilot CLI is supportable later as a credit-metered route, not a no-metered default. [detail](#0190--recurring-research-profiles--no-metered-cost-routing)
- **1.0 Stability commitment + quality bar** - versioned CLI / MCP / library / frontmatter / OKF / next-action / profile contracts; Pyright-strict and "parse, don't validate" boundaries; the structural golden-corpus eval gate, model-judged live `distill eval`, and verification depth on the deterministic core; branch coverage >=95%; blocking lint/security CI; the OS support matrix; and the presentation pass. [detail](#100--stability-commitment--quality-bar)
- **Provider breadth + plan-quota compute (committed, post-1.0)** - the eval-gated adapter contract across cloud APIs (xAI, Google, **Anthropic and OpenAI - adapters already in-tree**, AWS Bedrock, Microsoft Foundry) *and* the plan-quota class: route batch analysis through agent CLIs and subscriptions only where support statements prove included-plan usage (Claude, Codex, Gemini/Antigravity, Grok, OpenCode, Kiro, local Ollama/LM Studio), with `distill eval` as the gate that decides what is actually usable. Credit-metered CLIs such as GitHub Copilot can be supported under explicit paid policy, but they do not belong in the no-metered default. [detail](#looking-beyond-10)
- **Beyond 1.0 (exploratory)** - semantic alias resolution over `mentions.jsonl`, and shared LLM-intermediate caching as a load-bearing pattern. [detail](#looking-beyond-10)

A harden pass is slotted in whenever the surface a recent feature added warrants it (the 0.9.20-0.9.23 series is the precedent), so the sequence above is the feature spine, not the whole release stream. Detail for each forward milestone follows; shipped releases - and the design rationale behind them - are recorded in [`docs/CHANGELOG.md`](docs/CHANGELOG.md). The "[intentionally not in scope](#intentionally-not-in-scope)" section at the bottom is the deliberate exclusions list.

### Agent-legible corpus (0.9 series)

The corpus already *is* the interface - plain Markdown, stable filenames, frontmatter, per-topic CLAUDE.md. This pass makes that architecture legible to every major harness and stops paying token rent on the MCP surface. All conventions and packaging; no new verbs.

- [x] **Emit AGENTS.md alongside CLAUDE.md per topic.** Shipped 0.9.29: identical generated content under both filenames, per topic and at the library root (Claude Code reads CLAUDE.md; Codex, Cursor, Gemini CLI and the 30+ tools on the cross-vendor standard read AGENTS.md). The same release fixed the index under-count that hid legacy-layout corpora (27 -> 35 topics on the dev library).
- [x] **One canonical SKILL.md.** Shipped 0.9.29: `skills/distill-corpus/SKILL.md` - one vendor-neutral file teaching an agent the corpus layout, receipt discipline, and CLI (preview-before-ingest, cost awareness). The "CLI + skill" distribution pattern, not the symlink-machinery model, which stays rejected.
- [~] **MCP surface consolidation (the §11 just-in-time item, promoted).** Mostly already real: `find_insights` returns ranked `(path, preview, score)` tuples with `read_insight(path, section?)` drill-down (paths-not-payloads is the shipped default), `generate_report` truncates at 5K chars, and `list_contested` is folded into `find_concepts(contested_only=True)`. The current code and MCP docs count 24 tools after later `ask`, summary, and concept-recovery additions. Remaining: continue collapsing overlapping action tools toward workflow shapes where it doesn't break the adapter contract's CLI-parity rule, and keep resources/prompts deprioritized (no evidence mainstream clients use either; they cost no tool-schema tokens, so removal is maintenance relief, not context relief).
- [x] **Positioning refresh.** Shipped across 0.9.28-0.9.29: README lead + "Where distill sits" (report/search layers vs the corpus layer; the loop is the moat, not the Markdown), "memory layer" language retired, samples labelled synthetic, reliability/trust-boundaries section added.
- [x] **Proof artifacts - the text slice.** The example corpus shipped in 0.9.29 (`examples/library/topics/claim-verification/` - real, labelled, $0.19 of analysis; full-text receipts omitted for arXiv licensing), and the README's labelled text samples link to it. **Screenshots/GIFs/terminal recordings are deliberately deferred to the 1.0 presentation pass** (product-owner call, 2026-06-11): capture them once the product is further built so the visuals show the finished thing, not a moving target. The text-first README is the interim stance.

Why this came first: it is the distribution channel for everything after it. The framing that matters is not "plain Markdown"; it is "the rigorous, verified corpus producer" that other agents can safely consume.

### 0.10.0 - Verified corpus: run-time verify + self-maintaining audit

The trust release. Anthropic's Agent SDK formalizes the agent loop as `gather context -> take action -> verify`; distillr does gather (discover) and act (analyze + synthesize) but nothing catches a hallucinated number, name, or date before it is committed to the library. Meanwhile the measured fact-check accuracy of deep-research agents is 39-77% - including the Gemini Deep Research reports distillr itself ingests. The golden-corpus eval gate in 1.0 is the *test-time* check; this milestone adds the *write-time* check, and packages the trust signals into one visible surface.

**Run-time verify hook.** *(Status: the deterministic tier is complete as of 0.10.1 - numeric/percent/money/year claims grounded against the source receipt on **every** analysis emit path (paper, video, site page, tweet, local file), `_Verify.json` sidecars, all three modes (`warn` default / `strict` refuses the write while keeping the receipt and sidecar / `off`), settable via `DISTILL_VERIFY` or `--verify` on `papers`/`discover`/`latest`. Shipped since: the local entailment-checker tier for prose claims (0.13.0) and **verify on every synthesis emit** (0.13.1 - paper/channel/topic/corpus/site, each grounded against its own inputs; the audit counts synthesis sidecars separately). Known limitation classes of the deterministic tier, named so nobody over-trusts it: derived arithmetic flags as unsupported (a "4.2-point gain" computed from 72.6 vs 68.4); support is presence, not context (a number attributed to the wrong metric passes); bare integers ≤3 digits - including sample sizes - are deliberately unchecked; prose claims carry no checkable tokens at all. The entailment tier exists to close exactly these.)*

- **Inline claim-grounding on every analysis emit** - for every `_Insights.md` write, post-process the structured output: extract each load-bearing claim (numbers, named products, dates, named people), ground it against the source artifact, flag unsupported claims in a `_verify.json` sidecar with the same identity stem.
- **Extract-then-check, with the check local and deterministic-first.** The 2026-settled architecture (RefChecker / Claimify-shaped): a regex/grep first cut for the easy cases ("this section claims a number; does the number appear in the source"), then a small local entailment checker scoring each (claim, source-chunk) pair - [Vectara HHEM-2.1-Open](https://huggingface.co/vectara/hallucination_evaluation_model) (110M params, Apache 2.0, CPU-feasible) as the default, IBM Granite Guardian via Ollama as the higher-accuracy option. Never an LLM-as-judge-of-record, per the invariants ("LLM proposes, Python decides"); the verifier deliberately does not share the analysis model's biases. Avoid NC-licensed checkers (Bespoke-MiniCheck).
- **Configurable severity** - `--verify warn` (default; surface to console, write anyway), `--verify strict` (refuse the write), `--verify off`. Deterministic verification layered on stochastic output - the Agent SDK "hooks" pattern. **This is a legitimate *structural* check, NOT brittle junk:** "is the cited number present in (or does it round from) the source?" is a ground-truth question the charter explicitly allows, and it correctly catches invented numbers. (Correction 2026-06-14: an earlier draft of this line called the numeric tier "advisory only / must not hold the strict veto" - an over-correction. Ripping out a legitimate structural gate for a narrow false-positive is itself a brittle over-reaction; not everything deterministic is brittle.) Its one real limitation, named honestly: it over-refuses *derived* numbers under `strict` (a "4.2-point gain" computed from 72.6 vs 68.4 is not literally in the source) and under-catches wrong-metric numbers. The right fix is **not** to weaken the structural floor but to layer context-aware grounding on top - exactly what the local **entailment tier** (shipped 0.13.0) does, and where this improves further. The numeric floor stays; making the regex do arbitrary arithmetic-derivation would be its own brittleness.
- **Run it over ingested Deep Research reports too** - that input stream has the measured weakness; grounding its load-bearing claims against the corpus receipts is the highest-leverage single application of the hook.
- **Dogfood corpus informing this design:** `library/topics/claim-verification/` (6 papers, ingested 2026-06-11 via goal-aware discover, ~$0.19). Key findings for the hook: claim decomposition measurably improves evidence matching (subquestions 59.6 vs 36.9 F1 on PolitiFact); a *domain-adapted* small NLI verifier approaches GPT-4o on grounding (Auto-GDA lifts DeBERTa 0.708 -> 0.878 ROC-AUC vs GPT-4o's 0.883) - so the off-the-shelf local checker is the floor, with Auto-GDA-style synthetic adaptation as the upgrade path; and numerical/comparison claims are the measured hard class (peak 47.33 Conflicting-class F1 on QuanTemp), which makes QuanTemp the natural eval fixture for exactly the numbers/dates/names claims this hook targets.

**Self-maintaining audit.** *(Shipped 0.10.2: `distill audit <topic|all>` composes the verify-sidecar rollup - clean / flagged / never-checked per insight, the panel's "visible trust moment" - with exact duplicate video identities, health warnings, contested concepts, broken links, and coverage gaps into a `<topic>_Audit.md` artifact; `--report-only` for unattended runs, interactive action menu otherwise, where only free deterministic actions execute and anything that spends prints its command instead. `health` remains the fast console view. Remaining: wire the scheduled cadence in 0.12 and an MCP `audit` read tool.)* Original spec - the Karpathy-pattern "monthly health check," composed from signals distill already produces:

- **`distill audit <topic|all>`** - one run bundling the three checks plus artifact-level stale-detection (reads the `prompt_id` / `model_version` floor when present, formalized in 0.12). Supersedes the console-only `health` output; `health` becomes the fast/no-report alias.
- **Corpus-wide contradictions map** - surface the cross-source disagreements synthesis already names and the contested-concept flags the playbook already tracks as a dedicated scannable section: which claims conflict, across which sources, still unresolved. Contradictions are strategic signal, not noise to smooth away - the failure mode a naive auto-wiki hits is resolving "engineering says 12 weeks, sales says 8" into a false "10."
- **One report artifact** - `<topic>_Audit.md` with standard frontmatter + provenance, so the audit is itself a corpus artifact agents can read. `--report-only` for scheduled runs.
- **Phase-2 action menu** - apply link/style fixes, draft stubs for suggested-but-missing concept notes, hand `research_gaps` next-actions to gap-driven `discover` so "you're thin on X" becomes "preview candidates for X."

Why this version: verify gates three later milestones - the audit's gap-filling branch, `ask --save` re-ingestion (0.12), and trustworthy source breadth (0.11) - so it must come before the funnel widens, not after. Trust is also where the competitive leaders are racing (contradiction detection, lint, draft-promotion), and a *verified* corpus is the one claim none of them can make: their trust features check structure; this checks claims against receipts. Audit lands beside it because verify is the substance and audit is the screenshot-able surface - together they are one legible "trustworthy corpus" story.

### 0.11.0 - Source breadth and audio capability

The three-source baseline (YouTube, websites, arXiv) was calibrated to "sources with public APIs and existing transcript layers." A validation run against two X posts revealed two simultaneous gaps: X itself was unsupported, and any source with audio but no native captions (X-native video, podcasts, conference talks, Loom, Vimeo) had no transcription path. Both shipped during the 0.9 validation work - they're now the foundation a focused breadth pass builds on.

**What the shipped 0.9 work left ready (do not re-design here):**

- `distill ingest <url>` thin dispatcher (routes by host to the right adapter; falls back to existing `distill site` / `distill latest` / `distill paper` for unknown hosts). Mirror of the local-file dispatcher 0.9 introduces for paths.
- X (Twitter) adapter via the public `cdn.syndication.twimg.com` embed endpoint - legitimate publisher path, not anti-bot evasion. Emits `Tweet.md` + `Transcript.txt` (when video attached) + `Insights.md` with standard frontmatter.
- Whisper transcription layer (`distill/ingestors/transcribe.py`) with **local-first provider routing**: `faster-whisper` on CUDA or CPU is the default, then a cloud ladder of xAI Grok STT (~$0.10/hr, reuses the existing `XAI_API_KEY`) before OpenAI Whisper-1 (~$0.36/hr) as the final fallback. Each cloud tier is skipped when its key is absent. Per-source `vocabulary_hint` derived from the source's own metadata (tweet text, author handle, paper title, page H1) biases proper-noun spelling (Whisper's `initial_prompt`, Grok STT's `keyterm`) - closes the "Claude Code → QuadCode" mistranscription class.
- `distill doctor` Transcription section: surfaces faster-whisper version, CUDA device count + supported compute types, cached Whisper models, and the routing line ("local-first → cloud fallback" vs. cloud-only vs. unavailable) so provider surprises are visible before a run.

**What this pass adds (the five-adapter set):**

- [x] **Podcasts** - shipped 0.11.1, RSS-first by design: `distill ingest <feed-url>` (auto-detected or `--rss`, `--episodes N`) parses the feed with the same defusedxml hygiene as the arXiv path, and the **transcript ladder prefers free text over paid audio** - a Podcasting-2.0 `<podcast:transcript>` is fetched (VTT/SRT normalized to plain text) before any enclosure download; only otherwise does audio route through the local-first Whisper ladder with a vocabulary hint derived from the episode's own metadata. Conversation-shaped insights (speaker-attributed claims, frameworks, quotes), verify-gated, audit-counted. Remaining for later slices: Parakeet TDT v3 as the optional English ASR fast path, pyannote diarization, and feed-level watch integration. Original spec: RSS is the *durable* path - the June 2026 research confirmed yt-dlp's YouTube route is degrading under PO-token/SABR enforcement, so audio breadth must not lean on it. Closes the largest single content surface for primary practitioner audio, and it is confirmed white space: no open-source tool does structured insight extraction from podcasts (the incumbents - Snipd, Podwise - are closed consumer apps). Reuses the transcribe.py provider routing wholesale; consider NVIDIA Parakeet TDT v3 as an optional English fast path (better WER than Whisper large-v3 at ~20x the throughput on the Open ASR Leaderboard) and pyannote community-1 for speaker diarization, with Whisper staying the multilingual default.
- [x] **GitHub repos** - shipped 0.11.0: `distill ingest <github-url>` captures metadata + README + recent releases via the public REST API (`GITHUB_TOKEN` optional, never required) into a `Repo.md` receipt + structured `_Insights.md` (what it is / maturity signals grounded in metadata / when to use / limits its own README admits), verify-gated like every other emit path and rolled into `distill audit`. **Extract insights, don't concatenate** held: every OSS repo tool (Repomix, Gitingest) stops at packing files into a prompt; structured repo *understanding* existed only in closed products (DeepWiki, Copilot Spaces). Remaining for a later slice: the structured issues/discussions subset, and lens threading.
- [x] **Generic audio/video files** - shipped 0.11.2: `distill ingest <path>` for eleven audio/video extensions routes through the local-first Whisper ladder with a filename-derived vocabulary hint and a "raw media" prompt that first establishes what kind of recording it is (talk, interview, meeting, memo) before extracting. Transcript is the receipt; verify-gated.
- [x] **Substack / newsletter posts** - shipped 0.11.2: feeds route by substance from one fetch - substantial `content:encoded` bodies mean newsletter-first *even when narration audio is attached* (the live-validation catch: a narrated Substack initially mis-routed to the podcast path and tried to transcribe its own narration). Full post HTML reduced to text (no page scraping needed), per-post `_Content.md` receipt + page-prompt insight, verify-gated.
- **X (already shipped in 0.9 validation)** - listed here for completeness; this pass hardens it with: tests, MCP `find_insights`-style read tool, optional thread expansion (fetch parent + reply chain), and consolidated cost/run tracking through the standard `CostTracker` / `RunSummary` plumbing.

**Adapter contract (enforced by reviewer checklist, not lint):**

Every new adapter must implement these five behaviors so it composes with the rest of the system:

1. **Capture as a deterministic function of public input** - given the same URL or path, the captured artifact bytes are reproducible (modulo upstream changes). No login walls, no captcha defeat, no scraping that breaks if the site adds anti-bot. The X adapter's syndication-endpoint approach is the reference shape.
2. **Emit conventional artifacts** - at minimum a raw artifact (`Tweet.md` / `Episode.md` / `Repo.md` / `Page.md` / `Paper.md`) and an `_Insights.md`, both via `write_markdown_artifact` with `base_frontmatter` + `ProvenanceFields`. No new directory layouts or filename schemes - file under `library/topics/<topic>/<source>/<identity>/`.
3. **Pass source metadata to downstream model calls** - Whisper transcription gets a `vocabulary_hint` derived from the source's own text; analysis prompts get author/title/date in their context. The pattern that fixed proper-noun mistranscription for tweets generalizes: the source knows what's in it.
4. **Cost-track through `CostTracker`** - every LLM and transcription call records to the run tracker with a meaningful `call_type`. No off-ledger spend.
5. **MCP tool parity** - every CLI ingest verb has a matching MCP tool that takes the same arguments and produces the same artifacts. Agents and humans see the same affordance.

**Calibration debt - the real risk of "more sources" and how this scope bounds it:**

The roadmap excludes additional cloud LLM providers (see "[intentionally not in scope](#intentionally-not-in-scope)") precisely because each provider is calibration debt - prompts that work well on one regress on another. The same logic applies to sources: a paper-style analysis prompt under-extracts on a podcast (different structure, different signal density, different listener stance). This pass caps the breadth at five adapters with the contract above so the 1.0 golden-corpus eval gate stays tractable. Further sources - LinkedIn, Bluesky, Mastodon, HackerNews, Reddit, Discord exports, Slack archives, slide decks - defer to the post-1.0 plugin system the roadmap already gestures at. The cap is deliberate; if a community contribution wants to add a sixth adapter, the contract above is the gate, not the version number.

Two additions ride along with the adapters:

- **YouTube-path resilience.** *(Shipped 0.12.11: caption fetch retries transient failures with backoff - the transient/permanent split is structural, an exception retries while a clean download with no `.vtt` file means captionless and stops; and captionless videos now route through the same local-first Whisper ladder every other audio source uses (bestaudio download, title/uploader vocabulary hint, spend on the tracker), with the legacy scribe path demoted to last resort.)* Original spec: The PO-token/SABR churn that makes RSS the right podcast default also threatens the core YouTube ingestion path. Retry/backoff/resume-friendly subtitle handling (roadmap §4) graduates from backlog to part of this pass: a breadth release that adds fragile sources while the flagship source degrades quietly would be net-negative.
- **Paper-metadata sources refresh.** Prefer OpenAlex (CC0, free dumps) and Ai2's Asta Scientific Corpus MCP over the classic Semantic Scholar API (changelog silent since late 2024, restrictive keys) for the recency/citation ranking signals in §6.

Why this comes after 0.10: the breadth pass needs the shipped 0.9 `distill ingest` dispatcher as a real entry point, and every new adapter's output now lands behind the verify hook - podcast transcripts and repo digests are noisier inputs than arXiv PDFs, so widening the funnel *after* the trust gate exists is the order that keeps the corpus trustworthy. 0.12's stale-detection + budget guardrails would likewise mis-fire if applied to half-built adapters. The Whisper layer + X adapter shipped in 0.9 are the cheap part; the four remaining adapters are the disciplined-execution part.

### 0.12.0 - Compounding corpus

The "leave it running" version: hands-off operation for a daily-driver research system, plus the output->input loop that makes the corpus compound with use. Everything here lands on top of a verify hook and audit surface that have been proven for two versions.

**Operational polish.**

- Scheduled refresh via cron / Task Scheduler - *(recipes shipped 0.12.1 in `docs/usage.md` "Running on a schedule": Task Scheduler + cron lines for `catch-up`, `audit all --report-only`, and gap-fill previews, honoring the boundary that distill is the loopable primitive and the scheduler stays external. Remaining: the goal-file refresh hook for `distill watch`.)* The same scheduler also runs `distill audit --report-only` on a cadence (the "monthly health check" automation), so corpus drift is caught without manual prompting and the audit report lands as a dated artifact.
- Semantic dedup across videos, pages, and papers (artifact-preserving - source-origin attribution stays in the synthesis layer).
- Stale-detection and auto-reanalysis triggers when prompts or models change materially. *(Detection shipped 0.12.2: the prompt-version registry (`distill/prompts/registry.py`) is the single source of truth all twenty prompt families stamp from AND the floor the audit compares against - the table cannot drift from the writers. `distill audit` now rolls up current / stale / no-provenance / unknown-family per topic, stale artifacts count as findings, and the report lists recorded-vs-current ids. Trigger shipped 0.12.6: the audit action menu prints per-artifact re-analysis commands resolved from each stale artifact's own frontmatter -- exact `ingest`/`papers` lines where the source routes, named fallbacks where it doesn't; spend printed, never auto-run. Synthesis stale-flag shipped 0.12.8: source-relative freshness (`distill/library/freshness.py`) compares each topic-level synthesis against the source subtree it actually synthesizes -- frontmatter-timestamped, tolerance-guarded, surfaced in the audit report, leading the dashboard health list, and as a warning line in the generated CLAUDE.md/AGENTS.md; shadowed legacy syntheses (a superseded `paper_synthesis.md` beside its modern replacement) are flagged too. Planned from a full review of the 53-topic dev library, which validated the design live: a real paper synthesis predating five later-ingested papers, and a real shadowed-legacy pair.)* **Artifact-level, not blanket.** Each artifact's frontmatter already records `prompt_id` and `model_version` (since 0.7); stale-detection inverts that index and re-analyzes only the artifacts on the critical path of the changed component. Blanket re-runs on every prompt bump don't scale once the corpus passes a few hundred artifacts. **Staleness is surfaced, not just acted on silently:** a stale synthesis is more dangerous than stale source data because it reads with the confidence of well-written prose while being wrong (the "confident misinformation" failure mode), so a stale flag rides the synthesis frontmatter and the dashboard rather than living only in a `distill health` console run.
- Cost anomaly detection and budget guardrails per topic and workflow.
- **MCP write-side gating** - *(read-only mode shipped 0.12.1: `DISTILL_MCP_READ_ONLY=1` gates all twelve spend/ingest/mutation tools behind a signature-preserving decorator that refuses before any body executes, with the read surface untouched; "read-only MCP, CLI ingest by a named operator" documented as the recommended agent-facing posture. Per-call spend caps + ingest-domain allowlist shipped 0.12.9: `DISTILL_MCP_MAX_SPEND_PER_CALL` enforces on *actual recorded spend* via a budget on the run tracker -- the crossing call stays on the ledger, then the run stops with a structured response, no off-ledger spend ever -- and `DISTILL_MCP_INGEST_ALLOWLIST` confines the URL-taking ingest tools to operator-approved hosts and subdomains.)* Original finding (June 2026 panel, enterprise architect): spend-and-ingest tools callable by any connected agent are budget-burn and corpus-poisoning surface.
- **Estimator accuracy as the goal, not padding.** The pre-run estimate is judged on calibration - expected value close to actual, with an honest low/high range - not on erring safely high. A padded estimate is still a wrong estimate: it discourages runs the user would happily pay for, exactly as an undershoot surprises them (the 0.10 dogfood run estimated $0.26 against $0.19 actual - fine for one run, but the bias should shrink as `cost_log.jsonl` history accrues). Surface estimate-vs-actual error per workflow in `distill costs` so calibration drift is visible and the self-calibration loop is accountable to a number.
- **Per-call prompt telemetry.** Every router call writes prompt-input tokens, output tokens, elapsed time, provider, workload, call type, run id, and outcome to `library/.distill/telemetry.jsonl`, and `distill costs` plus the local web costs page expose the biggest prompts so context-budget regressions are visible.
- Live per-item progress plus resume-friendly failure handling for long mixed-source runs, so transcript-rate limits or slow site ingestion are visible without manual filesystem inspection. *(Shipped 0.12.10: per-item `[i/N]` progress already existed on every loop; the missing half was failure isolation -- one crashed paper/site/video now records a structured run issue and the loop continues, synthesis still covers what landed, and the summary prints the resume hint ("re-run the same command -- already-ingested sources skip", which is true because re-runs are convergent). The spend cap stays a hard stop through these catches. The dogfood library carried the scar of the old behavior: a topic with five papers newer than its last synthesis, from a run that died mid-loop.)*
- **Dev-library review findings (2026-06-12, from auditing all 53 real topics).** Two items graduated to named 0.12.x margins, both now shipped: the **library-level hygiene rollup** *(shipped 0.12.12: `distill audit all` ends with a library-wide view -- empty topic directories listed as safe to delete, unreadable reparse points, sources-but-no-orientation topics with the regen command, and test/validation-suggesting names listed informationally -- written to `Library_Audit.md` at the library root plus a one-line console rollup; validated live: 46 healthy / 7 empty / 11 test-named on the dev library, matching the review)*, and **orientation-emission completeness as a contract** -- every emit path that writes artifacts must leave the topic agent-visible (the 0.12.8 paper-path fix is the worked example; the reviewer checklist now asks it of every new adapter). Parked deliberately, not forgotten: cross-topic program grouping (eight sibling `kilo-*` topics with zero cross-references read as one invisible research program -- `distill synthesize` already covers the multi-topic synthesis need, and a grouping surface is a post-0.12 design question), and a media-size note in the audit (one topic carried 80 MB of source video beside 15 KB of text).

**Output->input loop (`distill ask`).** *(Shipped 0.12.0 - design in [`docs/design/ask-loop.md`](docs/design/ask-loop.md); grounded-only answers with `[[wiki-link]]` citations, verify sidecars on every answer, and strict-by-definition promotion: `--save` refuses any answer with an unsupported load-bearing claim or a no-coverage body. MCP `ask` tool ships read-only; promotion stays CLI-only until MCP write-gating. Validated live: the claim-verification corpus answered the entailment-tier design question and the verified answer became the corpus's first derived insight, picked up by `distill audit` automatically.)* Original spec:

This is the mechanic the Karpathy "LLM Wiki" pattern is built around and the one half of the loop distillr does not yet have: you ask the corpus a question, you like the answer, and the answer *becomes corpus* so the next question starts from a richer base. Today distillr is excellent at `input -> corpus` (capture, analyze, synthesize) but every output (`report`, `research-brief`, `synthesize`) is a **terminal artifact** - nothing re-ingests it, and there is no lightweight query verb at all. The compounding "day 1 basic, day 100 an asset" behavior the pattern promises depends entirely on closing this loop.

- **`distill ask "<question>" --topic <t>`** - query the corpus (reuse the `find_insights` retrieval path), answer grounded only in the topic's artifacts, and write a provenance-stamped answer to an answers layer (`library/topics/<t>/answers/<slug>_Answer.md`, standard frontmatter, `[[backlinks]]` to every cited source). MCP parity: an `ask` tool with the same arguments.
- **Optional re-ingest** - `--save` (or a prompt) promotes a liked answer into the corpus so synthesis and future answers can build on it. This is the compounding step.
- **Gated on the 0.10 verify hook - this is non-negotiable.** The exact failure mode this risks: "the AI writes something slightly wrong, you save it back, and the next answer quietly builds on a mistake." Re-ingest therefore runs the run-time verify hook on the answer first; an answer with an unsupported load-bearing claim is refused (or flagged and quarantined under `--verify warn`) rather than silently folded in. The verify hook is *why* this loop is safe in distillr and unsafe in the unguarded folder-and-CLAUDE.md version. It is also why this lands two versions after the hook and audit shipped - the trust surfaces exist and have been exercised before outputs start feeding back in.

**Sub-agent-friendly MCP surface.** *(Shipped 0.12.5: `find_insights_summary(topic, query, max_tokens)` -- lexical-rank slice, one query-focused compression call, **cached by corpus revision** (path+mtime+size hash of the matched slice, so repeats are free until the corpus actually changes -- validated live: $0.022 first call over 7 sources, $0.000 second); spend-gated under read-only mode. Plus `list_topic_summary(topic)`, free and deterministic, for sub-agents choosing where to query. 24 MCP tools total.)* Original spec:

Today's `find_insights(topic, query)` returns full artifact bodies. For a 50-paper corpus, an agent that queries this blows past most context windows. The Agent SDK's sub-agent pattern (delegate "do X over Y, here's bounded context, return result") needs a token-bounded query primitive:

- **`find_insights_summary(topic, query, max_tokens=4000)`** - same query, returns a synthesis sized to fit a sub-agent's context. Implementation: existing `find_insights` plus a one-shot LLM compression pass over the matching slice with the query as the focus. Cached by `(topic, query, max_tokens, corpus_revision)` so repeated sub-agent calls don't repay the compression cost.
- **`list_topic_summary(topic)`** - paragraph-length topic overview pulled from the topic synthesis frontmatter, used when a sub-agent is choosing which topic to query.

Why this version: stale-detection and semantic dedup need stable artifact identity and provenance (0.7 + 0.8), the ask loop needs the 0.10 verify hook and audit, and the sub-agent MCP tools depend on the 0.9 two-pass synthesis claim intermediate (so the summary pass has structured inputs rather than re-extracting from prose) plus the consolidated paths-not-payloads surface from the agent-legible pass. 0.12 is where everything underneath compounds.

### Engineering legibility + CLI-UX (0.13 onward)

The releases between the named milestones and 1.0. Two strands run in parallel, both serving the same end: a corpus *and* a codebase that the dominant reader - an agent - can consume without a human, and that a human can drive without friction.

**Trust and agent-readiness (shipped, 0.13-0.16).** The entailment tier and verify-on-every-synthesis closed the last 0.10 verify items (0.13); agent-grade `--json` with a strict stdout/stderr split made the read surface loopable (0.14); `distill update` made the tool self-upgrading (0.15); and the blocking golden-corpus eval gate froze what good extraction looks like so prompt drift can't pass silently (0.16). Detail in [`docs/CHANGELOG.md`](docs/CHANGELOG.md).

**Codebase legibility - `_logic.py` monolith removal (complete).** The ROADMAP's "one command group per file" target was violated by a single 9k-line module that no agent could hold in context. This earned the feature spine, not a harden pass, because *agent-context-fit is legibility for the dominant reader*. The work landed as many small, green, pure-relocation PRs, each moving one command group into `distill/commands/<group>.py` or a focused helper owner and lowering a must-only-decrease module-size ratchet. The root callback, concepts app construction, discover/learning/topic-change bridges, and private compatibility exports have all moved to owned modules or `distill._cli_impl`; `distill/commands/_logic.py` is deleted, no production command module imports it, no command sub-apps remain there, and the module-size allowlist is empty. The load-bearing stale-patch hazard is handled by the documented repoint-in-the-same-PR rule and grep gate. Design and procedure: [`docs/design/logic-decomposition.md`](docs/design/logic-decomposition.md); operating model: [`docs/design/how-we-build.md`](docs/design/how-we-build.md).

**Human + agent CLI-UX.** Aligned to current CLI best practice (clig.dev-era): a guided, no-TTY-safe `distill init` (creates `.env`, validates the key, installs the browser, ends on a ready/not-ready verdict), did-you-mean on mistyped commands, a machine-readable `doctor` readiness verdict, global `--quiet` / `--verbose` output controls, and recurring-workflow `--help` examples have landed. Status: `papers`, `site-batch`, `latest`, `catch-up`, `discover`, and default `report` now print phase or item progress, completed counts, failed counts, spend, and ETA when available.

Why this run is its own thing rather than folded into 1.0: it is the order of operations that makes 1.0 reachable. 1.0 is a *stability and quality* claim (frozen contracts, ≥95% coverage, the full Pyright-strict and parse-don't-validate bar); you cannot credibly freeze contracts on a 9k-line module no reviewer can audit, and the CLI-UX surface should settle before the CLI flags are versioned and frozen.

### 0.17.0 - OKF interop + loop-ready stewardship surface

OKF is the new interchange target for agent-readable knowledge, and loop engineering is the new consumption pattern. Distill should serve both without becoming a generic wiki maintainer or scheduler.

**OKF producer and validator.**

- **Read-only export first.** `distill export <topic|all> --format okf` writes a conformant bundle under `output/` or a user-specified path. It maps distill artifacts into OKF concept documents with `type`, `title`, `description`, `resource`, `tags`, and `timestamp`, plus `# Citations` sections derived from source URLs, receipts, and verify sidecars. The native `library/` layout remains the source of truth.
- **Validation before mutation.** `distill okf validate <path>` checks OKF conformance: every non-reserved `.md` has parseable YAML frontmatter and non-empty `type`; `index.md` and `log.md` are structurally valid when present; broken links are warnings, not failures, matching the spec's permissive consumer model.
- **Progressive disclosure.** Exported `index.md` files summarize child concepts and subdirectories so agents can inspect the bundle before opening individual files. `log.md` is synthesized from run history and audit events, not hand-authored.
- **Optional discovery pointer.** A generated `llms.txt` pointer is allowed for hosted/exported OKF bundles, but only as a pointer. Agents must still start from `index.md`, AGENTS.md/CLAUDE.md, MCP, or files.

**Loop-ready stewardship surface.**

- **Next-action plan shipped.** `distill audit <topic|all> --next-actions --json` emits a bounded plan from existing deterministic findings: broken links, missing orientation, stale artifacts with routable sources, stale syntheses, coverage gaps, missing corpus synthesis, missing diffs, and missing trend summaries. Each action carries an id, rationale, exact command, cost class, approval level, write scope, loop metadata, and verifier/stop condition.
- **No autonomous execution inside distill.** The plan is data for Codex, Claude Code, cron, GitHub Actions, or a human operator. Distill does not add a scheduler, worker pool, or PR bot.
- **Verification is the stop condition.** A loop is done when the command exits cleanly and the relevant audit/verify signal turns green, not when a model declares success.
- **Loop admission metadata.** A next-action row that is meant for repeated execution names its state path, max attempts, verifier, approval class, and acceptance metric. If Distill cannot name those, it emits an operator note rather than a loop action.
- **Budget and safety are first-class fields.** Actions expose spend estimates, read/write class, ingest domains, and whether `DISTILL_MCP_READ_ONLY`, `DISTILL_MCP_MAX_SPEND_PER_CALL`, or allowlists would block them.

Why this comes before 1.0: it is an additive compatibility layer over shipped artifacts and a contract for external loops. It should settle before the library/frontmatter contracts freeze.

### 0.18.0 - Batch-run visibility

This closes the last codebase-legibility and human-loopability gap before 1.0.

- **`_logic.py` removal shipped.** The remaining compatibility bridge now lives in `distill._cli_impl`, the facade module is deleted, and call sites plus patch strings point at canonical owners.
- **Batch progress and running cost.** Status: `papers`, `site-batch`, `discover` paper/site ingestion, and default `report` now print phase/item/completed/failed/spend output, with ETA after enough items complete. Video-backed loops used by `latest`, `catch-up`, and `discover` video ingestion print persistent per-video completed/failed/spend progress after each item and include spend in live phase labels. `site-batch` and `discover` site ingestion isolate seed-level exceptions as `site-ingest` issues and continue. Global `--quiet` suppresses human console output for external loops, `--verbose` mirrors DEBUG logs to stderr, `library/.distill/distill.log` captures DEBUG logs for post-run review, and `--json` stdout purity stays intact.
- **Verbosity dial.** Add consistent `-q` / `-v` behavior before the CLI contract freezes.
- **Help examples.** Shipped: `--help` examples now cover recurring workflow preview, approved profile runs, discovery preview/commit, single-target ingest, audit next-action plans, OKF export, and OKF validation.

### 0.19.0 - Recurring research profiles + no-metered-cost routing

This is the daily-driver pass for the "I keep seeing this topic evolve" workflow. A user should be able to track topics like "AI developer news", "live agentic dev", or "agentic coding loops" with a saved profile, then refresh it cheaply and safely.

**Recurring research profiles.**

- **First-class profiles.** Add a profile file that binds a topic, goal, preferred YouTube channels, trusted domains, newsletter/feed URLs, search phrases, source limits, rigor, and default output actions. Substack-class feeds are the durable path for sources such as Latent Space because Distill can ingest full post text from feeds today. It is a durable artifact an external loop can read and rerun.
- **Preview remains the default commit boundary.** Profile refreshes surface new candidates and cost before ingest unless `--yes` is explicitly set by a trusted operator or external loop. Preview resolution is deterministic for fetch, parse, freshness, identity, caps, and no-metered refusal; semantic priority belongs to a model route. If no eligible no-metered model route exists, preview shows labeled structural order rather than a fake keyword quality rank.
- **Profile health in audit.** `distill audit` reports whether a profile has gone stale, whether its feeds/channels/domains still resolve, and whether the corpus is thin relative to its own profile.
- **Examples.** Ship checked-in examples for "AI developer news", "agentic coding", and "vendor docs watch" using public sources, high-signal newsletter feeds, and preview-only commands.

**No-metered-cost routing.**

- **Name it precisely.** This is no-incremental-metered-cost mode: local hardware as sunk-cost compute, or included subscription / plan-quota usage, with no API-billed calls unless the user opts in. It is not a claim that compute, electricity, quota, or rate limits do not exist.
- **Cost policy.** Add `DISTILL_COST_MODE=auto|no-metered|paid-ok` plus CLI `--cost-mode`. In `no-metered`, distill refuses paid API calls and prints the provider/workload that would have spent money.
- **Fresh sources still apply.** Local Ollama/LM Studio routes change the model that analyzes captured receipts; they do not make Distill answer from stale model memory. Discovery and ingest still fetch current sources first.
- **Local first for fan-out.** Ollama/LM Studio remain the preferred no-metered route when `distill eval` says quality clears the workload bar, especially for high-volume candidate triage, cross-topic clustering, draft summaries, and repeated refresh passes.
- **Plan-quota adapters are explicit.** Codex CLI, Claude Code, Grok Build, Gemini CLI, Antigravity, and similar tools are only used when the user has configured them and the adapter can prove it is using plan credentials rather than an API key. Terms, quotas, and headless support are provider-specific and may change, so failures degrade to a clear message. GitHub Copilot CLI is treated as credit-metered unless a future support statement proves no incremental cost.
- **Plan quota is for bounded high-judgment work.** Included quota routes are useful for bursty cross-topic research, reviewer passes, synthesis planning, contradiction interpretation, and agentic fan-out where local models are too weak or too slow but API billing is not acceptable.
- **CLI adapters are external workers, not hidden providers.** Codex starts with `codex exec --json` under `read-only` or `workspace-write` sandboxing. Claude Code starts with print mode for narrow experiments and graduates to the Agent SDK when Distill needs structured production streams. Grok Build starts with headless JSON or streaming JSON output, then ACP for app integration. All three write only a scratch result manifest; Distill performs verification, ledger recording, and final corpus writes. The command matrix and June 2026 flag guidance live in [`docs/design/cli-adapter-runbook.md`](docs/design/cli-adapter-runbook.md).
- **No-metered proof fails closed.** Local inference is no-metered by topology. Plan-quota usage is no-metered only when preflight can show a subscription/session route rather than an API key or purchased credits. `ANTHROPIC_API_KEY`, `XAI_API_KEY`, or an OpenAI API-key route blocks plan-quota claims unless the user selected `paid-ok`.
- **Safety posture is adapter-specific.** Codex avoids `danger-full-access`; Grok scripts use `--no-auto-update` and reserve `--always-approve` for isolated scratch workspaces; Claude settings deny `.env`, secrets, and unexpected writes. Every adapter has timeouts, output limits, and structured stop reasons.
- **Eval gate.** A plan-quota route graduates only when it passes `distill eval` for the workload. Cheap unusable output is not a route.
- **Judge local against quota routes.** `distill eval` compares local output, plan-quota CLI output, and metered API output on the same fixtures using an LLM-as-judge rubric over receipts: faithfulness, specificity, citation use, synthesis quality, and actionability. The recommended route is the cheapest no-incremental-metered-cost route that clears the quality bar.
- **Cost per accepted change.** Cross-route eval records attempts, accepted outputs, rejected or quarantined outputs, elapsed time, usage, and verifier failures. A route with zero dollar spend but a low acceptance rate does not become the default.
- **Ledger still records usage.** Even if dollars are zero, runs log provider, route, estimated tokens or available usage signal, elapsed time, and any quota/rate-limit stop.

**Planned 0.19.x order.**

- **0.19.0 profile artifacts and preview.** Ship schema, examples, validation, and preview-only candidate discovery for AI developer news, live agentic dev, and vendor docs watch. Candidate fetch and normalization are rule-owned; source fit, novelty, rumor classification, and priority are model-judged or explicitly marked unranked.
- **0.19.1 cost policy and local routes.** Wire `auto`, `no-metered`, and `paid-ok` through the router, ledger, Ollama, LM Studio, and deterministic fetch/transcript paths. Status: config/router parsing, top-level CLI override, no-metered profile replay commands, approval-gated profile run execution, zero-dollar route/provider ledger rows, fail-closed route refusal, and structured blocked-route reporting are wired; `no-metered` allows local Ollama/LM Studio and blocks API-billed, credit-metered, unproven plan-quota, or ambiguous routes before provider calls. Local routes are labeled as sunk-cost compute and zero-dollar usage is recorded.
- **0.19.2 adapter doctor.** Add read-only preflight checks for Codex CLI, Claude Code, Grok Build, Gemini CLI, and Antigravity: installed version, auth mode, blocked API-key state, headless support, machine-readable output support, and support-statement version. Status: `distill doctor --adapters` reports binary presence, version/help probes, required structured-output flags, API-key environment blockers, local config API-key markers, selected JSON auth-command markers, route class, support-statement status, structured support details, and strict `adapter-workload.v1`, `adapter-native-usage.v1`, and `adapter-result.v1` scratch contracts. Support details record checked date, source URLs, required evidence, notes, and whether the statement is current for no-metered routing. The manifest boundary rejects missing usage signals, unsafe scratch paths, missing declared files, unexpected new scratch files, no-metered results with metered auth or API-key blockers, and quota or rate-limit stops without structured `quota_stop` metadata. A scratch-only exact-argv runner primitive exists with shell disabled, timeout handling, API-key env stripping, manifest loading, and scratch write checks. A workload runner now invokes optional post-process capture hooks before verifying manifest reads, writes, and cost mode against a checked workload package. A native result writer turns captured CLI output plus explicit native usage metadata or a validated native usage file into validated scratch manifests, Codex and Claude capture writers can convert captured CLI JSON into that scratch manifest shape, and a generic stdout capture writer can write `result.txt` before manifest validation when a real native usage file exists. A ledger helper converts verified manifests into included-plan usage rows and metadata. Blocked Codex, Claude, Grok, Gemini, and Antigravity read-only command planners record future argv shapes plus staged prompt, schema, result capture, and native usage capture metadata, and Claude schema paths can be inlined from scratch JSON schema files. Gemini and Antigravity fail closed on `GOOGLE_API_KEY` as well as `GEMINI_API_KEY`. Remaining: current official no-metered support statements, installed-session auth proof where no command or config proof exists, native usage collection and capture wiring for Grok, Gemini, and Antigravity, and eval graduation. Report Copilot separately as a credit-metered CLI candidate under explicit paid policy.
- **0.19.3 cross-route quality eval.** Add fixture comparisons for local sunk-cost routes, plan-quota CLI routes, and metered API routes. Use LLM-as-judge scoring over receipts plus cost-per-accepted-change accounting so fan-out routing is based on output quality and retained work, not just availability.
- **0.19.4 read-only CLI adapter prototypes.** Add eval-gated read-only adapter workloads first: profile enrichment, corpus Q&A, candidate classification, and synthesis planning. No corpus writes from adapter processes.
- **0.19.5 profile run and loop handoff.** Status: `distill profile run <name>` emits JSON plans, requires `--yes` to execute, records per-command outcomes, persists resume state, emits profile-related next-action rows compatible with the audit action schema, and surfaces local profile health in `distill audit all` so cron, GitHub Actions, Codex, Claude Code, Grok Build, Gemini CLI, Antigravity, or a human operator can steward the profile without scraping console text.

Why this comes before 1.0: recurring profiles and cost policy are user-facing contracts. If they are going to exist, they should settle before CLI flags and config semantics freeze.

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
- **Parse, don't validate - strict domain types at every boundary.** Every external input (MCP tool arguments, frontmatter parsing, local-file/adapter ingest, LLM structured outputs) is *parsed once* at the system boundary into a rich domain type (a Pydantic v2 model with `strict=True, extra='forbid'`, a `NewType`, or a frozen dataclass), not re-validated ad hoc deeper in. Core logic never receives raw primitives that could be invalid - illegal states are made unrepresentable, so malformed input fails at the boundary with a precise error instead of propagating. Reinforces the verifiable-corpus thesis: the corpus is only as trustworthy as the parsing on what enters it.
- **Ruff** zero-warning under the project config, blocking. Cyclomatic complexity (`C901`) capped; `# noqa` requires an inline justification. Security rules (`S` / bandit) consolidated into the single ruff pass where practical.
- **Bandit + pip-audit** blocking in CI (both promoted in 0.8.3). Dependencies pinned via the committed `uv.lock`; CI installs with `uv sync --frozen` so the tested environment is the locked environment, a CycloneDX SBOM ships with each release, and PyPI publishing emits PEP 740 build-provenance attestations over the existing OIDC trusted-publishing channel (no stored credentials) so the chain from a reviewed `main` commit to the installed wheel is cryptographically verifiable.
- **import-linter** dependency-direction contracts blocking in CI (promoted in 0.8.3), so the layered architecture in [Target package layout](#target-package-layout-10) is enforced, not just documented.
- **Python 3.12-3.14 support matrix**, every version green on every PR. `requires-python = ">=3.12"`; the floor moves forward as old versions reach EOL, the ceiling tracks the current stable release.
- **OS support matrix: Linux, macOS, and Windows are all first-class.** Shipped 2026-06-11: CI now runs the unit suite + CLI smoke on `macos-latest` and `windows-latest` (Python 3.12) alongside the full coverage-gated 3.12-3.14 matrix on ubuntu, so path handling, console rendering, and subprocess behavior are enforced on every platform users actually run - development happens on Windows, and before this the CI was ubuntu-only. 1.0 may widen the smoke jobs toward the full version matrix. This tool has to work for anyone, on whatever box they have - including local models on consumer GPUs.
- **No silent error swallowing.** Every `except` either re-raises or logs-then-raises. Audited and lint-rule-enforced where ruff supports it.
- **Golden corpus eval gate - STRUCTURAL offline gate; quality lives in `distill eval`, not CI.** Two things that must stay separate (the charter, [`docs/design/agentic-balance.md`](docs/design/agentic-balance.md)):
  - **The offline CI gate is structural and deterministic, and stays that way.** It runs with no API keys, so it *cannot* judge quality with a model. What it legitimately freezes (as `test_golden_gate.py` already does today): scorer **discrimination** (the hand-written golden scores high, a deliberately-degraded output scores low - proving the scorer isn't a rubber stamp), fixture↔golden **sync**, and prompt-builder **wiring** (the real per-workload prompts assemble with a mock LLM). Using the deterministic composite *here* is fine because it scores **fixed, hand-written goldens we control** to test discrimination - it does **not** score live model output. The hard rule: **never extend this gate to score *live* model output against composite floors** - that is the brittle trap (it would punish paraphrase and reward keyword-stuffing, gating every prompt change on a regex). The ~20-fixture scale-up grows the *fixtures*, not the gate's job.
  - **Live-output quality is judged by `distill eval`'s model judges** (faithfulness + coverage against the source), run on-demand against a real model. That is the only place a quality judgment belongs, and it is model-judged, not a deterministic score. It is not, and cannot be, an offline CI gate.
  - Still ahead: a structural golden for the concept-playbook pipeline (threshold/polarity discrimination, same shape), the ~20-fixture scale-up, an `eval_models` MCP tool. (Correction 2026-06-14: an earlier draft of this line wrongly called for a "model-judged offline gate" - impossible without keys in CI, and unnecessary since the gate is structural and live quality is `distill eval`'s job.)
- **Metamorphic robustness pass - CUT as fake-rigor (do not build).** The previous plan here (METAL templates; `SynonymReplacement` / `L33TChanging` perturbations; a Universal-Sentence-Encoder cosine ≥ 0.6 acceptance gate; kappa floors; ~30 variants) is **removed.** It perturbed surface tokens and asserted concept-set stability against cosine-similarity thresholds - measuring surface-token stability and calling it semantic robustness. That is a pile of deterministic thresholds dressed as science, the exact brittle-proxy pattern the charter ([`docs/design/agentic-balance.md`](docs/design/agentic-balance.md)) forbids, and as a CI gate it would block legitimate prompt changes on cosine numbers. If robustness-to-rephrasing ever genuinely needs testing, it is a **model judgment** ("do these equivalent inputs yield the same substantive concepts?"), not a cosine gate - and it earns its place only by `distill eval` showing it catches real regressions, not by citing a framework. Do not build the cosine/perturbation machinery.
- **Pre-commit hooks identical to CI checks** - no contributor surprises between local and remote.

**Verification depth (where it matters, not everywhere).**

The gates above prove *coverage* and *types*. These prove the tests and the code are actually correct under adversarial conditions. They are scoped to the layers where correctness is load-bearing - the deterministic pure-Python core (`concepts/` merge + normalize + recovery, `library/` slugs + frontmatter + links, evidence-interval arithmetic) and the external-service boundaries - not blanket across presentation code, because that is where the cost/value trade-off actually lands.

- **Design by Contract on the deterministic core.** Encode the merge/normalize/recovery invariants as executable pre/postconditions and class invariants (via the `deal` library, which also generates Hypothesis tests directly from the contracts) - for example: merge is idempotent and order-independent, a rollback's rebuilt rollup row round-trips the restored frontmatter, evidence intervals never invert. Contracts run in dev and CI and can be optimized out (`python -O`) where overhead matters. Applied to the same pure-Python layer the property tests already target, so the two compound rather than overlap.
- **Mutation testing on the core packages.** A periodic `mutmut` (or equivalent) pass injects artificial regressions into `concepts/`, `library/`, and `llm/retry` and asserts the test suite catches them - proving the suite's *efficacy*, not just its coverage percentage. Scoped to the core (mutation testing is too slow to run blanket on 14.5k lines) and run on a cadence, not every PR. Complements the structural golden-corpus gate and model-judged `distill eval`: those catch prompt and output drift, this catches dead tests.
- **Stateful property testing of the playbook lifecycle.** A Hypothesis state machine models the concept layer's real lifecycle - append mentions to `mentions.jsonl`, merge, write notes, snapshot to `.history/`, roll back, re-merge - and asserts the invariants hold across arbitrary operation orderings. This is the class of bug (ordering, accumulation, rollback-after-merge) that single-shot example tests miss.
- **Fault-injection at the external boundaries.** Deterministic tests that inject malformed LLM JSON, truncated/empty transcripts, network timeouts, and yt-dlp failures, asserting the pipeline degrades cleanly (resume-friendly, no half-written artifacts) and that the "no silent error swallowing" rule actually holds under turbulence - verified, not assumed. distillr's concurrency is asyncio IO, so the discipline that matters is async-safety (no blocking calls in async paths, correct cancellation), not the shared-memory thread-safety a free-threaded service would need.

**Polish.**

- Repo presentation pass: README screenshots/gifs (terminal dashboard, sample report, web UI, library in Obsidian), GitHub repo description and topics, and contributor onboarding that gets a new contributor from clone to a verified first contribution path.
- All public APIs documented (concise docstrings on the public surface; longer where the rationale isn't obvious from naming).
- `docs/CONTRIBUTING.md` covers the full quality posture above so contributors know the bar before they open a PR.

Why this version: 1.0 is a stability *and* quality claim. It's the version external systems can build on without expecting churn, and the version a new contributor can land a clean PR in without a long onboarding tail. Competitively, the agent-integration story now ships much earlier (the agent-legible 0.9 pass); 1.0's job is the presentation pass, onboarding docs, and stable contracts that convert "technically superior" into "actually adopted" - and by this point the story writes itself: verified, agent-legible, multi-source, user-owned.

## Looking beyond 1.0

Not committed. Notes on directions worth thinking about once 1.0 stability is in place.

- **Shareable goal-files / topic recipes.** A `discover` goal-file is already an executable description of a corpus - the same "idea file as a prompt you hand an agent" format Karpathy's gist popularized. The direction is making goal-files portable artifacts: publish or share a goal-file (with its `--site-seeds`) so someone else can reproduce or refresh a corpus from the research *intent*, not just receive the output. Plain Markdown like everything else, no lock-in, and it fits the post-1.0 plugin-boundary timing rather than the critical path.

- **Provider breadth + plan-quota compute on an eval-gated adapter contract (committed).** The `distill/llm` router already abstracts provider+model behind workload tags, and the provider directory is further along than the pitch admits: grok, gemini, ollama, and lmstudio are calibrated/wired today, **anthropic and openai adapters already exist in-tree** (wireable, not yet calibrated defaults), and an `AgentProvider` already does deferred zero-cost execution via task files an external agent (Claude Code, Kiro) picks up. The committed post-1.0 work has three strands, all behind the same gate:

  - **Cloud API adapters**: complete the set - xAI, Google, Anthropic, OpenAI (calibrate the existing in-tree adapters), then AWS Bedrock and Microsoft Foundry (new) - so users on enterprise clouds run distill against the endpoints they are provisioned for. A default still ships (one calibrated cloud route + the local route); everything else is opt-in.
  - **Plan-quota compute (the "you're already paying for it" class).** Many users carry subscription plans with generous quotas - Claude (Pro/Max), OpenAI Codex, Gemini/Antigravity, Grok plans, OpenCode, Kiro - plus local hardware. Routing batch analysis through the **agent CLIs those plans license** (headless invocations, or the shipped `AgentProvider` task-file pattern when direct invocation isn't permitted) makes marginal ingestion cost approach zero for people already paying a flat fee. Two hard caveats are part of the design, not afterthoughts: (a) **plan terms and headless-automation policies churn** - vendors change what subscriptions permit for programmatic CLI use, so each harness adapter ships with a documented support statement and degrades to a clean message, never silent breakage or ToS-violating workarounds; (b) **"free" is not "usable"** - a plan-quota or local model graduates only by clearing `distill eval`'s cost x quality bar on the golden fixtures, exactly like any other backend. Plan-quota runs still record token volumes to the cost ledger (the no-off-ledger-spend invariant covers usage, not just dollars).
  - **The gate**: `distill eval` decides everything. A backend goes from "wireable" to "calibrated and eval-recommended" only by clearing the bar, and the same harness produces the cross-provider, cost-aware comparison that says which backend to use for which workload - and whether a plan-quota or local model now beats the cloud floor. Distillr ships no uncalibrated default, so breadth is added *without* abandoning the no-calibration-debt discipline (see [Intentionally not in scope](#intentionally-not-in-scope)). The eval gate is the thing that pays the calibration debt down cheaply instead of guessing.

- **Semantic alias resolution over `mentions.jsonl`.** 0.8's normalize layer canonicalizes mention names mechanically (case-folding, plural stripping, punctuation cleanup). That handles the easy cases. The hard cases - "rotational embeddings" / "rotation embedding" / "phase rotation" being three names for the same concept; "DeepMind" / "Google DeepMind" being one org; or, more painfully, two papers in the same field using entirely disjoint vocabularies ("SciBERT" + "BiLSTM-CRF" vs "SciEvent" + "Agent-Action-Object triples") - are out of reach of regex.

  *Architecture, grounded in the cross-document event coreference literature:* two paradigms are validated and complementary. (a) **Symbolic compression**: assign each mention a structured identifier from its arguments - borrowing X-AMR's PropBank-style roleset + ARG-0 (Agent) / ARG-1 (Patient) / ARG-Loc / ARG-Time decomposition - then cluster via connected components on identifier match. Linear in corpus size; falls back to mechanical canonicalization when arguments are missing. (b) **Semantic compression**: generate a short LLM elaboration per mention (1-2 sentences expanding what the mention refers to), then run small-model pairwise scoring + clustering on the elaborations. The 2406.02148 / 2404.08656 papers found these two paradigms have complementary failure modes - symbolic misses paraphrase, semantic misses precise argument structure - and that a staged pipeline (symbolic bucketing first, LLM elaboration for ambiguous clusters) outperforms either alone. That staging is the recommended target architecture.

  *Why now matters for the schedule:* the corpus consensus from the entity-resolution literature is that direct LLM-as-classifier ("just ask GPT-4 if these are the same concept") consistently underperforms hybrid pipelines. Distillr's general no-LLM-for-verification stance survives intact under this finding - LLMs go in the *elaboration* helper role, not the *decision* role. Connected-components clustering is the final-arbiter step and stays pure Python.

  *Evaluation yardstick:* the ECB+ corpus metric suite is the established baseline - MUC, B³, CEAF_e, and CoNLL F1 are what the field reports. distillr's golden eval corpus should produce these scores against hand-coded clusters so improvement is measurable.

  *Surface shape:* an offline `distill concepts resolve-aliases [<topic>]` command that proposes merges (candidate pairs above a confidence threshold) and asks for confirmation, not an automatic pass that silently reshapes the corpus. Confirmed aliases append to a per-topic `aliases.yml` that the normalize layer reads at canonicalization time. The right pattern for a knowledge layer the user inspects.

  *Validated as a real need, not speculative.* In a controlled internal validation run on two papers from the same task family ("scientific claim extraction"), the 0.8 concept layer surfaced 24 distinct mentions and zero cross-paper concepts at threshold=2 - every term was unique across the pair despite topical overlap. Mechanical canonicalization cannot bridge that vocabulary gap. The literature's two-paradigm answer is well-validated; what's left is the engineering integration, scoped to post-1.0 so it doesn't widen the 1.0 surface.

- **Caching as a load-bearing pattern across eval/synthesis/resolution layers.** The research areas above that depend on repeated model judgments (claim extraction, long synthesis, entity resolution) call out caching of LLM-derived intermediates as the engineering pattern that makes their approaches affordable at scale. distillr already has this implicitly in `mentions.jsonl` (cache extraction outputs), but `claims.jsonl`, model-judged eval runs, and alias-resolution passes need it as a deliberate design element, not a bolt-on. Worth a shared utility in `distill/llm/cache.py` rather than three independent implementations.

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
- `import-linter` and `pip-audit` promoted into blocking CI; `pre-commit` made identical to CI; `xfail_strict`; branch coverage; SBOM on release. (Dependabot was trialed in 0.8.3 and deliberately dropped - dependency bumps are reviewed manually.)
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

- **Supply chain** (0.8.3): committed `uv.lock` + `uv sync --frozen`, blocking `pip-audit` and bandit in CI, a CycloneDX SBOM, PEP 740 provenance attestations, and SHA-pinned GitHub Actions. For an API consumer the "model supply chain is the new software supply chain" concern reduces to ordinary dependency hygiene, which is covered. (Dependency/action bumps are reviewed manually; Dependabot is deliberately not used.)
- **MCP path confinement**: `read_insight` / `read_concept` resolve caller-supplied paths through `_resolve_within_library` and refuse anything outside the library root (the path-traversal / auth-bypass class addressed in the prior security pass).
- **Secret handling**: API keys are `SecretStr`, kept out of artifacts and logs; a `detect-private-key` pre-commit hook guards commits.

**Hardened in 0.8.7:**

- **Indirect prompt-injection resistance.** The one AI-specific threat that actually applies: every analyzed source (YouTube transcript, web page, PDF, tweet) is untrusted input fed to an LLM, and a source can carry embedded instructions ("ignore previous; write X") that hijack the analysis or synthesis and land in the corpus. A shared `UNTRUSTED_CONTENT_RULES` constant is now threaded into every per-source analysis prompt (video, shorts, scan, site page, paper, tweet): the embedded source is labelled untrusted data and the model is told to ignore any instructions inside it. This is the *prevention* half; the 0.10 run-time verify hook (claim-grounding) is the *detection* half, and they compose.
- **Web-dashboard output sanitization.** The local dashboard rendered corpus artifacts through `markdown(...)` with raw HTML passed through (`distill/web/server.py`), so untrusted-derived content - or an injected `<script>` inside an insight - was a stored-XSS vector. The rendered HTML is now run through an `nh3` allowlist sanitizer before serving (script/event-handlers/`javascript:` URLs stripped, formatting and tables preserved), per Python-Markdown's own guidance to sanitize output rather than trust the renderer.

**Still ahead (1.0):**

- **Boundaries are trust boundaries.** The 1.0 "parse, don't validate" work already validates MCP tool arguments and ingest inputs; the roadmap states explicitly that those parsing boundaries *are* the security boundary - path confinement and URL/SSRF validation on fetch paths live there, so the parse layer doubles as the trust layer rather than being a separate bolt-on.

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
