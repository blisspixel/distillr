# Distill documentation

The full documentation set. The [project README](../README.md) is the overview and quickstart; this page is the map to everything deeper, grouped by what you are trying to do.

## Get started

- [Project README](../README.md) - what distill is, install, and a first run.
- [Usage guide](usage.md) - the getting-started flows for each source type (YouTube, websites, papers, ingest), plus `distill init` setup.

## How-to guides

Task-oriented recipes for a specific goal.

- [Usage guide](usage.md) - discovery, watches, synthesis, reports, briefings, unattended/agent operation, scheduling.
- [Briefing context template](briefing-contexts/TEMPLATE.md) - starting point for `--context-file` prompts.
- [Grok 4.3 migration](migration-grok-4.3.md) - moving off the retired fast tiers.

## Reference

Look-up information: precise, structured, neutral.

- [Usage guide](usage.md) - the full command and flag reference.
- [Outputs](outputs.md) - what every artifact (insights, syntheses, reports, sidecars) contains.
- [MCP server](mcp.md) - tools, resources, and prompts exposed to agents.
- [Public contracts](contracts/) - candidate-v1 artifact, CLI, MCP, and core
  state snapshots plus the compatibility and review policy.
- [Cost model](cost.md) - per-workload cost, examples, and guardrails.

## Explanation

Background and the reasoning behind the design.

- [Architecture](architecture.md) - data flow, the report pipeline, model routing, security hardening.
- [Invariants](invariants.md) - the design charter: what distill is, is not, and the rules that do not bend.
- [Roadmap](roadmap.md) - the area-by-area backlog ([top-level ROADMAP](../ROADMAP.md) is the milestone spine).
- [Design notes](design/) - per-feature design docs (ask loop, entailment tier, decomposition, provider caching, how-we-build).

## Project

- [Contributing](CONTRIBUTING.md) - dev setup, the quality gates, and what is in scope.
- [Security](SECURITY.md) - threat model and how to report a vulnerability.
- [Changelog](CHANGELOG.md) - what shipped, per release.
- [Research](research/) - source sweeps and competitive analysis backing roadmap decisions.
