# Path to 1.0 (and beyond)

Status: operational plan. Anchored to [`version-architecture.md`](version-architecture.md)
and the 1.0 section of [`../../ROADMAP.md`](../../ROADMAP.md). Revalidated
for the `0.20.7` research-trust maintenance boundary. Releases `0.20.1`
through `0.20.6` shipped billing, routing, typing, and capture fixes;
`0.20.7` shipped claim generations, derived origin, and issues #40 through #57.
The 2026-10-18 readiness review found no open GitHub issues or pull requests;
the remaining release gates below still require evidence. Closing the maintenance
queue does not close those gates.
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
combined-coverage CI bar with branch measurement on Linux, macOS, and Windows.

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

### B. Published performance baseline (comparable history complete; journey gaps)

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

The [0.20.7 maintenance record](../research/maintenance-2026-10-17.md)
adds a real Windows CPU paper journey, interrupt/recovery and zero-cost no-op
receipts, a CPU optional-verifier install measurement, and frozen Linux
container/browser smoke. These receipts narrow the remaining work; they do
not establish native Linux/macOS end-to-end journeys or the larger batches.
Use proven on-device inference for new local $0 evidence. A metered route
requires separate cost authority; an unavailable platform remains an explicit
gap rather than a simulated live pass.

The comparable-run gate is complete. The published
[`0.19.70 history`](../performance/comparable-history-0.19.70.md) revalidates
five paired Linux/macOS workflows and derives an active advisory policy. Timing
and resource signals remain non-blocking; correctness and evidence integrity
remain blocking.

### C. Quality bar completeness (mostly done; residual ratchets)

