# Public contract snapshots

These files are the machine-readable **freeze-ready** external contract for
Distill's 1.0 stability commitment. They make accidental surface changes
visible before 1.0 declares the contract frozen.

Current snapshots:

- `artifacts-v1.json` records modern artifact filename patterns, reader
  compatibility paths, standard base-frontmatter fields, field types,
  provenance fields, and representative persisted frontmatter serialization.
- `cli-v1.json` records every command path plus its public options, positional
  arguments, requiredness, defaults, cardinality, and validation type.
- `config-v1.json` records core `DistillConfig` fields, declared non-secret
  defaults, environment-variable names and environment-loader policy,
  cost-policy normalization, and configuration-owned library path examples.
- `mcp-v1.json` records MCP tool input and output schemas, resource URIs,
  resource-template URIs, and prompt arguments. Its JSON Schema dialect is
  Draft 2020-12.
- `state-v1.json` records Draft 2020-12 schemas for normalized core
  `library.json` and per-channel `state.json` documents plus representative
  accepted empty, legacy, and explicit-field inputs and their normalized forms.

## Status

| Field | Meaning |
|-------|---------|
| `freeze-ready` | Covered surface is complete enough to freeze at 1.0 under [`COMPATIBILITY.md`](COMPATIBILITY.md). Drift still requires reviewed PR + changelog. |
| `frozen` | Used only after the 1.0.0 release tags these snapshots as SemVer public API. |

The MCP 2026-07-28 compatibility checkpoint that previously blocked freeze
readiness is **complete** (0.19.47 inventory + 0.19.48 SDK v2 port; snapshot
byte-identical across the swap). See
[`docs/design/mcp-2026-07-28-adoption.md`](../design/mcp-2026-07-28-adoption.md)
and [`docs/design/path-to-1.0.md`](../design/path-to-1.0.md).

Still **out of the freeze set** until separate slices land (additive after 1.0
is allowed under the compatibility policy):

- Router/provider configuration and direct runtime environment controls beyond
  `config-v1.json`
- Additional state documents and file locations outside configuration path
  helpers
- Artifact-specific frontmatter schemas and value semantics beyond the base set
- Caller-specific reader and writer extension integration
- Full legacy-library migration automation beyond the compatibility promise

## Compatibility policy

Until 1.0, every snapshot change must be intentional, reviewed with its runtime
change, and recorded in the changelog. A changed snapshot is evidence of a
contract decision, not permission to accept drift automatically.

Starting with 1.0:

- Removing or renaming a command, option, argument, tool, resource, template,
  prompt, input field, or output field is breaking and requires a major
  release. Output fields remain part of the response contract even when their
  schema does not mark them as required.
- Making an accepted input narrower, adding a required input, changing command
  dispatch behavior, or changing a default in a way that changes established
  behavior is breaking.
- Adding an optional input or a new command or MCP primitive is additive and
  may ship in a minor release.
- Adding an optional output field is additive when the existing schema permits
  additional fields and existing fields retain their meaning.
- Changing an artifact's canonical filename pattern, suffix, extension,
  frontmatter field type, requiredness, or established value meaning is
  breaking. Removing an accepted legacy reader path is also breaking.
- Adding an optional frontmatter field is additive when existing readers
  tolerate unknown fields and all established fields retain their meaning.
- Removing or renaming a persisted state field, narrowing its accepted type,
  changing an established normalization default, or adding a field that old
  documents cannot omit is breaking.
- Adding a persisted state field is additive only when older documents still
  normalize successfully and the new field has a stable default.
- Removing or renaming a snapshotted `DistillConfig` setting or environment
  variable, narrowing its type or accepted normalized input, changing an
  established default, or changing a stable configured path shape is breaking.
- Adding an optional setting is additive when its default preserves existing
  behavior and no established environment variable changes meaning.
- Fixing behavior without changing the public shape may ship in a patch
  release.
- Help text, descriptions, presentation formatting, private Python imports,
  and prompt bodies are not frozen by these snapshots. Documented behavior and
  generated artifact contracts still apply independently.

This classification follows [Semantic Versioning 2.0.0](https://semver.org/),
which requires a declared public API and reserves incompatible API changes for
major releases. JSON schemas follow the
[JSON Schema Draft 2020-12 reference](https://json-schema.org/draft/2020-12),
and MCP schemas follow the current
[MCP server schema reference](https://modelcontextprotocol.io/specification/2026-07-28/schema);
the server answers both the 2026-07-28 era and legacy initialize clients, and
the recorded wire shapes are identical in both. These sources were checked on
2026-07-31.

Library corpus promises live in [`COMPATIBILITY.md`](COMPATIBILITY.md).

## Review workflow

Check the runtime against the tracked snapshots:

```console
uv run python scripts/public_contracts.py --check
```

After an intentional public change, regenerate all snapshots and review the
diff:

```console
uv run python scripts/public_contracts.py --write
git diff -- docs/contracts/
```

The default test suite runs check mode, so stale or unreviewed contract changes
fail locally and in CI. Check mode also rejects tracked `*-v1.json` files that
are no longer generated, so removing a contract from the generator cannot
silently disable enforcement. Snapshot generation is deterministic and reads
runtime registration, TypedDict and core settings metadata plus pure artifact,
state-normalization, configuration-validation, default-path, and path-layout
builders. It does not construct settings sources, contact providers, fetch
sources, or read secret values.
