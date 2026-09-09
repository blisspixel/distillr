# Perspective Editorial

A standalone editorial skill for a private person or company perspective.
Version 0.1.0. This is the Claude and Codex compatibility package. Distillr is not required.

Use the host's existing research, writing, file, and Word export tools. The skill
guides reading, ideas, angle selection, outlining, drafting, a whole-article
rewrite, evidence and prose review, revisions, and Markdown or DOCX delivery.
Capability limits remain visible. A skill cannot itself enforce a dollar cap.
External paid calls require an authorized budget-enforcing adapter.

Copy assets/perspective.example.toml from inside the skill to a private workspace
and edit it for the writer or company. Keep real perspectives, examples, API keys,
receipts, and articles outside this package. Cloud hosts follow their own data
and sharing rules. The example does not enable paid calls.

For GitHub Copilot, copy skills/perspective-editorial into .github/skills/ in a
chosen project or ~/.copilot/skills/ for personal use. For Claude Code, copy it
into .claude/skills/ or ~/.claude/skills/. Claude Cowork uses account skills or
plugins, not the local Claude Code personal skill directory.

For Copilot Cowork's plugin upload or Agents Toolkit import, choose the separate
Claude-compatible archive if using the strict portable archive. A root
plugin.json is not the same layout as .claude-plugin/plugin.json. Use the host's
installation controls and review its permissions. Installation is optional.

Start with: Use perspective-editorial and my private perspective to research this
week's AI news, choose a useful angle, draft, rewrite and critique it, then provide
Markdown and Word. External paid calls are disabled.

Read SKILL.md and its conditional references for the exact procedure. Optional
Distillr and Retonr adapters are documented there. This package activates no MCP
servers, hooks, model downloads, credentials, or scheduled tasks.

This directory is generated from the canonical skill. In the source repository,
edit skills/perspective-editorial and run:

    uv run python -m scripts.editorial_skill_distributions --write

Installation guidance and dated interoperability research:
https://github.com/blisspixel/distillr/blob/main/docs/portable-editorial-skill.md
