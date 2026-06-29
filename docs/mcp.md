# MCP server

Distill exposes its corpus and a subset of its commands as an [MCP](https://modelcontextprotocol.io) (Model Context Protocol) server, so AI assistants and agent systems can query the library and trigger common operations directly.

In a multi-agent workflow, Distill can handle the research-and-corpus-building role: other agents (strategists, architects, writers) query `distill://...` resources or call MCP tools to get grounded, structured intelligence without duplicating the ingestion work.

## Installation

The MCP server installs alongside the CLI. After `pip install distillr`, the `distill-mcp` command is available as a stdio transport.

## Claude Desktop / Claude Code

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "distill": {
      "command": "distill-mcp"
    }
  }
}
```

Then ask Claude things like:

- *"What are today's top items from my deals-channel watch?"*
- *"Get me current on Microsoft Fabric - what changed this week?"*
- *"Research Kubernetes cost optimization from YouTube."*

## Tools

27 tools, grouped by role. Set `DISTILL_MCP_READ_ONLY=1` to serve only the read surface -- every spend/ingest/mutation tool refuses with a clear message (recommended for agent-facing deployments). For deployments that *do* expose the write tools, two narrower guardrails: `DISTILL_MCP_MAX_SPEND_PER_CALL=<dollars>` caps each tool call's recorded spend (the call that crosses completes -- its spend already happened and stays on the ledger -- then the run stops with a structured `budget_exceeded` response; artifacts written before the stop are durable and re-runs converge), and `DISTILL_MCP_INGEST_ALLOWLIST=<host,host>` confines the URL-taking ingest tools (`process_video_url`, `watch_add`, `site_batch`) to the listed hosts and their subdomains. (The surface is deliberately small and shrinking toward workflow-shaped tools: every always-loaded tool schema costs the consuming agent context, so duplicates get removed -- `list_contested` was folded into `find_concepts(contested_only=True)` in 0.9.30.)

**Discover & ingest**

| Tool | What it does |
|---|---|
| `discover` | Goal-aware cross-source discovery (papers + videos); returns ranked candidates with a calibrated `cost_estimate` |
| `papers` | Search arXiv and ingest a paper set into a topic |
| `learn_topic` | Find + process + synthesize best videos for a topic |
| `search_videos` | Preview best YouTube videos for a topic (no ingest) |
| `process_video_url` | Transcribe + analyze a single video |
| `site_batch` | Ingest direct URLs or a curated website seed set |
| `catch_up` | Refresh watched channels (scan for new videos) |

`site_batch` accepts direct `urls` or a relative `seed_file` inside the library
root. Direct URL lists and TXT seed files stay exact-page by default. JSON seed
files use the same seed parser as the CLI, including `mode: "exact-page"`,
`mode: "shallow-crawl"`, `crawl: true/false`, and `crawl_prefix`; unsupported
mode names return a structured error before any ingest work starts. With
`preview=true`, the tool returns the resolved plan without model checks,
crawling, writes, or spend, and that preview is allowed even when
`DISTILL_MCP_READ_ONLY=1`.

**Synthesize & report**

| Tool | What it does |
|---|---|
| `synthesize` | Corpus synthesis over a topic (`style=...`; `two_pass=true` runs over `claims.jsonl`) |
| `resynthesize_topic` | Regenerate channel, topic, and mixed-source corpus synthesis from existing insights |
| `generate_report` | Deep research report (Gemini + Grok 4-phase pipeline) |

**Query the corpus (read surface)**

| Tool | What it does |
|---|---|
| `list_topics` | Free list of the corpus topics, so tool-only clients can discover what exists before calling a topic-scoped tool |
| `find_insights_summary` | Token-bounded, query-focused brief over a topic's matching insights (cached by corpus revision -- repeats are free; spend-gated in read-only mode) |
| `list_topic_summary` | Free one-paragraph topic orientation for sub-agents choosing where to query |
| `ask` | Answer a question grounded only in a topic's corpus, with cited sources (promotion via --save is CLI-only) |
| `find_insights` | Ranked `(path, preview, score)` matches for a topic + query - paths, not payloads |
| `read_insight` | Read a specific insight artifact (drill-down after `find_insights`) |
| `find_concepts` | Find concept/entity notes in a topic's playbook layer |
| `read_concept` | Read a specific concept/entity note |
| `research_gaps` | Inspect a topic corpus for thin coverage, stale recency, and missing artifacts |
| `concept_history` | List a concept/entity note's `.history` snapshots with per-step change summaries |
| `concept_diff` | Structured diff of a concept note across versions (source/interval/contested deltas + body diff) |

**Watch & ops**

| Tool | What it does |
|---|---|
| `watch_add` / `watch_remove` | Manage your watch list |
| `costs` | Cost history |
| `doctor` | Environment + corpus health diagnostics |

**OKF interop**

| Tool | What it does |
|---|---|
| `okf_export` | Write a read-only OKF v0.1 bundle under `output/`; returns paths and a short preview, not full payloads |
| `okf_validate` | Structural OKF bundle validation (read-only; works in `DISTILL_MCP_READ_ONLY=1`) |

## Resources

| Resource URI | What it exposes |
|---|---|
| `distill://topics` | All topics with channel counts |
| `distill://watchlist` | Watch list with per-channel settings |
| `distill://watch-alerts` | Latest watch alert digest |
| `distill://topics/{topic}/videos` | All videos with URL, duration, analysis mode, and artifact status |
| `distill://topics/{topic}/synthesis` | Topic synthesis |
| `distill://topics/{topic}/corpus` | Mixed-source corpus synthesis |
| `distill://topics/{topic}/sources` | Source inventory and artifact availability |
| `distill://topics/{topic}/diff` | Latest change briefing |
| `distill://topics/{topic}/trends` | Momentum / trend summary |
| `distill://topics/{topic}/channels/{ch}/synthesis` | Channel synthesis |
| `distill://topics/{topic}/channels/{ch}/insights/{n}` | Video insights (1 = newest) |
| `distill://costs` | Cost history |

## Prompts

| Prompt | Workflow |
|---|---|
| `daily_deals` | Catch up + show latest deals from a channel |
| `morning_briefing` | Refresh all channels + summarize what's new using alerts, diffs, and trends |
| `topic_research` | Search + process + synthesize a topic end-to-end |
| `topic_gap_review` | Ask distill what a tracked topic is missing before more ingestion |

## Typical agent patterns

- **Morning briefing agent**: call `morning_briefing` prompt at a fixed time, get a ready-to-read digest
- **Research analyst agent**: use `topic_research` prompt + `generate_report` tool; hand off to a writer agent
- **Continuous monitor**: poll `distill://watch-alerts` on a schedule; escalate on notable changes
- **Gap-driven ingestion**: run `research_gaps` tool before adding new sources; only ingest what's actually missing
