# Path to 1.0 (and beyond)

Status: operational plan. Anchored to [`version-architecture.md`](version-architecture.md)
and the 1.0 section of [`../../ROADMAP.md`](../../ROADMAP.md). Revalidated
against code, roadmap, release evidence, and the live GitHub state at
`distillr==0.19.74`. The active release boundary is `0.19.75`.
Published performance evidence now includes five paired
Linux/macOS runs with preserved receipts and an active advisory policy, the
0.19.60 Windows 100 / 500 / 1_000 / 10_000 matrix, and Windows frozen workflow
replay through 0.19.63 (paper / video / site / synthesis / verify / profile /
report). Write-path fault injection for empty analysis, empty transcripts, PDF
fetch failure, yt-dlp failure, and malformed structured JSON shipped in 0.19.64.

## The honest answer

**1.0 is not missing a feature checklist.** The product promise of 0.x is
already true: goal-aware discovery, eight source types, verify-gated writes,
synthesis, audit next-actions, OKF, profiles, no-metered routing, MCP dual-era
2026-07-28, Agent Skills, optional metered OpenRouter routing, and a 95 percent
branch-coverage CI bar on Linux, macOS, and Windows.

**1.0 is a stability commitment:** external systems can depend on Distill
without expecting churn. That is a *promise with evidence*, not a version
number you stamp when tired of 0.x.

Shipping `1.0.0` before those evidence gates clear would be a false promise.
Getting to 1.0 *as fast as honesty allows* means clearing the remaining gates
in dependency order and refusing to invent calendar freezes or brittle quality
scorers to look "done."

## What is NOT stopping 1.0

These are real product directions, but they are **explicitly post-1.0** in the
version architecture. Chasing them delays 1.0 without strengthening the
stability promise:

| Item | Why it is not a 1.0 gate |
|------|--------------------------|
| Plan-quota CLI graduation (Codex, Claude Code, etc.) | Vendor-gated auth proof; 2.0-era |
| Route orchestration strategies (ensemble, critic) | 2.0 spine after freeze |
| MCP Tasks extension | Official SDK package not shipped; long-run UX, not contract freeze |
| New source adapters (OpenAlex, PubMed, etc.) | Feature breadth; after freeze |
| Research program, portfolio selection, and field-model compiler | Product-quality evolution; evaluate now, ship after stable contracts |
| Email/Slack notifications, multi-topic channels | Parked / maybe-later |
| Database of record, SaaS, multi-user auth | Intentionally never |

## What actually blocks 1.0

From the ROADMAP 1.0 readiness gate (paraphrased and prioritized by dependency):

### A. Contract freeze of covered surfaces (complete)

MCP 2026-07-28 checkpoint **shipped** (0.19.47 inventory + 0.19.48 SDK v2).
Covered snapshots exist and drift-gate CI. The compatibility and library corpus
migration policy is published in [`COMPATIBILITY.md`](../contracts/COMPATIBILITY.md), covered
snapshots are marked `freeze-ready`, and the project names are fixed as CLI
`distill` plus PyPI package `distillr`. Additional contract slices, including
more router environment settings and artifact-specific schemas, may expand
additively under that policy and do not block 1.0.

### B. Published performance baseline (partial harness, no freeze yet)

`benchmarks/corpus_scale/` exists for deterministic offline scale evidence.
Published: the [`0.19.66 Linux/macOS matrix and replay`](../performance/cross-platform-0.19.66.md),
Windows scale 100 (0.19.50 and 0.19.60), 500, 1_000, and 10_000 at n=20,
plus CLI `--version` process start, and Windows frozen workflow replay (paper /
video / site / synthesis / numeric verify / profile / report) at n=20, under
[`../performance/`](../performance/). The manual, non-blocking GitHub Actions
workflow validates correctness and integrity and uploads raw receipts with a
run-bound manifest. Still open for the 1.0 bar:

1. Add cross-platform clean-install, artifact-size, cold-start, and export
   measurements.
2. Live reference journeys as *release evidence*, not PR gates (20-paper run,
   50-video catch-up, site-batch) with hardware / provider / cost metadata.

The comparable-run gate is complete. The published
[`0.19.70 history`](../performance/comparable-history-0.19.70.md) revalidates
five paired Linux/macOS workflows and derives an active advisory policy. Timing
and resource signals remain non-blocking; correctness and evidence integrity
remain blocking.

### C. Quality bar completeness (mostly done; residual ratchets)

| Gate | Status |
|------|--------|
| Branch coverage >=95% | Met; the blocking full-suite floor remains 95 percent and current evidence is retained in CI |
| Ruff / bandit / pip-audit / import-linter | Met, CI-blocking |
| Python 3.12-3.14 + OS smoke | Met |
| Golden structural offline gate | Met; do not extend to live model scoring |
| Mutation testing / deal contracts | Partial (core packages); cadence not PR-blocking |
| Pyright full package | Blocking basic diagnostics; **central strict only `distill/llm`** (file-level strict is widespread but not complete) |
| Parse-don't-validate at every boundary | Partial; write paths now refuse empty analysis bodies; more surfaces remain |

