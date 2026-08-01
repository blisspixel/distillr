# Compatibility policy (toward 1.0 and after)

Status: binding policy for freeze-ready covered surfaces. Complements
[`README.md`](README.md) in this directory and SemVer 2.0.0.

## Product names (frozen)

| Surface | Name | Notes |
|---------|------|-------|
| CLI commands | `distill`, `distill-mcp` | Public argv contracts |
| PyPI distribution | `distillr` | Import package remains `distill` |
| GitHub repository | `blisspixel/distillr` | |

The rename window for these names closes at 1.0. Do not introduce a second
public brand without a major-version migration plan.

## What freezes at 1.0

When 1.0.0 ships, the following **covered** snapshots become the frozen public
API for SemVer purposes (status field becomes `frozen` in that release):

- `cli-v1.json` - command tree, options, arguments, defaults, types
- `mcp-v1.json` - tools, resources, templates, prompts, schemas
- `artifacts-v1.json` - modern filename patterns, base frontmatter, provenance
- `config-v1.json` - non-secret DistillConfig fields and env names
- `state-v1.json` - library index and channel state schemas

Breaking changes to those shapes require a **major** version. Additive optional
fields and new commands/tools may ship in **minor** versions. See
[`README.md`](README.md) for the full classification table.

## What does not freeze

- Prompt *bodies* (only `prompt_id` + artifact contract stability)
- Private Python modules and internal helpers
- Presentation formatting, help prose, log wording
- Uncovered contract slices listed in `README.md` until they gain snapshots

## Library corpus compatibility

### Promise

A corpus written by Distill **0.5 or later** must open under Distill **1.0**
without manual rewrite when:

1. Paths remain under the configured library root.
2. Artifact filenames use modern patterns or documented reader-compatibility
   paths recorded in `artifacts-v1.json`.
3. Frontmatter uses known base fields; unknown keys are ignored by readers
   that tolerate extras (see artifact contract).

### Operator recovery

| Situation | Expected behavior |
|-----------|-------------------|
| Legacy short concept slugs | Still readable; migrations via `distill migrate` / doctor when available |
| Missing orientation files | Audit next-actions emit loop-readable repair commands |
| Partial migrate failure | Nonzero exit; partial progress reported; re-run is convergent |
| Corrupt state JSON | Fail closed; quarantine or backup per library state contracts |

### What we do not promise

- Opening corpora from unreleased experimental forks or hand-edited schemas
  outside the contracts.
- Bit-identical regeneration of insights after prompt or model revision
  (content is allowed to improve; contracts must hold).
- Cross-major jumps that skip documented migrations when a future 2.0 renames
  a frozen field (would require explicit major migration notes).

## MCP protocol eras

Distill MCP remains dual-era: protocol **2026-07-28** via `server/discover` and
legacy `initialize` clients on the same stdio binary. Dropping a protocol era
is a major-version decision unless the MCP deprecation window has expired and
a documented migration exists.

## Cost-mode and no-metered semantics

`auto` / `no-metered` / `paid-ok` semantics and fail-closed ambiguous billing
are part of the 1.0 behavioral contract. Widening what counts as no-metered
without proof is a breaking policy change.

## How to change a freeze-ready contract before 1.0

1. Change runtime behavior and tests.
2. `uv run python scripts/public_contracts.py --write`
3. Review the diff in the same PR as the runtime change.
4. Note the decision in `docs/CHANGELOG.md`.
5. Do not regenerate snapshots to silence drift without a product decision.

After 1.0, step 5 becomes a major-version requirement for removals and
narrowings.
