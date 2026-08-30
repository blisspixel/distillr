# Roadmap

Distill is an active beta. This page is the concise public direction and the
evidence gate for 1.0. Shipped work belongs in the
[`docs/CHANGELOG.md`](docs/CHANGELOG.md), the area-by-area backlog lives in
[`docs/roadmap.md`](docs/roadmap.md), and implementation decisions live under
[`docs/design/`](docs/design/).

## Product direction

Distill is the persistent, verifiable research-corpus layer for people and
agents. Its human analogue is an exceptional research librarian, literature
analyst, and research desk. It discovers and captures current public sources
and local files, analyzes them through a configured model route, verifies
claims against source receipts, and maintains a plain-Markdown corpus that
remains readable without Distill.

The long-term product is not the largest possible corpus. It is the smallest
trustworthy body of research that preserves what matters in a field: canonical
sources, competing views, evidence, gaps, history, and meaningful changes. The
research-desk doctrine and feature-admission rubric live in
[`docs/design/research-desk-doctrine.md`](docs/design/research-desk-doctrine.md).

The near-term product goals are:

1. Improve corpus trust through current claim generations, derived-origin
   preservation, exact source identity, write-time verification, contradiction
   handling, and durable evidence.
2. Keep fast-moving topics current through goal-aware discovery and recurring
   profiles while distinguishing new documents from meaningful new knowledge.
3. Make bounded source-set ingestion easy to preview, approve, resume, and
   audit, with a future path toward inquiry maps and visible source-selection
   rationale.
4. Preserve the distinct contribution of every source family while compiling
   one cross-source view of the field.
5. Keep local inference genuinely no-metered while failing closed when billing
   status is ambiguous.
6. Finish the evidence needed for a credible 1.0 compatibility commitment.

The native corpus remains the source of truth. MCP, Agent Skills, Agent Plugins,
OKF exports, dashboard views, and future indexes are interfaces or projections
over those files, not alternate databases of record.

## Decision boundaries

Distill uses deterministic rules for facts with ground truth: schema parsing,
URL and path safety, exact receipt checks, cost refusal, action identifiers,
approval classes, and verifier stop conditions. Semantic questions such as
source fit, novelty, quality, faithfulness, rumor likelihood, and contradiction
interpretation belong to model judgment. For irreversible actions, models
return per-criterion verdicts and Python aggregates, records, and gates them.

Do not add keyword, regex, length, similarity, or score thresholds as substitutes
for semantic judgment. The complete rule and remediation ledger are in
[`docs/design/agentic-balance.md`](docs/design/agentic-balance.md) and
[`docs/design/model-judgment-vs-brittle-fallbacks.md`](docs/design/model-judgment-vs-brittle-fallbacks.md).

## Current priorities

| Priority | Outcome | Exit evidence |
|---|---|---|
| Correct active derived evidence | Removed or rewritten assertions do not survive a successful refresh, and corpus-derived answers never become apparent independent evidence | Generation and zero-claim retirement tests, origin-preservation tests, legacy compatibility, and full CI |
| Establish the research-desk baseline | Product work is judged on source selection, redundancy, disagreement, meaningful change, navigation, and stopping rather than source volume | Representative mature, fast-moving, and contested-field fixtures with per-case findings |
| Harden public boundaries | No credential persistence, unsafe paths, partial metadata publication, or silent malformed-input fallback | Focused regression tests, full CI, and release notes |
| Complete performance evidence | Characterize hosted-runner variance and measure install, cold start, export, and live reference journeys | Published, hash-bound receipts and an advisory policy |
| Finish type and parse ratchets | External values are parsed once into strict domain types before core logic sees them | Pyright coverage, boundary tests, and no reduction in branch coverage |
| Improve operator readiness | A representative user can install, preview, ingest, audit, and recover without hidden state or unclear spend | Cross-platform journey evidence, accessibility checks, and professional docs |
| Preserve contract readiness | Covered CLI, MCP, artifact, configuration, and state snapshots remain stable | Drift-gated snapshots and the published compatibility policy |

Feature work and hardening releases remain interleaved. A hardening release adds
no product surface unless a fix requires a narrow contract correction. Every
release clears the same quality and supply-chain gates.

## Competitive landscape (August 2026)

Plain Markdown and agent-readable files are now common. Distill should not try
to win as a generic wiki editor, memory layer, graph UI, or hosted notebook.
Its differentiated work is the acquisition and trust pipeline: goal-aware
multi-source discovery, source-specific capture, receipt-bound verification,
contradiction surfacing, and a portable corpus that compounds across runs.

The supporting primary-source review, competitor table, and positioning
implications live in
[`docs/research/roadmap-review-2026-08-20.md`](docs/research/roadmap-review-2026-08-20.md).
Product-facing comparisons live in
[`docs/positioning.md`](docs/positioning.md).

## Milestones at a glance

- **0.1 through 0.19 shipped.** Distill now covers eight source types,
  verification, synthesis, audit, cited questions, profiles, no-metered routing,
  MCP 2026-07-28 compatibility, Agent Skills, Agent Plugins packaging, and OKF
  v0.2 export. Per-release details are in the
  [`changelog`](docs/CHANGELOG.md).
- **Current hardening cycle.** Close bugs at persistence, process, network,
  billing, and contract boundaries. Keep `main` releasable and publish small,
  independently verified releases.
- **1.0 readiness.** Finish the evidence gates below. Version 1.0 is a
  compatibility promise, not a feature-count target or calendar date.

The dependency-ordered operational plan is
[`docs/design/path-to-1.0.md`](docs/design/path-to-1.0.md). The longer version
architecture is
[`docs/design/version-architecture.md`](docs/design/version-architecture.md).

