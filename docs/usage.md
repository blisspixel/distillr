# Usage

Full command reference. For the short version, see the README.

> Every command prints contextual next steps - file paths and suggested follow-up commands - so you can usually find your way without re-reading this doc.

## Table of Contents

- [Goal-aware discovery (cross-source)](#goal-aware-discovery-cross-source)
- [Analysis lens (per-topic intent)](#analysis-lens-per-topic-intent)
- [YouTube: Stay current on a topic](#youtube-stay-current-on-a-topic)
- [YouTube: Ramp up fast](#youtube-ramp-up-fast)
- [YouTube: Channel watch and catch-up](#youtube-channel-watch-and-catch-up)
- [YouTube: Topic watch (recurring)](#youtube-topic-watch-recurring)
- [Recurring research profiles](#recurring-research-profiles)
- [Websites](#websites)
- [arXiv papers](#arxiv-papers)
- [Reports](#reports)
- [Research briefings and deep synthesis](#research-briefings-and-deep-synthesis)
- [Library management](#library-management)
- [Concept playbook and recovery](#concept-playbook-and-recovery)
- [Viewing and exporting](#viewing-and-exporting)
- [Diagnostics](#diagnostics)
- [Global output controls](#global-output-controls)

## Goal-aware discovery (cross-source)

When you have a **research goal** rather than a keyword query, `distill discover` is the front door. It takes a natural-language goal, has Grok generate candidate search queries for papers and videos, lets you optionally add curated website seed files or trusted website sections, and then does a single unified LLM rerank of the combined pool *against the goal* (not against keywords). You see one ranked cross-source table and only commit to ingestion after confirming.

On a **fresh topic** (no artifacts yet), discover leads with a *size-then-approve* menu instead of auto-ingesting: it shows the ranked candidates and 2-3 sized options - *Excellent / Including good / Everything worthwhile* - each with its source breakdown and its own spend estimate, and ingests the option you pick. `--yes` skips the menu (rigor-filtered auto-ingest); `--size` forces the menu on a topic that already has artifacts.

```bash
# Inline goal
distill discover "help an AI become a great music composer" --topic music --preview
distill discover "2026 enterprise search architectures" --topic enterprise-search --yes

# Goal file - reusable across refreshes
distill discover --goal-file private/ai-composer-goal.md --topic music --yes

# Goal file + curated sites (official docs / vendor pages / labs)
distill discover --goal-file private/agent365-goal.md --topic agent365 \
  --site-seeds private/agent365_sites.json --site-limit 10 --preview

# Goal file + trusted site expansion
distill discover --goal-file private/agent365-goal.md --topic agent365 \
  --trusted-site https://learn.microsoft.com/en-us/microsoft-365/agents \
  --site-limit 10 --preview
```

Flags:

- `--topic / -t` - topic folder to file outputs under (defaults to a slug of the goal)
- `--paper-limit` / `--video-limit` - max per-source ingestion targets (default 10 each)
- `--site-seeds` / `--site-limit` - optional curated website seed file plus max site seeds to ingest after rerank (default 10 when supplied)
- `--trusted-site` - trusted domain or section URL to enumerate page candidates from before rerank. May be repeated. Enumeration is bounded to public same-host URLs from sitemaps, TOC/navigation links, and landing-page links; selected pages ingest in exact-page mode.
- `--site-crawl-depth` / `--site-crawl-pages` - opt selected website candidates into bounded shallow crawls. Defaults are depth `0` and pages `1`, which keep exact-page ingest. Trusted-site generated seeds stay section-scoped when depth is above `0`.
- `--papers-only` / `--videos-only` - mutually exclusive, skip the other source type entirely (also short-circuits the LLM query-generation call for the disabled side, so you don't pay for queries the run will throw away). Useful when one source type has thin coverage of the topic.
- `--days / -d` - YouTube recency window (default 365)
- `--shorts / --no-shorts` - include Shorts under 3 min (default off - deeper content favored)
- `--ingest-attachments` - for selected site seeds, pull PDF text and supported embedded-video transcripts into the page corpus
- `--rigor strict|balanced|loose` - quality bar on the rerank score; drops candidates below the level's goal-fit threshold (0.7 / 0.5 / 0.3) before the per-source limits. Default `balanced`.
- `--lens research|practitioner|competitive|academic|general` - the analytical lens each per-source insight is written through. Default: inferred from the goal (e.g. a goal mentioning "research" / "prior art" picks `research`; "vendor" / "enterprise" picks `competitive`). The lens is persisted as the topic's intent (`topics/<topic>/intent.json`), so later `papers` / `latest` / `discover` runs into the same topic inherit it. `competitive` reproduces the pre-0.9.24 enterprise pre-sales sections.
- `--preview` - show the ranked plan without ingesting. Prints a metadata-aware spend estimate as a range (e.g. `~$0.42 (est; $0.29-$0.63)`) and **saves the exact shortlist under an id**; preview-only spend lands in `cost_log.jsonl` as `discover_preview`.
- `--from-preview <id>` - ingest the exact set a previous `--preview` saved, by its id. Skips query-generation and the rerank entirely, so you commit to precisely what you saw. (Mutually exclusive with `--preview` / `--from-gaps`.)
- `--from-gaps` - derive the goal from an existing topic's coverage gaps instead of a written goal (requires `--topic`).
- `--yes / -y` - skip the interactive confirmation / sizing menu (rigor-filtered auto-ingest)
- `--goal-file` - load the goal from a markdown file instead of the positional argument. Enables goal-driven topic refreshes (save `private/<name>.md`, re-run discover periodically).

Rerank scores each candidate on `goal_fit` / `depth_score` / `complementarity_score` / `final_score`. Papers, videos, curated site seeds, and trusted-site page candidates are ranked in the same pool - a documentation page that directly advances the goal can outrank a shallow video, and vice versa. Website candidates are allowlist-driven: `discover` does not perform arbitrary web search. It reranks the exact URLs from `--site-seeds` plus public same-host candidates enumerated from repeated `--trusted-site` domains or section URLs, then ingests selected pages in exact-page mode unless `--site-crawl-depth` opts into a bounded shallow crawl. Site preview rows include the exact URL, section label, discovery source, and sitemap freshness date when known. Links found in landing-page TOC/navigation containers are labeled `toc link` and listed before generic landing links.

Video candidate discovery prints the free metadata summary before reranking,
for example `Found 88 videos + 12 Shorts, ~47h of content across 5 search(es)`.
When some durations are missing, the line labels the total as known content
and reports the unknown-duration count.

The pre-run spend estimate scales per-video cost by duration and **self-calibrates** against your `cost_log.jsonl` history (per-source rates from clean single-source runs, falling back to defaults when history is thin), so it sharpens as you use the tool. Typical cost: `--preview` ~$0.05, full run ~$1-3 depending on paper/video count.

During ingestion, selected papers and site seeds print per-item progress with
phase, item count, completed count, failed count, running spend, and ETA once
enough items have completed. Selected videos use the same video progress
surface as `latest` and `catch-up`.

## Analysis lens (per-topic intent)

Every per-source insight is written through an **analysis lens** that fits what the corpus is for, instead of one fixed persona. The lenses are `research`, `practitioner`, `competitive`, `academic`, and `general` (the neutral default). `competitive` is the enterprise pre-sales framing (Vendor Watch, Business Value Signals, Customer Conversation Starters); the others drop the sales sections for ones that match the subject matter.

The lens lives in a per-topic **intent** (`topics/<topic>/intent.json`). Set it once and every later ingest into that topic - `discover`, `papers`, `latest`, and the MCP tools - reads sources through it.

```bash
# Set it explicitly (no re-ingest needed; applies to future ingests)
distill intent set agentic-harness --lens research
distill intent show agentic-harness
distill intent clear agentic-harness          # revert to neutral 'general'

# Or set it inline on any entry point (persists for the topic)
distill discover --goal-file private/goal.md --topic agentic-harness   # goal drives the analysis; lens stays general
distill papers "agent memory systems" --topic memory --lens research
distill latest "Fabric best practices" --topic fabric --lens practitioner
```

The `--goal` is carried into every analysis prompt, so the model adapts the analysis to it regardless of lens. `--lens` selects the section template + analyst stance (`general` default, or `research` / `practitioner` / `competitive` / `academic`); it is not guessed from the goal text. Existing insights already on disk keep their original lens until re-analyzed; a `distill resynthesize <topic> --two-pass` refreshes the cross-source synthesis (and adds the thesis rung) cheaply.

## YouTube: Stay current on a topic

```bash
# One-shot: find and distill the best recent coverage for a query
distill latest "Microsoft AI news" --topic microsoft-news --days 14 --limit 20 --report

# Tight recency window for rumor-heavy / breaking topics
distill latest "Claude Code leak analysis" --topic claude-code-leak --hours 20 --limit 20 --report
```

`distill latest` defaults to a date-first, Shorts-inclusive, multi-query discovery pass tuned for stay-current workflows. `--hours` gives sub-day precision. For rumor-heavy or April 1 style topics, the selector leans skeptical (favors concrete evidence terms).

`--rigor strict|balanced|loose|off` adds a quality bar on the rerank score (video thresholds 0.6 / 0.4 / 0.25), dropping weak picks before the channel cap; default `off` (unchanged behavior), and it needs the LLM rerank - under `--no-rerank` / `--top-by-date` an explicit bar is skipped with a warning. The thresholds are calibrated per command (lower than `discover`'s, since `latest` is a single-source relevance ranker rather than a cross-source curation gate - see [`architecture.md`](architecture.md) "Rigor calibration").

During processing, `distill latest` prints per-video progress after each item:
completed count, failed count, running spend, and ETA when enough videos have
completed. Live transcript and analysis phase labels include the same running
spend.

For strict "last N uploads in the window" semantics - bypassing both the LLM rerank and the heuristic relevance/depth mix and sorting purely by upload date - pass `--top-by-date`. Channel cap still applies, and `--rerank` is force-disabled so query-expansion spend isn't billed for output that's then ignored.

```bash
distill latest "Sora 2 demos" --topic sora --days 7 --top-by-date --limit 5
```

After a run, inspect what changed:

```bash
distill diff <topic>             # against last watch run or fallback window
distill trends <topic>           # momentum over recorded diff windows
```

## YouTube: Ramp up fast

```bash
# Learn a topic from recent YouTube coverage (no report by default)
distill learn "Microsoft Fabric best practices"

# Generate a quick brief after learning
distill brief "Microsoft Fabric best practices"

# Or ramp up and produce a full report in one command
distill ramp-up "Microsoft Fabric best practices" --topic fabric --report
```

Previewing selection without processing:

```bash
distill search "Microsoft Fabric best practices"    # preview best-pick set
distill explore "Microsoft Fabric best practices"   # broader landscape scan
distill latest "<query>" --preview                  # same as latest, preview only
```

Analyze a specific video or test a single channel:

```bash
distill video https://www.youtube.com/watch?v=abc123
distill channel https://www.youtube.com/@SomeCreator --limit 2
```

## YouTube: Channel watch and catch-up

The watch list is for channels you want to stay current on without running full analysis every time. Each watched channel has its own lookback window and optional custom analysis instructions.

```bash
distill watch add https://www.youtube.com/@SomeCreator

# Custom lookback + per-channel extraction instructions
distill watch add https://www.youtube.com/@DealsChannel --days 2 \
  --instructions "Extract top 10 deals: item, price, link, why it's a deal"

distill watch                                       # see the list
distill watch days SomeCreator 7                    # update lookback
distill watch instructions DealsChannel "..."       # update instructions
distill watch remove OldChannel                     # stop watching

# Refresh all watched channels (uses each channel's own lookback)
distill catch-up
distill catch-up SomeCreator                        # refresh one channel
distill catch-up --days 1                           # override lookback
distill catch-up --dry-run                          # preview

# Upgrade lightweight scan outputs to full 2-pass analysis
distill reanalyze deals --deep
```

Scan mode (used by `catch-up`) is lightweight (~$0.001/video). During
processing, `catch-up` prints per-video completed count, failed count, running
spend, and ETA when enough videos have completed. Use `reanalyze --deep` when
you want the full 2-pass analysis on a video you flagged from a scan.

## YouTube: Topic watch (recurring)

Recurring queries - "Microsoft AI news" daily, "Azure AI updates" weekly - with budget guardrails and per-run delta outputs.

```bash
distill topic-watch add "Microsoft AI news" --topic microsoft-news \
  --cadence daily --days 1 --limit 10

# Ranking mode (freshness | balanced | popularity)
distill topic-watch add "..." --topic ... --cadence daily --ranking freshness

# Budget guardrails
distill topic-watch add "Azure AI updates" --topic azure-ai --cadence weekly \
  --limit 20 --max-run-cost 1.50 --monthly-budget 12
distill topic-watch budget azure-ai --max-run-cost 2.00 --monthly-budget 15

# Pause / resume / run
distill topic-watch pause azure-ai
distill topic-watch resume azure-ai
distill topic-watch run --preview
distill topic-watch run
distill topic-watch run azure-ai --ignore-budget   # explicit override
```

Each topic-watch run leaves:

- `library/topics/<topic>/<topic>_Watch_Update.md` - per-watch delta summary
- `library/topics/<topic>/<topic>_Topic_Diff.md` - reusable topic-level change report
- `library/topics/<topic>/change_history.jsonl` - timestamped change counts
- `library/topics/<topic>/<topic>_Topic_Trends.md` - momentum over recent diff windows
- `library/library_Latest_Changes.md` - library-level rollup
- `library/library_Watch_Alerts.md` - digest of notable changes (also exposed via MCP at `distill://watch-alerts`)

## Recurring research profiles

Research profiles are saved source plans for topics you refresh repeatedly.
They bind a topic, goal file, trusted feeds, YouTube channels, domains,
repositories, saved queries, freshness limits, and cost mode in one YAML file
under `library/profiles/`.

```bash
# Inspect the exact candidate rows and commands without writing analysis artifacts
distill profile preview ai-developer-news
distill profile preview examples/profiles/ai-developer-news.yaml --no-fetch

# Plan a run. This prints the same command list plus the durable state path.
distill profile run ai-developer-news
distill --json profile run ai-developer-news --no-fetch

# Execute approved commands through the existing Distill ingest and analysis paths.
distill profile run ai-developer-news --yes
distill --cost-mode no-metered profile run ai-developer-news --yes
```

`profile run` is approval-gated. Without `--yes`, it prints or emits the plan
and does not execute commands or write run state. With `--yes`, it executes the
approved argv rows from preview, captures each exit code and output tail, and
writes state to `library/.distill/profiles/<profile>/run_state.json`.
JSON output includes `next_actions` rows with the same argv, approval, write
scope, verifier, and loop metadata shape used by audit next actions, so an
external runner can execute profile refreshes without scraping console text.

Resume policy is structural: exact feed items and exact YouTube videos are
marked complete on success, while standing seeds such as feeds, channels,
domains, repositories, and saved queries remain repeatable so recurring
profiles keep checking for new material. Failed commands stay retryable and are
recorded in the state file.

`distill audit all` includes recurring profile health from local files and run
state: invalid profile files, missing goal files, stale or missing runs,
recorded command failures, invalid run state, and profiles whose local corpus
is still thin relative to the saved source plan.

```bash
distill doctor --adapters
distill --json doctor --adapters
```

The adapter doctor is read-only. It checks candidate CLI adapter binaries,
version/help commands, required structured-output flags, route class, support
statement status and detail, metered environment blockers, and the required
`adapter-workload.v1`, `adapter-native-usage.v1`, and `adapter-result.v1`
scratch contracts. Support details include the
checked date, source URLs, required evidence, notes, and whether the statement
is current for no-metered routing. It also scans known local adapter config
files and selected JSON auth-command outputs for metered-route and session
markers, reporting marker names without secret values. The manifest contract
includes no-metered rejection of API-key blockers, broader metered-route
blockers, metered auth, and metered usage allowance, plus the before/after
scratch write check future runners must use and structured `quota_stop`
metadata for future quota and rate-limit stops. A reusable runner
primitive can execute exact argv
arrays inside scratch with shell disabled and API-key environment variables
stripped. A workload runner can load a checked `adapter-workload.v1` package,
execute an exact argv in scratch, and reject results that read outside the
package, write outside declared outputs, or report a different cost mode. A
native result writer can turn captured CLI output plus explicit native usage
metadata or a validated `adapter-native-usage.v1` scratch file into a validated
`adapter-result.v1` scratch manifest. A
ledger helper can convert verified adapter manifests into cost-tracker rows and
metadata. The Codex read-only command planner records the future
`codex exec --sandbox read-only` argv shape, the Claude planner records a
blocked `claude -p --input-format text --output-format json` shape, and the
Grok planner records a blocked `grok --no-auto-update --prompt-file ...
--output-format json` shape. The Gemini planner records a blocked
`gemini --approval-mode plan --output-format json --prompt ""` shape. The
Antigravity planner records a blocked `agy -p` shape.
Plans include staged prompt, schema, result capture, native usage capture, and
allowed scratch capture metadata; Claude schema paths can be inlined from
staged JSON schema files. Plans stay blocked until support, auth, and eval
adapter gates exist. Distill can parse Codex JSONL `turn.completed` usage and
Claude JSON `usage` output into the native usage contract. Grok, Gemini CLI,
and Antigravity also have adapter-specific native usage parsers and capture
writers for JSON-style usage output. Workload runner capture hooks can write
validated scratch manifests from those captured outputs. Gemini stays blocked
on native schema enforcement. Antigravity stays blocked because local help
exposes no reliable headless JSON or native schema surface. A generic stdout
capture helper can write captured stdout to `result.txt`, but it still requires
a real validated native usage file. Distill still does not expose any
plan-quota adapter as an eligible route by itself.

The standard `distill doctor --json` output also reports portable local route
availability for Ollama and LM Studio under `local_inference.route_availability`.
Those rows are route evidence only: provider, model when known, checked time,
service availability decision, and blocked reasons. They are intentionally not
account evidence and must not contain GitHub identities, emails, tokens, or
subscription account identifiers.

## Websites

```bash
# 0. Inspect exact-page versus shallow-crawl behavior before writing
distill site-batch configs/example_seeds.json --topic example --preview

# 1. Validate raw capture first (writes artifacts, no analysis)
distill site-batch configs/example_seeds.json --topic example-raw --scrape-only --seed-only

# 2. Run exact-page analysis once capture looks right
distill site-batch configs/example_seeds.json --topic example --seed-only

# 2b. Pull PDF text and supported embedded-video transcripts into the corpus
distill site-batch configs/example_seeds.json --topic example --seed-only --ingest-attachments

# 3. Generate the wider Deep Research report
distill report example
```

One URL instead of a batch:

```bash
distill site https://example.com/products/overview --topic example --scrape-only --seed-only
```

Flags:

- `--scrape-only` writes raw capture only (no insights, synthesis, or reports)
- `--preview` prints the resolved seed plan and exits before crawling, model
  checks, or writes. Use `distill --json site-batch ... --preview` to emit the
  same plan as structured JSON for loop runners.
- `--seed-only` processes only the exact input URLs (safest for curated lists)
- `--ingest-attachments` writes `attachments.json` per page and, when possible, extracts PDF text and supported embedded-video transcripts into the page corpus
- `--same-section-only` allows shallow crawl but keeps discovery inside the same top-level section (`/topic`, `/partner`, `/lab`, `/docs`, etc.)
- `--crawl-prefix /path/branch` on `distill site` keeps followed same-host
  links under a specific path branch.

During `site-batch`, each seed prints a progress line with the current phase,
item count, completed count, failed count, and running spend. A seed-level
exception records a `site-ingest` run issue and the next seed still runs. The
spend cap remains a hard stop. Reused unchanged pages and empty crawls are
surfaced as structural skip outcomes in progress lines and MCP `site_batch`
JSON.

See [`configs/example_seeds.json`](../configs/example_seeds.json) for the seed-file shape. JSON URL objects and collections can set `mode` to `exact-page` or `shallow-crawl`, or use `crawl: false` / `crawl: true` as a boolean alias. Unsupported mode names fail during seed-file loading instead of falling back to a wider crawl. They can also set `crawl_prefix` to keep shallow crawls inside a docs branch such as `/en-us/microsoft-365/agents`. Drop your own `private/<anything>_seeds.json` locally (git-ignored by default).

## arXiv papers

```bash
# Ingest one paper directly from arXiv (abstract + full PDF text + structured insight)
distill paper https://arxiv.org/abs/2602.12670 --topic my-research

# Search arXiv and build a topic-level paper corpus - expands the query,
# LLM-reranks candidates, ingests the top N (all on by default)
distill papers "agent memory systems" --topic my-research --limit 20

# Preview the ranked shortlist without ingesting (free-ish, ~$0.01)
distill papers "agent memory systems" --topic my-research --limit 20 --preview

# Old behavior: literal query, newest-first, blind ingest of top N
distill papers "agent memory systems" --topic my-research --limit 20 \
  --no-expand --no-rerank --sort date

# Mixed-source synthesis across videos, sites, and papers filed under one topic
distill corpus my-research

# Export citations for Zotero or a reference manager
distill export my-research --what citations --format bibtex
distill export my-research --what citations --format ris
```

Flags on `distill papers`:

- `--limit / -n` - how many papers to analyze after reranking (default 10)
- `--sort relevance|date` - arXiv candidate order before rerank (default `relevance`)
- `--expand / --no-expand` - expand the single user query into up to six arXiv search variants via Grok (default on). Candidates are deduped by `paper_id` across variants. arXiv calls are spaced 3.5s to respect rate limits.
- `--rerank / --no-rerank` - LLM rerank with `RankedPaper` scoring on relevance / depth / novelty / credibility (default on). Runs *before* PDF fetch and analysis, so you don't pay to analyze off-topic picks.
- `--rigor strict|balanced|loose|off` - quality bar on the rerank score; drops papers below the per-source threshold (0.65 / 0.45 / 0.30) before the `--limit` cap. Default `off` (keep the rerank's top picks as before). Needs `--rerank` - under `--no-rerank` the scores are heuristic, off the rerank scale, so an explicit bar is skipped with a warning. When set, the whole candidate pool is reranked so the bar has something to drop, and a `kept X/Y` line shows what it cut.
- `--preview` - show the ranked shortlist and stop. Use this to sanity-check what you'd actually ingest before committing.

During ingestion, `distill papers` prints per-paper progress with the current
phase, item count, completed count, failed count, running spend, and ETA once
enough items have completed. Per-paper analysis failures become structured
`paper-analysis` run issues and the loop continues. The spend cap remains a
hard stop.

The default pipeline (expand + rerank + relevance-sorted) fixes the prior failure mode where generic queries like "music theory deep learning" or "automatic harmonization" pulled in unrelated subfields (physics, image processing) because arXiv's tokenizer has no concept of research intent.

The underlying arXiv query builder is tuned to be tight without being brittle:
- 2-word queries phrase-match (`"music transformer"`) for precision.
- 3+ word queries AND-join tokens so every term must appear without requiring adjacency - this is what makes longer LLM-generated queries work.

For a **goal-driven** corpus across papers *and* videos, use `distill discover` above instead.

Paper outputs land under:

- `library/topics/<topic>/papers/<paper-slug>/metadata.json`
- `library/topics/<topic>/papers/<paper-slug>/<paper-slug>_Paper.md` (abstract, extracted full text, DOI when arXiv supplies one)
- `library/topics/<topic>/papers/<paper-slug>/<paper-slug>_Insights.md` (structured analysis)
- `library/topics/<topic>/<topic>_Paper_Synthesis.md` (cross-paper synthesis)
- `library/topics/<topic>/<topic>_Corpus_Synthesis.md` (mixed-source view)
- `output/citations-<topic>.bib` or `output/citations-<topic>.ris` when exported with `distill export <topic> --what citations`

### Two-pass synthesis (`--two-pass`)

`distill resynthesize <topic> --two-pass` runs a claim-based corpus synthesis instead of summarizing the per-source insights directly. Pass 1 extracts atomic claims from every `_Insights.md` into an append-only `library/topics/<topic>/.claims/claims.jsonl` (one cheap LLM call per not-yet-extracted source - re-runs skip sources already in the store). Pass 2 synthesizes over the claim set: it clusters claims by what they assert, names contradictions between sources explicitly, and cites each statement back to specific claim handles (`[C7]`), surfacing low-confidence and single-source claims as the corpus's soft spots rather than dropping them.

Single-pass synthesis remains the default; `--two-pass` is opt-in and falls back to single-pass if a topic has no extractable claims. The same path is available to agents through the MCP `synthesize` tool's `two_pass` argument.

```bash
distill resynthesize my-research --two-pass
```

## Reports

The 4-phase strategic report (research -> section writing -> assembly -> QA):

```bash
distill report ai                                   # topic-scoped report
distill report SomeCreator                          # channel-scoped (auto-resolves topic)
distill report --all                                # report across every topic
distill report ai --focus "enterprise deployment patterns and vendor lock-in"

# Debugging / iteration
distill report ai --research-only                   # Phase 1 only
distill report ai --sections executive_briefing,vendor_battleground
distill report ai --legacy                          # single-shot Deep Research
distill report ai --no-qa                           # skip Phase 4
distill report ai --test                            # cheaper, faster validation
```

See [architecture.md](architecture.md) for how the 4 phases interact.

During the default 4-phase report, `distill report` prints report-phase
progress for research, section writing, assembly, and QA. Section writing also
prints per-section progress, and QA rewrites print per-fix progress. Each line
includes completed count, failed count, running spend, and ETA when available.

## Evaluate models (cost × quality)

Models change fast and there is no cheap xAI cloud tier anymore (the fast tiers retired 2026-05-15; `grok-4.3` is the cloud floor). `distill eval` measures whether a cheaper model - usually a **local** one - is good enough, instead of guessing.

```bash
# Compare the cloud floor against a local model on all workloads
distill eval --models grok-4.3,qwen3.5:27b

# One workload, write a report artifact, skip the cost prompt
distill eval --workload paper --models grok-4.3,qwen3.5:27b --report --yes
```

It runs each model over frozen golden fixtures (3 per analysis workload: paper / video / site) at `temperature=0`, scores each output on deterministic diagnostic dimensions (structure, verbosity-resistant depth, concept coverage vs the golden, formatting), and then asks model judges for the route-graduation gates. A candidate must clear a source-anchored faithfulness floor, so an unfaithful fixture vetoes migration however the candidate scores. It must also be judged at par with the anchor through order-randomized pairwise comparisons in both A/B orderings, so position bias cancels. If there is no usable judge signal, migration fails closed to the anchor. The deterministic composite and `--threshold` are advisory report diagnostics, not the migration gate.

Flags:

- `--workload paper|video|site|all` - which fixtures to run (default `all`)
- `--models a,b,c` - comma-separated model ids; provider is inferred (grok → xAI, anything unrecognized → local Ollama)
- `--anchor <model>` - the incumbent/reference everything is compared against (default `grok-4.3`; added to `--models` if absent)
- `--judge <model>`: model judge used for source-anchored faithfulness and pairwise at-par comparisons (default `grok-4.3`). A neutral judge is preferred for unbiased migration evidence.
- `--threshold 0.9`: advisory composite reference shown in the report; it does not authorize a migration
- `--report` - write the table to `library/.distill/eval/<workload>_<ts>.md`
- `--no-cache` - re-run every `(model, fixture)` instead of reusing `.distill/eval_cache/`
- `--yes` - skip the pre-run cost confirmation

**Local is optional and cross-platform.** The eval (and all of distill) runs cloud-only on any OS - local models are an opt-in cost lever, not a requirement. When you do eval local models, the VRAM-fit guard reads NVIDIA VRAM (`nvidia-smi`) or Apple Silicon unified memory; on AMD/Intel/CPU-only or any machine where VRAM can't be probed it doesn't block - it just notes that local will run on CPU (slow). Cloud models are never affected by the local-hardware check.

Every run also appends one row per `(model, fixture)` to `library/.distill/eval/results.jsonl` (scores, win-rate, cost) so you can track quality and cost **drift over time** as models change.

The eval **recommends**; it never switches your configured model. To act on a recommendation, set the model yourself (e.g. `DISTILL_PROVIDER=ollama` + `DISTILL_ANALYSIS_MODEL=<model>` in `.env`). A non-anchor recommendation means the model judges found the candidate faithful and at par with the anchor. A recommendation for the anchor means no cheaper model was certified at par, a cheaper model was unfaithful, or the judge signal was missing. (Quick local-only check: `distill doctor --eval --model <name>`.)

## Research briefings and deep synthesis

When the 4-phase report is the wrong shape (multi-topic literature review, stakeholder decision briefing, architectural grounding for a downstream agent), use one of these instead:

```bash
# Multi-topic Gemini Deep Research briefing (web-augmented)
distill research-brief -t topic-a,topic-b \
  --context-file private/product-decision.md --name q2-review

# Multi-topic grok-4.3 single-call synthesis (corpus-only, no web augmentation)
distill synthesize -t topic-a,topic-b \
  --context-file private/lit-review.md --name ai-lit

# Inline context for a quick one-off
distill synthesize -t ai --context "Summarize for a VP of Engineering deciding on vendor lock-in risks" --name vp-summary
```

| Command | Engine | Best for | Typical cost |
|---|---|---|---|
| `distill report <topic>` | Gemini Deep Research + Grok 4-phase pipeline | Strategic intelligence report on one topic, 30-50 pages | ~$2-4 |
| `distill research-brief --topic ... --context-file ...` | Gemini Deep Research | Web-augmented briefing across multiple topics with custom structure | ~$3-5 |
| `distill synthesize --topic ... --context-file ...` | grok-4.3 single call | Dense corpus-only synthesis across multiple topics (e.g. academic paper corpora) | ~$0.50 |

**The context file is the prompt.** Copy [`docs/briefing-contexts/TEMPLATE.md`](briefing-contexts/TEMPLATE.md) as a starting point. Personal/client-specific context files live in [`private/`](../private/) (git-ignored by default).

Output lands in `output/briefing-{name}.md` or `output/synthesis-{name}.md`.

## Library management

```bash
distill library                                     # overview of everything
distill videos ai                                   # list processed videos in a topic
distill add ai https://www.youtube.com/@AnotherCreator
distill remove ai https://www.youtube.com/@OldChannel

# Refresh - only process what's new since last run
distill run ai --refresh
distill run --all --refresh
distill run ai --refresh --shorts                   # include Shorts in refresh
distill run ai --dry-run                            # preview what would run
```

## Concept playbook and recovery

The concept playbook accumulates evidence about named techniques, architectures, datasets, people, and vendors across a topic's `_Insights.md` files. Every refresh that changes a note snapshots the prior version under `.history/`, so the playbook is recoverable.

```bash
# Build / refresh the playbook for a topic (extraction + deterministic merge)
distill concepts build tkg
distill concepts build tkg --threshold 3 --refresh   # re-extract over every insight

# Inspect a note's version history (newest first, with per-step change summaries)
distill concepts log tkg rotational_embedding

# Diff a note across versions
distill concepts diff tkg rotational_embedding                       # most recent snapshot vs live
distill concepts diff tkg rotational_embedding 2026-05-29T08:10:31Z  # that snapshot vs live
distill concepts diff tkg rotational_embedding <ts_a> <ts_b>         # snapshot vs snapshot

# Restore a prior snapshot (reversible: current version is backed up first;
# the concepts.jsonl / entities.jsonl rollup row is rewritten to match)
distill concepts rollback tkg rotational_embedding 2026-05-29T08:10:31Z
distill concepts rollback tkg rotational_embedding 2026-05-29T08:10:31Z --yes   # skip confirm
```

The `<slug>` is the note's filename stem (e.g. `concepts/rotational_embedding.md` -> `rotational_embedding`). Timestamps are accepted in either ISO (`2026-05-29T08:10:31Z`) or filesystem-stem (`2026-05-29T08-10-31Z`) form; `distill concepts log` prints the exact values to copy. Agents can reach the same read surface over MCP via `concept_history` and `concept_diff`.

## Agent orientation (CLAUDE.md)

Every topic directory and the library root carry an auto-generated `CLAUDE.md` orientation file, so a coding agent that auto-loads `CLAUDE.md` (Claude Code, Cursor, Codex CLI, and others) gets immediate context the moment it `cd`s in: a one-line summary, source counts, a link to the topic synthesis, "ask me about" example queries from the corpus's named entities and concepts, and the MCP read-surface tools. These regenerate automatically on every topic refresh; the command below is for backfilling existing topics or regenerating on demand.

```bash
distill claude-md tkg          # regenerate one topic's CLAUDE.md + the library index
distill claude-md --all        # regenerate every topic + the library index
```

`CLAUDE.md` is plain Markdown with no frontmatter and is generated from existing artifacts (no LLM calls). It is meant to be regenerated, not hand-edited.

## Viewing and exporting

```bash
# View insights for a video (by index, newest = 1)
distill show SomeCreator                            # latest video
distill show SomeCreator 3                          # 3rd newest
distill show SomeCreator 3 -w transcript            # show transcript view
distill show ai 1                                   # explicit topic

# Package latest N videos into one markdown for downstream use
distill package-latest SomeCreator                  # latest 10 with insights
distill package-latest SomeCreator -n 20            # latest 20
distill package-latest ai -n 10 --transcript        # all channels in topic, with transcripts

# View channel / topic synthesis
distill synthesis SomeCreator                       # channel synthesis
distill synthesis ai                                # topic-level synthesis

# View the full report
distill findings ai

# Inspect change history
distill diff ai
distill diff ai --watch ai-daily
distill trends ai
distill trends ai --limit 5

# Export to DOCX (written to output/)
distill export ai --what report
distill export SomeCreator --what synthesis
distill export ai --what bundle --format deepr      # zipped corpus bundle
distill export ai --format okf                      # OKF v0.1 directory bundle
distill export all --format okf                     # OKF bundle for every topic
distill export ai --what citations --format bibtex  # paper citations
distill export ai --what citations --format ris     # Zotero-readable citations
distill okf validate output/okf-ai                  # validate any OKF bundle

# Open files / folders in the system file browser
distill open                                        # open output/
distill open ai                                     # open topic dir
distill open --what report ai                       # open the report
```

## Diagnostics

```bash
distill status                                      # quick library overview
distill doctor                                      # check API keys + system health
distill doctor --update                             # upgrade yt-dlp via pip
distill costs                                       # cost history, estimator accuracy, biggest prompts
distill health ai                                   # fast console view: stale syntheses + thin artifacts
distill audit ai                                    # full trust report -> ai_Audit.md + action menu
                                                    #   (verify coverage, prompt staleness, synthesis freshness,
                                                    #    exact video duplicates, thin long-video transcripts,
                                                    #    near-duplicate insights,
                                                    #    contested concepts, links, gaps; stale
                                                    #    artifacts/syntheses get re-analysis commands -- printed,
                                                    #    never run)
distill audit ai --next-actions --json             # machine-readable actions with commands,
                                                    #   approval class, write scope, loop state,
                                                    #   and verifier stop conditions
distill audit all --report-only                     # every topic, no prompts (for scheduled runs);
                                                    #   also writes Library_Audit.md: library-wide
                                                    #   hygiene (empty/unreadable/unindexed topics)

# Maintenance
distill migrate                                     # rename legacy ID-based video dirs
distill cleanup                                     # delete orphaned Gemini File Search stores
```

### Running on a schedule (loop-ready)

Distill is the loopable primitive; the scheduler is whatever you already run.
Every command is safe unattended: non-interactive flags, convergent re-runs
(a converged corpus exits 0 as a no-op), clean failure messages, report
artifacts instead of console-only output.

Windows Task Scheduler (weekly refresh + audit):

```powershell
schtasks /Create /SC WEEKLY /D MON /ST 06:00 /TN "distill-refresh" `
  /TR "distill catch-up"
schtasks /Create /SC WEEKLY /D MON /ST 06:30 /TN "distill-audit" `
  /TR "distill audit all --report-only"
```

cron (Linux/macOS):

```cron
0 6 * * 1   distill catch-up
30 6 * * 1  distill audit all --report-only
0 7 * * 1   distill discover --from-gaps --topic <topic> --preview
```

The gap-fill line is `--preview` on purpose: scheduled jobs surface candidate
spend; a human (or a budgeted agent) commits it with `--from-preview <id>`.
Audit reports land as dated `<topic>_Audit.md` artifacts, so drift,
contradictions, and verification coverage surface without manual prompting.

### Read-only MCP for agent deployments

Set `DISTILL_MCP_READ_ONLY=1` in the MCP server's environment to serve only
the read surface: connected agents can search, read, and inspect gaps, but
every spend/ingest/mutation tool (`papers`, `discover`, `site_batch`,
`synthesize`, `ask`, watch management, reports) refuses with a clear message
pointing at the CLI. The recommended posture when agents you don't fully
control can reach the server: ingest happens via the CLI by a named operator.
One exception is structural planning: `site_batch(preview=true)` returns the
resolved crawl plan without model checks, crawling, writes, or spend.

For deployments that do expose the write tools, two narrower guardrails:

- `DISTILL_MCP_MAX_SPEND_PER_CALL=0.50` caps each tool call's recorded spend
  in dollars. Enforcement is on actual spend, not an estimate: the model call
  that crosses the cap completes (its spend already happened and stays on the
  ledger -- no off-ledger spend, ever), then the run stops with a structured
  `budget_exceeded` response. Artifacts written before the stop are durable
  and verify-gated, and a re-run converges (already-ingested sources skip).
- `DISTILL_MCP_INGEST_ALLOWLIST=youtube.com,learn.microsoft.com` confines the
  URL-taking ingest tools (`process_video_url`, `watch_add`, `site_batch`) to
  the listed hosts and their subdomains -- the corpus-poisoning guard.
  `site_batch` applies the allowlist after expanding TXT or JSON seed files,
  including mixed exact-page and shallow-crawl JSON seeds. Hosts match exactly
  or as subdomains (`www.youtube.com` passes `youtube.com`; `evilyoutube.com`
  does not).

### Ask the corpus (`distill ask`)

```bash
distill ask "which entailment checker should we use?" --topic claim-verification
distill ask "..." --topic t --save     # promote a verified answer into the corpus
```

Answers are grounded ONLY in the topic's artifacts (top-matching insights via
the same retrieval `find_insights` uses), with every claim citing its source
as a `[[wiki-link]]`; "the corpus does not cover this" is a valid answer.
Each answer is written to `answers/<slug>_Answer.md` with provenance and a
`_Verify.json` sidecar grounding its numbers against the retrieved excerpts.

`--save` is the compounding step: a **clean** answer is re-ingested as a
first-class insight (`synthesis_scope: derived-answer`) that synthesis,
concepts, and future answers build on. Promotion is strict by definition:
unsupported load-bearing claims, unknown bracketed source stems, or answers
with no retrieved source citation refuse the save. The answer and sidecar
remain, so you can see why. MCP parity: an `ask` tool (read-only; promotion
stays CLI-only).

### Claim verification (the verify hook)

Every analysis emit (papers, videos, site pages, X posts, local files) grounds
the insight's numeric claims (decimals, percents, counts with separators,
money, years) against the source receipt in the same directory before the
artifact is committed, writing a `<stem>_Verify.json` sidecar either way --
positive evidence ("checked 11, supported 11") as well as flags. A flag means
*support not found*, not *false*: the sidecar carries the context line so you
(or `distill audit`) can adjudicate.

Modes, via the `DISTILL_VERIFY` env var or `--verify` on `papers` / `discover`
/ `latest`:

```bash
distill papers "..." --topic t --verify strict      # refuse to write a flagged insight
DISTILL_VERIFY=off distill latest "..."             # skip the check for this run
# default: warn -- flag to console, write anyway
```

Strict mode keeps the receipt and the sidecar, records the refusal in the run
summary, and leaves videos unprocessed so a re-run retries them. The
deterministic tier checks numbers only; named-entity/prose claims await the
local entailment-checker tier ([roadmap](../ROADMAP.md)).

### yt-dlp staleness preflight

YouTube-touching commands (`channel`, `search`, `explore`, `learn`, `latest`,
`discover`, `topic update`, `catch-up`, `topic-watch run`, `ramp-up`) run a
zero-network version-age check on entry. If yt-dlp's date-stamped release is
more than 14 days old, you'll see a one-line yellow warning pointing at
`distill doctor --update`. The result is cached for 24 hours in
`library/.preflight.json`, so the check adds essentially no overhead on
repeated runs.

To opt out (CI, scripted automation):

```bash
export DISTILL_NO_PREFLIGHT=1
```

## Exit Codes

All CLI commands return stable exit codes for scripting and CI integration:

| Code | Name | Meaning |
|------|------|---------|
| 0 | SUCCESS | Command completed successfully |
| 1 | RUNTIME_ERROR | Unexpected error during execution |
| 2 | USAGE_ERROR | Invalid arguments or flags |
| 3 | CONFIG_ERROR | Missing API key or invalid configuration |
| 4 | NETWORK_ERROR | API timeout, DNS failure, HTTP error |
| 5 | NOT_FOUND | Requested topic, channel, or resource doesn't exist |

## Setup (`distill init`)

The guided first-run wizard. It creates a `.env` (and **never** overwrites an existing one without `--force`, so your keys are safe), helps you choose the cloud or local provider, live-validates your key against the provider, installs the Playwright browser if it's missing, and ends with a ready/not-ready verdict plus the first command to try.

```bash
distill init                       # interactive: pick provider, paste key, validate
distill init --provider cloud      # skip the provider prompt
distill init --provider local      # set DISTILL_PROVIDER=ollama, probe reachability
distill init --yes                 # non-interactive: accept defaults, don't prompt
distill init --no-browser          # skip the Chromium install step
distill init --force               # recreate .env from the template (overwrites!)
distill --json init                # machine-readable readiness verdict
```

`distill init` is no-TTY-safe: with no terminal and no `--yes`, it creates the env file and prints the manual next steps rather than blocking on a prompt, so a scripted or agent-driven setup never hangs. The exit code is `0` when the setup is ready to ingest and `1` when something still needs doing (the verdict lists exactly what). `distill doctor` remains the read-only diagnostic; `init` is the one that *sets things up*.

## Version

```bash
distill --version       # or -V; prints the installed version and exits 0
```

Eager, so it works before any environment is configured - handy for bug reports and agent preflight.

## Global output controls

Global output flags go before the command:

```bash
distill --quiet catch-up              # suppress human console output
distill --verbose doctor              # enable debug logging
distill --json library                # machine-readable stdout
```

`--quiet` / `-q` is for external loops that only need exit codes, artifacts, or
JSON output. It suppresses the shared human console for that invocation and
resets on the next command. `--verbose` / `-v` enables debug logging on stderr,
matching `--debug`. The run log at `library/.distill/distill.log` captures DEBUG
records for post-run review even when console output remains warning-only.
`--quiet` cannot be combined with `--verbose` or `--debug`.

## JSON Output

Pass `--json` for machine-readable output. The read surface is covered -
`library`, `videos`, `show`, `synthesis`, `findings`, `costs`, `doctor`,
`health`, `alerts`, the dashboard view, and `concepts` export:

```bash
distill --json library               # topic + channel inventory
distill --json synthesis <topic>     # the synthesis document + provenance
distill --json show <topic> 1        # a video's insights (or --what transcript)
distill --json doctor                # health check + readiness verdict
```

`distill --json doctor` carries a top-level **`ready`** boolean (true when a cloud key live-validates or a local server is running, so the environment can analyze a source) alongside per-check status in `checks` (including a `browser` entry: `installed` / `missing` / `unknown`) and `warnings`. An agent can gate on `ready` in one read; a not-ready environment is fixed with `distill init`.

When `--json` is active:
- **stdout** carries exactly one JSON object with `status`, `data`, and optionally `error` - nothing else, so it always parses
- **stderr** carries all human/progress/diagnostic output (the shared console is redirected there), so it never corrupts the JSON on stdout
- `--json` is **read-only**: querying a not-yet-generated synthesis returns `{"found": false}` rather than triggering a paid generation
- Rich formatting and color are suppressed on stdout; `NO_COLOR` is respected

Exit codes still apply (e.g. 3 for config errors), so a caller can branch on both the envelope and the code.

## Unattended / agent operation

Distill is built to run in a loop or under an agent with no human at the keyboard:

- **`--quiet` / `-q`** suppresses human console output when a loop only needs
  exit codes, artifacts, or JSON.
- **`library/.distill/distill.log`** captures DEBUG logging for post-run review
  without requiring verbose console output.
- **`--yes` / `-y`** skips confirmation on every spend- or mutation-gated command.
- **`audit --report-only`** writes the report artifact and sets the exit code from findings without prompting.
- **`audit --next-actions --json`** emits bounded action rows an external loop can run and verify without scraping console output.
- **No-TTY safety:** when stdin is not a terminal, interactive prompts resolve to their safe default instead of aborting on EOF - a confirmation with no safe default declines (and prints the `--yes` hint), and menu prompts take their listed default. Bare `distill` skips the screen-clear when stdout is piped.
- **Exit codes** (above) distinguish config (3) and network (4) failures from generic runtime errors (1), so a loop can branch on the cause.

## Zero-key tour / demo path

Evaluation does not require API keys. Use `--preview` (or `--seed-only --preview`) against the bundled example seeds plus the example corpus shipped in `examples/`. These paths exercise discovery planning, site seed resolution, and corpus reading without any LLM analysis spend or keys.

```bash
# Zero-key preview of bundled site seeds (no analysis)
distill site-batch configs/example_seeds.json --topic demo --seed-only --preview

# Inspect the public example corpus (no keys needed)
distill --help
distill library --json   # or open examples/ in your editor/Obsidian

# Read the example corpus orientation (generated AGENTS.md / CLAUDE.md style)
ls examples/library/topics/
cat examples/library/topics/*/AGENTS.md | head -20
```

The example seeds and corpus let you walk the preview, plan, and read surfaces with zero setup beyond the install. Full analysis paths still require keys or a local model server.

## Updating distill

```bash
distill update            # upgrade to the latest published release, in place
distill update --check    # report installed vs latest without upgrading
distill --json update --check   # same, machine-readable
```

`distill update` detects the install method - **uv tool**, **pipx**, or **pip** - and runs the matching upgrade (`uv tool upgrade` / `pipx upgrade` / `pip install --upgrade`). On a **source/editable checkout** it won't touch your working tree; it tells you to `git pull` + `uv sync` instead.

distill also surfaces a one-line "update available" nudge on startup when a newer release is published - checked against PyPI at most once per day (cached), non-blocking, and silenced with `DISTILL_NO_UPDATE_CHECK=1`.

## Shell completions

```bash
distill --install-completion    # install tab-completion for your shell
distill --show-completion        # print the completion script to inspect/source
```

Completion covers commands, flags, and live topic-name arguments (bash, zsh, fish, PowerShell).
