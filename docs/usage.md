# Usage

Full command reference. For the short version, see the [README](../README.md).
Install alternatives and keys: [install.md](install.md). Positioning vs other
tools: [positioning.md](positioning.md).

> Every command prints contextual next steps - file paths and suggested follow-up commands - so you can usually find your way without re-reading this doc.

## Common first commands

```bash
# Goal-aware cross-source discovery
distill discover "help an AI become a great music composer" --topic music --preview
distill --cost-mode no-metered topic preview "agent memory systems" --topic memory --videos 10 --papers 10

# YouTube topic, then arXiv papers
distill latest "Microsoft Fabric best practices" --limit 10 --report
distill --cost-mode no-metered papers "agent memory systems" --topic memory --limit 5 --preview
distill --cost-mode paid-ok papers "agent memory systems" --topic memory --limit 20
distill export memory --what citations --format bibtex

# Vendor / research site batch
distill site-batch configs/example_seeds.json --topic example --seed-only

# Ask the corpus (grounded-only, cited); --save promotes a verified answer
distill ask "which checker should the verify tier use?" --topic memory

# Free trust report (no model calls)
distill audit memory --report-only
distill audit memory --next-actions --json
```

Long runs print per-item progress (completed, failed, spend, ETA). Use
`distill --quiet <command>` for loops that only need files, exit codes, or
JSON. DEBUG stays in `library/.distill/distill.log` (8 MiB roll, three backups).
`--verbose` mirrors debug to stderr. Exit codes and site/discovery preview
behavior are documented under [Exit Codes](#exit-codes) and the source sections
below.

**Capacity.** Local inference plus the public internet is how Distill builds a
knowledge corpus: do more ingest, stay more current, grow the markdown wiki.
Ad hoc commands are for when you are at the keyboard. `profile refresh` is for
after hours. `$0` local runs are volume; they take wall clock, and that clock
gets shorter as local models improve. `--cost-mode paid-ok` is how you do a
lot quickly: preview, then `--limit 20 --workers 3` if the estimate looks
right. Plan-quota CLIs you already subscribe to are the intended fast
included-plan lane, but Distill does not treat them as no-metered until it can
prove included-plan auth. See [cost.md](cost.md).

## Table of Contents

- [Goal-aware discovery (cross-source)](#goal-aware-discovery-cross-source)
- [Analysis lens (per-topic intent)](#analysis-lens-per-topic-intent)
- [YouTube: Stay current on a topic](#youtube-stay-current-on-a-topic)
- [YouTube: Ramp up fast](#youtube-ramp-up-fast)
- [YouTube: Channel watch and catch-up](#youtube-channel-watch-and-catch-up)
- [YouTube: Topic watch (recurring)](#youtube-topic-watch-recurring)
- [Recurring research profiles](#recurring-research-profiles)
- [Active host-session workers](#active-host-session-workers)
- [Agent Skill lifecycle](#agent-skill-lifecycle)
- [Websites](#websites)
- [Direct ingest: X, repos, feeds, and local files](#direct-ingest-x-repos-feeds-and-local-files)
- [arXiv papers](#arxiv-papers)
- [Reports](#reports)
- [Research briefings and deep synthesis](#research-briefings-and-deep-synthesis)
- [Library management](#library-management)
- [Concept playbook and recovery](#concept-playbook-and-recovery)
- [Viewing and exporting](#viewing-and-exporting)
- [Diagnostics](#diagnostics)
- [Provider and model route](#provider-and-model-route)
- [Global output controls](#global-output-controls)

## Goal-aware discovery (cross-source)

When you have a **research goal** rather than a keyword query, `distill discover` is the front door. It takes a natural-language goal, has the configured model generate candidate search queries for papers and videos, lets you optionally add curated website seed files or trusted website sections, and then does a single unified model rerank of the combined pool *against the goal* (not against keywords). You see one ranked cross-source table and only commit to ingestion after confirming.

For a topic-owned workflow, start with `topic preview`. A mixed paper and video
preview saves the exact ranked set and prints one complete replay command. The
replay ingests that saved set without searching or reranking again, then saves
the topic profile. A video-only preview has no saved selection snapshot, so its
continuation says that candidates will refresh before ingestion.

```bash
distill --cost-mode no-metered topic preview "agent memory systems" \
  --topic memory --videos 10 --papers 10 --days 30 --no-shorts
# Run the exact topic create --from-preview command printed by the preview.
```

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
  --trusted-site https://learn.microsoft.com/en-us/microsoft-365/agents-sdk/ \
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
- `--lens research|practitioner|competitive|academic|general` - the analytical lens each per-source insight is written through. Default: neutral `general`. The goal is still carried into every analysis prompt, but Distill does not infer a lens from keywords. The lens is persisted as the topic's intent (`topics/<topic>/intent.json`), so later `papers` / `latest` / `discover` runs into the same topic inherit it. `competitive` reproduces the pre-0.9.24 enterprise pre-sales sections.
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

Repeating `distill video` for an exact video ID with a nonempty transcript and
insight is a converged no-op. It reuses the existing artifacts without model
or ledger work. Pass `--force` when you intentionally want to rerun analysis,
or use `distill reanalyze` for a registered channel or topic.

## YouTube: Channel watch and catch-up

The watch list is for channels you want to stay current on without running full analysis every time. Each watched channel has its own lookback window and optional custom analysis instructions.

Watch URLs must be public HTTPS YouTube channel URLs without credentials,
queries, fragments, or custom ports. Accepted `youtube.com`, `www.youtube.com`,
and mobile hosts converge on `https://www.youtube.com/...` before duplicate
lookup, discovery, or state mutation.

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

Scan mode (used by `catch-up`) is lightweight (~$0.008/video at the default
Grok 4.6 route). During
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

Budget evaluation is serialized for the whole batch and the current cost
ledger is rescanned before each non-paused entry. This makes spend recorded by
an earlier watch visible to the next decision and prevents concurrent batches
from racing the same budget. If cost history is incomplete, a budgeted watch
stops before provider work unless the operator explicitly supplies
`--ignore-budget`.

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

To keep many topics current (a Karpathy-style wiki on a $0 local route), save
one profile per topic with `cadence: daily` or `weekly`, then pack what fits
tonight:

```bash
distill --cost-mode no-metered profile refresh --max-hours 6
distill --cost-mode no-metered profile refresh --max-hours 6 --yes
```

That does not start 100 full ingests. It ranks stale and never-run profiles,
estimates wall clock from `distill bench` or the last run, and takes only what
fits the window (default 12 profiles, 3 fresh items each). The rest wait until
tomorrow. Distill still does not schedule itself; put the `--yes` line on Task
Scheduler or cron.
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

## Active host-session workers

When a command routed to `DISTILL_PROVIDER=agent` reaches model work, Distill
writes a deferred task under `library/.distill/tasks/pending/` and exits with a
pending-task message. An already active coding-agent session can complete that
task without Distill invoking the vendor CLI or handling its credentials:

```bash
# Prompt-free queue inventory
distill --json worker list

# Claim one task into an isolated scratch workspace
distill --json worker claim --host worker-a --worker-id interactive

# After writing only the returned result.md path, provide the token by environment
distill --json worker submit <task-id> --model <model-label>

# Release an incomplete task for another host using the same environment variable
distill --json worker abandon <task-id> --reason "quota exhausted"
```

`worker claim` returns exact read paths for `task.json` and `prompt.md`, the one
allowed `result.md` write path, an opaque ownership token, the
`DISTILL_WORKER_CLAIM_TOKEN` environment name, and a lease. Do not put the real
token in process arguments, scripts, logs, or shell history. Inject it into the
submit or abandon process through the host's secret-environment mechanism and
clear it immediately afterward. For an interactive shell, read it without echo
instead of typing it into a recorded command:

```bash
read -rsp "Claim token: " DISTILL_WORKER_CLAIM_TOKEN
printf '\n'
export DISTILL_WORKER_CLAIM_TOKEN
distill --json worker submit <task-id> --model <model-label>
unset DISTILL_WORKER_CLAIM_TOKEN
```

```powershell
$claimToken = Read-Host "Claim token" -AsSecureString
$env:DISTILL_WORKER_CLAIM_TOKEN = [Net.NetworkCredential]::new("", $claimToken).Password
distill --json worker submit <task-id> --model <model-label>
Remove-Item Env:DISTILL_WORKER_CLAIM_TOKEN
```

Submit rejects changed staged inputs, extra workspace files, unsafe paths,
oversized results, wrong ownership, conflicting results, and malformed
receipts. Claim, submit, abandon, release, and provider replay share one
serialized transition boundary. Ownership and the exact workspace file set are
rechecked immediately before publication, so an abandoned, expired, or
replaced claim cannot publish afterward. Submission is idempotent for the same
claim and exact result. A result without a valid submission receipt remains
pending and is never replayed. After submission, rerun the original Distill
command so `AgentProvider` can replay the validated result and continue through
the normal verify and corpus-write path.

If a worker cannot finish, `worker abandon` records why and makes the task
claimable by another host. `worker release-expired <task-id>` is preview-only;
add `--yes` only after an operator confirms the original worker is inactive.

This protocol constrains what Distill accepts, but it does not sandbox the
already active host process. Keep the host's own approvals and sandbox enabled.
The route is recorded as `host-managed`: Distill has no direct API charge, but
the external session may consume plan quota, credits, or API billing. It is not
proven no-metered, and recurring profile cost receipts fail closed when its
external cost is unavailable.

## Agent Skill lifecycle

The bundled [`distill-corpus` skill](../skills/distill-corpus/) contains the
complete agent-side procedure. It is available through native Codex and Claude
plugin marketplaces, Gemini's skill installer, Grok's Claude-compatible plugin
loader, Antigravity's `.agents/skills/` path, and versioned claude.ai ZIP
uploads. The
[`distribution guide`](design/agent-skill-distribution.md) gives exact install,
update, validation, and checksum details. Direct plan-quota adapters remain
separate and blocked until adapter doctor, current support, auth, usage,
scratch, and eval gates pass.

The strict release archive follows the current
[Agent Plugins 1.0.0 Working Draft](https://agent-plugins.org/specification):
root `plugin.json` provides the portable manifest and `skills/` is the fixed
skill location. It intentionally has no root `mcp.json`; configure
`distill-mcp` separately with explicit read-only and cost policy when MCP
access is required. The checked-in repository plugin and historical plugin ZIP
also carry client-native compatibility files. Use
`distill-corpus-agent-plugin-<version>.zip` when a client requests the strict
portable package. See the [interoperability baseline](interoperability.md) for
the exact boundary and version update policy.

The installed Python package carries an exact, integrity-manifested copy of the
skill. Inspect all clients and direct-discovery targets without writing or
starting any host:

```bash
distill skill doctor
distill --json skill doctor --client codex --scope project
```

Prefer a client's native package manager when it supplies provenance and
updates. The direct lifecycle is the portable fallback and is also useful for
an intentionally project-local installation. Every mutation previews unless
`--yes` is present:

```bash
# Preview, then install or safely update the project copy
distill skill install --client codex --scope project
distill skill install --client codex --scope project --yes

# Install for one user, or inspect a different project root
distill skill install --client claude --scope user --yes
distill skill doctor --client antigravity --project-root ../another-project

# Preview and remove only a clean Distill-managed copy
distill skill uninstall --client codex --scope project
distill skill uninstall --client codex --scope project --yes

# Produce a deterministic archive plus <archive>.sha256
distill skill export --output distill-corpus.skill
```

The client target controls the documented discovery directory: Codex and the
portable target use `.agents/skills`, Claude uses `.claude/skills`, Gemini uses
`.gemini/skills`, and Grok uses `.grok/skills`. Antigravity uses
`.agents/skills` for project scope and `.gemini/config/skills` for user scope.
Do not combine a native plugin install with a direct copy for the same client.

An exact unmanaged copy can be adopted. A divergent unmanaged directory,
changed managed file, symbolic link, junction, multiply linked file, oversized
tree, or destination race is refused. Apply and update stage the verified wheel
bytes, swap directories under a lock, and verify the completed tree. Uninstall
accepts only a clean ownership manifest. Export archives use stable ordering,
timestamps, modes, and SHA-256 output so two exports of one version are
byte-identical.

Skill installation does not make a host a Distill model provider and does not
establish whether a client session uses included quota, purchased credits, or
an API key. `distill skill doctor` reports binary presence only. Active-session
worker results remain `host-managed`, and ambiguous routes remain blocked in
`no-metered` mode.

On Claude Code versions that expose the native plugin eval runner, maintainers
can compare the plugin with its no-plugin baseline:

```bash
claude plugin eval plugins/distill-corpus \
  --ablation with-without --runs 3 --max-cost-usd 5 --no-scaffold
```

The six source-controlled cases cover corpus reading, safe curation, worker
handoff, billing truth, local recency, and an unrelated-task negative trigger.
They grant no tools and use model graders for semantic behavior. Structural
schema and distribution drift run in offline CI; paid model behavior remains an
explicit, budget-capped release evaluation.

### Plan-quota adapter doctor

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

Ollama contention is handled before inference. If another model is resident,
Distill waits with bounded backoff, logs the active and requested models, and
never silently substitutes. `DISTILL_LOCAL_TIMEOUT` is the total ceiling for
the contention wait. Once inference starts, it is a per-read idle timeout, not
a wall-clock runtime limit, so a generation that keeps streaming can run
longer. A contention timeout exits as a network-class failure with retry
guidance, which lets an external loop reschedule the command without scraping
an apparent hang.

Ollama model discovery streams `/api/tags` through a 2 MiB response ceiling and
accepts only a strict bounded `models` object. LM Studio model discovery applies
its own 1 MiB response and model-shape ceilings. Oversized, deeply structured,
or malformed registries fail closed. Local readiness requires the configured
exact model id to appear in the successful provider inventory.

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

See [`configs/example_seeds.json`](../configs/example_seeds.json) for the seed-file shape. JSON URL objects and collections can set `mode` to `exact-page` or `shallow-crawl`, or use `crawl: false` / `crawl: true` as a boolean alias. Unsupported mode names fail during seed-file loading instead of falling back to a wider crawl. They can also set `crawl_prefix` to keep shallow crawls inside a docs branch such as `/en-us/microsoft-365/agents-sdk`. Drop your own `private/<anything>_seeds.json` locally (git-ignored by default).

## Direct ingest: X, repos, feeds, and local files

`distill discover` searches arXiv and YouTube and reranks operator-supplied site
candidates. It does not search X, GitHub, podcast directories, newsletters, or
your filesystem. Add those sources by exact URL or path:

```bash
distill ingest https://x.com/example/status/1234567890 --topic agent-harnesses
distill ingest https://github.com/example/project --topic agent-harnesses
distill ingest https://example.com/feed.xml --rss --episodes 3 --topic agent-harnesses
distill ingest private/research-notes.md --topic agent-harnesses

# Capture an X post without attached-video transcription or model analysis
distill ingest https://x.com/example/status/1234567890 --topic agent-harnesses \
  --no-transcribe --no-analyze
```

A non-HTTP target stays on the local-file path. If it does not exist, Distill
prints the exact target, suggests checking the path, and exits with
`NOT_FOUND` (5) before URL adapter routing or model work. A missing local file
is never reported as an unsupported website host.

X uses the public syndication endpoint and never bypasses login or anti-bot
walls. Artifacts land under
`topics/<topic>/x/<handle>/posts/<post>/`. `--no-transcribe` skips attached
video transcription; `--no-analyze` keeps the receipt without writing an
insight. In `no-metered` mode, local transcription remains allowed and cloud
speech-to-text fallbacks refuse before a provider call.

Default analyzed X replays require the same semantic content hash on both the
receipt and insight, then reuse complete artifacts without model or ledger
work. Engagement-count changes alone do not trigger analysis. Edits to post
text, long-form text, previews, quoted posts, or attached-media identity do.
Proven unchanged pre-hash pairs receive a one-time hash migration without a
model call. Failed analysis never commits the receipt-side completion marker.
Raw-only capture commits its receipt hash after any requested attached-video
transcript lands, so repeating `--no-analyze` is also write, ledger, model, and
speech-to-text free. Pass `--force` to refresh unchanged content intentionally.

The current one-pass corpus aggregator combines channel, site, and paper
synthesis inputs. When directly ingested X, repo, feed, or local-file insights
must influence the cross-source result, use `distill resynthesize <topic>
--two-pass`, which reads all `_Insights.md` files recursively.

## arXiv papers

```bash
# Ingest one paper directly from arXiv (abstract + full PDF text + structured insight)
distill paper https://arxiv.org/abs/2602.12670 --topic my-research

# Search arXiv and build a topic-level paper corpus - expands the query,
# LLM-reranks candidates, ingests the top N (all on by default)
distill --cost-mode paid-ok papers "agent memory systems" --topic my-research --limit 20

# Preview the ranked shortlist without ingesting; refuse API-billed model routes
distill --cost-mode no-metered papers "agent memory systems" --topic my-research --limit 5 --preview
# After `distill bench`, that preview also prints how long the ingest would take
# on this machine. $0.00 and "~1h15m" are the same kind of control.

# Old behavior: literal query, newest-first, blind ingest of top N
distill papers "agent memory systems" --topic my-research --limit 20 \
  --no-expand --no-rerank --sort date

# Opt in to a small independent-analysis group after approving projected spend
distill papers "agent memory systems" --topic my-research --limit 20 --workers 3

# Mixed-source synthesis across videos, sites, and papers filed under one topic
distill corpus my-research

# Export citations for Zotero or a reference manager
distill export my-research --what citations --format bibtex
distill export my-research --what citations --format ris
```

Direct paper replay is version-exact. A completed arXiv `v1` is reused without
model or ledger work, while a fetched `v2` is treated as new source content.
Pass `--force` to reanalyze the same version intentionally.

Flags on `distill papers`:

- `--limit / -n` - how many papers to analyze after reranking (default 10)
- `--sort relevance|date` - arXiv candidate order before rerank (default `relevance`)
- `--expand / --no-expand` - expand the single user query into up to six arXiv search variants via the configured model (default on). Candidates are deduped by `paper_id` across variants. arXiv calls are spaced 3.5s to respect rate limits.
- `--rerank / --no-rerank` - LLM rerank with `RankedPaper` scoring on relevance / depth / novelty / credibility (default on). Runs *before* PDF fetch and analysis, so you don't pay to analyze off-topic picks.
- `--rigor strict|balanced|loose|off` - quality bar on the rerank score; drops papers below the per-source threshold (0.65 / 0.45 / 0.30) before the `--limit` cap. Default `off` (keep the rerank's top picks as before). Needs `--rerank` - under `--no-rerank` the scores are heuristic, off the rerank scale, so an explicit bar is skipped with a warning. When set, the whole candidate pool is reranked so the bar has something to drop, and a `kept X/Y` line shows what it cut.
- `--preview` - show the ranked shortlist and stop. Use this to sanity-check what you'd actually ingest before committing. On a local route it also prints `$0.00` plus a wall-clock estimate from `distill bench` (or `unknown` if this machine has not been measured). Hours-long local ingests are expected.
- `--workers 1|2|3` - concurrent independent PDF fetch and paper analysis.
  Default `1` preserves one-at-a-time spend and failure semantics. Values `2`
  and `3` are explicit opt-ins after the total workflow estimate passes.

During ingestion, `distill papers` prints per-paper progress with the current
phase, item count, completed count, failed count, running spend, and ETA once
enough items have completed. Per-paper analysis failures become structured
`paper-analysis` run issues and the loop continues. The spend cap remains a
hard stop. With multiple workers, only independent fetch and analysis run in
the bounded worker group. Progress updates, verification, artifact writes,
summary mutation, cross-paper synthesis, and mixed-corpus synthesis stay on the
coordinating thread. Projected per-paper spend is reserved atomically against
the shared budget before each concurrent analysis starts. A hard stop cancels
work that has not started; a provider request already in flight cannot be
retracted, so use `--workers 1` when strict one-call-at-a-time behavior matters.

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

Citation export only writes entries whose local paper artifact or metadata
receipt still exists; stale bibliography records refuse the export instead of
producing dangling keys.

### Two-pass synthesis (`--two-pass`)

`distill resynthesize <topic> --two-pass` runs a claim-based corpus synthesis instead of summarizing the per-source insights directly. Pass 1 extracts atomic claims from every `_Insights.md` into an append-only `library/topics/<topic>/.claims/claims.jsonl` (one cheap LLM call per not-yet-extracted source - re-runs skip sources already recorded in the strict source ledger). Claim publication and ledger advancement share one topic transaction, including durable zero-claim receipts, so concurrent cooperating runs do not repeat the same model work and interrupted appends do not mark a source complete. Pass 2 synthesizes over the claim set: it clusters claims by what they assert, names contradictions between sources explicitly, and cites each statement back to specific claim handles (`[C7]`), surfacing low-confidence and single-source claims as the corpus's soft spots rather than dropping them.

Single-pass synthesis remains the default; `--two-pass` is opt-in and falls back to single-pass if a topic has no extractable claims. The same path is available to agents through the MCP `synthesize` tool's `two_pass` argument.

If a two-pass synthesis cites a claim handle that is not present in the extracted
claim set, Distill refuses the write and keeps any previous synthesis in place.

```bash
distill resynthesize my-research --two-pass
```

## Reports

`distill report` is one facade with three explicit profiles. The default reads
the durable corpus and does not require Gemini Deep Research:

```bash
distill report ai                                   # corpus-report, topic scope
distill report SomeCreator                          # corpus-report, channel scope
distill report --all                                # corpus-report, entire library
distill report ai --focus "enterprise deployment patterns and vendor lock-in"

# Full depth: Gemini dossier, then ordered strategic sections and QA
distill report ai --profile accordion
distill report ai --profile accordion --research-only
distill report ai --profile accordion --sections executive_briefing,vendor_battleground

# One Gemini Deep Research artifact, without sequential section writing
distill report ai --profile deep-research
distill report ai --legacy                          # compatibility alias

# Corpus profile iteration
distill report ai --sections evidence_map,contradictions_uncertainty
distill report ai --no-qa
```

| Profile | Research material | Writing path | Cold-start estimate |
|---|---|---|---:|
| `corpus-report` (default) | Existing syntheses, insights, and receipt paths | 6 ordered sections, assembly, full-document QA, ordered rewrites | ~$0.99 on the default Grok route; $0 direct API cost on a proven local route |
| `accordion` | Gemini Deep Research dossier grounded in the corpus and web | 10 ordered strategic sections, assembly, full-document QA, ordered rewrites | Known writer estimate plus unavailable Google external cost |
| `deep-research` | Gemini Deep Research | One provider-authored report | External cost unavailable; $2.50 is a non-binding Distill planning placeholder |

These are expected point estimates, not price guarantees. Distill resolves the
configured report route before applying a workflow cap. Standard Deep Research
shows a $2.50 midpoint but requires $3 of available budget; Max shows $5 and
requires $7. A local Ollama or LM Studio writer contributes $0 direct API cost;
Gemini Deep Research remains metered in the two profiles that use it.

Sequential writing is deliberate. Section N sees prior sections, and the QA
review sees the complete assembled report before failed sections are rewritten
in report order. Independent report chapters are not fanned out. The final
structural audit refuses unresolved numbered citations and a missing,
duplicated, or reordered section spine. See [architecture.md](architecture.md)
for the complete flow.

## Evaluate models (cost × quality)

Models change fast. `grok-4.6` is the current xAI default, while explicit
overrides remain supported. `distill eval` measures whether a different cloud
or local model is good enough for a workload instead of guessing.

```bash
# Compare the cloud floor against a local model on all workloads
distill eval --models grok-4.6,qwen3.5:27b

# One workload, write a report artifact, skip the cost prompt
distill eval --workload paper --models grok-4.6,qwen3.5:27b --report --yes
```

It runs each model over frozen golden fixtures (3 each for paper, video, and
site, plus 5 adversarial corpus-Q&A fixtures for `ask`) at `temperature=0`,
scores each output on deterministic diagnostic dimensions (structure,
verbosity-resistant depth, concept coverage vs the golden, formatting), and
then asks model judges for the route-graduation gates. A candidate must clear a
source-anchored faithfulness floor, so an unfaithful fixture vetoes migration
however the candidate scores. It must also be judged at par with the anchor
through order-randomized pairwise comparisons in both A/B orderings, so
position bias cancels. If there is no usable judge signal, migration fails
closed to the anchor. The deterministic composite and `--threshold` are
advisory report diagnostics, not the migration gate.

Flags:

- `--workload paper|video|site|ask|all` - which fixtures to run (default `all`)
- `--models a,b,c` - comma-separated model ids. Known prefixes route to xAI
  (`grok`), Gemini (`gemini` / `deep-research`), Anthropic (`claude`), the
  reserved OpenAI route (`gpt` / `o1` / `o3`), or an adapter candidate
  (`adapter:`); anything else is treated as a local Ollama model.
- `--anchor <model>` - the incumbent/reference everything is compared against.
  `auto` uses `grok-4.6` when an XAI key is configured, otherwise the first
  listed model. The anchor is added to `--models` if absent.
- `--judge <model>` - model judge used for source-anchored faithfulness and
  pairwise at-par comparisons. `auto` selects a different-family model that is
  not one of the candidates when one is available. With no neutral judge,
  migration fails closed.
- `--threshold 0.9`: advisory composite reference shown in the report; it does not authorize a migration
- `--report` - write the table to `library/.distill/eval/<workload>_<ts>.md`
- `--no-cache` - re-run every `(model, fixture)` instead of reusing `.distill/eval_cache/`
- `--allow-oversized` - run local models whose weights exceed detected GPU or
  unified-memory capacity instead of skipping them to avoid CPU spill.
- `--yes` - skip the pre-run cost confirmation

**Local is optional and cross-platform.** The eval (and all of distill) runs cloud-only on any OS - local models are an opt-in cost lever, not a requirement. When you do eval local models, the VRAM-fit guard reads NVIDIA VRAM (`nvidia-smi`) or Apple Silicon unified memory; on AMD/Intel/CPU-only or any machine where VRAM can't be probed it doesn't block - it just notes that local will run on CPU (slow). Cloud models are never affected by the local-hardware check.

Every run also appends one row per `(model, fixture)` to `library/.distill/eval/results.jsonl` (scores, win-rate, cost) so you can track quality and cost **drift over time** as models change.

The eval **recommends**; it never switches your configured model. To act on a recommendation, set the route yourself with `distill provider set ollama <model>` (or env vars such as `DISTILL_PROVIDER` / `DISTILL_MODEL`). A non-anchor recommendation means the model judges found the candidate faithful and at par with the anchor. A recommendation for the anchor means no cheaper model was certified at par, a cheaper model was unfaithful, or the judge signal was missing. `distill doctor --json` checks local service and model availability; use `distill eval --workload <name> --models <models>` for the quality decision.

## Research briefings and deep synthesis

For a multi-topic literature review, custom stakeholder briefing, or a dense
single-call synthesis, use one of these instead:

```bash
# Multi-topic Gemini Deep Research briefing (web-augmented)
distill research-brief -t topic-a,topic-b \
  --context-file private/product-decision.md --name q2-review

# Multi-topic Grok single-call synthesis (corpus-only, no web augmentation)
distill synthesize -t topic-a,topic-b \
  --context-file private/lit-review.md --name ai-lit

# Inline context for a quick one-off
distill synthesize -t ai --context "Summarize for a VP of Engineering deciding on vendor lock-in risks" --name vp-summary
```

| Command | Engine | Best for | Typical cost |
|---|---|---|---|
| `distill report <topic>` | Existing corpus + configured ordered writer | Evidence-backed report without mandatory web research | ~$0.99 on default cloud route; $0 direct on proven local route |
| `distill report <topic> --profile accordion` | Gemini Deep Research + configured ordered writer | Full-depth strategic intelligence report | Known writer estimate plus unavailable Google external cost |
| `distill report <topic> --profile deep-research` | Gemini Deep Research | Single provider-authored research report | External cost unavailable; $2.50 is a non-binding Distill planning placeholder |
| `distill research-brief --topic ... --context-file ...` | Gemini Deep Research | Web-augmented briefing across multiple topics with custom structure | External cost unavailable; hard dollar budgets refuse before remote setup |
| `distill synthesize --topic ... --context-file ...` | Configured synthesis model, one call | Dense corpus-only synthesis across multiple topics (e.g. academic paper corpora) | Estimate before run |

**The context file is the prompt.** Copy [`docs/briefing-contexts/TEMPLATE.md`](briefing-contexts/TEMPLATE.md) as a starting point. Personal/client-specific context files live in [`private/`](../private/) (git-ignored by default).

Output lands in `output/briefing-{name}.md` or `output/synthesis-{name}.md`.
Report-style outputs refuse unresolved numbered citation handles such as
`[cite: 1]` before writing when Distill has no structural citation map for
them. The completed model call remains on the cost ledger; the unsafe report,
briefing, or synthesis file is not promoted.

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

The concept playbook accumulates evidence about named techniques, architectures, datasets, people, and vendors across a topic's `_Insights.md` files. Every refresh that changes a note snapshots the prior version under `.history/`, so the playbook is recoverable. Multiple changes in the same second receive stable `__2`, `__3`, and later suffixes instead of overwriting one another. If an interrupted build updates mentions or notes but not every derived playbook export, the next build detects its durable repair marker and rebuilds the derived state before returning an idle result.

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

## Agent orientation (CLAUDE.md and AGENTS.md)

Every topic directory and the library root carry auto-generated `CLAUDE.md` and `AGENTS.md` orientation files with identical content. Their fixed trust boundary appears before navigation or workflow guidance, and topic files use static research questions without interpolating topic names, synthesis filenames, or corpus-derived prose into privileged instructions. They still report structural source counts, synthesis availability and staleness, playbook availability, and the MCP read surface. These files regenerate automatically on every topic refresh; the command below is for backfilling existing topics or regenerating on demand.

```bash
distill claude-md tkg          # regenerate one topic's CLAUDE.md + the library index
distill claude-md --all        # regenerate every topic + the library index
```

Both files are plain Markdown with no frontmatter and are generated from existing artifacts without model calls. They are meant to be regenerated, not hand-edited.

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
distill export ai --format okf                      # OKF v0.2 directory bundle
distill export all --format okf                     # OKF bundle for every topic
distill export ai --what citations --format bibtex  # paper citations
distill export ai --what citations --format ris     # Zotero-readable citations
distill okf validate output/okf-ai                  # validate any OKF bundle

# Open files / folders in the system file browser
distill open                                        # open output/
distill open ai                                     # open topic dir
distill open --what report ai                       # open the report
```

The documented JSON read surface stays structured on empty states. For
`distill --json show <topic> <index>`, `data.found` is `false`, content and path
are `null`, and `data.reason` identifies `no_channels`, `no_videos`,
`video_not_found`, or `invalid_metadata`. Human `show` output remains concise.
Missing topics passed to `diff` or `trends` exit with `NOT_FOUND` (5).

## Dashboard

```bash
distill                         # terminal home screen
distill --json                  # bounded dashboard.v2 operator snapshot
distill --json dashboard        # the same explicit dashboard contract
distill dashboard --web         # write a standalone local HTML dashboard
distill serve                   # local web dashboard at http://127.0.0.1:8899
```

The terminal home screen shows tracked topics, watches, recent runs, failures,
rolling spend, and paths to local run evidence. Bare and explicit dashboard
JSON return the same bounded `dashboard.v2` envelope. Its `spend.recent_usd`
field is null when retained cost evidence cannot support a complete total. The
web dashboard adds keyboard-accessible drill-downs with rendered markdown, cost
history, and watchlist status. Scripts are same-origin static assets under a
restrictive CSP. Every dashboard reads library files only (no database).

## Diagnostics

```bash
distill status                                      # quick library overview
distill --cost-mode no-metered doctor               # system health; refuse API-billed key probes
distill --cost-mode paid-ok doctor                   # include minimal live cloud-key validation
distill --cost-mode no-metered doctor --update      # upgrade yt-dlp without cloud-key probes
distill costs                                       # cost history, estimator accuracy, biggest prompts,
                                                    #   and exact-ID command/provider/phase performance evidence
distill health ai                                   # fast console view: stale syntheses + thin artifacts
distill audit ai                                    # full trust report -> ai_Audit.md + action menu
                                                    #   (verify coverage, prompt staleness, synthesis freshness,
                                                    #    exact video duplicates, thin long-video transcripts,
                                                    #    near-duplicate insights,
                                                    #    contested concepts, links, gaps; stale artifacts get
                                                    #    inert JSON argv or manual-review guidance, never shell text)
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

Migration scans and wiki-link repair touch only visible, confined, bounded,
single-link regular files. Dry-run output states that link repair follows
successful renames. An apply run reports every refused read or write and exits
with status 1 when any error remains, even when earlier renames succeeded.

When a run has failed results or recorded issues, its terminal summary prints
the exact local `latest_run_errors.md` receipt after that file is written.
`run_log.jsonl`, `latest_run.json`, and `latest_run_errors.md` share one run ID
and one serialized update boundary. Concurrent runs cannot leave the two latest
projections pointing at different runs; a projection failure restores the prior
pair and remains visible while the complete run-log row stays diagnostic.
Failed source rows also receive a safe retry hint; already-ingested sources are
skipped on the next run. If the evidence receipt cannot be written, Distill
shows and logs that failure instead of advertising a path that does not exist.

The recent correlated-performance section of `distill costs` reads
`.distill/phase_telemetry.jsonl`, `telemetry.jsonl`, and `cost_log.jsonl`,
bounded to the newest 16 MiB of each file. Biggest-prompt ranking and the
local/cloud split separately stream the full provider telemetry history. Those
reads retain only the requested top rows and running counters, cap each encoded
row at 1 MiB, require strict finite nonnegative measurements, and continue past
invalid UTF-8 or malformed rows. The human inference split names the skipped
row count and exact local telemetry path; JSON output exposes the same call
counts, malformed-row count, and read-error state under `provider_telemetry`.
Like every CLI invocation, its own command envelope is
appended after rendering, but observer rows are excluded from the recent
workflow list and counted explicitly. Only a `phase: command` row establishes a
run, and provider or cost rows join only through the same non-empty `run_id`.
Older rows without an ID remain visible as legacy coverage counts and are never
guessed from timestamps. In `--json` output, the additive `performance` object
separates the command envelope from an optional workflow summary and includes
recent runs, the latest nested phases, coverage, and machine-readable timing,
process-CPU, artifact, and memory semantics. Invalid numeric fields stay
unknown and are counted as schema-invalid rather than being shown as zero. If
an invalid row can still be attributed to a run, that run's completeness flag
is false and its affected aggregate remains `null`; explicit valid zeroes and a
complete run with no provider calls remain zero.
When a file exceeds the read window, `coverage.tail_limited_logs` names it in
JSON and the human view states that older rows were excluded. Because an older
sibling row may belong to a retained command anchor, the affected phase,
provider, or cost completeness flag is false and its aggregate stays `null`.
The retained command envelope and valid rows remain visible as an explicitly
incomplete subset.

Cost history applies a matching strict evidence boundary across `distill
costs`, dashboards, calibration, recurring watches, and MCP. Rows are limited
to 1 MiB, confined input to 16 MiB, and retained valid history to 10,000 rows.
Monetary fields must be finite and nonnegative, and timestamps must be valid
ISO values. The JSON `cost_history` coverage object reports malformed,
omitted-valid, invalid-time, and read-error counts. Human output names the same
integrity problem. Valid retained runs stay visible, but totals, projections,
calibration, budget claims, and surprise-cost warnings remain unknown when the
evidence is incomplete.

Phase, provider, and cost writers serialize cooperating processes through
hidden sibling lock files under `.distill/`. If an interrupted write leaves a
partial final row, the next writer inserts one record boundary before its own
row so later evidence is not absorbed by the partial data. Provider and phase
telemetry stay fail-soft and never replace the underlying workflow result.
Cost rows fail closed and are `fsync`-flushed before profile receipt state is
marked written. The logs remain append-only; Distill does not yet rotate,
delete, or compact them because archive completeness and receipt continuity
are not defined.

### Running on a schedule (loop-ready)

Distill is the loopable primitive; the scheduler is whatever you already run.
Every command is safe unattended: non-interactive flags, convergent re-runs
(a converged corpus exits 0 as a no-op), clean failure messages, report
artifacts instead of console-only output.

Windows Task Scheduler (overnight wiki fuel + morning audit):

```powershell
schtasks /Create /SC DAILY /ST 01:00 /TN "distill-refresh" `
  /TR "distill --cost-mode no-metered profile refresh --max-hours 6 --yes"
schtasks /Create /SC DAILY /ST 07:00 /TN "distill-audit" `
  /TR "distill --cost-mode no-metered audit all --report-only"
```

`profile refresh` packs due topics into the six-hour window. A `$0` local
machine that estimates `~20m` per topic will rotate through dozens of
profiles over a couple of weeks, which is how 100 wiki topics stay current
without a 100-topic stampede on Monday night. Cloud API runs finish in
minutes and can use a shorter window. Distill does not schedule itself.

cron (Linux/macOS):

```cron
0 1 * * *   distill --cost-mode no-metered profile refresh --max-hours 6 --yes
0 7 * * *   distill --cost-mode no-metered audit all --report-only
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

- `DISTILL_MCP_MAX_SPEND_PER_CALL=0.50` gives each tool call a dollar allowance.
  Budgeted xAI, Gemini chat, and Anthropic attempts reserve a conservative
  prompt-plus-maximum-output bound before provider construction, with hidden
  provider retries disabled. Cloud transcription reserves its duration price.
  Deep Research is refused whenever this hard cap is active because Google does
  not expose a provider-side dollar ceiling for its autonomous loop. The
  refusal occurs before client construction, File Search store creation,
  upload, or provider contact. Unbudgeted provider usage is recorded exactly
  once and labeled as external cost unavailable.
- `DISTILL_MCP_INGEST_ALLOWLIST=youtube.com,learn.microsoft.com` confines URL
  entry points and stored-URL refresh (`process_video_url`, `watch_add`,
  `site_batch`, and `catch_up` against each stored watch URL) to the listed
  hosts and their subdomains -- the corpus-poisoning guard for concrete URLs.
  Query-shaped tools (`discover`, `papers`, `learn_topic`, `search_videos`)
  stay open-world when write tools are enabled; use `DISTILL_MCP_READ_ONLY=1`
  when the server must not reach the public web at all. MCP `site_batch`
  accepts direct URL arrays or bounded JSON manifests under
  `library/site-seeds/`; it does not read TXT or ordinary library files. The
  allowlist applies after expanding mixed exact-page and shallow-crawl JSON
  seeds. Hosts match exactly
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
stays CLI-only) returns `status: refused` for the same source-citation identity
failures instead of returning them as normal answers.

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
summary, and leaves videos unprocessed so a re-run retries them. The base tier
checks numeric claims. Installing `distillr[entailment]` adds the local
HHEM-2.1-Open tier for substantive prose claims without a cloud call; strict
mode refuses prose flags when that optional tier is available.

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

The CLI reserves stable exit codes for scripting and CI integration. Commands
use the most specific class they can prove at the boundary; code 1 remains the
fallback for an execution failure that has no narrower supported class.

| Code | Name | Meaning |
|------|------|---------|
| 0 | SUCCESS | Command completed successfully |
| 1 | RUNTIME_ERROR | Unexpected error during execution |
| 2 | USAGE_ERROR | Invalid arguments or flags |
| 3 | CONFIG_ERROR | Missing API key or invalid configuration |
| 4 | NETWORK_ERROR | API timeout, DNS failure, HTTP error |
| 5 | NOT_FOUND | Requested topic, channel, or resource doesn't exist |
| 6 | BUDGET_EXCEEDED | A workflow or per-call cost cap refused further work |

Deterministic preflight and recovery paths preserve that distinction. Invalid
learning options, topic workflow values, export selectors, citation formats,
and `open --what` requests exit 2. Missing required keys or an explicitly
configured editor exit 3. Missing topics, profiles, channels, corpus artifacts,
citations, concept notes, and recovery snapshots exit 5. These refusals happen
before provider calls, subprocess launches, or artifact writes. A declined
interactive confirmation is a separate command outcome and should not be
treated as a missing resource.
The content-free command row in `phase_telemetry.jsonl` preserves terminal
classes as `usage_error`, `config_error`, `network_error`, `not_found`, and
`budget_exceeded`; runtime and unknown nonzero statuses remain `error`.
Typed cost-policy refusal remains `refused`, even though it returns the
configuration status, so billing gates stay distinguishable from bad setup.

## Setup (`distill init`)

The guided first-run wizard. It creates a `.env` (and **never** overwrites an existing one without `--force`, so your keys are safe), helps you choose the cloud or local provider, live-validates your key against the provider, installs the Playwright browser if it's missing, and ends with a ready/not-ready verdict plus the first command to try. Cloud key validation can make a small billed request in `auto` mode and records it in the local cost ledger. Use `distill --cost-mode no-metered init` to refuse API-billed or ambiguous validation.

```bash
distill --cost-mode no-metered init # recommended: setup with fail-closed validation
distill --cost-mode paid-ok init    # explicitly permit minimal live cloud-key validation
distill init                       # use the configured/default auto cost policy
distill init --provider cloud      # skip the provider prompt
distill init --provider local      # set Ollama plus an exact model, then verify both
distill init --yes                 # non-interactive: accept defaults, don't prompt
distill init --no-browser          # skip the Chromium install step
distill init --force               # recreate .env from the template (overwrites!)
distill --json init                # machine-readable readiness verdict
```

`distill init` is no-TTY-safe: with no terminal and no `--yes`, it creates the env file and prints the manual next steps rather than blocking on a prompt, so a scripted or agent-driven setup never hangs. Ollama setup writes `DISTILL_MODEL=qwen3.5:27b` only when no model is already configured; LM Studio asks for an exact loaded model id. Existing model choices are preserved. `--force` starts from the new template, removes process values that came only from the replaced file, and preserves real shell or global CLI overrides. Env updates leave exactly one active assignment for each key. The exit code is `0` only when the selected local service responds successfully, the exact configured model is present, and the browser is installed. `distill doctor` remains the read-only diagnostic; `init` is the one that *sets things up*.

The suggested `distill papers ... --preview` step stops before paper ingest and
corpus writes. It can still use the configured model for expansion or reranking,
so any preview model cost is recorded in the local ledger. Use
`--cost-mode no-metered` when the requirement is to refuse API-billed routes.

## Version

```bash
distill --version       # or -V; prints the installed version and exits 0
```

Eager, so it works before any environment is configured - handy for bug reports and agent preflight.

## Provider and model route

Show, list, or set the analysis provider without hand-editing `.env`:

```bash
distill provider                              # show active provider + model
distill provider list                         # routable providers
distill provider list gemini                  # known Gemini analysis models + prices
distill provider set gemini gemini-3.7-flash  # persist DISTILL_PROVIDER + DISTILL_MODEL
distill provider set gemini                   # cloud default model (gemini-3.7-flash)
distill provider set ollama qwen3.5:27b       # exact local inventory id required
```

On a TTY, `distill provider set` with no arguments walks an interactive picker.
Without a TTY, pass explicit provider (and model for local/agent routes). Use
`--yes` to accept cloud catalog defaults without prompts.

For one run only, use global flags (no `.env` write):

```bash
distill --provider gemini --model gemini-3.7-flash papers "..." --limit 5
distill -p gemini -m gemini-3.5-flash-lite papers "..." --limit 20
# known cloud model ids also infer the provider:
distill -m gemini-3.7-flash papers "..." --limit 5
```

Aliases: `google` -> `gemini`, `grok` -> `xai`, `claude` -> `anthropic`.
Deep Research reports still use `GEMINI_API_KEY` on their own path; the provider
command configures the analysis/synthesis chat route.

## Global output controls

Global output flags go before the command:

```bash
distill --quiet catch-up              # suppress human console output
distill --verbose doctor              # enable debug logging
distill --json library                # machine-readable stdout
distill --provider gemini --model gemini-3.7-flash papers "..." --limit 5
distill -p gemini -m gemini-3.5-flash-lite doctor
distill --cost-mode paid-ok --provider gemini doctor
```

`--provider` / `-p` and `--model` / `-m` override the analysis route for one
invocation by setting `DISTILL_PROVIDER` and `DISTILL_MODEL` in the process
environment (they do not rewrite `.env`). A known cloud model id with only
`--model` infers the matching provider. Persist a default with
`distill provider set`.

`--quiet` / `-q` is for external loops that only need exit codes, artifacts, or
JSON output. It suppresses the shared human console for that invocation and
resets on the next command. `--verbose` / `-v` enables debug logging on stderr,
matching `--debug`. The run log at `<configured-library>/.distill/distill.log`
captures DEBUG records for post-run review even when console output remains
warning-only. It rolls at 8 MiB and retains `distill.log.1` through
`distill.log.3`; reconfiguration also replaces a legacy unbounded handler.
`--quiet` cannot be combined with `--verbose` or `--debug`.

## JSON Output

Pass the global `--json` flag for commands that implement a structured output
contract. Stable read envelopes include `library`, `videos`, `show`,
`synthesis`, `findings`, `costs`, `doctor`, `health`, `alerts`, the dashboard
view, and `concepts` export:

```bash
distill --json                       # bounded dashboard.v2 operator snapshot
distill --json dashboard             # identical explicit dashboard snapshot
distill --json library               # topic + channel inventory
distill --json synthesis <topic>     # the synthesis document + provenance
distill --json show <topic> 1        # a video's insights (or --what transcript)
distill --cost-mode no-metered --json doctor  # readiness without API-billed probes
```

`distill --json doctor` carries a top-level **`ready`** boolean alongside per-check status in `checks` (including a `browser` entry: `installed` / `missing` / `unknown`) and `warnings`. A cloud route is ready only after the exact resolved model succeeds on its configured provider. Known cross-provider assignments are rejected before a call. A local route is ready only when its configured analysis model is explicit, its endpoint is strict loopback, the service responds successfully, and that exact model appears in the bounded inventory. Under `no-metered`, cloud-key checks report `skipped`, so readiness requires that proven local route. Use `paid-ok` only when an intentional live cloud validation is required. An agent can gate on `ready` in one read; a not-ready environment is fixed with the cost-explicit `init` paths above.

Bare `distill --json` and `distill --json dashboard` return the same
`dashboard.v2` data object. It includes a `first_run` verdict, primitive count
and spend metrics, at most 100 topic names and 10 recent run summaries, bounded
warning lists, next commands, and exact configured paths for the latest run,
run errors, debug log, phase telemetry, provider telemetry, and cost ledger.
The human banner and panels are omitted, so successful dashboard reads have
one JSON object on stdout and no stderr output.

When `--json` is active:
- **stdout** carries exactly one JSON object with `status`, `data`, and optionally `error` - nothing else, so it always parses
- **stderr** carries all human/progress/diagnostic output (the shared console is redirected there), so it never corrupts the JSON on stdout
- the listed **read surfaces** stay read-only: querying a not-yet-generated synthesis returns `{"found": false}` rather than triggering a paid generation
- `show` empty states also return a success envelope with `found: false` and a stable `reason`; they never fall back to human-only text
- Rich formatting and color are suppressed on stdout; `NO_COLOR` is respected

`--json` changes output shape, not command side effects. Preview and action-plan
commands document their own JSON contracts, including `site-batch --preview`
and `audit --next-actions`. Do not assume that an unlisted command emits an
envelope merely because the global flag parses. Exit codes still apply, so a
caller can branch on both a documented envelope and the code.

## Unattended / agent operation

Distill is built to run in a loop or under an agent with no human at the keyboard:

- **`--quiet` / `-q`** suppresses human console output when a loop only needs
  exit codes, artifacts, or JSON.
- **`<configured-library>/.distill/distill.log`** captures DEBUG logging for
  post-run review without requiring verbose console output.
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

# Inspect the CLI and the public example corpus (no keys needed)
distill --help
```

From a source checkout, open
`examples/library/topics/claim-verification/AGENTS.md` and
`examples/library/topics/claim-verification/claim_verification_Paper_Synthesis.md`
directly in your editor or Obsidian. These generated example receipts are
files to inspect, not a registered live library. The example seeds and corpus
let you walk the preview, plan, and artifact-reading surfaces with zero setup
beyond the install. Full analysis paths still require keys or a local model
server.

## Updating distill

```bash
distill update            # upgrade to the latest published release, in place
distill update --check    # report installed vs latest without upgrading
distill --json update --check   # same, machine-readable
```

`distill update` detects the install method - **uv tool**, **pipx**, or **pip** - and runs the matching upgrade (`uv tool upgrade` / `pipx upgrade` / `pip install --upgrade`). On a **source/editable checkout** it won't touch your working tree; it tells you to `git pull` + `uv sync` instead.

distill also surfaces a one-line "update available" nudge on startup when a newer release is published - checked against PyPI at most once per day (cached), non-blocking, and silenced with `DISTILL_NO_UPDATE_CHECK=1`.

### 0.19.40 compatibility notes

- Existing site page owner receipts migrate automatically to a query-free
  source URL plus full-identity digest when their directory is next reserved.
- MCP `list_topic_summary` now exposes top-level and synthesis evidence status.
  Clients should handle `ok`, `degraded`, and `unavailable`, with nested
  synthesis states that also distinguish `absent`.
- Watch and library channel URLs are canonicalized before duplicate lookup and
  mutation. Credentials, queries, fragments, custom ports, and non-channel
  YouTube paths are rejected.
- Migration automation must treat exit status 1 as failure after the command
  prints any completed renames and exact link-repair errors.

### 0.19.39 compatibility notes

- Dashboard JSON is `dashboard.v2`. `spend.recent_usd` is null when the
  `cost_history` coverage record says retained evidence cannot support a
  complete total.
- `worker submit` and `worker abandon` accept the claim token only through
  `DISTILL_WORKER_CLAIM_TOKEN`; the former `--claim-token` option is removed.
- MCP synthesis regeneration requires literal `force=true`. Values that merely
  coerce to true do not authorize a write.
- Existing bounded completion ledgers and claim or mention histories remain
  readable. New source IDs use a shared 16 KiB UTF-8 ceiling, including podcast
  GUIDs, so there is no required migration for valid 0.19.38 topics.

## Shell completions

```bash
distill --install-completion    # install tab-completion for your shell
distill --show-completion        # print the completion script to inspect/source
```

Completion covers commands, flags, and live topic-name arguments (bash, zsh, fish, PowerShell).
