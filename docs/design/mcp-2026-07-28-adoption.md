# MCP 2026-07-28 adoption

Status: phase 1 shipped (0.19.47); phase 2, the SDK v2 port, shipped
(0.19.48) with the evidence below. Phase 3 (Tasks extension) is staged.
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

### Phase 2: SDK v2 port (shipped in 0.19.48)

The `mcp>=1.27.2,<2` bound and its package-metadata regression test existed
so the breaking SDK line could not drift in; this release is the deliberate
graduation. What shipped, with the acceptance evidence gathered on the
development machine (Windows, 2026-07-31):

1. Dependency lifted to `mcp>=2.0.0,<3` (2.0.0 in the lock); the metadata
   regression test now guards the v2 line and reserves the same review for
   a future v3.
2. `distill/mcp/server.py` ported: `DistillMCPServer(MCPServer)` replaces
   the FastMCP subclass, the telemetry seam overrides the v2 `call_tool`
   (the dispatcher routes protocol calls through the public method, same as
   v1), the server version is a first-class constructor argument (the v1
   private-attribute seam is gone), and deliberate cache hints mark the
   static listings and `server/discover` fresh for one hour at `private`
   scope while `resources/read` deliberately stays uncached so corpus reads
   are always fresh. All guardrails (read-only, spend cap, allowlist) and
   the write-tool registry re-proven under the existing test files.
3. Dual-era operation proven over real Windows stdio against the installed
   `distill-mcp` binary: a modern v2 client negotiates protocol 2026-07-28
   through `server/discover` (serverInfo, capabilities, `ttlMs` 3600000 /
   `cacheScope` private on `tools/list`), and a genuine v1.28.1 client
   completes the legacy `initialize` handshake at 2025-11-25. Same 27
   tools, same behavior, both eras.
4. `docs/contracts/mcp-v1.json` is byte-identical across the SDK swap: the
   snake_case v2 Python API serializes to the same camelCase wire shapes,
   so the public contract provably did not move.
5. No-analytics stance verified structurally: the v2 dependency is
   `opentelemetry-api` only; no OTel SDK or exporter is installed, so the
   tracer is a no-op and nothing can leave the machine. CLI startup is
   unaffected (the CLI never imports the SDK; same-machine comparison
   against the released 0.19.47 wheel showed no regression).

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
failures on the existing ledger path. Status after the v2 port (rechecked
2026-07-31 against `mcp` 2.0.0): the core SDK ships the general
`mcp.server.extension.Extension` seam (identifier plus contributed tools,
resources, and methods) but still not the official
`io.modelcontextprotocol/tasks` package or bindings. Adopt the official
implementation when it publishes; implementing that identifier on the
Extension seam directly is the fallback once the extension package
stabilizes, and bare protocol methods outside that seam remain off the table.

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
| SDK v2 churn in early patch releases | The lock pins 2.0.0; upgrades land as reviewed PRs through the full gate, and the dual-era test evidence reruns on every release |
| OTel dependency vs no-analytics invariant | Verified at the port: api-only dependency, no SDK or exporter installed, no-op tracer. Re-verify if any dependency ever pulls in the OTel SDK |
| Contract snapshot churn misread as drift | Resolved: the snapshot was byte-identical across the SDK swap; any future change stays one reviewed decision per `docs/contracts/README.md` |
| Import-time cost regression from v2 dependencies | Measured at the port: CLI unaffected (never imports the SDK); server import cost is paid once by the long-running process |
| Legacy hosts on v1 client SDKs | Proven working: a real 1.28.1 client completes initialize against the ported binary over stdio |
