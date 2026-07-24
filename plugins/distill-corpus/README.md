# Distill Corpus agent plugin

This is the generated, self-contained distribution of the canonical
`skills/distill-corpus/` Agent Skill for Codex, Claude Code, Grok Build, and
Gemini CLI. Version: `0.19.41`.

Do not edit this directory by hand. Change the canonical skill or the generator,
then run:

```text
uv run python scripts/agent_skill_distributions.py --write
```

Installing this plugin teaches an already active agent how to work with Distill.
It does not grant credentials, select a billing route, or prove that host usage
is included in a subscription.

The generated `evals/` suite is compatible with Claude Code's native plugin
evaluation runner. It is a model-judged behavioral suite, not a deterministic
keyword score and not evidence that another client's router behaves identically.
