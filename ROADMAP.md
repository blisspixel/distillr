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

`distill discover` is the goal-aware front door across papers, videos, curated website seed files, and trusted-site page expansion. Docs-heavy workflows can pass repeated `--trusted-site` domains or section URLs so Distill enumerates public same-host candidates from sitemaps, TOC/navigation links, and landing-page links before the goal-aware rerank, instead of requiring every page seed by hand. Selected website candidates ingest exact pages by default, with opt-in bounded shallow crawls for operators who want one section hop. Website preview rows now include exact URL, section label, discovery source, and sitemap freshness date when known. Website batch seed files can mix explicit exact-page and shallow-crawl modes, and `distill site-batch --preview` shows the resolved crawl plan before writes. With global `--json`, that preview emits the same plan as loop-readable rows. MCP `site_batch` honors the same JSON seed modes only for bounded manifests under `library/site-seeds/`, and `preview=true` returns the plan even in read-only deployments.

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
- **MCP 2026-07-28 is a near-term compatibility checkpoint, not a product pivot.** The May 21 release candidate for the July 28, 2026 MCP spec makes the protocol core stateless, adds `server/discover`, cache metadata for tool and resource lists, first-class extensions, a redesigned Tasks extension, MCP Apps, authorization hardening, full JSON Schema 2020-12 for tool schemas, and annotation-only deprecations for roots, sampling, and logging. Distill should track the final spec as soon as it lands, then run a focused compatibility spike while the 1.0 MCP surface remains a candidate: inventory deprecated features, validate schemas, decide whether long-running ingest/report/profile commands should expose Tasks, and keep stdio/local deployments working while remote HTTP compatibility catches up to SDK support.
- **Registries don't distribute.** MCP registry usage concentrates in ~10 famous servers (top 10 take ~46% of attention); skills marketplaces have a measured 13.4% critical-flaw rate (Snyk ToxicSkills, Feb 2026). The adoption levers that work: a good `uvx`-runnable CLI, agent-readable docs in the repo, and a self-describing corpus - plus the security story ("your research is local plain files; no third-party server in the loop"), which MCP's 2026 CVE record turned into a real selling point.

**Why not "just make it an MCP skill"?** Distillr already *is* an MCP server (MCP-first since 0.5). But a thin MCP wrapper or agent skill would be useless for what distillr actually does - long-running batch ingestion, persistent corpus maintenance, and compounding knowledge across sessions are exactly what interactive agents (Claude Code, Cursor, Windsurf) are terrible at. The architecture is separation of concerns: distillr is the dedicated research-corpus layer; agents query it via MCP or read it as files. Shipping one canonical SKILL.md that *teaches agents the CLI* is distribution for that architecture, not a replacement of it. It's "and," not "or."

## Path to 1.0

The longer horizon - what 1.0, 2.0, and 3.0 each *promise*, the maybe-later parking lot, and the design-doc ledger - lives in [`docs/design/version-architecture.md`](docs/design/version-architecture.md); this section remains the operational spine to 1.0.

The goal of 1.0 is a stable, agent-drivable research tool that an external agent can use without surprises and that a human can run as a daily-driver knowledge system. This roadmap does not schedule a freeze. Readiness follows evidence from the current product surface, not a calendar or a claim that feature breadth is done. Seven themes run through every version:

