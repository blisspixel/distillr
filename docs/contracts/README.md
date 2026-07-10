# Public contract snapshots

These files are the machine-readable candidate for Distill's 1.0 external
contract. They make accidental surface changes visible before 1.0 declares the
contract stable.

Current snapshots:

- `cli-v1.json` records every command path plus its public options, positional
  arguments, requiredness, defaults, cardinality, and validation type.
- `mcp-v1.json` records MCP tool input and output schemas, resource URIs,
  resource-template URIs, and prompt arguments. Its JSON Schema dialect is
  Draft 2020-12.

The snapshots are marked `candidate` because the MCP compatibility checkpoint
scheduled after the 2026-07-28 protocol release must finish before the 1.0
surface can be declared stable. Artifact paths, frontmatter fields, stored
state, and legacy-library migration are also tracked by the 1.0 roadmap and
will receive separate contract coverage.

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
[MCP server schema reference](https://modelcontextprotocol.io/specification/2025-11-25/schema).
These sources were checked on 2026-07-10.

## Review workflow

Check the runtime against the tracked snapshots:

```console
uv run python scripts/public_contracts.py --check
```

After an intentional public change, regenerate both snapshots and review the
diff:

```console
uv run python scripts/public_contracts.py --write
git diff -- docs/contracts/
```

The default test suite runs check mode, so stale or unreviewed contract changes
fail locally and in CI. Snapshot generation is deterministic and reads runtime
registration metadata only. It does not contact providers, fetch sources, or
read secret values.
