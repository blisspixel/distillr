# Distill Corpus agent plugin

This is the generated, self-contained distribution of the canonical
`skills/distill-corpus/` Agent Skill. The root `plugin.json` targets the
vendor-neutral Agent Plugins v1 specification. Compatibility manifests are also
included for Codex, Claude Code, Grok Build, and Gemini CLI. Version: `0.19.51`.

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
