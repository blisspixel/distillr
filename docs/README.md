# Distill documentation

The full documentation set. The [project README](../README.md) is the overview and quickstart; this page is the map to everything deeper, grouped by what you are trying to do.

## Get started

- [Project README](../README.md) - what distill is, install, and a first run.
- [Install and setup](install.md) - alternate installers, keys, local models, updates.
- [Positioning](positioning.md) - how Distill differs from Deep Research, notebooks, and wiki tools.
- [Usage guide](usage.md) - the getting-started flows for each source type (YouTube, websites, papers, ingest), plus `distill init` setup.

## How-to guides

Task-oriented recipes for a specific goal.

- [Usage guide](usage.md) - discovery, watches, synthesis, reports, briefings, unattended/agent operation, scheduling.
- [Active host-session workers](usage.md#active-host-session-workers) - claim,
  complete, submit, abandon, and safely hand off deferred agent tasks.
- [Agent Skill lifecycle](usage.md#agent-skill-lifecycle) - verify, preview,
  install, update, remove, export, and behavior-test the bundled skill.
- [Distill corpus skill](../skills/distill-corpus/) - agent-side corpus and
  host-worker procedure for compatible coding-agent clients.
- [Agent Skill distribution](design/agent-skill-distribution.md) - native
  Codex, Claude, Grok, Gemini, Antigravity, and claude.ai packaging, release,
  validation, update, and billing contracts.
- [Interoperability standards](interoperability.md) - exact Agent Plugins,
  Agent Skills, and OKF baselines, portable boundaries, and update policy.
- [Briefing context template](briefing-contexts/TEMPLATE.md) - starting point for `--context-file` prompts.
- [Grok 4.6 default migration](migration-grok-4.6.md) - current xAI default,
  pricing, context, and override behavior.
- [Gemini 3.7 Flash migration](migration-gemini-3.7.md) - current optional
  Google-provider default, pricing window, and compatibility behavior.
- [Grok 4.5 default migration](migration-grok-4.5.md) - historical guide for
  the previous default.
- [Grok 4.3 migration](migration-grok-4.3.md) - historical guide for moving
  off the retired fast tiers.

## Reference

Look-up information: precise, structured, neutral.

- [Usage guide](usage.md) - the full command and flag reference.
- [Outputs](outputs.md) - what every artifact (insights, syntheses, reports, sidecars) contains.
- [MCP server](mcp.md) - tools, resources, and prompts exposed to agents.
- [Public contracts](contracts/) - freeze-ready v1 artifact, CLI, core
  configuration, MCP, and core state snapshots plus the compatibility policy.
- [Cost model](cost.md) - per-workload cost, examples, and guardrails.
- [Interoperability standards](interoperability.md) - current portable package
  and knowledge-exchange contracts.

## Explanation

Background and the reasoning behind the design.

- [Architecture](architecture.md) - data flow, the report pipeline, model routing, security hardening.
- [Invariants](invariants.md) - the design charter: what distill is, is not, and the rules that do not bend.
- [Roadmap](roadmap.md) - the area-by-area backlog ([top-level ROADMAP](../ROADMAP.md) is the milestone spine).
- [Performance and language admission](design/performance-and-language-admission.md) - benchmark contract, optimization order, and evidence gates for Rust, Go, Mojo, and free-threaded Python.
- [Performance baseline (0.19.60)](performance/baseline-0.19.60.md) - published offline Windows corpus-scale evidence at 100 / 500 / 1_000 / 10_000.
- [Workflow replay (0.19.63)](performance/workflow-replay-0.19.63.md) - frozen paper, video, site, synthesis, verify, profile, and report paths with Distill-owned timings.
- [Design notes](design/) - per-feature design docs (ask loop, entailment tier, decomposition, provider caching, how-we-build).

## Project

- [Contributing](CONTRIBUTING.md) - dev setup, the quality gates, and what is in scope.
- [Security](SECURITY.md) - threat model and how to report a vulnerability.
- [Changelog](CHANGELOG.md) - what shipped, per release.
- [Research](research/) - source sweeps and competitive analysis backing roadmap decisions, including the [2026-08-20 roadmap review](research/roadmap-review-2026-08-20.md).
