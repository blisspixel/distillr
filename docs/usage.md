# Usage

Full command reference. For the short version, see the README.

> Every command prints contextual next steps — file paths and suggested follow-up commands — so you can usually find your way without re-reading this doc.

## Table of Contents

- [Goal-aware discovery (cross-source)](#goal-aware-discovery-cross-source)
- [YouTube: Stay current on a topic](#youtube-stay-current-on-a-topic)
- [YouTube: Ramp up fast](#youtube-ramp-up-fast)
- [YouTube: Channel watch and catch-up](#youtube-channel-watch-and-catch-up)
- [YouTube: Topic watch (recurring)](#youtube-topic-watch-recurring)
- [Websites](#websites)
- [arXiv papers](#arxiv-papers)
- [Reports](#reports)
- [Research briefings and deep synthesis](#research-briefings-and-deep-synthesis)
- [Library management](#library-management)
- [Concept playbook and recovery](#concept-playbook-and-recovery)
- [Viewing and exporting](#viewing-and-exporting)
- [Diagnostics](#diagnostics)

## Goal-aware discovery (cross-source)

When you have a **research goal** rather than a keyword query, `distill discover` is the front door. It takes a natural-language goal, has Grok generate candidate search queries for papers and videos, lets you optionally add curated website seed files, and then does a single unified LLM rerank of the combined pool *against the goal* (not against keywords). You see one ranked cross-source table and only commit to ingestion after confirming.

On a **fresh topic** (no artifacts yet), discover leads with a *size-then-approve* menu instead of auto-ingesting: it shows the ranked candidates and 2–3 sized options — *Excellent / Including good / Everything worthwhile* — each with its source breakdown and its own spend estimate, and ingests the option you pick. `--yes` skips the menu (rigor-filtered auto-ingest); `--size` forces the menu on a topic that already has artifacts.

```bash
# Inline goal
distill discover "help an AI become a great music composer" --topic music --preview
distill discover "2026 enterprise search architectures" --topic enterprise-search --yes

# Goal file — reusable across refreshes
distill discover --goal-file private/ai-composer-goal.md --topic music --yes

# Goal file + curated sites (official docs / vendor pages / labs)
distill discover --goal-file private/agent365-goal.md --topic agent365 \
  --site-seeds private/agent365_sites.json --site-limit 10 --preview
```

Flags:

- `--topic / -t` — topic folder to file outputs under (defaults to a slug of the goal)
- `--paper-limit` / `--video-limit` — max per-source ingestion targets (default 10 each)
- `--site-seeds` / `--site-limit` — optional curated website seed file plus max site seeds to ingest after rerank (default 10 when supplied)
- `--papers-only` / `--videos-only` — mutually exclusive, skip the other source type entirely (also short-circuits the LLM query-generation call for the disabled side, so you don't pay for queries the run will throw away). Useful when one source type has thin coverage of the topic.
- `--days / -d` — YouTube recency window (default 365)
- `--shorts / --no-shorts` — include Shorts under 3 min (default off — deeper content favored)
- `--ingest-attachments` — for selected site seeds, pull PDF text and supported embedded-video transcripts into the page corpus
- `--rigor strict|balanced|loose` — quality bar on the rerank score; drops candidates below the level's goal-fit threshold (0.7 / 0.5 / 0.3) before the per-source limits. Default `balanced`.
- `--preview` — show the ranked plan without ingesting. Prints a metadata-aware spend estimate as a range (e.g. `~$0.42 (est; $0.29-$0.63)`) and **saves the exact shortlist under an id**; preview-only spend lands in `cost_log.jsonl` as `discover_preview`.
- `--from-preview <id>` — ingest the exact set a previous `--preview` saved, by its id. Skips query-generation and the rerank entirely, so you commit to precisely what you saw. (Mutually exclusive with `--preview` / `--from-gaps`.)
- `--from-gaps` — derive the goal from an existing topic's coverage gaps instead of a written goal (requires `--topic`).
- `--yes / -y` — skip the interactive confirmation / sizing menu (rigor-filtered auto-ingest)
- `--goal-file` — load the goal from a markdown file instead of the positional argument. Enables goal-driven topic refreshes (save `private/<name>.md`, re-run discover periodically).

Rerank scores each candidate on `goal_fit` / `depth_score` / `complementarity_score` / `final_score`. Papers, videos, and curated site seeds are ranked in the same pool — a documentation page that directly advances the goal can outrank a shallow video, and vice versa. Website candidates are seed-driven: `discover` does not web-search for pages, it reranks the exact URLs you provide in `--site-seeds` and ingests the selected ones in exact-page mode.

The pre-run spend estimate scales per-video cost by duration and **self-calibrates** against your `cost_log.jsonl` history (per-source rates from clean single-source runs, falling back to defaults when history is thin), so it sharpens as you use the tool. Typical cost: `--preview` ~$0.05, full run ~$1–3 depending on paper/video count.

## YouTube: Stay current on a topic

```bash
# One-shot: find and distill the best recent coverage for a query
distill latest "Microsoft AI news" --topic microsoft-news --days 14 --limit 20 --report

# Tight recency window for rumor-heavy / breaking topics
distill latest "Claude Code leak analysis" --topic claude-code-leak --hours 20 --limit 20 --report
```

`distill latest` defaults to a date-first, Shorts-inclusive, multi-query discovery pass tuned for stay-current workflows. `--hours` gives sub-day precision. For rumor-heavy or April 1 style topics, the selector leans skeptical (favors concrete evidence terms).

`--rigor strict|balanced|loose|off` adds a quality bar on the rerank score (video thresholds 0.6 / 0.4 / 0.25), dropping weak picks before the channel cap; default `off` (unchanged behavior), and it needs the LLM rerank — under `--no-rerank` / `--top-by-date` an explicit bar is skipped with a warning. The thresholds are calibrated per command (lower than `discover`'s, since `latest` is a single-source relevance ranker rather than a cross-source curation gate — see [`architecture.md`](architecture.md) "Rigor calibration").

For strict "last N uploads in the window" semantics — bypassing both the LLM rerank and the heuristic relevance/depth mix and sorting purely by upload date — pass `--top-by-date`. Channel cap still applies, and `--rerank` is force-disabled so query-expansion spend isn't billed for output that's then ignored.

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

Scan mode (used by `catch-up`) is lightweight (~$0.001/video). Use `reanalyze --deep` when you want the full 2-pass analysis on a video you flagged from a scan.

## YouTube: Topic watch (recurring)

Recurring queries — "Microsoft AI news" daily, "Azure AI updates" weekly — with budget guardrails and per-run delta outputs.

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

- `library/topics/<topic>/<topic>_Watch_Update.md` — per-watch delta summary
- `library/topics/<topic>/<topic>_Topic_Diff.md` — reusable topic-level change report
- `library/topics/<topic>/change_history.jsonl` — timestamped change counts
- `library/topics/<topic>/<topic>_Topic_Trends.md` — momentum over recent diff windows
- `library/library_Latest_Changes.md` — library-level rollup
- `library/library_Watch_Alerts.md` — digest of notable changes (also exposed via MCP at `distill://watch-alerts`)

## Websites

```bash
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
- `--seed-only` processes only the exact input URLs (safest for curated lists)
- `--ingest-attachments` writes `attachments.json` per page and, when possible, extracts PDF text and supported embedded-video transcripts into the page corpus
- `--same-section-only` allows shallow crawl but keeps discovery inside the same top-level section (`/topic`, `/partner`, `/lab`, `/docs`, etc.)

See [`configs/example_seeds.json`](../configs/example_seeds.json) for the seed-file shape. Drop your own `private/<anything>_seeds.json` locally (git-ignored by default).

## arXiv papers

```bash
# Ingest one paper directly from arXiv (abstract + full PDF text + structured insight)
distill paper https://arxiv.org/abs/2602.12670 --topic my-research

# Search arXiv and build a topic-level paper corpus — expands the query,
# LLM-reranks candidates, ingests the top N (all on by default)
distill papers "agent memory systems" --topic my-research --limit 20

# Preview the ranked shortlist without ingesting (free-ish, ~$0.01)
distill papers "agent memory systems" --topic my-research --limit 20 --preview

# Old behavior: literal query, newest-first, blind ingest of top N
distill papers "agent memory systems" --topic my-research --limit 20 \
  --no-expand --no-rerank --sort date

# Mixed-source synthesis across videos, sites, and papers filed under one topic
distill corpus my-research
```

Flags on `distill papers`:

- `--limit / -n` — how many papers to analyze after reranking (default 10)
- `--sort relevance|date` — arXiv candidate order before rerank (default `relevance`)
- `--expand / --no-expand` — expand the single user query into up to six arXiv search variants via Grok (default on). Candidates are deduped by `paper_id` across variants. arXiv calls are spaced 3.5s to respect rate limits.
- `--rerank / --no-rerank` — LLM rerank with `RankedPaper` scoring on relevance / depth / novelty / credibility (default on). Runs *before* PDF fetch and analysis, so you don't pay to analyze off-topic picks.
- `--rigor strict|balanced|loose|off` — quality bar on the rerank score; drops papers below the per-source threshold (0.65 / 0.45 / 0.30) before the `--limit` cap. Default `off` (keep the rerank's top picks as before). Needs `--rerank` — under `--no-rerank` the scores are heuristic, off the rerank scale, so an explicit bar is skipped with a warning. When set, the whole candidate pool is reranked so the bar has something to drop, and a `kept X/Y` line shows what it cut.
- `--preview` — show the ranked shortlist and stop. Use this to sanity-check what you'd actually ingest before committing.

The default pipeline (expand + rerank + relevance-sorted) fixes the prior failure mode where generic queries like "music theory deep learning" or "automatic harmonization" pulled in unrelated subfields (physics, image processing) because arXiv's tokenizer has no concept of research intent.

The underlying arXiv query builder is tuned to be tight without being brittle:
- 2-word queries phrase-match (`"music transformer"`) for precision.
- 3+ word queries AND-join tokens so every term must appear without requiring adjacency — this is what makes longer LLM-generated queries work.

For a **goal-driven** corpus across papers *and* videos, use `distill discover` above instead.

Paper outputs land under:

- `library/topics/<topic>/papers/<paper-slug>/metadata.json`
- `library/topics/<topic>/papers/<paper-slug>/<paper-slug>_Paper.md` (abstract + extracted full text)
- `library/topics/<topic>/papers/<paper-slug>/<paper-slug>_Insights.md` (structured analysis)
- `library/topics/<topic>/<topic>_Paper_Synthesis.md` (cross-paper synthesis)
- `library/topics/<topic>/<topic>_Corpus_Synthesis.md` (mixed-source view)

### Two-pass synthesis (`--two-pass`)

`distill resynthesize <topic> --two-pass` runs a claim-based corpus synthesis instead of summarizing the per-source insights directly. Pass 1 extracts atomic claims from every `_Insights.md` into an append-only `library/topics/<topic>/.claims/claims.jsonl` (one cheap LLM call per not-yet-extracted source — re-runs skip sources already in the store). Pass 2 synthesizes over the claim set: it clusters claims by what they assert, names contradictions between sources explicitly, and cites each statement back to specific claim handles (`[C7]`), surfacing low-confidence and single-source claims as the corpus's soft spots rather than dropping them.

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

## Research briefings and deep synthesis

When the 4-phase report is the wrong shape (multi-topic literature review, stakeholder decision briefing, architectural grounding for a downstream agent), use one of these instead:

```bash
# Multi-topic Gemini Deep Research briefing (web-augmented)
distill research-brief -t topic-a,topic-b \
  --context-file private/product-decision.md --name q2-review

# Multi-topic Grok 4.20 single-call synthesis (corpus-only, no web augmentation)
distill synthesize -t topic-a,topic-b \
  --context-file private/lit-review.md --name ai-lit

# Inline context for a quick one-off
distill synthesize -t ai --context "Summarize for a VP of Engineering deciding on vendor lock-in risks" --name vp-summary
```

| Command | Engine | Best for | Typical cost |
|---|---|---|---|
| `distill report <topic>` | Gemini Deep Research + Grok 4-phase pipeline | Strategic intelligence report on one topic, 30–50 pages | ~$2–4 |
| `distill research-brief --topic ... --context-file ...` | Gemini Deep Research | Web-augmented briefing across multiple topics with custom structure | ~$3–5 |
| `distill synthesize --topic ... --context-file ...` | Grok 4.20 single call | Dense corpus-only synthesis across multiple topics (e.g. academic paper corpora) | ~$0.50 |

**The context file is the prompt.** Copy [`docs/briefing-contexts/TEMPLATE.md`](briefing-contexts/TEMPLATE.md) as a starting point. Personal/client-specific context files live in [`private/`](../private/) (git-ignored by default).

Output lands in `output/briefing-{name}.md` or `output/synthesis-{name}.md`.

## Library management

```bash
distill library                                     # overview of everything
distill videos ai                                   # list processed videos in a topic
distill add ai https://www.youtube.com/@AnotherCreator
distill remove ai https://www.youtube.com/@OldChannel

# Refresh — only process what's new since last run
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
distill costs                                       # cost history across runs
distill health ai                                   # audit stale syntheses + thin artifacts

# Maintenance
distill migrate                                     # rename legacy ID-based video dirs
distill cleanup                                     # delete orphaned Gemini File Search stores
```

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

## JSON Output

Pass `--json` to any command for machine-readable output:

```bash
distill --json alerts                # JSON alert digest
distill --json doctor                # JSON health check
```

When `--json` is active:
- stdout contains a single JSON object with `status`, `data`, and optionally `error` fields
- stderr receives any diagnostic or progress messages
- Rich formatting, progress bars, and color are suppressed
- The `NO_COLOR` environment variable is also respected
