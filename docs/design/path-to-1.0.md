# Path to 1.0 (and beyond)

Status: operational plan. Anchored to [`version-architecture.md`](version-architecture.md)
and the 1.0 section of [`../../ROADMAP.md`](../../ROADMAP.md). Revalidated
2026-08-20 against code, roadmap, release evidence, and the live GitHub state at
`distillr==0.19.65`; published performance evidence is the 0.19.50 scale-100
receipt, the 0.19.60 Windows 100 / 500 / 1_000 / 10_000 matrix, and frozen
workflow replay through 0.19.63 (paper / video / site / synthesis / verify /
profile / report). Write-path fault injection for empty analysis, empty
transcripts, PDF fetch failure, yt-dlp failure, and malformed structured JSON
shipped in 0.19.64.

## The honest answer

**1.0 is not missing a feature checklist.** The product promise of 0.x is
already true: goal-aware discovery, eight source types, verify-gated writes,
synthesis, audit next-actions, OKF, profiles, no-metered routing, MCP dual-era
2026-07-28, Agent Skills, and a 95% branch-coverage CI bar on Linux/macOS/Windows.

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
Published: Windows scale 100 (0.19.50 and 0.19.60), 500, 1_000, and 10_000
at n=20, plus CLI `--version` process start, and Windows frozen workflow
replay (paper / video / site / synthesis / numeric verify / profile / report)
at n=20, under [`../performance/`](../performance/). A manual, non-blocking
GitHub Actions workflow now runs the exact matrix and replay on Linux and macOS,
validates correctness and integrity, and uploads raw receipts with a run-bound
manifest. Still open for the 1.0 bar:

1. Run and publish comparable Linux and macOS receipts from the same merge
   commit, seed, fixtures, and n=20 profile, then build enough history to
   characterize hosted-runner variance.
2. Live reference journeys as *release evidence*, not PR gates (20-paper run,
   50-video catch-up, site-batch) with hardware / provider / cost metadata.

### C. Quality bar completeness (mostly done; residual ratchets)

| Gate | Status |
|------|--------|
| Branch coverage >=95% | Met (0.19.56: 6,582 passed at 95.04%; floor remains 95%) |
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

## Dependency-ordered plan (no calendar fiction)

```
Phase 0  Document truth (this file) + name freeze decision
    |
Phase 1  Contract + library compatibility policy
    |    Graduate covered snapshots under that policy
    |
Phase 2  Performance baseline v1 (offline scale matrix + cold CLI start)
    |    Keep live journeys as scheduled release evidence
    |
Phase 3  Close residual quality ratchets (Pyright strict packages,
    |    parse boundaries, verification-depth cadence)
    |
Phase 4  Operator presentation + a11y + freeze-time security receipt
    |
Phase 5  1.0.0 release: freeze covered contracts, ship migration note,
         publish baseline, tag under SemVer major
    |
Beyond   2.0: plan-quota routes, orchestration, stewardship loops
         3.0: recipes, corpus merge, plugin ecosystem
```

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

- Live plan-quota adapters only when vendor evidence exists.
- Route orchestration scored by `distill eval` cost per accepted change.
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

| Phase | Status | Evidence |
|-------|--------|----------|
| 0 Plan + name freeze | done | this document; names frozen in `COMPATIBILITY.md` |
| 1 Compatibility policy + contract freeze-ready | done | `docs/contracts/COMPATIBILITY.md`; snapshots `status: freeze-ready` |
| 2 Performance baseline v1 | partial | Windows scale-100/500/1_000/10_000 n=20 plus workflow replay n=20 published; manual Linux/macOS collection and validation workflow added; publishing those receipts and live journeys remain |
| 3 Quality ratchets | partial | 95.04% cov, llm strict, file-level strict ~76% of modules; write-path fault injection for empty analysis / transcripts / network / yt-dlp (0.19.64) |
| 4 Presentation / a11y / security receipt | partial | prior harden cycles |
| 5 Ship 1.0.0 | blocked on 2-4 completeness | |