## 1.0.0 - Stability commitment + quality bar

Distill can release 1.0 when every required promise is supported by durable
evidence. Covered interfaces are freeze-ready today, but the complete release
gate is not yet closed.

| Gate | Status | Evidence or remaining work |
|---|---|---|
| Covered contract snapshots and compatibility policy | Complete | [`docs/contracts/COMPATIBILITY.md`](docs/contracts/COMPATIBILITY.md) and drift-gated snapshots |
| Branch coverage at or above 95 percent | Complete | Blocking Linux test matrix with branch coverage |
| Ruff, Pyright, import contracts, Bandit, pip-audit, build, and supported Python matrix | Complete | Blocking CI on `main` |
| Cross-platform deterministic correctness | Complete | Linux, macOS, and Windows receipts with matching deterministic results |
| Comparable hosted-runner history | Complete | Five paired Linux and macOS runs in the [`0.19.70 history`](docs/performance/comparable-history-0.19.70.md) |
| Install, artifact-size, cold-start, and export evidence | Partial | Expand the cross-platform user-experience workflow and publish receipts |
| Live paper, video, and site journeys | Partial | Publish release evidence with hardware, model, tokens, cost, verification, retry, resume, and no-op metadata |
| Strict typing and parse-at-boundary ratchets | Partial | Continue package coverage without weakening current gates |
| Operator presentation and accessibility | Partial | Record onboarding, finish assistive-technology review, and keep docs current |
| Freeze-time security receipt | Pending | Run the final adversarial review with no open validated medium-or-higher finding |

Timing from public hosted runners remains advisory. Correctness, evidence
integrity, security properties, and contract drift are blocking. The performance
policy and raw receipts are published in
[`docs/performance/comparable-history-0.19.70.md`](docs/performance/comparable-history-0.19.70.md).

## Target package layout (1.0)

The current package boundaries are the reference shape. Large modules continue
to decompose behind stable CLI, MCP, library, and file contracts. A package
reorganization is not itself a 1.0 goal, and no native-language component is
admitted without a measured whole-workflow benefit and a maintained Python
fallback. See [`docs/architecture.md`](docs/architecture.md),
[`docs/design/logic-decomposition.md`](docs/design/logic-decomposition.md), and
[`docs/design/performance-and-language-admission.md`](docs/design/performance-and-language-admission.md).

## Security posture

Distill is a single-user local CLI and MCP server that consumes untrusted public
content and model APIs. Its primary assets are provider credentials and corpus
integrity. Its practical attack surface is URL fetching, local path handling,
untrusted content crossing model boundaries, child processes, durable state,
MCP capabilities, and supply-chain inputs.

Security work therefore focuses on SSRF and redirect safety, bounded reads and
writes, credential-free persistence and diagnostics, prompt-injection framing,
HTML sanitization, trusted executable resolution, child-environment scrubbing,
atomic publication, spend refusal, and exact receipt checks. The maintained
threat model and disclosure process are in
[`docs/SECURITY.md`](docs/SECURITY.md).

## Engineering standards: adopted, adapted, declined

Adopted and blocking:

- A committed `uv.lock` and frozen CI environments.
- Ruff checks and formatting, Pyright, import-linter, Bandit, pip-audit, build
  verification, and tests across Python 3.12 through 3.14.
- At least 95 percent branch coverage, with the floor ratcheted upward only.
- SHA-pinned GitHub Actions, release provenance, and SBOM generation.
- Atomic durable writes and strict JSON at publication boundaries.
- Property, contract, mutation, fault-injection, and frozen-replay tests where
  they provide evidence for deterministic behavior.

Adapted:

- Performance timing is advisory until host variance and production-shaped
  evidence justify a stronger promise.
- Model evaluation gates semantic behavior; deterministic tests gate structure,
  safety, and exact controlled fixtures.
- Derived indexes may exist only as disposable accelerators under `.distill/`.

Declined:

- Quality gates based on surface-form heuristics.
- Live network or provider timing as a pull-request gate.
- Uncalibrated providers in the default route ladder.
- A native rewrite without a measured, bounded seam.

Contributor setup and exact local commands are in
[`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md).

## Looking beyond 1.0

Post-1.0 product work can turn the stable corpus into a stronger research desk:
inquiry maps in discovery preview, source-role and expected-contribution
judgments, portfolio-level selection, one contribution envelope across source
families, a field model over all current evidence, meaningful change briefs,
selective refresh, and reading paths through existing query and report
surfaces.

Enabling work can include plan-quota adapters after billing proof, richer route
orchestration after eval graduation, optional MCP Tasks support after official
SDK support, semantic alias proposals, additional scientific discovery sources,
and explicitly versioned plugin boundaries. These remain behind the same cost,
verification, research-value, and compatibility rules.

## Intentionally not in scope

- A proprietary editor, mobile app, hosted SaaS, or multi-user auth layer.
- A database of record or general-purpose vector-store product.
- Real-time collaboration or sync. Plain files and existing sync tools own it.
- Paywall, login-wall, or anti-bot circumvention.
- An autonomous scheduler or unbounded agent fleet inside Distill.
- A mode that lowers corpus fidelity to reduce cost.
- Uncalibrated cloud providers enabled by default.

These exclusions can be revisited only when the constraint behind them changes.

## Full backlog

The detailed backlog, partial work, and area ownership live in
[`docs/roadmap.md`](docs/roadmap.md). Shipped items move to the
[`changelog`](docs/CHANGELOG.md) so the roadmap stays focused on forward work.
