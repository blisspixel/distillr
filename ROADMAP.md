# Roadmap

High-level direction. Shipped work lives in [`docs/CHANGELOG.md`](docs/CHANGELOG.md). The full, area-by-area backlog (un-trimmed, with priority breakdowns) lives in [`docs/roadmap.md`](docs/roadmap.md).

## Current shape

Distill is a source-to-intelligence platform covering four source types, labelled by maturity:

- **YouTube** (stable) — channels, topic searches, videos, Shorts
- **Websites** (stable) — vendor sites, research hubs, curated URL sets
- **arXiv papers** (stable) — phrase-matched search, full-PDF extraction, cross-paper synthesis
- **X posts** (beta) — `distill ingest <tweet-url>` via the public syndication endpoint, with local-first Whisper transcription for native video; thread expansion and consolidated cost plumbing land with the 0.11 breadth pass

`distill discover` is the goal-aware front door across papers, videos, and curated website seed files. The next refinement for docs-heavy research is app-native trusted-site discovery on allowlisted domains, so workflows like "prefer Microsoft docs + Microsoft channels" do not require hand-curated page seeds.

Everything produces plain markdown in a local `library/` directory. An MCP server exposes the corpus to AI assistants and agent systems.

Distillr is the **persistent, verifiable research corpus** for AI agent workflows — the production CLI for the pattern Karpathy's ["LLM Wiki" gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) made famous: ingest sources, maintain an interlinked plain-Markdown corpus, let agents query it. It's the corpus that [Deepr](https://github.com/blisspixel/deepr) experts query for grounded intelligence, that coding agents consult via MCP or read directly as files, and that humans browse in Obsidian. The ingestion pipeline is the input mechanism; the real product is the always-current, always-queryable corpus.

We deliberately do **not** position this as a "memory layer." The agent-memory category (mem0, Zep, Letta, Cognee) is conversation-fact extraction — a different job, being commoditized from below by free native memory in Claude/ChatGPT/Gemini, and measured by benchmarks (LoCoMo et al.) that are both contested and irrelevant to a research corpus. Distillr is a research corpus / knowledge substrate; it competes with none of those tools on their turf and should not invite the comparison.

## Competitive landscape (June 2026)

*Refreshed 2026-06-11 from a primary-source research sweep; star counts verified directly against the GitHub API that day. The May 2026 analysis this replaces is in git history.*

**The architecture bet won the argument.** In the nine months to mid-2026, "plain files over RAG" went from contrarian to mainstream-endorsed: Anthropic's [context-engineering guidance](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) recommends just-in-time file retrieval over pre-built semantic indexes (semantic search: "less accurate, more difficult to maintain, and less transparent"), and every Anthropic memory surface — the memory tool, Claude Code auto-memory, managed-agent memory — is Markdown files. Letta, the MemGPT company that defined database-backed agent memory, publicly sunset its server-side memory tools for git-backed file "context repositories" (March 2026). Karpathy's April 2026 gist (~16M views on the announcement post) made the whole pattern famous. The pure-Markdown invariant no longer needs defending; it needs citing.

**But the generic wiki-maintenance niche saturated within weeks of the gist.** The May analysis tracked four small tools; the actual leaders emerged elsewhere:

| Tool | Stars (2026-06-11) | What it is | Relation to distillr |
|------|--------------------|------------|----------------------|
| [kepano/obsidian-skills](https://github.com/kepano/obsidian-skills) | 35.3k | Obsidian CEO's official Agent Skills for Markdown vaults | Validates skills-as-distribution and vault conventions; not an ingestion pipeline |
| [nashsu/llm_wiki](https://github.com/nashsu/llm_wiki) | 11.1k | Desktop LLM-wiki app + web clipper, "instead of traditional RAG", MCP + lint reports | The mass-market wiki maintainer |
| [claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian) | 6.5k | "Self-organizing second brain" conventions for Claude Code + Obsidian | Generic `/ingest`, no source-specific pipelines |
| [obsidian-wiki (Ar9av)](https://github.com/Ar9av/obsidian-wiki) | 1.8k | Skills-based vault agent (35 skills), session auto-capture | The "install skills into your agent" model |
| [SwarmVault](https://github.com/swarmclawai/swarmvault) | 538 | LLM wiki + hybrid SQLite/embeddings, typed graph with per-edge provenance, contradiction detection, installers for 10+ agent harnesses | The trust-features pacesetter, DB-backed |
| [Lacuna-wiki](https://github.com/Labhund/lacuna-wiki) | 32 | MCP-first DuckDB wiki | Stalled (no pushes since April 2026) |

Distillr should not chase that crowd — the vault-maintenance fight is lost to 35k/11k-star incumbents and the storage format is no longer a differentiator (everyone has Markdown now).

**Where distillr's ground is uncrowded (verified June 2026):**

1. **The acquisition front-half.** Every tool above starts at "drop in sources you already have." None does goal-aware multi-source *discovery* (searching YouTube + arXiv + web against a research goal, reranking for fit and complementarity, then ingesting with transcript-grade pipelines). Adversarially verified: no mainstream product maintains a self-growing, user-owned, plain-file research corpus across runs. The closest proprietary convergence is NotebookLM — Deep Research reports now flow into persistent notebooks with Gemini-app sync (April 2026) — but it exports only to Google Docs/Sheets, a documented pain point to position against. The window is open but the idea is now famous; clones add pipelines weekly.
2. **Trust is the new quality frontier — and distillr's pipeline was built for it.** The leaders compete on contradiction detection (SwarmVault), lint/orphan reports (llm_wiki), and draft-then-promote review gates (WUPHF). The academic evidence is on distillr's side of the argument: deep-research agents fact-check their own citations at only 39–77% accuracy, degrading as retrieval scales ([arXiv 2605.06635](https://arxiv.org/abs/2605.06635)). Structured per-item insights with receipts, cross-source synthesis that preserves disagreements, the verify hook, and the audit surface are exactly this frontier — and the verification architecture is now settled practice (see the 0.10 milestone).
3. **Source white space.** No open-source tool does structured insight extraction from podcasts (the incumbents — Snipd, Podwise — are closed consumer apps), and repo understanding exists only in closed products (Cognition's DeepWiki, Copilot Spaces); OSS repo tools (Repomix, Gitingest) stop at concatenation. Distillr's per-item insight format applied to those sources is genuinely unoccupied ground.

**Agent legibility is distribution, and it is near-free (promoted out of "1.0 polish"):**

- **AGENTS.md won the cross-vendor baseline** (Linux Foundation / Agentic AI Foundation; read by Codex, Cursor, Gemini CLI, 30+ tools) — but Claude Code reads CLAUDE.md, so the corpus should emit *both* per topic (the documented bridge is a one-line `@AGENTS.md` import). Skip llms.txt (dead as a signal).
- **SKILL.md went vendor-neutral** ([agentskills.io](https://agentskills.io), ~32 tools by March 2026), and the winning vendor pattern is exactly distillr's shape: *a CLI plus one skill teaching the agent to use it*. One canonical SKILL.md is one file, ~100 tokens until invoked — categorically different from the symlink-machinery model this roadmap still rejects.
- **The MCP server stays but slims.** Token-efficiency is now canon: Anthropic measured ~85% schema savings from deferred tool loading and large gains from [code-execution over tool calls](https://www.anthropic.com/engineering/code-execution-with-mcp); GitHub cut agentic-workflow tokens ~62% partly by replacing MCP calls with the `gh` CLI; Claude Code's own best practices call CLI tools "the most context-efficient way to interact with external services." At ~500–1,000 schema tokens per tool, 22 always-loaded tools is the pattern the ecosystem is punishing. Consolidate to a handful of workflow-shaped tools that return **paths into the corpus plus short previews, never full payloads** — the corpus being plain files makes this natural. The server remains the only route to claude.ai web/mobile and hosted agents, so it stays; it becomes a thin window onto the files.
- **Registries don't distribute.** MCP registry usage concentrates in ~10 famous servers (top 10 take ~46% of attention); skills marketplaces have a measured 13.4% critical-flaw rate (Snyk ToxicSkills, Feb 2026). The adoption levers that work: a good `uvx`-runnable CLI, agent-readable docs in the repo, and a self-describing corpus — plus the security story ("your research is local plain files; no third-party server in the loop"), which MCP's 2026 CVE record turned into a real selling point.

**Why not "just make it an MCP skill"?** Distillr already *is* an MCP server (MCP-first since 0.5). But a thin MCP wrapper or agent skill would be useless for what distillr actually does — long-running batch ingestion, persistent corpus maintenance, and compounding knowledge across sessions are exactly what interactive agents (Claude Code, Cursor, Windsurf) are terrible at. The architecture is separation of concerns: distillr is the dedicated research-corpus layer; agents query it via MCP or read it as files. Shipping one canonical SKILL.md that *teaches agents the CLI* is distribution for that architecture, not a replacement of it. It's "and," not "or."

## Path to 1.0

The goal of 1.0 is a stable, MCP-first research tool that an external agent can drive without surprises and that a human can run as a daily-driver knowledge system. Milestones are ordered by dependency, not by calendar — each one unblocks the next. Four themes run through every version:

- **MCP-first.** Every workflow has a clean tool surface for agents, not just a CLI for humans. CLI commands are thin wrappers over the same library calls the MCP server uses.
- **Effective-context-aware.** Cloud models in 2026 have 1M+ context windows — a 100K paper fits whole. Chunking is not a universal concern; it is a local-model concern. The system should be adaptive: send content whole when the provider's window allows it, chunk intelligently when it does not (local models with 8K-32K windows). The 2025-2026 context-engineering literature (lost-in-the-middle, ACE-style playbooks, just-in-time retrieval) informs the design, but the implementation targets where it actually matters.
- **Local-first all the way down.** "Local Markdown corpus" is meaningless if every analysis call goes to a paid cloud API. When ingestion is basically free, you use it more — more sources, more frequent refreshes, richer corpus. Local doesn't mean lower quality; it means the economics don't punish thoroughness. If a workload can't meet the quality bar locally, it stays on cloud. Tested on RTX 4090 (Windows) and M1 Mac; should work on any Ollama/LM Studio compatible hardware. The hardware trend bends this way: consumer GPUs (4090/5090-class) already run capable 27B-70B models, and DGX Spark-class desktop and laptop machines arriving through late 2026 put much larger local models within reach on a single workstation. So the default bias shifts toward local *whenever a workload clears the quality bar* — with `distill eval` (cost x quality over frozen fixtures) as the arbiter of "good enough" rather than vibes — and cloud stays the floor for what local can't yet match (long-context synthesis, web-grounded Deep Research). The router exists precisely so this ratio can move per-workload over time without touching pipeline code.
- **Built to last.** Module-size caps, dependency-direction enforcement (import-linter), ruff/Pyright/coverage gates, and structured logging are established as conventions in 0.3 and apply to every later milestone. 0.8.3 hardens the supporting toolchain so these conventions are reproducibly *enforced* rather than aspirational — a committed `uv.lock` plus `uv sync --frozen` ends dependency float (the typer 0.26 upgrade that silently turned a green `main` red is the cautionary case), dependency upgrades land as manually reviewed PRs that run CI before merge, import-linter and pip-audit move into CI, and coverage switches to a branch-metric ratchet. So 1.0 lands at the quality bar without a backfill scramble.

**Release rhythm: feature passes interleaved with recurring harden passes.** The milestones below are feature-shaped and dependency-ordered, but they do not ship as one uninterrupted march. Every few feature releases, distillr runs a **bug-hunt + harden pass** — a release that adds no product surface and instead finds and fixes defects (security, SSRF/DoS and resource-exhaustion ceilings, crash-on-malformed-input, supply-chain) and then ratchets the quality gate. The 0.9.20–0.9.23 series is the worked example: an adversarial security review plus a parse-don't-crash sweep over untrusted and corruptible local state, the branch-coverage floor raised up-only, and every GitHub Action pinned to a commit SHA. This is deliberate sequencing, not interruption — hardening the surface a feature just added is cheaper than one end-of-line scramble before 1.0, and each pass feeds the 1.0 quality bar incrementally rather than as a backfill. Every release, feature or harden, clears the same CI gate (ruff, import-linter, bandit + pip-audit, pyright, and the 3.12–3.14 test matrix with its branch-coverage floor).

### Milestones at a glance

Previously shipped: **0.1 through 0.9.27.** Initial release and internal foundations; the MCP-first surface; local inference; the living-wiki concept/entity playbook plus its recovery surface (`concepts log/diff/rollback`, MCP `concept_history`/`concept_diff`); the reproducible `uv` toolchain and engineering baseline; the agent-discoverable library (auto-generated `CLAUDE.md`); the **0.9 discovery loop** (preview-as-default, score-cliff sizing, `--rigor`, gap-driven discovery); **two-pass synthesis** with a structured claim intermediate; synthesis **register styles** + the anti-AI-slop guard; **local-file ingest** (`distill ingest <path>`); the **X + Whisper** adapter (local-first transcription); and the **goal-aware agentic slice** (adaptive analysis lenses + persisted `CorpusIntent` on every ingest entry point, the thesis/white-space synthesis rung, corpus-aware discovery dedup + reproducible plans). Interleaved with these: the **0.9.20–0.9.23 security/robustness hardening series** (yt-dlp SSRF, dashboard exfil beacon, ingest/MCP/syndication DoS ceilings, second-hop prompt-injection hardening, atomic-write durability, GitHub-Actions SHA-pinning, and a parse-don't-crash sweep over untrusted/corruptible local state) plus the 0.9.26 command-dispatch fix. Per-release detail lives in [`docs/CHANGELOG.md`](docs/CHANGELOG.md).

Ahead — the path to 1.0 and beyond, ordered by dependency. *(Reordered 2026-06-11 after the June competitive-research sweep: the verify hook moved forward — it gates three later milestones, its architecture is now settled practice, and trust is the frontier the leaders compete on; agent legibility was promoted out of "1.0 polish" because it is distribution, it is near-free, and the window is now; source breadth lands behind the trust gate so a wider input funnel doesn't compound unverified content.)*

- **Agent-legible corpus (0.9 series)** — emit AGENTS.md alongside the per-topic CLAUDE.md, publish one canonical SKILL.md teaching agents the CLI, consolidate the MCP surface to a few workflow-shaped paths-not-payloads tools, and refresh positioning (research corpus, not "memory layer"). [detail](#agent-legible-corpus-09-series)
- **0.10 Verified corpus** — the write-time claim-grounding verify hook (extract-then-check with a small local checker) plus the self-maintaining `distill audit` (one report artifact + action menu). Verify is the substance; audit is the visible surface. [detail](#0100--verified-corpus-run-time-verify--self-maintaining-audit)
- **0.11 Source breadth and audio capability** — the four remaining adapters (podcasts RSS-first, GitHub repos as insight extraction, generic audio/video files, Substack) on a documented adapter contract, plus YouTube-path resilience. [detail](#0110--source-breadth-and-audio-capability)
- **0.12 Compounding corpus** — the `distill ask` output->input loop (gated on verify), sub-agent-friendly MCP summaries, scheduled refresh + scheduled audit, semantic dedup, artifact-level stale-detection, budget guardrails. [detail](#0120--compounding-corpus)
- **1.0 Stability commitment + quality bar** — versioned CLI / MCP / library / frontmatter contracts; Pyright-strict and "parse, don't validate" boundaries; the golden-corpus eval gate (+ metamorphic robustness) and verification depth on the deterministic core; branch coverage ≥95%; blocking lint/security CI; the presentation pass; and a documented prompt-revision cadence (contracts are stable, prompts are versioned and revised on a schedule). [detail](#100--stability-commitment--quality-bar)
- **Beyond 1.0** — semantic alias resolution over `mentions.jsonl`, and shared LLM-intermediate caching as a load-bearing pattern. [detail](#looking-beyond-10)

A harden pass is slotted in whenever the surface a recent feature added warrants it (the 0.9.20–0.9.23 series is the precedent), so the sequence above is the feature spine, not the whole release stream. Detail for each forward milestone follows; shipped releases — and the design rationale behind them — are recorded in [`docs/CHANGELOG.md`](docs/CHANGELOG.md). The "[intentionally not in scope](#intentionally-not-in-scope)" section at the bottom is the deliberate exclusions list.

### Agent-legible corpus (0.9 series)

The corpus already *is* the interface — plain Markdown, stable filenames, frontmatter, per-topic CLAUDE.md. This pass makes that architecture legible to every major harness and stops paying token rent on the MCP surface. All conventions and packaging; no new verbs.

- **Emit AGENTS.md alongside CLAUDE.md per topic.** Verified June 2026: Claude Code reads CLAUDE.md; Codex, Cursor, Gemini CLI and 30+ tools read AGENTS.md (the Linux-Foundation-backed standard) and ignore CLAUDE.md. Same generated content, both filenames (or AGENTS.md + a one-line `@AGENTS.md` CLAUDE.md shim). Near-zero cost; makes the corpus readable by every agent, not just Claude.
- **One canonical SKILL.md.** A single vendor-neutral skill ("how to query and curate a distillr corpus: grep these directories, read this frontmatter, run these `distill` commands") published in the repo for users to drop into `~/.claude/skills/` / `~/.agents/skills`. This is the "CLI + skill" distribution pattern the ecosystem converged on — not the symlink-machinery model, which stays rejected.
- **MCP surface consolidation (the §11 just-in-time item, promoted).** Collapse the 22-tool surface toward a few workflow-shaped tools whose default response is ranked `(path, preview, score)` tuples with a `read_insight(path, section?)` drill-down — paths-not-payloads. Full-body returns stay available on explicit request. Deprioritize the 12 resources / 4 prompts (no evidence mainstream clients use either). The MCP server's job: the corpus from claude.ai web/mobile and hosted agents; the files' job: everything local.
- **Positioning refresh.** README/docs language moves from "memory layer" to "verifiable research corpus / the production CLI for the LLM-wiki pattern"; state the NotebookLM contrast (their corpus exports to Docs/Sheets only; ours *is* files) and cite the Anthropic/Letta/Karpathy convergence rather than arguing it.
- **Proof artifacts (pulled forward from the 1.0 presentation pass).** External QA's unanimous top finding: nobody can evaluate the tool without installing it. Ship the cheap proof slice now — a small public example corpus (a real, labelled `library/topics/<example>/` tree in the repo or a release asset), 3–4 screenshots/GIFs (terminal run, dashboard, a synthesis open in Obsidian), and one terminal recording of a `discover --preview -> ingest` run. Demo provenance must be unambiguous: every sample is labelled real-or-synthetic. The full README hero/screenshot polish stays in 1.0; this is the minimum evidence layer.

Why this comes first: it is the cheapest milestone on the spine, it is the distribution channel for everything after it, and it is time-sensitive — the pattern is famous now, the clones are weeks from adding pipelines, and the framing ("the rigorous one") is still unclaimed.

### 0.10.0 — Verified corpus: run-time verify + self-maintaining audit

The trust release. Anthropic's Agent SDK formalizes the agent loop as `gather context -> take action -> verify`; distillr does gather (discover) and act (analyze + synthesize) but nothing catches a hallucinated number, name, or date before it is committed to the library. Meanwhile the measured fact-check accuracy of deep-research agents is 39–77% — including the Gemini Deep Research reports distillr itself ingests. The golden-corpus eval gate in 1.0 is the *test-time* check; this milestone adds the *write-time* check, and packages the trust signals into one visible surface.

**Run-time verify hook.**

- **Inline claim-grounding on every analysis emit** — for every `_Insights.md` write, post-process the structured output: extract each load-bearing claim (numbers, named products, dates, named people), ground it against the source artifact, flag unsupported claims in a `_verify.json` sidecar with the same identity stem.
- **Extract-then-check, with the check local and deterministic-first.** The 2026-settled architecture (RefChecker / Claimify-shaped): a regex/grep first cut for the easy cases ("this section claims a number; does the number appear in the source"), then a small local entailment checker scoring each (claim, source-chunk) pair — [Vectara HHEM-2.1-Open](https://huggingface.co/vectara/hallucination_evaluation_model) (110M params, Apache 2.0, CPU-feasible) as the default, IBM Granite Guardian via Ollama as the higher-accuracy option. Never an LLM-as-judge-of-record, per the invariants ("LLM proposes, Python decides"); the verifier deliberately does not share the analysis model's biases. Avoid NC-licensed checkers (Bespoke-MiniCheck).
- **Configurable severity** — `--verify warn` (default; surface to console, write anyway), `--verify strict` (refuse the write), `--verify off`. Deterministic verification layered on stochastic output — the Agent SDK "hooks" pattern.
- **Run it over ingested Deep Research reports too** — that input stream has the measured weakness; grounding its load-bearing claims against the corpus receipts is the highest-leverage single application of the hook.
- **Dogfood corpus informing this design:** `library/topics/claim-verification/` (6 papers, ingested 2026-06-11 via goal-aware discover, ~$0.19). Key findings for the hook: claim decomposition measurably improves evidence matching (subquestions 59.6 vs 36.9 F1 on PolitiFact); a *domain-adapted* small NLI verifier approaches GPT-4o on grounding (Auto-GDA lifts DeBERTa 0.708 -> 0.878 ROC-AUC vs GPT-4o's 0.883) — so the off-the-shelf local checker is the floor, with Auto-GDA-style synthetic adaptation as the upgrade path; and numerical/comparison claims are the measured hard class (peak 47.33 Conflicting-class F1 on QuanTemp), which makes QuanTemp the natural eval fixture for exactly the numbers/dates/names claims this hook targets.

**Self-maintaining audit.** The Karpathy-pattern "monthly health check," already mostly built but scattered and console-only: `distill health` (stale syntheses, thin artifacts, contested concepts), `distill doctor --links` (broken backlinks), and the MCP-only `research_gaps(topic)` (coverage gaps + next actions). This pass composes them — packaging, not new analysis:

- **`distill audit <topic|all>`** — one run bundling the three checks plus artifact-level stale-detection (reads the `prompt_id` / `model_version` floor when present, formalized in 0.12). Supersedes the console-only `health` output; `health` becomes the fast/no-report alias.
- **Corpus-wide contradictions map** — surface the cross-source disagreements synthesis already names and the contested-concept flags the playbook already tracks as a dedicated scannable section: which claims conflict, across which sources, still unresolved. Contradictions are strategic signal, not noise to smooth away — the failure mode a naive auto-wiki hits is resolving "engineering says 12 weeks, sales says 8" into a false "10."
- **One report artifact** — `<topic>_Audit.md` with standard frontmatter + provenance, so the audit is itself a corpus artifact agents can read. `--report-only` for scheduled runs.
- **Phase-2 action menu** — apply link/style fixes, draft stubs for suggested-but-missing concept notes, hand `research_gaps` next-actions to gap-driven `discover` so "you're thin on X" becomes "preview candidates for X."

Why this version: verify gates three later milestones — the audit's gap-filling branch, `ask --save` re-ingestion (0.12), and trustworthy source breadth (0.11) — so it must come before the funnel widens, not after. Trust is also where the competitive leaders are racing (contradiction detection, lint, draft-promotion), and a *verified* corpus is the one claim none of them can make: their trust features check structure; this checks claims against receipts. Audit lands beside it because verify is the substance and audit is the screenshot-able surface — together they are one legible "trustworthy corpus" story.

### 0.11.0 — Source breadth and audio capability

The three-source baseline (YouTube, websites, arXiv) was calibrated to "sources with public APIs and existing transcript layers." A validation run against two X posts revealed two simultaneous gaps: X itself was unsupported, and any source with audio but no native captions (X-native video, podcasts, conference talks, Loom, Vimeo) had no transcription path. Both shipped during the 0.9 validation work — they're now the foundation a focused breadth pass builds on.

**What the shipped 0.9 work left ready (do not re-design here):**

- `distill ingest <url>` thin dispatcher (routes by host to the right adapter; falls back to existing `distill site` / `distill latest` / `distill paper` for unknown hosts). Mirror of the local-file dispatcher 0.9 introduces for paths.
- X (Twitter) adapter via the public `cdn.syndication.twimg.com` embed endpoint — legitimate publisher path, not anti-bot evasion. Emits `Tweet.md` + `Transcript.txt` (when video attached) + `Insights.md` with standard frontmatter.
- Whisper transcription layer (`distill/ingestors/transcribe.py`) with **local-first provider routing**: `faster-whisper` on CUDA or CPU is the default, then a cloud ladder of xAI Grok STT (~$0.10/hr, reuses the existing `XAI_API_KEY`) before OpenAI Whisper-1 (~$0.36/hr) as the final fallback. Each cloud tier is skipped when its key is absent. Per-source `vocabulary_hint` derived from the source's own metadata (tweet text, author handle, paper title, page H1) biases proper-noun spelling (Whisper's `initial_prompt`, Grok STT's `keyterm`) — closes the "Claude Code → QuadCode" mistranscription class.
- `distill doctor` Transcription section: surfaces faster-whisper version, CUDA device count + supported compute types, cached Whisper models, and the routing line ("local-first → cloud fallback" vs. cloud-only vs. unavailable) so provider surprises are visible before a run.

**What this pass adds (the five-adapter set):**

- **Podcasts** — RSS-first by design: feed ingestion, episode `.mp3` download via stdlib, publisher transcripts when the feed carries them, local transcription otherwise; standard analysis prompt tuned for interview/conversation shape. RSS is the *durable* path — the June 2026 research confirmed yt-dlp's YouTube route is degrading under PO-token/SABR enforcement, so audio breadth must not lean on it. Closes the largest single content surface for primary practitioner audio, and it is confirmed white space: no open-source tool does structured insight extraction from podcasts (the incumbents — Snipd, Podwise — are closed consumer apps). Reuses the transcribe.py provider routing wholesale; consider NVIDIA Parakeet TDT v3 as an optional English fast path (better WER than Whisper large-v3 at ~20x the throughput on the Open ASR Leaderboard) and pyannote community-1 for speaker diarization, with Whisper staying the multilingual default.
- **GitHub repos** — README + structured subset of issues/discussions/releases, via the public REST API (no auth required at low rate, `GITHUB_TOKEN` lifts limits). Critical because for any OSS tool, the repo itself is the primary source — not the marketing page. Emits `Repo.md` + `Insights.md`. **Extract insights, don't concatenate:** every OSS repo tool (Repomix, Gitingest) stops at packing files into a prompt; structured repo *understanding* exists only in closed products (Cognition's DeepWiki, Copilot Spaces). Distillr's per-item insight format applied to repos is unoccupied ground; tree-sitter compression (Repomix-style) is acceptable as preprocessing, never as the output.
- **Generic audio/video files** — `distill ingest <path-to-.mp3-or-.m4a-or-.mp4>` (or `.wav`, `.opus`) routed through the Whisper layer + a "raw media" analysis prompt that expects no native structure. Drops out almost free from the 0.9 local-file dispatcher + the Whisper layer; covers conference talks distributed as files, downloaded Loom recordings, voice memos, interview MP3s.
- **Substack / newsletter posts** — RSS-driven site ingest with the existing site scraper plus a small adapter for Substack's predictable per-post HTML structure (header, byline, body, footnotes). Most of the work is RSS feed enumeration and the per-post structural extraction; the analysis prompt is the existing site-page prompt.
- **X (already shipped in 0.9 validation)** — listed here for completeness; this pass hardens it with: tests, MCP `find_insights`-style read tool, optional thread expansion (fetch parent + reply chain), and consolidated cost/run tracking through the standard `CostTracker` / `RunSummary` plumbing.

**Adapter contract (enforced by reviewer checklist, not lint):**

Every new adapter must implement these five behaviors so it composes with the rest of the system:

1. **Capture as a deterministic function of public input** — given the same URL or path, the captured artifact bytes are reproducible (modulo upstream changes). No login walls, no captcha defeat, no scraping that breaks if the site adds anti-bot. The X adapter's syndication-endpoint approach is the reference shape.
2. **Emit conventional artifacts** — at minimum a raw artifact (`Tweet.md` / `Episode.md` / `Repo.md` / `Page.md` / `Paper.md`) and an `_Insights.md`, both via `write_markdown_artifact` with `base_frontmatter` + `ProvenanceFields`. No new directory layouts or filename schemes — file under `library/topics/<topic>/<source>/<identity>/`.
3. **Pass source metadata to downstream model calls** — Whisper transcription gets a `vocabulary_hint` derived from the source's own text; analysis prompts get author/title/date in their context. The pattern that fixed proper-noun mistranscription for tweets generalizes: the source knows what's in it.
4. **Cost-track through `CostTracker`** — every LLM and transcription call records to the run tracker with a meaningful `call_type`. No off-ledger spend.
5. **MCP tool parity** — every CLI ingest verb has a matching MCP tool that takes the same arguments and produces the same artifacts. Agents and humans see the same affordance.

**Calibration debt — the real risk of "more sources" and how this scope bounds it:**

The roadmap excludes additional cloud LLM providers (see "[intentionally not in scope](#intentionally-not-in-scope)") precisely because each provider is calibration debt — prompts that work well on one regress on another. The same logic applies to sources: a paper-style analysis prompt under-extracts on a podcast (different structure, different signal density, different listener stance). This pass caps the breadth at five adapters with the contract above so the 1.0 golden-corpus eval gate stays tractable. Further sources — LinkedIn, Bluesky, Mastodon, HackerNews, Reddit, Discord exports, Slack archives, slide decks — defer to the post-1.0 plugin system the roadmap already gestures at. The cap is deliberate; if a community contribution wants to add a sixth adapter, the contract above is the gate, not the version number.

Two additions ride along with the adapters:

- **YouTube-path resilience.** The PO-token/SABR churn that makes RSS the right podcast default also threatens the core YouTube ingestion path. Retry/backoff/resume-friendly subtitle handling (roadmap §4) graduates from backlog to part of this pass: a breadth release that adds fragile sources while the flagship source degrades quietly would be net-negative.
- **Paper-metadata sources refresh.** Prefer OpenAlex (CC0, free dumps) and Ai2's Asta Scientific Corpus MCP over the classic Semantic Scholar API (changelog silent since late 2024, restrictive keys) for the recency/citation ranking signals in §6.

Why this comes after 0.10: the breadth pass needs the shipped 0.9 `distill ingest` dispatcher as a real entry point, and every new adapter's output now lands behind the verify hook — podcast transcripts and repo digests are noisier inputs than arXiv PDFs, so widening the funnel *after* the trust gate exists is the order that keeps the corpus trustworthy. 0.12's stale-detection + budget guardrails would likewise mis-fire if applied to half-built adapters. The Whisper layer + X adapter shipped in 0.9 are the cheap part; the four remaining adapters are the disciplined-execution part.

### 0.12.0 — Compounding corpus

The "leave it running" version: hands-off operation for a daily-driver research system, plus the output->input loop that makes the corpus compound with use. Everything here lands on top of a verify hook and audit surface that have been proven for two versions.

**Operational polish.**

- Scheduled refresh via cron / Task Scheduler; goal-file refresh hook for `distill watch`. The same scheduler also runs `distill audit --report-only` on a cadence (the "monthly health check" automation), so corpus drift is caught without manual prompting and the audit report lands as a dated artifact.
- Semantic dedup across videos, pages, and papers (artifact-preserving — source-origin attribution stays in the synthesis layer).
- Stale-detection and auto-reanalysis triggers when prompts or models change materially. **Artifact-level, not blanket.** Each artifact's frontmatter already records `prompt_id` and `model_version` (since 0.7); stale-detection inverts that index and re-analyzes only the artifacts on the critical path of the changed component. Blanket re-runs on every prompt bump don't scale once the corpus passes a few hundred artifacts. **Staleness is surfaced, not just acted on silently:** a stale synthesis is more dangerous than stale source data because it reads with the confidence of well-written prose while being wrong (the "confident misinformation" failure mode), so a stale flag rides the synthesis frontmatter and the dashboard rather than living only in a `distill health` console run.
- Cost anomaly detection and budget guardrails per topic and workflow.
- Live per-item progress plus resume-friendly failure handling for long mixed-source runs, so transcript-rate limits or slow site ingestion are visible without manual filesystem inspection.

**Output->input loop (`distill ask`).**

This is the mechanic the Karpathy "LLM Wiki" pattern is built around and the one half of the loop distillr does not yet have: you ask the corpus a question, you like the answer, and the answer *becomes corpus* so the next question starts from a richer base. Today distillr is excellent at `input -> corpus` (capture, analyze, synthesize) but every output (`report`, `research-brief`, `synthesize`) is a **terminal artifact** — nothing re-ingests it, and there is no lightweight query verb at all. The compounding "day 1 basic, day 100 an asset" behavior the pattern promises depends entirely on closing this loop.

- **`distill ask "<question>" --topic <t>`** — query the corpus (reuse the `find_insights` retrieval path), answer grounded only in the topic's artifacts, and write a provenance-stamped answer to an answers layer (`library/topics/<t>/answers/<slug>_Answer.md`, standard frontmatter, `[[backlinks]]` to every cited source). MCP parity: an `ask` tool with the same arguments.
- **Optional re-ingest** — `--save` (or a prompt) promotes a liked answer into the corpus so synthesis and future answers can build on it. This is the compounding step.
- **Gated on the 0.10 verify hook — this is non-negotiable.** The exact failure mode this risks: "the AI writes something slightly wrong, you save it back, and the next answer quietly builds on a mistake." Re-ingest therefore runs the run-time verify hook on the answer first; an answer with an unsupported load-bearing claim is refused (or flagged and quarantined under `--verify warn`) rather than silently folded in. The verify hook is *why* this loop is safe in distillr and unsafe in the unguarded folder-and-CLAUDE.md version. It is also why this lands two versions after the hook and audit shipped — the trust surfaces exist and have been exercised before outputs start feeding back in.

**Sub-agent-friendly MCP surface.**

Today's `find_insights(topic, query)` returns full artifact bodies. For a 50-paper corpus, an agent that queries this blows past most context windows. The Agent SDK's sub-agent pattern (delegate "do X over Y, here's bounded context, return result") needs a token-bounded query primitive:

- **`find_insights_summary(topic, query, max_tokens=4000)`** — same query, returns a synthesis sized to fit a sub-agent's context. Implementation: existing `find_insights` plus a one-shot LLM compression pass over the matching slice with the query as the focus. Cached by `(topic, query, max_tokens, corpus_revision)` so repeated sub-agent calls don't repay the compression cost.
- **`list_topic_summary(topic)`** — paragraph-length topic overview pulled from the topic synthesis frontmatter, used when a sub-agent is choosing which topic to query.

Why this version: stale-detection and semantic dedup need stable artifact identity and provenance (0.7 + 0.8), the ask loop needs the 0.10 verify hook and audit, and the sub-agent MCP tools depend on the 0.9 two-pass synthesis claim intermediate (so the summary pass has structured inputs rather than re-extracting from prose) plus the consolidated paths-not-payloads surface from the agent-legible pass. 0.12 is where everything underneath compounds.

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
- **Golden corpus eval gate.** A frozen ~20-paper reference corpus ships with hand-checked golden insights (claims, methods, limits sections) plus hand-checked concept-playbook output (which concepts cross threshold, which polarities, which intervals). CI runs the full analysis + concepts pipeline against it with mock LLM responses fixed for reproducibility, and gates on per-section agreement with the golden output. Catches the regression class that the rest of the quality bar misses — prompt drift, model swaps, and silent degradation of section extraction or concept polarity assignment — none of which show up in coverage, type, or lint gates. *(0.9.6 shipped the front half: the `distill/eval/` harness + scoring + advisory judge + `distill eval` command for interactive cost × quality model selection. 1.0 turns the same fixtures + scoring into a blocking CI gate with mock-fixed responses. Follow-up: an `eval_models` MCP tool so agents can request the comparison.)*
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

Why this version: 1.0 is a stability *and* quality claim. It's the version external systems can build on without expecting churn, and the version a new contributor can land a clean PR in without a long onboarding tail. Competitively, the agent-integration story now ships much earlier (the agent-legible 0.9 pass); 1.0's job is the presentation pass, onboarding docs, and stable contracts that convert "technically superior" into "actually adopted" — and by this point the story writes itself: verified, agent-legible, multi-source, user-owned.

## Looking beyond 1.0

Not committed. Notes on directions worth thinking about once 1.0 stability is in place.

- **Shareable goal-files / topic recipes.** A `discover` goal-file is already an executable description of a corpus — the same "idea file as a prompt you hand an agent" format Karpathy's gist popularized. The direction is making goal-files portable artifacts: publish or share a goal-file (with its `--site-seeds`) so someone else can reproduce or refresh a corpus from the research *intent*, not just receive the output. Plain Markdown like everything else, no lock-in, and it fits the post-1.0 plugin-boundary timing rather than the critical path.

- **Provider breadth on an eval-gated adapter contract.** The `distill/llm` router already abstracts provider+model behind workload tags (grok, gemini, ollama, lm_studio today). The post-1.0 direction is a documented provider-adapter contract so the same workloads run on more backends without each one becoming silent calibration debt — **local** (Ollama / LM Studio on macOS, Linux, Windows; consumer GPUs through DGX Spark-class workstations) and **cloud** (xAI, Google, Anthropic, OpenAI, AWS Bedrock, Microsoft Foundry). The gate is `distill eval`: a model graduates from "wireable" to "calibrated and eval-recommended" only by clearing the cost x quality bar on the golden fixtures, and the same harness produces the cross-provider, cost-aware comparison that says which backend to use for which workload (and whether a free local model now beats the cloud floor). You still opt in — distillr ships no uncalibrated default — so this is how breadth is added *without* abandoning the no-calibration-debt discipline (see [Intentionally not in scope](#intentionally-not-in-scope)). The eval gate is the thing that pays the calibration debt down cheaply instead of guessing.

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
- `import-linter` and `pip-audit` promoted into blocking CI; `pre-commit` made identical to CI; `xfail_strict`; branch coverage; SBOM on release. (Dependabot was trialed in 0.8.3 and deliberately dropped — dependency bumps are reviewed manually.)
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
- **Auto `uv lock --upgrade` in CI.** A manually reviewed upgrade PR (running full CI against the new lock before merge) is strictly safer than CI silently re-resolving — the un-reviewed auto-upgrade is the same dependency-float failure mode 0.8.3 exists to kill, just relocated. (Automated bump bots are also declined; bumps are reviewed by hand.)
- **Power-of-10 hard gates that do not fit a Markdown pipeline** — two-asserts-per-function, fixed loop bounds, and no-recursion are flight-software rules for hard-real-time control loops. The in-character subset is already convention here: module-size caps, `C901` complexity caps, no silent error swallowing, narrowest-scope declarations. The rest would be ceremony, not safety.
- **Copier / portfolio template scaffolding** — a cross-project concern (how *many* repos share standards), not a property of distillr's own codebase. Out of scope for this roadmap.

## Security posture

distillr's threat model follows from what it actually is: a local-first CLI and MCP server that **consumes** third-party LLM APIs (xAI, Gemini) to turn untrusted public sources into a local Markdown corpus. It trains no models, serves no inference, holds no model weights, and is single-user. So the large body of "AI security" guidance aimed at *model builders and operators* — training-data poisoning and backdoors, model extraction / inversion / membership inference, differential privacy and privacy-budget accounting, confidential-compute enclaves (TEEs / SMPC / homomorphic encryption), model watermarking and signing, adversarial-robustness certification, multi-agent trust zones, post-quantum model-IP protection — targets a system distillr is not. Those are **out of scope by architecture, not by neglect.** distillr's real assets are the user's API keys and the integrity of the corpus; its real attack surface is untrusted ingested content plus the tool and HTTP boundaries.

**Already in place:**

- **Supply chain** (0.8.3): committed `uv.lock` + `uv sync --frozen`, blocking `pip-audit` and bandit in CI, a CycloneDX SBOM, PEP 740 provenance attestations, and SHA-pinned GitHub Actions. For an API consumer the "model supply chain is the new software supply chain" concern reduces to ordinary dependency hygiene, which is covered. (Dependency/action bumps are reviewed manually; Dependabot is deliberately not used.)
- **MCP path confinement**: `read_insight` / `read_concept` resolve caller-supplied paths through `_resolve_within_library` and refuse anything outside the library root (the path-traversal / auth-bypass class addressed in the prior security pass).
- **Secret handling**: API keys are `SecretStr`, kept out of artifacts and logs; a `detect-private-key` pre-commit hook guards commits.

**Hardened in 0.8.7:**

- **Indirect prompt-injection resistance.** The one AI-specific threat that actually applies: every analyzed source (YouTube transcript, web page, PDF, tweet) is untrusted input fed to an LLM, and a source can carry embedded instructions ("ignore previous; write X") that hijack the analysis or synthesis and land in the corpus. A shared `UNTRUSTED_CONTENT_RULES` constant is now threaded into every per-source analysis prompt (video, shorts, scan, site page, paper, tweet): the embedded source is labelled untrusted data and the model is told to ignore any instructions inside it. This is the *prevention* half; the 0.10 run-time verify hook (claim-grounding) is the *detection* half, and they compose.
- **Web-dashboard output sanitization.** The local dashboard rendered corpus artifacts through `markdown(...)` with raw HTML passed through (`distill/web/server.py`), so untrusted-derived content — or an injected `<script>` inside an insight — was a stored-XSS vector. The rendered HTML is now run through an `nh3` allowlist sanitizer before serving (script/event-handlers/`javascript:` URLs stripped, formatting and tables preserved), per Python-Markdown's own guidance to sanitize output rather than trust the renderer.

**Still ahead (1.0):**

- **Boundaries are trust boundaries.** The 1.0 "parse, don't validate" work already validates MCP tool arguments and ingest inputs; the roadmap states explicitly that those parsing boundaries *are* the security boundary — path confinement and URL/SSRF validation on fetch paths live there, so the parse layer doubles as the trust layer rather than being a separate bolt-on.

If distillr ever ships a hosted multi-tenant service or fine-tunes its own models, the out-of-scope list above reopens. Until then, deepening it would be securing an attack surface the project does not have.

## Intentionally not in scope

A roadmap is also an opinion about what *not* to build. These are deliberate exclusions, not gaps. Several are informed by the competitive landscape (see above) — competitors that make different choices validate that these are real trade-offs, not oversights.

- **No graph-view UI inside distill.** Obsidian / Logseq / Dendron already do this well; reimplementing duplicates effort without adding value. The Obsidian-native milestone (0.7) is the answer. (SwarmVault builds its own graph view; we get it free from the ecosystem.)
- **No proprietary editor, mobile app, or cloud-hosted SaaS.** The whole point is plain-text Markdown with no lock-in. A hosted version would create exactly the dependency the project exists to avoid.
- **No general-purpose RAG / vector-store / SQLite index.** distillr is opinionated about the corpus shape and the analysis pipeline. Embeddings are an implementation detail (used selectively for dedup, possibly inside `find_insights`), not a primary surface. Users who want a generic RAG toolkit have LangChain and LlamaIndex. (SwarmVault and Lacuna-wiki add SQLite/DuckDB; we deliberately avoid this — pure-Markdown + git-friendly is the defensible niche for serious researchers.)
- **No multi-user / auth / collaboration layer.** Single-user local tool. Shared corpora are a `git` problem, not a distillr problem.
- **No additional cloud LLM providers by default.** Each provider is calibration debt — prompts that work well on one model regress on another. Users can wire OpenAI / Anthropic / Mistral / etc. through the 0.3 router, but distillr won't ship default model policies for them. Local providers are the exception because they carry the local-first promise. (Transcription providers are not subject to this exclusion: speech-to-text carries no analysis-prompt calibration debt, so the Whisper transcription ladder ships a cloud tier — xAI Grok STT, reusing the already-required `XAI_API_KEY` — beneath the local-first default.) The exclusion is against *uncalibrated defaults*, not against provider reach: post-1.0, the eval-gated adapter contract (see [Looking beyond 1.0](#looking-beyond-10)) is the path by which a backend — local or cloud (Bedrock, Foundry, Anthropic, OpenAI, Google, xAI) — graduates to calibrated-and-recommended by passing `distill eval`, rather than being shipped blind.
- **No plugin / extension system before 1.0.** Premature abstraction. The right plugin boundaries become obvious only after the internal architecture from 0.3–0.5 has carried real workloads. Revisit post-1.0.
- **No real-time collaboration or sync service.** Markdown + git is the answer. distillr won't compete with Obsidian Sync, Logseq Sync, or Syncthing.
- **No "install skills into your agent" model.** obsidian-wiki (Ar9av) takes the approach of symlinking skill files into Claude Code / Cursor / etc. Distillr's architecture is separation of concerns: distillr is the dedicated memory layer, agents query it via MCP. A thin skill wrapper would be useless for long-running batch ingestion and persistent corpus maintenance — exactly what interactive agents are terrible at.
- **No anti-bot / paywall / login-walled scraping.** Playwright handles legitimate access; defeating hostile defenses is whack-a-mole that pulls focus from the analysis pipeline and creates legal/ethical surface area.
- **No "cheap mode" that compromises fidelity.** The product premise is "as good as we can possibly make it" regardless of whether inference runs locally or in the cloud. Local models exist to make the corpus *always current* at zero marginal cost, not to produce worse outputs faster. Cost reduction happens through local inference, compaction, and JIT context — never through cheaper prompts that produce worse outputs. A local insight must be good enough that synthesis and expert queries can trust it without qualification.

These exclusions are load-bearing, not permanent. They get revisited if the constraint that drives them changes.

## Full backlog

The area-by-area backlog (stay-current, dashboard, papers, cross-source intelligence, context engineering, discovery loop, etc.) lives in [`docs/roadmap.md`](docs/roadmap.md). Items there will be tagged with the milestone above where they land in a follow-up pass.

Design principles drawn from the context-engineering literature are summarized in [`docs/architecture.md#context-engineering-principles`](docs/architecture.md#context-engineering-principles).
