# Recurring profiles and no-metered-cost routing

Status: accepted direction for 0.19, after OKF/loop-readiness and batch-run
visibility settle.

Implementation status: profile schema, preview, approval-gated replay, resume
state, cost modes, local route evidence, adapter doctor, scratch contracts, and
pure graduation and route-pool decisions are shipped. The bounded
active-session handoff through `distill worker` is shipped and records results
as host-managed with unavailable external cost. Codex, Claude, Grok, Gemini
CLI, Antigravity, and Copilot are still candidate direct external workers, not
live Distill providers. No plan-quota route is currently eligible for
`no-metered`; the admission requirements below remain binding.

This document turns the recurring "track AI developer news / live agentic dev"
workflow into a product slice, and defines the cost policy that keeps it useful
without surprise API spend.

Concrete June 2026 command flags, preflights, and adapter invocation patterns
live in [`cli-adapter-runbook.md`](cli-adapter-runbook.md).

## Research signals

- YouTube exposes channel update feeds through
  `https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID` in its push
  notification guide, which gives Distill a low-cost way to monitor creator
  updates before falling back to heavier YouTube Data API calls. The Data API
  remains quota-based, with all requests costing quota units. Sources:
  [YouTube push notifications](https://developers.google.com/youtube/v3/guides/push_notifications)
  and [YouTube Data API overview](https://developers.google.com/youtube/v3/getting-started).
- Newsletter and Substack-class sources are already a first-class Distill input
  through RSS/feed ingestion. Profiles should track the publication feed URL,
  not just a single article URL, so recurring refresh can capture new posts and
  preserve full post text from `content:encoded` bodies when the publisher
  provides them.
- Local model servers are mature enough to be first-class routes: Ollama serves
  a local API at `http://localhost:11434/api`, and LM Studio serves local models
  through REST plus OpenAI-compatible and Anthropic-compatible endpoints.
  Sources: [Ollama API docs](https://docs.ollama.com/api/introduction) and
  [LM Studio server docs](https://lmstudio.ai/docs/developer/core/server).
- Codex CLI is a local terminal coding agent, and Codex is included in ChatGPT
  plans with plan-specific limits. Sources:
  [Codex CLI docs](https://developers.openai.com/codex/cli) and
  [Codex plan docs](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan).
- Codex CLI has an explicit non-interactive mode for automation. The safe
  automation defaults are `codex exec --json --sandbox read-only` for planning
  and inspection, then `--sandbox workspace-write` only when an adapter is
  approved to write to its scratch area. Sources:
  [Codex non-interactive mode](https://developers.openai.com/codex/noninteractive),
  [Codex sandboxing](https://developers.openai.com/codex/concepts/sandboxing),
  and [Codex approvals](https://developers.openai.com/codex/agent-approvals-security).
- Claude Code can use Pro/Max subscription usage, but an `ANTHROPIC_API_KEY`
  environment variable makes it use API billing instead. Subscription limits
  are shared with Claude usage. Source:
  [Claude Code plan support](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan).
- Claude Code supports non-interactive print mode, isolated worktrees, settings
  permissions, and the Agent SDK. Distill should use print mode only for early
  adapter experiments and prefer the SDK when it needs structured events or
  durable production behavior. Sources:
  [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference),
  [Claude Code settings](https://code.claude.com/docs/en/settings), and
  [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview).
- Grok Build is available to SuperGrok and X Premium Plus subscribers, supports
  plan mode, and xAI release notes describe headless scripting and orchestrator
  usage. Sources: [Grok Build launch](https://x.ai/news/grok-build-cli),
  [Grok modes](https://docs.x.ai/build/modes-and-commands), and
  [xAI release notes](https://docs.x.ai/developers/release-notes).
- Grok Build has first-class headless scripting and Agent Client Protocol
  support. Distill should prefer `grok -p ... --output-format json` or
  `--output-format streaming-json` for one-shot tasks, and ACP when it needs a
  long-lived app integration. Sources:
  [Grok Build overview](https://docs.x.ai/build/overview),
  [Grok headless scripting](https://docs.x.ai/build/cli/headless-scripting),
  and [Grok enterprise auth](https://docs.x.ai/build/enterprise).
- GitHub Copilot CLI is a command-line agent with plan mode, permission
  prompts, and current-directory scoping. GitHub documents plan and agent usage
  through Copilot plans, AI credits, and usage limits, so Copilot should not be
  treated as a no-metered default. It can be supported later as an explicit
  credit-metered CLI route under `paid-ok` or a separate plan-credit policy, but
  not as a local or no-metered route by default. Sources:
  [About GitHub Copilot CLI](https://docs.github.com/copilot/concepts/agents/about-copilot-cli),
  [Copilot CLI command reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference),
  and [GitHub Copilot usage limits](https://docs.github.com/en/copilot/concepts/usage-limits).
- Gemini CLI and Antigravity are useful but volatile Google routes. Gemini CLI
  documents terminal and automation use, while Google's current guidance
  positions Antigravity as the agent manager or IDE path with the `agy` CLI and
  Gemini CLI as the terminal or headless path. Treat both as candidate
  plan-quota routes until adapter doctor proves the installed binary, auth
  mode, output format, current support statement, and that API-key, AI-credit,
  or overage routes are not being used. Sources:
  [Gemini CLI repository](https://github.com/google-gemini/gemini-cli),
  [Gemini CLI authentication](https://github.com/google-gemini/gemini-cli/blob/main/docs/get-started/authentication.mdx),
  [Gemini CLI quota and pricing](https://github.com/google-gemini/gemini-cli/blob/main/docs/resources/quota-and-pricing.md),
  [Antigravity CLI overview](https://antigravity.google/docs/cli-overview),
  [Antigravity plans](https://antigravity.google/docs/plans),
  and [Choosing Antigravity or Gemini CLI](https://cloud.google.com/blog/topics/developers-practitioners/choosing-antigravity-or-gemini-cli).
- Agent eval guidance is clear on the operating model: define success criteria,
  evaluate the produced outcome, and track cost, token use, latency, and errors.
  Sources:
  [Writing effective tools for AI agents](https://www.anthropic.com/engineering/writing-tools-for-agents)
  and [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).

## Product stance

Distill should support recurring research topics as saved, inspectable profiles.
A profile is not a hidden background agent. It is a durable plan for how to
refresh a corpus from trusted sources, under a declared cost policy, with
preview and verifier surfaces the user or an external loop can run.

"Free" needs a precise product meaning. The product term is
**no-incremental-metered-cost**:

- deterministic local work,
- public feeds and already accessible pages,
- local model inference,
- or proved included subscription / plan-quota CLI usage,

with no API-billed call unless the user opts into it.

The cost classes are:

- **Local sunk-cost compute.** Ollama, LM Studio, and local transcription spend
  the user's hardware, electricity, and time, but do not create an incremental
  vendor API bill. This is the preferred route for high-volume refresh,
  fan-out, draft analysis, and cross-topic scans once eval says quality clears
  the workload bar.
- **Included plan quota.** Codex CLI, Claude Code, Grok Build, and similar
  tools may be effectively free at the margin when the user already has a plan
  and the route consumes included quota rather than API credits. Gemini CLI and
  Antigravity join this class only when their support statement and installed
  binary make headless or scripted use clear. This is useful for bursty agentic
  fan-out, cross-topic research, reviewer passes, and synthesis planning. It
  still consumes a finite quota and may hit provider rate or session limits, so
  it remains on the usage ledger.
- **Host-managed session.** An already active agent session can claim a bounded
  deferred task, write one scratch result, and submit a validated receipt. This
  is useful before direct adapters graduate because Distill never handles the
  host's credentials or launches its binary. It is not proof of included-plan
  usage: the session may consume plan quota, credits, or API billing. The ledger
  records direct Distill charge separately, marks external cost unavailable,
  and refuses to verify a recurring profile budget receipt containing it.
- **Metered API spend.** Cloud API routes are the quality floor and escalation
  path, but only run in `auto` or `paid-ok` when policy and caps allow them.
  CLI routes backed by paid credits, including Copilot-style AI-credit usage,
  belong here unless a future support statement proves otherwise.

## Profile model

A profile should be a file under the user's library, not only CLI state:

```yaml
schema_version: research-profile.v1
name: ai-developer-news
topic: ai-developer-news
goal_file: goals/ai-developer-news.md
cost_mode: no-metered
freshness:
  cadence: manual
  stale_after: P7D
sources:
  youtube_channels:
    - channel_id: UC...
      label: example-channel
  feeds:
    - https://www.latent.space/feed
    - https://example.com/feed.xml
  domains:
    - docs.anthropic.com
    - developers.openai.com
  repositories:
    - openai/codex
queries:
  - agentic coding loops
  - live agentic dev
outputs:
  summary: true
  trend_notes: true
  okf_export: false
limits:
  max_new_items: 25
  max_metered_usd: 0
```

The first checked-in examples should be:

- `ai-developer-news`: channels, vendor docs, release notes, newsletter feeds,
  and other feeds around coding agents and agent platforms.
- `live-agentic-dev`: YouTube-heavy creator tracking, with transcript-first
  ingest and local transcription fallback.
- `vendor-docs-watch`: official docs and release notes only, useful for
  tracking OpenAI, Anthropic, Google, xAI, Microsoft, and local model tooling.

## Profile preview and the rule/judgment split

Profile preview is the first place this slice can accidentally recreate the
brittle-rule failure mode. The resolver should be deterministic about facts it
can prove, and agentic about judgments that depend on meaning.

Rule-owned preview work:

- Parse profile files and reject invalid schemas.
- Resolve feeds, YouTube channel Atom feeds, repository metadata, trusted
  domains, and saved queries into candidate rows.
- Normalize public URLs, repo identities, timestamps, source ids, and local
  output paths.
- Enforce profile limits, no-metered-cost refusal, explicit allowlists,
  freshness windows, duplicate suppression, and preview-only writes.

Agentic preview work:

- Judge source fit against the goal file.
- Judge novelty against the existing corpus.
- Judge whether a candidate is a rumor, a release note, a tutorial, a primary
  source, or a useful secondary interpretation.
- Prioritize candidates when the profile has more candidates than the user wants
  to inspect or ingest.

If no eligible local or plan-quota model route is available in `no-metered`
mode, preview may still return deterministic source rows by recency, feed order,
or explicit profile order. It must label that result as structural ordering, not
semantic quality ranking. Keyword, regex, title-length, or domain-weight scores
may be diagnostic hints, but they must not become the quality gate.

## Cost modes

`DISTILL_COST_MODE` and `--cost-mode` accept:

- `auto`: default behavior. Use the best configured provider route that clears
  policy, budget, and eval checks.
- `no-metered`: refuse routes that would bill an API or consume purchased
  credits. Allow deterministic work, local models, and configured plan-quota
  CLI routes that have a support statement and pass eval.
- `paid-ok`: allow metered APIs within explicit caps.

Important invariants:

- No-metered-cost mode must fail closed. If Distill cannot prove a route avoids
  metered API spend, it prints the blocked provider and the command that would
  run in `auto` or `paid-ok`.
- Included subscription usage is still usage. Runs record provider, route,
  model when available, approximate tokens or native usage signal, elapsed time,
  and any quota or rate-limit stop.
- Plan-quota routing is opt-in per adapter. Distill must not rely on private
  tokens, impersonation, undocumented bypasses, or environment tricks.
- Each adapter needs a support statement that can be updated when vendor plan
  terms or headless automation behavior changes.

## Provider routing

The no-metered route order should be:

1. Deterministic parse, fetch, transcript, and audit actions.
2. Local OpenAI-compatible or native routes: Ollama, LM Studio, and existing
   local transcription.
3. Configured plan-quota CLI adapters: Codex CLI, Claude Code, Grok Build,
   Gemini CLI, and Antigravity when the support statement is clear.
4. Metered cloud API routes only when cost mode is `auto` or `paid-ok`.

GitHub Copilot CLI is not in the no-metered ladder by default. It can follow
the same adapter shape later, but should be classified as credit-metered unless
preflight proves a no-incremental-cost entitlement.

For high-volume work, route selection should also understand shape:

- Local sunk-cost routes are favored for broad fan-out: candidate triage,
  cross-topic clustering, repeated draft summaries, and cheap negative passes.
- Plan-quota CLI routes are favored for bounded high-judgment passes when local
  models are too weak or too slow but the user has included quota available:
  reviewer passes, cross-topic synthesis planning, contradiction interpretation,
  and adapter self-checks.
- Metered APIs are reserved for workloads where local and plan-quota routes fail
  quality, context, latency, or policy requirements.

Claude Code gets an extra preflight: if `ANTHROPIC_API_KEY` is present and the
chosen route claims subscription usage, Distill must block and explain that the
CLI would use API billing.

## CLI adapter contract

Codex CLI, Claude Code, Grok Build, Gemini CLI, Antigravity, and similar tools
are not normal model
providers inside Distill. Treat them as external workers with stronger
boundaries:

1. **No direct corpus mutation.** Adapters may read the source package and write
   a result manifest to a scratch directory. Distill parses the manifest,
   verifies it, records cost or usage, and performs the final corpus write
   itself.
2. **Machine-readable output required.** Codex starts with JSONL from
   `codex exec --json`. Grok starts with `--output-format json` or
   `--output-format streaming-json`, then ACP when a durable app bridge is
   needed. Claude starts with print mode for narrow experiments and graduates
   to the Agent SDK for structured streams. Gemini and Antigravity do not enter
   the route set until adapter doctor proves a stable structured output or
   scratch-manifest path. Copilot-style credit-metered CLIs follow the same
   output rule if they are added under `paid-ok`.
3. **Read-only before write.** First workloads are corpus Q&A, classification,
   synthesis planning, and profile preview enrichment. Workspace write access is
   allowed only after the read-only adapter clears eval fixtures and writes
   exclusively to the scratch manifest path.
4. **No-metered proof is explicit.** Local routes are no-metered by topology.
   Plan-quota routes are no-metered only when the adapter preflight can show the
   CLI is using an included plan session rather than an API key or purchased
   credits. If the auth mode is unknown, block in `no-metered`.
5. **API-key presence blocks plan claims.** For Claude, `ANTHROPIC_API_KEY`
   blocks subscription routing. For Grok, `XAI_API_KEY` or a configured model
   API key blocks plan-quota routing unless the user selected `paid-ok`. For
   Codex, an OpenAI API-key route is treated as metered unless the adapter can
   prove a ChatGPT-plan session is being used. For Google or any other included
   quota route, unknown entitlement, API-key auth, cloud-provider auth, gateway
   auth, or credential-backed auth blocks no-metered claims. For GitHub Copilot,
   AI-credit usage is metered unless a future support
   statement proves a no-incremental-cost entitlement.
6. **Provider-specific safety flags.** Codex uses `read-only` or
   `workspace-write` sandboxes and avoids `danger-full-access`. Grok scripts use
   `--no-auto-update`; `--always-approve` is allowed only inside an isolated
   scratch workspace. Claude settings deny `.env`, secrets, and unexpected
   writes, and allow only the narrow commands needed for the workload.
7. **Bounded loop behavior.** Every adapter call has a timeout, max output
   size, max turn or session budget when supported, and a structured stop
   reason. Rate limits, quota stops, auth ambiguity, and malformed output fail
   closed.
8. **Same result schema for all adapters.** The result manifest records route,
   provider, model when available, auth mode, command class, usage signal,
   elapsed time, quota-stop metadata, files read, files written, output text,
   citations or receipts, API-key blockers, broader metered-route blockers,
   and policy decisions.
   Workload packages and native usage records are scratch-relative and
   validated before an adapter result can feed the ledger. Verified manifests
   can be transformed into cost-log rows, and checked workload runs verify
   manifest reads, writes, and cost mode against the package. A native result
   writer can write validated manifests from captured CLI output only when the
   caller supplies explicit native usage metadata or a validated
   `adapter-native-usage.v1` file. Command planners may record exact argv
   shapes, staged prompt paths, schema paths, result capture paths, native usage
   capture paths, and allowed scratch capture files while still blocked. Claude
   schema paths can be inlined from staged JSON schema files, but this does not
   bypass adapter support, auth, adapter-specific native usage capture, or eval
   gates.
9. **Acceptance accounting.** Adapter eval records attempts, accepted outputs,
   rejected outputs, verifier failures, elapsed time, usage, and cost per
   accepted change. No-metered routes still lose when they produce too much
   rejected work.
10. **Eval before recommendation.** A CLI adapter can be installed and tested
   before it is recommended. It becomes a route only after `distill eval` shows
   that its output clears the workload bar and the no-metered ledger remains
   complete. `distill.eval.graduation.adapter_route_graduation_decision`
   combines the model-judged eval gate with adapter doctor readiness and fails
   closed when either side is missing.
11. **Judge local against quota routes.** `distill eval` should compare local
    model output against plan-quota CLI output for the same fixture and workload.
    A judge model evaluates faithfulness, specificity, citation use, synthesis
    quality, and actionability from receipts. Distill recommends the cheapest
    no-incremental-metered-cost route that clears the bar, not the route that is
    merely available.

## Build order

1. **Docs and examples.** Add three profile examples, including trusted
   newsletter feeds, and document cost modes before adding new commands.
2. **Profile schema and validation.** Pure parser and validator with fixtures.
   No network or LLM dependency.
3. **Profile preview.** `distill profile preview <name>` resolves feeds,
   channels, domains, repos, and queries into candidate source rows without
   writing analysis artifacts. Structural resolution is rule-owned; source fit,
   novelty, rumor classification, and priority are model-judged when an eligible
   no-metered route exists, otherwise the preview is labeled as unranked
   structural order.
4. **Profile run.** `distill profile run <name>` executes the same approved
   ingest and analysis paths Distill already uses, with resume-friendly state.
5. **Cost policy enforcement.** Route selection respects `auto`,
   `no-metered`, and `paid-ok`, and writes a ledger entry for every run.
6. **Adapter doctor.** Add read-only preflights for local, Codex, Claude Code,
   Grok Build, Gemini CLI, and Antigravity routes: installed version, auth mode,
   dangerous environment variables, headless support, machine-readable output
   support, support statement version, and structured support detail. Copilot
   can be reported separately as a credit-metered CLI candidate under explicit
   paid policy.
7. **Adapter contracts.** Add plan-quota adapters only behind explicit support
   statements whose no-metered status is current, adapter-specific capture
   wiring, adapter-specific native usage capture, environment preflights, and
   `distill eval` fixtures.
8. **Cross-route eval.** Extend `distill eval` so local sunk-cost routes,
   plan-quota CLI routes, and metered API routes can be compared on the same
   fixture with an LLM-as-judge rubric, acceptance accounting, and a usage
   ledger row. The pure graduation decision exists; route-pool wiring still
   needs to consume it.
9. **Loop handoff.** Profiles emit next-action rows compatible with the 0.17
   schema, including state paths, max attempts, verifier commands, and
   acceptance metrics, so Codex, Claude Code, Grok Build, Gemini CLI,
   Antigravity, cron, GitHub Actions, or a paid-policy Copilot route can steward
   them externally.

## Non-goals

- No hidden daemon or built-in scheduler in the first profile slice.
- No claim that subscription usage has no cost or no limits.
- No automated YouTube anti-bot workaround.
- No plan-quota adapter without eval evidence and a current structured support
  statement.
- No profile-only pipeline that bypasses existing verify, audit, cost, and
  corpus invariants.

## Success criteria

- A user can create an `ai-developer-news` profile, preview new sources, run it
  in no-metered-cost mode, and see exactly what was skipped because it would
  have spent money.
- The same profile can be handed to an external loop through profile-run
  `next_actions` JSON without scraping console text, and the loop can stop from
  state and verifier data rather than parsing a model completion claim.
- Local and plan-quota routes are measured against frozen fixtures before they
  are trusted for profile analysis.
- The cost ledger remains complete even when dollar cost is zero.
