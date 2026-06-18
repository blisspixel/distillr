# Recurring profiles and no-metered-cost routing

Status: accepted direction for 0.19, after OKF/loop-readiness and batch-run
visibility settle.

This document turns the recurring "track AI developer news / live agentic dev"
workflow into a product slice, and defines the cost policy that keeps it useful
without surprise API spend.

## Research signals

- YouTube exposes channel update feeds through
  `https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID` in its push
  notification guide, which gives Distill a low-cost way to monitor creator
  updates before falling back to heavier YouTube Data API calls. The Data API
  remains quota-based, with all requests costing quota units. Sources:
  [YouTube push notifications](https://developers.google.com/youtube/v3/guides/push_notifications)
  and [YouTube Data API overview](https://developers.google.com/youtube/v3/getting-started).
- Local model servers are mature enough to be first-class routes: Ollama serves
  a local API at `http://localhost:11434/api`, and LM Studio serves local models
  through REST plus OpenAI-compatible and Anthropic-compatible endpoints.
  Sources: [Ollama API docs](https://docs.ollama.com/api/introduction) and
  [LM Studio server docs](https://lmstudio.ai/docs/developer/core/server).
- Codex CLI is a local terminal coding agent, and Codex is included in ChatGPT
  plans with plan-specific limits. Sources:
  [Codex CLI docs](https://developers.openai.com/codex/cli) and
  [Codex plan docs](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan).
- Claude Code can use Pro/Max subscription usage, but an `ANTHROPIC_API_KEY`
  environment variable makes it use API billing instead. Subscription limits
  are shared with Claude usage. Source:
  [Claude Code plan support](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan).
- Grok Build is available to SuperGrok and X Premium Plus subscribers, supports
  plan mode, and xAI release notes describe headless scripting and orchestrator
  usage. Sources: [Grok Build launch](https://x.ai/news/grok-build-cli),
  [Grok modes](https://docs.x.ai/build/modes-and-commands), and
  [xAI release notes](https://docs.x.ai/developers/release-notes).
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

"Free" is not the right word. The product term is **no-metered-cost**:

- deterministic local work,
- public feeds and already accessible pages,
- local model inference,
- or explicitly configured subscription / plan-quota CLI usage,

with no API-billed call unless the user opts into it.

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

- `ai-developer-news`: channels, vendor docs, release notes, and feeds around
  coding agents and agent platforms.
- `live-agentic-dev`: YouTube-heavy creator tracking, with transcript-first
  ingest and local transcription fallback.
- `vendor-docs-watch`: official docs and release notes only, useful for
  tracking OpenAI, Anthropic, Google, xAI, Microsoft, and local model tooling.

## Cost modes

`DISTILL_COST_MODE` and `--cost-mode` should accept:

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
3. Configured plan-quota CLI adapters: Codex CLI, Claude Code, Grok Build, and
   later Gemini / Antigravity if the support statement is clear.
4. Metered cloud API routes only when cost mode is `auto` or `paid-ok`.

Claude Code gets an extra preflight: if `ANTHROPIC_API_KEY` is present and the
chosen route claims subscription usage, Distill must block and explain that the
CLI would use API billing.

## Build order

1. **Docs and examples.** Add three profile examples and document cost modes
   before adding new commands.
2. **Profile schema and validation.** Pure parser and validator with fixtures.
   No network or LLM dependency.
3. **Profile preview.** `distill profile preview <name>` resolves feeds,
   channels, domains, repos, and queries into candidate source rows without
   writing analysis artifacts.
4. **Profile run.** `distill profile run <name>` executes the same approved
   ingest and analysis paths Distill already uses, with resume-friendly state.
5. **Cost policy enforcement.** Route selection respects `auto`,
   `no-metered`, and `paid-ok`, and writes a ledger entry for every run.
6. **Adapter contracts.** Add plan-quota adapters only behind explicit support
   statements, environment preflights, and `distill eval` fixtures.
7. **Loop handoff.** Profiles emit next-action rows compatible with the 0.17
   schema so Codex, Claude Code, Grok Build, cron, or GitHub Actions can steward
   them externally.

## Non-goals

- No hidden daemon or built-in scheduler in the first profile slice.
- No claim that subscription usage is literally free.
- No automated YouTube anti-bot workaround.
- No plan-quota adapter without eval evidence and a support statement.
- No profile-only pipeline that bypasses existing verify, audit, cost, and
  corpus invariants.

## Success criteria

- A user can create an `ai-developer-news` profile, preview new sources, run it
  in no-metered-cost mode, and see exactly what was skipped because it would
  have spent money.
- The same profile can be handed to an external loop through next-action JSON
  without scraping console text.
- Local and plan-quota routes are measured against frozen fixtures before they
  are trusted for profile analysis.
- The cost ledger remains complete even when dollar cost is zero.
