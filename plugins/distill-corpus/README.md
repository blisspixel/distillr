# Distill Corpus agent plugin

This is the generated, self-contained distribution of the canonical
`skills/distill-corpus/` Agent Skill. The root `plugin.json` targets the
vendor-neutral Agent Plugins 1.0.0 Working Draft. This
repository distribution is the universal compatibility bundle, so native
manifests are also included for Codex, Claude Code, Grok Build, and Gemini CLI.
Version: `0.19.71`.

The release artifact named
`distill-corpus-agent-plugin-0.19.71.zip` contains only the portable Agent
Plugins core, documentation, and license. Use that artifact when a client asks
for a strict Agent Plugins package. The historical
`distill-corpus-plugin-0.19.71.zip` name remains the universal bundle.

Do not edit this directory by hand. Change the canonical skill or the generator,
then run:

```text
uv run python scripts/agent_skill_distributions.py --write
```

Installing this plugin teaches an already active agent how to work with Distill.
It does not grant credentials, select a billing route, or prove that host usage
is included in a subscription.

The portable package is intentionally skill-only. It does not include a root
`mcp.json`, because installing a documentation skill must not silently activate
Distill's write-capable or spend-capable MCP tools. Configure `distill-mcp`
separately with the desired read-only and cost policy when MCP access is needed.

The generated `evals/` suite is compatible with Claude Code's native plugin
evaluation runner. It is a model-judged behavioral suite, not a deterministic
keyword score and not evidence that another client's router behaves identically.
