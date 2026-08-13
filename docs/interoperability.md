# Interoperability standards

Last authoritative review: 2026-08-13.

Distill uses open standards at three different boundaries. Agent Plugins
packages the procedure an agent can load. Model Context Protocol exposes a
controlled runtime surface. Open Knowledge Format packages a read-only
projection of the knowledge that procedure can inspect. None replaces
Distill's native corpus, cost policy, verification gate, or authorization
boundary.

## Current baselines

| Boundary | Baseline | Status | Authoritative source |
|---|---|---|---|
| Portable agent package | Agent Plugins 1.0.0 | Working Draft | [Specification](https://agent-plugins.org/specification) and [manifest schema](https://agent-plugins.org/schemas/1.0.0/plugin.schema.json) |
| Agent procedure | Agent Skills | Current published specification | [Specification](https://agentskills.io/specification) |
| Agent runtime protocol | MCP 2026-07-28 | Current compatibility checkpoint | [Specification](https://modelcontextprotocol.io/specification/2026-07-28) |
| Knowledge exchange | OKF 0.2 | Current specification | [OKF v0.2 specification](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) |

The [Google Cloud launch article](https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing/)
introduced OKF 0.1 on 2026-06-12. It remains useful product context, but it is
not the implementation authority for Distill's current OKF exporter. The v0.2
specification supersedes its `timestamp` and body `# Citations` conventions
with `generated.at` and frontmatter `sources`.

## Agent Plugins boundary

The strict portable release artifact is
`distill-corpus-agent-plugin-<version>.zip`. It contains:

- root `plugin.json` targeting the canonical Agent Plugins 1.0.0 schema;
- `skills/distill-corpus/SKILL.md` plus its bounded references;
- a portable README and Apache-2.0 license.

It intentionally omits root `mcp.json`. Agent Plugins permits a skills-only
package, and installing documentation must not silently activate Distill's
write-capable or spend-capable MCP tools. Operators configure `distill-mcp`
separately with explicit read-only and cost policies.

The historical `distill-corpus-plugin-<version>.zip` artifact and checked-in
`plugins/distill-corpus/` directory are universal compatibility bundles. They
carry the same portable root manifest and exact skill, plus native Codex,
Claude, Gemini, Grok-compatible, and behavioral-evaluation files. Those native
files are convenience surfaces, not additions to the Agent Plugins portable
component model. A client that requests a strict Agent Plugins package should
use the strict artifact.

The distribution gate validates the Agent Skills frontmatter floor, validates
the root manifest against a checked-in copy of the immutable 1.0.0 JSON Schema,
proves the generated copies match the canonical skill, and builds deterministic
archives with SHA-256 checksums. These are structural checks. Trigger quality,
faithfulness, and workflow value remain semantic evaluation concerns.

## MCP boundary

`distill-mcp` uses the MCP SDK v2 line and negotiates protocol 2026-07-28 with
modern clients while preserving the legacy initialize path for older clients.
The public contract snapshot locks tools, resources, templates, prompts,
annotations, server identity, and deterministic discovery order. Read-only
mode and per-call spend caps remain Distill policy, not properties Agent
Plugins or MCP can infer.

The strict Agent Plugins archive deliberately omits `mcp.json`, so installing
the portable skill does not activate this runtime surface. Operators configure
`distill-mcp` separately. The detailed protocol inventory and compatibility
evidence are in
[`design/mcp-2026-07-28-adoption.md`](design/mcp-2026-07-28-adoption.md).

## OKF boundary

`distill export <topic|all> --format okf` writes an OKF 0.2 directory bundle.
The native `library/` remains authoritative and the export remains disposable.
The projection includes, when supported by native evidence:

- bundle-root `index.md` with `okf_version: "0.2"` and progressive disclosure;
- date-grouped, newest-first `log.md` without legacy frontmatter;
- concept documents with parseable YAML frontmatter and non-empty `type`;
- `sources` entries with stable receipt resources;
- `generated: {by, at}` projection metadata;
- `status` and absolute `stale_after` lifecycle fields when known;
- `verified` only when a clean verification sidecar has usable coverage and
  binds to the exact exported artifact digest;
- bounded source receipts and verification receipts for auditability.

The validator follows OKF's permissive consumer rule. Missing optional fields,
unknown types and extensions, and broken links do not invalidate a bundle.
Malformed concept frontmatter, an empty `type`, invalid reserved-file
structure, or a missing `runtime` on `Attested Computation` does invalidate the
relevant structure. Distill does not invent a credibility score because OKF
records objective source signals and leaves trust interpretation to consumers.

Distill does not currently import or merge external OKF bundles. Import is a
separate trust problem because an external bundle may not carry Distill receipt
or verification contracts. Distill also does not implement the runtime receipt,
attester ABI, or caching machinery that OKF 0.2 explicitly defers.

## Version update policy

Standards are configuration and contracts, not evergreen prose. When an
upstream specification changes:

1. Read the normative specification and schema from the authoritative source.
2. Record the review date and exact targeted version here.
3. Compare required fields, fixed locations, reserved filenames, versioning,
   failure behavior, and security requirements against implementation and tests.
4. Update the locked schema fixture only for a published canonical identifier.
   Never download a schema while loading a plugin or running default tests.
5. Preserve backward compatibility or ship a documented migration when an
   upstream change is breaking.
6. Regenerate tracked plugin files and run the complete quality gate.
7. Keep model, provider, client, and pricing claims in their own current-source
   registries. No interoperability standard proves a route is supported or
   free.

Do not implement draft proposals merely because they exist in an issue or
discussion. Adopt a proposal only after it enters the authoritative
specification or Distill explicitly labels it as a non-portable extension.