### D. Operator and presentation readiness (evidence, not code volume)

1. Representative onboarding journey (init -> preview -> ingest -> audit)
   recorded as release evidence.
2. Accessibility: CLI no-color / 40-column / exit taxonomy; web landmarks and
   keyboard (partial cycles already shipped; AT review incomplete).
3. Security: continuous adversarial passes; no open validated MEDIUM+ findings
   at freeze (current posture is strong; needs a freeze-time audit receipt).
4. Screenshots / short recordings for README presentation pass (deliberately
   deferred; still open).

## Dependency-ordered release plan

The authoritative version table and update protocol live in
[`ROADMAP.md`](../../ROADMAP.md#versioned-execution-sequence). No row carries a
date or duration estimate.

1. `0.19.74`: shipped provider accountability, OpenRouter, and Python 3.15
   readiness evidence.
2. `0.19.75`: correct active claim generations and derived-origin
   preservation.
3. `0.19.76`: publish the expert-authored research-desk evaluation baseline.
4. `0.19.77`: publish operator, accessibility, install, export, cold-start, and
   live reference-journey evidence.
5. `0.19.78`: close remaining strict-boundary, deterministic-core, and
   freeze-time security evidence.
6. `1.0.0rc1`: freeze and exercise the exact compatibility promise without new
   product surface.
7. `1.0.0`: publish only when the release-candidate evidence remains valid on
   the final commit.

Post-1.0 work retains its existing dependency order: research program,
evidence portfolio, field model, meaningful refresh, navigation, bounded
stewardship loops, qualified provider breadth, recipes, merge, and plugins.

## Success criteria for 1.0.0

All must be true and linked from the release notes:

1. Covered public contracts marked freeze-ready with SemVer policy.
2. `docs/contracts/COMPATIBILITY.md` (or successor) documents library migration.
3. `docs/performance/baseline-*.md` publishes offline scale matrix + cold start.
4. CI quality bar green on Linux 3.12-3.14, macOS smoke, Windows smoke.
5. Freeze-time security scan receipt (bandit + pip-audit + adversarial notes).
6. Onboarding + presentation assets land in docs/README as evidence, not as a
   new product surface.
7. Explicit **name freeze**: CLI `distill`, package `distillr`.
8. Changelog entry that states what is frozen and what remains additive.

## What "beyond 1.0" means immediately after freeze

Do not reopen contracts casually. Next work is **2.0-shaped**:

- Establish the research-desk evaluation baseline before changing discovery or
  synthesis behavior.
- Build inquiry maps, source-role and contribution handoffs, evidence-portfolio
  selection, one field model, meaningful refresh, and reading paths in that
  dependency order.
- Live plan-quota adapters only when vendor evidence exists.
- Route orchestration judged by `distill eval` faithfulness and research-desk
  fixtures, with cost per accepted material change recorded separately.
- Stewardship loops remaining external; Distill stays the loopable primitive.
- Optional MCP Tasks when the official extension package ships.

## Decisions recorded for this plan

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Name | Keep `distill` / `distillr` | Already public on PyPI and in agent ecosystems; rename cost > benefit |
| Contract status | Freeze covered v1 snapshots after policy docs | MCP era checkpoint is complete; remaining slices are additive |
| 1.0 timing | Evidence-gated, not calendar-gated | Matches ROADMAP; "today" means max honest progress, not a fake 1.0.0 |
| Live perf in CI | Never as PR gate | Runner variance; keep offline advisory until history exists |
| Plan-quota in 1.0 | No | Vendor-gated; would make 1.0 hostage to third parties |

## Execution status (updated as work lands)

| Version | Status | Evidence or next proof |
|---|---|---|
| `0.19.74` | shipped | OpenRouter and Python 3.15 advisory implementation, docs, tests, budgeted live provider validation, aligned artifacts, and release publication |
| `0.19.75` | active | generation retirement, zero-claim behavior, derived-origin preservation, migration coverage |
| `0.19.76` | next | expert-authored research-desk fixtures and published baseline results |
| `0.19.77` | queued | clean-install, artifact-size, cold-start, export, onboarding, accessibility, recovery, and live-journey receipts |
| `0.19.78` | queued | remaining strict typing, parse boundaries, deterministic-core evidence, and freeze-time security receipt |
| `1.0.0rc1` | gated | all covered contracts frozen and exercised; only release blockers admitted |
| `1.0.0` | gated | every readiness gate closed and release-candidate evidence valid on the final commit |
