# Use the editorial workflow as a standalone skill

`perspective-editorial` runs the editorial process in an existing agent host.
Distillr and Retonr are optional. The host supplies research, models, files, and
document tools; the skill supplies the procedure and review criteria. It works
from a private person or company perspective through reading, ideas, angle
selection, outline, draft, full rewrite, critique, revisions, and final delivery.

The canonical [skill](../skills/perspective-editorial/SKILL.md) has one generic
[perspective example](../skills/perspective-editorial/assets/perspective.example.toml).
Copy that example to a private workspace and edit it there. The package does not
contain personal perspectives, writing samples, keys, research, or articles.
Choose what context to share with a cloud host under that host's data rules.

## Choose a package

Build locally from the repository root:

```text
uv run python -m scripts.editorial_skill_distributions --build
```

The `agent-dist/` outputs are self-contained. Using them does not require Python,
this repository, or a Distill installation.
Prebuilt packages are attached to the
[v0.20.0 release](https://github.com/blisspixel/distillr/releases/tag/v0.20.0).

| Artifact | Use |
| --- | --- |
| `perspective-editorial-0.1.0.zip` or `.skill` | The skill folder, including its references, generic profile, and optional Codex display metadata. Use ZIP for hosts that request ZIP. |
| `perspective-editorial-plugin-0.1.0.zip` | Plugin contents at the archive root, with Claude and Codex manifests and behavioral evaluation cases. |
| `perspective-editorial-agent-plugin-0.1.0.zip` | Strict portable Agent Plugins 1.0.0 layout with root `plugin.json` and `skills/`. |
| `perspective-editorial-0.1.0.sha256` | Digests of the four archives. |

The skill version is independent of the Distill Python package version. Nothing
is installed or registered in a personal marketplace by the build command.

## Use it in your host

| Host | Installation surface |
| --- | --- |
| GitHub Copilot | Extract the standalone skill folder into a chosen project's `.github/skills/`, or personal `~/.copilot/skills/`. [GitHub instructions](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-cloud-agent/add-skills) |
| Claude Code | Put the standalone folder in project `.claude/skills/` or personal `~/.claude/skills/`; alternatively use its plugin controls with the compatibility package. [Claude skill locations](https://code.claude.com/docs/en/skills#choose-where-skills-load) |
| Claude Cowork | Enable the skill through Customize in Desktop or account skill settings. Cowork does not read the local Claude Code personal skill folder. [Cowork skill scope](https://code.claude.com/docs/en/skills#use-skills-in-cowork-and-cloud-sessions) |
| Microsoft 365 Copilot Cowork | Open Customize, Plugins, Upload plugin and select the compatibility ZIP. Cowork documents conversion of Claude-compatible packages. Choose the intended sharing scope in the host. Availability depends on account and organization policy. [Microsoft instructions](https://learn.microsoft.com/en-us/microsoft-365/copilot/cowork/cowork-plugins) |
| Codex | Use the standalone skill or the `.codex-plugin` compatibility package through the client's supported installation controls. The package contains optional display metadata and no tool dependencies. |
| Agent Plugins clients | Use the strict portable package according to the client's installation mechanism. The specification defines package structure; discovery and installation remain client-specific. [Agent Plugins specification](https://agent-plugins.org/specification) |

For Microsoft Agents Toolkit conversion, use the compatibility plugin folder:

```text
atk import openplugin --path ./plugins/perspective-editorial --output ./editorial-m365 --privacy-url https://your-company.example/privacy --terms-url https://your-company.example/terms
```

Replace the example URLs with your actual publisher URLs. The toolkit importer
looks for a dot-directory manifest such as `.claude-plugin/plugin.json`; the
strict portable package's root `plugin.json` is a different layout. Conversion
creates an M365 project that still needs its normal packaging and validation.
This repository does not supply a tenant registration or publish anything.
[Microsoft conversion guidance](https://learn.microsoft.com/en-us/microsoft-365/copilot/cowork/cowork-plugin-development)

## Start a task

```text
Use perspective-editorial with my private company perspective. Research this
week's AI news, propose and critique three angles, select the most useful one,
plan the argument, draft about 1,000 words, rewrite it fully, critique and revise
it, and deliver Markdown and Word. External paid calls are disabled.
```

For a person, supply their role, audience, point of view, and authorized style
examples. For a company, supply its audience, position, voice, and restrictions.
The same workflow uses either. Ask for ideas or an outline alone when that is
the desired output; the skill respects that narrower scope.

The default is a substantive second writing pass. If you require a separate
non-Anthropic writer, set `workflow.require_independent_non_anthropic_rewrite`
to `true` or state it in the request. The host needs an actual authorized route
to that writer. A second Claude pass cannot satisfy that requirement. Neither
rewriting nor Retonr establishes that a statistical watermark has been removed.

Current news requires current sources. DOCX requires a real export capability.
The skill records unmet requirements instead of claiming missing research,
independent review, or exports were completed. Process notes stay outside the
clean article, and publication remains a separate user-directed action.

## Budgets and optional integrations

A skill is instructions, so it cannot enforce a weekly dollar limit. Host fees
and credit usage follow the host's controls. External paid calls require an
authorized tool that reserves a maximum cost before each call and maintains a
persistent shared allowance. Unknown billing blocks a no-metered route.

Use [Distill's editorial commands](editorial.md) when you want the implemented
local preference, source capture, shared weekly budget ledger, explicit
OpenRouter routing, and programmatic Markdown/DOCX gates. The standalone profile
is host-neutral: initialize a separate Distill profile and copy the shared
author fields as described in the skill's
[adapter reference](../skills/perspective-editorial/references/integrations.md).
Retonr is optional in both modes. Its inspected CLI checks a supplied candidate;
its internal rewrite service still needs a supported exposed adapter.

## Authoring decisions and validation

Research checked September 9, 2026. The design follows the common Agent Skills
format: a precise activation description, a concise procedure, and references
loaded only for the relevant phase. It omits automatic shell execution, broad
tool permissions, and required MCP servers. Behavioral cases cover the intended
company use, restricted scope, missing research, billing limits, source injection,
missing rewrite/export capabilities, and an unrelated coding request.
These choices apply [Agent Skills authoring guidance](https://agentskills.io/skill-creation/best-practices)
and [Anthropic's skill best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices).

The build verifies the canonical files and generated copies, validates the
portable manifest against the pinned Agent Plugins 1.0.0 schema, rejects linked
or credential-shaped source files, and creates reproducible archives. Tests
extract the standalone skill into an isolated directory and resolve its
references without the Distill runtime. CI checks and builds both the corpus
skill and the standalone editorial package. The release workflow builds and
attaches both sets of archives when a release is published.

Local validation on September 9, 2026 passed 7,231 tests with 95.26% coverage,
lint, formatting, the production type check, and both skill/plugin validators.
Six text-only behavioral probes using GPT-5.6 Luna with Gemini 3.7 Flash review
passed, including a single bounded retry after an empty provider response.
Their recorded inference cost was $0.0381. These probes had no external tools
and do not exercise native skill discovery, actual research, or Word export.

Client layouts and instructions have been checked against their documentation.
These checks do not establish successful installation or model behavior in a
particular Cowork tenant, Claude account, Copilot client, or Codex session.
Account installation and end-to-end host trials remain separate validation.

To change the package, edit `skills/perspective-editorial/` and its matching
`evals/` suite, then regenerate the owned plugin directory:

```text
uv run python -m scripts.editorial_skill_distributions --write
uv run python -m scripts.editorial_skill_distributions --check
uv run python -m scripts.editorial_skill_distributions --build
```
