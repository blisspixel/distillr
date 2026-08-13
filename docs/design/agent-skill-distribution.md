# Agent Skill distribution

Status: implemented

## Decision

Distill maintains one hand-edited Agent Skill at
[`skills/distill-corpus/`](../../skills/distill-corpus/). A deterministic
generator copies that exact skill into one self-contained plugin that current
Agent Plugins v1, Codex, Claude Code, Grok Build, and Gemini CLI surfaces can
consume. The same generator builds the ZIP-shaped artifacts used by claude.ai
and other Agent Skills clients, plus an integrity-manifested package resource
used by the `distill skill` lifecycle.

The skill teaches an already active agent how to read and curate a Distill
corpus and how to complete a bounded `distill worker` task. It is not an LLM
provider adapter. Installing it does not give Distill access to a host's
credentials, launch that host, or establish how the host invocation is billed.

## What the ecosystem patterns taught us

The useful pattern in
[`devinilabs/claude-watch`](https://github.com/devinilabs/claude-watch) is a
small canonical skill plus a release-built `.skill` archive. Its legacy Codex
metadata is not the current Codex plugin contract, so Distill uses the current
`.codex-plugin/plugin.json` shape instead of copying that detail.

[`vercel-labs/skills`](https://github.com/vercel-labs/skills) demonstrates the
value of one canonical skill, explicit agent targets, update support, and
symlinks where the local platform supports them. Distill remains installable
through that community CLI, but does not depend on it. Native vendor install
paths and inspectable release archives remain first-class.

[`obra/superpowers`](https://github.com/obra/superpowers) demonstrates that a
skill library can span Claude, Codex, Gemini, and other harnesses while keeping
behavioral tests and native manifests. Its release history also shows why
cached plugin copies need completeness checks. Distill checks the exact file
inventory, content, archive roots, and checksums rather than trusting a copy
step.

The common denominator is the
[`SKILL.md` Agent Skills format](https://agentskills.io/specification). Vendor
packaging is a thin distribution layer around it:

- [Agent Plugins v1](https://agent-plugins.org/specification) defines the
  portable package contract: required root `plugin.json`, fixed `skills/`, and
  optional root `mcp.json`.
- [Codex uses `.codex-plugin/plugin.json` and a `skills/` directory](https://learn.chatgpt.com/docs/build-plugins).
- [Claude Code plugins use `.claude-plugin/plugin.json` and the same `skills/`
  directory](https://code.claude.com/docs/en/discover-plugins), with a
  [repository marketplace](https://code.claude.com/docs/en/plugin-marketplaces)
  at `.claude-plugin/marketplace.json`.
- [Grok Build reads Claude Code plugins and marketplaces](https://docs.x.ai/build/features/skills-plugins-marketplaces),
  so it does not need a forked skill.
- [Gemini CLI extensions use `gemini-extension.json`](https://github.com/google-gemini/gemini-cli/blob/main/docs/extensions/reference.md)
  and also discover `skills/`. A root manifest makes the repository an
  updateable `distillr` extension, while the native skill installer can still
  [install the canonical subdirectory directly](https://geminicli.com/docs/cli/using-agent-skills/).
- Gemini CLI and
  [Antigravity](https://codelabs.developers.google.com/getting-started-google-antigravity)
  both recognize workspace `.agents/skills/`, which is the most portable
  project-scoped location.

## Distribution matrix

| Surface | Preferred unit | Install or load path | Validation |
|---|---|---|---|
| Agent Plugins v1 clients | Portable plugin | Install `plugins/distill-corpus` or the matching plugin archive | Root manifest schema, fixed skill discovery, and drift check |
| Codex CLI and app | Repository plugin | Add `blisspixel/distillr` as marketplace `distillr`, then install `distill-corpus@distillr` | Codex plugin validator plus drift check |
| Claude Code | Repository plugin | Add marketplace `blisspixel/distillr`, then install `distill-corpus@distillr` | `claude plugin validate --strict` |
| Grok Build | Claude-compatible plugin | Use the repository marketplace or load `plugins/distill-corpus` with `--plugin-dir` | Same generated plugin and skill checks |
| Gemini CLI | Repository extension | `gemini extensions install https://github.com/blisspixel/distillr`; use `gemini extensions update distillr` later | Root and universal-plugin manifests pass `gemini extensions validate` |
| Antigravity | Canonical skill | Place the folder at `.agents/skills/distill-corpus`, or use a compatible Agent Skills installer | Skill validator and exact-copy check |
| claude.ai | Versioned ZIP | Upload `distill-corpus-<version>.zip` from the matching GitHub release | ZIP inventory, fixed root, checksum |
| Generic Agent Skills clients | Canonical skill or `.skill` | Install the folder or matching release archive | Agent Skills validator and checksum |
| Any installed Distill CLI | Verified direct fallback | Preview with `distill skill install --client <client>`, then apply with `--yes` | Runtime manifest, exact inventory, safe replacement, post-write verification |

The repository plugin deliberately contains the portable Agent Plugins v1 root
manifest, three client compatibility manifests, and one copied
`skills/distill-corpus/` tree. Each client ignores the manifests it does not
own. This produces one cacheable plugin instead of separate copies that can
disagree.

The portable package is intentionally skill-only and omits root `mcp.json`.
Installing a corpus procedure must not silently activate Distill's write-capable
or spend-capable MCP tools. Operators configure `distill-mcp` separately with
the desired read-only mode, allowlist, and spend caps.

## Source and drift invariants

Only `skills/distill-corpus/` is edited by hand as skill content. Behavioral
cases are authored under `evals/distill-corpus/`. Everything under
`plugins/distill-corpus/`, the bundled
`distill/resources/agent-skills/` tree, the two marketplace manifests, and the
root Gemini extension manifest are generated by
[`scripts/agent_skill_distributions.py`](../../scripts/agent_skill_distributions.py).

The generator enforces structural ground truth only:

- the package version is strict semantic versioning and is copied into every
  versioned manifest;
- root `plugin.json` declares the Agent Plugins v1.0.0 schema and uses only its
  closed set of portable metadata fields;
- skill inputs are bounded regular files, not links or credential-shaped files;
- the generated plugin has an exact file inventory and byte-for-byte skill and
  eval copy;
- the Python package copy has a versioned manifest with per-file byte counts,
  hashes, and a stable tree digest;
- ZIP entries are sorted, use a fixed timestamp and mode, and have exactly one
  top-level directory;
- release artifacts receive SHA-256 checksums;
- a changed canonical skill, project version, manifest template, missing file,
  or unexpected cached file fails `--check` until `--write` is run.

These checks do not judge whether the prose is semantically good. Trigger fit,
faithfulness, and workflow quality remain model-evaluated concerns. The
source-controlled Claude plugin suite provides five positive or adversarial
workflow cases and one unrelated-task negative case. Its graders judge semantic
criteria instead of keyword presence. Cross-client behavior still needs
client-specific evaluation before a public marketplace submission. Structural
validation is necessary, but it is not a substitute for that eval gate.

## Installed lifecycle

The wheel exposes four read or mutation surfaces:

```bash
distill skill doctor
distill skill install --client codex --scope project
distill skill uninstall --client codex --scope project
distill skill export --output distill-corpus.skill
```

`doctor` verifies every packaged byte before reporting native CLI presence and
the state of each documented direct-discovery target. It does not invoke those
clients, inspect credentials, or infer billing from login. Native package
managers remain preferred where they preserve provenance and updates. The
direct path is the safe portable fallback.

Install and uninstall are preview-first. `--yes` applies the displayed action.
The direct lifecycle adopts only a byte-identical unmanaged copy, updates or
removes only a clean Distill-managed copy, refuses links and hardlinks, rechecks
state under a lock, stages writes, swaps directories with rollback, and verifies
the final inventory. Export is deterministic and emits a SHA-256 sidecar. A
native and a direct installation should not be enabled for the same client
because duplicate skill names can make discovery ambiguous.

## Behavioral evaluation

Canonical cases live in `evals/distill-corpus/` and are copied into the plugin.
They cover normal corpus reading, preview-first curation, bounded worker
handoff, billing ambiguity, local inference with current sources, and a negative
trigger for unrelated code work. The cases grant no tools. LLM graders evaluate
semantic behavior per criterion, while Python checks only schema, inventory,
positive and negative coverage, and the presence of model graders.

On Claude Code versions and accounts that have the native runner enabled:

```bash
claude plugin eval plugins/distill-corpus \
  --ablation with-without --runs 3 --max-cost-usd 5 --no-scaffold
```

This is an explicit, paid-capable eval rather than an offline CI gate. Review
the with-versus-without delta, individual grader explanations, and variance
across runs. Do not replace those judgments with a keyword or length score.
The command is currently an Anthropic early-access feature. If the client
reports that the eval is unavailable, record a release block rather than
bypassing its feature gate or substituting deterministic semantic scoring.
A human maintainer may explicitly waive that vendor-gated run for one release;
the changelog must record the waiver and the validation evidence used instead.

## Build and release

Contributor workflow:

```bash
uv run python scripts/agent_skill_distributions.py --write
uv run python scripts/agent_skill_distributions.py --check
```

Plugin caches are versioned. Any released skill or manifest change must ship
with a project version bump, followed by `--write`; reusing a version can leave
Codex, Claude, Grok, or Gemini on a valid but stale cached plugin. The tag and
package-version release gate already refuses a mismatched release.

Release workflow:

```bash
uv run python scripts/agent_skill_distributions.py --build --output agent-dist
```

That produces:

- `distill-corpus-<version>.skill`, an Agent Skills archive;
- `distill-corpus-<version>.zip`, the claude.ai upload shape;
- `distill-corpus-plugin-<version>.zip`, the self-contained multi-client plugin;
- `distill-agent-distributions-<version>.sha256`, checksums for all three.

Skill archives contain `distill-corpus/SKILL.md` at their root. The plugin
archive contains `distill-corpus/` followed by the portable root manifest, the
three compatibility manifests, the single skill tree, behavioral evals, its
README, and its license. The wheel carries the small verified skill resource
required by `distill skill`; standalone agent artifacts stay in `agent-dist/`
and are not published as Python distributions.

## Billing and fallback truth

The skill files and deterministic validation are local artifacts. The model
that follows the skill is a separate cost boundary.

- Ollama and LM Studio are the only implemented routes Distill can classify as
  no-metered by topology.
- An active Codex, Claude Code, Grok Build, Gemini, or Antigravity session can
  complete a worker task, but Distill records the result as `host-managed` and
  external cost unavailable.
- A subscription may include that activity, consume a quota or credit pool, or
  route through an API key. The skill cannot prove which occurred.
- `DISTILL_COST_MODE=no-metered` therefore does not accept host-managed worker
  results as proven no-metered.
- Direct CLI adapters remain a separate route. Each must prove current vendor
  support, included-plan authentication, scratch confinement, native usage,
  and eval quality before it enters a no-metered route ladder.

This separation still gives users the useful fleet fallback today. A person can
hand one bounded task to whichever already active host has capacity, abandon a
failed claim, and let another host take it, without pretending that the manual
handoff is an automatic or free provider.