| Gate | Status |
|------|--------|
| Combined coverage >=95%, branch measurement enabled | Met: 95.40% on the frozen follow-up tree; the blocking mechanism is unchanged |
| Branch-only coverage >=95% | Remaining 1.0 target: the same receipt records 91.67%; add meaningful missing-path tests and a separate branch-only assertion without lowering the combined floor or widening exclusions |
| Ruff / bandit / pip-audit / import-linter | Met, CI-blocking; dependency audit covers the frozen core environment, with optional advisory limits recorded separately |
| Python 3.12-3.15 + OS smoke | Met on the exact 0.20.7 release commit; [CI](https://github.com/blisspixel/distillr/actions/runs/39102971516) |
| Golden structural offline gate | Met; do not extend to live model scoring |
| Mutation testing / deal contracts | Partial (core packages); cadence not PR-blocking |
| Pyright full package | Zero diagnostics with warnings blocking; eight centrally strict packages plus file-level strictness. Remaining package promotion stays open |
| Parse-don't-validate at every boundary | Partial; write paths now refuse empty analysis bodies; more surfaces remain |

### D. Operator and presentation readiness (evidence, not code volume)

1. Representative onboarding journey (init -> preview -> ingest -> audit)
   recorded as release evidence.
2. Accessibility: CLI no-color / 40-column / exit taxonomy; web landmarks and
   keyboard (partial cycles already shipped; AT review incomplete).
3. Security: continuous adversarial passes; no open validated MEDIUM+ findings
   at freeze. The frozen core audit passed. `0.20.8` moved the optional
   entailment extra to `transformers>=5.17,<6`, recorded that Distillr does not
   call the unpatched loaders, and audited that extra from its locked export.
   The 2026-10-24 default and export audits are clean. The freeze-time review
   remains `0.20.11`. The October 17
   [path assessment](../research/optional-dependency-review-2026-10-17.md)
   stays the historical record.
4. README house-theme screenshots and real-browser keyboard/automated
   accessibility receipts shipped in 0.20.7. Complete representative onboarding
   and assistive-technology evidence; automated checks do not establish screen
   reader usability.

### E. Research-quality baseline (next)

`0.20.9` is the next product outcome because the unit suite and one successful local
paper journey cannot establish dependable research quality. Follow the
[doctrine's evaluation design](research-desk-doctrine.md#evaluation-like-a-research-desk)
through the existing evaluation and pipeline seams:

1. Freeze representative mature, fast-moving, and contested-field cases with
   dated receipts, explicit questions, essential and redundant candidates,
   source roles, qualifications, unresolved gaps, and expert-reviewed expected
   judgments. Draft fixtures can be prepared locally; expert review remains
   a separate recorded requirement.
2. Measure retrieval against the source pool separately from synthesis over a
   fixed captured corpus. This distinguishes missing evidence from poor use of
   available evidence. Record source-selection reasons and inaccessible or
   omitted material.
3. Include the correction/disagreement episode and its withdrawal, zero-claim,
   invalid-extraction/refusal, and no-meaningful-change variants. Record current
   behavior honestly, including failures in selective revision that belong to
   the post-1.0 program.
4. Collect per-criterion semantic verdicts, calibrate judges against recorded
   human review, and report disagreements and uncertainty. Python validates
   schemas and aggregates verdicts; keyword matching or one aggregate score
   cannot establish faithfulness or research quality. Keep live semantic runs
   separate from deterministic CI and record model, prompt, source, cost, and
   code identities.
5. Publish the baseline and disposition every failure: a defect in a covered
   promise blocks freeze until fixed and re-evaluated; a planned capability is
   documented with its limitation and existing roadmap owner. Passing this
   gate requires a reviewed, reproducible assessment and honest dispositions,
   not implementation of the entire post-1.0 research desk.

Do not change discovery or synthesis defaults before this baseline exists.

## Remaining work in release order

| Order | Release | Work and exit evidence |
|---|---|---|
| 1 | `0.20.9` | Publish the reviewed retrieval/synthesis baseline above and classify failures against the covered compatibility promise |
| 2 | `0.20.10` | Fill missing native-platform install, size, startup, export, onboarding, recovery, assistive-technology, and representative batch receipts; reuse existing Windows and container evidence with its stated limits |
| 3 | `0.20.11` | Inventory remaining strict-package and parse-boundary gaps, close them with focused checks, raise branch-only coverage to >=95%, add its explicit assertion, and publish deterministic-core fault-injection/verification and freeze-time security evidence |
| 4 | `1.0.0rc1` | Rehearse supported installs, upgrades, migrations, CLI/MCP contracts, corpus recovery, and built-artifact behavior on the frozen candidate; accept only release-blocking fixes |
| 5 | `1.0.0` | Revalidate every required receipt against the final commit and publish matching artifacts, provenance, SBOM, compatibility statement, and release notes |

Keep the scope in these rows. New adapters, external worker routes, ensembles,
and the broader field-model/selective-refresh system retain their existing
post-1.0 owners. A newly discovered correctness or security defect still needs
an explicit disposition; a green historical CI run cannot waive it.

## Dependency-ordered release plan

The authoritative version table and update protocol live in
[`ROADMAP.md`](../../ROADMAP.md#versioned-execution-sequence). No row carries a
date or duration estimate.

1. `0.19.74`: shipped provider accountability, optional OpenRouter, and Python
   3.15 readiness evidence.
2. `0.20.0`: shipped the requested editorial consumer and standalone skill.
3. `0.20.1`: shipped local-inference billing proof, interoperability, and API pacing.
4. `0.20.2`: shipped frontier model registration and fallback workflow budgets.
5. `0.20.3`: shipped strict typing expansion, modular boundaries, and coverage.
6. `0.20.4`: shipped site-capture receipts and dependency security maintenance.
7. `0.20.5`: shipped current API, routed billing, SDK, and dependency security fixes.
8. `0.20.6`: shipped no-metered setup, pinned previews and capture repairs.
9. `0.20.7`: shipped active claim generations, derived origin and maintenance fixes.
10. `0.20.8`: shipped the trust-material refresh, optional Transformers
    advisory floors, and snapshot-bound MCP evidence identity.
11. `0.20.9`: publish the research-desk evaluation baseline before changing defaults.
12. `0.20.10`: publish operator, accessibility, install, export, cold-start, and live
    reference-journey evidence.
13. `0.20.11`: close strict-boundary, deterministic-core, and security evidence gaps.
14. `1.0.0rc1`: freeze and exercise covered contracts without new product surface.
15. `1.0.0`: publish only while every gate remains true on the final commit.

## Success criteria for 1.0.0

All must be true and linked from the release notes:

1. Covered public contracts marked freeze-ready with SemVer policy.
2. `docs/contracts/COMPATIBILITY.md` (or successor) documents library migration.
3. `docs/performance/baseline-*.md` publishes offline scale matrix + cold start.
4. CI quality bar green on Linux 3.12-3.15, macOS smoke, Windows smoke.
5. Freeze-time security scan receipt (bandit + pip-audit + adversarial notes).
6. Onboarding + presentation assets land in docs/README as evidence, not as a
   new product surface.
7. Explicit **name freeze**: CLI `distill`, package `distillr`.
8. Changelog entry that states what is frozen and what remains additive.
9. Published expert-reviewed retrieval/synthesis baseline with calibrated
   judgments, correction/disagreement results, and dispositions for failures.
10. Separate branch-only >=95% assertion, remaining strict-package/boundary
    ratchets, and deterministic-core verification evidence are complete.

## What "beyond 1.0" means immediately after freeze

Do not reopen contracts casually. Next work is **2.0-shaped**:

- Use the pre-freeze research-desk baseline to evaluate subsequent discovery
  and synthesis changes; expand cases as capabilities grow.
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
| `0.20.0` | released | budgeted editorial workflow, Markdown/DOCX sample, optional portable skill, tests and release artifacts |
| `0.20.1` | shipped | local-inference billing proof, MCP and Agent Plugins compatibility, bounded API pacing, release evidence |
| `0.20.2` | shipped | frontier model registration, OpenRouter DeepSeek routing and defaults, global workflow budget fallbacks, tests and release evidence |
| `0.20.3` | shipped | strict Pyright expansion, modular boundaries, coverage, and agent instructions |
| `0.20.4` | shipped | typed site-capture receipts, bounded visits, readiness, and dependency security |
| `0.20.5` | shipped | current model and pricing audit, SDK compatibility, routed billing regressions, dependency security, full release gates |
| `0.20.6` | shipped | no-metered setup, pinned previews and capture repairs |
| `0.20.7` | shipped | generation retirement, zero-claim behavior, derived origin, discovery and freshness uncertainty, and issues #40 through #57 |
| `0.20.8` | shipped | emSign and optional Transformers floors, clean default and entailment-export audits, snapshot-bound MCP evidence identity, and the [published release](https://github.com/blisspixel/distillr/releases/tag/v0.20.8) |
| `0.20.9` | queued | expert-authored research-desk fixtures and published baseline results |
| `0.20.10` | queued | clean-install, artifact-size, cold-start, export, onboarding, accessibility, recovery, and live-journey receipts |
| `0.20.11` | queued | remaining strict typing, parse boundaries, deterministic-core evidence, and freeze-time security receipt |
| `1.0.0rc1` | gated | all covered contracts frozen and exercised; only release blockers admitted |
| `1.0.0` | gated | every readiness gate closed and release-candidate evidence valid on the final commit |
