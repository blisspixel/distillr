# MCP 2026-07-28 adoption

Status: phase 1 shipped (0.19.47). Phase 2 gated on SDK v2 hardening evidence.
Owner: MCP surface. Companion backlog: `docs/roadmap.md`, section
"MCP 2026-07-28 compatibility spike".

This document records the compatibility inventory against the final
2026-07-28 Model Context Protocol specification, the decisions it produced,
and the staged plan for adopting the new protocol era fully. The roadmap
called for exactly this checkpoint: "track the final spec as soon as it
lands, then run a focused compatibility spike while the 1.0 MCP surface
remains a candidate."

## What the final spec changes

Verified against the published specification (2026-07-28), not the May
release candidate summary:

- **Stateless core.** The `initialize`/`notifications/initialized` handshake
  and protocol-level sessions are removed. Every request carries its protocol
  version, client capabilities, and optional client identity in
  `_meta` (`io.modelcontextprotocol/*` keys). Servers identify themselves in
  each result's `_meta`.
- **`server/discover` is mandatory.** Servers MUST implement it to advertise
  supported versions, capabilities, and identity. Clients use it for up-front
  version selection and as the backward-compatibility probe on stdio.
- **Server-initiated requests are gone.** Roots/list, sampling, and
  elicitation calls from server to client are replaced by the Multi
  Round-Trip Request pattern: the server returns an `InputRequiredResult`
  and the client retries the original request with responses attached.
- **`subscriptions/listen`** replaces `resources/subscribe`, the HTTP GET
  stream, and list-changed notifications. Request-scoped notifications
  (progress, per-request log messages) still flow on the request's own
  response stream.
- **Results carry `resultType`**, and `tools/list`, `prompts/list`,
  `resources/list`, `resources/read`, and `resources/templates/list` results
  carry required `ttlMs` and `cacheScope` cache metadata. Servers SHOULD
  return tools in a deterministic order so clients can cache listings.
- **Deprecations.** Roots, Sampling, and Logging enter the deprecation
  lifecycle (minimum twelve-month window). HTTP+SSE is formally Deprecated.
  Dynamic Client Registration is deprecated in favor of Client ID Metadata
  Documents.
- **Tasks moved to an official extension** (`io.modelcontextprotocol/tasks`):
  durable task handles, `tasks/get` polling, `tasks/update` for mid-flight
  input, cooperative `tasks/cancel`, per-request capability negotiation.
- **Schema loosening.** Tool `inputSchema`/`outputSchema` accept any JSON
  Schema 2020-12 keywords; `structuredContent` accepts any JSON value.
- **Error codes.** Resource-not-found moved from `-32002` to `-32602`;
  `-32020` to `-32099` is reserved for the specification.

## Distill's exposure inventory

The server is stdio-only, FastMCP-based, pinned to `mcp>=1.27.2,<2`
(1.28.1 in the lock), speaking protocol 2025-11-25 through the SDK.

| Spec change | Exposure | Basis |
|---|---|---|
| Stateless core / handshake removal | None in Distill code; SDK-owned | No `initialize` handling, no protocol-version strings, no session state in `distill/mcp/` |
| `server/discover` | SDK-owned; arrives with the v2 port | No custom lifecycle code |
| Roots / Sampling / Logging deprecation | Zero usage | No `list_roots`, `create_message`, `ctx.info`, or `setLevel` call sites; path confinement and model routing are Distill-local |
| Elicitation and MRTR | Zero protocol usage | `synthesize` uses a hand-rolled `force=true` confirmation returned as data, which works identically in both eras |
| `subscriptions/listen` | None; no subscriptions or list-changed notifications emitted | Tool/resource/prompt sets are static after import-time registration |
| Progress notifications | Used; remains Active and request-scoped in the new era | Four async tools report per-phase progress |
| Cache metadata, `resultType` | SDK-owned envelope fields; arrive with the v2 port | Distill sets no envelopes by hand |
| Deterministic tool order | Already deterministic; now frozen by a regression test | Registration is a fixed module tuple plus in-module definition order |
| JSON Schema 2020-12 | Already the dialect of the contract snapshots | `docs/contracts/mcp-v1.json` |
| HTTP authorization changes | Out of scope | No HTTP transport; single-user local stdio server |

Conclusion: Distill has no dependency on any removed or deprecated protocol
feature. The entire era migration is concentrated in the SDK boundary.

## Phase 0 findings (2026-07-31)

- **The SDK v2 line is stable on PyPI**: `mcp 2.0.0` is the current release
  (preceded by `2.0.0b1`/`2.0.0rc1`), `requires-python >= 3.10`.
- **The port is real, not cosmetic.** Probed against the published wheel:
  `mcp.server.fastmcp` no longer exists; the server API is
  `mcp.server.mcpserver.MCPServer`; protocol constant is `2026-07-28`.
  Fields are snake_case in Python; handler internals are rebuilt.