- **Agent-first, with parallel surfaces.** Workflows expose stable library calls through the CLI, plain files, and MCP where hosted or structured access helps. The CLI and MCP remain thin wrappers over the same implementation, while the corpus itself stays the lowest-overhead agent interface.
- **Effective-context-aware.** Cloud models in 2026 have 1M+ context windows - a 100K paper fits whole. Chunking is not a universal concern; it is a local-model concern. The system should be adaptive: send content whole when the provider's window allows it, chunk intelligently when it does not (local models with 8K-32K windows). The 2025-2026 context-engineering literature (lost-in-the-middle, ACE-style playbooks, just-in-time retrieval) informs the design, but the implementation targets where it actually matters.
- **Local-first all the way down.** "Local Markdown corpus" is meaningless if every analysis call goes to a paid cloud API. When ingestion is basically free, you use it more - more sources, more frequent refreshes, richer corpus. Local doesn't mean lower quality; it means the economics don't punish thoroughness. If a workload can't meet the quality bar locally, it stays on cloud. Local execution should work on any Ollama/LM Studio compatible hardware that passes doctor checks and workload eval. The hardware trend bends toward more capable desktop and laptop local inference over time, so the default bias shifts toward local *whenever a workload clears the quality bar* - with `distill eval` (cost x quality over frozen fixtures) as the arbiter of "good enough" rather than vibes - and cloud stays the floor for what local can't yet match (long-context synthesis, web-grounded Deep Research). The router exists precisely so this ratio can move per-workload over time without touching pipeline code.
- **Loop-ready.** The 2026 shift from prompt-running to loop engineering (design the loop once; the work happens unattended and verified) is distillr's natural habitat - but distillr is the *loopable primitive and persistent state layer*, never the loop runner (no scheduler-orchestrator surface; the cron / agent-harness / stewardship layer above owns the loop). The contract every command must meet: safe to run unattended - non-interactive flags (`--yes`, `--report-only`), convergent re-runs (a converged corpus is a clean exit-0 no-op, shipped for `discover`/`papers` in 0.9.27), clean failure exits instead of tracebacks, resumability, and report artifacts rather than console-only output. The review question for any new flag or behavior: *can a recurring loop run this without a human?* The stricter admission test is: recurring work, automated verifier, bounded budget, usable tools, and persisted state. The minimum viable loop is trigger, reusable knowledge, state file, and gate. The metric that matters is cost per accepted change, not attempts or tokens. The verify hook (0.10) is the load-bearing piece - a loop without a verify gate scales slop, not work - which is why it precedes every autonomous-loop behavior on this spine. The deeper question underneath - *where distill is itself a deterministic workflow vs where it lets the model drive* - is settled in [`docs/design/agentic-balance.md`](docs/design/agentic-balance.md): agentic at the leaves (discovery, analysis, synthesis), Python-owned at the decisions (invariant #6), and completion checked against receipts plus faithfulness verdicts instead of a self-declared "done" flag (invariant #8). That charter, grounded in Anthropic's workflow-vs-agent framing, is the guardrail the more-agentic roadmap items (adaptive lenses, goal-driven discovery, the deep-synthesis loop) operate within. Its remediation arm - [`docs/design/model-judgment-vs-brittle-fallbacks.md`](docs/design/model-judgment-vs-brittle-fallbacks.md) - catalogs where deterministic keyword/regex heuristics still impersonate a semantic judgment (notably the discovery reranker's no-model gate and a rumor-keyword skeptical trip-wire) and stages the fix: route judgment to whatever model the user has (cloud *or* local - never assumed), and when there is none, degrade to a labeled recency order rather than fake quality with keyword scoring.
- **More agentic, with explicit rule boundaries.** The direction is more model-driven on open-ended surfaces: discovery query expansion, candidate judgment, analysis lensing, synthesis planning, contradiction interpretation, and future deep-synthesis loops. The rule-owned surfaces stay deterministic: URL and path safety, schema parsing, budget stops, dedup and merge bookkeeping, action ids, approval class, exact command emission, audit rollups, and verifier stop conditions. Every forward item should be readable as one of three shapes: agentic judgment, rule-owned structure, or judgment-then-rule where a model returns per-criterion verdicts and Python aggregates. If a feature judges quality, relevance, faithfulness, or completeness, it must use model judgment. If it gates an irreversible action, it must expose a structural verifier and a testable stop condition.
- **Built to last.** Module-size caps, dependency-direction enforcement (import-linter), ruff/Pyright/coverage gates, and structured logging are established as conventions in 0.3 and apply to every later milestone. 0.8.3 hardens the supporting toolchain so these conventions are reproducibly *enforced* rather than aspirational - a committed `uv.lock` plus `uv sync --frozen` ends dependency float (the typer 0.26 upgrade that silently turned a green `main` red is the cautionary case), dependency upgrades land as manually reviewed PRs that run CI before merge, import-linter and pip-audit move into CI, and coverage switches to a branch-metric ratchet. So 1.0 lands at the quality bar without a backfill scramble.
- **Measured before optimized.** Distill is Python-first, not Python-only. Performance work starts with production-shaped phase measurement, then removes repeated I/O and improves algorithms, and only then extracts a narrow native capability when it produces a material whole-workflow, memory, safety, or reliability gain. Language boundaries stay behind the stable Python, CLI, MCP, and file contracts. Markdown remains authoritative; every derived index is disposable and rebuildable. The admission policy and current evidence live in [`docs/design/performance-and-language-admission.md`](docs/design/performance-and-language-admission.md).

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

Shipped: **0.1 through 0.19** (latest release 0.19.39, 2026-07-18). Per-release detail is the changelog's job, not the roadmap's: [`docs/CHANGELOG.md`](docs/CHANGELOG.md). Newest-first headlines:

- **0.19 Recurring research profiles + no-metered-cost routing** - saved profile artifacts (topic + goal + sources + rigor), the `auto|no-metered|paid-ok` cost-mode router with fail-closed refusal, `distill doctor --adapters` preflights, `distill profile run` handoff with resume state, and the route availability/pool primitives. The remaining route-graduation gates are vendor-gated (see Current refinement program). Design: [`docs/design/recurring-profiles-cost-routing.md`](docs/design/recurring-profiles-cost-routing.md), [`docs/design/route-orchestration.md`](docs/design/route-orchestration.md).

  Cost visibility tightened after the xAI spend review: `distill doctor` reports
  the active cost mode and warns when `auto` mode has metered API keys
  configured, listing key names only and pointing to fail-closed no-metered
  mode. `distill costs`, JSON cost output, the CLI dashboard, and the local web
  dashboard also surface structural surprise-cost warnings from the ledger,
  including high daily spend, spend spikes, configured per-workflow budget
  overruns, and any recorded xAI media-generation model ids.
- **0.18 Batch-run visibility** - the `_logic.py` monolith fully retired, per-item / per-phase progress with running cost and ETA on the long ingest and report loops, and `-q` / `-v` / `--json` verbosity controls while the CLI contracts remain candidates.
- **0.17 OKF interop + loop-ready stewardship** - `distill export --what bundle --format okf` and `distill okf validate` (OKF v0.1 bundles projected over the native corpus), plus `distill audit --next-actions --json` as the loop handoff surface. Design: [`docs/design/okf-loop-readiness.md`](docs/design/okf-loop-readiness.md).
- **0.13-0.16 Engineering legibility + CLI-UX** - the entailment tier + verify-on-every-synthesis (0.13), agent-grade `--json` / strict stdout-stderr split (0.14), in-place `distill update` (0.15), the blocking structural golden-corpus eval gate (0.16), and the full `_logic.py` monolith removal. Design: [`docs/design/logic-decomposition.md`](docs/design/logic-decomposition.md).
- **0.12 Compounding corpus** - the `distill ask` loop with strict-by-definition `--save` promotion, revision-cached sub-agent MCP summaries, read-only MCP + per-call spend caps + ingest allowlist, semantic dedup, the prompt-version registry + staleness rollup, and per-item failure isolation. Design: [`docs/design/ask-loop.md`](docs/design/ask-loop.md).
- **0.11 Source breadth + audio** - five adapters (GitHub repos, podcasts RSS-first, generic media, newsletters, X), every one verify-gated, plus YouTube caption-retry with backoff and the Whisper fallback.
- **0.10 Verified corpus** - the write-time claim-grounding hook on every analysis *and* synthesis emit path (`warn|strict|off`), and `distill audit` rolling verification coverage + health + links + gaps into a per-topic report.
- **0.9 Agent-legible corpus** - AGENTS.md beside CLAUDE.md per topic, one canonical SKILL.md, the paths-not-payloads MCP consolidation, the public example corpus, and the "research corpus, not memory layer" positioning refresh.
- **0.1-0.8 Foundations** - the MCP-first surface, local inference, the concept/entity playbook + recovery surface, the reproducible `uv` toolchain + engineering baseline, the discovery loop, two-pass synthesis, local-file ingest, and the X + Whisper adapter; interleaved with the 0.9.20-0.9.23 security/robustness hardening series.

**Current refinement program.** The 0.19 surface is broad, but breadth is not a
freeze signal. The active backlog is grouped by product-quality debt so each
cycle can improve a real workflow without opening unrelated feature scope:

- **Feature work:** defer new breadth unless a current workflow cannot be made
  trustworthy without it. The final MCP compatibility spike remains a bounded
  compatibility task after the 2026-07-28 specification publishes.
- **UX flow debt:** compress setup choices, keep preview-first paths obvious,
  and make worker, retry, resume, and recovery flows self-explanatory.
- **Visual polish debt:** review terminal density, dashboard hierarchy, empty
  states, responsive behavior, and representative media from current builds.
- **Observability debt:** make every bounded refusal identify the affected
  phase, limit, run or task identity, and local receipt or telemetry path.
- **Reliability debt:** continue end-to-end deadline, byte, attempt, process,
  memory, state-transition, replay, and cross-platform fault-injection work.
- **Security debt:** close validated findings, keep MCP reads least-capability,
  preserve trusted executable identity, and rerun adversarial boundary reviews.
- **Accessibility debt:** verify keyboard order, focus visibility, semantic
  structure, contrast, reduced motion, no-color CLI comprehension, and
  screen-reader-friendly status and error copy.
- **Documentation debt:** keep README, usage, security, MCP, operator, and
  migration guidance synchronized with tested behavior and billing truth.

**Cycle 5 maintenance evidence (2026-07-17).** The current dashboard now keeps
its documented JSON stdout contract at both root and explicit command paths,
names configured local evidence paths, and distinguishes preview-before-ingest
from no-spend behavior. The local web surface moved executable code out of
inline HTML, tightened script CSP, and added keyboard tab, landmark, caption,
and scoped-header semantics. Remaining work stays in the debt groups above;
this pass does not change product scope or schedule a stability decision.

**Cycle 6 refinement evidence (2026-07-17).** Onboarding now leads through one
recommended isolated install, no-metered setup, and preview before full ingest,
while installed help, setup follow-up, empty states, and dashboard JSON keep the
same fail-closed path. Alternate install methods remain available without
competing for attention.
The current CLI read surface returns structured `show` empty states, not-found
topic commands use the stable exit taxonomy, and missing local files stop before
URL routing. Partial runs now expose an exact local error receipt or a visible
receipt-write failure plus bounded retry guidance. Broader cross-command exit
taxonomy and representative assistive-technology review remain active debt;
this cycle adds no feature scope and creates no freeze signal.

**Cycle 7 refinement evidence (2026-07-17).** Deterministic refusal semantics
now match the reserved CLI taxonomy across shared learning validation, topic
workflows, report and export preflight, vault and artifact opening,
resynthesis and reanalysis, and concept recovery. Invalid input exits 2,
missing configuration exits 3, and locally proven absence exits 5 before
provider, subprocess, or write boundaries. Unsupported or incomplete
`open --what` intent now fails closed instead of opening an unrelated folder.
Ambiguous search, partial-result, generic profile, and cancellation outcomes
remain explicitly deferred until each has one evidenced semantic cause. This
is reliability and operator polish on the current surface, not new scope or a
freeze signal.

**Cycle 8 refinement evidence (2026-07-17).** The installed CLI now preserves
the reserved usage, configuration, network, not-found, and budget classes in
content-free command telemetry instead of collapsing ordinary nonzero exits to
one generic error. The local diagnostic log rolls at 8 MiB with three backups,
and the recent performance view reads at most the newest 16 MiB from each
structured evidence log. Tail-limited sources are named in human and JSON
coverage, and aggregates whose older siblings may be excluded fail closed as
incomplete. Representative 40-column no-color refusals remained ANSI-free and
actionable, so this cycle made no cosmetic copy change without a failing case.
Structured telemetry retention and compaction remain reliability and
observability debt until their audit-history and concurrent-writer guarantees
are designed. This work adds no product surface and creates no freeze signal.

**Cycle 9 refinement evidence (2026-07-17).** Phase, provider, and cost
histories now serialize cooperating processes through per-file locks. A torn
final row is isolated before the next append, cost migration shares the ledger
critical section, and cost rows are `fsync`-flushed before profile receipt
state advances. Provider-history reads now use strict finite JSON, a 1 MiB
per-row ceiling, bounded top-N memory, stable tie ordering, and fail-soft
corruption handling across CLI and web cost views. The human inference split
names skipped malformed rows and their exact local path. Retention and
compaction remain deferred until a lossless archive can preserve completeness,
stable cost receipts, concurrent writers, and rollback. This is bounded
reliability and operator hardening, not feature breadth or a freeze signal.

**Cycle 10 refinement evidence (2026-07-18).** Mutable library, channel, and
watch state now uses bounded strict-JSON reads plus locked read-modify-write
transactions, so cooperating processes preserve one another's updates.
Corrupt state is rechecked under lock, preserved in non-colliding backups, and
never replaced after a failed quarantine. Cost-ledger readers now apply strict
monetary and timestamp validation, bounded rows and retained history, and one
coverage contract across CLI, dashboard, calibration, recurring watches, and
MCP. Completeness-sensitive totals and budget claims fail closed while valid
retained rows remain diagnostic. Topic-watch budget decisions serialize and
rescan before each entry, closing same-batch overspend races. Lossless history
archival, target-link policy, representative assistive-technology validation,
and a fresh code graph remain deferred quality debt. This is reliability,
security, accessibility, and operator refinement on the current surface. It
does not create a freeze signal.

**Cycle 11 refinement evidence (2026-07-18).** This pass stayed on the current
product surface and closed independently reproduced security, reliability, and
operator-trust defects:

- **Security:** subprocesses retain one validated executable identity, remove
  ambient Python and Node execution overrides plus credentials, and bound their
  process trees, output, time, and memory. Local media uses one stable private
  snapshot before local or cloud work. Network diagnostics omit URL secrets,
  generated agent orientations place a static trust boundary first, synthesis
  verification sidecars bind the exact rendered artifact, stale-source advice
  stays inert structured data, and MCP regeneration requires a literal JSON
  boolean authorization.
- **Reliability:** claim and concept extraction serialize per topic, publish
  model evidence before strict completion ledgers, checkpoint already-paid
  work at budget boundaries, and repair interrupted completion or derived-state
  updates before repeating provider work. Claim, mention, quality, eval,
  topic-change, and run histories serialize writers; canonical knowledge
  histories enforce typed row and byte capacity before append. Same-second
  concept snapshots no longer collide, kind migration preserves history, and
  linked child state cannot redirect reads, writes, repairs, or deletions.
  Rendered playbook notes cannot exceed their own reader ceiling, colliding
  slugs allocate in bounded linear work, failed migration removes only its new
  snapshots, and recovery refuses oversized rollup projections before changing
  a live note. Synthesis and saved-answer artifacts publish with their exact
  verification sidecars under one rollback-capable transaction.
- **Observability:** unrepresentable cost totals render as unavailable instead
  of infinity or zero. Invalid quality history names its exact path while the
  point-in-time audit remains usable without an invented baseline. Latest run
  JSON and Markdown projections share a run ID and rollback as a correlated
  pair while the append-only row remains diagnostic.
- **Documentation and regression protection:** README, operator, security,
  architecture, cost, MCP, output, contributor, generated example, public
  contract, and Agent Skill surfaces follow tested behavior. Exploit-specific
  controls cover path swaps, linked ancestry and state, child startup injection,
  transport coercion, corrupted and oversized histories, concurrent writers,
  partial derived-state recovery, and projection rollback.

Lossless history archival, representative assistive-technology validation,
browser-media validation, performance baselining, and a fresh code graph remain
active quality debt. This is not a freeze signal and does not narrow the broader
refinement program.

**Cycle 12 refinement evidence (2026-07-18).** This pass hardened current URL,
site, local-provider, migration, Agent Skill, and MCP workflows without adding
feature breadth:

- **Security and privacy:** request URLs remain available only to the fetch
  boundary. Diagnostics retain an origin, while stored artifacts, prompts,
  failure evidence, and attachment manifests retain a query-free public URL.
  Full request identity remains in domain-separated hashes, and query order is
  preserved when it affects request identity. The public Agent Skill bundle
  constructor now enforces exact identity, digest, size, file count, required
  entrypoint, and cross-platform relative-path safety.
- **Reliability and resource control:** adapter doctor probes now use bounded
  concurrent output drains, isolated process-tree cleanup, elapsed and memory
  ceilings, trusted execution context, and bounded iterative auth or config
  parsing. Local readiness probes do not consume response bodies. Ollama model
  discovery applies response, shape, model-count, field-count, and string
  bounds. Browser workers receive process-tree cleanup on every exit.
- **Operator trust:** visible legacy migration reads only bounded, confined,
  single-link Markdown, reports every repair failure, and exits nonzero after
  partial failure. MCP topic summaries distinguish absent, degraded, and
  unavailable synthesis evidence. CLI and MCP watch additions canonicalize and
  validate YouTube channel URLs before lookup, discovery, or mutation.
- **Regression protection:** all nine original URL-disclosure reproductions no
  longer reach their vulnerable assertions. Focused resource, migration,
  ownership, model-registry, site-boundary, watch, and MCP controls pass, along
  with the complete local release gate.

**Cycle 14 refinement evidence (2026-07-22).** Onboarding multi-provider clarity
on the current surface, without a multi-cloud init wizard:

- Root help lists `distill provider list/set` and one-shot `--provider` /
  `--model` overrides beside the preview-first topic path.
- Ready `init` prints the resolved analysis route and a non-xAI switch hint;
  JSON init reports `analysis_provider` and `analysis_model`.
- `topic --help` lists preview before create so the command table matches the
  recommended flow.
- `.env` / init templates treat Gemini as analysis plus Deep Research, and
  point operators at `distill provider set`.
- Complements the shipped `distill provider` command and Gemini 3.6 Flash /
  3.5 Flash-Lite catalog support. Full multi-cloud init key capture remains
  deferred; provider set is the bounded route.

This is documentation, help, and setup-verdict polish only. It adds no feature
breadth and creates no freeze signal.

**Cycle 13 refinement evidence (2026-07-18).** This pass tightened billing
truth, local readiness, preview continuity, and first-run comprehension on the
current product surface:

- **Security and cost truth:** a local provider label no longer proves local
  topology. No-metered Ollama and LM Studio routes require strict loopback
  HTTP(S); remote, deceptive, wildcard, malformed, and unsupported endpoints
  fail before provider construction and cannot enter the ledger as local work.
- **Cloud route truth:** doctor validates the exact resolved provider and model,
  rejects known cross-provider assignments, and cannot turn an unrelated valid
  key probe into a ready verdict. Remote local-adapter spend is reported as
  external and unavailable instead of zero.
- **Setup and recovery:** `init` and doctor now require one explicit model id
  that exactly matches a bounded successful provider inventory. Missing,
  unavailable, and mismatched models have specific recovery steps, and the
  shared config loader reads the documented current-directory `.env`. Forced
  setup removes stale values loaded from the replaced file, and env updates
  canonicalize duplicate assignments for deterministic next-run state.
- **Preview continuity:** mixed topic preview returns one exact topic-owned
  replay command with the effective cost mode and source settings. Replay
  persists intent and refresh state, ingests the saved set without another
  search or rerank, and saves the topic profile. Video-only preview logs its
  measured cost and labels its refreshed-at-commit selection honestly.
- **Replay reliability:** preview snapshots use serialized atomic writes,
  enforce their schema on read, and emit option-safe continuation commands.
- **Accounting and test safety:** per-attempt provider usage survives retries and
  fail-closed budget stops with consistent route telemetry. Default local tests
  cannot inherit billable cloud credentials. Dashboard rows and totals retain
  known direct spend when external provider cost is unavailable.
- **Onboarding:** topic help and the empty dashboard now lead with preview.
  README, usage, cost, security, architecture, and environment examples match
  the implemented readiness and billing boundaries.

Measured zero-work CLI startup remains the next dedicated refinement theme.
The current baseline is roughly 3.0 to 3.3 seconds for `--version` at the
median and materially noisier for help. Lazy command registration needs a
separate compatibility-focused cycle rather than being folded into these
security and workflow fixes. This evidence adds no feature breadth and does
not create a freeze signal.

Lossless history archival, live assistive-technology review, representative
browser media, a measured performance baseline, broad test-fixture typing, and
a fresh code graph remain active quality debt. This cycle is another refinement
checkpoint, not a freeze signal.

The future 1.0 stability commitment is a readiness gate, not the next release
instruction. Candidate contracts can keep improving during this program. The
stability decision requires compatibility and migration evidence, a published
performance baseline, sustained clean cross-platform release evidence,
representative user and operator journey reviews, accessibility and security
closure, and a materially reduced high-impact refinement backlog. Detail for
the eventual commitment remains below. Shipped work and rationale live in
[`docs/CHANGELOG.md`](docs/CHANGELOG.md). The
"[intentionally not in scope](#intentionally-not-in-scope)" section remains the
deliberate exclusions list.

### Shipped milestone detail -> the changelog

The per-milestone detail for everything shipped (0.1-0.19) used to live here. It has moved to its system of record - per-release notes in [`docs/CHANGELOG.md`](docs/CHANGELOG.md), and design rationale in the design docs ([agentic-balance](docs/design/agentic-balance.md), [model-judgment-vs-brittle-fallbacks](docs/design/model-judgment-vs-brittle-fallbacks.md), [entailment-tier](docs/design/entailment-tier.md), [ask-loop](docs/design/ask-loop.md), [okf-loop-readiness](docs/design/okf-loop-readiness.md), [logic-decomposition](docs/design/logic-decomposition.md)). The roadmap below keeps only forward work. Minor follow-on slices inside shipped milestones (podcast diarization / Parakeet fast path, the repo issues-and-discussions subset, further MCP tool consolidation) are tracked in the [full backlog](docs/roadmap.md).

#### Validation (2026-06-20)

Before collapsing these, every "shipped" claim was re-checked against the code, not against its own annotation:

- **Static** - 28 load-bearing claims across the verify pipeline, the 0.12 compounding surface, the brittle-proxy remediation ledger (P1-P4), the five source adapters, the 0.18/0.19 CLI and loop surface, and the security hardening were each verified against the implementation and its tests. Spot evidence: `run_verify_hook` is wired into every analysis and synthesis emit path; `model_available()` (router-based) has replaced the `config.xai_api_key` gate across the CLI and MCP; `_looks_like_rumor_query` and `infer_lens` are confirmed deleted tree-wide; there is no `eval/stats.py` bootstrap machinery; the dashboard sanitizes through an `nh3` allowlist.
- **Live** - a real grok-4.3 run (`distill papers ... --limit 2`, $0.06) produced per-paper insights, a cross-paper synthesis, and three `_Verify.json` sidecars (schema v2; the synthesis sidecar grounded 15/15 claims against its receipts), proving the capture -> analyze -> verify -> synthesize path works end-to-end, not just in mocked tests.

Nothing in the shipped record failed to validate. The forward milestones below are what is genuinely left.

#### Agentic harness dogfood validation (2026-07-11)

A zero-paid-spend mixed-source run across papers, technical videos, and X
validated the loop-ready boundary and exposed replay, contention, cost-policy,
verification-coverage, source-fidelity, and filesystem-inventory defects. The
findings, evidence, fixes, and prioritized product implications are recorded in
[`docs/research/agentic-development-harnesses-validation.md`](docs/research/agentic-development-harnesses-validation.md).

### 0.18 and 0.19 shipped -> the changelog

0.18 (batch-run visibility) and 0.19 (recurring research profiles + no-metered-cost routing) shipped through 0.19.40. Per the convention above, per-release detail lives in [`docs/CHANGELOG.md`](docs/CHANGELOG.md); the design rationale is in [`docs/design/recurring-profiles-cost-routing.md`](docs/design/recurring-profiles-cost-routing.md), [`docs/design/cli-adapter-runbook.md`](docs/design/cli-adapter-runbook.md), and [`docs/design/route-orchestration.md`](docs/design/route-orchestration.md).

The bounded active-session handoff now ships: provider-neutral tasks can be
atomically claimed through `distill worker`, completed only in an isolated
scratch workspace, submitted with ownership and hash receipts, or abandoned for
another host. One canonical Agent Skill now packages that procedure for Codex,
Claude Code, Grok Build, Gemini CLI, Antigravity, claude.ai, and compatible
Agent Skills clients. Generated client manifests, strict local vendor
validation, byte-for-byte drift checks, deterministic release archives, and
SHA-256 checksums keep those surfaces synchronized. The installed CLI now
verifies its wheel bundle and provides preview-first direct install, clean
update or removal, and deterministic export as a portable fallback. Six native
Claude plugin cases compare positive, adversarial, and negative-trigger
behavior with model graders. This remains manual,
skill-driven fallback across already active sessions. It is recorded as
host-managed with unavailable external cost, not as a live plan-quota provider
or a no-metered route. Design:
[`docs/design/agent-skill-distribution.md`](docs/design/agent-skill-distribution.md).

What remains from the 0.19 theme is genuinely forward and sits after 1.0 - it gates on vendor policy and on the read-only adapter prototypes, not on near-term effort:

- **Plan-quota route graduation (vendor-gated).** A direct plan-quota CLI route (Codex CLI, Claude Code, Grok Build, Gemini CLI, Antigravity) becomes a live no-metered route only once an adapter doctor proves included-plan auth (not an API key), machine-readable output, scratch-only writes, complete usage ledgering, live availability, and `distill eval` quality. The active-session worker does not clear those gates because Distill does not launch the host or inspect its auth. The doctor scaffolding, the strict `adapter-workload.v1` / `adapter-native-usage.v1` / `adapter-result.v1` scratch contracts, the capture writers, and the pure graduation decision are all in-tree; the open gates are current official no-metered support statements and installed-session auth proof, which are provider-specific and may change. GitHub Copilot CLI stays a credit-metered candidate under explicit paid policy.
- **Route orchestration strategies.** A strategy layer over several validated routes used together (ensemble best-of-N with a cross-family judge, maker-checker, bounded critic-refine), scored by `distill eval` on cost per accepted change, pool-aware. Buildable and testable against local + mock routes today. Design: [`docs/design/route-orchestration.md`](docs/design/route-orchestration.md).

### Trust hardening implications for the remaining spine

Recent hallucination failure-pattern review reinforces the existing direction:
Distill's advantage is not a better model guess, it is a verified source-to-corpus
workflow that makes unsupported certainty hard to write and easy to audit.

- Citation and source identity are structural truth. Handles, citation keys,
  source ids, exported bibliography rows, and generated answer citations should
  resolve to real local receipts or refuse promotion. Report section numbered
  citations now refuse promotion rather than being stripped when the handle
  cannot resolve, lightweight topic briefs now refuse the same unresolvable
  numbered citations before corpus writes, single-call synthesis outputs refuse
  them before writing output files, and cached sub-agent query summaries now
  refuse uncited or unknown source-stem citations instead of overstating
  provenance.
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
  low-confidence output labels rather than be averaged away. `distill eval`
  now preserves hallucination-risk fixture labels in rows, JSONL logs, and
  reports, with review findings derived from model-judge signals rather than
  deterministic semantic scoring.

### 1.0.0 - Stability commitment + quality bar

This is a future readiness decision, not the current implementation phase. No
public-API freeze is scheduled. When the conditions below are supported by
release evidence, 1.0 can make a documented compatibility promise without
locking in shapes that still need product, security, accessibility, or operator
refinement.

**Stability.**

- CLI flags, MCP tool/resource/prompt schemas, library directory layout, and frontmatter fields are versioned. Breaking changes require a major-version bump and a documented migration.
  - Status 2026-07-10: deterministic candidate-v1 snapshots now cover the full CLI command and parameter tree; MCP tools, input/output schemas, resources, resource templates, and prompts; modern artifact filenames, reader compatibility paths, base frontmatter, provenance fields, and representative serialized frontmatter behavior; core `DistillConfig` settings, environment names, declared non-secret defaults, cost validation, and configuration-owned library path shapes; and Draft 2020-12 schemas plus input normalization examples for the core library index and per-channel state. The default suite rejects unreviewed drift in these covered surfaces. The snapshots remain candidates until the post-2026-07-28 MCP checkpoint completes; router/provider configuration and direct runtime environment controls, additional state documents and file locations outside configuration path helpers, artifact-specific frontmatter schemas and value semantics, caller-specific reader and writer extension integration, and full legacy migration are the remaining contract slices.
- Documented backwards-compatibility policy for the `library/` directory (a 0.5 corpus opens cleanly in 1.0).
- **Measured performance baseline published.** The full contract is in [`docs/design/performance-and-language-admission.md`](docs/design/performance-and-language-admission.md), with the executable backlog in [`docs/roadmap.md`](docs/roadmap.md#9c-measured-performance-and-implementation-boundaries).
  - Live reference journeys cover a 20-paper run, a 50-video catch-up, and a site-batch. They record wall time, time to first and final verified artifact, phase attribution, CPU time, peak memory, item and byte counts, token volume, cost, verification coverage, retry/resume/no-op rates, hardware, provider, model, cache state, and corpus digest.
  - Deterministic generated-corpus fixtures cover search, audit, links, insight discovery, dashboard reads, manifest scans, and near-duplicate detection at increasing scale. Frozen offline workflow replays separate Distill-owned overhead from simulated provider wait.
  - Blocking performance checks are limited to deterministic offline fixtures after runner variance is characterized. Live model, network, and hardware journeys are scheduled or release evidence, not ordinary PR gates.
  - Optimization order is measurement, repeated-scan and data-movement removal, algorithm and cache improvements, bounded concurrency, then a conditional native spike. No language extraction precedes that sequence.
  - Status 2026-07-12: correlated command evidence is readable through `distill costs`; corpus-scale result v2 isolates every sample in a timeout-bounded child process, fingerprints the measured source, labels the warmed filesystem state, and withholds p95 below 20 samples; and the first profiled algorithm seam now uses an exact indexed candidate pass that reduced 499,500 possible pairs to 150 at 1,000 insights. The canonical scale matrix, frozen workflow replay, comparable scheduled history, live reference journeys, and published baseline remain open. The evidence does not yet admit Rust, Go, Mojo, or free-threaded Python into the product.

**A future stability commitment is about contracts, not about prompts. Prompt-revision cadence is separate.**

The 1.0 stability commitment freezes the *external contracts* (CLI flags, MCP schemas, library layout, frontmatter fields). It deliberately does **not** freeze the *prompts* that drive analysis, synthesis, concept extraction, and verification. Agent behavior changes as models change; distillr's prompts are no different. What works on one model version may regress on the next, and over-fitting prompts to the last validated model is its own kind of brittleness.

- **Prompts are versioned (`prompt_id`), not frozen.** Every artifact's frontmatter already records the `prompt_id` and `model_version` that produced it (since 0.7). 1.0 formalizes that this is the *only* required stability for prompts - the actual prompt body can revise without a major-version bump as long as the contract its output satisfies (frontmatter shape, claimed sections, golden eval gate pass) holds.
- **Documented revision trigger.** Prompts revise when a model change, eval result, or dogfood finding shows the current prompt is no longer the best implementation of the stable artifact contract.
- **Stale-detection is the user-facing consequence.** 0.10's stale-detection re-analyzes artifacts whose `prompt_id` or `model_version` falls behind the current floor. The cadence above is what defines the floor.
- **Distinction matters because users build on contracts, not prompts.** A downstream MCP consumer or Obsidian dataview depends on `synthesis_scope: "single-paper"` meaning the same thing it always meant - that's contract stability. It doesn't depend on the analysis prompt being literally identical to the 0.7 version - that's an implementation detail that *should* evolve as models improve.

**Quality bar (CI-enforced, not aspirational).**

- **Branch test coverage ≥95%**, ratcheted. 0.8.3 turns on branch coverage and starts the up-only climb from the measured baseline; the blocking CI and pre-push gates now enforce 95% across the surface. Branch (not line) is the metric, and the target is flat rather than tiered - the cost is real on presentation-heavy code (CLI rendering, web routes, dashboards), and that trade-off is accepted deliberately rather than hidden behind a per-package carve-out. Coverage is reported on every PR and can go up, not down.
  - Status 2026-07-12: the 0.19.34 release CI passes 4,227 tests at 95.01% branch coverage on Python 3.12, with the Python 3.13 and 3.14 matrix plus macOS and Windows smoke suites green.
  - Status 2026-07-14: the 0.19.36 maintenance release added adversarial
    coverage for exact-IP fetches, resource-limited PDF parsing, fail-closed
    provider and transcription accounting, concurrent secret-file updates,
    decoded-sample duration accounting, hidden-retry refusal, dashboard Host
    validation, manifest-protocol confinement, malformed feed normalization,
    installer integrity, total ASCII structural-integer parsing, isolated
    subprocess entry points, and identity-bound atomic deferred-agent task
    publication. Its definitive local gate passed 5,224 tests with three
    platform skips and eight live-network tests deselected at 95.01
    percent branch coverage; release evidence is recorded in the changelog.
  - Status 2026-07-16: the 0.19.37 release gate passes 5,405 tests with three
    platform skips and eight live-network tests deselected at 95.12 percent
    branch coverage. The release adds the bounded active-session worker,
    generated multi-client Agent Skill distributions, and the verified
    preview-first direct-install fallback described above.
- **Integration tests run by default** with mock LLMs so contributors run the full pipeline on every push without burning real spend.
- **Pyright blocking across the full package surface, with strict-mode promotion still open.** CI runs `pyright --warnings distill/` and fails on any diagnostic. `distill/llm/` is centrally strict, and promoted modules elsewhere carry file-level strict directives; remaining packages continue through the strict ratchet before 1.0. No `# type: ignore` without an inline reason comment.
- **Parse, don't validate - strict domain types at every boundary.** Every external input (MCP tool arguments, frontmatter parsing, local-file/adapter ingest, LLM structured outputs) is *parsed once* at the system boundary into a rich domain type (a Pydantic v2 model with `strict=True, extra='forbid'`, a `NewType`, or a frozen dataclass), not re-validated ad hoc deeper in. Core logic never receives raw primitives that could be invalid - illegal states are made unrepresentable, so malformed input fails at the boundary with a precise error instead of propagating. The audit health surface now parses verify sidecars into typed flag rows and stale prompt records before rendering or action planning. The shared dashboard data surface parses cost logs, latest-run payloads, topic-change history, and site manifests into typed records before CLI or web renderers read them. Shared command helpers now preserve typed metadata-writing and duration-formatting contracts before artifact writes. Topic diff, trend, watch-alert, and change-history command paths now use typed topic-change rows and typed count records before writing artifacts or rendering command output. Reinforces the verifiable-corpus thesis: the corpus is only as trustworthy as the parsing on what enters it.
- **Ruff** zero-warning under the project config, blocking. Cyclomatic complexity (`C901`) capped; `# noqa` requires an inline justification. Security rules (`S` / bandit) consolidated into the single ruff pass where practical.
- **Bandit + pip-audit** blocking in CI (both promoted in 0.8.3). Dependencies pinned via the committed `uv.lock`; CI installs with `uv sync --frozen` so the tested environment is the locked environment, a CycloneDX SBOM ships with each release, and PyPI publishing emits PEP 740 build-provenance attestations over the existing OIDC trusted-publishing channel (no stored credentials) so the chain from a reviewed `main` commit to the installed wheel is cryptographically verifiable.
- **import-linter** dependency-direction contracts blocking in CI (promoted in 0.8.3), so the layered architecture in [Target package layout](#target-package-layout-10) is enforced, not just documented.
- **Agent Skill distribution is generated and drift-gated.** One canonical
  skill feeds the Codex, Claude, Grok, Gemini, Antigravity, and claude.ai
  surfaces. CI verifies the wheel integrity manifest, exact generated copies,
  behavioral-eval structure, and deterministic archives;
  releases attach the `.skill`, claude.ai ZIP, universal plugin ZIP, and
  SHA-256 checksums separately from the Python packages.
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
- **Fault-injection at the external boundaries.** Deterministic tests that inject malformed LLM JSON, truncated/empty transcripts, network timeouts, and yt-dlp failures, asserting the pipeline degrades cleanly (resume-friendly, no half-written artifacts) and that the "no silent error swallowing" rule actually holds under turbulence - verified, not assumed. Distill's primary concurrency model is I/O plus external workers, with subprocesses, thread-backed helpers, and synchronous phases also present. Async safety, cancellation, bounded fan-out, and write-scope isolation are the current disciplines; a future free-threaded or native path must add the race and shared-state tests its own design requires.

**Polish and release confidence.**

- Complete evidence-backed reviews of onboarding, daily use, recovery,
  operator diagnostics, accessibility, and current visual hierarchy before
  treating presentation as a media-capture task.
- Document all public APIs with concise contracts and longer rationale only
  where naming cannot explain the boundary.
- Keep `docs/CONTRIBUTING.md` aligned with the full quality posture so a new
  contributor can reach a verified first contribution without hidden gates.
- Capture README screenshots or recordings only from representative, tested
  current builds. Media is evidence of the product surface, not a substitute
  for fixing it.

Why this version: 1.0 is a stability and quality claim. External systems should
receive that promise only after current workflows are polished, observable,
accessible, resilient, secure, and migration-tested enough to support it.

## Looking beyond 1.0

Not committed. Notes on directions worth thinking about once 1.0 stability is in place.

- **Shareable goal-files / topic recipes.** A `discover` goal-file is already an executable description of a corpus - the same "idea file as a prompt you hand an agent" format Karpathy's gist popularized. The direction is making goal-files portable artifacts: publish or share a goal-file (with its `--site-seeds`) so someone else can reproduce or refresh a corpus from the research *intent*, not just receive the output. Plain Markdown like everything else, no lock-in, and it fits the post-1.0 plugin-boundary timing rather than the critical path.

- **Provider breadth + plan-quota compute on an eval-gated adapter contract (committed).** The `distill/llm` router already abstracts provider+model behind workload tags, and the provider directory is further along than the pitch admits: grok, gemini, anthropic, ollama, and lmstudio are wired today. Anthropic's Claude API route is explicit opt-in metered support, including `claude-sonnet-5`, but it is not a calibrated default until `distill eval` proves the workload. OpenAI remains a reserved cloud route that must be implemented and calibrated before use. `AgentProvider` plus `distill worker` now provide deferred, scratch-only execution by an already active external agent session. Its billing class is host-managed and unproved, so it is not zero-cost or route-eligible by assertion. The committed post-1.0 work has three strands, all behind the same gate:

  - **Cloud API adapters**: complete the set - xAI, Google, and Anthropic are live today; OpenAI, AWS Bedrock, and Microsoft Foundry are post-1.0 adapter work that must be implemented, calibrated, and eval-gated before use - so users on enterprise clouds run distill against the endpoints they are provisioned for. A default still ships (one calibrated cloud route + the local route); everything else is opt-in.
  - **Plan-quota compute (the "you're already paying for it" class).** Many users carry subscription plans with generous quotas - Claude (Pro/Max), OpenAI Codex, Gemini/Antigravity, Grok plans, OpenCode, Kiro - plus local hardware. Routing bounded analysis through the agent CLIs those plans license can reduce incremental cost after Distill proves that the installed route actually uses included quota. The shipped active-session handoff captures the useful skill pattern and manual cross-host fallback now, but deliberately records external cost as unavailable. Two hard caveats are part of the design, not afterthoughts: (a) **plan terms and headless-automation policies churn** - vendors change what subscriptions permit for programmatic CLI use, so each harness adapter ships with a documented support statement and degrades to a clean message, never silent breakage or ToS-violating workarounds; (b) **"free" is not "usable"** - a plan-quota or local model graduates only by clearing `distill eval`'s cost x quality bar on the golden fixtures, exactly like any other backend. Plan-quota runs still record token volumes to the cost ledger (the no-off-ledger-spend invariant covers usage, not just dollars).
  - **The gate**: `distill eval` decides everything. A backend goes from "wireable" to "calibrated and eval-recommended" only by clearing the bar, and the same harness produces the cross-provider, cost-aware comparison that says which backend to use for which workload - and whether a plan-quota or local model now beats the cloud floor. Distillr ships no uncalibrated default, so breadth is added *without* abandoning the no-calibration-debt discipline (see [Intentionally not in scope](#intentionally-not-in-scope)). The eval gate is the thing that pays the calibration debt down cheaply instead of guessing.

- **Provider prompt and context caching policy.** The research spike is complete in [`docs/design/provider-caching.md`](docs/design/provider-caching.md). Before enabling provider-side prompt caching knobs, Distill must use provider-specific economics, not a generic "cache on" flag: Anthropic cache writes cost more than base input and 1-hour TTL costs more again, OpenAI and Azure OpenAI caching is automatic but still needs hit-rate telemetry and retention policy, Gemini explicit context caching can add storage-time charges, Bedrock cache checkpoints have platform-specific TTL and usage fields, and xAI cache hits are automatic and evictable. Any implementation must be opt in per provider, record cached token and storage metrics in the ledger, avoid pre-warming unless projected savings are positive, set explicit TTL or retention bounds when the API allows it, stop background cache refreshes when the command exits, and never claim no-metered savings unless the route proof and usage ledger show it.

- **Semantic alias resolution over `mentions.jsonl`.** 0.8's normalize layer canonicalizes mention names mechanically (case-folding, plural stripping, punctuation cleanup). That handles the easy cases. The hard cases - "rotational embeddings" / "rotation embedding" / "phase rotation" being three names for the same concept; "DeepMind" / "Google DeepMind" being one org; or, more painfully, two papers in the same field using entirely disjoint vocabularies ("SciBERT" + "BiLSTM-CRF" vs "SciEvent" + "Agent-Action-Object triples") - are out of reach of regex.

  *Architecture, grounded in the cross-document event coreference literature:* two paradigms are validated and complementary. (a) **Symbolic compression**: assign each mention a structured identifier from its arguments - borrowing X-AMR's PropBank-style roleset + ARG-0 (Agent) / ARG-1 (Patient) / ARG-Loc / ARG-Time decomposition - then cluster via connected components on identifier match. Linear in corpus size; falls back to mechanical canonicalization when arguments are missing. (b) **Semantic compression**: generate a short LLM elaboration per mention (1-2 sentences expanding what the mention refers to), then run small-model pairwise scoring + clustering on the elaborations. The 2406.02148 / 2404.08656 papers found these two paradigms have complementary failure modes - symbolic misses paraphrase, semantic misses precise argument structure - and that a staged pipeline (symbolic bucketing first, LLM elaboration for ambiguous clusters) outperforms either alone. That staging is the recommended target architecture.

  *Why now matters for the schedule:* the corpus consensus from the entity-resolution literature is that direct LLM-as-classifier ("just ask GPT-4 if these are the same concept") consistently underperforms hybrid pipelines. Distillr's general no-LLM-for-verification stance survives intact under this finding - LLMs go in the *elaboration* helper role, not the *decision* role. Connected-components clustering is the rule-owned final-arbiter step. Python remains the reference implementation; an optional accelerator cannot own the semantic policy or canonical state.

  *Evaluation yardstick:* the ECB+ corpus metric suite is the established baseline - MUC, B³, CEAF_e, and CoNLL F1 are what the field reports. distillr's golden eval corpus should produce these scores against hand-coded clusters so improvement is measurable.

  *Surface shape:* an offline `distill concepts resolve-aliases [<topic>]` command that proposes merges (candidate pairs above a confidence threshold) and asks for confirmation, not an automatic pass that silently reshapes the corpus. Confirmed aliases append to a per-topic `aliases.yml` that the normalize layer reads at canonicalization time. The right pattern for a knowledge layer the user inspects.

  *Validated as a real need, not speculative.* In a controlled internal validation run on two papers from the same task family ("scientific claim extraction"), the 0.8 concept layer surfaced 24 distinct mentions and zero cross-paper concepts at threshold=2 - every term was unique across the pair despite topical overlap. Mechanical canonicalization cannot bridge that vocabulary gap. The literature's two-paradigm answer is well-validated; what's left is the engineering integration, scoped to post-1.0 so it doesn't widen the 1.0 surface.

- **Caching as a load-bearing pattern across eval/synthesis/resolution layers.** The research areas above that depend on repeated model judgments (claim extraction, long synthesis, entity resolution) call out caching of LLM-derived intermediates as the engineering pattern that makes their approaches affordable at scale. distillr already has this implicitly in `mentions.jsonl` (cache extraction outputs), but `claims.jsonl`, model-judged eval runs, and alias-resolution passes need it as a deliberate design element, not a bolt-on. Worth a shared utility in `distill/llm/cache.py` rather than three independent implementations. Keep this distinct from provider-side prompt caches: local durable intermediate caches are files Distill owns and can inspect, while provider caches are opaque, TTL-bound, and may carry provider-specific cost or retention behavior.

## Target package layout (1.0)

The package shape established by the 0.3 decomposition and refined by later milestones. `import-linter` and the module-size cap enforce its dependency direction in CI. The current implementation and [`docs/architecture.md`](docs/architecture.md) are authoritative where filenames have evolved.

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

The canonical current layout and rationale live in [`docs/architecture.md`](docs/architecture.md). This roadmap section remains a compact architectural overview rather than a release checklist.

## Engineering standards: adopted, adapted, declined

The 0.8.3 and 1.0 quality posture above was pressure-tested against two general "elite Python standards" briefs - a baseline one (uv-everywhere, NASA Power-of-10, 3.14-only, 95% coverage, full OpenTelemetry) and a more advanced one (formal verification, Design by Contract, supply-chain provenance, pure-Python-first, free-threading). A standards memo is a useful forcing function, but applying one wholesale to a published library is how a project acquires cargo-cult gates that fit someone else's system and not its own. This section records the judgment calls so a future contributor (or a future revisit of the same brief) does not silently re-import the parts distillr deliberately rejected. It is the same discipline as "Intentionally not in scope" below, applied to engineering process rather than product surface.

**Adopted** (genuinely new, high-value, in scope at 0.8.3 / 1.0):

- `uv` as the sole toolchain, a committed `uv.lock`, and `uv sync --frozen` in CI - reproducible environments, and the direct fix for the dependency-float break that motivated 0.8.3.
- `import-linter` and `pip-audit` promoted into blocking CI; `pre-commit` made identical to CI; `xfail_strict`; branch coverage; SBOM on release. (Automated dependency update bots were trialed in 0.8.3 and deliberately dropped - dependency bumps are reviewed manually.)
- The full Pyright-strict ratchet and "parse, don't validate" strict domain types at every boundary (1.0).
- **PEP 740 build-provenance attestations** over the existing OIDC trusted-publishing channel (secretless), so the path from a reviewed `main` commit to the installed wheel is cryptographically verifiable. The cheap, high-value slice of the advanced brief's Sigstore/SLSA section.
- **Verification depth on the deterministic core** (1.0): Design by Contract (`deal`) on the merge/normalize/recovery invariants, mutation testing of the core packages, Hypothesis stateful testing of the playbook lifecycle, and fault-injection at the external-service boundaries. "Formally contracted where it matters" - scoped to the pure-Python core, not blanket.

**Adapted** (taken in spirit, tailored to this project):

- **Python 3.12 floor + 3.13/3.14 matrix, not 3.14-only.** distillr is a library other people install; the baseline optimizes for "good citizen to downstream consumers," not for making an optional runtime feature the minimum before a measured whole-command benefit exists.
- **Pyright, not Astral `ty`.** `ty` is promising but too immature in mid-2026 to gate CI on; the strictness target is identical, the checker stays the one already wired in.
- **Structured-logging discipline, not full OpenTelemetry.** No-secrets, level-correct, file-capturable logging is the bar. Distributed tracing and OTel semantic conventions are service-grade observability for a single-user local CLI - overhead without a consumer.
- **`ruff` security rules consolidated, not the full unstable preview ruleset.** Fold bandit's `S` checks into the one ruff pass where practical; do not turn on preview rules wholesale, which churn between releases and would fight the reproducibility goal.
- **Static analysis at the floor (3.12), tested at the ceiling (3.14).** ruff and Pyright target 3.12 so a 3.13/3.14-only syntax or API can't slip past review and break a supported user; the test matrix still runs the newest. The advanced brief's "3.14 as the static-analysis baseline" would invert this and silently raise the real floor.
- **Design by Contract scoped to the deterministic core, not blanket.** `deal` contracts pay off on the pure-functional merge/normalize/recovery/interval layer where invariants are crisp; smeared across IO/orchestration/presentation code they become noise. "Where it matters" is doing the work in that phrase.
- **structlog with consistent semantic fields, not full OpenTelemetry tracing.** Adopt the field-naming discipline (stable keys, no secrets) without standing up a tracing backend a single-user local CLI has no consumer for.
- **Free-threaded CPython as an evidence-gated experiment, not a default.** Python 3.14t may enter a scheduled compatibility and benchmark lane when production-shaped profiling identifies GIL-bound in-process work. It graduates only when required extensions remain compatible without silently restoring the GIL and whole-workflow throughput improves without violating latency, memory, race-safety, or installation budgets.

**Declined** (wrong for this project):

- **3.14-only baseline** - breaks installs for the entire current downstream base; covered above.
- **Language-driven rewrites and blanket purity rules.** Distill currently publishes an approximately 825 KB purelib `py3-none-any` wheel, while its dependency graph legitimately includes native wheels and external runtimes such as Rust-backed `pydantic-core` and `nh3`, Playwright, CTranslate2, PyTorch, and local model servers. New first-party native code is neither banned nor presumed valuable. It must pass the measured admission, fallback, differential-correctness, cross-platform artifact, audit, SBOM, and rollback gates in [`docs/design/performance-and-language-admission.md`](docs/design/performance-and-language-admission.md).
- **Free-threading or shared-memory concurrency as the default architecture.** Current evidence does not justify changing the supported runtime or concurrency model. The adapted benchmark lane above may reopen the decision; runtime availability alone does not.
- **Container / image scanning (trivy), full SLSA L3 generators.** The published artifacts are a PyPI source distribution and universal wheel. The repository supports source-built containers through its Dockerfile but does not publish an image, so `pip-audit`, SBOM generation, and PEP 740 attestations cover the release surface that exists today. Revisit image scanning if a container image becomes a published artifact.
- **Auto `uv lock --upgrade` in CI.** A manually reviewed upgrade PR (running full CI against the new lock before merge) is strictly safer than CI silently re-resolving - the un-reviewed auto-upgrade is the same dependency-float failure mode 0.8.3 exists to kill, just relocated. (Automated bump bots are also declined; bumps are reviewed by hand.)
- **Power-of-10 hard gates that do not fit a Markdown pipeline** - two-asserts-per-function, fixed loop bounds, and no-recursion are flight-software rules for hard-real-time control loops. The in-character subset is already convention here: module-size caps, `C901` complexity caps, no silent error swallowing, narrowest-scope declarations. The rest would be ceremony, not safety.
- **Copier / portfolio template scaffolding** - a cross-project concern (how *many* repos share standards), not a property of distillr's own codebase. Out of scope for this roadmap.

## Security posture

distillr's threat model follows from what it actually is: a local-first CLI and MCP server that **consumes** third-party LLM APIs (xAI, Gemini) to turn untrusted public sources into a local Markdown corpus. It trains no models, serves no inference, holds no model weights, and is single-user. So the large body of "AI security" guidance aimed at *model builders and operators* - training-data poisoning and backdoors, model extraction / inversion / membership inference, differential privacy and privacy-budget accounting, confidential-compute enclaves (TEEs / SMPC / homomorphic encryption), model watermarking and signing, adversarial-robustness certification, multi-agent trust zones, post-quantum model-IP protection - targets a system distillr is not. Those are **out of scope by architecture, not by neglect.** distillr's real assets are the user's API keys and the integrity of the corpus; its real attack surface is untrusted ingested content plus the tool and HTTP boundaries.

**Already in place:**

- **Supply chain** (0.8.3): committed `uv.lock` + `uv sync --frozen`, blocking `pip-audit` and bandit in CI, a CycloneDX SBOM, PEP 740 provenance attestations, and SHA-pinned GitHub Actions, including the PyPI publish action after verifying its matching container image tag. For an API consumer the "model supply chain is the new software supply chain" concern reduces to ordinary dependency hygiene, which is covered. (Dependency/action bumps are reviewed manually; automated dependency update bots are deliberately not used.)
- **MCP capability confinement**: `read_insight` authorizes bounded topic
  Markdown only, concept reads stay inside their artifact classes, site seed
  previews use a dedicated bounded JSON namespace, and no-follow reads refuse
  paths outside each tool's declared capability.
- **Secret handling**: API keys are `SecretStr`, kept out of artifacts and logs; a `detect-private-key` pre-commit hook guards commits.

**Hardened in 0.8.7:**

- **Indirect prompt-injection resistance.** The one AI-specific threat that actually applies: every analyzed source (YouTube transcript, web page, PDF, tweet) is untrusted input fed to an LLM, and a source can carry embedded instructions ("ignore previous; write X") that hijack the analysis or synthesis and land in the corpus. A shared `UNTRUSTED_CONTENT_RULES` constant is now threaded into every per-source analysis prompt (video, shorts, scan, site page, paper, tweet): the embedded source is labelled untrusted data and the model is told to ignore any instructions inside it. This is the *prevention* half; the 0.10 run-time verify hook (claim-grounding) is the *detection* half, and they compose.
- **Web-dashboard output sanitization.** The local dashboard rendered corpus artifacts through `markdown(...)` with raw HTML passed through (`distill/web/server.py`), so untrusted-derived content - or an injected `<script>` inside an insight - was a stored-XSS vector. The rendered HTML is now run through an `nh3` allowlist sanitizer before serving (script/event-handlers/`javascript:` URLs stripped, formatting and tables preserved), per Python-Markdown's own guidance to sanitize output rather than trust the renderer.

**Hardened in the current refinement cycle:**

- **End-to-end source budgets.** Shared fetches carry one deadline through DNS,
  redirects, retries, backoff, and caller reads. Sitemap, attachment, browser,
  HTML, PDF, MCP, and OKF workflows enforce aggregate attempt, byte, entry,
  process-tree, memory, diagnostic, and elapsed ceilings at their controlling
  boundary.
- **Trusted local execution.** Executable launches resolve one absolute trusted
  identity outside the current directory, use a trusted working directory, and
  scrub injection-prone or credential-bearing child environment values. UNC
  and device targets are rejected before filesystem probes.
- **Atomic deferred publication.** Worker admission, claims, release, abandon,
  submit, and replay share a serialized transition boundary. Publication
  rechecks ownership and the exact workspace set, and replay requires a valid
  submission receipt.

**Continuing security work:**

- **Boundaries remain trust boundaries.** Continue the parse-don't-validate
  ratchet across untyped legacy inputs and keep path authorization, URL and
  SSRF checks, state parsing, cost refusal, and publication preconditions at
  the boundary that owns the operation.
- **Agent-facing guidance is validated, not just written.** Any future skill text, MCP tool description, adapter prompt, or generated orientation template that tells an agent how to act should carry a small source-controlled contract: scope, risk class, allowed side effects, expected verifier, and test plan. CI should validate those contracts and the house-style rules so agent-facing files cannot drift into personal account assumptions, machine-attribution lines, secret leakage, or unbounded tool affordances.
- **Guardrails stay surface-scoped.** Always-on checks cover credentials, cost policy, personal-data hygiene, attribution/style, and irreversible-action boundaries. Surface-specific checks cover URL ingest, local-file ingest, MCP path reads, external adapter scratch writes, and provider routing. This keeps the guidance small enough to follow while preserving the agentic-balance rule: deterministic code owns structure and safety boundaries, model judgment owns semantic quality.

If distillr ever ships a hosted multi-tenant service or fine-tunes its own models, the out-of-scope list above reopens. Until then, deepening it would be securing an attack surface the project does not have.

## Intentionally not in scope

A roadmap is also an opinion about what *not* to build. These are deliberate exclusions, not gaps. Several are informed by the competitive landscape (see above) - competitors that make different choices validate that these are real trade-offs, not oversights.

- **No graph-view UI inside distill.** Obsidian / Logseq / Dendron already do this well; reimplementing duplicates effort without adding value. The Obsidian-native milestone (0.7) is the answer. (SwarmVault builds its own graph view; we get it free from the ecosystem.)
- **No proprietary editor, mobile app, or cloud-hosted SaaS.** The whole point is plain-text Markdown with no lock-in. A hosted version would create exactly the dependency the project exists to avoid.
- **No database of record or general-purpose RAG / vector-store surface.** Distill is opinionated about the corpus shape and analysis pipeline. A measured search or dedup accelerator may use a derived index only under `.distill/`; it must be git-ignored, rebuildable from Markdown and JSONL, never authoritative, and paired with a direct-file fallback. Users who want a generic RAG toolkit have LangChain and LlamaIndex. Pure Markdown plus git-friendly source artifacts remain the defensible product boundary.
- **No multi-user / auth / collaboration layer.** Single-user local tool. Shared corpora are a `git` problem, not a distillr problem.
- **No additional cloud LLM providers by default.** Each provider is calibration debt - prompts that work well on one model regress on another. Anthropic now ships as an explicit opt-in API route, and users can wire future OpenAI / Mistral / etc. routes through the same router, but distillr won't ship default model policies for them until the eval gate proves the workload. Local providers are the exception because they carry the local-first promise. (Transcription providers are not subject to this exclusion: speech-to-text carries no analysis-prompt calibration debt, so the Whisper transcription ladder ships a cloud tier - xAI Grok STT, reusing the already-required `XAI_API_KEY` - beneath the local-first default.) The exclusion is against *uncalibrated defaults*, not against provider reach: post-1.0, the eval-gated adapter contract (see [Looking beyond 1.0](#looking-beyond-10)) is the path by which a backend - local or cloud (Bedrock, Foundry, Anthropic, OpenAI, Google, xAI) - graduates to calibrated-and-recommended by passing `distill eval`, rather than being shipped blind.
- **No general Distill ingestion or provider plugin system before 1.0.** Premature abstraction. The generated agent-client plugin is a distribution wrapper around one skill, not an internal extension API. The right runtime plugin boundaries become obvious only after the internal architecture from 0.3-0.5 has carried real workloads. Revisit post-1.0.
- **No real-time collaboration or sync service.** Markdown + git is the answer. distillr won't compete with Obsidian Sync, Logseq Sync, or Syncthing.
- **No autonomous skill fleet or symlink-managed agent runtime.** Distill ships one canonical skill that teaches agents to use the CLI and corpus. Its direct lifecycle may install that one verified skill into a documented client directory, but it does not manage fleets or symlink trees. The skill can complete explicitly claimed deferred tasks through a scratch-only protocol and hand failures to another active host. Distill still does not launch an interactive coding agent as an unbounded batch runtime or bypass its own verification and corpus-write path. Distill remains the dedicated research-corpus layer; agents use its files, CLI, MCP surface, or bounded worker handoff.
- **No anti-bot / paywall / login-walled scraping.** Playwright handles legitimate access; defeating hostile defenses is whack-a-mole that pulls focus from the analysis pipeline and creates legal/ethical surface area.
- **No "cheap mode" that compromises fidelity.** The product premise is "as good as we can possibly make it" regardless of whether inference runs locally or in the cloud. Local models exist to make the corpus *always current* at zero marginal cost, not to produce worse outputs faster. Cost reduction happens through local inference, compaction, and JIT context - never through cheaper prompts that produce worse outputs. A local insight must be good enough that synthesis and expert queries can trust it without qualification.

These exclusions are load-bearing, not permanent. They get revisited if the constraint that drives them changes.

## Full backlog

The area-by-area backlog (stay-current, dashboard, papers, cross-source intelligence, context engineering, discovery loop, etc.) lives in [`docs/roadmap.md`](docs/roadmap.md). Items there will be tagged with the milestone above where they land in a follow-up pass.

Design principles drawn from the context-engineering literature are summarized in [`docs/architecture.md#context-engineering-principles`](docs/architecture.md#context-engineering-principles).