- **New v2 dependencies**: `mcp-types`, `httpx2`, `opentelemetry-api`,
  `jsonschema`, `pyjwt[crypto]`, `uvicorn`, `sse-starlette`,
  `python-multipart`, and `pywin32` on Windows. Two consequences to verify at
  the port: the no-outbound-analytics stance (OpenTelemetry middleware is
  enabled by default in the SDK; without a configured exporter it must emit
  nothing off-box) and CLI startup cost (the lazy-import discipline from the
  startup cycle applies).
- **No upstream blocker.** `google-genai` 2.7.0 no longer depends on `mcp`;
  the `mcp` package is a direct dependency of Distill only.
- **Dual-era support.** A v2 server answers both the stateless 2026-07-28
  era and legacy `initialize` clients from one endpoint, so the port does
  not drop older hosts.

## Staged plan

### Phase 1 (shipped in 0.19.47, on the v1 SDK)

Spec-aligned improvements that are era-independent:

- Every tool declares complete behavior hints (`readOnlyHint`,
  `destructiveHint`, `idempotentHint`, `openWorldHint`), derived from the
  `write_tool` registry so client-visible hints cannot contradict the
  `DISTILL_MCP_READ_ONLY` refusal boundary. Regression tests enforce the
  alignment, the read-tool profile, and the documented open-world and
  destructive policy.
- `tools/list` order is frozen by a regression test (deterministic listings
  are a client-caching SHOULD in the new spec).
- The server identifies itself with the installed `distillr` version instead
  of the SDK's version.
- Tests no longer reach into private SDK internals (`_tool_manager`); they
  use the public listing API, removing a known breakage point for the port.
- `docs/mcp.md`'s tool count is cross-checked against the runtime registry
  by a test.

### Phase 2: SDK v2 port (dedicated release; the graduation gate)

The `mcp>=1.27.2,<2` bound and its package-metadata regression test exist so
the breaking SDK line cannot drift in. Graduation is a deliberate release:

1. Lift the bound to `mcp>=2,<3`; update the lock and the metadata test.
2. Port `distill/mcp/server.py`: `MCPServer` construction, the telemetry
   interception seam that today overrides `FastMCP.call_tool`, progress
   context, and the guardrail decorators (all transport-independent, all
   re-proven under the existing test files).
3. Verify `server/discover` output: capabilities, identity, `ttlMs` and
   `cacheScope` (long TTL, `private` scope; the listing is static per
   process and the corpus is single-user).
4. Regenerate `docs/contracts/mcp-v1.json` as one reviewed contract change;
   record negotiated protocol versions in the snapshot metadata.
5. Prove the no-analytics stance (no OTel egress without an exporter),
   startup budget, Windows stdio behavior, and dual-era operation against a
   modern and a legacy client.

Trigger discipline: v2.0.0 shipped three days after the spec. The port waits
for at least one v2 patch cycle of ecosystem hardening unless a host
regression forces it earlier; the contract snapshots stay candidates until
this phase completes (the 1.0 readiness dependency).

### Phase 3: Tasks extension (after the port)

Long-running ingest and report tools (`papers`, `site_batch`,
`generate_report`, `synthesize`, `learn_topic`, `catch_up`) are exactly the
workload host timeouts punish, and Distill already owns durable run state,
budgets, resume, and phase telemetry. When the stable SDK exposes the tasks
extension: advertise `io.modelcontextprotocol/tasks`, return task handles
only to clients that declared the capability (spec-required graceful
degradation keeps today's blocking behavior for everyone else), persist the
task registry under `library/.distill/` so handles survive a stdio restart,
and surface `budget_exceeded` and `read_only` refusals as structured task
failures on the existing ledger path. If the SDK does not expose the
extension, this phase holds as a tracked blocked note rather than
hand-rolled protocol methods.

## Decisions

- **MCP Apps: exploration, not scope.** The local dashboard already serves
  the review need; revisit only on a concrete host demand.
- **Streamable HTTP and the authorization stack: out of scope.** Distill is
  a single-user local stdio server; CIMD, RFC 9207, and DCR changes have no
  surface here. The stateless core makes a future HTTP mode cheap if one is
  ever wanted; that is noted, not built.
- **MRTR elicitation: deferred.** The `synthesize` `force=true` confirmation
  is era-independent, loop-safe, and works on hosts without elicitation
  support. Converting it to MRTR adds protocol risk without capability.
- **No pre-stable SDK in production.** The quality gate (coverage, contract
  snapshots, PyPI users) outranks era freshness; v1 servers remain fully
  supported by dual-era clients during the deprecation window.

## Risks

| Risk | Mitigation |
|---|---|
| SDK v2 churn in early patch releases | Phase 2 waits for hardening evidence; spike venv pins exact versions |
| OTel dependency vs no-analytics invariant | Explicit egress verification is a phase 2 acceptance criterion |
| Contract snapshot churn misread as drift | One reviewed change with a changelog entry, per `docs/contracts/README.md` |
| Import-time cost regression from v2 dependencies | Measured against the startup baseline before graduation |
| Host ecosystems moving to 2026-07-28-only | Not credible inside the twelve-month deprecation window; dual-era clients keep v1 servers reachable |
